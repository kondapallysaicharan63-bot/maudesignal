"""Errors the tool layer raises; each transport maps them to its own status.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

from maudesignal.common.exceptions import MaudeSignalError


class ConnectorError(MaudeSignalError):
    """Base class; the message is safe to show a caller (it never holds a key)."""

    code = "connector_error"

    def __init__(self, message: str = "", suggestions: list[str] | None = None) -> None:
        """Keep the message and, when useful, a short list of suggestions.

        Args:
            message: Text safe to show a caller.
            suggestions: Optional "did you mean" values (never applied automatically).
        """
        super().__init__(message)
        self.suggestions: list[str] = list(suggestions or [])


class InvalidInputError(ConnectorError):
    """The caller's input is not usable (maps to 422)."""

    code = "invalid_input"


class UnknownProductCodeError(InvalidInputError):
    """A well-formed product code that the connector has no sign of (maps to 422)."""

    code = "unknown_product_code"


class NotFoundError(ConnectorError):
    """Nothing stored matches (maps to 404)."""

    code = "not_found"


class SourceUnavailableError(ConnectorError):
    """A live source could not be reached and nothing stored can stand in (maps to 502)."""

    code = "source_unavailable"
