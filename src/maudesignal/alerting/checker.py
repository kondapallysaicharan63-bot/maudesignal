"""Alert checker — evaluates all active rules against the DB (Phase 2)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from maudesignal.alerting.notifiers.base import Notifier
from maudesignal.alerting.notifiers.console import ConsoleNotifier
from maudesignal.alerting.notifiers.email_notifier import EmailNotifier
from maudesignal.alerting.notifiers.slack import SlackNotifier
from maudesignal.common.logging import get_logger
from maudesignal.storage.database import Database
from maudesignal.storage.models import AlertRuleRecord

logger = get_logger(__name__)


@dataclass(frozen=True)
class AlertCheckResult:
    """Summary of one alert-check run."""

    rules_evaluated: int
    alerts_fired: int
    alerts_delivered: int
    details: list[dict[str, Any]]


class AlertChecker:
    """Evaluate all active alert rules against live DB metrics."""

    def __init__(self, db: Database) -> None:
        """Initialize with a Database instance."""
        self._db = db

    def check_all(self, product_code: str | None = None) -> AlertCheckResult:
        """Evaluate every active rule (optionally scoped to a product code).

        Fires notifications for rules whose metric exceeds their threshold.
        Returns a summary of what fired.
        """
        rules = self._db.list_alert_rules(active_only=True)
        if product_code:
            rules = [r for r in rules if r.product_code in (product_code, None)]

        fired = 0
        delivered = 0
        details: list[dict[str, Any]] = []

        for rule in rules:
            result = self._evaluate(rule)
            if result is None:
                continue
            metric_value, message = result
            notifier = _build_notifier(rule)
            ok = notifier.send(subject=f"MaudeSignal alert: {rule.metric}", body=message)
            self._db.insert_alert_event(
                event_id=str(uuid.uuid4()),
                rule_id=rule.rule_id,
                product_code=rule.product_code,
                metric=rule.metric,
                metric_value=metric_value,
                threshold=rule.threshold,
                message=message,
                delivered=ok,
            )
            fired += 1
            if ok:
                delivered += 1
            details.append(
                {
                    "rule_id": rule.rule_id,
                    "metric": rule.metric,
                    "product_code": rule.product_code,
                    "metric_value": metric_value,
                    "threshold": rule.threshold,
                    "delivered": ok,
                }
            )
            logger.info(
                "alert_fired",
                rule_id=rule.rule_id,
                metric=rule.metric,
                value=metric_value,
                threshold=rule.threshold,
            )

        return AlertCheckResult(
            rules_evaluated=len(rules),
            alerts_fired=fired,
            alerts_delivered=delivered,
            details=details,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate(self, rule: AlertRuleRecord) -> tuple[float, str] | None:
        """Return (metric_value, message) if rule fires, else None."""
        since = datetime.now(UTC) - timedelta(days=rule.window_days)
        pc = rule.product_code

        if rule.metric == "new_reports":
            count = self._db.count_extractions_in_window(
                product_code=pc,
                skill_name="maude-narrative-extractor",
                since=since,
            )
            value = float(count)
            if value >= rule.threshold:
                return value, _format_message(rule, value, f"{int(value)} new reports")

        elif rule.metric == "ai_rate":
            rate = self._db.ai_rate_in_window(product_code=pc, since=since)
            if rate >= rule.threshold:
                pct = f"{rate * 100:.1f}%"
                return rate, _format_message(rule, rate, f"AI-related rate {pct}")

        elif rule.metric == "severity_rate":
            rate = self._db.severity_rate_in_window(product_code=pc, since=since)
            if rate >= rule.threshold:
                pct = f"{rate * 100:.1f}%"
                return rate, _format_message(rule, rate, f"Serious/death rate {pct}")

        elif rule.metric == "new_failure_mode":
            new_modes = self._detect_new_failure_modes(pc, since)
            if new_modes:
                value = float(len(new_modes))
                modes_str = ", ".join(new_modes)
                return value, _format_message(rule, value, f"New failure modes: {modes_str}")

        return None

    def _detect_new_failure_modes(self, product_code: str | None, since: datetime) -> list[str]:
        """Return failure_mode_categories first seen after `since`."""
        since_naive = since.replace(tzinfo=None) if since.tzinfo else since
        all_rows = self._db.list_extractions(
            product_code=product_code,
            skill_name="ai-failure-mode-classifier",
        )
        historical: set[str] = set()
        recent: set[str] = set()
        for row in all_rows:
            cat = json.loads(row.output_json).get("failure_mode_category") or ""
            if row.extraction_ts < since_naive:
                historical.add(cat)
            else:
                recent.add(cat)
        return sorted(recent - historical - {"not_ai_related", ""})


def _format_message(rule: AlertRuleRecord, value: float, description: str) -> str:
    scope = f"product_code={rule.product_code}" if rule.product_code else "all products"
    note = f" ({rule.description})" if rule.description else ""
    return (
        f"Rule {rule.rule_id}{note}\n"
        f"Scope: {scope} | Window: {rule.window_days}d\n"
        f"Metric: {rule.metric} | Value: {value:.3f} | Threshold: {rule.threshold:.3f}\n"
        f"Detail: {description}"
    )


def _build_notifier(rule: AlertRuleRecord) -> Notifier:
    """Construct the right notifier from a rule record."""
    cfg: dict[str, str] = {}
    if rule.delivery_config:
        cfg = json.loads(rule.delivery_config)

    if rule.delivery == "slack":
        return SlackNotifier(webhook_url=cfg.get("webhook_url", ""))
    if rule.delivery == "email":
        return EmailNotifier(
            smtp_host=cfg.get("smtp_host", "localhost"),
            smtp_port=int(cfg.get("smtp_port", "587")),
            sender=cfg.get("sender", "maudesignal@localhost"),
            recipient=cfg.get("recipient", ""),
            username=cfg.get("username") or None,
            password=cfg.get("password") or None,
            use_tls=cfg.get("use_tls", "true").lower() == "true",
        )
    return ConsoleNotifier()
