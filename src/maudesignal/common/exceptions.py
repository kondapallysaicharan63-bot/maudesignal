"""Exception hierarchy for MaudeSignal.

All MaudeSignal exceptions inherit from ``MaudeSignalError`` so callers can
catch all-of-our-errors without catching arbitrary library exceptions.
"""


class MaudeSignalError(Exception):
    """Base exception for all MaudeSignal errors."""


# --- Ingestion layer ---


class IngestionError(MaudeSignalError):
    """Raised for errors during MAUDE data ingestion."""


class OpenFDAAPIError(IngestionError):
    """Raised for non-recoverable openFDA API errors."""


class OpenFDARateLimitError(OpenFDAAPIError):
    """Raised when openFDA returns 429 after all retries exhausted."""


# --- Extraction layer ---


class ExtractionError(MaudeSignalError):
    """Raised for errors during LLM-based extraction."""


class SkillLoadError(ExtractionError):
    """Raised when a SKILL.md file cannot be loaded or parsed."""


class LLMOutputError(ExtractionError):
    """Raised when LLM output is malformed or fails schema validation."""


class BudgetExceededError(ExtractionError):
    """Raised when cumulative LLM costs exceed the configured ceiling."""


# --- Verification layer ---


class CitationVerificationError(MaudeSignalError):
    """Raised when citation verification fails unexpectedly.

    Note: a citation being *fake* is not an error — it's a valid result
    (``verified=False``). This exception is reserved for infrastructure
    failures (e.g., openFDA unreachable, guidance index corrupt).
    """


# --- Storage layer ---


class StorageError(MaudeSignalError):
    """Raised for database errors."""
