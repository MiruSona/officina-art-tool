import pytest

import test_ui_icons
from arttool import image, profile
from arttool.errors import CheckFailed
from arttool.jsonio import read_json, write_json
from arttool.ui import bake_ui, check_ui, frame, icons


def prof(**over):
   return profile.load_profile("topdown_action", over)


def make_build(tmp_path, run_check=True):
   p = prof()
   out = tmp_path / "ui"
   frame.build(p, "panel", (16, 16), out)
   frame.build(p, "button", (32, 16), out)
   icons.cut(p, test_ui_icons.make_sheet(tmp_path), out)
   if run_check:
      write_json(out / "check.json", check_ui.run(out, p))
   return p, out


def test_bake_makes_files(tmp_path):
   p, out = make_build(tmp_path)
   result = bake_ui.bake(p, out, tmp_path / "unity", "Game.UI")

   made = set(result["files"])
   assert {"ui_atlas.png", "ui_manifest.json", "ui.uss", "UiSpecAsset.json"} <= made
   assert {"Editor/UiImportSettings.cs", "Editor/TmpFontBaker.cs"} <= made
   assert result["forced"] is False and result["check"] == "ok"


def test_atlas_holds_every_piece(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity")
   data = read_json(tmp_path / "unity" / "ui_manifest.json")
   atlas = image.load(tmp_path / "unity" / "ui_atlas.png")

   assert image.size(atlas) == tuple(data["atlas_size"])
   for entry in data["frames"]:
      x1, y1, x2, y2 = entry["rect"]
      assert image.bbox(image.crop(atlas, x1, y1, x2 - x1, y2 - y1)) is not None


def test_manifest_carries_slice_scale(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity")
   data = read_json(tmp_path / "unity" / "ui_manifest.json")
   assert data["slice_scale"] == 6.25
   assert data["ppu"] == 16


def test_uss_has_slice_scale_on_every_bg(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity")
   text = (tmp_path / "unity" / "ui.uss").read_text(encoding="utf-8")

   assert text.count("-unity-slice-scale: 6.25") == 6
   assert ".bg-panel_normal {" in text
   assert "-unity-slice-left: 3;" in text
   assert "min-width: 7px; min-height: 7px;" in text
   assert 'url("/Assets/UI/ui_atlas.png#panel_normal")' in text


def test_uss_base_rules(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity")
   text = (tmp_path / "unity" / "ui.uss").read_text(encoding="utf-8")
   assert ".ui-column { flex-direction: column; }" in text
   assert ".ui-spacer { flex-grow: 1; }" in text
   assert "Galmuri11 SDF.asset" in text
   assert "font-size: 11px" in text


def test_ui_spec_numbers_only(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity", "Game.UI")
   spec = read_json(tmp_path / "unity" / "UiSpecAsset.json")
   assert spec["ppu"] == 16
   assert spec["referenceWidth"] == 320 and spec["referenceHeight"] == 180
   assert spec["namespace"] == "Game.UI"
   assert spec["scaleMode"] == "integer"


def test_font_settings_written(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity")
   settings = read_json(tmp_path / "unity" / "font_bake.json")
   assert settings["nativePx"] == 11
   assert settings["charsetPath"].endswith("charset.txt")


def test_bake_refuses_without_report(tmp_path):
   p, out = make_build(tmp_path, run_check=False)
   with pytest.raises(CheckFailed, match="검수 보고"):
      bake_ui.bake(p, out, tmp_path / "unity")


def test_bake_refuses_failed_report(tmp_path):
   p, out = make_build(tmp_path, run_check=False)
   write_json(out / "check.json", {"version": 1, "status": "fail", "failed": ["ui_states"]})
   with pytest.raises(CheckFailed, match="통과하지"):
      bake_ui.bake(p, out, tmp_path / "unity")


def test_force_marks_manifest(tmp_path):
   p, out = make_build(tmp_path, run_check=False)
   write_json(out / "check.json", {"version": 1, "status": "fail", "failed": ["ui_states"]})
   bake_ui.bake(p, out, tmp_path / "unity", force=True)
   assert read_json(tmp_path / "unity" / "ui_manifest.json")["forced"] is True


def test_unity_scripts_are_copied_whole(tmp_path):
   p, out = make_build(tmp_path)
   bake_ui.bake(p, out, tmp_path / "unity")
   text = (tmp_path / "unity" / "Editor" / "UiImportSettings.cs").read_text(encoding="utf-8")
   assert "class UiImportSettings : AssetPostprocessor" in text
   assert "spritePixelsPerUnit" in text
   # namespace 줄만 바뀌고 나머지는 원본 그대로다
   want = (bake_ui.unity_dir() / "UiImportSettings.cs").read_text(encoding="utf-8").splitlines()
   got = text.splitlines()
   assert [l for l in got if not l.startswith("namespace ")] == [l for l in want if not l.startswith("namespace ")]


def test_dynamic_atlas_note(tmp_path):
   p, out = make_build(tmp_path)
   result = bake_ui.bake(p, out, tmp_path / "unity")
   assert "DynamicAtlasSettings" in result["notes"][0]


def test_run_checks_then_bakes(tmp_path):
   p, out = make_build(tmp_path, run_check=False)
   result = bake_ui.run(p, out, tmp_path / "unity", "Game.UI", False)
   assert result["check"] == "ok"
   assert (out / "check.json").is_file()
