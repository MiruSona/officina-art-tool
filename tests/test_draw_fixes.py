"""그리기 보강 (리뷰 2차 R2-M3 · L2 ~ L8, solid 외곽선 · 두께) 시험. 그림은 모두 합성."""

import json
import sys

import numpy as np
import pytest

from arttool import image
from arttool.checks.outline import measure_outline
from arttool.draw import Canvas, outline, shapes
from arttool.errors import ArtToolError
from arttool.palette import load_ramps

OM = sys.modules["arttool.draw.outline"]
FILL = (192, 128, 96)


def _square(size=12, x0=4, y0=4, x1=8, y1=8, color=FILL):
   arr = image.new(size, size)
   shapes.paint(arr, shapes.box((size, size), x0, y0, x1, y1), color)
   return arr


def _ramps(tmp_path, outline_hex="#101018"):
   data = {"version": 1, "name": "t", "ramp_len": 3, "outline": outline_hex,
           "ramps": {"skin": ["#402020", "#804040", "#C08060"]}}
   path = tmp_path / "pal.json"
   path.write_text(json.dumps(data), encoding="utf-8")
   return load_ramps(path)


# ── solid · 두께 ─────────


def test_solid_uses_one_given_color():
   out = outline(_square(), "solid", color="#3A2010")
   ring = OM.ring(_square()[:, :, 3] > 0)
   colors = {tuple(int(v) for v in out[y, x, :3]) for y, x in zip(*np.nonzero(ring))}
   assert colors == {(0x3A, 0x20, 0x10)}


def test_solid_needs_color():
   with pytest.raises(ArtToolError):
      outline(_square(), "solid")


def test_solid_reads_back_as_solid():
   """check 의 판정과 짝 : 검정이 아닌 한 색 선은 solid 로 읽힌다."""
   arr = image.new(32, 32)
   shapes.paint(arr, shapes.ellipse((32, 32), 4, 4, 28, 28), FILL)
   shapes.paint(arr, shapes.box((32, 32), 16, 0, 32, 32) & shapes.ellipse((32, 32), 4, 4, 28, 28), (48, 96, 192))
   got = measure_outline(outline(arr, "solid", color="#4A2A18"), "top_left")
   assert got["verdict"] == "solid"


@pytest.mark.parametrize("where", ["outside", "inside"])
def test_width_two_makes_two_rings(where):
   arr = _square()
   one = outline(arr, "black", where=where)
   two = outline(arr, "black", where=where, width=2)
   black = lambda a: ((a[:, :, :3] == 0).all(axis=2) & (a[:, :, 3] > 0)).sum()
   assert black(two) > black(one)
   if where == "outside":
      assert tuple(two[4, 2, :3]) == (0, 0, 0) and tuple(two[4, 3, :3]) == (0, 0, 0) and two[4, 1, 3] == 0
   else:
      assert tuple(two[5, 5, :3]) == (0, 0, 0) and ((two[:, :, 3] > 0) == (arr[:, :, 3] > 0)).all()


def test_width_must_be_small_int():
   with pytest.raises(ArtToolError):
      outline(_square(), "black", width=0)
   with pytest.raises(ArtToolError):
      outline(_square(), "black", width=1.5)


# ── R2-M3 : 램프 맨 아래 ─────────


def test_ramp_bottom_falls_back_to_outline_color(tmp_path):
   ramps = _ramps(tmp_path)
   assert OM.darker((0x40, 0x20, 0x20), 2, ramps) == (0x10, 0x10, 0x18)
   assert OM.darker((0x80, 0x40, 0x40), 2, ramps) == (0x40, 0x20, 0x20)    # 한 칸이라도 내려가면 램프 안
   notes = []
   OM.plan(_square(color=(0x40, 0x20, 0x20)), "selout", ramps=ramps, notes=notes)
   assert notes and notes[0]["rule"] == "outline_ramp_bottom" and notes[0]["count"] == 16


