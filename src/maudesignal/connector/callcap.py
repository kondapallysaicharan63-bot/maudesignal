"""The one daily cost rule for every call to Meta: reserve the worst case per model call.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

THE RULE (nothing else enforces the daily total):

1. Before EVERY Meta call (each Muse Spark chat completion, including tool-loop and repair
   turns, each Voice Transcribe call, each SAM call) compute that call's WORST-CASE cost:
   Spark = estimated input tokens x input price + ``max_tokens`` x output price (``max_tokens``
   is always set explicitly); SAM = the per-image price; transcription = audio seconds x the
   per-second price.
2. Write ``ledger/<UTC-day>/<uuid>.json`` = ``{"hold_usd": worst_case}`` to the private Blob
   store, list the day's prefix and sum the COUNTED value of every object: ``actual_usd`` if
   the object has ``settled_ok`` true, else ``hold_usd``.
3. If the sum (ours included) is over the cap, delete our own object and make no call (a
   recorded answer is shown). If the write, the list or a read fails, no call is made either.
4. After the call, ONLY if the provider returned a successful response with usage, overwrite
   our own object with ``{"hold_usd", "actual_usd", "settled_ok": true}``. On any exception,
   timeout, missing usage or failed overwrite the object is left as it is: it counts its
   worst-case hold for the rest of the day.

Because the real cost of a call never exceeds its worst case, the day's total can only be
over-counted, never under-counted. Two calls that reserve at the same moment can each pass, so
the cap enforced is the daily total (``MAUDESIGNAL_LIVE_DAILY_USD``, 3.00) minus the largest
possible single-call hold, :data:`MAX_CALL_HOLD_USD` (0.10): a call whose worst case is above
that is not made. With the defaults the enforced cap is 2.90. This bound assumes a listing
sees the objects just written (list-after-put visibility); if listings lag for three or more
simultaneous instances the overshoot could reach (k-1) x 0.10.
"""

from __future__ import annotations

import json
import math
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from typing import Any

from maudesignal.common.logging import get_logger
from maudesignal.connector.blob_store import BlobRef, ObjectGoneError, RecordStore, StoreError
from maudesignal.connector.globalcap import global_daily_usd
from maudesignal.copilot.spend import SpendLimitError, chat_cost_usd
from maudesignal.vision.sam import SAM_USD_PER_IMAGE

logger = get_logger(__name__)

LEDGER_PREFIX = "ledger"
#: Day-level flags (for example "research is switched off for today"). Kept OUTSIDE the ledger
#: prefix so a flag is never read as a ledger object.
FLAG_PREFIX = "ledger-flags"
#: The largest worst-case hold one call may place. A call above it is not made.
MAX_CALL_HOLD_USD = 0.10
#: Output cap used when a caller did not set ``max_tokens`` (every call must have one).
DEFAULT_MAX_TOKENS = 8000
#: Conservative input tokens for one image part (its bytes are not counted as text).
IMAGE_TOKENS = 8000
#: Worst-case input tokens are estimated from the prompt's UTF-8 size divided by this.
BYTES_PER_TOKEN = 3
#: Voice Transcribe price per audio second ($0.18 per audio hour), billed per whole second.
VOICE_USD_PER_SECOND = 0.18 / 3600.0
_READ_WORKERS = 8


class CallRefusedError(SpendLimitError):
    """The call was not made: today's cap is reached, the ledger failed, or the hold is too big.

    ``cap`` is ``"cap"``, ``"ledger"`` or ``"size"``. A subclass of ``SpendLimitError`` so every
    existing caller already shows a recorded answer for it. The message holds no token.
    """


def enforced_cap(daily_usd: float | None = None) -> float:
    """The cap the ledger enforces: the daily total minus the largest single-call hold."""
    total = global_daily_usd() if daily_usd is None else daily_usd
    return max(0.0, round(total - MAX_CALL_HOLD_USD, 6))


# -- worst-case holds ---------------------------------------------------------------------


def _strip_images(obj: Any, counter: list[int]) -> Any:
    """``obj`` with every image part reduced to its type (the bytes are priced separately)."""
    if isinstance(obj, dict):
        if obj.get("type") in ("image_url", "input_image"):
            counter[0] += 1
            return {"type": obj.get("type")}
        return {k: _strip_images(v, counter) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_images(v, counter) for v in obj]
    return obj


