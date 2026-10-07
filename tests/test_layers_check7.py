"""7판-가 — `layers check` 넓히기 (설계 2026-10-07 7판 2-1 ~ 2-7 · 5절). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import numpy as np
import pytest

from arttool import errors, image, layerset
from arttool.errors import UsageError
from arttool.jsonio import read_json, write_json
from arttool.sprite import layerops
from arttool.sprite.split import ANCHOR_KINDS

from test_layers_ops import run_cli

W = H = 12
GRAY = (128, 128, 128)
RED = (200, 0, 0)
BLUE = (0, 0, 200)


def _box(x0, y0, x1, y1, rgb, size=(W, H)):
   arr = image.new(*size)
   arr[y0:y1, x0:x1] = (*rgb, 255)
   return arr


def write_v2(folder, rows, frames: dict, canvas=(W, H), anchor=None):
   """버전 2 묶음. frames = {그림: {겹: 배열}}."""
   data = {"version": 2, "canvas": list(canvas), "layers": rows, "items": list(frames)}
   if anchor is not None:
      data["anchor"] = anchor
   layerset.save(folder, layerset.from_dict(data))
   for item, parts in frames.items():
      for name, arr in parts.items():
         image.save(folder / name / f"{item}.png", arr)
   return folder


def check(folder, *extra, report=None):
   rep = report or (folder.parent / "r.json")
   code = run_cli(["layers", "check", "--in", str(folder), *extra], rep)
   return code, read_json(rep)


# --- 7-가-1 : anchor · kind: mask 칸 ---


def test_anchor_names_match_split():
   assert layerset.ANCHOR_KINDS == ANCHOR_KINDS


def test_anchor_and_mask_round_trip_as_v2(tmp_path):
   data = {"version": 2, "canvas": [W, H], "anchor": "bbox_center",
           "layers": [{"name": "content", "kind": "content"}, {"name": "tier1", "kind": "mask"}], "items": []}
   ls = layerset.from_dict(data)
   assert ls.anchor == "bbox_center"
   assert ls.layer("tier1").kind == "mask"
   out = ls.to_dict()
   assert out["version"] == 2 and out["anchor"] == "bbox_center"
   assert layerset.from_dict(out).to_dict() == out


def test_anchor_point_kept_as_pair():
   ls = layerset.from_dict({"version": 2, "canvas": [W, H], "anchor": [5, 11], "layers": [{"name": "a", "kind": "deco"}]})
   assert ls.anchor == (5, 11)
   assert ls.to_dict()["anchor"] == [5, 11]


@pytest.mark.parametrize("anchor", ["middle", [13, 0], [0, 13], [0, -1], [1], [1.5, 2], True])   # [x, y] 는 변 좌표라 [12, 12] 까지 된다 (B1)
def test_bad_anchor_rejected(anchor):
   with pytest.raises(UsageError, match="anchor"):
      layerset.from_dict({"version": 2, "canvas": [W, H], "anchor": anchor, "layers": [{"name": "a", "kind": "deco"}]})


def test_v1_rejects_anchor_and_mask_kind():
   with pytest.raises(UsageError, match="version 2"):
      layerset.from_dict({"version": 1, "canvas": [W, H], "anchor": "bbox_center", "layers": [{"name": "a", "kind": "deco"}]})
   with pytest.raises(UsageError, match="version 2"):
      layerset.from_dict({"version": 1, "canvas": [W, H], "layers": [{"name": "a", "kind": "mask"}]})


def test_mask_kind_only_makes_v2():
   ls = layerset.LayerSet((W, H), [layerset.Layer("a", "deco"), layerset.Layer("m", "mask")])
   assert ls.to_dict()["version"] == 2
   assert "anchor" not in ls.to_dict()


def test_old_kinds_and_guess_kind_never_mask():
   assert "mask" not in layerset.KINDS            # 그리는 겹 낱말 목록은 그대로 (split · draw 가 이름 = kind 로 쓴다)
   assert "mask" in layerset.ALL_KINDS
   assert layerops.guess_kind("mask") == "deco"
   assert layerops.guess_kind("mask_hair") == "deco"
   assert layerops.guess_kind("hair_mask") == "hair"


def test_carry_meta_keeps_anchor():
   old = layerset.from_dict({"version": 2, "canvas": [W, H], "anchor": "bbox_center", "layers": [{"name": "a", "kind": "deco"}]})
   fresh = layerset.LayerSet((W, H), old.layers, ["x"])
   assert layerset.carry_meta(old, fresh).anchor == "bbox_center"


def _masked_set(tmp_path, gap=False):
   """content 회색 네모 + 층 마스크 둘(위 · 아래 반). 마스크는 그림에 안 쌓인다."""
   content = _box(2, 2, 10, 10, GRAY)
   tier1 = _box(2, 2, 10, 6, (255, 255, 255))
   tier2 = _box(2, 6, 10, 10, (255, 255, 255))
   if gap:
      tier2[9, 9] = 0
   rows = [{"name": "content", "kind": "content"}, {"name": "tier1", "kind": "mask"}, {"name": "tier2", "kind": "mask"}]
   return write_v2(tmp_path / "set", rows, {"f0": {"content": content, "tier1": tier1, "tier2": tier2}})


def test_mask_layers_are_not_stacked_or_checked_as_paint(tmp_path):
   folder = _masked_set(tmp_path)
   original = tmp_path / "f0.png"
   image.save(original, _box(2, 2, 10, 10, GRAY))
   code, rep = check(folder, "--original", str(original))
   assert code == errors.EXIT_OK
   assert rep["roundtrip_diff"] == 0
   assert [w["rule"] for w in rep["warnings"]] == []        # 마스크와 content 가 같은 칸이어도 poke · exclusive 가 안 난다
   assert set(rep) == {"version", "status", "in", "canvas", "layers", "items", "failed", "rules", "warnings", "roundtrip_diff"}


def test_mask_layers_left_out_of_cover(tmp_path):
   folder = _masked_set(tmp_path)
   cover = tmp_path / "cover.png"
   image.save(cover, _box(2, 2, 10, 10, (255, 255, 255)))
   code, rep = check(folder, "--cover", str(cover))
   assert code == errors.EXIT_OK
   assert rep["cover"][0]["overlap"] == 0                    # 마스크까지 세면 칸마다 2겹이 된다


def test_view_and_export_leave_mask_out(tmp_path):
   folder = _masked_set(tmp_path)
   assert run_cli(["layers", "export", "--in", str(folder), "--out", str(tmp_path / "ex"), "--flat"]) == errors.EXIT_OK
   flat = image.load(tmp_path / "ex" / "f0.png")
   assert np.all(flat[2:10, 2:10, :3] == GRAY)


def test_fill_refuses_mask_as_nearest(tmp_path):
   folder = _masked_set(tmp_path)
   mask = tmp_path / "m.png"
   image.save(mask, _box(0, 0, 12, 12, (255, 255, 255)))
   code = run_cli(["layers", "fill", "--in", str(folder), "--mask", str(mask), "--nearest", "tier1", "--out", str(tmp_path / "o")])
   assert code == errors.EXIT_USAGE


# --- 7-가-2 : --counts · 기준점 ---


def _frames(n, shift_at=None, dy=0):
   """bowl(아래) + tool(위) 장 n 개. shift_at 장은 tool 을 dy 만큼 내린다(bbox 바닥이 바뀐다)."""
   out = {}
   for i in range(n):
      tool = _box(4, 2, 8, 6 + (dy if i == shift_at else 0), RED)
      out[f"f{i}"] = {"bowl": _box(2, 6, 10, 10, GRAY), "tool": tool}
   return out


ROWS = [{"name": "bowl", "kind": "base"}, {"name": "tool", "kind": "deco"}]


def test_counts_same_and_reported(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(3))
   code, rep = check(folder, "--counts")
   assert code == errors.EXIT_OK
   assert rep["counts"] == {"bowl": 3, "tool": 3}
   assert rep["warnings"] == []


def test_counts_differ_warns(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(3))
   (folder / "tool" / "f2.png").unlink()
   _, rep = check(folder, "--counts")
   assert rep["counts"] == {"bowl": 3, "tool": 2}
   line = [w for w in rep["warnings"] if w["rule"] == "layer_count"]
   assert len(line) == 1 and "bowl 3 · tool 2" in line[0]["detail"]


def test_counts_refused_on_variant_set(tmp_path):
   folder = tmp_path / "set"
   data = {"version": 2, "canvas": [W, H], "layers": ROWS, "items": [{"name": "f0", "pick": {"bowl": "a", "tool": "b"}}]}
   layerset.save(folder, layerset.from_dict(data))
   image.save(folder / "bowl" / "a.png", _box(2, 6, 10, 10, GRAY))
   image.save(folder / "tool" / "b.png", _box(4, 2, 8, 6, RED))
   code = run_cli(["layers", "check", "--in", str(folder), "--counts"])
   assert code == errors.EXIT_USAGE


def test_anchor_name_same_on_every_frame(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(3), anchor="bbox_bottom_center")
   code, rep = check(folder)
   assert code == errors.EXIT_OK
   assert rep["anchors"] == [{"item": f"f{i}", "at": [6, 9]} for i in range(3)]
   assert rep["warnings"] == []


def test_anchor_name_moved_frame_warns_and_tol_lets_it_pass(tmp_path):
   frames = _frames(3)
   frames["f2"]["bowl"] = _box(2, 6, 10, 11, GRAY)        # 바닥이 한 칸 내려갔다
   folder = write_v2(tmp_path / "set", ROWS, frames, anchor="bbox_bottom_center")
   _, rep = check(folder)
   line = [w for w in rep["warnings"] if w["rule"] == "layer_anchor"]
   assert len(line) == 1 and "f2" in line[0]["detail"] and line[0]["items"] == [[6, 10]]
   _, rep = check(folder, "--anchor-tol", "1")
   assert [w for w in rep["warnings"] if w["rule"] == "layer_anchor"] == []


def test_anchor_point_compares_to_cell(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(2), anchor=[5, 8])
   _, rep = check(folder)
   line = [w for w in rep["warnings"] if w["rule"] == "layer_anchor"]
   assert len(line) == 2 and line[0]["items"] == [[6, 10]]                 # 변 좌표 : bbox 아래변 y1 (B1)


def test_anchor_ignores_mask_layers(tmp_path):
   rows = [*ROWS, {"name": "zone", "kind": "mask"}]
   frames = _frames(2)
   frames["f1"]["zone"] = _box(0, 0, 12, 12, (255, 255, 255))   # 마스크가 캔버스 전체여도 기준점은 그대로
   folder = write_v2(tmp_path / "set", rows, frames, anchor="bbox_bottom_center")
   _, rep = check(folder)
   assert [w["rule"] for w in rep["warnings"] if w["rule"] == "layer_anchor"] == []


@pytest.mark.parametrize("tol", ["-1", "65"])
def test_anchor_tol_range(tmp_path, tol):
   folder = write_v2(tmp_path / "set", ROWS, _frames(1), anchor="bbox_center")
   assert run_cli(["layers", "check", "--in", str(folder), "--anchor-tol", tol]) == errors.EXIT_USAGE


def test_anchor_tol_without_anchor_is_usage(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(1))
   assert run_cli(["layers", "check", "--in", str(folder), "--anchor-tol", "2"]) == errors.EXIT_USAGE


# --- 7-가-3 : --mask-of 합집합 ---


def test_mask_of_clean_is_zero(tmp_path):
   folder = _masked_set(tmp_path)
   code, rep = check(folder, "--mask-of", "content")
   assert code == errors.EXIT_OK
   assert rep["mask_of"] == {"base": "content", "masks": ["tier1", "tier2"],
                             "items": [{"item": "f0", "gap": 0, "overlap": 0, "outside": 0}]}
   assert rep["warnings"] == []


def test_mask_of_gap_overlap_outside(tmp_path):
   folder = _masked_set(tmp_path, gap=True)
   tier1 = image.load(folder / "tier1" / "f0.png")
   tier1[6, 2] = (255, 255, 255, 255)        # tier2 와 겹침
   tier1[0, 0] = (255, 255, 255, 255)        # content 밖
   image.save(folder / "tier1" / "f0.png", tier1)
   code, rep = check(folder, "--mask-of", "content")
   assert code == errors.EXIT_OK              # 모두 경고다
   assert rep["mask_of"]["items"] == [{"item": "f0", "gap": 1, "overlap": 1, "outside": 1}]
   rules = {w["rule"]: w for w in rep["warnings"]}
   assert set(rules) == {"layer_mask_gap", "layer_mask_overlap", "layer_mask_outside"}
   assert rules["layer_mask_gap"]["items"] == [[9, 9]]


def test_mask_of_needs_mask_layers_and_paint_base(tmp_path):
   folder = write_v2(tmp_path / "set", ROWS, _frames(1))
   assert run_cli(["layers", "check", "--in", str(folder), "--mask-of", "bowl"]) == errors.EXIT_USAGE
   folder = _masked_set(tmp_path / "b")
   assert run_cli(["layers", "check", "--in", str(folder), "--mask-of", "tier1"]) == errors.EXIT_USAGE
   assert run_cli(["layers", "check", "--in", str(folder), "--mask-of", "nope"]) == errors.EXIT_USAGE


# --- 7-가-4 : --holes ---


def _holed_set(tmp_path):
   """content 네모 안에 구멍 둘 : (4,4) 한 칸 · [6,8)×[6,8) 네 칸. lid 는 큰 구멍만 덮는다."""
   content = _box(2, 2, 10, 10, GRAY)
   content[4, 4] = 0
   content[6:8, 6:8] = 0
   lid = _box(6, 6, 8, 8, RED)
   rows = [{"name": "content", "kind": "content"}, {"name": "lid", "kind": "deco"}, {"name": "zone", "kind": "mask"}]
   zone = _box(0, 0, 12, 12, (255, 255, 255))
   zone[1:11, 1:11] = 0                       # 마스크 겹의 구멍은 안 센다
   return write_v2(tmp_path / "set", rows, {"f0": {"content": content, "lid": lid, "zone": zone}})


def test_holes_open_by_default(tmp_path):
   folder = _holed_set(tmp_path)
   code, rep = check(folder, "--holes")
   assert code == errors.EXIT_OK
   assert rep["holes"] == [{"item": "f0", "layer": "content", "count": 2, "cells": 5, "covered": 0, "open": 2,
                            "regions": [{"box": [6, 6, 8, 8], "cells": 4, "covered": False},
                                        {"box": [4, 4, 5, 5], "cells": 1, "covered": False}]}]
   line = [w for w in rep["warnings"] if w["rule"] == "layer_hole"]
   assert len(line) == 1 and len(line[0]["items"]) == 5


def test_holes_under_upper_layer_are_covered(tmp_path):
   folder = _holed_set(tmp_path)
   _, rep = check(folder, "--holes", "--holes-under", "lid")
   row = rep["holes"][0]
   assert (row["covered"], row["open"]) == (1, 1)
   line = [w for w in rep["warnings"] if w["rule"] == "layer_hole"]
   assert line[0]["items"] == [[4, 4]]          # 덮인 구멍은 경고에 안 든다


def test_hole_min_drops_small(tmp_path):
   folder = _holed_set(tmp_path)
   _, rep = check(folder, "--holes", "--hole-min", "2")
   assert rep["holes"][0]["count"] == 1 and rep["holes"][0]["cells"] == 4


def test_holes_bad_args(tmp_path):
   folder = _holed_set(tmp_path)
   base = ["layers", "check", "--in", str(folder)]
   assert run_cli([*base, "--holes", "--holes-under", "content"]) == errors.EXIT_USAGE    # 맨 아래 겹은 아무것도 못 덮는다
   assert run_cli([*base, "--holes", "--holes-under", "zone"]) == errors.EXIT_USAGE       # 마스크 겹
   assert run_cli([*base, "--holes-under", "lid"]) == errors.EXIT_USAGE                   # --holes 없이
   assert run_cli([*base, "--holes", "--hole-min", "0"]) == errors.EXIT_USAGE


def test_holes_list_capped(tmp_path, monkeypatch):
   from arttool.sprite import layerchecks
   monkeypatch.setattr(layerchecks, "HOLES_MAX", 1)
   folder = _holed_set(tmp_path)
   _, rep = check(folder, "--holes")
   assert len(rep["holes"][0]["regions"]) == 1 and rep["holes"][0]["more"] == 1


def test_labels_moved_but_light_same():
   from arttool import pieces
   from arttool.style import light
   mask = np.zeros((5, 5), dtype=bool)
   mask[0, 0] = mask[1, 1] = mask[4, 4] = True
   label, sizes = pieces.labels(mask)
   assert sizes.tolist() == [2, 1] and label[0, 0] == label[1, 1] == 0 and label[4, 4] == 1
   assert light._labels is pieces.labels


# --- 7-가-5 : --before · --shared-colors ---


def _two_tone(tmp_path, name, mid=None):
   """content 회색 두 단(밝 · 어둠). mid 를 주면 (5,5) 한 칸을 그 색으로 — 사례 8 「평균 메움」."""
   content = _box(2, 2, 10, 6, (160, 160, 160))
   content[6:10, 2:10] = (*(96, 96, 96), 255)
   if mid is not None:
      content[5, 5] = (*mid, 255)
   return write_v2(tmp_path / name, [{"name": "content", "kind": "content"}], {"f0": {"content": content}})


def test_before_new_color_from_average_fill(tmp_path):
   old = _two_tone(tmp_path, "old")
   new = _two_tone(tmp_path, "new", mid=(128, 128, 128))
   code, rep = check(new, "--before", str(old))
   assert code == errors.EXIT_OK
   assert rep["before"] == {"in": str(old), "items": [{"item": "f0", "layer": "content", "colors": [2, 3], "new": 1, "new_cells": 1}]}
   line = [w for w in rep["warnings"] if w["rule"] == "layer_new_color"]
   assert len(line) == 1 and line[0]["items"] == [[5, 5]]


def test_before_reused_color_is_quiet(tmp_path):
   old = _two_tone(tmp_path, "old")
   new = _two_tone(tmp_path, "new", mid=(96, 96, 96))        # 있던 색을 더 쓴 것
   _, rep = check(new, "--before", str(old))
   assert rep["before"]["items"][0]["new"] == 0
   assert rep["warnings"] == []


def test_before_missing_pair_warns(tmp_path):
   old = _two_tone(tmp_path, "old")
   new = write_v2(tmp_path / "new", [{"name": "content", "kind": "content"}],
                  {"f0": {"content": _box(2, 2, 10, 10, GRAY)}, "f1": {"content": _box(2, 2, 10, 10, GRAY)}})
   _, rep = check(new, "--before", str(old))
   line = [w for w in rep["warnings"] if w["rule"] == "layer_before_missing"]
   assert len(line) == 1 and "f1" in line[0]["detail"]


def test_before_must_be_folder(tmp_path):
   new = _two_tone(tmp_path, "new")
   assert run_cli(["layers", "check", "--in", str(new), "--before", str(tmp_path / "none")]) == errors.EXIT_ERROR


def _white_pair(tmp_path, glass_white=(246, 246, 244)):
   content = _box(2, 6, 10, 10, (250, 250, 250))             # 흰 내용물
   glass = _box(2, 2, 10, 6, (60, 90, 160))
   glass[3, 3] = (*glass_white, 255)                         # 흰 반사 한 칸
   rows = [{"name": "content", "kind": "content"}, {"name": "glass", "kind": "deco"}]
   return write_v2(tmp_path / "set", rows, {"f0": {"content": content, "glass": glass}})


def test_shared_colors_near_white(tmp_path):
   folder = _white_pair(tmp_path)
   code, rep = check(folder, "--shared-colors")
   assert code == errors.EXIT_OK
   line = [w for w in rep["warnings"] if w["rule"] == "layer_shared_color"]
   assert len(line) == 1
   assert "content · glass" in line[0]["detail"] and "#FAFAFA" in line[0]["detail"].upper()
   assert [3, 3] in line[0]["items"]


def test_shared_colors_tol_zero_is_quiet(tmp_path):
   folder = _white_pair(tmp_path)
   _, rep = check(folder, "--shared-colors", "--shared-tol", "0")
   assert [w for w in rep["warnings"] if w["rule"] == "layer_shared_color"] == []


def test_shared_colors_skips_busy_layer(tmp_path, monkeypatch):
   from arttool.sprite import layerchecks
   monkeypatch.setattr(layerchecks, "SHARED_COLORS_MAX", 1)
   folder = _white_pair(tmp_path)
   _, rep = check(folder, "--shared-colors")
   assert [w["rule"] for w in rep["warnings"]] == ["layer_shared_skipped"]


def test_shared_tol_needs_flag_and_range(tmp_path):
   folder = _white_pair(tmp_path)
   base = ["layers", "check", "--in", str(folder)]
   assert run_cli([*base, "--shared-tol", "3"]) == errors.EXIT_USAGE
   assert run_cli([*base, "--shared-colors", "--shared-tol", "65"]) == errors.EXIT_USAGE


# --- 7-가-6 : --known · --baseline · --fail-on-new ---


def test_fail_on_new_turns_warning_into_fail(tmp_path):
   folder = _holed_set(tmp_path)
   code, rep = check(folder, "--holes", "--fail-on-new")
   assert code == errors.EXIT_CHECK_FAIL
   assert rep["status"] == "fail" and rep["new_warnings"] == 5


def test_known_moves_hole_cells(tmp_path):
   folder = _holed_set(tmp_path)
   known = tmp_path / "known.json"
   write_json(known, [{"rule": "layer_hole", "where": "*", "note": "뚜껑 밑"}])
   code, rep = check(folder, "--holes", "--known", str(known), "--fail-on-new")
   assert code == errors.EXIT_OK
   assert rep["warnings"] == [] and rep["new_warnings"] == 0
   assert rep["known"][0]["rule"] == "layer_hole"


def test_baseline_round_trip_passes(tmp_path):
   folder = _holed_set(tmp_path)
   _, first = check(folder, "--holes", report=tmp_path / "first.json")
   code, rep = check(folder, "--holes", "--baseline", str(tmp_path / "first.json"), "--fail-on-new")
   assert code == errors.EXIT_OK and rep["new_warnings"] == 0


def test_no_known_args_no_known_keys(tmp_path):
   folder = _holed_set(tmp_path)
   _, rep = check(folder, "--holes")
   assert "known" not in rep and "new_warnings" not in rep
