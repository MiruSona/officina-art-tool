"""UI 코드 리뷰 30건을 잡아 두는 시험."""

import numpy as np
import pytest

import test_ui_icons
import test_ui_ninepatch
from arttool import cli, errors, image, profile
from arttool.errors import ArtToolError, PathJailError
from arttool.jsonio import read_json, write_json
from arttool.ui import bake_ui, check_ui, font, frame, icons, manifest, ninepatch, screen, uss

BAD_ROOT = '/Assets/UI"); } * { color: red'


def prof(**over):
   return profile.load_profile("topdown_action", over)


def spec_file(tmp_path, spec):
   path = tmp_path / "spec.json"
   write_json(path, spec)
   return path


def _make_build(tmp_path, with_icons=False):
   p = prof()
   build = tmp_path / "build"
   frame.build(p, "panel", (16, 16), build)
   if with_icons:
      icons.cut(p, test_ui_icons.make_sheet(tmp_path), build)
   write_json(build / "check.json", check_ui.run(build))
   return p, build


# --- #3 cut2 귀퉁이 outline 이 살아 있나 (#23 : 알파가 아니라 색으로 잰다) ---


def test_cut2_diagonal_outline_survives():
   p = prof(**{"ui.generator.corner": "cut2"})
   arr = frame.draw(p, "panel", (16, 16), "normal")
   outline = frame.slot_colors(p, frame.load_ui_ramps(p), "normal")["outline"]

   spots = ((2, 0), (1, 1), (0, 2), (13, 0), (14, 1), (15, 2),
            (0, 13), (1, 14), (2, 15), (15, 13), (14, 14), (13, 15))
   for x, y in spots:
      assert tuple(int(v) for v in arr[y, x][:3]) == outline, (x, y)


def test_cut2_still_clears_three_per_corner():
   p = prof(**{"ui.generator.corner": "cut2"})
   arr = frame.draw(p, "panel", (16, 16), "normal")
   for x, y in ((0, 0), (1, 0), (0, 1), (15, 0), (14, 0), (15, 1)):
      assert arr[y, x][3] == 0, (x, y)


def test_cut1_corner_outline_is_untouched():
   p = prof()
   arr = frame.draw(p, "panel", (16, 16), "normal")
   outline = frame.slot_colors(p, frame.load_ui_ramps(p), "normal")["outline"]
   for x, y in ((1, 0), (0, 1), (14, 0), (15, 1)):
      assert tuple(int(v) for v in arr[y, x][:3]) == outline, (x, y)


# --- #4 out 폴더가 없어도 일곱 명령이 다 돈다 ---


def test_all_seven_commands_make_their_own_folders(tmp_path):
   build = tmp_path / "없던곳" / "build"
   out = tmp_path / "없던곳2" / "unity"
   raw = tmp_path / "raw"
   raw.mkdir()
   for state in ("normal", "pressed", "disabled"):
      image.save(raw / f"window_{state}.9.png", test_ui_ninepatch.make_nine())
   sheet = test_ui_icons.make_sheet(tmp_path)

   base = ["--profile", "topdown_action", "ui"]
   assert cli.main(base + ["frame", "--kind", "panel", "--out", str(build)]) == 0
   assert cli.main(base + ["import", "--in", str(raw), "--out", str(build)]) == 0
   assert cli.main(base + ["icons", "--in", str(sheet), "--out", str(build)]) == 0
   assert cli.main(base + ["check", "--in", str(build), "--report", str(build / "check.json")]) == 0
   assert cli.main(base + ["bake", "--in", str(build), "--out", str(out)]) == 0

   spec = spec_file(tmp_path, {"screen": "s", "root": {"id": "root", "type": "column"}})
   assert cli.main(base + ["screen", "--spec", str(spec), "--out", str(tmp_path / "또없던곳")]) == 0

   text = tmp_path / "Text"
   text.mkdir()
   (text / "a.txt").write_text("가나", encoding="utf-8")
   code = cli.main(base + ["font", "--scan-root", str(tmp_path), "--scan", "Text",
                           "--out", str(tmp_path / "또또없던곳" / "charset.txt")])
   assert code == 0


# --- #5 id · #8 자료형 · #9 최상위 모르는 키 · #10 grow · #27 음수 ---


@pytest.mark.parametrize("bad_id", ["root { color: red } * ", "a b", "#x", "1abc", "", "a{b}"])
def test_bad_id_is_refused(bad_id):
   with pytest.raises(ArtToolError):
      screen.validate({"id": bad_id, "type": "column"})


@pytest.mark.parametrize("good_id", ["root", "btn_resume", "a-b", "_x9"])
def test_good_id_passes(good_id):
   assert screen.validate({"id": good_id, "type": "column"})["id"] == good_id