def estimate_input_tokens(kwargs: dict[str, Any]) -> int:
    """Conservative input tokens of a chat request: UTF-8 bytes / 3, plus a flat price per image."""
    images = [0]
    prompt = {
        k: _strip_images(kwargs[k], images)
        for k in ("messages", "tools", "response_format")
        if k in kwargs
    }
    text = json.dumps(prompt, default=str, ensure_ascii=False)
    return math.ceil(len(text.encode("utf-8")) / BYTES_PER_TOKEN) + images[0] * IMAGE_TOKENS


def chat_hold_usd(kwargs: dict[str, Any]) -> float:
    """Worst-case cost of one chat call: input estimate x input price + max_tokens x output."""
    model = str(kwargs.get("model") or "")
    return chat_cost_usd(model, estimate_input_tokens(kwargs), int(kwargs["max_tokens"]))


def sam_hold_usd(images: int = 1) -> float:
    """Worst-case cost of a SAM call: the per-image price."""
    return round(images * SAM_USD_PER_IMAGE, 6)


def transcribe_hold_usd(audio_seconds: float) -> float:
    """Worst-case cost of transcribing a clip: one more whole second than its length."""
    return round((math.ceil(max(0.0, audio_seconds)) + 1) * VOICE_USD_PER_SECOND, 6)


# -- the ledger ---------------------------------------------------------------------------


class Reservation:
    """One call's own ledger object. Settling only ever rewrites this object."""

    def __init__(self, store: RecordStore, pathname: str, hold_usd: float) -> None:
        """Create the handle for the object at ``pathname``."""
        self._store, self.pathname, self.hold_usd = store, pathname, hold_usd

    def settle(self, actual_usd: float) -> bool:
        """Record the real cost. True when written; False leaves the hold counted."""
        actual = round(float(actual_usd), 6)
        if actual > self.hold_usd + 1e-9:
            # By construction this cannot happen; if it does the real cost is stored (it is
            # counted when settled) and the breach is logged so the price table is fixed.
            logger.warning(
                "call_cost_above_hold", hold_usd=self.hold_usd, actual_usd=actual, path="ledger"
            )
        record = {"hold_usd": self.hold_usd, "actual_usd": actual, "settled_ok": True}
        try:
            self._store.overwrite_json(self.pathname, record)
        except Exception:  # noqa: BLE001 - any failure leaves the worst-case hold in place
            logger.error("call_settle_failed", hold_usd=self.hold_usd, actual_usd=actual)
            return False
        return True


