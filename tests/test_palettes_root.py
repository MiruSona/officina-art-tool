"""3판 : ramps_file 의 $palettes/ 접두와 ARTTOOL_PALETTES 뿌리, 템플릿 램프를 못 믿을 때 물러나기."""
import json
import os

import pytest

from arttool.draw import Canvas
from arttool.errors import ArtToolError, UsageError
from arttool.profile import load_profile


def _ramps_json(path, name):
   data = {"version": 1, "name": name, "ramp_len": 2, "ramps": {"skin": ["#402020", "#C08060"]}}
   path.parent.mkdir(parents=True, exist_ok=True)
   path.write_text(json.dumps(data), encoding="utf-8")
   return path


def _profile(folder, ramps_file):
   folder.mkdir(parents=True, exist_ok=True)
   path = folder / "game.yaml"
   path.write_text(f"preset: topdown_action\npalette:\n  ramps_file: \"{ramps_file}\"\n", encoding="utf-8")
   return path


def test_palettes_prefix_reads_env_root(tmp_path, monkeypatch):
   pal = _ramps_json(tmp_path / "pal" / "x.json", "x")
   monkeypatch.setenv("ARTTOOL_PALETTES", str(tmp_path / "pal"))
   prof = load_profile(str(_profile(tmp_path / "prof", "$palettes/x.json")))
   assert prof.ramps_path() == pal.resolve()
   assert (tmp_path / "pal").resolve() in prof.palette_roots()


def test_palettes_prefix_without_env_is_usage_error(tmp_path, monkeypatch):
   monkeypatch.delenv("ARTTOOL_PALETTES", raising=False)
   prof = load_profile(str(_profile(tmp_path / "prof", "$palettes/x.json")))
   with pytest.raises(UsageError, match="꺼져 있다"):
      prof.ramps_path()


@pytest.mark.parametrize("bad", ["relative/pal", "MISSING", "DRIVE"])
def test_bad_env_value_is_dropped_when_gathering(tmp_path, monkeypatch, bad):
   """틀린 ARTTOOL_PALETTES 는 뿌리를 모을 때 그 뿌리만 빼고 경고 — $palettes/ 를 안 쓰는 일은 안 죽는다."""
   value = {"MISSING": str(tmp_path / "없는폴더"), "DRIVE": tmp_path.anchor}.get(bad, bad)
   monkeypatch.setenv("ARTTOOL_PALETTES", value)
   prof = load_profile(str(_profile(tmp_path / "prof", "palettes/x.json")))
   notes = []
   roots = prof.palette_roots(notes)
   assert len(roots) == 2 and prof.palette_roots() == roots
   assert [n["rule"] for n in notes] == ["palettes.root_ignored"]


def test_drive_root_env_is_usage_error_for_prefix(tmp_path, monkeypatch):
   monkeypatch.setenv("ARTTOOL_PALETTES", tmp_path.anchor)
   prof = load_profile(str(_profile(tmp_path / "prof", "$palettes/x.json")))
   with pytest.raises(UsageError, match="드라이브 뿌리"):
      prof.ramps_path()


@pytest.mark.parametrize("bad", ["relative/pal", "MISSING"])
def test_bad_env_value_is_usage_error(tmp_path, monkeypatch, bad):
   value = bad if bad != "MISSING" else str(tmp_path / "없는폴더")
   monkeypatch.setenv("ARTTOOL_PALETTES", value)
   prof = load_profile(str(_profile(tmp_path / "prof", "$palettes/x.json")))
   with pytest.raises(UsageError, match="ARTTOOL_PALETTES"):
      prof.ramps_path()


def test_env_symlink_is_usage_error(tmp_path, monkeypatch):
   real = tmp_path / "real"
   real.mkdir()
   link = tmp_path / "link"
   try:
      os.symlink(real, link, target_is_directory=True)
   except (OSError, NotImplementedError):
      pytest.skip("이 PC 에서는 링크를 만들 권한이 없다")
   monkeypatch.setenv("ARTTOOL_PALETTES", str(link))
   prof = load_profile(str(_profile(tmp_path / "prof", "$palettes/x.json")))
   with pytest.raises(UsageError, match="링크"):
      prof.ramps_path()


def test_palettes_prefix_cannot_climb_out(tmp_path, monkeypatch):
   _ramps_json(tmp_path / "x.json", "밖")
   (tmp_path / "pal").mkdir()
   monkeypatch.setenv("ARTTOOL_PALETTES", str(tmp_path / "pal"))
   prof = load_profile(str(_profile(tmp_path / "prof", "$palettes/../x.json")))
   with pytest.raises(ArtToolError):
      prof.ramps_path()


def test_old_profile_ignores_env(tmp_path, monkeypatch):
   # 접두 없는 옛 프로필은 환경변수를 켜도 프로필 옆 파일을 그대로 집는다.
   near = _ramps_json(tmp_path / "prof" / "x.json", "옆")
   _ramps_json(tmp_path / "pal" / "x.json", "뿌리")
   monkeypatch.setenv("ARTTOOL_PALETTES", str(tmp_path / "pal"))
   prof = load_profile(str(_profile(tmp_path / "prof", "x.json")))
   assert prof.ramps_path() == near.resolve()


def test_canvas_untrusted_template_ramps_warns_and_falls_back(tmp_path, monkeypatch):
   monkeypatch.delenv("ARTTOOL_PALETTES", raising=False)
   outside = _ramps_json(tmp_path / "elsewhere" / "pal.json", "밖")
   _ramps_json(tmp_path / "prof" / "own.json", "own")
   prof_path = _profile(tmp_path / "prof", "own.json")
   guide_dir = tmp_path / "guide"
   guide_dir.mkdir()
   tpl = {"name": "char_small", "size": [16, 16], "layers": [{"name": "body", "kind": "body"}],
          "check": {"palette": {"ramps_file": str(outside)}}}
   (guide_dir / "template.json").write_text(json.dumps(tpl), encoding="utf-8")
   c = Canvas(template=guide_dir, profile=str(prof_path))
   assert [w["rule"] for w in c.warnings] == ["template.ramps_outside"]
   assert c.ramps is not None and c.ramps.name == "own"


def test_read_json_non_utf8_is_arttool_error(tmp_path):
   """UTF-8 이 아닌 JSON 은 깨진 JSON 과 같은 ArtToolError 로."""
   from arttool.jsonio import read_json
   bad = tmp_path / "x.json"
   bad.write_bytes(b'{"a": "\xff\xfe"}')
   with pytest.raises(ArtToolError, match="못 읽었다"):
      read_json(bad)
