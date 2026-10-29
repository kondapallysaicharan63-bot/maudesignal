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


def _drop_changed_modules() -> None:
    """Forget the imported ``maudesignal`` modules once any of their source files changed.

    Streamlit Cloud pulls a new commit into the running process. The app script is
    re-executed, but modules it imports stay cached, so a new ``app.py`` could import
    a name the old cached module lacks (an ImportError on 2026-10-29). Dropping them
    makes the next import load the new code.
    """
    ours = [
        (name, module)
        for name, module in list(sys.modules.items())
        if name == "maudesignal" or name.startswith("maudesignal.")
    ]
    changed = False
    for _, module in ours:
        path = getattr(module, "__file__", None)
        if not path or not Path(path).exists():
            continue
        mtime = Path(path).stat().st_mtime
        seen = getattr(module, "__ms_mtime__", None)
        if seen is None:
            module.__ms_mtime__ = mtime  # type: ignore[attr-defined]
        elif seen != mtime:
            changed = True
    if changed:  # drop them all: an unchanged module may hold the old one's objects
        for name, _ in ours:
            del sys.modules[name]


_drop_changed_modules()
try:
    runpy.run_path(str(_SRC / "maudesignal" / "dashboard" / "app.py"), run_name="__main__")
finally:
    _drop_changed_modules()  # records the modules this run imported
