"""Generate ``api/openapi.json`` from the app (a test fails if the committed file drifts).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Run from the repository root::

    python3.12 -m maudesignal.connector.openapi
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from maudesignal.connector.app import Settings, create_app
from maudesignal.connector.data import PROJECT_ROOT
from maudesignal.connector.research import research_forced_off
from maudesignal.connector.security import KeyStore, RateLimiter

OPENAPI_PATH = PROJECT_ROOT / "api" / "openapi.json"


def build_spec() -> dict[str, Any]:
    """The OpenAPI document (no environment is read: the spec never depends on keys)."""
    with research_forced_off():
        app = create_app(Settings(keys=KeyStore([]), limiter=RateLimiter(), audit_full_text=False))
        spec: dict[str, Any] = app.openapi()
    return spec


def render(spec: dict[str, Any]) -> str:
    """Stable JSON text, newline-terminated."""
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(path: Path = OPENAPI_PATH) -> None:
    """Write the spec to ``path``."""
    path.write_text(render(build_spec()), encoding="utf-8")


if __name__ == "__main__":
    main()
