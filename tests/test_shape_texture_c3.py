"""보완 고리 3 질감 옵션 : wood_grain `dir: around` · 질감 `ramp_extra`."""

import copy

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import parse, render

WOOD = {"ramp": ["#6B3F2A", "#8E5A3C", "#B07A52"], "level": 1}
RING = {
   "canvas": {"size": [32, 32], "origin": [16, 16]},
   "light": "top_left",
   "outline": {"mode": "none"},
   "materials": {"clay": WOOD},
   "shapes": [{"type": "ellipsoid", "radii": [13, 13, 2], "material": "clay"}],
}
GRAIN = {"kind": "wood_grain", "on": "clay", "density": 0.5, "length": 6, "gap": 0.1, "seed": 1}


def _render(data, texture=None):
   d = copy.deepcopy(data)
   if texture is not None:
      d["texture"] = texture
   arr, _ = render(parse(d))
   return arr


def _changed(a, b):
   return np.any(a[:, :, :3] != b[:, :, :3], axis=2)


def _runs(ch):
   """바뀐 칸이 가로 · 세로로 이웃과 이어진 몫."""
   return (ch[:, 1:] & ch[:, :-1]).sum() / max(1, ch.sum()), (ch[1:, :] & ch[:-1, :]).sum() / max(1, ch.sum())


def test_around_turns_grain_on_round_shape_without_follow():
   """dir around : follow 없이도(또는 light 여도) 둥근 판의 결이 둘레를 돈다 — 세로로도 이어진다."""
   plain = _render(RING)
   h_auto, v_auto = _runs(_changed(plain, _render(RING, [GRAIN])))
   h_ar, v_ar = _runs(_changed(plain, _render(RING, [{**GRAIN, "dir": "around"}])))
   assert h_auto > v_auto
   assert v_ar > v_auto
   lit = _render(RING, [{**GRAIN, "dir": "around", "follow": "light", "fade": 0.0}])
   assert _changed(plain, lit).any()


def test_around_keeps_long_shapes_like_auto():
   """둥글지 않은(긴) 도형은 around 여도 auto 와 칸까지 같다."""
   bar = {**copy.deepcopy(RING), "canvas": {"size": [40, 16], "origin": [20, 8]},
          "shapes": [{"type": "box", "size": [30, 6, 4], "material": "clay"}]}
   assert np.array_equal(_render(bar, [GRAIN]), _render(bar, [{**GRAIN, "dir": "around"}]))


CLOTH = {
   "canvas": {"size": [24, 24], "origin": [12, 12]},
   "light": "top_left",
   "outline": {"mode": "none"},
   "materials": {"cream": {"ramp": ["#EFE6D2"], "ambient": 1.0}},
   "shapes": [{"type": "box", "size": [18, 18, 2], "material": "cream"}],
}
FOLD = {"kind": "fold", "style": "mass", "on": "cream", "width": 3, "strength": 1.0, "light": 0.0, "seed": 2,
        "spots": [[12, 8, 8]]}


def test_ramp_extra_sets_the_shade_color():
   """한 색 재질 : ramp_extra 가 없으면 셈한 그늘 색, 있으면 그 색으로 한 단 내려간다."""
   plain = _render(CLOTH)
   a = _render(CLOTH, [FOLD])
   b = _render(CLOTH, [{**FOLD, "ramp_extra": ["#F3D7AF"]}])
   ch = _changed(plain, b)
   assert ch.any()
   assert {tuple(c) for c in b[ch][:, :3].tolist()} == {(0xF3, 0xD7, 0xAF)}
   assert (0xF3, 0xD7, 0xAF) not in {tuple(c) for c in a[_changed(plain, a)][:, :3].tolist()}


def test_empty_ramp_extra_is_the_old_behaviour():
   assert np.array_equal(_render(CLOTH, [FOLD]), _render(CLOTH, [{**FOLD, "ramp_extra": []}]))


@pytest.mark.parametrize("bad, word", [
   ({**FOLD, "ramp_extra": ["nope"]}, "ramp_extra"),
   ({**FOLD, "ramp_extra": "#F3D7AF"}, "ramp_extra"),
   ({"kind": "mottle", "on": "cream", "dir": "around"}, "dir"),
])
def test_bad_c3_fields_name_the_field(bad, word):
   with pytest.raises(ArtToolError, match=word):
      parse({**copy.deepcopy(CLOTH), "texture": [bad]})
