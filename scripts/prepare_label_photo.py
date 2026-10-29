"""Prepare a device-label photo for the public demo: strip all metadata, downsize.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Run this on your own machine BEFORE committing a photo. It re-encodes the image
pixels only (no EXIF, GPS, camera or timestamp metadata survives) and caps the
long side at 2000 px. It cannot see serial numbers or QR codes: crop or cover
them yourself first — never commit an original photo with a serial or QR visible.

    python3.12 scripts/prepare_label_photo.py IMG_1234.jpg demo/vision/labels/label-1.jpg
    python3.12 scripts/prepare_label_photo.py --check demo/vision/labels   # CI guard
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MAX_SIDE = 2000


def has_metadata(path: Path) -> bool:
    """True when the file still carries EXIF / GPS / XMP / text metadata."""
    with Image.open(path) as im:
        if im.getexif():
            return True
        info = {k.lower() for k in im.info}
        return bool(info & {"exif", "xmp", "xml:com.adobe.xmp", "comment", "icc_profile_name"})


def prepare(src: Path, dst: Path) -> Path:
    """Write a metadata-free, downsized copy of ``src`` to ``dst``."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        clean = Image.new("RGB", im.size)
        clean.paste(im)  # pixels only: nothing from the original header is carried over
    dst.parent.mkdir(parents=True, exist_ok=True)
    fmt = "PNG" if dst.suffix.lower() == ".png" else "JPEG"
    clean.save(dst, fmt, **({"quality": 90} if fmt == "JPEG" else {}))
    return dst


def main() -> int:
    """CLI; exit 1 when ``--check`` finds a photo with metadata."""
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path, nargs="?")
    ap.add_argument("--check", action="store_true", help="fail if any photo in SRC has metadata")
    args = ap.parse_args()
    if args.check:
        photos = [p for p in sorted(args.src.iterdir()) if p.suffix.lower() in SUFFIXES]
        bad = [p.name for p in photos if has_metadata(p)]
        for name in bad:
            print(f"[labels] {name}: still carries metadata — run prepare_label_photo.py on it")
        print(f"[labels] {len(photos)} photo(s) checked, {len(bad)} with metadata")
        return 1 if bad else 0
    if args.dst is None:
        ap.error("give a destination path")
    out = prepare(args.src, args.dst)
    print(f"wrote {out} (metadata stripped, long side <= {MAX_SIDE}px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