def test_id_must_be_a_string():
   with pytest.raises(ArtToolError, match="문자열"):
      screen.validate({"id": 7, "type": "label", "text": "x"})


def test_text_must_be_a_string():
   with pytest.raises(ArtToolError, match="문자열"):
      screen.validate({"id": "a", "type": "label", "text": 7})


def test_pad_must_be_a_number():
   with pytest.raises(ArtToolError, match="pad"):
      screen.validate({"id": "a", "type": "column", "pad": "8; color: red"})


def test_size_must_be_numbers():
   with pytest.raises(ArtToolError, match="size"):
      screen.validate({"id": "a", "type": "column", "size": ["a", "b"]})


def test_gap_must_be_a_number():
   with pytest.raises(ArtToolError, match="gap"):
      screen.validate({"id": "a", "type": "row", "gap": "2"})


@pytest.mark.parametrize("node", [
   {"id": "a", "type": "row", "gap": -5},
   {"id": "a", "type": "row", "pad": -1},
   {"id": "a", "type": "row", "size": [-2, 3]},
])
def test_negative_values_are_refused(node):
   with pytest.raises(ArtToolError, match="0 이상"):
      screen.validate(node)


def test_grow_must_be_bool():
   with pytest.raises(ArtToolError, match="참·거짓"):
      screen.validate({"id": "a", "type": "row", "grow": "no"})
   assert screen.validate({"id": "a", "type": "row", "grow": True})


def test_unknown_top_level_key(tmp_path):
   path = spec_file(tmp_path, {"screen": "d", "junk": 1, "root": {"id": "r", "type": "spacer"}})
   with pytest.raises(ArtToolError, match="모르는 칸"):
      screen.load(path)


def test_bg_name_is_checked_too():
   with pytest.raises(ArtToolError):
      screen.validate({"id": "a", "type": "panel", "bg": "x } * { color: red"})


def test_screen_name_cannot_be_a_path(tmp_path):
   path = spec_file(tmp_path, {"screen": "sub/evil", "root": {"id": "r", "type": "spacer"}})
   with pytest.raises(ArtToolError):
      screen.load(path)


# --- #7 assets_root ---


@pytest.mark.parametrize("bad", [BAD_ROOT, "/Assets/UI'", "/Assets UI", "/Assets/UI;"])
def test_bad_assets_root_is_refused(bad):
   with pytest.raises(ArtToolError, match="assets_root"):
      uss.check_assets_root(bad)


def test_good_assets_root_passes():
   assert uss.check_assets_root("/Assets/UI") == "/Assets/UI"
   assert uss.check_assets_root("Assets/My-UI_2.0") == "Assets/My-UI_2.0"


def test_bake_refuses_bad_assets_root(tmp_path):
   p, build = _make_build(tmp_path)
   with pytest.raises(ArtToolError, match="assets_root"):
      bake_ui.bake(p, build, tmp_path / "unity", assets_root=BAD_ROOT)


# --- #6 --namespace 가 .cs 에 닿는다 ---


def test_namespace_reaches_the_cs_files(tmp_path):
   p, build = _make_build(tmp_path)
   bake_ui.bake(p, build, tmp_path / "unity", namespace="MyGame.Ui")
   for name in bake_ui.UNITY_FILES:
      text = (tmp_path / "unity" / "Editor" / name).read_text(encoding="utf-8")
      lines = [line for line in text.splitlines() if line.startswith("namespace ")]
      assert lines == ["namespace MyGame.Ui"], (name, lines)
   assert read_json(tmp_path / "unity" / "UiSpecAsset.json")["namespace"] == "MyGame.Ui"


@pytest.mark.parametrize("bad", ["My Game", "1Game", "Game.", "Game;class X{}", ""])
def test_bad_namespace_is_refused(tmp_path, bad):
   p, build = _make_build(tmp_path)
   with pytest.raises(ArtToolError, match="namespace"):
      bake_ui.bake(p, build, tmp_path / "unity", namespace=bad)


# --- #2 C# 는 Editor 폴더로, #if UNITY_EDITOR 로 감쌌다 ---


def test_cs_goes_into_editor_folder(tmp_path):
   p, build = _make_build(tmp_path)
   result = bake_ui.bake(p, build, tmp_path / "unity")
   assert "Editor/UiImportSettings.cs" in result["files"]
   assert (tmp_path / "unity" / "Editor" / "UiImportSettings.cs").is_file()
   assert not (tmp_path / "unity" / "UiImportSettings.cs").exists()


def test_cs_files_are_editor_only():
   for name in bake_ui.UNITY_FILES:
      text = (bake_ui.unity_dir() / name).read_text(encoding="utf-8")
      assert text.lstrip().startswith("#if UNITY_EDITOR"), name
      assert text.rstrip().endswith("#endif"), name


