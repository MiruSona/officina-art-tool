import colorsys
import json
import sys

import numpy as np
import pytest

from arttool import image
from arttool.draw import Canvas, outline, shapes

# `arttool.draw.outline` 이름은 함수가 차지한다(공개 이름). 모듈은 sys.modules 로 꺼낸다.
OM = sys.modules["arttool.draw.outline"]
from arttool.errors import ArtToolError
from arttool.palette import load_ramps

FILL = (192, 128, 96)


def _square(size=10, x0=3, y0=3, x1=7, y1=7, color=FILL):
   arr = image.new(size, size)
   shapes.paint(arr, shapes.box((size, size), x0, y0, x1, y1), color)
   return arr


def _ramps(tmp_path):
   data = {"version": 1, "name": "t", "ramp_len": 4, "outline": "#101018",
           "ramps": {"skin": ["#402020", "#804040", "#C08060", "#F0C0A0"]}}
   path = tmp_path / "pal.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return load_ramps(path)


def _val(rgb):
   return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[2]


def test_ring_and_edge():
   mask = shapes.box((6, 6), 1, 1, 5, 5)
   ring = OM.ring(mask)
   assert ring.sum() == 16 and not ring[0, 0] and ring[0, 1] and not (ring & mask).any()
   edge = OM.edge(mask)
   assert edge.sum() == 12 and not edge[2, 2]
   # 캔버스 끝에 닿은 칸도 가장자리다
   assert OM.edge(np.ones((3, 3), bool)).sum() == 8


def test_none_changes_nothing():
   arr = _square()
   assert (outline(arr, "none") == arr).all()


def test_bad_mode_and_light():
   with pytest.raises(ArtToolError, match="외곽선 방식"):
      outline(_square(), "thick")
   with pytest.raises(ArtToolError, match="빛 방향"):
      outline(_square(), "selout", light="bottom")
   with pytest.raises(ArtToolError, match="자리"):
      outline(_square(), "black", where="middle")


def test_black_outside_uses_palette_outline(tmp_path):
   arr = _square()
   out = outline(arr, "black")
   assert tuple(out[2, 4, :3]) == (0, 0, 0) and out[2, 2, 3] == 0   # 모서리 대각은 안 칠함 (4방향)
   assert tuple(out[4, 4, :3]) == FILL                               # 안은 그대로
   assert (arr[2, 4] == 0).all()                                      # 받은 배열은 그대로
   out2 = outline(arr, "black", ramps=_ramps(tmp_path))
   assert tuple(out2[2, 4, :3]) == (0x10, 0x10, 0x18)


def test_selout_is_darker_same_family():
   out = outline(_square(), "selout")
   ring_colors = {tuple(int(v) for v in out[y, x, :3]) for y, x in zip(*np.nonzero(OM.ring(_square()[:, :, 3] > 0)))}
   assert len(ring_colors) == 1
   (c,) = ring_colors
   assert _val(c) < _val(FILL) * 0.85


def test_selout_uses_ramp_two_steps_down(tmp_path):
   ramps = _ramps(tmp_path)
   out = outline(_square(color=(0xC0, 0x80, 0x60)), "selout", ramps=ramps)
   assert tuple(out[2, 4, :3]) == (0x40, 0x20, 0x20)   # C08060(2칸) → 402020(0칸)


def test_selout_light_lit_side_brighter(tmp_path):
   ramps = _ramps(tmp_path)
   arr = _square(color=(0xC0, 0x80, 0x60))
   out = outline(arr, "selout+light", ramps=ramps, light="top_left")
   top, left = tuple(out[2, 4, :3]), tuple(out[4, 2, :3])
   bottom, right = tuple(out[7, 4, :3]), tuple(out[4, 7, :3])
   assert top == left == (0x80, 0x40, 0x40)          # 한 칸 아래
   assert bottom == right == (0x40, 0x20, 0x20)      # 두 칸 아래
   # 빛이 위에서만 오면 왼쪽은 그늘 쪽
   top_only = outline(arr, "selout+light", ramps=ramps, light="top")
   assert tuple(top_only[4, 2, :3]) == (0x40, 0x20, 0x20)
   # 셈으로 어둡게 할 때도 빛 쪽이 1.15 배 넘게 밝다 (check 의 판정 문턱)
   calc = outline(_square(), "selout+light")
   assert _val(tuple(calc[2, 4, :3])) >= _val(tuple(calc[7, 4, :3])) * 1.15


def test_inside_keeps_size():
   arr = _square()
   out = outline(arr, "black", where="inside")
   assert ((out[:, :, 3] > 0) == (arr[:, :, 3] > 0)).all()
   assert tuple(out[3, 3, :3]) == (0, 0, 0) and tuple(out[4, 4, :3]) == FILL


def test_canvas_outline_goes_to_owner_layer():
   c = Canvas(12, layers=["body", "hair"])
   c["body"].box(3, 5, 9, 11, "#C08060")
   c["hair"].box(3, 2, 9, 5, "#3060C0")
   c.outline("black")
   assert c["hair"].px(5, 1) == "#000000"    # 머리 위 → hair 겹
   assert c["body"].px(5, 11) == "#000000"   # 몸 아래 → body 겹
   assert c["body"].px(5, 1) is None and c["hair"].px(5, 11) is None
   assert c["body"].px(2, 7) == "#000000" and c["hair"].px(2, 3) == "#000000"


def test_canvas_outline_needs_mode_without_style():
   with pytest.raises(ArtToolError, match="외곽선 방식을 준다"):
      Canvas(8).outline()


def test_outline_check_agrees_with_selout():
   """이 모듈로 두른 그림의 가장자리 칸이 check ② 의 selout 조건(어두움 · 순흑 아님)에 맞는다."""
   arr = image.new(16, 16)
   shapes.paint(arr, shapes.disc((16, 16), 7.5, 7.5, 6), FILL)
   out = outline(arr, "selout")
   edge = OM.edge(out[:, :, 3] > 0)
   colors = out[edge][:, :3]
   assert (colors.max(axis=1) > 24).all()
   assert all(_val(tuple(c)) < _val(FILL) * 0.85 for c in colors)
