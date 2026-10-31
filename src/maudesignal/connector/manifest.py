"""Generate ``api/mcp-manifest.json`` from the tool registry (a test fails if it drifts).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Run from the repository root::

    python3.12 -m maudesignal.connector.manifest
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from maudesignal.connector.data import PROJECT_ROOT
from maudesignal.connector.mcp_server import (
    INSTRUCTIONS,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_TITLE,
    tool_list,
)
from maudesignal.connector.models import ADVISORY

MANIFEST_PATH = PROJECT_ROOT / "api" / "mcp-manifest.json"
MANIFEST_VERSION = "0.1.0"


def build_manifest() -> dict[str, Any]:
    """The manifest: server, endpoint, auth and the same tools ``tools/list`` returns."""
    return {
        "name": SERVER_NAME,
        "title": SERVER_TITLE,
        "version": MANIFEST_VERSION,
        "description": INSTRUCTIONS,
        "protocolVersion": PROTOCOL_VERSION,
        "transport": {
            "type": "streamable-http",
            "mode": "stateless, JSON responses, POST only (no session, no event stream)",
            "path": "/mcp",
        },
        "authentication": {
            "type": "api-key",
            "headers": ["X-API-Key", "Authorization: Bearer <key>"],
            "note": "Read-only key. Never send a key in the URL.",
        },
        "advisory": ADVISORY,
        "readOnly": True,
        "tools": tool_list(),
    }


def render(manifest: dict[str, Any]) -> str:
    """Stable JSON text, newline-terminated."""
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(path: Path = MANIFEST_PATH) -> None:
    """Write the manifest to ``path``."""
    path.write_text(render(build_manifest()), encoding="utf-8")


if __name__ == "__main__":
    main()
