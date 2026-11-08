"""부품 사전(kit) — 부품 놓기(at · z · scale · flip · 이름 바꾸기) · 부품 안 부품 · 수 셈($add · $sub · $mul) · 파낸 구멍 뒤 재질."""

import json

import numpy as np
import pytest

from arttool.errors import ArtToolError
from arttool.shape import assemble, expand_template, load, parse, render

BOX_PART = {
   "template_version": 1,
   "params": {"w": {"type": "number", "default": 4}, "h": {"type": "number", "default": 2},
              "c": {"type": "color", "default": "#C03030"}},
   "spec": {
      "materials": {"m": {"ramp": ["$c"], "ambient": 1.0}},
      "shapes": [{"type": "extrude", "material": "m", "y_down": True, "depth": 2,
                  "rect": [0, {"$mul": ["$h", -1]}, "$w", 0]}],
      "stamps": [{"on": "m", "at": [0.5, 0.5], "grid": ["ab"], "legend": {"a": "#000000", "b": "#FFFFFF"}}],
   },
}


def _host(*parts, size=(16, 8), **extra):
   data = {"version": 1, "canvas": {"size": list(size), "origin": [0, 0]}, "materials": {},
           "shapes": list(parts)}
   data.update(extra)
   return data


def _write(tmp_path, name, data):
   file = tmp_path / name
   file.write_text(json.dumps(data), encoding="utf-8")
   return file


def _opaque(arr):
   ys, xs = np.nonzero(arr[:, :, 3])
   return xs.min(), xs.max(), ys.min(), ys.max()


def test_part_is_placed_renamed_and_stamped(tmp_path):
   _write(tmp_path, "box.part.json", BOX_PART)
   spec = _write(tmp_path, "s.json", _host({"part": "box.part.json", "as": "a", "at": [3, 6], "params": {"w": 5}}))
   s = load(spec)
   assert list(s.materials) == ["a.m"]
   assert s.stamps[0].on == "a.m" and s.stamps[0].at == (3.5, -5.5)
   arr, _ = render(s)
   assert _opaque(arr) == (3, 7, 4, 5)           # rect 0..5 × -2..0 를 (3, 6) 에
   assert tuple(arr[5, 3, :3]) == (0, 0, 0) and tuple(arr[5, 4, :3]) == (255, 255, 255)


def test_scale_stretches_xy_and_flip_mirrors_grid(tmp_path):
   _write(tmp_path, "box.part.json", BOX_PART)
   s = load(_write(tmp_path, "s.json", _host({"part": "box.part.json", "as": "a", "at": [2, 7], "scale": [2, 1.5]})))
   arr, _ = render(s)
   assert _opaque(arr) == (2, 9, 4, 6)           # 폭 4 → 8, 높이 2 → 3
   f = load(_write(tmp_path, "f.json", _host({"part": "box.part.json", "as": "a", "at": [10, 6], "flip": True})))
   assert f.stamps[0].grid == ["ba"]
   arr, _ = render(f)
   assert _opaque(arr) == (6, 9, 4, 5)           # x 0..4 가 거울로 −4..0


def test_two_copies_do_not_share_materials_and_host_material_is_shared(tmp_path):
   part = json.loads(json.dumps(BOX_PART))
   part["spec"]["shapes"].append({"type": "extrude", "material": "ink", "y_down": True, "depth": 2, "pos": [0, 0, 1],
                                  "rect": [0, -1, 1, 0]})
   _write(tmp_path, "box.part.json", part)
   data = _host({"part": "box.part.json", "as": "a", "at": [1, 4]},
                {"part": "box.part.json", "as": "b", "at": [8, 4], "params": {"c": "#3030C0"}})
   data["materials"] = {"ink": {"ramp": ["#00FF00"], "ambient": 1.0}}
   s = load(_write(tmp_path, "s.json", data))
   assert set(s.materials) == {"ink", "a.m", "b.m"}
   assert s.materials["b.m"].ramp[0] == (0x30, 0x30, 0xC0)
   assert sum(p.material == "ink" for p in s.prims) == 2