def test_ramp_bottom_without_outline_color_is_computed(tmp_path):
   data = {"version": 1, "name": "t", "ramp_len": 2, "ramps": {"skin": ["#402020", "#C08060"]}}
   (tmp_path / "p.json").write_text(json.dumps(data), encoding="utf-8")
   got = OM.darker((0x40, 0x20, 0x20), 2, load_ramps(tmp_path / "p.json"))
   assert got != (0x40, 0x20, 0x20) and sum(got) < 0x40 + 0x20 + 0x20


def test_computed_darker_cuts_luma_by_exact_share():
   """셈으로 어둡게 할 때 밝기 몫이 색마다 같다 — 빛 쪽 · 그늘 쪽 바탕색이 달라도 selout 이 selout 으로 읽힌다."""
   for rgb in [(192, 128, 96), (48, 96, 192), (230, 220, 120), (60, 40, 30)]:
      got = OM.darker(rgb, 2)
      assert abs(OM.luma(got) / OM.luma(rgb) - 0.6) < 0.03


# ── Canvas (L2 ~ L8) ─────────


def test_canvas_report_names_ramp_bottom_and_double_outline(tmp_path):
   c = Canvas(12, layers=["body"], ramps=_ramps(tmp_path))
   c["body"].box(4, 4, 8, 8, "#402020")
   c.outline("selout")
   c.outline("selout")
   rules = [w["rule"] for w in c.report()["warnings"]]
   assert "outline_ramp_bottom" in rules and "outline_twice" in rules


def test_canvas_outline_skips_cells_of_unpicked_layers():
   c = Canvas(12, layers=["body", "hair"])
   c["body"].box(4, 4, 8, 8, "#C08060")
   c["hair"].box(8, 4, 10, 8, "#304080")      # body 바로 오른쪽
   c.outline("black", layers=["body"])
   assert c["hair"].px(8, 5) == "#304080"     # 남의 그림을 안 덮는다
   assert c["body"].px(8, 5) is None
   assert c["body"].px(3, 5) == "#000000"


def test_canvas_solid_and_width():
   c = Canvas(12, layers=["body"])
   c["body"].box(4, 4, 8, 8, "#C08060")
   c.outline("solid", color="#402818", width=2)
   assert c["body"].px(2, 5) == "#402818" and c["body"].px(3, 5) == "#402818"


def test_px_outside_is_none():
   c = Canvas(8, layers=["body"])
   c["body"].box(0, 0, 8, 8, "#C08060")
   assert c["body"].px(-1, 0) is None and c["body"].px(0, 8) is None and c["body"].px(7, 7) == "#C08060"


def test_color_must_be_integers_and_size_accepts_numpy_ints():
   c = Canvas(np.int64(8), layers=["body"])
   assert c.size == (8, 8)
   with pytest.raises(ArtToolError):
      c["body"].dot(1, 1, (1.7, 2, 3))
   c["body"].dot(1, 1, (np.uint8(10), 20, 30))
   assert c["body"].px(1, 1) == "#0A141E"


def test_open_rejects_missing_item(tmp_path):
   c = Canvas(8, layers=["body"])
   c["body"].box(1, 1, 7, 7, "#C08060")
   c.save(tmp_path / "set")
   assert Canvas.open(tmp_path / "set")["body"].px(2, 2) == "#C08060"
   with pytest.raises(ArtToolError):
      Canvas.open(tmp_path / "set", "walk0")


def test_preview_refuses_inside_layer_set(tmp_path):
   c = Canvas(8, layers=["body"])
   c["body"].box(1, 1, 7, 7, "#C08060")
   c.save(tmp_path / "set")
   with pytest.raises(ArtToolError):
      c.preview(tmp_path / "set" / "look.png")
   with pytest.raises(ArtToolError):
      Canvas.open(tmp_path / "set").preview(tmp_path / "set" / "body" / "x.png")
   assert c.preview(tmp_path / "look.png").is_file()
