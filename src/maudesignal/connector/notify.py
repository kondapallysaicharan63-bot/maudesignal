"""Email notification for new feedback (Resend). Never fails the request.

Needs ``RESEND_API_KEY`` and ``FEEDBACK_NOTIFY_TO``; without them the step is skipped and
``notify_skipped`` is logged. Only a status or error class is logged, never the key or text.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

import httpx

from maudesignal.common.logging import get_logger

logger = get_logger(__name__)

RESEND_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "MaudeSignal <onboarding@resend.dev>"
TIMEOUT_SECONDS = 5.0


class Notifier(Protocol):
    """Sends one notification for a stored feedback record."""

    def feedback(self, record: dict[str, Any]) -> None:
        """Notify; must not raise."""


def _body(record: dict[str, Any]) -> str:
    lines = [
        f"Rating (matches real PMS/RA work?): {record['rating']}/5",
        f"Comment: {record['comment']}",
        f"What would stop your team using it?: {record['blocker']}",
        f"One thing that would make it useful?: {record['one_thing']}",
        f"Role: {record.get('role') or '-'}",
        f"Consent: {record['consent']}",
        f"Ref code: {record.get('ref') or '-'}",
        f"Page: {record['page']}",
        f"Received (UTC): {record['received_utc']}",
        f"Id: {record['id']}",
    ]
    return "\n".join(lines)


class ResendNotifier:
    """Resend email sender (HTTP client injectable for tests)."""

    def __init__(
        self,
        api_key: str,
        to: list[str],
        sender: str = DEFAULT_FROM,
        client: httpx.Client | None = None,
    ) -> None:
        """Create a notifier."""
        self._key = api_key
        self._to = to
        self._from = sender
        self._client = client or httpx.Client(timeout=TIMEOUT_SECONDS)

    def feedback(self, record: dict[str, Any]) -> None:
        """Send the email; failures are logged (status or class only) and swallowed."""
        subject = f"MaudeSignal feedback: {record['rating']}/5 ({record.get('ref') or 'no code'})"
        payload = {"from": self._from, "to": self._to, "subject": subject, "text": _body(record)}
        try:
            r = self._client.post(
                RESEND_URL, json=payload, headers={"Authorization": f"Bearer {self._key}"}
            )
        except Exception as exc:  # noqa: BLE001 - notification must never fail the request
            logger.warning("notify_failed", error_type=type(exc).__name__)
            return
        if r.status_code >= 300:
            logger.warning("notify_failed", status=r.status_code)
        else:
            logger.info("notify_sent", status=r.status_code)


class NoopNotifier:
    """Used when email is not configured."""

    def feedback(self, record: dict[str, Any]) -> None:
        """Log that notification was skipped."""
        logger.info("notify_skipped")


def notifier_from_env(env: dict[str, str] | None = None) -> Notifier:
    """Resend notifier when both env vars are set, else a no-op."""
    e = os.environ if env is None else env
    key = e.get("RESEND_API_KEY", "").strip()
    to = [t.strip() for t in e.get("FEEDBACK_NOTIFY_TO", "").split(",") if t.strip()]
    if not key or not to:
        return NoopNotifier()
    return ResendNotifier(key, to, e.get("FEEDBACK_NOTIFY_FROM", "").strip() or DEFAULT_FROM)
