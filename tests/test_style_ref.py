"""`style ref` 시험. 그림은 모두 코드로 만든 합성 그림이다. 배선 전이라 `run` 을 Namespace 로 바로 부른다."""

from __future__ import annotations

import argparse
import base64

import numpy as np
import pytest
from PIL import Image

from arttool import errors, image
from arttool.style import ref

RED = (200, 30, 30, 255)


def _args(in_file, out_file, **extra):
   values = {"in_file": str(in_file), "out_file": str(out_file), "canvas": "128x128", "crop": None,
             "colors": 32, "b64": None, "max_kb": 12.0, "report": None}
   values.update(extra)
   return argparse.Namespace(**values)


def _save(tmp_path, arr, name="a.png"):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _noise(w, h, seed=1):
   rng = np.random.default_rng(seed)
   arr = rng.integers(0, 256, size=(h, w, 4), dtype=np.uint8)
   arr[:, :, 3] = 255
   return arr


def test_ref_crops_bbox_center_when_larger(tmp_path):
   arr = image.new(300, 200)
   arr[120:160, 200:260] = RED   # bbox 가운데 (230, 140)
   src = _save(tmp_path, arr)
   result = ref.run(_args(src, tmp_path / "ref.png", canvas="64x64"))
   assert result["size"] == [64, 64]
   assert result["crop"] == [198, 108, 64, 64]
   assert any(w["rule"] == "ref.cropped" for w in result["warnings"])
   out = image.load(tmp_path / "ref.png")
   assert image.bbox(out) == (2, 12, 62, 52)


def test_ref_explicit_crop(tmp_path):
   arr = image.new(100, 100, RED)
   arr[10, 10] = (0, 0, 255, 255)
   src = _save(tmp_path, arr)
   result = ref.run(_args(src, tmp_path / "ref.png", crop="10,10,20,30"))
   assert result["size"] == [20, 30]
   assert result["crop"] == [10, 10, 20, 30]
   out = image.load(tmp_path / "ref.png")
   assert tuple(out[0, 0]) == (0, 0, 255, 255)
   assert not any(w["rule"] == "ref.cropped" for w in result["warnings"])


def test_ref_crop_outside_exit2(tmp_path):
   src = _save(tmp_path, image.new(50, 50, RED))
   with pytest.raises(errors.UsageError):
      ref.run(_args(src, tmp_path / "ref.png", crop="40,40,20,20"))
   assert not (tmp_path / "ref.png").exists()


def test_ref_no_resize_when_smaller(tmp_path):
   src = _save(tmp_path, image.new(40, 30, RED))
   result = ref.run(_args(src, tmp_path / "ref.png"))
   assert result["size"] == [40, 30]
   assert result["crop"] is None
   assert image.size(image.load(tmp_path / "ref.png")) == (40, 30)


def test_ref_reduces_to_palette_png(tmp_path):
   src = _save(tmp_path, _noise(64, 64))
   result = ref.run(_args(src, tmp_path / "ref.png", colors=16))
   assert result["colors_before"] > 16
   assert result["colors_after"] <= 16
   with Image.open(tmp_path / "ref.png") as img:
      assert img.mode == "P"
   assert image.count_colors(image.load(tmp_path / "ref.png")) <= 16


def test_ref_keeps_transparency(tmp_path):
   arr = image.new(20, 20)
   arr[5:15, 5:15] = RED
   arr[2, 2] = (10, 200, 10, 90)   # 반투명 → 투명
   arr[3, 3] = (10, 200, 10, 200)  # 반투명 → 불투명
   src = _save(tmp_path, arr)
   result = ref.run(_args(src, tmp_path / "ref.png"))
   out = image.load(tmp_path / "ref.png")
   assert out[0, 0, 3] == 0 and out[2, 2, 3] == 0
   assert out[3, 3, 3] == 255 and out[10, 10, 3] == 255
   assert tuple(out[10, 10]) == RED
   assert any(w["rule"] == "ref.soft_alpha" for w in result["warnings"])
   with Image.open(tmp_path / "ref.png") as img:
      assert img.mode == "P" and "transparency" in img.info


def test_ref_b64_matches_png(tmp_path):
   src = _save(tmp_path, image.new(16, 16, RED))
   result = ref.run(_args(src, tmp_path / "ref.png", b64=str(tmp_path / "ref.txt")))
   text = (tmp_path / "ref.txt").read_text(encoding="ascii")
   assert "\n" not in text
   png = (tmp_path / "ref.png").read_bytes()
   assert base64.b64decode(text) == png
   assert result["png_bytes"] == len(png)
   assert result["b64_bytes"] == len(text)
   assert text not in str(result)   # base64 는 보고에 안 싣는다


def test_ref_warns_large_b64(tmp_path):
   src = _save(tmp_path, _noise(128, 128))
   result = ref.run(_args(src, tmp_path / "ref.png", colors=256, max_kb=1.0))
   assert result["status"] == "warn"
   assert any(w["rule"] == "ref.b64_large" for w in result["warnings"])


@pytest.mark.parametrize("canvas", ["128", "0x64", "axb", "64x"])
def test_ref_bad_canvas_exit2(tmp_path, canvas):
   src = _save(tmp_path, image.new(8, 8, RED))
   with pytest.raises(errors.UsageError):
      ref.run(_args(src, tmp_path / "ref.png", canvas=canvas))


def test_ref_bad_colors_exit2(tmp_path):
   src = _save(tmp_path, image.new(8, 8, RED))
   for bad in (1, 257):
      with pytest.raises(errors.UsageError):
         ref.run(_args(src, tmp_path / "ref.png", colors=bad))


def test_ref_empty_image_exit1(tmp_path):
   src = _save(tmp_path, image.new(8, 8))
   with pytest.raises(errors.ArtToolError) as info:
      ref.run(_args(src, tmp_path / "ref.png"))
   assert info.value.exit_code == errors.EXIT_ERROR


def test_ref_refuses_overwrite_input(tmp_path):
   src = _save(tmp_path, image.new(8, 8, RED))
   before = src.read_bytes()
   with pytest.raises(errors.UsageError):
      ref.run(_args(src, src))
   with pytest.raises(errors.UsageError):
      ref.run(_args(src, tmp_path / "ref.png", b64=str(src)))
   assert src.read_bytes() == before
