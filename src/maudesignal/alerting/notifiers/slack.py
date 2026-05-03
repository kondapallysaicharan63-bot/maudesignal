"""Slack webhook alert notifier (Phase 2)."""

from __future__ import annotations

import json

import httpx

from maudesignal.alerting.notifiers.base import Notifier
from maudesignal.common.logging import get_logger

logger = get_logger(__name__)


class SlackNotifier(Notifier):
    """Post an alert to a Slack incoming-webhook URL."""

    def __init__(self, webhook_url: str) -> None:
        """Initialize with a Slack incoming-webhook URL."""
        if not webhook_url:
            raise ValueError("SlackNotifier requires a non-empty webhook_url")
        self._webhook_url = webhook_url

    @property
    def channel(self) -> str:
        """Return channel identifier."""
        return "slack"

    def send(self, *, subject: str, body: str) -> bool:
        """POST alert payload to Slack webhook; return True on success."""
        payload = {"text": f"*{subject}*\n{body}"}
        try:
            resp = httpx.post(
                self._webhook_url,
                content=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                timeout=10.0,
            )
            resp.raise_for_status()
            logger.info("alert_sent", channel="slack", subject=subject)
            return True
        except Exception as exc:
            logger.error("alert_delivery_failed", channel="slack", error=str(exc))
            return False
