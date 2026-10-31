"""Create an API key for the MaudeSignal connector without ever printing it.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The key is random (43 URL-safe characters) and goes to exactly one place:

(a) With ``VERCEL_TOKEN`` and ``VERCEL_PROJECT_ID`` set (plus ``VERCEL_TEAM_ID`` for a team
    project), it is written to the project's encrypted ``MAUDESIGNAL_API_KEYS`` environment
    variable for Production through the Vercel REST API. The script prints only where to read
    it back: Vercel > Project > Settings > Environment Variables > MAUDESIGNAL_API_KEYS
    (click to reveal). The new key is APPENDED to the comma-separated list, so earlier keys keep
    working; to revoke a key, delete its entry in the dashboard.

(b) Otherwise it is written to a new file outside the repository with mode 600, and the script
    prints only that path and what to do with it.

The key is never printed to stdout or stderr, never passed on a command line, never logged and
never written inside the repository. Vercel's reply is never printed either (it can echo the
value); only the HTTP status is shown on failure.

With ``--label LABEL`` the entry is written as ``LABEL=KEY`` so logs and the audit chain show
the label. The script then also prints the line to paste, without the key: ``LABEL=<key>``.

Usage::

    python3.12 -m maudesignal.connector.keygen [--label LABEL] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

ENV_NAME = "MAUDESIGNAL_API_KEYS"
VERCEL_API = "https://api.vercel.com"
REPO_ROOT = Path(__file__).resolve().parents[3]
REVEAL = (
    "set; copy it from Vercel > Project > Settings > Environment Variables > "
    "MAUDESIGNAL_API_KEYS (click to reveal)"
)

#: ``http(method, url, token, body) -> (status, parsed_json_or_None)``; the default uses urllib.
HttpFn = Callable[[str, str, str, dict[str, Any] | None], tuple[int, Any]]


def _urllib_http(
    method: str, url: str, token: str, body: dict[str, Any] | None
) -> tuple[int, Any]:  # pragma: no cover - real network
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(  # noqa: S310 - fixed https Vercel API URL
        url,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            raw = resp.read()
            return int(resp.status), (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return int(exc.code), None
    except (urllib.error.URLError, TimeoutError, ValueError):
        return 0, None


def new_key() -> str:
    """A fresh random key (43 URL-safe characters, well above the server's 32 minimum)."""
    return secrets.token_urlsafe(32)


def _team_query(env: Mapping[str, str]) -> str:
    team = env.get("VERCEL_TEAM_ID", "").strip()
    return f"?teamId={team}" if team else ""


def entry_for(key: str, label: str | None) -> str:
    """The list entry for a key: ``KEY`` or ``LABEL=KEY``."""
    return f"{label}={key}" if label else key


def set_vercel_env(
    key: str, env: Mapping[str, str], http: HttpFn, label: str | None = None
) -> int | None:
    """Append the key to the encrypted Production variable (created if missing).

    Earlier keys are kept. Returns None on success, else the HTTP status (0 for no response).
    The existing value is read through the API and written back; it is never printed.
    """
    token, project = env["VERCEL_TOKEN"], env["VERCEL_PROJECT_ID"]
    q = _team_query(env)
    status, listing = http("GET", f"{VERCEL_API}/v10/projects/{project}/env{q}", token, None)
    if status != 200 or not isinstance(listing, dict):
        return status or 0
    existing = next(
        (
            e
            for e in listing.get("envs", [])
            if e.get("key") == ENV_NAME and "production" in (e.get("target") or [])
        ),
        None,
    )
    entry = entry_for(key, label)
    value = entry
    if existing and existing.get("id"):
        # Encrypted values are not in the list; read this one by id (decrypted) to append.
        status, one = http(
            "GET", f"{VERCEL_API}/v1/projects/{project}/env/{existing['id']}{q}", token, None
        )
        if status != 200 or not isinstance(one, dict):
            return status or 0
        old = str(one.get("value") or "").strip().strip(",")
        value = f"{old},{entry}" if old else entry
    body: dict[str, Any] = {"value": value, "type": "encrypted", "target": ["production"]}
    if existing and existing.get("id"):
        url = f"{VERCEL_API}/v9/projects/{project}/env/{existing['id']}{q}"
        status, _ = http("PATCH", url, token, body)
    else:
        url = f"{VERCEL_API}/v10/projects/{project}/env{q}"
        status, _ = http("POST", url, token, {"key": ENV_NAME, **body})
    return None if status in (200, 201) else (status or 0)


def _inside_repository(target_dir: Path) -> bool:
    """True when ``target_dir`` is in this source tree or under any directory with a VCS entry."""
    if target_dir == REPO_ROOT or REPO_ROOT in target_dir.parents:
        return True
    return any((p / ".git").exists() for p in (target_dir, *target_dir.parents))


def write_key_file(key: str, directory: Path, now: datetime) -> Path:
    """Write the key to a new mode-600 file in ``directory`` (never inside the repository)."""
    target_dir = directory.expanduser().resolve()
    if _inside_repository(target_dir):
        raise ValueError("refusing to write a key inside the repository")
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"maudesignal-connector-key-{now:%Y%m%dT%H%M%SZ}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(key + "\n")
    path.chmod(0o600)
    return path


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    http: HttpFn = _urllib_http,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Run the script; returns the exit code. Output never contains the key."""
    out, err = stdout or sys.stdout, stderr or sys.stderr
    environ = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Create a connector API key without printing it.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("~/.config/maudesignal"),
        help="Where the key file goes when Vercel is not configured (outside the repository).",
    )
    parser.add_argument(
        "--label",
        default=None,
        help="Name for the key (1 to 32 letters, digits, - or _), e.g. meta-review. Logs and "
        "the audit chain show it. Prints the line to paste, without the key.",
    )
    args = parser.parse_args(argv)
    label: str | None = args.label
    if label is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", label):
        print("The label must be 1 to 32 letters, digits, - or _.", file=err)
        return 2
    key = new_key()
    if environ.get("VERCEL_TOKEN") and environ.get("VERCEL_PROJECT_ID"):
        failed = set_vercel_env(key, environ, http, label)
        if failed is not None:
            print(
                f"Vercel API call failed (HTTP {failed or 'no response'}). "
                "No key was saved anywhere. Check VERCEL_TOKEN, VERCEL_PROJECT_ID and "
                "VERCEL_TEAM_ID, then run the script again.",
                file=err,
            )
            return 1
        print(REVEAL, file=out)
        print(
            "Redeploy the project so the new value is used. The new key was appended; earlier "
            "keys keep working. Delete an entry in the dashboard to revoke that key.",
            file=out,
        )
        return 0
    try:
        path = write_key_file(key, args.out_dir, now())
    except (OSError, ValueError) as exc:
        print(f"Could not save the key: {type(exc).__name__}. Nothing was written.", file=err)
        return 1
    print(f"Key saved to {path} (mode 600). It was not printed.", file=out)
    print(
        "Next: in Vercel > Project > Settings > Environment Variables, add MAUDESIGNAL_API_KEYS "
        "(Production) and paste the file's single line as the value, then redeploy.",
        file=out,
    )
    print(
        f'To try it from this shell without showing it: MAUDESIGNAL_KEY="$(cat {path})"',
        file=out,
    )
    if label:
        print(
            f"Line to paste into MAUDESIGNAL_API_KEYS (append it after a comma): {label}=<key>",
            file=out,
        )
    print("Delete the file once the key is stored in your password manager.", file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
