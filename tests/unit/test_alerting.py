"""Unit tests for Phase 2 alerting module."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from maudesignal.alerting.checker import AlertChecker
from maudesignal.alerting.notifiers.console import ConsoleNotifier
from maudesignal.alerting.notifiers.slack import SlackNotifier
from maudesignal.alerting.rules import (
    VALID_DELIVERY,
    VALID_METRICS,
    validate_delivery,
    validate_metric,
)
from maudesignal.storage.database import Database

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.db")


def _seed_extraction(
    db: Database,
    *,
    maude_report_id: str,
    product_code: str,
    skill_name: str,
    output: dict,
    ts: datetime | None = None,
) -> None:
    """Insert a normalized event + extraction row for testing."""
    db.upsert_normalized_event(
        maude_report_id=maude_report_id,
        product_code=product_code,
        event_type="malfunction",
        event_date=None,
        narrative="Test narrative.",
        mfr_narrative=None,
        manufacturer=None,
        brand_name=None,
    )
    eid = str(uuid.uuid4())
    db.insert_extraction(
        extraction_id=eid,
        maude_report_id=maude_report_id,
        skill_name=skill_name,
        skill_version="1.0.0",
        model_used="mock",
        output_payload=output,
        confidence_score=output.get("confidence_score", 0.8),
        requires_review=False,
    )
    if ts is not None:
        from sqlalchemy import update

        from maudesignal.storage.models import ExtractionRecord

        with db._session() as session:
            session.execute(
                update(ExtractionRecord)
                .where(ExtractionRecord.extraction_id == eid)
                .values(extraction_ts=ts)
            )
            session.commit()


# ---------------------------------------------------------------------------
# validate_metric / validate_delivery
# ---------------------------------------------------------------------------


class TestValidators:
    def test_valid_metrics_accepted(self) -> None:
        for m in VALID_METRICS:
            validate_metric(m)  # must not raise

    def test_invalid_metric_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown metric"):
            validate_metric("not_a_real_metric")

    def test_valid_delivery_accepted(self) -> None:
        for d in VALID_DELIVERY:
            validate_delivery(d)  # must not raise

    def test_invalid_delivery_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown delivery"):
            validate_delivery("fax")


# ---------------------------------------------------------------------------
# ConsoleNotifier
# ---------------------------------------------------------------------------


class TestConsoleNotifier:
    def test_send_returns_true(self, capsys) -> None:
        notifier = ConsoleNotifier()
        result = notifier.send(subject="Test Alert", body="Some body text.")
        assert result is True
        captured = capsys.readouterr()
        assert "Test Alert" in captured.out

    def test_channel_is_console(self) -> None:
        assert ConsoleNotifier().channel == "console"


# ---------------------------------------------------------------------------
# SlackNotifier
# ---------------------------------------------------------------------------


class TestSlackNotifier:
    def test_missing_url_raises(self) -> None:
        with pytest.raises(ValueError, match="webhook_url"):
            SlackNotifier(webhook_url="")

    def test_channel_is_slack(self) -> None:
        n = SlackNotifier(webhook_url="https://hooks.slack.com/fake")
        assert n.channel == "slack"

    def test_send_success(self) -> None:
        n = SlackNotifier(webhook_url="https://hooks.slack.com/fake")
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        with patch("maudesignal.alerting.notifiers.slack.httpx.post", return_value=mock_resp):
            result = n.send(subject="Alert", body="Body text.")
        assert result is True

    def test_send_failure_returns_false(self) -> None:
        n = SlackNotifier(webhook_url="https://hooks.slack.com/fake")
        with patch(
            "maudesignal.alerting.notifiers.slack.httpx.post",
            side_effect=Exception("connection refused"),
        ):
            result = n.send(subject="Alert", body="Body.")
        assert result is False


# ---------------------------------------------------------------------------
# Database: alert_rules
# ---------------------------------------------------------------------------


class TestAlertRulesDB:
    def test_insert_and_list(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        db.insert_alert_rule(
            rule_id="r001",
            product_code="QIH",
            metric="ai_rate",
            threshold=0.5,
            window_days=30,
            delivery="console",
            delivery_config=None,
            description="Test rule",
        )
        rules = db.list_alert_rules(active_only=True)
        assert len(rules) == 1
        assert rules[0].rule_id == "r001"
        assert rules[0].metric == "ai_rate"

    def test_deactivate_rule(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        db.insert_alert_rule(
            rule_id="r002",
            product_code=None,
            metric="new_reports",
            threshold=10.0,
            window_days=7,
            delivery="console",
            delivery_config=None,
            description=None,
        )
        assert db.deactivate_alert_rule("r002") is True
        assert len(db.list_alert_rules(active_only=True)) == 0

    def test_deactivate_nonexistent_returns_false(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        assert db.deactivate_alert_rule("ghost") is False


# ---------------------------------------------------------------------------
# Database: alert_events
# ---------------------------------------------------------------------------


class TestAlertEventsDB:
    def test_insert_and_list(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        db.insert_alert_event(
            event_id="e001",
            rule_id="r001",
            product_code="QIH",
            metric="ai_rate",
            metric_value=0.75,
            threshold=0.5,
            message="AI rate exceeded threshold.",
            delivered=True,
        )
        events = db.list_alert_events()
        assert len(events) == 1
        assert events[0].delivered is True
        assert events[0].metric_value == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Database: metric queries
# ---------------------------------------------------------------------------


class TestMetricQueries:
    def test_count_extractions_in_window(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        now = datetime.now(UTC)
        # 2 recent extractions
        for i in range(2):
            _seed_extraction(
                db,
                maude_report_id=f"R00{i}",
                product_code="QIH",
                skill_name="maude-narrative-extractor",
                output={"ai_related_flag": True, "confidence_score": 0.8},
                ts=now - timedelta(hours=1),
            )
        # 1 old extraction outside window
        _seed_extraction(
            db,
            maude_report_id="R999",
            product_code="QIH",
            skill_name="maude-narrative-extractor",
            output={"ai_related_flag": True, "confidence_score": 0.8},
            ts=now - timedelta(days=60),
        )
        count = db.count_extractions_in_window(
            product_code="QIH",
            skill_name="maude-narrative-extractor",
            since=now - timedelta(days=30),
        )
        assert count == 2

    def test_ai_rate_in_window(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        now = datetime.now(UTC)
        since = now - timedelta(days=30)
        # 3 total: 2 AI, 1 not AI
        for i, ai in enumerate([True, True, False]):
            _seed_extraction(
                db,
                maude_report_id=f"AR{i}",
                product_code="QIH",
                skill_name="maude-narrative-extractor",
                output={"ai_related_flag": ai, "confidence_score": 0.8},
                ts=now - timedelta(hours=1),
            )
        rate = db.ai_rate_in_window(product_code="QIH", since=since)
        assert rate == pytest.approx(2 / 3)

    def test_ai_rate_empty_returns_zero(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        rate = db.ai_rate_in_window(product_code="QIH", since=datetime.now(UTC) - timedelta(days=7))
        assert rate == 0.0


# ---------------------------------------------------------------------------
# AlertChecker
# ---------------------------------------------------------------------------


class TestAlertChecker:
    def test_no_rules_returns_zero(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        checker = AlertChecker(db)
        result = checker.check_all()
        assert result.rules_evaluated == 0
        assert result.alerts_fired == 0

    def test_rule_fires_when_threshold_exceeded(self, tmp_path: Path, capsys) -> None:
        db = _make_db(tmp_path)
        now = datetime.now(UTC)
        # Seed 5 extractions in the window
        for i in range(5):
            _seed_extraction(
                db,
                maude_report_id=f"CHK{i}",
                product_code="QIH",
                skill_name="maude-narrative-extractor",
                output={"ai_related_flag": True, "confidence_score": 0.8},
                ts=now - timedelta(hours=1),
            )
        # Add rule: fire when new_reports >= 3 in 30 days
        db.insert_alert_rule(
            rule_id="chk01",
            product_code="QIH",
            metric="new_reports",
            threshold=3.0,
            window_days=30,
            delivery="console",
            delivery_config=None,
            description=None,
        )
        checker = AlertChecker(db)
        result = checker.check_all()
        assert result.alerts_fired == 1
        assert result.alerts_delivered == 1
        assert len(db.list_alert_events()) == 1

    def test_rule_does_not_fire_below_threshold(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        now = datetime.now(UTC)
        _seed_extraction(
            db,
            maude_report_id="BLW1",
            product_code="QIH",
            skill_name="maude-narrative-extractor",
            output={"ai_related_flag": True, "confidence_score": 0.8},
            ts=now - timedelta(hours=1),
        )
        db.insert_alert_rule(
            rule_id="blw01",
            product_code="QIH",
            metric="new_reports",
            threshold=10.0,
            window_days=30,
            delivery="console",
            delivery_config=None,
            description=None,
        )
        result = AlertChecker(db).check_all()
        assert result.alerts_fired == 0

    def test_inactive_rule_not_evaluated(self, tmp_path: Path) -> None:
        db = _make_db(tmp_path)
        db.insert_alert_rule(
            rule_id="inact01",
            product_code=None,
            metric="new_reports",
            threshold=0.0,
            window_days=30,
            delivery="console",
            delivery_config=None,
            description=None,
        )
        db.deactivate_alert_rule("inact01")
        result = AlertChecker(db).check_all()
        assert result.rules_evaluated == 0
