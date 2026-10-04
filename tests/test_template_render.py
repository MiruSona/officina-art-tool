"""template render · 화풍 입히기 (설계 8-6 그리기 · 화풍 입히기 · fixed 줄, 10-3 layers 칸)."""

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from arttool import cli, image, layerset
from arttool.jsonio import read_json
from arttool.palette import load_ramps
from arttool.profile import tool_home
from arttool.sprite import split
from arttool.template import guide, run
from arttool.template.run import build

GUIDE_RGB = {(255, 0, 255), (0, 255, 255), (255, 255, 0)}


def args(name, size, out, **extra):
   base = {"sub": "render", "name": name, "size": size, "out_dir": str(out), "preset": None, "scale": None, "over": None, "profile": None}
   base.update(extra)
   return argparse.Namespace(**base)


def show(name, size=None, **extra):
   base = {"sub": "show", "name": name, "size": size, "preset": None, "profile": None}
   base.update(extra)
   return run.run(argparse.Namespace(**base))


def game_profile(tmp_path: Path, outline: str = "selout", palette: bool = True) -> str:
   """시험용 프로필. 램프 파일은 프로필 옆에 둔다(프로필 폴더 기준 상대경로)."""
   lines = ["name: e_game", "preset: topdown_action", "style:", f"  outline: {outline}", "  light: top_right"]
   if palette:
      shutil.copy(tool_home() / "palettes" / "lpc_cloth.json", tmp_path / "game_ramps.json")
      lines += ["palette:", "  ramps_file: game_ramps.json"]
   path = tmp_path / "e_game.yaml"
   path.write_text("\n".join(lines) + "\n", encoding="utf-8")
   return str(path)


def colors_of(arr) -> set:
   return {tuple(int(c) for c in px[:3]) for px in arr[arr[:, :, 3] > 0]}


def test_ring_burst_frames(tmp_path):
   result = run.run(args("fx_ring_burst", "16x16", tmp_path))
   assert result["status"] == "ok"
   frames = [image.load(tmp_path / f"fx_ring_burst_f{i:02d}.png") for i in range(5)]
   solid = [f[:, :, 3] > 0 for f in frames]
   counts = [int(s.sum()) for s in solid]
   assert counts[0] == 4                                   # 2×2 점
   assert solid[0][7:9, 7:9].all()
   assert solid[1][0, 7] and solid[1][7, 0] and solid[1][7, 7]   # 지름 16 꽉 찬 원
   assert counts[1] > counts[2] > counts[3] > counts[4] > 0      # 원 > 2px 고리 > 1px 고리 > 점선 고리
   assert not solid[2][7, 7] and solid[2][7, 1] and not solid[3][7, 1]  # 고리 두께 2 · 1
   for f in frames:
      assert colors_of(f) == {(255, 255, 255)}
      assert set(np.unique(f[:, :, 3])) <= {0, 255}


@pytest.mark.parametrize("name, size, preset", [
   ("char_small", "32x32", None), ("char_parts", "16x16", None), ("cycle_char", "16x16", "walk"),
   ("bg_screen", "180x320", None), ("ui9_panel", "16x16", None), ("icon_set", "16x16", None),
   ("tile_base", "16x16", None), ("fx_ring_burst", "16x16", None), ("fx_sparkle", "17x17", "big"),
   ("fx_dust", "8x8", None), ("motion_guide", "32x32", "cloth"),
])
def test_guide_uses_three_colors_and_binary_alpha(tmp_path, name, size, preset):
   run.run(args(name, size, tmp_path, preset=preset))
   arr = image.load(tmp_path / f"{name}_guide.png")
   assert image.size(arr) == tuple(int(v) for v in size.split("x"))
   assert colors_of(arr) <= GUIDE_RGB and colors_of(arr)
   assert set(np.unique(arr[:, :, 3])) <= {0, 255}
   data = read_json(tmp_path / "template.json")
   assert data["profile_applied"] is False and data["name"] == name
   # 10-3 : 모든 그림 템플릿이 layers.json 뼈대를 낸다
   ls = layerset.load(tmp_path)
   assert ls.canvas == image.size(arr) and ls.template == name and ls.items == []


def test_layers_skeleton_follows_kind_table(tmp_path):
   run.run(args("char_small", "16x16", tmp_path / "c"))
   ls = layerset.load(tmp_path / "c")
   assert ls.names() == ["body", "cloth", "face", "hair", "deco"]
   assert ls.exclusive_pairs() == [("face", "hair")] and ls.layer("deco").optional
   run.run(args("bg_screen", "180x320", tmp_path / "b"))
   assert layerset.load(tmp_path / "b").names() == ["base", "structure", "deco", "front"]
   run.run(args("fx_dust", "8x8", tmp_path / "f"))
   assert layerset.load(tmp_path / "f").names() == ["fx"]


