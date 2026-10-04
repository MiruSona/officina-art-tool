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


def test_check_loose_cli(tmp_path, capsys):
   """낱장 폴더를 그대로 받는다. 프레임 규격이 없어도 돈다."""
   from arttool import image

   loose = tmp_path / "loose"
   loose.mkdir()
   image.save(loose / "berry.png", helpers.blob(8, 8))

   code = cli.main(["--profile", "topdown_action", "check", "--in", str(loose), "--report", str(tmp_path / "c.json")])
   assert code == errors.EXIT_OK
   assert "낱장 모드" in capsys.readouterr().out
   assert read_json(tmp_path / "c.json")["checked"]["mode"] == "loose"


def test_module_entry_point():
   """setup.ps1 의 연기 시험이 쓰는 길이다. 끊기면 설치가 실패로 보인다."""
   import subprocess
   import sys

   # cli 가 늘 UTF-8 로 쓰므로 UTF-8 로 풀어 읽는다 (로캘 cp949 로 읽으면 한글 도움말에서 깨진다).
   done = subprocess.run([sys.executable, "-m", "arttool", "--help"], capture_output=True, text=True, encoding="utf-8")
   assert done.returncode == 0
   assert "arttool" in done.stdout


def _env_without_pythonioencoding():
   import os

   env = dict(os.environ)
   env.pop("PYTHONIOENCODING", None)
   env["PYTHONUTF8"] = "0"
   return env


def test_pipe_output_is_utf8(tmp_path):
   """파이프로 나가도 UTF-8 이다. 예전엔 cp949 로 나가 한글이 깨졌다 (설계 3-1)."""
   import subprocess
   import sys

   loose = tmp_path / "loose"
   loose.mkdir()
   from arttool import image

   image.save(loose / "berry.png", helpers.blob(8, 8))
   cmd = [sys.executable, "-m", "arttool", "--profile", "topdown_action", "check", "--in", str(loose), "--report", str(tmp_path / "c.json")]
   done = subprocess.run(cmd, capture_output=True, env=_env_without_pythonioencoding())
   assert done.returncode == 0
   assert "낱장 모드" in done.stdout.decode("utf-8")
   assert "낱장 모드" in done.stderr.decode("utf-8")


def test_pipe_output_survives_dash(tmp_path):
   """cp949 에 없는 `—` 가 출력에 들어가도 종료 0 이다. 예전엔 UnicodeEncodeError 로 종료 1 이었다."""
   import subprocess
   import sys

   code = "import sys; from arttool import cli; cli._utf8_streams(); print('가 — 나'); sys.exit(0)"
   done = subprocess.run([sys.executable, "-c", code], capture_output=True, env=_env_without_pythonioencoding())
   assert done.returncode == 0
   assert done.stdout.decode("utf-8").strip() == "가 — 나"


def test_pythonioencoding_is_respected():
   """PYTHONIOENCODING 을 준 사람은 그 값을 따른다 (비상구)."""
   import os
   import subprocess
   import sys

   env = dict(os.environ)
   env["PYTHONIOENCODING"] = "cp949"
   code = "import sys; from arttool import cli; cli._utf8_streams(); print(sys.stdout.encoding)"
   done = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
   assert done.stdout.decode("ascii").strip().lower() == "cp949"
