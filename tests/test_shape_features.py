"""도형 렌더러 게임 그림 실측(2026-11-08)에서 더한 기능 — 돌출 · 원뿔 · rim 상한 · 재질 선 · 띠 그늘 · 무늬 · 도장 copies."""

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import parse, render
from arttool.shape.pattern import hash01
from arttool.shape.sdf import Prim, lathe_polygon

INK = "#102030"


def _spec(shapes, materials=None, **extra):
   data = {
      "version": 1,
      "canvas": {"size": [16, 16], "origin": [0, 0]},
      "materials": materials or {"m": {"ramp": ["#404040", "#808080", "#C0C0C0"], "ambient": 1.0}},
      "shapes": shapes,
   }
   data.update(extra)
   return parse(data)


def _box(x0, y0, x1, y1, mat="m", z=0, **kw):
   return {"type": "extrude", "material": mat, "y_down": True, "depth": 2, "pos": [0, 0, z],
           "points": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], **kw}


def _solid(arr):
   return arr[:, :, 3] > 0


# --- 돌출 · 원뿔 ---


def test_extrude_silhouette_is_the_polygon_in_pixel_corners():
   arr, _ = render(_spec([_box(3, 4, 9, 7)]))
   want = np.zeros((16, 16), dtype=bool)
   want[4:7, 3:9] = True
   assert np.array_equal(_solid(arr), want)


def test_extrude_round_tilts_only_the_edge_band():
   data = [_box(2, 2, 14, 14, round=0.9)]
   mats = {"m": {"ramp": ["#000000", "#555555", "#AAAAAA", "#FFFFFF"], "ambient": 0.0}}
   arr, _ = render(_spec(data, mats))
   # 가운데는 납작면이라 한 색, 오른쪽 아래 가장자리는 빛을 등져 더 어둡다
   assert tuple(arr[8, 8, :3]) == tuple(arr[6, 6, :3])
   assert arr[13, 13, 0] < arr[8, 8, 0]


def test_extrude_rejects_too_few_points_and_big_round():
   with pytest.raises(ArtToolError, match="points"):
      _spec([{"type": "extrude", "material": "m", "points": [[0, 0], [1, 1]]}])
   with pytest.raises(ArtToolError, match="round"):
      _spec([_box(0, 0, 4, 4, round=5)])


def test_cone_is_pointed_on_top():
   prim = Prim("cone", {"_poly": lathe_polygon([[4, 0], [0, 8]])}, "m")
   d = prim.distance(np.array([[0.5, 1.0, 0.0], [3.5, 7.0, 0.0], [0.0, 9.0, 0.0]]))
   assert d[0] < 0 and d[1] > 0 and d[2] == pytest.approx(1.0)


# --- rim 은 상한 ---


def test_rim_caps_level_but_keeps_darker_shadow():
   mats = {"m": {"ramp": ["#000000", "#808080", "#FFFFFF"], "ambient": 0.0, "rim": {"below": 0.5, "index": 1}}}
   data = {"version": 1, "canvas": {"size": [32, 32], "origin": [16, 16]}, "materials": mats,
           "shapes": [{"type": "sphere", "r": 12, "material": "m"}]}
   arr, _ = render(parse(data))
   assert tuple(arr[16, 5, :3]) == (0x80, 0x80, 0x80)      # 빛 쪽 둘레 = rim 단
   assert tuple(arr[27, 24, :3]) == (0, 0, 0)               # 그늘 쪽 둘레는 rim 보다 어두운 채로


# --- 재질 선 (빛 쪽 밝은 선) ---


def test_material_line_light_side_and_dark_side():
   mats = {"m": {"ramp": ["#808080"], "ambient": 1.0, "line": {"color": "#000000", "light": "#FF0000"}}}
   arr, rep = render(_spec([_box(4, 4, 10, 10)], mats, outline={"mode": "solid", "color": INK}))
   assert tuple(arr[3, 6, :3]) == (255, 0, 0)        # 위 = 빛 쪽
   assert tuple(arr[6, 3, :3]) == (255, 0, 0)        # 왼쪽 = 빛 쪽
   assert tuple(arr[10, 6, :3]) == (0, 0, 0)         # 아래
   assert tuple(arr[6, 10, :3]) == (0, 0, 0)         # 오른쪽
   assert rep["material_line"] > 0