# --- #11 #12 사람이 고친 .cs 를 안 덮는다 · 원자 쓰기 ---


def test_edited_cs_is_kept_and_new_is_written_beside(tmp_path):
   p, build = _make_build(tmp_path)
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)
   mine = out / "Editor" / "UiImportSettings.cs"
   mine.write_text("// 내가 고친 것\n", encoding="utf-8")

   result = bake_ui.bake(p, build, out)
   assert mine.read_text(encoding="utf-8").startswith("// 내가 고친 것")
   assert (out / "Editor" / "UiImportSettings.cs.new").is_file()
   assert any("UiImportSettings.cs" in w for w in result["warnings"])


def test_same_cs_is_not_flagged(tmp_path):
   p, build = _make_build(tmp_path)
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)
   result = bake_ui.bake(p, build, out)
   assert result["warnings"] == []
   assert not (out / "Editor" / "UiImportSettings.cs.new").exists()


def test_text_outputs_are_atomic(tmp_path, monkeypatch):
   import os

   seen = []
   real = os.replace

   def spy(src, dst):
      seen.append(str(src))
      real(src, dst)

   p, build = _make_build(tmp_path)
   monkeypatch.setattr(os, "replace", spy)
   bake_ui.bake(p, build, tmp_path / "unity")
   spec = spec_file(tmp_path, {"screen": "s", "root": {"id": "root", "type": "column"}})
   screen.build(p, spec, tmp_path / "unity")

   tmps = [name for name in seen if name.endswith(".tmp")]
   assert tmps
   assert all(str(os.getpid()) in name for name in tmps)
   for tail in ("ui.uss", "s.uxml", "s.uss", "UiImportSettings.cs"):
      assert any(tail in name for name in seen), tail


# --- #14 UI 아틀라스 한도는 따로 · #15 PPU 대조 ---


def test_atlas_max_is_its_own_key(tmp_path):
   _p, build = _make_build(tmp_path)
   assert prof().ui["check"]["atlas_max"] == 2048

   tight = prof(**{"ui.check.atlas_max": 8})
   assert any(w["rule"] == "ui_atlas_size" for w in check_ui.run(build, tight)["warnings"])

   loose_font = prof(**{"ui.font.subset.atlas_max": 8})
   assert check_ui.run(build, loose_font)["warnings"] == []


def test_ppu_rule_exists_and_passes(tmp_path):
   p, build = _make_build(tmp_path)
   bake_ui.bake(p, build, tmp_path / "unity")
   report = check_ui.run(build, p, tmp_path / "unity" / "ui_manifest.json")
   assert [r["rule"] for r in report["rules"]].count("ui_ppu") == 1
   assert len(report["rules"]) == 6
   assert report["status"] == "ok"


def test_ppu_mismatch_fails(tmp_path):
   p, build = _make_build(tmp_path)
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)
   data = read_json(out / "ui_manifest.json")
   data["ppu"] = 32
   write_json(out / "ui_manifest.json", data)
   assert "ui_ppu" in check_ui.run(build, p, out / "ui_manifest.json")["failed"]


def test_ppu_missing_fails(tmp_path):
   p, build = _make_build(tmp_path)
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)
   data = read_json(out / "ui_manifest.json")
   del data["ppu"]
   write_json(out / "ui_manifest.json", data)
   assert "ui_ppu" in check_ui.run(build, p, out / "ui_manifest.json")["failed"]


# --- #16 감옥 · #17 scan_dirs ---


def test_ui_check_report_is_jailed(tmp_path):
   _p, build = _make_build(tmp_path)
   climb = tmp_path / "안" / ".." / ".." / "탈출.json"
   code = cli.main(["--profile", "topdown_action", "ui", "check", "--in", str(build), "--report", str(climb)])
   assert code == errors.EXIT_PATH


def test_ui_font_out_is_jailed(tmp_path):
   text = tmp_path / "Text"
   text.mkdir()
   (text / "a.txt").write_text("가", encoding="utf-8")
   climb = tmp_path / "안" / ".." / ".." / "탈출.txt"
   code = cli.main(["--profile", "topdown_action", "ui", "font", "--scan-root", str(tmp_path),
                    "--scan", "Text", "--out", str(climb)])
   assert code == errors.EXIT_PATH


def test_absolute_scan_dir_is_refused(tmp_path):
   text = tmp_path / "Text"
   text.mkdir()
   (text / "a.txt").write_text("가", encoding="utf-8")
   with pytest.raises(PathJailError):
      font.build(prof(), [str(text.resolve())], tmp_path / "charset.txt", root=tmp_path)


def test_scan_dir_cannot_climb_out(tmp_path):
   with pytest.raises(PathJailError):
      font.build(prof(), ["../../밖"], tmp_path / "charset.txt", root=tmp_path)


