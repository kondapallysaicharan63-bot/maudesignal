"""Image helpers for the vision features: resize, encode, crop, draw a box.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Pure Pillow, no model calls. Meta's image-understanding docs list the inline
limits these helpers respect: at most 50 images per request, at most 50 MB per
inline image, and PNG / JPEG / WEBP / GIF (https://dev.meta.ai/docs/image-understanding,
read 2026-10-27).
"""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from maudesignal.common.exceptions import MaudeSignalError

MAX_IMAGES_PER_REQUEST = 50
MAX_INLINE_IMAGE_BYTES = 50_000_000
SUPPORTED_MIME = ("image/png", "image/jpeg", "image/webp", "image/gif")


class ImageInputError(MaudeSignalError):
    """The image could not be decoded or is outside the documented limits."""


@dataclass(frozen=True)
class EncodedImage:
    """Image bytes ready to send inline."""

    data: bytes
    mime: str
    width: int
    height: int

    @property
    def data_url(self) -> str:
        """``data:<mime>;base64,...`` URL (accepted by Chat Completions and SAM)."""
        return to_data_url(self.data, self.mime)


def to_data_url(data: bytes, mime: str) -> str:
    """Base64 data URL for inline image input.

    Raises:
        ImageInputError: Unsupported MIME type or above the inline size limit.
    """
    if mime not in SUPPORTED_MIME:
        raise ImageInputError(f"unsupported image type {mime!r}")
    if len(data) > MAX_INLINE_IMAGE_BYTES:
        raise ImageInputError(f"image is {len(data) / 1e6:.1f} MB; the inline limit is 50 MB")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def open_image(data: bytes) -> Image.Image:
    """Decode bytes to an RGB image with EXIF orientation applied.

    SAM coordinates are in the media's displayed pixels (after EXIF rotation), so
    every downstream step works on the transposed image.

    Raises:
        ImageInputError: Not a decodable image.
    """
    if not data:
        raise ImageInputError("image is empty")
    try:
        raw = Image.open(io.BytesIO(data))
        raw.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageInputError(f"not a readable image: {exc}") from exc
    oriented: Image.Image = ImageOps.exif_transpose(raw)
    return oriented.convert("RGB")


def fit(img: Image.Image, max_side: int) -> Image.Image:
    """Downscale so the longest side is at most ``max_side`` (never upscales)."""
    w, h = img.size
    longest = max(w, h)
    if longest <= max_side:
        return img
    scale = max_side / longest
    return img.resize(
        (max(1, round(w * scale)), max(1, round(h * scale))), Image.Resampling.LANCZOS
    )


def encode(img: Image.Image, *, fmt: str = "PNG", quality: int = 90) -> EncodedImage:
    """Encode an image as PNG or JPEG."""
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    return EncodedImage(data=buf.getvalue(), mime=mime, width=img.width, height=img.height)


def prepare(data: bytes, *, max_side: int, fmt: str = "PNG") -> EncodedImage:
    """Decode, orient, downscale and re-encode an image for a model request."""
    return encode(fit(open_image(data), max_side), fmt=fmt)


def crop_with_margin(
    img: Image.Image, box: tuple[int, int, int, int], margin: float = 0.06
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Crop ``box`` (x1, y1, x2, y2, inclusive) plus a relative margin, clamped to the image.

    Returns:
        The crop and the clamped crop box actually used.
    """
    x1, y1, x2, y2 = box
    mx = round((x2 - x1 + 1) * margin)
    my = round((y2 - y1 + 1) * margin)
    cx1 = max(0, x1 - mx)
    cy1 = max(0, y1 - my)
    cx2 = min(img.width, x2 + 1 + mx)
    cy2 = min(img.height, y2 + 1 + my)
    if cx2 <= cx1 or cy2 <= cy1:
        return img, (0, 0, img.width, img.height)
    return img.crop((cx1, cy1, cx2, cy2)), (cx1, cy1, cx2, cy2)


def draw_boxes(
    img: Image.Image,
    boxes: list[tuple[int, int, int, int]],
    *,
    highlight: int | None = 0,
    width: int = 4,
) -> Image.Image:
    """Return a copy with boxes drawn; the ``highlight`` index is drawn in blue."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    for i, b in enumerate(boxes):
        color = (24, 119, 242) if i == highlight else (160, 160, 160)
        draw.rectangle(b, outline=color, width=width)
    return out


def thumbnail_data_url(png_or_jpeg: bytes, *, max_side: int = 220) -> str:
    """Small JPEG thumbnail as a data URL (for stored demo readings)."""
    return encode(fit(open_image(png_or_jpeg), max_side), fmt="JPEG", quality=70).data_url
