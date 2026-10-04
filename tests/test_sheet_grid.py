"""`sheet --grid N` 시험 (피드백 후속 설계 3-7). 그림은 코드로 만든다.

배선 전에도 돌게 `sheet.run` 은 `grid` · `grid_color` 를 getattr 로 읽는다. 시험은 Namespace 를 직접 만든다.
"""

from __future__ import annotations

from argparse import Namespace

import numpy as np
import pytest

from arttool import errors, image, sheet

FILL = (40, 120, 60, 255)
MAGENTA = (255, 0, 255, 255)


def _write(tmp_path, w=16, h=16):
   path = tmp_path / "in.png"
   image.save(path, image.new(w, h, FILL))
   return path


def _args(tmp_path, source, **extra) -> Namespace:
   values = {"in_paths": [str(source)], "out_file": str(tmp_path / "sheet.png"), "kinds": "zoom", "scale": "4",
             "tile": 2, "bg": "checker", "label": False, "report": None}
   values.update(extra)
   return Namespace(**values)


def _cell(made: np.ndarray, result: dict) -> tuple[int, int]:
   """zoom 칸의 그림 자리 (x, y) — 판 여백 GAP + 눈금 여백."""
   left, top = result["grid_margin"]
   return sheet.GAP + left, sheet.GAP + top


def test_grid_lines_every_n(tmp_path):
   source = _write(tmp_path)
   result = sheet.run(_args(tmp_path, source, grid=8))
   made = image.load(tmp_path / "sheet.png")
   x0, y0 = _cell(made, result)
   scale = result["scale"]
   # 원본 0 · 8 칸 자리 세로선, 그 사이는 그림 색
   for col in (0, 8):
      assert tuple(made[y0 + 5, x0 + col * scale]) == MAGENTA
      assert tuple(made[y0 + col * scale, x0 + 5]) == MAGENTA
   assert tuple(made[y0 + 5, x0 + 4 * scale]) == FILL
   assert tuple(made[y0 + 5, x0 + 8 * scale + 1]) == FILL
   assert result["grid"] == 8


@pytest.mark.skipif(not image.has_label_font(), reason="딱지 글꼴이 없다")
def test_grid_labels_margin(tmp_path):
   source = _write(tmp_path)
   result = sheet.run(_args(tmp_path, source, grid=8))
   made = image.load(tmp_path / "sheet.png")
   left, top = result["grid_margin"]
   assert left > 0 and top > 0
   x0, y0 = _cell(made, result)
   top_band = made[sheet.GAP : y0, x0 : x0 + 16 * 4]
   left_band = made[y0 : y0 + 16 * 4, sheet.GAP : x0]
   # 여백 띠에 글자 칸(딱지 색)이 있다
   assert np.any(np.all(top_band == sheet.LABEL_COLOR, axis=2))
   assert np.any(np.all(left_band == sheet.LABEL_COLOR, axis=2))


def test_grid_raises_scale_to_4(tmp_path):
   source = _write(tmp_path)
   result = sheet.run(_args(tmp_path, source, scale="2", grid=4))
   assert result["scale"] == 4
   assert any(w["rule"] == "grid_scale" for w in result["warnings"])


def test_grid_requires_zoom_exit2(tmp_path):
   source = _write(tmp_path)
   with pytest.raises(errors.UsageError):
      sheet.run(_args(tmp_path, source, kinds="silhouette", grid=8))
   with pytest.raises(errors.UsageError):
      sheet.run(_args(tmp_path, source, grid=1))
   with pytest.raises(errors.UsageError):
      sheet.run(_args(tmp_path, source, grid=8, grid_color="pink"))


def test_grid_off_by_default_same_output(tmp_path):
   source = _write(tmp_path)
   plain = sheet.run(_args(tmp_path, source, out_file=str(tmp_path / "a.png"), kinds="zoom,tile", label=True))
   off = sheet.run(_args(tmp_path, source, out_file=str(tmp_path / "b.png"), kinds="zoom,tile", label=True, grid=0))
   assert (tmp_path / "a.png").read_bytes() == (tmp_path / "b.png").read_bytes()
   plain.pop("out"), off.pop("out")
   assert plain == off
   assert "grid" not in plain