def test_char_parts_masks_disjoint_and_split_reads(tmp_path):
   run.run(args("char_parts", "32x32", tmp_path))
   spec_path = tmp_path / "split.json"
   spec = split.load_spec(read_json(spec_path), tmp_path)
   masks = split._load_masks(spec)
   assert set(spec.layers) == {"body", "cloth_bottom", "cloth_top", "face", "hair", "deco"}
   assert len(masks) == 5                                   # deco 는 마스크 없음(optional)
   total = np.zeros((32, 32), dtype=int)
   for m in masks.values():
      total += m
   assert total.max() == 1                                  # 마스크끼리 안 겹친다
   # 얼굴은 네모가 아니라 눈 · 입 칸만
   face = image.load(tmp_path / "char_parts_mask_face.png")[:, :, 3] > 0
   lines = build("char_parts", "32x32", None, None)[0]["lines"]
   boxes = [lines["eye_box_l"], lines["eye_box_r"], lines["mouth"], *lines["cheeks"]]
   assert int(face.sum()) == sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in boxes)
   # split 이 실제로 거절하지 않는다 : 마스크 자리에 칠한 그림을 나눠 본다
   art = image.new(32, 32)
   art[total > 0] = (61, 92, 155, 255)
   parts, _ = split.split_array(art, spec, masks)
   assert parts


def test_cycle_frames_bob(tmp_path):
   run.run(args("cycle_char", "32x32", tmp_path, preset="walk"))
   shown = read_json(tmp_path / "template.json")
   tops = []
   for i in range(8):
      arr = image.load(tmp_path / f"cycle_char_f{i:02d}.png")
      white = np.all(arr[:, :, :3] == 255, axis=2) & (arr[:, :, 3] > 0)
      tops.append(int(np.argmax(white.any(axis=1))))
      assert (arr[shown["lines"]["baseline_y"], :, :3] == (255, 0, 255)).all()   # 기준선
   assert tops == shown["lines"]["head_top_y"]


def test_motion_frames_and_overlay_preview(tmp_path):
   run.run(args("motion_guide", "32x32", tmp_path, preset="hair", scale=4))
   dots = [image.load(tmp_path / f"motion_guide_f{i:02d}.png") for i in range(6)]
   for arr in dots:
      assert colors_of(arr) == {(0, 255, 255)}
      assert int((arr[:, :, 3] > 0).sum()) == 4
   preview = image.load(tmp_path / "motion_guide_preview.png")
   # 왼쪽 128×128 이 겹친 판, 오른쪽은 기준점 이름표 칸 (설계 8-3 미리보기 이름표)
   assert preview.shape[0] >= 128 and preview.shape[1] > 128


def test_tile_preview_is_2x2(tmp_path):
   run.run(args("tile_base", "16x16", tmp_path, scale=2))
   preview = image.load(tmp_path / "tile_base_preview.png")
   guide_arr = image.load(tmp_path / "tile_base_guide.png")
   assert np.array_equal(preview[:64, :64], guide.enlarge(guide.tile2x2(guide_arr), 2))


def test_profile_wins_over_template_style(tmp_path):
   prof = game_profile(tmp_path, outline="selout")
   shown = show("char_small", "32x32", profile=prof)
   assert shown["profile_applied"] is True and shown["profile"] == "e_game"
   assert shown["check"]["style"]["outline"] == "selout"
   assert shown["check"]["style"]["light"] == "top_right"
   assert "selective outline" in shown["prompt"] and "light from top-right" in shown["prompt"]


def test_profile_unset_outline_keeps_template_value(tmp_path):
   prof = game_profile(tmp_path, outline="unset", palette=False)
   shown = show("fx_dust", profile=prof)
   assert shown["check"]["style"]["outline"] == "none"


def test_fixed_field_keeps_template_value(tmp_path):
   prof = game_profile(tmp_path, outline="selout")
   shown = show("fx_ring_burst", profile=prof)
   assert shown["fixed"] == ["style.outline"]
   assert shown["check"]["style"]["outline"] == "none"      # fixed 칸만 템플릿이 이긴다
   assert shown["check"]["style"]["light"] == "top_right"   # 나머지는 프로필
   assert shown["check"]["frames"] == 5 and shown["check"]["size"] == [16, 16]


