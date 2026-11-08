"""도형 렌더러 2차 실측(2026-11-08)에서 더한 기능 — rect · ellipse · mirror · 도형 copies · 납작 level · 띠 set ·
두꺼운 안쪽 선 · rows 무늬 · 부채꼴 줄무늬 · 잎 붓질."""

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import parse, render

GRAY = ["#404040", "#808080", "#C0C0C0"]


def _spec(shapes, materials=None, size=(16, 16), **extra):
   data = {
      "version": 1,
      "canvas": {"size": list(size), "origin": [0, 0]},
      "materials": materials or {"m": {"ramp": GRAY, "level": 1}},
      "shapes": shapes,
   }
   data.update(extra)
   return parse(data)


def _ex(mat="m", z=0, **geo):
   return {"type": "extrude", "material": mat, "y_down": True, "depth": 0.4, "pos": [0, 0, z], **geo}


def _solid(arr):
   return arr[:, :, 3] > 0


# --- 단면 줄임말 : rect · ellipse · mirror ---


def test_rect_is_the_same_as_four_points():
   a, _ = render(_spec([_ex(rect=[3, 4, 9, 7])]))
   b, _ = render(_spec([_ex(points=[[3, 4], [9, 4], [9, 7], [3, 7]])]))
   assert np.array_equal(a, b)
   assert _solid(a).sum() == 6 * 3


def test_ellipse_fills_cells_inside_the_ellipse():
   arr, _ = render(_spec([_ex(ellipse=[8, 8, 6, 3])]))
   solid = _solid(arr)
   assert solid[8, 2] and solid[8, 13] and solid[6, 8] and solid[9, 8]
   assert not solid[4, 8] and not solid[8, 1] and not solid[3, 3]


def test_mirror_closes_the_half_outline():
   half, _ = render(_spec([_ex(mirror=8, points=[[8, 2], [3, 2], [3, 12], [8, 12]])]))
   full, _ = render(_spec([_ex(rect=[3, 2, 13, 12])]))
   assert np.array_equal(half, full)


def test_outline_needs_exactly_one_form():
   with pytest.raises(ArtToolError, match="하나만"):
      _spec([_ex(rect=[0, 0, 4, 4], ellipse=[2, 2, 1, 1])])
   with pytest.raises(ArtToolError, match="rect"):
      _spec([_ex(rect=[4, 0, 0, 4])])


# --- 도형 copies ---


def test_shape_copies_repeat_in_picture_cells():
   arr, _ = render(_spec([_ex(rect=[1, 1, 3, 3], copies=[[0, 0], [5, 0], [0, 6]])]))
   solid = _solid(arr)
   assert solid[1, 1] and solid[1, 6] and solid[7, 1]
   assert solid.sum() == 3 * 4


def test_shape_copies_validate():
   with pytest.raises(ArtToolError, match="copies"):
      _spec([_ex(rect=[1, 1, 3, 3], copies=[[1]])])


# --- 납작 level · 띠 set ---


def test_level_makes_flat_color_regardless_of_light():
   mats = {"m": {"ramp": GRAY, "level": 2}}
   arr, _ = render(_spec([{"type": "sphere", "r": 6, "pos": [8, -8, 0], "material": "m"}], mats))
   colors = np.unique(arr[_solid(arr)][:, :3], axis=0)
   assert colors.tolist() == [[0xC0, 0xC0, 0xC0]]


def test_band_set_can_raise_the_level():
   mats = {"m": {"ramp": GRAY, "level": 0, "bands": [{"offset": [3, 0], "level": 2, "mode": "set"}]}}
   arr, _ = render(_spec([_ex(rect=[2, 2, 12, 6])], mats))
   assert tuple(arr[3, 5, :3]) == (0x40, 0x40, 0x40)
   assert tuple(arr[3, 10, :3]) == (0xC0, 0xC0, 0xC0)       # 오른쪽 끝 3칸만 밝게
   assert tuple(arr[3, 8, :3]) == (0x40, 0x40, 0x40)