class CallLedger:
    """Per-call spend ledger in the private Blob store (one small object per model call)."""

    def __init__(
        self,
        store: RecordStore,
        *,
        cap_usd: float | None = None,
        today: Callable[[], date] | None = None,
    ) -> None:
        """Create the ledger.

        Args:
            store: The private Blob store (a fake in tests).
            cap_usd: The enforced cap; default ``MAUDESIGNAL_LIVE_DAILY_USD`` minus
                :data:`MAX_CALL_HOLD_USD`.
            today: UTC date clock (tests).
        """
        self._store = store
        self.cap_usd = enforced_cap() if cap_usd is None else cap_usd
        self._today = today or (lambda: datetime.now(UTC).date())
        self._settled: dict[str, float] = {}  # path -> actual USD, settled objects never change
        self._lock = threading.Lock()

    @staticmethod
    def _prefix(day: str) -> str:
        return f"{LEDGER_PREFIX}/{day}/"

    def _counted(self, ref: BlobRef) -> float | None:
        """One object's counted USD (an unreadable listed object counts the max hold)."""
        with self._lock:
            cached = self._settled.get(ref.pathname)
        if cached is not None:
            return cached
        try:
            raw = json.loads(self._store.get(ref))
        except ObjectGoneError:
            # A listed object that cannot be read is never counted as 0 (a 404 can come from an
            # auth or URL mismatch). It is counted at the largest possible hold; the one
            # legitimate case, a refused call's own deleted object, then over-counts briefly.
            logger.warning("ledger_object_unreadable_counted_at_max")
            return MAX_CALL_HOLD_USD
        except (StoreError, ValueError):
            raise CallRefusedError("ledger", "The spend ledger could not be read.") from None
        try:
            hold = float(raw["hold_usd"])
            settled = raw.get("settled_ok") is True
            actual = float(raw["actual_usd"]) if settled else 0.0
        except (KeyError, TypeError, ValueError, AttributeError):
            raise CallRefusedError("ledger", "The spend ledger could not be read.") from None
        value = actual if settled else hold
        if not math.isfinite(value) or value < 0:
            raise CallRefusedError("ledger", "The spend ledger could not be read.")
        if settled:
            with self._lock:
                self._settled[ref.pathname] = value
        return value

    def total(self, day: str | None = None) -> float:
        """The day's counted total. Raises :class:`CallRefusedError` when it is unreadable."""
        d = day or self._today().isoformat()
        return self._sum(d)[0]

    def _sum(self, day: str) -> tuple[float, set[str]]:
        try:
            refs = self._store.list_prefix(self._prefix(day), strict=True)
        except StoreError:
            raise CallRefusedError("ledger", "The spend ledger could not be listed.") from None
        todo = [r for r in refs if r.pathname not in self._settled]
        if len(todo) > 1:
            with ThreadPoolExecutor(max_workers=min(_READ_WORKERS, len(todo))) as pool:
                values = dict(
                    zip((r.pathname for r in todo), pool.map(self._counted, todo), strict=True)
                )
        else:
            values = {r.pathname: self._counted(r) for r in todo}
        total = 0.0
        for r in refs:
            v = values[r.pathname] if r.pathname in values else self._counted(r)
            total += v or 0.0
        return round(total, 6), {r.pathname for r in refs}

    def _take_back(self, pathname: str) -> None:
        """Delete our own object after a refusal; if that fails it stays (only over-counts)."""
        try:
            ref = next(
                (r for r in self._store.list_prefix(pathname) if r.pathname == pathname), None
            )
            if ref is not None:
                self._store.delete(ref)
        except StoreError:
            logger.error("call_refused_hold_kept")

    # -- day-level flags (research kill switch) ---------------------------------------------

    def _flag_path(self, name: str, day: str) -> str:
        return f"{FLAG_PREFIX}/{day}/{name}.json"

    def set_flag(self, name: str, reason: str = "") -> bool:
        """Raise the day-level flag ``name`` (for example ``research``). True when written."""
        day = self._today().isoformat()
        try:
            self._store.put_json(self._flag_path(name, day), {"flag": name, "reason": reason[:80]})
        except StoreError:
            logger.error("ledger_flag_write_failed", flag=name)
            return False
        logger.warning("ledger_flag_set", flag=name, reason=reason[:80])
        return True

    def flag_set(self, name: str) -> bool:
        """True when today's flag ``name`` is raised, or when it cannot be read (fail closed)."""
        path = self._flag_path(name, self._today().isoformat())
        try:
            return any(r.pathname == path for r in self._store.list_prefix(path, strict=True))
        except StoreError:
            return True

    def reserve(
        self,
        hold_usd: float,
        *,
        max_hold_usd: float = MAX_CALL_HOLD_USD,
        cap_usd: float | None = None,
        kind: str | None = None,
        exclusive: bool = False,
        blocked_by: str | None = None,
    ) -> Reservation:
        """Hold ``hold_usd`` before a call, or raise :class:`CallRefusedError`.

        Writes our object, lists the day, sums the counted values and compares the sum
        (ours included) with the cap. Nothing is called on any failure.

        The keyword arguments are used only by Research mode; their defaults keep the rule
        above unchanged for every other call. ``max_hold_usd`` is the largest hold allowed for
        this call; ``cap_usd`` a lower cap for it; ``kind`` names the object
        (``<kind>-<uuid>.json``); ``exclusive`` refuses the call while another unsettled object
        of the same kind is listed (one such call in flight per day); ``blocked_by`` refuses
        it while that day-level flag is raised.
        """
        hold = round(float(hold_usd), 6)
        if not math.isfinite(hold) or hold < 0:
            raise CallRefusedError("size", "The call's worst-case cost is not valid.")
        if hold > max_hold_usd + 1e-9:
            raise CallRefusedError(
                "size", "The call's worst-case cost is above the per-call limit."
            )
        if blocked_by is not None and self.flag_set(blocked_by):
            raise CallRefusedError("flag", "This kind of call is switched off for today.")
        cap = self.cap_usd if cap_usd is None else min(cap_usd, self.cap_usd)
        day = self._today().isoformat()
        name = f"{kind}-{uuid.uuid4().hex}" if kind else uuid.uuid4().hex
        path = f"{self._prefix(day)}{name}.json"
        try:
            self._store.put_json(path, {"hold_usd": hold})
        except StoreError:
            raise CallRefusedError("ledger", "The spend ledger could not be written.") from None
        try:
            total, listed = self._sum(day)
        except CallRefusedError:
            self._take_back(path)
            raise
        if path not in listed:
            total = round(total + hold, 6)  # our write is not listed yet: count it anyway
        if total > cap + 1e-9:
            self._take_back(path)
            raise CallRefusedError("cap", "Today's live-call budget is used up.")
        if exclusive and kind:
            marker = f"{self._prefix(day)}{kind}-"
            with self._lock:
                busy = [
                    p
                    for p in listed
                    if p != path and p.startswith(marker) and p not in self._settled
                ]
            if busy:
                self._take_back(path)
                raise CallRefusedError("busy", "Another call of this kind is in flight.")
        if blocked_by is not None and self.flag_set(blocked_by):
            # Checked again AFTER our object is listed: a call of this kind that finished in
            # between raised the flag before it settled, so we see the flag here.
            self._take_back(path)
            raise CallRefusedError("flag", "This kind of call is switched off for today.")
        return Reservation(self._store, path, hold)

    def metered(
        self,
        hold_usd: float,
        call: Callable[[], Any],
        actual_usd: Callable[[Any], float | None],
        *,
        kill_flag: str | None = None,
        **reserve_options: Any,
    ) -> Any:
        """Reserve ``hold_usd``, run ``call`` and settle after a successful reply with usage.

        ``actual_usd(result)`` returns the real cost, or ``None`` when the reply has no usage
        (the hold then stays). An exception from ``call`` propagates with the hold in place.

        Research mode only: ``reserve_options`` go to :meth:`reserve`, and with ``kill_flag``
        a real cost above the hold is still recorded but also raises that day-level flag, so
        no further call of that kind is reserved today. Other callers pass neither.
        """
        reservation = self.reserve(hold_usd, **reserve_options)
        try:
            result = call()
        except BaseException:
            if reserve_options.get("exclusive"):
                # An exclusive (research) call that failed after it was sent may still be
                # billed for an unknown amount: raise the day flag FIRST, so the freed slot can
                # never let a second such call through today. Then mark its object settled AT
                # ITS HOLD, so it counts exactly what an unsettled hold counts but no longer
                # blocks as "in flight". Other calls are untouched.
                if kill_flag is not None:
                    self.set_flag(kill_flag, "call failed after it was sent")
                reservation.settle(reservation.hold_usd)
            raise
        try:
            actual = actual_usd(result)
        except Exception:  # noqa: BLE001 - unreadable usage: the hold stays
            actual = None
        if actual is not None:
            if kill_flag is not None and actual > reservation.hold_usd + 1e-9:
                # Raised BEFORE the settle, so no call of this kind can be reserved between.
                self.set_flag(kill_flag, "real cost above the hold")
            reservation.settle(actual)
        return result


