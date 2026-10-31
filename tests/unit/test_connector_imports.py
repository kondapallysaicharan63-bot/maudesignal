"""The connector must import with only the packages in api/requirements.txt (HACKATHON-BUILT)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Heavy top-level packages that api/requirements.txt does not install.
BLOCKED = (
    "PIL",
    "numpy",
    "pandas",
    "scipy",
    "streamlit",
    "weasyprint",
    "matplotlib",
    "evidently",
    "plotly",
    "altair",
    "fitz",
    "pypdf",
)

SCRIPT = """
import sys
BLOCKED = set(%r)
class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError("blocked in test: " + name)
        return None
sys.meta_path.insert(0, Block())
import maudesignal.connector.app
bad = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
assert not bad, bad
print("IMPORT OK")
"""


def test_connector_app_imports_without_packages_missing_from_api_requirements() -> None:
    lines = (ROOT / "api" / "requirements.txt").read_text().lower().splitlines()
    reqs = "\n".join(ln for ln in lines if not ln.lstrip().startswith("#"))
    for pkg in ("pillow", "numpy", "pandas", "scipy", "streamlit", "weasyprint"):
        assert pkg not in reqs
    out = subprocess.run(
        [sys.executable, "-c", SCRIPT % (BLOCKED,)],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr[-800:]
    assert "IMPORT OK" in out.stdout


def test_vision_modules_still_reexport_the_moved_helpers() -> None:
    from maudesignal.common import device_ids
    from maudesignal.vision import fda_pdf, label, verify

    assert label.gtin_check_digit_ok is device_ids.gtin_check_digit_ok
    assert label.parse_udi is device_ids.parse_udi
    assert verify.norm_text is device_ids.norm_text
    assert verify.norm_company is device_ids.norm_company
    assert fda_pdf.normalize_k_number is device_ids.normalize_k_number
