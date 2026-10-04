"""`bands` 시험. 그림은 모두 코드로 만든 합성 그림이다. 배선 전이라 `run` 을 Namespace 로 바로 부른다."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from arttool import errors, image
from arttool.edit import bands

WHITE = (255, 255, 255, 255)
OFFWHITE = (246, 244, 242, 255)
GREEN = (60, 140, 60, 255)
BROWN = (90, 50, 20, 255)


def _args(in_file, **extra):
   values = {"in_file": str(in_file), "axis": "y", "top": 8, "mark": None, "report": None}
   values.update(extra)
   return argparse.Namespace(**values)


def _save(tmp_path, arr, name="raw.png"):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _textured(w, h, seed=3):
   """잔잔한 무늬 — 줄마다 색이 조금씩 다르고 한 줄 안도 여러 색이다."""
   rng = np.random.default_rng(seed)
   arr = image.new(w, h, GREEN)
   jitter = rng.integers(-25, 26, size=(h, w, 3))
   arr[:, :, :3] = np.clip(arr[:, :, :3].astype(int) + jitter, 0, 255).astype(np.uint8)
   return arr


def test_bands_finds_white_top_bottom(tmp_path):
   arr = _textured(40, 60)
   arr[:10] = WHITE
   arr[50:] = OFFWHITE
   result = bands.run(_args(_save(tmp_path, arr)))
   assert result["blank"]["start"] == [0, 10]
   assert result["blank"]["end"] == [50, 60]
   assert result["status"] == "ok"


def test_bands_transparent_rows_count_as_blank(tmp_path):
   arr = _textured(40, 30)
   arr[:4] = (0, 0, 0, 0)
   arr[4, :39] = WHITE        # 95% 이상이 흰색이면 빈 줄
   result = bands.run(_args(_save(tmp_path, arr)))
   assert result["blank"]["start"] == [0, 5]
   assert result["blank"]["end"] is None


def test_bands_ranks_molding_line_first(tmp_path):
   arr = _textured(48, 80)
   arr[:8] = WHITE
   arr[40:43] = BROWN      # 몰딩 줄
   result = bands.run(_args(_save(tmp_path, arr)))
   first = result["lines"][0]
   assert first["y"] == 40
   assert first["uniform"] == 1.0
   # 흰 띠와 그림 사이 경계는 후보에서 뺀다
   assert all(row["y"] != 8 for row in result["lines"])
   assert len(result["lines"]) <= 8


def test_bands_axis_x(tmp_path):
   arr = _textured(80, 30)
   arr[:, 70:] = WHITE
   arr[:, 25] = BROWN
   result = bands.run(_args(_save(tmp_path, arr), axis="x"))
   assert result["blank"]["start"] is None
   assert result["blank"]["end"] == [70, 80]
   assert result["lines"][0]["x"] == 25


def test_bands_none_warns(tmp_path):
   result = bands.run(_args(_save(tmp_path, image.new(20, 20, GREEN))))
   assert result["status"] == "warn"
   assert result["lines"] == []
   assert any(w["rule"] == "bands.none" for w in result["warnings"])


def test_bands_bad_args_exit2(tmp_path):
   src = _save(tmp_path, _textured(10, 10))
   with pytest.raises(errors.UsageError):
      bands.run(_args(src, axis="z"))
   with pytest.raises(errors.UsageError):
      bands.run(_args(src, top=0))


def test_bands_mark_png_written(tmp_path):
   arr = _textured(30, 40)
   arr[20] = BROWN
   mark = tmp_path / "m.png"
   result = bands.run(_args(_save(tmp_path, arr), mark=str(mark)))
   assert result["mark"] == str(mark)
   out = image.load(mark)
   w, h = image.size(out)
   assert h == 80 and w > 60          # ×2 + 왼쪽 여백
   red = (out[:, :, 0] == 255) & (out[:, :, 1] == 0) & (out[:, :, 2] == 0)
   assert red[40].any()               # 줄 20 의 눈금


def test_bands_mark_refuses_input_path(tmp_path):
   src = _save(tmp_path, _textured(10, 10))
   before = src.read_bytes()
   with pytest.raises(errors.UsageError):
      bands.run(_args(src, mark=str(src)))
   assert src.read_bytes() == before
