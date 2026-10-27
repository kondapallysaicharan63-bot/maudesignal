"""Device label photo → 510(k) record → product code (SAM 3.1 + Muse Spark).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

1. **Find the label** — SAM 3.1 with the noun phrase ``"label"`` (then ``"text"``,
   then ``"barcode"``); the best box (confidence, then area) is cropped with a
   margin. No match, or SAM unavailable → the full photo is read, and the result
   says so.
2. **Read it** — Muse Spark reads the crop (``skills/device-label-reader``, strict
   JSON): device name, manufacturer, model, K-number, UDI / GTIN, lot, serial.
3. **Check it** — deterministic: K-number format, existence in openFDA 510(k) (and
   in the local catalog when given), GS1 check digit on the GTIN. With no K-number,
   openFDA is searched by name and the candidates are RETURNED; an ambiguous match
   is never auto-picked.
4. **Route it** — the product code (from the verified K-number, or from a name
   search whose candidates all share one product code) lets the UI open that
   product's signals.

Lot and serial numbers are kept in memory for the analyst's session only:
:meth:`LabelResult.to_dict` drops them unless explicitly asked, and nothing in this
module logs or stores them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from PIL import Image

from maudesignal.extraction.skill_loader import LoadedSkill
from maudesignal.vision.fda_pdf import normalize_k_number
from maudesignal.vision.images import crop_with_margin, encode, fit, open_image
from maudesignal.vision.openfda510k import Fda510kRecord, OpenFda510k, OpenFdaError
from maudesignal.vision.sam import SamBox, SamClient, SamError, SamResult, best_record
from maudesignal.vision.spark import DEFAULT_VISION_MODEL, call_spark_json, image_part, load_skill
from maudesignal.vision.verify import Check, norm_company, norm_text

SKILL_NAME = "device-label-reader"
LABEL_FIELDS: tuple[str, ...] = (
    "device_name",
    "manufacturer",
    "model_number",
    "k_number",
    "udi",
    "gtin",
    "lot",
    "serial",
)
SESSION_ONLY_FIELDS = frozenset({"lot", "serial"})
SAM_PROMPTS: tuple[str, ...] = ("label", "text", "barcode")
SAM_MAX_SIDE = 1600
READ_MAX_SIDE = 1600
MIN_BOX_SHARE = 0.01  # ignore specks under 1% of the image

KStatus = Literal["verified", "not_in_openfda", "bad_format", "illegible", "not_printed"]
MatchBasis = Literal[
    "k_number", "single_name_match", "name_match_one_product_code", "ambiguous", "none"
]


@dataclass(frozen=True)
class LabelField:
    """One field read from the label."""

    value: str
    legibility: str

    @property
    def present(self) -> bool:
        """The field was read (fully or partly)."""
        return bool(self.value) and self.legibility not in ("not_present", "illegible")


def gtin_check_digit_ok(digits: str) -> bool:
    """GS1 mod-10 check digit for GTIN-8/12/13/14."""
    d = re.sub(r"\D", "", digits or "")
    if len(d) not in (8, 12, 13, 14):
        return False
    body, check = d[:-1], int(d[-1])
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def parse_udi(udi: str) -> dict[str, str]:
    """Split a human-readable GS1 UDI ``(01)...(17)...`` into application identifiers."""
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"\((\d{2,4})\)([^(]*)", udi)}


@dataclass
class LabelResult:
    """Everything the UI needs to show a label reading honestly."""

    image_width: int
    image_height: int
    fields: dict[str, LabelField]
    overall_legibility: str
    sam_prompts_tried: list[str] = field(default_factory=list)
    sam_prompt: str | None = None
    sam_boxes: list[SamBox] = field(default_factory=list)
    chosen_box: SamBox | None = None
    crop_box: tuple[int, int, int, int] | None = None
    sam_note: str = ""
    checks: list[Check] = field(default_factory=list)
    k_number: str | None = None
    k_status: KStatus = "not_printed"
    openfda: Fda510kRecord | None = None
    candidates: list[Fda510kRecord] = field(default_factory=list)
    product_code: str | None = None
    match_basis: MatchBasis = "none"
    gtin: str | None = None
    gtin_valid: bool | None = None
    model: str = ""
    skill_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    spark_cost_usd: float = 0.0
    sam_cost_usd: float = 0.0

    @property
    def cost_usd(self) -> float:
        """SAM + Muse Spark cost."""
        return round(self.spark_cost_usd + self.sam_cost_usd, 6)

    @property
    def needs_human_pick(self) -> bool:
        """Name search found several products: the analyst must choose."""
        return self.match_basis == "ambiguous"

    def to_dict(self, *, include_session_fields: bool = False) -> dict[str, Any]:
        """JSON form. Lot / serial are omitted unless ``include_session_fields``."""
        fields = {
            k: {"value": v.value, "legibility": v.legibility}
            for k, v in self.fields.items()
            if include_session_fields or k not in SESSION_ONLY_FIELDS
        }
        return {
            "kind": "device_label_reading",
            "image_size": [self.image_width, self.image_height],
            "fields": fields,
            "session_fields_omitted": not include_session_fields,
            "overall_legibility": self.overall_legibility,
            "sam": {
                "prompts_tried": self.sam_prompts_tried,
                "prompt_used": self.sam_prompt,
                "boxes": [_box_dict(b) for b in self.sam_boxes],
                "chosen_box": _box_dict(self.chosen_box) if self.chosen_box else None,
                "crop_box": list(self.crop_box) if self.crop_box else None,
                "note": self.sam_note,
            },
            "checks": [c.to_dict() for c in self.checks],
            "k_number": self.k_number,
            "k_status": self.k_status,
            "openfda": self.openfda.to_dict() if self.openfda else None,
            "candidates": [c.to_dict() for c in self.candidates],
            "product_code": self.product_code,
            "match_basis": self.match_basis,
            "gtin": self.gtin,
            "gtin_valid": self.gtin_valid,
            "model": self.model,
            "skill_version": self.skill_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": {
                "spark": self.spark_cost_usd,
                "sam": self.sam_cost_usd,
                "total": self.cost_usd,
            },
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LabelResult:
        """Inverse of :meth:`to_dict` (for recorded demo runs)."""
        sam = d.get("sam") or {}
        size = d.get("image_size") or [0, 0]
        cost = d.get("cost_usd") or {}
        ofda = d.get("openfda")
        return cls(
            image_width=int(size[0]),
            image_height=int(size[1]),
            fields={
                k: LabelField(str(v.get("value") or ""), str(v.get("legibility") or ""))
                for k, v in (d.get("fields") or {}).items()
            },
            overall_legibility=str(d.get("overall_legibility") or ""),
            sam_prompts_tried=[str(p) for p in sam.get("prompts_tried") or []],
            sam_prompt=sam.get("prompt_used"),
            sam_boxes=[_box_from(b) for b in sam.get("boxes") or []],
            chosen_box=_box_from(sam["chosen_box"]) if sam.get("chosen_box") else None,
            crop_box=_crop_from(sam.get("crop_box")),
            sam_note=str(sam.get("note") or ""),
            checks=[
                Check(str(c["source"]), c["outcome"], str(c.get("detail") or ""))
                for c in d.get("checks") or []
            ],
            k_number=d.get("k_number"),
            k_status=d.get("k_status") or "not_printed",
            openfda=Fda510kRecord.from_dict(ofda) if isinstance(ofda, dict) else None,
            candidates=[Fda510kRecord.from_dict(c) for c in d.get("candidates") or []],
            product_code=d.get("product_code"),
            match_basis=d.get("match_basis") or "none",
            gtin=d.get("gtin"),
            gtin_valid=d.get("gtin_valid"),
            model=str(d.get("model") or ""),
            skill_version=str(d.get("skill_version") or ""),
            input_tokens=int(d.get("input_tokens") or 0),
            output_tokens=int(d.get("output_tokens") or 0),
            spark_cost_usd=float(cost.get("spark") or 0.0),
            sam_cost_usd=float(cost.get("sam") or 0.0),
        )


def _box_dict(b: SamBox | None) -> dict[str, Any] | None:
    if b is None:
        return None
    return {"x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2, "w": b.w, "h": b.h, "c": b.confidence}


def _crop_from(v: Any) -> tuple[int, int, int, int] | None:
    if not isinstance(v, list | tuple) or len(v) != 4:
        return None
    return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))


def _box_from(d: dict[str, Any]) -> SamBox:
    c = d.get("c")
    return SamBox(
        int(d["x1"]),
        int(d["y1"]),
        int(d["x2"]),
        int(d["y2"]),
        int(d["w"]),
        int(d["h"]),
        float(c) if c is not None else None,
    )


def locate_label(
    sam: SamClient | None, img: Image.Image, prompts: tuple[str, ...] = SAM_PROMPTS
) -> tuple[list[SamResult], SamResult | None, str]:
    """Run SAM prompts in order until one returns a usable box.

    Returns:
        (every result, the result used or None, a note for the UI).
    """
    if sam is None:
        return [], None, "SAM not configured; the full photo was read"
    sent = encode(img, fmt="JPEG")
    results: list[SamResult] = []
    min_area = MIN_BOX_SHARE * img.width * img.height
    for prompt in prompts:
        try:
            res = sam.segment(sent, prompt)
        except SamError as exc:
            return results, None, f"SAM failed ({exc}); the full photo was read"
        results.append(res)
        usable = [r for r in res.records if r.box.scaled_to(img.width, img.height).area >= min_area]
        if usable:
            res.records = usable
            return results, res, ""
    return results, None, f"SAM found no {' / '.join(prompts)}; the full photo was read"


def read_device_label(
    image_bytes: bytes,
    *,
    client: Any,
    sam: SamClient | None,
    openfda: OpenFda510k | None,
    model: str = DEFAULT_VISION_MODEL,
    skill: LoadedSkill | None = None,
    catalog_k_numbers: set[str] | None = None,
) -> LabelResult:
    """Run the full label flow on one photo.

    Args:
        image_bytes: The photo (JPEG / PNG / WEBP; EXIF orientation honoured).
        client: OpenAI-compatible client for Muse Spark.
        sam: SAM client, or None to read the full photo.
        openfda: openFDA 510(k) client, or None to skip online checks.
        model: Muse Spark model id.
        skill: ``device-label-reader`` (loaded from ``skills/`` if omitted).
        catalog_k_numbers: K-numbers in the local device catalog (extra check).

    Returns:
        The reading, its checks, candidates, and the product code when resolvable.

    Raises:
        ImageInputError: The photo cannot be decoded.
        VisionModelError: The Muse Spark call failed.
    """
    skill = skill or load_skill(SKILL_NAME)
    img = fit(open_image(image_bytes), SAM_MAX_SIDE)
    sam_results, used, note = locate_label(sam, img)
    crop, crop_box, chosen = img, None, None
    if used is not None:
        rec = best_record(used.records)
        if rec is not None:
            chosen = rec.box.scaled_to(img.width, img.height)
            crop, crop_box = crop_with_margin(img, chosen.as_tuple())
    out = call_spark_json(
        client,
        skill=skill,
        parts=[image_part(encode(fit(crop, READ_MAX_SIDE), fmt="PNG"))],
        model=model,
        max_tokens=1024,
    )
    raw_fields = out.data.get("fields") or {}
    fields = {
        name: LabelField(
            str((raw_fields.get(name) or {}).get("value") or "").strip(),
            str((raw_fields.get(name) or {}).get("legibility") or "not_present"),
        )
        for name in LABEL_FIELDS
    }
    result = LabelResult(
        image_width=img.width,
        image_height=img.height,
        fields=fields,
        overall_legibility=str(out.data.get("overall_legibility") or ""),
        sam_prompts_tried=[r.prompt for r in sam_results],
        sam_prompt=used.prompt if used else None,
        sam_boxes=[r.box.scaled_to(img.width, img.height) for r in used.records] if used else [],
        chosen_box=chosen,
        crop_box=crop_box,
        sam_note=note,
        model=out.model,
        skill_version=skill.version,
        input_tokens=out.input_tokens,
        output_tokens=out.output_tokens,
        spark_cost_usd=out.cost_usd,
        sam_cost_usd=round(sum(r.cost_usd for r in sam_results), 6),
    )
    verify_label(result, openfda=openfda, catalog_k_numbers=catalog_k_numbers)
    return result


def verify_label(
    result: LabelResult,
    *,
    openfda: OpenFda510k | None,
    catalog_k_numbers: set[str] | None = None,
) -> LabelResult:
    """Deterministic checks; fills k_status, candidates, product_code (in place)."""
    f = result.fields
    _check_gtin(result)
    kf = f.get("k_number", LabelField("", "not_present"))
    if kf.legibility == "illegible":
        result.k_status = "illegible"
    elif kf.value:
        try:
            result.k_number = normalize_k_number(kf.value)
        except ValueError:
            result.k_status = "bad_format"
            result.checks.append(Check("k_format", "fail", f"{kf.value!r} is not K + 6 digits"))
    if result.k_number:
        result.checks.append(Check("k_format", "pass", f"{result.k_number} is K + 6 digits"))
        if catalog_k_numbers is not None:
            in_cat = result.k_number in {k.upper() for k in catalog_k_numbers}
            result.checks.append(
                Check(
                    "catalog",
                    "pass" if in_cat else "n/a",
                    "in the local device catalog" if in_cat else "not in the local catalog",
                )
            )
        rec = _safe(lambda: openfda.get(result.k_number or "") if openfda else None, result)
        if rec is not None:
            result.k_status = "verified"
            result.openfda = rec
            result.product_code = rec.product_code
            result.match_basis = "k_number"
            result.checks.append(
                Check("openfda", "pass", f"{rec.k_number}: {rec.device_name} ({rec.applicant})")
            )
            _check_name_consistency(result, rec)
            return result
        if openfda is not None:
            result.k_status = "not_in_openfda"
            result.checks.append(Check("openfda", "fail", f"{result.k_number} not in openFDA"))
    _name_search(result, openfda)
    return result


def _safe(fn: Any, result: LabelResult) -> Any:
    try:
        return fn()
    except OpenFdaError as exc:
        result.checks.append(Check("openfda", "n/a", f"openFDA unavailable: {exc}"))
        return None


def _check_gtin(result: LabelResult) -> None:
    gt = result.fields.get("gtin", LabelField("", "not_present"))
    udi = result.fields.get("udi", LabelField("", "not_present"))
    digits = re.sub(r"\D", "", gt.value) if gt.value else ""
    if not digits and udi.value:
        digits = re.sub(r"\D", "", parse_udi(udi.value).get("01", ""))
    if not digits:
        return
    result.gtin = digits
    result.gtin_valid = gtin_check_digit_ok(digits)
    result.checks.append(
        Check(
            "gtin_check_digit",
            "pass" if result.gtin_valid else "fail",
            f"GTIN {digits}: GS1 check digit {'valid' if result.gtin_valid else 'INVALID'}",
        )
    )


def _check_name_consistency(result: LabelResult, rec: Fda510kRecord) -> None:
    name = result.fields.get("device_name", LabelField("", "not_present")).value
    mfr = result.fields.get("manufacturer", LabelField("", "not_present")).value
    notes = []
    if (
        name
        and norm_text(name) not in norm_text(rec.device_name)
        and norm_text(rec.device_name) not in norm_text(name)
    ):
        notes.append(f"label name {name!r} vs openFDA {rec.device_name!r}")
    if mfr and norm_company(mfr) != norm_company(rec.applicant):
        notes.append(f"label maker {mfr!r} vs applicant {rec.applicant!r}")
    if notes:
        result.checks.append(Check("label_vs_openfda", "fail", "; ".join(notes) + " — human check"))
    else:
        result.checks.append(Check("label_vs_openfda", "pass", "name / maker consistent"))


def _name_search(result: LabelResult, openfda: OpenFda510k | None) -> None:
    name = result.fields.get("device_name", LabelField("", "not_present"))
    mfr = result.fields.get("manufacturer", LabelField("", "not_present"))
    if openfda is None or not name.present:
        result.match_basis = "none"
        return
    cands: list[Fda510kRecord] = (
        _safe(
            lambda: openfda.search(
                device_name=name.value, applicant=mfr.value if mfr.present else None
            ),
            result,
        )
        or []
    )
    if not cands and mfr.present:
        cands = _safe(lambda: openfda.search(device_name=name.value), result) or []
    result.candidates = cands
    codes = sorted({c.product_code for c in cands if c.product_code})
    if len(cands) == 1:
        result.match_basis = "single_name_match"
        result.product_code = cands[0].product_code
    elif len(codes) == 1:
        result.match_basis = "name_match_one_product_code"
        result.product_code = codes[0]
    elif cands:
        result.match_basis = "ambiguous"
    result.checks.append(
        Check(
            "openfda_name_search",
            "pass" if result.product_code else ("fail" if not cands else "n/a"),
            f"{len(cands)} candidate(s), product code(s): {', '.join(codes) or 'none'}"
            + (" — analyst must pick" if result.match_basis == "ambiguous" else ""),
        )
    )
