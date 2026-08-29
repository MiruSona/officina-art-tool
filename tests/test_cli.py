import helpers
import test_blob
from arttool import cli, errors
from arttool.jsonio import read_json


def test_profile_show(capsys):
   assert cli.main(["--profile", "topdown_action", "profile", "show", "--json"]) == errors.EXIT_OK
   data = read_json_text(capsys.readouterr().out)
   assert data["canvas"]["frame"] == [64, 64]


def read_json_text(text):
   import json

   return json.loads(text)


def test_provider_list_human(capsys):
   assert cli.main(["provider", "list"]) == errors.EXIT_OK
   out = capsys.readouterr().out
   assert "code" in out and "켜짐" in out


def test_missing_profile_exit_code(capsys):
   assert cli.main(["--profile", "없는것", "profile", "show"]) == errors.EXIT_PROFILE
   assert "오류" in capsys.readouterr().err


def test_normalize_and_check_and_bake(tmp_path, capsys, monkeypatch):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   profile_file = write_tiny_profile(tmp_path)

   build = tmp_path / "build"
   assert cli.main(["--profile", profile_file, "normalize", "--in", str(raw), "--out", str(build), "--anim", "walk"]) == 0
   assert cli.main(["--profile", profile_file, "check", "--in", str(build), "--report", str(build / "check.json")]) == 0
   assert cli.main(["--profile", profile_file, "bake", "--in", str(build), "--out", str(tmp_path / "unity")]) == 0
   assert (tmp_path / "unity" / "sprite_manifest.json").is_file()


def test_check_fail_exit_code(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   profile_file = write_tiny_profile(tmp_path, max_colors=1)
   build = tmp_path / "build"
   cli.main(["--profile", profile_file, "normalize", "--in", str(raw), "--out", str(build), "--anim", "walk"])
   code = cli.main(["--profile", profile_file, "check", "--in", str(build), "--report", str(build / "check.json")])
   assert code == errors.EXIT_CHECK_FAIL


def test_tile_blob_cli(tmp_path):
   profile_file = write_tiny_profile(tmp_path, tile_size=test_blob.TILE)
   templates = test_blob.write_templates(tmp_path / "t6")
   code = cli.main(["--profile", profile_file, "tile", "blob", "--in", str(templates), "--out", str(tmp_path / "t47")])
   assert code == 0
   assert read_json(tmp_path / "t47" / "tileset.json")["count"] == 47


def test_anchors_needs_markers(tmp_path, capsys):
   profile_file = write_tiny_profile(tmp_path)
   code = cli.main(
      ["--profile", profile_file, "anchors", "--in", str(tmp_path), "--rig", "blob", "--out", str(tmp_path / "a.json")]
   )
   assert code == errors.EXIT_ERROR
   assert "--markers" in capsys.readouterr().err


def test_tile_place_needs_exe(tmp_path):
   from arttool.jsonio import write_json

   profile_file = write_tiny_profile(tmp_path, tile_size=test_blob.TILE)
   templates = test_blob.write_templates(tmp_path / "t6")
   cli.main(["--profile", profile_file, "tile", "blob", "--in", str(templates), "--out", str(tmp_path / "t47")])
   write_json(tmp_path / "rules.json", {"weights": {}})

   code = cli.main(
      [
         "--profile",
         profile_file,
         "tile",
         "place",
         "--tileset",
         str(tmp_path / "t47" / "tileset.json"),
         "--rules",
         str(tmp_path / "rules.json"),
         "--size",
         "4x4",
         "--out",
         str(tmp_path / "map"),
         "--exe",
         str(tmp_path / "없다.exe"),
      ]
   )
   assert code == errors.EXIT_NO_EXE


def write_tiny_profile(tmp_path, max_colors=48, tile_size=16):
   """시험용 작은 프로필을 파일로 쓴다. CLI 는 이름이나 경로만 받는다."""
   path = tmp_path / "tiny.yaml"
   path.write_text(
      "name: tiny\n"
      "preset: topdown_action\n"
      "canvas:\n"
      "  frame: [16, 16]\n"
      "  baseline_y: 13\n"
      "  center_x: 7.5\n"
      "anim:\n"
      "  walk: { frames: 2, dirs: 4 }\n"
      "rigs:\n"
      "  blob:\n"
      "    method: anchor\n"
      "    anchors: [head_top]\n"
      "    marker_colors: { head_top: '#FF00FF' }\n"
      f"tiles:\n  size: {tile_size}\n"
      f"check:\n  max_colors: {max_colors}\n"
      "palette:\n  ramps_file: palettes/lpc_cloth.json\n",
      encoding="utf-8",
   )
   return str(path)