def test_nested_part_and_self_reference(tmp_path):
   _write(tmp_path, "box.part.json", BOX_PART)
   _write(tmp_path, "pair.part.json", {"template_version": 1, "params": {}, "spec": {"shapes": [
      {"part": "box.part.json", "as": "l", "at": [0, 0]}, {"part": "box.part.json", "as": "r", "at": [6, 0]}]}})
   s = load(_write(tmp_path, "s.json", _host({"part": "pair.part.json", "as": "p", "at": [1, 6]})))
   assert set(s.materials) == {"p.l.m", "p.r.m"}
   assert _opaque(render(s)[0]) == (1, 10, 4, 5)
   _write(tmp_path, "loop.part.json", {"template_version": 1, "spec": {"shapes": [{"part": "loop.part.json", "as": "x"}]}})
   with pytest.raises(ArtToolError, match="자기 자신"):
      load(_write(tmp_path, "l.json", _host({"part": "loop.part.json", "as": "q"})))


def test_bad_entries_name_the_field(tmp_path):
   _write(tmp_path, "box.part.json", BOX_PART)
   with pytest.raises(ArtToolError, match="모르는 칸"):
      load(_write(tmp_path, "a.json", _host({"part": "box.part.json", "as": "a", "rot": 3})))
   with pytest.raises(ArtToolError, match="두 번"):
      load(_write(tmp_path, "b.json", _host({"part": "box.part.json", "as": "a"}, {"part": "box.part.json", "as": "a"})))
   with pytest.raises(ArtToolError, match="부품 파일이 없다"):
      load(_write(tmp_path, "c.json", _host({"part": "nope.json", "as": "a"})))
   bad = json.loads(json.dumps(BOX_PART))
   bad["spec"]["canvas"] = {"size": [4, 4]}
   _write(tmp_path, "bad.part.json", bad)
   with pytest.raises(ArtToolError, match="materials · shapes · stamps 만"):
      load(_write(tmp_path, "d.json", _host({"part": "bad.part.json", "as": "a"})))


def test_math_expressions():
   tpl = {"template_version": 1, "params": {"w": {"type": "number", "default": 6},
                                            "half": {"type": "number", "default": {"$mul": ["$w", 0.5]}}},
          "spec": {"v": [{"$add": ["$w", 1, 2]}, {"$sub": ["$w", "$half"]}, "$half"]}}
   assert expand_template(tpl)["v"] == [9, 3, 3.0]
   tpl["spec"]["v"] = [{"$sub": [1, 2, 3]}]
   with pytest.raises(ArtToolError, match="둘"):
      expand_template(tpl)
   tpl["spec"]["v"] = [{"$add": ["#FFFFFF", 1]}]
   with pytest.raises(ArtToolError, match="수다"):
      expand_template(tpl)


def test_subtracted_hole_shows_the_plate_behind():
   """파낸 구멍 자리에서는 앞 판 재질이 아니라 뒤 판 재질이 보인다 (틀 + 종이)."""
   data = {"canvas": {"size": [10, 10], "origin": [0, 0]},
           "materials": {"wood": {"ramp": ["#804020"], "ambient": 1.0}, "paper": {"ramp": ["#F0E0C0"], "ambient": 1.0}},
           "shapes": [{"type": "extrude", "material": "wood", "y_down": True, "depth": 4, "rect": [0, 0, 10, 10]},
                      {"type": "extrude", "material": "wood", "op": "subtract", "y_down": True, "depth": 8, "rect": [3, 3, 7, 7]},
                      {"type": "extrude", "material": "paper", "y_down": True, "depth": 2, "pos": [0, 0, -3], "rect": [2, 2, 8, 8]}]}
   arr, _ = render(parse(data))
   assert tuple(arr[5, 5, :3]) == (0xF0, 0xE0, 0xC0)
   assert tuple(arr[1, 1, :3]) == (0x80, 0x40, 0x20)


def test_assemble_without_parts_is_identity():
   data = {"materials": {"m": {}}, "shapes": [{"type": "sphere", "r": 1, "material": "m"}]}
   assert assemble(data) is data