# -- the single entry point for Meta calls ------------------------------------------------


def _usage_cost(resp: Any, model: str) -> float | None:
    """Real cost from the response's usage, or ``None`` when it carries none."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    tokens_in = getattr(usage, "prompt_tokens", None)
    tokens_out = getattr(usage, "completion_tokens", None)
    if tokens_in is None or tokens_out is None:
        return None
    return chat_cost_usd(model, int(tokens_in), int(tokens_out))


class CallMeter:
    """Wraps each kind of Meta call in :meth:`CallLedger.metered`. Used by every live path."""

    def __init__(self, ledger: CallLedger) -> None:
        """Create the meter on ``ledger``."""
        self.ledger = ledger

    def chat(self, create: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
        """One Spark chat completion (tool round, final answer or repair turn)."""
        call_kwargs = dict(kwargs)
        if not call_kwargs.get("max_tokens"):
            call_kwargs["max_tokens"] = DEFAULT_MAX_TOKENS
        model = str(call_kwargs.get("model") or "")
        return self.ledger.metered(
            chat_hold_usd(call_kwargs),
            lambda: create(**call_kwargs),
            lambda resp: _usage_cost(resp, model),
        )

    def sam(self, call: Callable[[], Any]) -> Any:
        """One SAM segmentation call (the result's ``cost_usd`` is its images x price)."""
        return self.ledger.metered(
            sam_hold_usd(1), call, lambda res: float(res.cost_usd) if res.usage else None
        )

    def transcribe(self, audio_seconds: float, call: Callable[[], Any]) -> Any:
        """One Voice Transcribe call (settled from the duration the provider reports)."""

        def actual(tr: Any) -> float | None:
            seconds = getattr(tr, "duration_s", None)
            if seconds is None:
                return None
            return round(math.floor(max(0.0, float(seconds))) * VOICE_USD_PER_SECOND, 6)

        return self.ledger.metered(transcribe_hold_usd(audio_seconds), call, actual)