def test_palette_applied_to_prompt_check_and_band(tmp_path):
   prof = game_profile(tmp_path)
   ramps = load_ramps(tmp_path / "game_ramps.json")
   plain = run.run(args("char_small", "16x16", tmp_path / "plain", scale=4))
   styled = run.run(args("char_small", "16x16", tmp_path / "styled", scale=4, profile=prof))
   data = read_json(tmp_path / "styled" / "template.json")
   # ⓑ 프롬프트에 프로필 색 hex — 램프마다 가운데 칸
   for name in ramps.names():
      middle = ramps.ramp(name)[len(ramps.ramp(name)) // 2]
      assert "#{:02X}{:02X}{:02X}".format(*middle) in data["prompt"]
   # ⓓ check 에 램프 파일 절대 경로 · 외곽선
   ramps_file = Path(data["check"]["palette"]["ramps_file"])
   assert ramps_file.is_absolute() and ramps_file.samefile(tmp_path / "game_ramps.json")
   assert data["check"]["palette"]["outline"] == "#000000"
   # ⓐ 견본 띠 줄 수 = 램프 수 (미리보기가 띠 높이 + 틈 만큼 커진다)
   cell = max(8, 4 * 2)
   band_h = len(ramps.names()) * (cell + 1) + 1
   h_plain = image.load(tmp_path / "plain" / "char_small_preview.png").shape[0]
   h_styled = image.load(tmp_path / "styled" / "char_small_preview.png").shape[0]
   assert h_styled == h_plain + 4 * guide.GAP + band_h
   # 1배 가이드에는 띠가 안 들어간다
   assert colors_of(image.load(tmp_path / "styled" / "char_small_guide.png")) <= GUIDE_RGB
   assert plain["profile_applied"] is False and styled["profile_applied"] is True


def test_profile_without_palette_has_no_band(tmp_path):
   prof = game_profile(tmp_path, palette=False)
   run.run(args("char_small", "16x16", tmp_path / "a", scale=4))
   run.run(args("char_small", "16x16", tmp_path / "b", scale=4, profile=prof))
   a = image.load(tmp_path / "a" / "char_small_preview.png")
   b = image.load(tmp_path / "b" / "char_small_preview.png")
   assert a.shape == b.shape
   data = read_json(tmp_path / "b" / "template.json")
   assert "palette" not in data["check"] and data["palette"] is None
   assert "palette" not in data["prompt"]


def test_swatch_band_rows():
   band = guide.swatch_band([[(1, 2, 3)] * 6, [(4, 5, 6)] * 6, [(7, 8, 9)] * 6], 8)
   assert band.shape[0] == 3 * 9 + 1


def test_palette_ramp_base_mode_writes_ramp_file(tmp_path):
   result = run.run(args("palette_ramp", "16x16", tmp_path, preset="metal"))
   ramp_file = tmp_path / "palette_ramp_ramp.json"
   assert str(ramp_file) in result["files"]
   ramps = load_ramps(ramp_file)
   assert ramps.names() == ["metal"] and ramps.ramp_len == 5
   assert ramps.ramp("metal")[2] == (0x3D, 0x5C, 0x9B)       # 밑색이 가운데 칸
   assert not (tmp_path / "layers.json").exists()


def test_palette_ramp_profile_mode_uses_profile_ramps(tmp_path):
   prof = game_profile(tmp_path)
   result = run.run(args("palette_ramp", "16x16", tmp_path / "o", profile=prof))
   assert not (tmp_path / "o" / "palette_ramp_ramp.json").exists()
   data = read_json(tmp_path / "o" / "template.json")
   assert data["lines"]["mode"] == "profile"
   report = data["lines"]["report"]
   assert set(report) == set(load_ramps(tmp_path / "game_ramps.json").names())
   assert all(r["steps"] == 6 and r["monotonic"] and r["padded"] == 0 for r in report.values())
   assert result["status"] == "ok"


def test_palette_ramp_base_with_profile_uses_profile_ramp_len(tmp_path):
   prof = game_profile(tmp_path)
   shown = show("palette_ramp", profile=prof, preset="gem", base="#9B3D3D")
   assert shown["lines"]["mode"] == "base" and len(shown["lines"]["ramp"]) == 6


def test_over_writes_enlarged_overlay(tmp_path):
   pic = image.new(16, 16, (10, 20, 30, 255))
   image.save(tmp_path / "pic.png", pic)
   result = run.run(args("char_small", "16x16", tmp_path / "o", scale=4, over=str(tmp_path / "pic.png")))
   over = image.load(tmp_path / "o" / "char_small_over.png")
   assert image.size(over) == (64, 64) and result["status"] == "ok"
   # 가이드가 없는 칸은 그림 색 그대로
   assert tuple(over[2, 2, :3]) == (10, 20, 30)


def test_over_size_mismatch_warns(tmp_path):
   image.save(tmp_path / "pic.png", image.new(20, 12, (10, 20, 30, 255)))
   result = run.run(args("char_small", "16x16", tmp_path / "o", over=str(tmp_path / "pic.png")))
   assert result["status"] == "warn"
   assert [w["rule"] for w in result["warnings"]] == ["template.over_size"]


def test_profile_tile_size_is_allowed_and_default(tmp_path):
   prof = game_profile(tmp_path)
   shown = show("tile_base", profile=prof)
   assert shown["size"] == [16, 16] and shown["check"]["tiles"]["size"] == 16
   shown = show("tile_base", "32x32", profile=prof)
   assert shown["status"] == "warn" and shown["warnings"][0]["rule"] == "template.tile_size"


def test_cli_render_and_show(tmp_path, capsys):
   out = tmp_path / "g"
   assert cli.main(["template", "render", "fx_ring_burst", "--size", "16x16", "--out", str(out), "--json"]) == 0
   assert (out / "fx_ring_burst_f04.png").is_file() and (out / "template.json").is_file()
   capsys.readouterr()
   assert cli.main(["template", "show", "char_small", "--size", "32x32", "--json"]) == 0
   data = json.loads(capsys.readouterr().out)
   assert data["preset"] == "sd" and data["lines"]["crotch_y"] == 26
   assert cli.main(["template", "show", "char_small", "--size", "20x20"]) == 2
