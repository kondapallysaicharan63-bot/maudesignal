"""SQLite storage layer for MaudeSignal.

All persistence goes through this module. Other modules do not touch
SQLAlchemy or sqlite3 directly.
"""

from maudesignal.storage.database import Database
from maudesignal.storage.models import (
    ExtractionRecord,
    LLMAuditLogRecord,
    NormalizedEventRecord,
    RawReportRecord,
)

__all__ = [
    "Database",
    "ExtractionRecord",
    "LLMAuditLogRecord",
    "NormalizedEventRecord",
    "RawReportRecord",
]
