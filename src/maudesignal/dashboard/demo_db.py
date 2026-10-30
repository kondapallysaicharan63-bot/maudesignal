"""Keyless demo database: a temporary copy with the recorded CAPA-need packs restored.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The committed ``data/demo/maudesignal_demo.db`` never changes. When the dashboard runs
with no ``META_MODEL_API_KEY`` it opens a copy instead, into which the CAPA-need evidence
packs recorded in ``demo/transcripts`` are replayed (see ``restore_recorded_capas``), so the
evidence pack shows the Muse Spark searches that prepared it. The copy lives for the process
(Streamlit re-runs the script, so the path is cached in this module, not in the script).
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from maudesignal.copilot.actions import restore_recorded_capas
from maudesignal.copilot.protocol import load_transcripts
from maudesignal.dossier.builder import transcripts_dir

_COPIES: dict[Path, Path] = {}


def keyless() -> bool:
    """True when no Meta key is configured (the stored-first demo)."""
    return not os.environ.get("META_MODEL_API_KEY")


def demo_copy_with_recorded_packs(source: Path) -> Path:
    """Path of a temporary copy of ``source`` with the recorded packs restored (cached)."""
    key = source.resolve()
    cached = _COPIES.get(key)
    if cached is not None and cached.is_file():
        return cached
    from maudesignal.storage.database import Database

    folder = Path(tempfile.mkdtemp(prefix="maudesignal-demo-"))
    copy = folder / source.name
    shutil.copy(source, copy)
    restore_recorded_capas(Database(copy), load_transcripts(transcripts_dir()))
    _COPIES[key] = copy
    return copy
