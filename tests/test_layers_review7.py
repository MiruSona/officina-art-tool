"""7판 코드리뷰 12건 · 실측 판정 5건 (설계 2026-10-07 「7-1. 구현 때 정한 것」 뒷줄). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import json

import pytest

from arttool import errors, image, layerset, sheet
from arttool.draw.canvas import Canvas
from arttool.errors import UsageError
from arttool.jsonio import read_json, write_json
from arttool.sprite import layerops

from test_layers_check7 import _box, check, write_v2
from test_layers_ops import run_cli
from test_sheet_compare import _ns

W = H = 12
GRAY = (128, 128, 128)
RED = (200, 0, 0)
WHITE = (255, 255, 255)


# --- #1 : <겹>_<v>.png 는 가장 긴 겹 접두에만 ---


def _flat(tmp_path):
   folder = tmp_path / "flat"
   folder.mkdir()
   arr = _box(2, 2, 6, 6, RED)
   for name in ("body_1", "body_2", "hair_1", "hair_2", "hair_front_1", "hair_front_2"):
      image.save(folder / f"{name}.png", arr)
   return folder


def test_flat_longest_prefix_wins(tmp_path):
   folder = _flat(tmp_path)
   ls = layerset.from_folder(folder, ["body", "hair", "hair_front"])
   assert ls.items == ["1", "2"]


def test_flat_counts_use_longest_prefix(tmp_path):
   folder = _flat(tmp_path)
   rep = tmp_path / "r.json"
   assert run_cli(["layers", "check", "--in", str(folder), "--order", "body,hair,hair_front"], rep) == errors.EXIT_OK
   data = read_json(rep)
   assert data["counts"] == {"body": 2, "hair": 2, "hair_front": 2}
   assert not [w for w in data["warnings"] if w["rule"] == "layer_count"]


def test_scan_variants_longest_prefix(tmp_path):
   folder = tmp_path / "set"
   rows = [{"name": "hair", "kind": "hair", "files": "hair_{v}.png"},
           {"name": "hair_front", "kind": "hair", "files": "hair_front_{v}.png"}]
   layerset.save(folder, layerset.from_dict({"version": 2, "canvas": [W, H], "layers": rows, "items": ["a"]}))
   image.save(folder / "hair_a.png", _box(0, 0, 2, 2, RED))
   image.save(folder / "hair_front_a.png", _box(0, 0, 2, 2, RED))
   found = layerops._scan_variants(folder, layerset.load(folder))
   assert found == {"hair": ["a"], "hair_front": ["a"]}


# --- #2 : 캔버스 보고 · 린트는 마스크 겹을 안 훑는다 ---


def _mask_canvas(tmp_path):
   file = tmp_path / "layers.json"
   write_json(file, {"version": 2, "canvas": [8, 8], "items": ["idle"],
                     "layers": [{"name": "body", "kind": "body"}, {"name": "zone", "kind": "mask", "optional": True}]})
   c = Canvas(template=file)
   c["body"].arr[2:6, 2:6] = (*GRAY, 255)
   c["zone"].arr[0, 0] = (255, 0, 255, 255)      # 가이드 색이지만 마스크 겹이라 그림이 아니다
   c["zone"].arr[1, 1] = (255, 255, 255, 128)    # 반투명도 마찬가지
   return c


def test_canvas_report_skips_mask_layers(tmp_path):
   rep = _mask_canvas(tmp_path).report()
   assert not [w for w in rep["warnings"] if w["rule"] in ("guide_color", "alpha", "palette")]


def test_canvas_report_empty_mask_still_counted(tmp_path):
   file = tmp_path / "layers.json"
   write_json(file, {"version": 2, "canvas": [8, 8], "items": ["idle"],
                     "layers": [{"name": "body", "kind": "body"}, {"name": "zone", "kind": "mask"}]})
   c = Canvas(template=file)
   c["body"].arr[2:6, 2:6] = (*GRAY, 255)
   empty = [w for w in c.report()["warnings"] if w["rule"] == "empty"]
   assert empty and empty[0]["items"] == ["zone"]              # 빈 겹 판정은 그대로


def test_canvas_lint_skips_mask_layers(tmp_path):
   result = _mask_canvas(tmp_path).lint()
   assert not [i for i in result.issues if i.get("layer") == "zone"]


# --- #3 : view --mask-of 는 check 와 같은 검사 ---


def _tint_set(tmp_path, masks=True):
   rows = [{"name": "content", "kind": "content"}]
   frames = {"content": _box(2, 2, 10, 10, WHITE)}
   if masks:
      rows.append({"name": "tier1", "kind": "mask"})
      frames["tier1"] = _box(2, 2, 10, 6, WHITE)
   return write_v2(tmp_path / "set", rows, {"f0": frames})


@pytest.mark.parametrize("mask_of", ["content,tier1", "nope", "tier1"])
def test_view_mask_of_refusals(tmp_path, mask_of):
   folder = _tint_set(tmp_path)
   argv = ["layers", "view", "--in", str(folder), "--out", str(tmp_path / "v.png"), "--tint", "content=#ff0000", "--mask-of", mask_of]
   assert run_cli(argv) == errors.EXIT_USAGE


def test_view_mask_of_needs_mask_layer(tmp_path):
   folder = _tint_set(tmp_path, masks=False)
   argv = ["layers", "view", "--in", str(folder), "--out", str(tmp_path / "v.png"), "--tint", "content=#ff0000", "--mask-of", "content"]
   assert run_cli(argv) == errors.EXIT_USAGE


def test_mask_base_shared_function():
   ls = layerset.from_dict({"version": 2, "canvas": [W, H], "layers": [{"name": "a", "kind": "deco"}, {"name": "m", "kind": "mask"}]})
   assert layerops.mask_base(ls, "a") == "a"
   assert layerops.mask_base(ls, None) is None
   for bad in ("a,m", "m", "zz"):
      with pytest.raises(UsageError):
         layerops.mask_base(ls, bad)


# --- #7 · #8 ---


def test_before_refusal_names_the_argument(tmp_path):
   folder = _flat(tmp_path)
   before = tmp_path / "before"
   before.mkdir()
   write_json(before / layerset.FILE_NAME, {"version": 1, "canvas": [W, H], "layers": [{"name": "body", "kind": "body"}]})
   with pytest.raises(UsageError, match="--before"):
      layerops.run_check(_check_ns(folder, order="body,hair,hair_front", before=str(before)))


def _check_ns(folder, **over):
   import argparse
   values = {"in_dir": str(folder), "template": None, "original": None, "cover": None}
   values.update(over)
   return argparse.Namespace(**values)


def test_masks_repeated_rejected(tmp_path):
   folder = _flat(tmp_path)
   with pytest.raises(UsageError, match="겹친"):
      layerset.from_folder(folder, ["body", "hair", "hair_front"], ["hair", "hair"])


def test_masks_all_judged_by_set(tmp_path):
   folder = _flat(tmp_path)
   with pytest.raises(UsageError):
      layerset.from_folder(folder, ["body", "hair"], ["body", "hair"])


# --- #10 : JSON 꼴 --tint 는 개수부터 ---


def test_tint_json_count_checked_first(tmp_path, monkeypatch):
   monkeypatch.setattr(layerops, "TINT_MAX", 2)
   folder = _tint_set(tmp_path)
   spec = tmp_path / "t.json"
   spec.write_text(json.dumps([{"name": f"c{i}", "tint": {"nope": "#ffffff"}} for i in range(3)]), encoding="utf-8")
   with pytest.raises(UsageError, match="2개까지"):
      layerops._parse_tints([str(spec)], layerset.load(folder), None)


# --- #12 : sheet --compare 짝 경고 ---


def test_compare_duplicate_and_self(tmp_path):
   a, b, old = tmp_path / "a", tmp_path / "b", tmp_path / "old"
   for d in (a, b, old):
      d.mkdir()
   arr = image.new(4, 4, (*RED, 255))
   image.save(a / "x.png", arr)
   image.save(b / "x.png", arr)
   image.save(old / "x.png", arr)
   result = sheet.run(_ns([a / "x.png", b / "x.png"], tmp_path / "s.png", compare=str(old)))
   rules = [w["rule"] for w in result["warnings"]]
   assert "compare_duplicate" in rules
   result = sheet.run(_ns([a / "x.png"], tmp_path / "s2.png", compare=str(a)))
   assert "compare_self" in [w["rule"] for w in result["warnings"]]


def test_compare_plain_has_no_new_warnings(tmp_path):
   a, old = tmp_path / "a", tmp_path / "old"
   a.mkdir()
   old.mkdir()
   image.save(a / "x.png", image.new(4, 4, (*RED, 255)))
   image.save(old / "x.png", image.new(4, 4, (*RED, 255)))
   result = sheet.run(_ns([a / "x.png"], tmp_path / "s.png", compare=str(old)))
   assert not [w for w in result["warnings"] if w["rule"] in ("compare_duplicate", "compare_self")]


# --- B1 : [x, y] anchor 는 변 좌표 ---


def _frames(n, tool_bottom=None):
   """bowl(받침) + tool(위). tool_bottom 을 주면 마지막 장 tool 이 받침 아래로 튀어나온다 (사례 9 꼴)."""
   out = {}
   for i in range(n):
      tool = _box(4, 2, 8, 6, RED)
      if tool_bottom is not None and i == n - 1:
         tool = _box(4, 2, 8, tool_bottom, RED)
         tool[2:tool_bottom, 9:11] = (*RED, 255)    # 옆으로도 튀어나와 가운데가 옮겨진다
      out[f"f{i}"] = {"bowl": _box(2, 6, 10, 10, GRAY), "tool": tool}
   return out


ROWS = [{"name": "bowl", "kind": "base"}, {"name": "tool", "kind": "deco"}]


def test_anchor_point_on_edges_accepted():
   ls = layerset.from_dict({"version": 2, "canvas": [W, H], "anchor": [W, H], "layers": [{"name": "a", "kind": "deco"}]})
   assert ls.anchor == (W, H)
   with pytest.raises(UsageError):
      layerset.from_dict({"version": 2, "canvas": [W, H], "anchor": [W + 1, 0], "layers": [{"name": "a", "kind": "deco"}]})


def test_anchor_point_measures_bottom_edge(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(2), anchor=[6, 10])   # bbox x 2..10 · 아래변 y=10
   code, rep = check(folder)
   assert code == errors.EXIT_OK
   assert rep["anchors"] == [{"item": "f0", "at": [6, 10]}, {"item": "f1", "at": [6, 10]}]
   assert [w for w in rep["warnings"] if w["rule"] == "layer_anchor"] == []


def test_anchor_name_kind_unchanged(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(2), anchor="bbox_bottom_center")
   _, rep = check(folder)
   assert rep["anchors"][0]["at"] == [6, 9]                                 # 이름 꼴은 칸 좌표 그대로


# --- B2 : anchor_layer ---


def test_anchor_layer_ignores_sticking_out_layer(tmp_path):
   frames = _frames(3, tool_bottom=12)
   folder = write_v2(tmp_path / "a", ROWS, frames, anchor="bbox_bottom_center")
   _, rep = check(folder)
   assert [w for w in rep["warnings"] if w["rule"] == "layer_anchor"]       # 튀어나온 도구가 bbox 를 끈다
   folder = tmp_path / "b" / "set"
   write_v2(folder, ROWS, frames, anchor="bbox_bottom_center")
   data = read_json(folder / layerset.FILE_NAME)
   data["anchor_layer"] = "bowl"
   write_json(folder / layerset.FILE_NAME, data)
   _, rep = check(folder)
   assert [w for w in rep["warnings"] if w["rule"] == "layer_anchor"] == []


def _with_anchor_layer(value, anchor="bbox_center"):
   data = {"version": 2, "canvas": [W, H], "layers": [{"name": "a", "kind": "deco"}, {"name": "m", "kind": "mask"}],
           "anchor_layer": value}
   if anchor is not None:
      data["anchor"] = anchor
   return data


def test_anchor_layer_round_trip_and_refusals():
   ls = layerset.from_dict(_with_anchor_layer("a"))
   assert ls.anchor_layer == "a" and ls.to_dict()["anchor_layer"] == "a"
   for bad in ("m", "zz", 3):
      with pytest.raises(UsageError):
         layerset.from_dict(_with_anchor_layer(bad))
   with pytest.raises(UsageError):
      layerset.from_dict(_with_anchor_layer("a", anchor=None))           # anchor 없이 혼자는 뜻이 없다
   with pytest.raises(UsageError):
      layerset.from_dict({**_with_anchor_layer("a"), "version": 1, "layers": [{"name": "a", "kind": "deco"}]})


def test_carry_meta_keeps_anchor_layer():
   old = layerset.from_dict(_with_anchor_layer("a"))
   fresh = layerset.from_dict({"version": 2, "canvas": [W, H], "layers": [{"name": "a", "kind": "deco"}]})
   out = layerset.carry_meta(old, fresh)
   assert out.anchor_layer == "a" and out.anchor == "bbox_center"
   gone = layerset.from_dict({"version": 2, "canvas": [W, H], "layers": [{"name": "b", "kind": "deco"}]})
   assert layerset.carry_meta(old, gone).anchor_layer is None                # 겹이 없어졌으면 잇지 않는다


# --- B3 : check --hole-max ---


def _holed(tmp_path):
   content = _box(1, 1, 11, 11, GRAY)
   content[3, 3] = 0                     # 1칸
   content[5:9, 5:9] = 0                 # 16칸 (일부러 둔 구멍)
   return write_v2(tmp_path / "set", [{"name": "content", "kind": "content"}], {"f0": {"content": content}})


def test_check_hole_max_marks_large(tmp_path):
   folder = _holed(tmp_path)
   _, rep = check(folder, "--holes", "--hole-max", "4")
   row = rep["holes"][0]
   assert row["open"] == 1 and row["large"] == 1
   assert row["regions"][0] == {"box": [5, 5, 9, 9], "cells": 16, "covered": False, "large": True}
   assert "large" not in row["regions"][1]
   line = [w for w in rep["warnings"] if w["rule"] == "layer_hole"]
   assert len(line) == 1 and line[0]["items"] == [[3, 3]]


def test_check_hole_max_all_large_no_warning(tmp_path):
   folder = _holed(tmp_path)
   content = image.load(folder / "content" / "f0.png")
   content[3, 3] = (*GRAY, 255)
   image.save(folder / "content" / "f0.png", content)
   _, rep = check(folder, "--holes", "--hole-max", "4")
   assert rep["holes"][0]["open"] == 0
   assert [w for w in rep["warnings"] if w["rule"] == "layer_hole"] == []


def test_check_hole_max_absent_keeps_old_shape(tmp_path):
   _, rep = check(_holed(tmp_path), "--holes")
   assert "large" not in rep["holes"][0] and all("large" not in r for r in rep["holes"][0]["regions"])


def test_check_hole_max_needs_holes(tmp_path):
   folder = _holed(tmp_path)
   assert run_cli(["layers", "check", "--in", str(folder), "--hole-max", "4"]) == errors.EXIT_USAGE
   assert run_cli(["layers", "check", "--in", str(folder), "--holes", "--hole-max", "0"]) == errors.EXIT_USAGE


# --- B4 : fill --hole-max 기본 32 ---


def test_fill_hole_max_default_32():
   assert layerops.HOLE_MAX == 32
