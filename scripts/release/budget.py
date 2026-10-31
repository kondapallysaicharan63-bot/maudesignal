"""One spend budget shared by every part of a smoke run that can call a live model.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A smoke run may spend at most ``MAX_USD`` and make at most ``MAX_ASKS`` live asks,
``MAX_PHOTOS`` live photos and ``MAX_VOICE`` live spoken questions in total. Before each live
call the caller reserves it (``reserve``): the call is allowed only when the cost already
spent, plus the holds of calls still in flight, plus this call's maximum hold, stays within the
dollar limit, and the count for its kind is not used up. After the call, ``settle`` adds the
real ``cost_usd``. A refused call is never silent: the caller records a FAIL line
``skipped: budget`` (see ``SKIPPED_BUDGET``).

The holds are the DEPLOYED API's default per-request caps (``connector/globalcap.py`` on
track-c-live: ask 0.25, voice 0.30, label 0.30), the most one call can cost there. They are NOT
caps of a local API (the release check has no live job and calls no model). Nothing in the
deployed API reports its caps (``/v1/health`` does not), so they are copied here; if an
operator raises the caps on the deployment, raise these too.

A call that gets no usable answer (timeout, non-200, no ``cost_usd``) may still have run the
model, so it is settled at its full hold (``settle(kind, None)``), never at $0.

The ceiling is $0.60 per run. ``SMOKE_PLAN`` is what a smoke run does and it fits with every
call at its full hold (``tests/unit/test_release_tools.py`` simulates it).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

MAX_USD = 0.60
MAX_ASKS, MAX_PHOTOS, MAX_VOICE = 10, 2, 1
HOLD_USD = {"ask": 0.25, "photo": 0.30, "voice": 0.30}
# The live calls one smoke run plans, in order: one direct question and one spoken question,
# $0.25 + $0.30 = $0.55 at the holds. The browser pass runs in recorded mode through route mocking
# (``e2e_web.py --mock-live``) and spends $0; the load test makes no live asks, only public
# ``check_device_type`` and health calls. ``live()`` makes a photo call only when asked to.
SMOKE_PLAN = {
    "direct": ("ask", "voice"),
    "web": (),
}
LIMITS = {"ask": MAX_ASKS, "photo": MAX_PHOTOS, "voice": MAX_VOICE}
# What a smoke run itself allows: 1 ask, 1 voice, 0 photos (``Smoke`` builds its Budget from this).
SMOKE_LIMITS = {"ask": 1, "photo": 0, "voice": 1}
SKIPPED_BUDGET = "skipped: budget"
KIND_OF_PATH = {"ask": "ask", "label": "photo", "voice": "voice"}  # /v1/live/<path>


@dataclass
class Budget:
    """Thread-safe dollar and count budget for live calls."""

    max_usd: float = MAX_USD
    limits: dict[str, int] = field(default_factory=lambda: dict(LIMITS))
    spent: float = 0.0
    held: float = 0.0
    used: dict[str, int] = field(default_factory=lambda: {"ask": 0, "photo": 0, "voice": 0})
    refused: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reserve(self, kind: str) -> bool:
        """Reserve one call of ``kind``; False (and logged in ``refused``) when it does not fit."""
        hold = HOLD_USD[kind]
        with self._lock:
            fits_usd = self.spent + self.held + hold <= self.max_usd + 1e-9
            fits_count = self.used[kind] < self.limits[kind]
            if not (fits_usd and fits_count):
                self.refused.append(kind)
                return False
            self.used[kind] += 1
            self.held += hold
            return True

    def settle(self, kind: str, cost_usd: float | None) -> None:
        """Release the hold of a reserved call and add what it cost.

        ``cost_usd`` is None when no cost came back (timeout, non-200, missing field): the
        server may still have spent up to the cap, so the full hold is recorded as spent.
        """
        with self._lock:
            self.held = max(0.0, self.held - HOLD_USD[kind])
            self.spent += HOLD_USD[kind] if cost_usd is None else max(0.0, cost_usd)

    def absorb(self, cost_usd: float, counts: dict[str, int]) -> None:
        """Add calls made elsewhere (the browser pass): their counts and cost (incl. holds)."""
        with self._lock:
            self.spent += max(0.0, cost_usd)
            for kind, n in counts.items():
                self.used[kind] = self.used.get(kind, 0) + n

    def remaining_counts(self) -> dict[str, int]:
        """How many more calls of each kind the count limits allow."""
        with self._lock:
            return {k: max(0, self.limits[k] - self.used[k]) for k in self.limits}

    def remaining_usd(self) -> float:
        """Dollars left after spent cost and holds."""
        with self._lock:
            return max(0.0, self.max_usd - self.spent - self.held)

    def max_asks_by_dollars(self) -> int:
        """How many more asks fit in the dollars left, each at its full hold."""
        return int((self.remaining_usd() + 1e-9) // HOLD_USD["ask"])

    def snapshot(self) -> dict[str, object]:
        """Numbers for the report."""
        with self._lock:
            return {
                "max_usd": self.max_usd,
                "spent_usd": round(self.spent, 6),
                "held_usd": round(self.held, 6),
                "used": dict(self.used),
                "limits": dict(self.limits),
                "refused": list(self.refused),
            }
