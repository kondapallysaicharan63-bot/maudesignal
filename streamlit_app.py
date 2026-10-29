"""Streamlit Community Cloud entry point (keyless, stored-first public demo).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs the MaudeSignal dashboard exactly as ``streamlit run
src/maudesignal/dashboard/app.py`` would. With no ``MAUDESIGNAL_DB_PATH`` and no
local ``data/maudesignal.db``, the dashboard opens the committed demo database
(``data/demo/maudesignal_demo.db``, 137 public openFDA MAUDE reports), so no API
key or setup is needed.

``runpy`` re-executes the app script on every Streamlit rerun, which a plain
``import`` would not (modules are cached after the first run).
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

runpy.run_path(str(_SRC / "maudesignal" / "dashboard" / "app.py"), run_name="__main__")
