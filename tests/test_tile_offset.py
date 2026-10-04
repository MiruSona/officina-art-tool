"""`tile offset` 시험. 그림은 모두 코드로 만든 합성 그림이다. 배선 전이라 `run` 을 Namespace 로 바로 부른다."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from arttool import errors, image
from arttool.tiles import offset

WHITE = (255, 255, 255, 255)
BLACK = (0, 0, 0, 255)


def _args(in_file, out_file, mask, **extra):
   values = {"in_file": str(in_file), "out_file": str(out_file), "mask": str(mask), "band": 16, "report": None}
   values.update(extra)
   return argparse.Namespace(**values)


def _save(tmp_path, arr, name="grass.png"):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _coords(w, h):
   """칸마다 (x, y) 를 R · G 에 적은 그림 — 어느 칸이 어디로 갔나 알 수 있다."""
   arr = image.new(w, h, (0, 0, 80, 255))
   for y in range(h):
      for x in range(w):
         arr[y, x, 0] = x
         arr[y, x, 1] = y
   return arr


def test_offset_moves_edges_to_center(tmp_path):
   src = _save(tmp_path, _coords(64, 64))
   result = offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png"))
   out = image.load(tmp_path / "o.png")
   assert result["shift"] == [32, 32]
   assert tuple(out[32, 32, :2]) == (0, 0)       # 원래 왼쪽 위 → 가운데
   assert tuple(out[31, 31, :2]) == (63, 63)     # 원래 오른쪽 아래 → 가운데 바로 왼쪽 위
   assert tuple(out[0, 0, :2]) == (32, 32)


def test_offset_odd_size(tmp_path):
   src = _save(tmp_path, _coords(33, 31))
   result = offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=4))
   out = image.load(tmp_path / "o.png")
   assert result["shift"] == [16, 15]
   assert image.size(out) == (33, 31)
   assert tuple(out[15, 16, :2]) == (0, 0)
   mask = image.load(tmp_path / "m.png")
   white = mask[:, :, 0] == 255
   assert white[0, 14:18].all() and not white[0, 13] and not white[0, 18]
   assert white[13:17, 0].all() and not white[12, 0] and not white[17, 0]


def test_offset_mask_cross_width(tmp_path):
   src = _save(tmp_path, _coords(64, 64))
   offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=16))
   mask = image.load(tmp_path / "m.png")
   white = mask[:, :, 0] == 255
   assert white[0].sum() == 16 and white[0, 24:40].all()   # 세로 띠 : x 24~39
   assert white[:, 0].sum() == 16 and white[24:40, 0].all()
   assert white.sum() == 16 * 64 * 2 - 16 * 16


def test_offset_mask_is_opaque_black_white(tmp_path):
   src = _save(tmp_path, _coords(32, 32))
   offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=8))
   mask = image.load(tmp_path / "m.png")
   assert (mask[:, :, 3] == 255).all()
   colors = {tuple(c) for c in mask.reshape(-1, 4)}
   assert colors == {WHITE, BLACK}


@pytest.mark.parametrize("band", [15, 0, 1])
def test_offset_band_odd_exit2(tmp_path, band):
   src = _save(tmp_path, _coords(64, 64))
   with pytest.raises(errors.UsageError):
      offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=band))


def test_offset_band_too_wide_exit2(tmp_path):
   src = _save(tmp_path, _coords(64, 32))
   with pytest.raises(errors.UsageError):
      offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=16))
   assert not (tmp_path / "o.png").exists() and not (tmp_path / "m.png").exists()


def test_offset_reports_seam_before(tmp_path):
   src = _save(tmp_path, _coords(32, 32))
   result = offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=8))
   seams = {row["seam"]: row for row in result["seam_before"]}
   assert set(seams) == {"right_left", "bottom_top"}
   assert seams["right_left"]["ok"] is False      # 좌표 그림은 네 변이 안 이어진다


def test_offset_transparent_warns(tmp_path):
   arr = _coords(32, 32)
   arr[3, 3, 3] = 0
   src = _save(tmp_path, arr)
   result = offset.run(_args(src, tmp_path / "o.png", tmp_path / "m.png", band=8))
   assert result["status"] == "warn"
   assert any(w["rule"] == "offset.has_transparent" for w in result["warnings"])


def test_offset_refuses_same_out_and_mask(tmp_path):
   src = _save(tmp_path, _coords(32, 32))
   with pytest.raises(errors.UsageError):
      offset.run(_args(src, tmp_path / "o.png", tmp_path / "o.png", band=8))
   before = src.read_bytes()
   with pytest.raises(errors.UsageError):
      offset.run(_args(src, src, tmp_path / "m.png", band=8))
   with pytest.raises(errors.UsageError):
      offset.run(_args(src, tmp_path / "o.png", src, band=8))
   assert src.read_bytes() == before
   assert np.array_equal(image.load(src), _coords(32, 32))