def test_band_mode_validates():
   mats = {"m": {"ramp": GRAY, "bands": [{"offset": [1, 0], "level": 0, "mode": "max"}]}}
   with pytest.raises(ArtToolError, match="mode"):
      _spec([_ex(rect=[0, 0, 4, 4])], mats)


# --- 두꺼운 안쪽 선 ---


def test_inner_width_two_paints_two_cells_inside_the_front_shape():
   mats = {"back": {"ramp": ["#808080"]}, "front": {"ramp": ["#C0C0C0"], "line": {"color": "#000000"}}}
   shapes = [_ex("back", 0, rect=[0, 0, 16, 16]), _ex("front", 1, rect=[4, 4, 12, 12])]
   one, _ = render(_spec(shapes, mats, outline={"inner_gap": 0.5}))
   two, _ = render(_spec(shapes, mats, outline={"inner_gap": 0.5, "inner_width": 2}))
   black = lambda a: np.all(a[:, :, :3] == 0, axis=2)
   assert black(one)[4, 6] and not black(one)[5, 6]
   assert black(two)[4, 6] and black(two)[5, 6] and not black(two)[6, 6]
   assert not black(two)[3, 6]                              # 뒤 판은 그대로


# --- rows · 부채꼴 줄무늬 ---


def test_rows_pattern_paints_picture_rows():
   mats = {"m": {"ramp": ["#808080"], "pattern": [{"kind": "rows", "rows": [5, 9], "width": 2, "color": "#FF0000"}]}}
   arr, _ = render(_spec([_ex(rect=[0, 0, 16, 16])], mats))
   red = np.all(arr[:, :, :3] == (255, 0, 0), axis=2)
   assert [y for y in range(16) if red[y, 3]] == [5, 6, 9, 10]


def test_fan_stripes_lean_toward_the_focus():
   pat = {"kind": "stripes", "axis": "x", "period": 8, "width": 4, "phase": 0, "color": "#FF0000"}
   straight = {"m": {"ramp": ["#808080"], "pattern": [pat]}}
   fan = {"m": {"ramp": ["#808080"], "pattern": [{**pat, "fan": [8, 40, -15.5]}]}}
   a, _ = render(_spec([_ex(rect=[0, 0, 16, 16])], straight))
   b, _ = render(_spec([_ex(rect=[0, 0, 16, 16])], fan))
   red = lambda arr: np.all(arr[:, :, :3] == (255, 0, 0), axis=2)
   assert np.array_equal(red(a)[15], red(b)[15])            # 잰 줄(ref_y)은 똑같다
   assert not np.array_equal(red(a)[0], red(b)[0])          # 위로 갈수록 가운데로 모인다


# --- 잎 붓질 ---


def test_strokes_are_deterministic_and_brighter_on_top():
   colors = ["#102010", "#305030", "#60A060", "#A0F0A0"]
   mats = {"m": {"ramp": ["#808080"], "pattern": [{"kind": "strokes", "density": 0.4, "length": 2, "jitter": 0,
                                                   "seed": 3, "colors": colors}]}}
   spec = _spec([_ex(rect=[0, 0, 16, 16])], mats)
   a, rep = render(spec)
   b, _ = render(spec)
   assert np.array_equal(a, b) and rep["patterned"] > 0
   top = a[0:4][:, :, 1].astype(int)
   bottom = a[12:16][:, :, 1].astype(int)
   painted_top = top[top != 0x80]
   painted_bottom = bottom[bottom != 0x80]
   assert painted_top.mean() > painted_bottom.mean()


def test_strokes_validate_colors():
   mats = {"m": {"ramp": ["#808080"], "pattern": [{"kind": "strokes", "colors": "green"}]}}
   with pytest.raises(ArtToolError, match="colors"):
      _spec([_ex(rect=[0, 0, 4, 4])], mats)