def test_material_line_on_inner_edge_of_front_object():
   mats = {"back": {"ramp": ["#808080"], "ambient": 1.0},
           "front": {"ramp": ["#C0C0C0"], "ambient": 1.0, "line": {"color": "#000000", "light": "#FF0000"}}}
   arr, _ = render(_spec([_box(1, 1, 15, 15, "back"), _box(5, 5, 11, 11, "front", z=6)], mats,
                         outline={"mode": "none", "inner_gap": 2}))
   assert tuple(arr[5, 7, :3]) == (255, 0, 0)        # 앞 물체 윗줄 (뒤가 위쪽 = 빛 쪽)
   assert tuple(arr[10, 7, :3]) == (0, 0, 0)         # 앞 물체 아랫줄
   assert tuple(arr[7, 7, :3]) == (0xC0, 0xC0, 0xC0)


# --- 띠 그늘 ---


def test_bands_darken_cells_whose_shifted_point_leaves_the_shape():
   mats = {"m": {"ramp": ["#000000", "#808080", "#FFFFFF"], "ambient": 1.0,
                 "bands": [{"offset": [2, 0], "level": 1}, {"offset": [0, 1], "level": 0}]}}
   arr, _ = render(_spec([_box(2, 2, 10, 10)], mats))
   assert tuple(arr[4, 4, :3]) == (255, 255, 255)
   assert tuple(arr[4, 8, :3]) == (0x80, 0x80, 0x80) and tuple(arr[4, 9, :3]) == (0x80, 0x80, 0x80)
   assert tuple(arr[4, 7, :3]) == (255, 255, 255)
   assert tuple(arr[9, 4, :3]) == (0, 0, 0)          # 맨 아래 줄


def test_bands_use_own_shape_not_neighbours():
   """다른 도형이 붙어 있어도 띠는 자기 실루엣만 본다."""
   mats = {"m": {"ramp": ["#000000", "#FFFFFF"], "ambient": 1.0, "bands": [{"offset": [1, 0], "level": 0}]}}
   arr, _ = render(_spec([_box(2, 2, 6, 6), _box(6, 2, 10, 6)], mats))
   assert tuple(arr[3, 5, :3]) == (0, 0, 0) and tuple(arr[3, 9, :3]) == (0, 0, 0)


def test_bands_validate_offset():
   mats = {"m": {"ramp": ["#000000"], "bands": [{"offset": [1.5, 0], "level": 0}]}}
   with pytest.raises(ArtToolError, match="offset"):
      _spec([_box(0, 0, 4, 4)], mats)


# --- 무늬 ---


def test_hash_is_deterministic_and_spread():
   keys = np.stack(np.meshgrid(np.arange(40), np.arange(40)), axis=-1).reshape(-1, 2)
   a, b = hash01(keys, 7), hash01(keys, 7)
   assert np.array_equal(a, b) and 0.0 <= a.min() and a.max() < 1.0
   assert 0.4 < a.mean() < 0.6 and not np.array_equal(a, hash01(keys, 8))


def test_speckle_density_and_determinism():
   mats = {"m": {"ramp": ["#808080"], "ambient": 1.0,
                 "pattern": {"kind": "speckle", "color": "#FF0000", "density": 0.1, "seed": 3}}}
   spec = _spec([_box(0, 0, 16, 16)], mats)
   a, rep = render(spec)
   b, _ = render(spec)
   red = np.all(a[:, :, :3] == (255, 0, 0), axis=2).sum()
   assert np.array_equal(a, b) and 8 <= red <= 50 and rep["patterned"] == red


def test_stripes_darken_every_period_rows():
   mats = {"m": {"ramp": ["#404040", "#C0C0C0"], "ambient": 1.0,
                 "pattern": {"kind": "stripes", "axis": "y", "period": 4, "width": 1, "darken": 1}}}
   arr, _ = render(_spec([_box(0, 0, 16, 16)], mats))
   dark_rows = [y for y in range(16) if arr[y, 5, 0] == 0x40]
   assert len(dark_rows) == 4 and all(b - a == 4 for a, b in zip(dark_rows, dark_rows[1:]))


def test_pattern_needs_color_or_darken():
   mats = {"m": {"ramp": ["#808080"], "pattern": {"kind": "speckle"}}}
   with pytest.raises(ArtToolError, match="color 또는 darken"):
      _spec([_box(0, 0, 4, 4)], mats)


# --- 도장 copies ---


def test_stamp_copies_repeat_the_grid():
   stamps = [{"on": "m", "at": [3, -3], "grid": ["#"], "legend": {"#": "#FF0000"}, "copies": [[0, 0], [4, 0], [0, 5]]}]
   arr, rep = render(_spec([_box(0, 0, 16, 16)], stamps=stamps))
   red = sorted(map(tuple, np.argwhere(np.all(arr[:, :, :3] == (255, 0, 0), axis=2))))
   assert red == [(3, 3), (3, 7), (8, 3)] and rep["stamped"] == 3
