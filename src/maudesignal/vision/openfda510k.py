"""Small openFDA 510(k) client used to check what the vision features read.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

openFDA is the primary source the readings are checked against (CLAUDE.md §6.2):
never the model's memory. Query strings are built by hand because openFDA uses
a literal ``+`` as its boolean separator, and ``%2B`` makes it return HTTP 500.
A 404 from openFDA means "no matches", not an error.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote

import httpx

from maudesignal.common.exceptions import MaudeSignalError

OPENFDA_510K_URL = "https://api.fda.gov/device/510k.json"
_SAFE = '+:"()[]*-.'
_TERM_CLEAN = re.compile(r"[^A-Za-z0-9 .\-]")


class OpenFdaError(MaudeSignalError):
    """openFDA request failed."""


@dataclass(frozen=True)
class Fda510kRecord:
    """The openFDA fields the vision checks use."""

    k_number: str
    applicant: str
    device_name: str
    product_code: str
    decision_date: str  # YYYY-MM-DD as openFDA returns it
    regulation_number: str
    statement_or_summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def from_api(cls, r: dict[str, Any]) -> Fda510kRecord:
        """Build from one openFDA ``results`` item."""
        ofda = r.get("openfda") or {}
        reg = ofda.get("regulation_number") or ""
        if isinstance(reg, list):
            reg = reg[0] if reg else ""
        return cls(
            k_number=str(r.get("k_number") or ""),
            applicant=str(r.get("applicant") or ""),
            device_name=str(r.get("device_name") or ""),
            product_code=str(r.get("product_code") or ""),
            decision_date=_iso(str(r.get("decision_date") or "")),
            regulation_number=str(reg),
            statement_or_summary=str(r.get("statement_or_summary") or ""),
            raw=r,
        )

    def to_dict(self) -> dict[str, str]:
        """Compact JSON form (no raw payload)."""
        return {
            "k_number": self.k_number,
            "applicant": self.applicant,
            "device_name": self.device_name,
            "product_code": self.product_code,
            "decision_date": self.decision_date,
            "regulation_number": self.regulation_number,
            "statement_or_summary": self.statement_or_summary,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fda510kRecord:
        """Inverse of :meth:`to_dict`."""

        def s(key: str) -> str:
            return str(d.get(key) or "")

        return cls(
            k_number=s("k_number"),
            applicant=s("applicant"),
            device_name=s("device_name"),
            product_code=s("product_code"),
            decision_date=s("decision_date"),
            regulation_number=s("regulation_number"),
            statement_or_summary=s("statement_or_summary"),
        )


def _iso(value: str) -> str:
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _phrase(value: str) -> str:
    cleaned = " ".join(_TERM_CLEAN.sub(" ", value).split())
    return '"' + cleaned.replace(" ", "+") + '"'


class OpenFda510k:
    """openFDA 510(k) lookups (injectable transport for tests)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        """Create the client.

        Args:
            api_key: Optional openFDA API key (raises the rate limit). Never logged.
            transport: Injected HTTP transport (``httpx.MockTransport`` in tests).
            timeout_s: Request timeout.
        """
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout_s, transport=transport)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> OpenFda510k:
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close on exit."""
        self.close()

    def _query(self, search: str, limit: int) -> list[dict[str, Any]]:
        url = f"{OPENFDA_510K_URL}?search={quote(search, safe=_SAFE)}&limit={limit}"
        if self._api_key:
            url += f"&api_key={quote(self._api_key, safe='')}"
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise OpenFdaError(f"openFDA request failed ({type(exc).__name__})") from exc
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise OpenFdaError(f"openFDA HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise OpenFdaError("openFDA returned non-JSON") from exc
        results = body.get("results") if isinstance(body, dict) else None
        return [r for r in results or [] if isinstance(r, dict)]

    def get(self, k_number: str) -> Fda510kRecord | None:
        """The record for one K-number, or None when openFDA has none."""
        rows = self._query(f"k_number:{k_number.strip().upper()}", 1)
        return Fda510kRecord.from_api(rows[0]) if rows else None

    def get_many(self, k_numbers: list[str]) -> dict[str, Fda510kRecord]:
        """Records for several K-numbers in one request (missing ones are absent)."""
        ks = sorted({k.strip().upper() for k in k_numbers if k.strip()})
        if not ks:
            return {}
        search = "+".join(f"k_number:{k}" for k in ks)
        return {
            rec.k_number: rec
            for rec in (Fda510kRecord.from_api(r) for r in self._query(search, len(ks)))
        }

    def search(
        self,
        *,
        device_name: str | None = None,
        applicant: str | None = None,
        limit: int = 10,
    ) -> list[Fda510kRecord]:
        """Name search (AND of the given terms), newest decision first."""
        terms = []
        if device_name and device_name.strip():
            terms.append(f"device_name:{_phrase(device_name)}")
        if applicant and applicant.strip():
            terms.append(f"applicant:{_phrase(applicant)}")
        if not terms:
            return []
        rows = self._query("+AND+".join(terms), limit)
        recs = [Fda510kRecord.from_api(r) for r in rows]
        return sorted(recs, key=lambda r: r.decision_date, reverse=True)
