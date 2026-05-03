"""Abstract base for all alert notifiers (Phase 2)."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Notifier(ABC):
    """Send an alert message via a specific channel."""

    @property
    @abstractmethod
    def channel(self) -> str:
        """Delivery channel identifier (console | slack | email)."""

    @abstractmethod
    def send(self, *, subject: str, body: str) -> bool:
        """Send the alert.

        Returns True on success, False on delivery failure.
        Must never raise — swallow transport errors and return False.
        """
