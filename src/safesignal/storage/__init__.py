"""SQLite storage layer for SafeSignal.

All persistence goes through this module. Other modules do not touch
SQLAlchemy or sqlite3 directly.
"""

from safesignal.storage.database import Database
from safesignal.storage.models import (
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
