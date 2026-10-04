"""layers 묶음 명령 — diff · mask · view · check · export (설계 10-4 · 10-6). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import json

import numpy as np
import pytest

from arttool import cli, errors, image, layerset
from arttool import sheet as sheet_mod
from arttool.jsonio import read_json
from arttool.sprite import layers as layers_mod

OUT = (20, 16, 16)
SKIN = (250, 220, 190)
HAIR = (90, 50, 30)
EYE = (30, 30, 80)
W = H = 12


def _fill(arr, x0, y0, x1, y1, rgb):
   arr[y0:y1, x0:x1] = (*rgb, 255)


def base_body():
   """12×12 기본체. 외곽선 네모 [2, 10) × [2, 12) 안에 살색."""
   arr = image.new(W, H)
   _fill(arr, 2, 2, 10, 12, OUT)
   _fill(arr, 3, 3, 9, 11, SKIN)
   return arr


def hair_result(carve=3):
   """머리만 바꾼 판 : 윗부분 [2, 10) × [3, 6) 머리색 + 정수리 외곽선 carve 칸을 투명으로."""
   arr = base_body()
   _fill(arr, 2, 3, 10, 6, HAIR)
   for x in range(4, 4 + carve):
      arr[2, x] = 0
   return arr


def face_result():
   arr = base_body()
   arr[7, 4] = (*EYE, 255)
   arr[7, 7] = (*EYE, 255)
   return arr


def run_cli(argv, report=None):
   if report is not None:
      argv = [*argv, "--report", str(report)]
   return cli.main(argv)


def make_diff(tmp_path, carve="report", results=None):
   image.save(tmp_path / "idle.png", base_body())
   inp = tmp_path / "inp"
   inp.mkdir(exist_ok=True)
   for name, arr in (results or {"hair": hair_result()}).items():
      image.save(inp / f"{name}.png", arr)
   rep = tmp_path / "diff.json"
   code = run_cli(["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(inp), "--out", str(tmp_path / "set"), "--carve", carve], rep)
   return code, read_json(rep)


def stacked(folder, item="idle"):
   ls = layerset.load(folder)
   return layers_mod.compose(ls.names(), layerset.read_item(folder, ls, item))


# --- diff ---


def test_diff_takes_changed_cells_as_layer(tmp_path):
   code, rep = make_diff(tmp_path)
   assert code == errors.EXIT_OK
   hair = image.load(tmp_path / "set" / "hair" / "idle.png")
   assert np.count_nonzero(hair[:, :, 3]) == 8 * 3
   assert np.all(hair[3:6, 2:10, :3] == HAIR)
   assert rep["layers"]["hair"]["pixels"] == 24
   ls = layerset.load(tmp_path / "set")
   assert ls.names() == ["body", "hair"] and ls.items == ["idle"]


def test_diff_carve_report_counts_but_keeps_body(tmp_path):
   """기본 report : 깎인 칸을 세어 경고만 하고 본체는 그대로 (머리 파츠가 여럿이면 구멍이 쌓이므로)."""
   code, rep = make_diff(tmp_path)
   assert rep["carve"] == "report"
   assert rep["layers"]["hair"]["carved"]["count"] == 3
   assert rep["layers"]["hair"]["carved"]["points"] == [[4, 2], [5, 2], [6, 2]]
   assert rep["status"] == "warn" and any(w["rule"] == "diff_carved" for w in rep["warnings"])
   body = image.load(tmp_path / "set" / "body" / "idle.png")
   assert np.array_equal(body, base_body())
   assert rep["layers"]["body"]["carved_removed"] == 0


def test_diff_carve_apply_follows_result(tmp_path):
   code, rep = make_diff(tmp_path, carve="apply")
   body = image.load(tmp_path / "set" / "body" / "idle.png")
   assert body[2, 5, 3] == 0 and rep["layers"]["body"]["carved_removed"] == 3
   # apply 는 결과를 따른다 : 쌓으면 inpaint 결과와 같다.
   assert np.array_equal(stacked(tmp_path / "set"), hair_result())


def test_diff_carve_common_removes_only_cells_every_layer_carved(tmp_path):
   """hair 는 (4..6, 2) 를, face 는 (4, 2) · (8, 2) 를 깎았다 → 둘 다 깎은 (4, 2) 만 본체에서 빠진다."""
   face = face_result()
   face[2, 4] = 0
   face[2, 8] = 0
   _, rep = make_diff(tmp_path, carve="common", results={"hair": hair_result(), "face": face})
   body = image.load(tmp_path / "set" / "body" / "idle.png")
   assert body[2, 4, 3] == 0
   assert body[2, 5, 3] == 255 and body[2, 8, 3] == 255
   assert rep["layers"]["body"]["carved_removed"] == 1 and rep["carved_all"]["points"] == [[4, 2]]
   _, applied = make_diff(tmp_path, carve="apply", results={"hair": hair_result(), "face": face})
   assert applied["layers"]["body"]["carved_removed"] == 4


def test_diff_carve_keep_is_gone(tmp_path):
   image.save(tmp_path / "idle.png", base_body())
   (tmp_path / "inp").mkdir()
   image.save(tmp_path / "inp" / "hair.png", hair_result())
   argv = ["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(tmp_path / "inp"), "--out", str(tmp_path / "set"), "--carve", "keep"]
   with pytest.raises(SystemExit) as caught:
      cli.main(argv)
   assert caught.value.code == errors.EXIT_USAGE


def test_diff_carved_all_only_counts_cells_every_layer_carved(tmp_path):
   _, rep = make_diff(tmp_path, results={"hair": hair_result(), "face": face_result()})
   assert rep["carved_all"]["count"] == 0
   both = face_result()
   both[2, 4] = 0
   _, rep = make_diff(tmp_path, results={"hair": hair_result(), "face": both})
   assert rep["carved_all"]["points"] == [[4, 2]]


def test_diff_orders_character_layers(tmp_path):
   make_diff(tmp_path, results={"hair": hair_result(), "face": face_result()})
   assert layerset.load(tmp_path / "set").names() == ["body", "face", "hair"]


def test_diff_overlap_goes_to_upper_layer(tmp_path):
   face = face_result()
   _fill(face, 3, 4, 5, 5, EYE)    # 머리 겹 자리와 겹친다
   _, rep = make_diff(tmp_path, results={"hair": hair_result(), "face": face})
   assert any(w["rule"] == "diff_overlap" for w in rep["warnings"])
   face_layer = image.load(tmp_path / "set" / "face" / "idle.png")
   assert face_layer[4, 3, 3] == 0


def test_diff_template_mask_counts_outside(tmp_path):
   guide = tmp_path / "guide"
   guide.mkdir()
   (guide / "template.json").write_text(json.dumps({"name": "t"}), encoding="utf-8")
   mask = image.new(W, H)
   mask[0:4, :] = 255                   # 위 네 줄만 — 머리 셋째 줄(y=5)·넷째 줄 밖
   image.save(guide / "t_mask_hair.png", mask)
   image.save(tmp_path / "idle.png", base_body())
   (tmp_path / "inp").mkdir()
   image.save(tmp_path / "inp" / "hair.png", hair_result(carve=0))
   rep_file = tmp_path / "r.json"
   run_cli(["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(tmp_path / "inp"), "--out", str(tmp_path / "set"),
            "--template", str(guide / "template.json")], rep_file)
   rep = read_json(rep_file)
   assert rep["layers"]["hair"]["outside_mask"] == 16
   assert any(w["rule"] == "diff_outside_mask" for w in rep["warnings"])
   assert layerset.load(tmp_path / "set").template == "t"


def test_diff_size_mismatch_is_error(tmp_path):
   code, _ = None, None
   image.save(tmp_path / "idle.png", base_body())
   (tmp_path / "inp").mkdir()
   image.save(tmp_path / "inp" / "hair.png", image.new(8, 8))
   code = run_cli(["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(tmp_path / "inp"), "--out", str(tmp_path / "set")])
   assert code == errors.EXIT_ERROR


def test_diff_rejects_body_named_input(tmp_path):
   image.save(tmp_path / "idle.png", base_body())
   (tmp_path / "inp").mkdir()
   image.save(tmp_path / "inp" / "body.png", base_body())
   code = run_cli(["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(tmp_path / "inp"), "--out", str(tmp_path / "set")])
   assert code == errors.EXIT_USAGE


# --- mask ---


def test_mask_picks_colors_and_grows(tmp_path):
   image.save(tmp_path / "b.png", hair_result(carve=0))
   out = tmp_path / "m.png"
   assert run_cli(["layers", "mask", "--in", str(tmp_path / "b.png"), "--colors", "#5A321E", "--out", str(out)]) == errors.EXIT_OK
   mask = image.load(out)
   assert np.count_nonzero(mask[:, :, 3]) == 24
   assert np.all(mask[mask[:, :, 3] > 0][:, :3] == 255)

   assert run_cli(["layers", "mask", "--in", str(tmp_path / "b.png"), "--colors", "#5A321E,#FAdCBE", "--grow", "1", "--out", str(out)]) == errors.EXIT_OK
   mask = image.load(out)
   # 머리 [2,10)×[3,6) → [1,11)×[2,7) 열 칸 × 다섯 줄, 살 [3,9)×[6,11) → [2,10)×[7,12) 여덟 칸 × 다섯 줄
   assert np.count_nonzero(mask[:, :, 3]) == 10 * 5 + 8 * 5


def test_mask_missing_color_warns_and_bad_hex_is_usage(tmp_path):
   image.save(tmp_path / "b.png", base_body())
   rep = cli.run(cli.build_parser().parse_args(["layers", "mask", "--in", str(tmp_path / "b.png"), "--colors", "#123456", "--out", str(tmp_path / "m.png")]))
   assert rep["status"] == "warn" and rep["warnings"][0]["rule"] == "mask_color_missing"
   assert run_cli(["layers", "mask", "--in", str(tmp_path / "b.png"), "--colors", "red", "--out", str(tmp_path / "m.png")]) == errors.EXIT_USAGE
   assert run_cli(["layers", "mask", "--in", str(tmp_path / "b.png"), "--colors", "#123456", "--grow", "-1", "--out", str(tmp_path / "m.png")]) == errors.EXIT_USAGE


# --- 손으로 만든 겹 묶음 ---


def write_set(folder, parts: dict, rows=None, items=("idle",), canvas=(W, H)):
   rows = rows or [{"name": n, "kind": n if n in layerset.KINDS else "deco"} for n in parts]
   ls = layerset.from_dict({"version": 1, "canvas": list(canvas), "layers": rows, "items": list(items)})
   layerset.save(folder, ls)
   for name, arr in parts.items():
      if arr is not None:
         image.save(folder / name / f"{items[0]}.png", arr)
   return ls


def three_layers():
   body = base_body()
   hair = image.new(W, H)
   _fill(hair, 2, 2, 10, 5, HAIR)
   face = image.new(W, H)
   face[7, 4] = (*EYE, 255)
   face[7, 7] = (*EYE, 255)
   return {"body": body, "face": face, "hair": hair}


def check(folder, *extra):
   rep = cli.run(cli.build_parser().parse_args(["layers", "check", "--in", str(folder), *extra]))
   return rep


# --- check ---


def test_check_clean_set_with_original_is_ok(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   original = layers_mod.compose(list(parts), parts)
   image.save(tmp_path / "idle.png", original)
   rep = check(tmp_path / "set", "--original", str(tmp_path / "idle.png"))
   assert rep["status"] == "ok", rep["warnings"]
   assert rep["roundtrip_diff"] == 0


def test_check_original_differs_is_fail_exit_4(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   other = layers_mod.compose(list(parts), parts)
   other[0, 0] = (1, 2, 3, 255)
   image.save(tmp_path / "idle.png", other)
   rep = check(tmp_path / "set", "--original", str(tmp_path / "idle.png"))
   assert rep["status"] == "fail" and rep["failed"] == ["original"] and rep["roundtrip_diff"] == 1
   assert rep["rules"][0]["items"] == [[0, 0]]
   assert cli.main(["layers", "check", "--in", str(tmp_path / "set"), "--original", str(tmp_path / "idle.png")]) == errors.EXIT_CHECK_FAIL


def test_check_empty_layer_but_not_optional(tmp_path):
   parts = three_layers()
   parts["deco"] = None
   parts["cloth"] = image.new(W, H)
   rows = [{"name": "body", "kind": "body"}, {"name": "cloth", "kind": "cloth"}, {"name": "face", "kind": "face"},
           {"name": "hair", "kind": "hair"}, {"name": "deco", "kind": "deco", "optional": True}]
   write_set(tmp_path / "set", parts, rows)
   rep = check(tmp_path / "set")
   empties = [w for w in rep["warnings"] if w["rule"] == "layer_empty"]
   assert len(empties) == 1 and "cloth" in empties[0]["detail"]


def test_check_exclusive_overlap(tmp_path):
   parts = three_layers()
   parts["face"][3, 4] = (*EYE, 255)           # 머리 자리에 눈
   rows = [{"name": "body", "kind": "body"}, {"name": "face", "kind": "face", "exclusive_with": ["hair"]}, {"name": "hair", "kind": "hair"}]
   write_set(tmp_path / "set", parts, rows)
   rep = check(tmp_path / "set")
   hit = [w for w in rep["warnings"] if w["rule"] == "layer_exclusive"]
   assert len(hit) == 1 and hit[0]["items"] == [[4, 3]]
   assert set(hit[0]) == {"rule", "ok", "detail", "items"} and hit[0]["ok"] is False


def test_check_canvas_size_and_soft_alpha(tmp_path):
   parts = three_layers()
   parts["face"] = image.new(8, 8)
   parts["hair"][3, 3, 3] = 128
   write_set(tmp_path / "set", parts)
   rules = {w["rule"] for w in check(tmp_path / "set")["warnings"]}
   assert {"layer_canvas", "layer_alpha"} <= rules


def test_check_poke_marks_carved_outline_trace(tmp_path):
   """머리 겹이 외곽선 안쪽만 칠하면 아래 몸 외곽선이 머리 바깥으로 한 줄 남는다."""
   parts = three_layers()
   hair = image.new(W, H)
   _fill(hair, 3, 3, 9, 5, HAIR)
   parts["hair"] = hair
   write_set(tmp_path / "set", parts)
   hit = [w for w in check(tmp_path / "set")["warnings"] if w["rule"] == "layer_poke"]
   assert hit and "body" in hit[0]["detail"] and [5, 2] in hit[0]["items"]


def test_check_template_mask_outside(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   guide = tmp_path / "g"
   guide.mkdir()
   (guide / "template.json").write_text(json.dumps({"name": "c"}), encoding="utf-8")
   mask = image.new(W, H)
   mask[0:4, :] = 255
   image.save(guide / "c_mask_hair.png", mask)
   hit = [w for w in check(tmp_path / "set", "--template", str(guide / "template.json"))["warnings"] if w["rule"] == "layer_mask"]
   assert len(hit) == 1 and "8" in hit[0]["detail"]


# --- view ---


def view(argv):
   return cli.run(cli.build_parser().parse_args(["layers", "view", *argv]))


def test_view_each_lays_layers_then_stack(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   out = tmp_path / "v.png"
   rep = view(["--in", str(tmp_path / "set"), "--each", "--scale", "2", "--out", str(out)])
   board = image.load(out)
   # 비교판(sheet.layout_rows)과 같은 판 : 겹 셋 + 합침 = 네 칸, 칸마다 바둑판 위 확대, 겹 이름 딱지
   cells = [*(parts[n] for n in parts), layers_mod.compose(list(parts), parts)]
   want = sheet_mod.layout_rows([[sheet_mod.render_kind(c, "zoom", 2) for c in cells]], ["idle"], [*parts, "합침"])
   assert np.array_equal(board, want)
   assert rep["label"] is True and rep["status"] == "ok"


def test_view_each_without_font_drops_labels(tmp_path, monkeypatch):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   monkeypatch.setattr(image, "has_label_font", lambda: False)
   data = view(["--in", str(tmp_path / "set"), "--each", "--out", str(tmp_path / "v.png")])
   assert data["label"] is False and data["status"] == "warn" and data["warnings"][0]["rule"] == "label_font"
   cells = [*(parts[n] for n in parts), layers_mod.compose(list(parts), parts)]
   assert np.array_equal(image.load(tmp_path / "v.png"), sheet_mod.layout_rows([[sheet_mod.render_kind(c, "zoom", 1) for c in cells]]))


def test_view_hide_and_only(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   out = tmp_path / "v.png"
   def board(names):
      cell = layers_mod.compose(names, {n: parts[n] for n in names})
      return sheet_mod.layout_rows([[sheet_mod.render_kind(cell, "zoom", 1)]], ["idle"], ["합침"])

   cli.main(["layers", "view", "--in", str(tmp_path / "set"), "--hide", "hair", "--out", str(out)])
   assert np.array_equal(image.load(out), board(["body", "face"]))
   cli.main(["layers", "view", "--in", str(tmp_path / "set"), "--only", "hair", "--out", str(out)])
   assert np.array_equal(image.load(out), board(["hair"]))
   assert cli.main(["layers", "view", "--in", str(tmp_path / "set"), "--only", "nope", "--out", str(out)]) == errors.EXIT_USAGE


# --- export ---


def test_export_flat_and_each_keep_canvas(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   rep = cli.run(cli.build_parser().parse_args(["layers", "export", "--in", str(tmp_path / "set"), "--out", str(tmp_path / "u"), "--flat", "--each"]))
   assert rep["files"] == ["idle.png", "idle_body.png", "idle_face.png", "idle_hair.png"]
   assert image.size(image.load(tmp_path / "u" / "idle_face.png")) == (W, H)
   assert np.array_equal(image.load(tmp_path / "u" / "idle.png"), layers_mod.compose(list(parts), parts))
   assert rep["anchor"]["canvas"] == [6, 11]


def test_export_trim_common_same_offset_and_rebuilds(tmp_path):
   parts = three_layers()
   write_set(tmp_path / "set", parts)
   out = tmp_path / "u"
   assert cli.main(["layers", "export", "--in", str(tmp_path / "set"), "--out", str(out), "--each", "--flat", "--trim-common"]) == errors.EXIT_OK
   offsets = read_json(out / "offsets.json")
   assert offsets["bbox"] == [2, 2, 10, 12] and offsets["size"] == [8, 10]
   assert {tuple(v) for v in offsets["files"].values()} == {(2, 2)}
   # trim --common 보고와 같은 칸
   assert offsets["common"] is True and offsets["pad"] == 0 and offsets["square"] is False
   assert {tuple(row["offset"]) for row in offsets["images"]} == {(2, 2)} and offsets["images"][0]["size"] == [8, 10]
   assert offsets["anchor"]["out"] == [4, 9]
   rebuilt = {}
   for name in parts:
      canvas = image.new(W, H)
      image.paste(canvas, image.load(out / f"idle_{name}.png"), 2, 2)
      rebuilt[name] = canvas
   assert np.array_equal(layers_mod.compose(list(parts), rebuilt), layers_mod.compose(list(parts), parts))


def test_export_needs_flat_or_each(tmp_path):
   write_set(tmp_path / "set", three_layers())
   assert cli.main(["layers", "export", "--in", str(tmp_path / "set"), "--out", str(tmp_path / "u")]) == errors.EXIT_USAGE


# --- 흐름 ---


def test_diff_output_passes_check_against_result(tmp_path):
   make_diff(tmp_path, carve="apply")
   image.save(tmp_path / "idle_hair.png", hair_result())
   rep = check(tmp_path / "set", "--original", str(tmp_path / "idle_hair.png"))
   assert rep["failed"] == [] and rep["roundtrip_diff"] == 0


def test_unknown_sub_is_usage():
   from arttool.sprite import layerops

   class Args:
      sub = "zzz"

   with pytest.raises(errors.UsageError):
      layerops.run(Args())


# --- 원본 보호 · 보강 판 ---


def test_mask_refuses_to_overwrite_input(tmp_path):
   """layers mask --out 이 --in 과 같으면 거절 (R1-H2)."""
   image.save(tmp_path / "b.png", base_body())
   before = (tmp_path / "b.png").read_bytes()
   assert run_cli(["layers", "mask", "--in", str(tmp_path / "b.png"), "--colors", "#FADCBE", "--out", str(tmp_path / "B.png")]) == errors.EXIT_USAGE
   assert (tmp_path / "b.png").read_bytes() == before


def test_view_refuses_output_inside_set(tmp_path):
   """layers view --out 이 겹 묶음 폴더 안이면 거절 — 겹 PNG 를 덮을 수 있다 (R1-H2)."""
   write_set(tmp_path / "set", three_layers())
   target = tmp_path / "set" / "body" / "idle.png"
   before = target.read_bytes()
   assert cli.main(["layers", "view", "--in", str(tmp_path / "set"), "--out", str(target)]) == errors.EXIT_USAGE
   assert cli.main(["layers", "view", "--in", str(tmp_path / "set"), "--out", str(tmp_path / "set" / "v.png")]) == errors.EXIT_USAGE
   assert target.read_bytes() == before and not (tmp_path / "set" / "v.png").exists()
   assert cli.main(["layers", "view", "--in", str(tmp_path / "set"), "--scale", "65", "--out", str(tmp_path / "v.png")]) == errors.EXIT_USAGE


def test_diff_refuses_to_overwrite_base(tmp_path):
   """이미 있는 묶음의 body 를 --base 로 주고 같은 묶음에 다시 diff 하면 거절 (R1-H3)."""
   make_diff(tmp_path)
   base = tmp_path / "set" / "body" / "idle.png"
   before = base.read_bytes()
   code = run_cli(["layers", "diff", "--base", str(base), "--in", str(tmp_path / "inp"), "--out", str(tmp_path / "set")])
   assert code == errors.EXIT_USAGE and base.read_bytes() == before


def test_diff_base_inside_in_folder_is_left_out(tmp_path):
   """--base 가 --in 폴더 안이면 기본체를 겹으로 세지 않는다 (R1-L3)."""
   inp = tmp_path / "inp"
   inp.mkdir()
   image.save(inp / "idle.png", base_body())
   image.save(inp / "hair.png", hair_result())
   rep_file = tmp_path / "r.json"
   assert run_cli(["layers", "diff", "--base", str(inp / "idle.png"), "--in", str(inp), "--out", str(tmp_path / "set")], rep_file) == errors.EXIT_OK
   rep = read_json(rep_file)
   assert layerset.load(tmp_path / "set").names() == ["body", "hair"]
   assert any(w["rule"] == "diff_base_in_folder" for w in rep["warnings"])


def test_diff_guesses_kind_and_order_from_prefix(tmp_path):
   """템플릿 없이 : 이름 앞 낱말로 kind, 순서는 body < cloth < face < hair < deco (실물 #24)."""
   results = {"hair": hair_result(), "cloth_top": face_result(), "cloth_bottom": face_result(), "face": face_result(), "cape": face_result()}
   make_diff(tmp_path, results=results)
   ls = layerset.load(tmp_path / "set")
   assert ls.names() == ["body", "cloth_bottom", "cloth_top", "face", "hair", "cape"]
   assert [layer.kind for layer in ls.layers] == ["body", "cloth", "cloth", "face", "hair", "deco"]


def test_export_flat_name_clash_is_refused(tmp_path):
   """items [a, a_b] + 겹 b + --flat --each : a_b.png 가 조용히 덮이던 것 (R1-M1)."""
   rows = [{"name": "body", "kind": "body"}, {"name": "b", "kind": "deco"}]
   ls = layerset.from_dict({"version": 1, "canvas": [W, H], "layers": rows, "items": ["a", "a_b"]})
   layerset.save(tmp_path / "set", ls)
   for item in ("a", "a_b"):
      image.save(tmp_path / "set" / "body" / f"{item}.png", base_body())
      image.save(tmp_path / "set" / "b" / f"{item}.png", face_result())
   code = cli.main(["layers", "export", "--in", str(tmp_path / "set"), "--out", str(tmp_path / "u"), "--flat", "--each"])
   assert code == errors.EXIT_ERROR and not (tmp_path / "u").exists()


def test_poke_ignores_body_around_face_but_keeps_long_trace(tmp_path):
   """얼굴 둘레로 본체가 1칸 보이는 것은 정상 (S1). 짧은 한두 칸도 안 잡는다. 긴 깎인 윤곽 띠는 그대로 잡는다."""
   parts = three_layers()
   face = image.new(W, H)
   _fill(face, 3, 3, 9, 6, EYE)              # 머리 외곽선 바로 안쪽까지 얼굴 카드 — 위 외곽선이 얼굴 바깥 1칸
   parts["face"] = face
   parts["hair"] = image.new(W, H)
   parts["hair"][0, 0] = (*HAIR, 255)
   write_set(tmp_path / "set", parts)
   assert not [w for w in check(tmp_path / "set")["warnings"] if w["rule"] == "layer_poke"]

   # 머리가 외곽선 안쪽만 칠한 긴 띠는 여전히 잡는다 (test_check_poke_marks_carved_outline_trace 와 같은 꼴)
   hair = image.new(W, H)
   _fill(hair, 3, 3, 9, 5, HAIR)
   parts = three_layers()
   parts["hair"] = hair
   write_set(tmp_path / "set2", parts)
   assert [w for w in check(tmp_path / "set2")["warnings"] if w["rule"] == "layer_poke"]


def test_poke_exclusive_pair_is_always_checked(tmp_path):
   """exclusive_with 짝(face · hair)은 짧아도 · face 가 위여도 다 본다."""
   body = image.new(W, H)
   hair = image.new(W, H)
   _fill(hair, 4, 4, 6, 6, HAIR)
   face = image.new(W, H)
   face[3, 4] = (*EYE, 255)                  # 머리 위로 한 칸 — 바깥은 빈 칸
   rows = [{"name": "body", "kind": "body", "optional": True}, {"name": "face", "kind": "face", "exclusive_with": ["hair"]}, {"name": "hair", "kind": "hair"}]
   write_set(tmp_path / "set", {"body": body, "face": face, "hair": hair}, rows)
   hit = [w for w in check(tmp_path / "set")["warnings"] if w["rule"] == "layer_poke"]
   assert hit and hit[0]["items"] == [[4, 3]]
