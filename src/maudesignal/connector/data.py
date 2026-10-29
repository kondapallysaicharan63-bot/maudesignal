"""Stored data the connector reads: demo database, digest, recorded answers.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Everything loads lazily and once. The demo database is copied to a temporary
folder first because serverless hosting mounts the repository read-only and
opening a SQLite file can write to it; the committed file is never touched.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

from maudesignal.copilot.tools import ToolContext
from maudesignal.copilot.transcript import load_transcripts
from maudesignal.gate.evidence import EvidenceStore
from maudesignal.gate.loader import store_from_database
from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import digest_from_database, digest_to_dict
from maudesignal.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ConnectorData:
    """Lazy, read-only view of the stored demo data."""

    def __init__(
        self,
        *,
        root: Path = PROJECT_ROOT,
        db_path: Path | None = None,
        digest_dir: Path | None = None,
        transcripts_dir: Path | None = None,
        manifest_path: Path | None = None,
        work_dir: Path | None = None,
    ) -> None:
        """Create the view (nothing is read until first use).

        Args:
            root: Repository root.
            db_path: Demo database (default ``data/demo/maudesignal_demo.db``).
            digest_dir: Folder of stored digests (default ``digests/``).
            transcripts_dir: Recorded copilot runs (default ``demo/transcripts/``).
            manifest_path: Seed manifest (default ``data/demo/SEED_MANIFEST.json``).
            work_dir: Where the writable database copy goes (default a temp folder).
        """
        self._db_src = db_path or root / "data" / "demo" / "maudesignal_demo.db"
        self._digest_dir = digest_dir or root / "digests"
        self._transcripts_dir = transcripts_dir or root / "demo" / "transcripts"
        self._manifest = manifest_path or root / "data" / "demo" / "SEED_MANIFEST.json"
        self._work_dir = work_dir
        self._lock = threading.Lock()
        self._db: Database | None = None
        self._store: EvidenceStore | None = None
        self._digest: dict[str, Any] | None = None
        self._transcripts: list[dict[str, Any]] | None = None

    @property
    def db(self) -> Database:
        """Writable copy of the demo database (the copilot appends its audit entry here)."""
        with self._lock:
            if self._db is None:
                work = self._work_dir or Path(tempfile.mkdtemp(prefix="maudesignal-connector-"))
                work.mkdir(parents=True, exist_ok=True)
                target = work / "demo.db"
                shutil.copyfile(self._db_src, target)
                self._db = Database(target)
            return self._db

    @property
    def store(self) -> EvidenceStore:
        """Evidence the gate and the stored tools read."""
        db = self.db
        with self._lock:
            if self._store is None:
                self._store = store_from_database(db)
            return self._store

    def tool_context(self) -> ToolContext:
        """Copilot tool context over the stored data."""
        return ToolContext(db=self.db, store=self.store, actor="connector:muse-spark")

    def digest(self) -> dict[str, Any]:
        """Latest stored digest (computed from the demo database if none is stored)."""
        if self._digest is None:
            files = sorted(self._digest_dir.glob("*.json")) if self._digest_dir.is_dir() else []
            if files:
                self._digest = json.loads(files[-1].read_text(encoding="utf-8"))
            else:
                db = self.db
                self._digest = digest_to_dict(digest_from_database(db, detect_from_database(db)))
        return self._digest

    def transcripts(self) -> list[dict[str, Any]]:
        """Recorded copilot runs (real Muse Spark runs, gate verdicts included)."""
        if self._transcripts is None:
            self._transcripts = load_transcripts(self._transcripts_dir)
        return self._transcripts

    def manifest(self) -> dict[str, Any]:
        """Seed manifest: when the snapshot was fetched and its latest report date."""
        try:
            data = json.loads(self._manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}
