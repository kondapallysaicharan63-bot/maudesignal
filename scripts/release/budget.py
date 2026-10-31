"""One spend budget shared by every part of a smoke run that can call a live model.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A smoke run may spend at most ``MAX_USD`` and make at most ``MAX_ASKS`` live asks,
``MAX_PHOTOS`` live photos and ``MAX_VOICE`` live spoken questions in total. Before each live
call the caller reserves it (``reserve``): the call is allowed only when the cost already
spent, plus the holds of calls still in flight, plus this call's maximum hold, stays within the
dollar limit, and the count for its kind is not used up. After the call, ``settle`` adds the
real ``cost_usd``. A refused call is never silent: the caller records a FAIL line
``skipped: budget`` (see ``SKIPPED_BUDGET``).

The holds equal the per-request caps the app is started with in the release live job
(0.12 ask, 0.12 voice, 0.15 photo), so they are the most one call can cost.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

MAX_USD = 0.60
MAX_ASKS, MAX_PHOTOS, MAX_VOICE = 10, 2, 1
HOLD_USD = {"ask": 0.12, "photo": 0.15, "voice": 0.12}
LIMITS = {"ask": MAX_ASKS, "photo": MAX_PHOTOS, "voice": MAX_VOICE}
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

    def settle(self, kind: str, cost_usd: float) -> None:
        """Release the hold of a reserved call and add what it really cost."""
        with self._lock:
            self.held = max(0.0, self.held - HOLD_USD[kind])
            self.spent += max(0.0, cost_usd)

    def absorb(self, cost_usd: float, counts: dict[str, int]) -> None:
        """Add calls made elsewhere (the browser pass): their counts and real cost."""
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

    def snapshot(self) -> dict[str, object]:
        """Numbers for the report."""
        with self._lock:
            return {
                "max_usd": self.max_usd,
                "spent_usd": round(self.spent, 6),
                "used": dict(self.used),
                "limits": dict(self.limits),
                "refused": list(self.refused),
            }
