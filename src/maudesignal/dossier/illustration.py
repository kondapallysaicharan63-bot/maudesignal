"""Optional AI cover illustration (Muse Image 1.0). OFF by default.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One image, $0.01, placed only on the cover and captioned "AI-generated
illustration — not evidence". The prompt lives in
``skills/dossier-cover-illustration/SKILL.md``; it receives only the public
classification name, never report narratives. The key is read by the caller
from the environment and is never logged or stored.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

import httpx

from maudesignal.copilot.agent import default_skills_root
from maudesignal.dossier.model import Illustration
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader

SKILL_NAME = "dossier-cover-illustration"
IMAGE_MODEL = "muse-image-1.0"
USD_PER_IMAGE = 0.01
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


class IllustrationError(RuntimeError):
    """Raised when the image API fails or returns something unusable."""


def prompt_for(classification: str, skill: LoadedSkill | None = None) -> str:
    """Fill the skill's prompt template with the classification name."""
    sk = skill or SkillLoader(default_skills_root()).load(SKILL_NAME)
    text = sk.system_prompt
    start, end = text.find("<!-- PROMPT START -->"), text.find("<!-- PROMPT END -->")
    if start < 0 or end < 0:
        raise IllustrationError("prompt markers missing in SKILL.md")
    template = text[start + len("<!-- PROMPT START -->") : end].strip()
    safe = "".join(ch for ch in classification if ch.isalnum() or ch in " ,-/()")[:120]
    return template.replace("{classification}", safe or "medical device")


def generate_illustration(
    *,
    api_key: str,
    classification: str,
    base_url: str = DEFAULT_BASE_URL,
    http: Any | None = None,
    timeout: float = 120.0,
) -> Illustration:
    """Generate one PNG with ``muse-image-1.0``.

    Args:
        api_key: Meta Model API key (from the environment; never logged).
        classification: Public FDA classification name for the prompt.
        base_url: Meta Model API base URL.
        http: Optional ``httpx.Client``-like object (tests inject a fake).
        timeout: Request timeout in seconds.

    Raises:
        IllustrationError: missing key, HTTP error, or a response without a PNG.
    """
    if not api_key:
        raise IllustrationError("no API key")
    body = {
        "model": IMAGE_MODEL,
        "prompt": prompt_for(classification),
        "n": 1,
        "output_format": "png",
    }
    client = http or httpx.Client(timeout=timeout)
    try:
        resp = client.post(
            f"{base_url.rstrip('/')}/images/generations",
            json=body,
            headers={"Authorization": f"Bearer {api_key}"},
        )
    except httpx.HTTPError as exc:
        raise IllustrationError(f"image request failed: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise IllustrationError(f"image API returned HTTP {resp.status_code}")
    data = resp.json().get("data") or []
    b64 = data[0].get("b64_json") if data and isinstance(data[0], dict) else None
    if not b64:
        raise IllustrationError("no b64_json in response")
    try:
        raw = base64.b64decode(b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IllustrationError("b64_json is not valid base64") from exc
    if not raw.startswith(_PNG_MAGIC):
        raise IllustrationError("response is not a PNG")
    return Illustration(png_b64=b64, model=IMAGE_MODEL)