# --- #18 밑줄 두 개 이름 ---


def test_split_name_uses_the_state_list():
   states = ["normal", "pressed", "disabled"]
   assert ninepatch.split_name("dialog_box", states) == ("dialog_box", "normal")
   assert ninepatch.split_name("btn_big_pressed", states) == ("btn_big", "pressed")
   assert ninepatch.split_name("panel", states) == ("panel", "normal")
   assert ninepatch.split_name("window_normal", states) == ("window", "normal")


def test_two_underscore_import_keeps_the_group(tmp_path):
   raw = tmp_path / "raw"
   raw.mkdir()
   for state in ("normal", "pressed", "disabled"):
      image.save(raw / f"dialog_box_{state}.9.png", test_ui_ninepatch.make_nine())
   out = tmp_path / "build"
   result = ninepatch.import_dir(prof(), raw, out)
   assert {f["group"] for f in result["frames"]} == {"dialog_box"}
   assert check_ui.run(out)["status"] == "ok"


# --- #19 이름 겹침 · #24 아틀라스 조각이 원본과 같은가 ---


def test_duplicate_name_between_frame_and_icon():
   frames = [{"name": "dup", "group": "g", "state": "normal", "size": [16, 16], "border": [3, 3, 3, 3],
              "min_size": [7, 7], "content_padding": [3, 3, 3, 3], "file": "a.png"}]
   icon_rows = [{"name": "dup", "size": 16, "family": "f", "file": "b.png", "hotspot": [8, 8]}]
   with pytest.raises(ArtToolError, match="이름이 겹친다"):
      manifest.build(prof(), frames, icon_rows)


def test_atlas_pieces_match_their_sources(tmp_path):
   p, build = _make_build(tmp_path, with_icons=True)
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)
   data = read_json(out / "ui_manifest.json")
   atlas = image.load(out / "ui_atlas.png")

   sources = {e["name"]: e["file"] for e in read_json(build / "border.json")["frames"]}
   sources.update({e["name"]: e["file"] for e in read_json(build / "icons.json")["icons"]})

   boxes = []
   for entry in data["frames"] + data["icons"]:
      x1, y1, x2, y2 = entry["rect"]
      cut = image.crop(atlas, x1, y1, x2 - x1, y2 - y1)
      assert np.array_equal(cut, image.load(build / sources[entry["name"]])), entry["name"]
      boxes.append((entry["name"], entry["rect"]))

   for i in range(len(boxes)):
      for j in range(i + 1, len(boxes)):
         a, b = boxes[i][1], boxes[j][1]
         assert not (a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]), (boxes[i], boxes[j])


# --- #28 --manifest ---


def test_manifest_given_but_missing(tmp_path):
   spec = spec_file(tmp_path, {"screen": "s", "root": {"id": "root", "type": "column"}})
   with pytest.raises(ArtToolError, match="매니페스트"):
      screen.build(prof(), spec, tmp_path / "out", manifest_path=tmp_path / "없다.json")


def test_bg_checked_flag(tmp_path):
   spec = spec_file(tmp_path, {"screen": "s", "root": {"id": "root", "type": "column"}})
   assert screen.build(prof(), spec, tmp_path / "out")["bg_checked"] is False

   p, build = _make_build(tmp_path)
   out = tmp_path / "unity"
   bake_ui.bake(p, build, out)
   spec2 = spec_file(tmp_path, {"screen": "t", "root": {"id": "root", "type": "column", "bg": "panel_normal"}})
   assert screen.build(p, spec2, out)["bg_checked"] is True


# --- #29 안 쓰는 인자 ---


def test_load_pieces_takes_only_the_folder():
   import inspect

   assert list(inspect.signature(check_ui.load_pieces).parameters) == ["build_dir"]


# --- #26 설계 예시가 구현과 맞는가 ---


def test_design_example_matches_implementation():
   text = (profile.tool_home() / "Docs" / "Design" / "2026-08-25-UI툴설계.md").read_text(encoding="utf-8")
   assert '"content_padding": [3, 2, 3, 4]' in text
   assert '"content_padding": [4, 5, 4, 3]' not in text
# --- R7 적힌 크기와 실제 PNG 크기가 다르면 굽지 않는다 ---


def test_bake_rejects_size_that_does_not_match_the_png(tmp_path):
   p, build = _make_build(tmp_path)
   entry = read_json(build / "border.json")["frames"][0]
   image.save(build / entry["file"], image.new(12, 12))

   with pytest.raises(ArtToolError, match="크기"):
      bake_ui.bake(p, build, tmp_path / "unity")


def test_bake_still_goes_when_sizes_match(tmp_path):
   p, build = _make_build(tmp_path)
   assert bake_ui.bake(p, build, tmp_path / "unity")["out"]
