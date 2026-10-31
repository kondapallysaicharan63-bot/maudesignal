"""Stored data the connector reads: demo database, digest, recorded answers.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Everything loads lazily and once. The demo database is copied to a temporary
folder first because serverless hosting mounts the repository read-only and
opening a SQLite file can write to it; the committed file is never touched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
import threading
from datetime import datetime
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
        self._sweep = root / "demo" / "sweep" / "ai-device-sweep.json"
        self._known_codes: frozenset[str] | None = None
        self._digest_dir = digest_dir or root / "digests"
        self._transcripts_dir = transcripts_dir or root / "demo" / "transcripts"
        self._manifest = manifest_path or root / "data" / "demo" / "SEED_MANIFEST.json"
        self._work_dir = work_dir
        self._lock = threading.Lock()
        #: Serialises live asks (agent write plus audit redaction) on this instance.
        self.live_ask_lock = threading.Lock()
        self._db: Database | None = None
        self._db_file: Path | None = None
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
                self._db_file = target
            return self._db

    def redact_audit_questions(self) -> int:
        """Replace the question text in the copilot's own audit entries with its hash.

        The copilot writes up to 500 characters of the question into its audit entry in this
        instance's temporary database copy. The connector's privacy statement says question
        text is not stored, so this runs after every live ask: each ``question`` field becomes
        ``sha256:<hex>`` and the hash chain is recomputed so it still verifies. Returns the
        number of entries changed.
        """
        _ = self.db
        with self._lock:
            if self._db_file is None:  # pragma: no cover - set by the db property above
                return 0
            con = sqlite3.connect(self._db_file)
            try:
                con.execute("PRAGMA secure_delete=ON")  # do not leave the text in free pages
                rows = con.execute(
                    "SELECT seq, ts, actor, action, entity_id, payload_json, prev_hash, "
                    "entry_hash FROM action_audit ORDER BY seq"
                ).fetchall()
                changed = 0
                prev = "GENESIS"
                for seq, ts, actor, action, entity_id, payload_json, old_prev, old_hash in rows:
                    new_payload = payload_json
                    try:
                        payload = json.loads(payload_json)
                    except ValueError:
                        payload = None
                    question = payload.get("question") if isinstance(payload, dict) else None
                    if (
                        isinstance(payload, dict)
                        and isinstance(question, str)
                        and not question.startswith("sha256:")
                    ):
                        digest = hashlib.sha256(question.encode("utf-8")).hexdigest()
                        payload["question"] = f"sha256:{digest}"
                        new_payload = json.dumps(payload, sort_keys=True)
                        changed += 1
                    if new_payload == payload_json and prev == old_prev and changed == 0:
                        prev = old_hash
                        continue
                    stamp = datetime.fromisoformat(str(ts))
                    entry = Database.audit_entry_hash(
                        prev, stamp, actor, action, entity_id, new_payload
                    )
                    con.execute(
                        "UPDATE action_audit SET payload_json=?, prev_hash=?, entry_hash=? "
                        "WHERE seq=?",
                        (new_payload, prev, entry, seq),
                    )
                    prev = entry
                con.commit()
                return changed
            finally:
                con.close()

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

    def known_product_codes(self) -> frozenset[str]:
        """Product codes the connector has a sign of.

        Sources: stored reports, the device catalog, the stored digest and the stored AI-device
        sweep. Used only to offer "did you mean"
        and to tell a code nobody has reported on from a typo; it never rewrites an input.
        There is no offline copy of the full openFDA classification list in this repository.
        """
        if self._known_codes is not None:
            return self._known_codes
        codes: set[str] = set()
        try:
            digest = self.digest()
            codes.update(str(x["product_code"]) for x in digest.get("signals", []))
            codes.update(str(c) for c in (digest.get("device_types") or {}))
        except (OSError, ValueError, KeyError):
            pass
        try:
            con = sqlite3.connect(f"file:{self._db_src}?mode=ro", uri=True)
            try:
                for table in ("raw_reports", "device_catalog"):
                    rows = con.execute(f"SELECT DISTINCT product_code FROM {table}").fetchall()
                    codes.update(str(r[0]) for r in rows if r[0])
            finally:
                con.close()
        except sqlite3.Error:
            pass
        try:
            sweep = json.loads(self._sweep.read_text(encoding="utf-8"))
            codes.update(
                str(r["product_code"]) for r in sweep.get("rows", []) if r.get("product_code")
            )
        except (OSError, ValueError, KeyError, AttributeError):
            pass
        self._known_codes = frozenset(c.upper() for c in codes if len(c) == 3)
        return self._known_codes

    def sweep(self) -> dict[str, Any]:
        """The stored AI-device sweep (``demo/sweep/ai-device-sweep.json``); empty when absent."""
        try:
            data = json.loads(self._sweep.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

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
