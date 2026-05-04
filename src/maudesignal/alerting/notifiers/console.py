"""Console (stdout) alert notifier (Phase 2)."""

from __future__ import annotations

from maudesignal.alerting.notifiers.base import Notifier
from maudesignal.common.logging import get_logger

logger = get_logger(__name__)


class ConsoleNotifier(Notifier):
    """Print alert to stdout — the default zero-config notifier."""

    @property
    def channel(self) -> str:
        """Return channel identifier."""
        return "console"

    def send(self, *, subject: str, body: str) -> bool:
        """Print alert to stdout and return True."""
        print(f"\n[ALERT] {subject}\n{body}\n")  # noqa: T201
        logger.info("alert_sent", channel="console", subject=subject)
        return True
