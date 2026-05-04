"""SMTP email alert notifier (Phase 2)."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from maudesignal.alerting.notifiers.base import Notifier
from maudesignal.common.logging import get_logger

logger = get_logger(__name__)


class EmailNotifier(Notifier):
    """Send alert via SMTP (plain-text email)."""

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        sender: str,
        recipient: str,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
    ) -> None:
        """Configure SMTP connection parameters."""
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._sender = sender
        self._recipient = recipient
        self._username = username
        self._password = password
        self._use_tls = use_tls

    @property
    def channel(self) -> str:
        """Return channel identifier."""
        return "email"

    def send(self, *, subject: str, body: str) -> bool:
        """Send email via SMTP; return True on success."""
        msg = MIMEText(body)
        msg["Subject"] = f"[MaudeSignal Alert] {subject}"
        msg["From"] = self._sender
        msg["To"] = self._recipient
        try:
            if self._use_tls:
                with smtplib.SMTP_SSL(self._smtp_host, self._smtp_port) as smtp:
                    if self._username and self._password:
                        smtp.login(self._username, self._password)
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(self._smtp_host, self._smtp_port) as smtp:
                    if self._username and self._password:
                        smtp.login(self._username, self._password)
                    smtp.send_message(msg)
            logger.info("alert_sent", channel="email", recipient=self._recipient)
            return True
        except Exception as exc:
            logger.error("alert_delivery_failed", channel="email", error=str(exc))
            return False
