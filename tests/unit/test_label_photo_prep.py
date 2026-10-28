"""Label-photo preparation: metadata is stripped and the CI guard catches leftovers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "prepare_label_photo", ROOT / "scripts" / "prepare_label_photo.py"
)
assert _spec and _spec.loader
prep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prep)


def _photo_with_exif(path: Path) -> Path:
    im = Image.new("RGB", (4000, 3000), (200, 180, 160))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x0132] = "2026:10:28 09:00:00"  # DateTime
    im.save(path, "JPEG", exif=exif.tobytes())
    return path


def test_prepare_strips_metadata_and_downsizes(tmp_path: Path) -> None:
    src = _photo_with_exif(tmp_path / "IMG_1.jpg")
    assert prep.has_metadata(src)
    out = prep.prepare(src, tmp_path / "labels" / "label-1.jpg")
    assert not prep.has_metadata(out)
    with Image.open(out) as im:
        assert max(im.size) == prep.MAX_SIDE


def test_check_mode_fails_on_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    labels = tmp_path / "labels"
    labels.mkdir()
    prep.prepare(_photo_with_exif(tmp_path / "a.jpg"), labels / "ok.jpg")
    monkeypatch.setattr(sys, "argv", ["x", "--check", str(labels)])
    assert prep.main() == 0
    _photo_with_exif(labels / "raw.jpg")
    assert prep.main() == 1
