"""Prepare the environment for a local test API (keys made here, never real ones).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

    python3 scripts/release/serve_api.py prepare --profile contract \
        --keys-file "$RUNNER_TEMP/keys.json" --env-file "$RUNNER_TEMP/api.env"
    set -a; . "$RUNNER_TEMP/api.env"; set +a
    python3 -m uvicorn api.index:app --port 8000 &

``prepare`` generates three random keys (a full key, a second full key for the rate-limit
check, a demo key), writes them to ``--keys-file`` (mode 0600, outside the repository) and the
environment the API reads to ``--env-file``. On GitHub Actions each key is masked in the log.
No Meta key is ever written: a profile that needs one reads it from the job's secret.

Profiles:

* ``contract`` low limits, so the rate-limit checks finish quickly;
* ``e2e`` high limits, so a browser run across engines and sizes is never throttled.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path

PROFILES: dict[str, dict[str, str]] = {
    "contract": {
        "MAUDESIGNAL_RATE_LIMIT_PER_MIN": "200",
        "MAUDESIGNAL_DEMO_RATE_PER_MIN": "10",
        "MAUDESIGNAL_LIVE_PER_MIN": "8",
        "MAUDESIGNAL_FAILED_AUTH_PER_MIN": "10",
        "MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR": "6",
        "MAUDESIGNAL_FEEDBACK_PER_HOUR": "50",
        "MAUDESIGNAL_LIVE_ASK_PER_DAY": "500",
        "MAUDESIGNAL_LIVE_VOICE_PER_DAY": "500",
        "MAUDESIGNAL_LIVE_LABEL_PER_DAY": "500",
        "MAUDESIGNAL_LIVE_MENTIONS_PER_DAY": "500",
    },
    "e2e": {
        "MAUDESIGNAL_RATE_LIMIT_PER_MIN": "1000",
        "MAUDESIGNAL_DEMO_RATE_PER_MIN": "1000",
        "MAUDESIGNAL_LIVE_PER_MIN": "1000",
        "MAUDESIGNAL_FAILED_AUTH_PER_MIN": "1000",
        "MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR": "1000",
        "MAUDESIGNAL_FEEDBACK_PER_HOUR": "1000",
        "MAUDESIGNAL_VISIT_PER_HOUR": "1000",
        "MAUDESIGNAL_LIVE_ASK_PER_DAY": "5000",
        "MAUDESIGNAL_LIVE_VOICE_PER_DAY": "5000",
        "MAUDESIGNAL_LIVE_LABEL_PER_DAY": "5000",
        "MAUDESIGNAL_LIVE_MENTIONS_PER_DAY": "5000",
    },
}


def make_keys() -> dict[str, str]:
    """Three random keys, each long enough for the API (32 characters or more)."""
    return {
        "key": secrets.token_urlsafe(36),
        "key2": secrets.token_urlsafe(36),
        "demo": secrets.token_urlsafe(36),
        "admin": secrets.token_urlsafe(36),
    }


def build_env(
    keys: dict[str, str], profile: str, origins: list[str], ledger_dir: str
) -> dict[str, str]:
    """The environment variables the API reads for ``profile`` (no Meta or openFDA key)."""
    env = {
        "MAUDESIGNAL_API_KEYS": f"release-a={keys['key']},release-b={keys['key2']}",
        "MAUDESIGNAL_DEMO_KEYS": f"demo={keys['demo']}",
        "MAUDESIGNAL_KEY_PEPPER": secrets.token_hex(16),
        "MAUDESIGNAL_ADMIN_KEY": keys["admin"],
        "MAUDESIGNAL_WEB_ORIGINS": ",".join(origins),
        "MAUDESIGNAL_TRUST_FORWARDED": "1",
        "MAUDESIGNAL_API_LEDGER_DIR": ledger_dir,
        "MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP": "1",
    }
    env.update(PROFILES[profile])
    return env


def main(argv: list[str] | None = None) -> int:
    """``prepare``: write the keys file and the env file."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--profile", choices=sorted(PROFILES), required=True)
    p.add_argument("--keys-file", type=Path, required=True)
    p.add_argument("--env-file", type=Path, required=True)
    p.add_argument("--origin", action="append", default=["http://127.0.0.1:4173"])
    p.add_argument("--ledger-dir", default="")
    args = ap.parse_args(argv)
    keys = make_keys()
    ledger = args.ledger_dir or str(args.keys_file.parent / f"ledger-{int(time.time())}")
    Path(ledger).mkdir(parents=True, exist_ok=True)
    env = build_env(keys, args.profile, list(dict.fromkeys(args.origin)), ledger)
    args.keys_file.parent.mkdir(parents=True, exist_ok=True)
    args.keys_file.write_text(json.dumps(keys), "utf-8")
    args.keys_file.chmod(0o600)
    args.env_file.write_text("".join(f"export {k}='{v}'\n" for k, v in env.items()), "utf-8")
    args.env_file.chmod(0o600)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for value in [*keys.values(), env["MAUDESIGNAL_KEY_PEPPER"]]:
            print(f"::add-mask::{value}")
    print(f"prepared the '{args.profile}' profile: {len(keys)} test keys (not shown)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
