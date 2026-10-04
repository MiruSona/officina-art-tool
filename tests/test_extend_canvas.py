"""`extend canvas` 시험 (피드백 후속 설계 3-5). 배경 그림은 코드로 만든다."""

from __future__ import annotations

from argparse import Namespace

import numpy as np
import pytest

from arttool import errors, image
from arttool.extend import canvas

SKY = (120, 180, 240, 255)
GROUND = (90, 60, 30, 255)


def _bg(width=8, height=6) -> np.ndarray:
   """줄마다 색이 다른 배경 : y 줄의 빨강 값 = y * 10 (줄 번호를 색으로 읽는다)."""
   arr = image.new(width, height, SKY)
   for y in range(height):
      arr[y, :, 0] = y * 10
   arr[-1, :] = GROUND
   return arr


def _args(path, out, **extra) -> Namespace:
   values = {"in_file": str(path), "size": "8x10", "out_file": str(out), "anchor": "bottom", "band": 1, "report": None}
   values.update(extra)
   return Namespace(**values)


def _save(tmp_path, arr, name="bg.png"):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _rules(result) -> list[str]:
   return [w["rule"] for w in result["warnings"]]


def test_canvas_up_repeats_top_row(tmp_path):
   source = _save(tmp_path, _bg())
   out = tmp_path / "o.png"
   result = canvas.run(_args(source, out))
   made = image.load(out)
   assert image.size(made) == (8, 10)
   assert result["offset"] == [0, 4]
   # 위로 생긴 4줄은 원본 맨 윗줄, 아래 6줄은 원본 그대로
   assert all(np.array_equal(made[y], made[4]) for y in range(4))
   assert np.array_equal(made[4:], _bg())
   assert result["status"] == "ok"


def test_canvas_band_tiles_in_phase(tmp_path):
   source = _save(tmp_path, _bg())
   out = tmp_path / "o.png"
   canvas.run(_args(source, out, size="8x11", band=3))
   made = image.load(out)
   original = _bg()
   # 원본은 y 5부터. 그 위는 원본 0·1·2 줄을 되풀이 — 바로 위(4)는 2번 줄, 그 위(3)는 1번 줄
   reds = [int(made[y, 0, 0]) for y in range(5)]
   assert reds == [int(original[r, 0, 0]) for r in (1, 2, 0, 1, 2)]


def test_canvas_center_both_sides(tmp_path):
   source = _save(tmp_path, _bg())
   out = tmp_path / "o.png"
   result = canvas.run(_args(source, out, size="8x10", anchor="center"))
   made = image.load(out)
   assert result["offset"] == [0, 2]
   assert np.array_equal(made[0], made[2]) and np.array_equal(made[1], made[2])
   assert np.array_equal(made[8], made[7]) and np.array_equal(made[9], made[7])
   assert tuple(made[9, 0]) == GROUND


def test_canvas_width_left(tmp_path):
   arr = _bg()
   arr[:, -1] = (255, 255, 0, 255)       # 오른쪽 끝 열을 노랑으로
   source = _save(tmp_path, arr)
   out = tmp_path / "o.png"
   result = canvas.run(_args(source, out, size="12x6", anchor="left"))
   made = image.load(out)
   assert result["offset"] == [0, 0]
   assert np.array_equal(made[:, :8], arr)
   assert all(tuple(made[y, x]) == (255, 255, 0, 255) for y in range(6) for x in range(8, 12))


def test_canvas_smaller_exit2(tmp_path):
   source = _save(tmp_path, _bg())
   with pytest.raises(errors.UsageError):
      canvas.run(_args(source, tmp_path / "o.png", size="7x10"))


def test_canvas_band_too_long_exit2(tmp_path):
   source = _save(tmp_path, _bg())
   with pytest.raises(errors.UsageError):
      canvas.run(_args(source, tmp_path / "o.png", band=7))


def test_canvas_edge_busy_warns(tmp_path):
   arr = _bg()
   arr[0, :, 1] = np.arange(8) * 20        # 맨 윗줄이 8색
   source = _save(tmp_path, arr)
   result = canvas.run(_args(source, tmp_path / "o.png"))
   assert "canvas.edge_busy" in _rules(result)
   assert result["status"] == "warn"


def test_canvas_refuses_overwrite_input(tmp_path):
   source = _save(tmp_path, _bg())
   before = source.read_bytes()
   with pytest.raises(errors.UsageError):
      canvas.run(_args(source, source))
   assert source.read_bytes() == before
