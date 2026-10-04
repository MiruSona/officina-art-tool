import pytest

from arttool import profile as P
from arttool.errors import ProfileError


def test_presets_exist():
   for name in P.PRESET_NAMES:
      assert (P.profiles_dir() / "presets" / f"{name}.yaml").is_file()


def test_example_profile_loads():
   prof = P.load_profile("topdown_action")
   assert prof.name == "topdown_action"
   assert prof.frame == (64, 64)
   assert prof.directions == 4
   assert prof.anim["walk"]["frames"] == 9
   assert prof.rig("blob")["method"] == "anchor"


def test_default_beats_nothing_preset_beats_default():
   prof = P.load_profile()
   assert prof.axes["projection"] == "quarter"
   iso = P.load_profile(None, {"preset": "iso"})
   # preset 은 파일에서만 고른다. 인자로 준 preset 은 축을 안 바꾼다
   assert iso.axes["projection"] == "quarter"


def test_cli_override_wins():
   prof = P.load_profile("topdown_action", {"axes.directions": 8})
   assert prof.directions == 8
   assert prof.direction_names()[1] == "southwest"


def test_ramps_path_found():
   prof = P.load_profile("topdown_action")
   assert prof.ramps_path().is_file()


def test_mirror_east_from_tiles():
   prof = P.load_profile("topdown_action")
   assert prof.mirror_east() is True


def test_unknown_top_key_fails(tmp_path):
   path = tmp_path / "bad.yaml"
   path.write_text("name: bad\n엉뚱한칸: 1\n", encoding="utf-8")
   with pytest.raises(ProfileError):
      P.load_profile(str(path))


def test_bad_projection():
   with pytest.raises(ProfileError):
      P.load_profile("topdown_action", {"axes.projection": "없는투영"})


def test_bad_directions():
   with pytest.raises(ProfileError):
      P.load_profile("topdown_action", {"axes.directions": 3})


def test_bad_frames():
   with pytest.raises(ProfileError):
      P.load_profile("topdown_action", {"anim.walk.frames": 0})


def test_baseline_outside_frame():
   with pytest.raises(ProfileError):
      P.load_profile("topdown_action", {"canvas.baseline_y": 999})


def test_missing_profile():
   with pytest.raises(ProfileError):
      P.load_profile("없는프로필")


def test_unknown_preset(tmp_path):
   path = tmp_path / "p.yaml"
   path.write_text("name: p\npreset: 없는프리셋\n", encoding="utf-8")
   with pytest.raises(ProfileError):
      P.load_profile(str(path))


def test_anchor_rig_without_anchors():
   with pytest.raises(ProfileError):
      P.load_profile("topdown_action", {"rigs.blob.anchors": []})


def test_all_presets_valid():
   for name in P.PRESET_NAMES:
      preset = P.load_preset(name)
      assert isinstance(preset, dict) and preset, name        # 프리셋 파일이 비지 않았다
      data = P.deep_merge(P.DEFAULTS, preset)
      P.validate(data)                                          # 꼴이 맞지 않으면 ProfileError
      prof = P.Profile(data)
      assert prof.directions in P.DIRECTION_COUNTS and prof.frame[0] > 0, name


def test_solid_outline_word_accepted(tmp_path):
   """style.outline 에 「한 색 선」 solid 를 쓸 수 있다 (실물 시험 #3)."""
   assert P.load_profile(_write(tmp_path, "style: { outline: solid }\n")).style["outline"] == "solid"


def test_tool_home_needs_only_profiles(tmp_path, monkeypatch):
   """소스 폴더 판정은 profiles/ 하나로 한다 (리뷰 R1-L4)."""
   monkeypatch.delenv("ARTTOOL_HOME", raising=False)
   fake_src = tmp_path / "src" / "arttool"
   fake_src.mkdir(parents=True)
   (tmp_path / "profiles").mkdir()
   monkeypatch.setattr(P, "__file__", str(fake_src / "profile.py"))
   assert P.tool_home() == tmp_path.resolve()
   bare_src = tmp_path / "bare" / "src" / "arttool"             # profiles/ 가 없는 자리
   bare_src.mkdir(parents=True)
   monkeypatch.setattr(P, "__file__", str(bare_src / "profile.py"))
   assert P.tool_home() == (bare_src / P.HOME_COPY).resolve()


README_EXAMPLE = """name: mozzi
preset: topdown_action
canvas: { frame: [64, 64], baseline_y: 50, center_x: 31.5 }
palette: { ramps_file: "" }
ui:
  icon:  { sizes: [28] }
  check: { palette_strict: false }
"""


def test_readme_minimal_profile_loads(tmp_path):
   """README 「어느 길로 쓰나」 의 최소 프로필 예시. 글만 고치고 안 돌려 보면 낡는다."""
   path = tmp_path / "mozzi.yaml"
   path.write_text(README_EXAMPLE, encoding="utf-8")

   prof = P.load_profile(str(path))
   assert prof.frame == (64, 64)
   assert prof.ui["icon"]["sizes"] == [28]
   assert prof.ui["check"]["palette_strict"] is False
   assert prof.ramps_path() is None


# --- 2026-10-04 개선 설계 7-1 : style · check.warn · check.background ---

def _write(tmp_path, text):
   path = tmp_path / "p.yaml"
   path.write_text("preset: topdown_action\n" + text, encoding="utf-8")
   return str(path)


def test_new_defaults_on_old_profile():
   """새 칸이 없는 옛 프로필도 그대로 읽히고 기본값을 받는다."""
   prof = P.load_profile("topdown_action")
   assert prof.style == {"outline": "unset", "light": "top_left", "scale": 1, "materials": {}}
   assert prof.warn("isolated") == {"enabled": True, "max_ratio": 0.15}
   assert prof.warn("near_colors") == {"enabled": True, "max_delta": 4, "min_pairs": 20}
   assert prof.color_cap_table() == {8: 4, 16: 8, 32: 16, 48: 44, 64: 48, 128: 48, 256: 64}
   assert prof.check["background"] == {"auto": True, "min_side": 128, "color_cap": 64, "max_colors": None}
   assert prof.check["max_colors"] == 48


def test_design_yaml_block_loads(tmp_path):
   """설계 7-1 의 YAML 을 그대로 붙여도 읽힌다."""
   text = (
      "style:\n"
      "  outline: selout+light\n"
      "  light: top\n"
      "  scale: 2\n"
      "  materials: { blade: metal, slime: goo }\n"
      "check:\n"
      "  max_colors: 48\n"
      "  warn:\n"
      "    integer_scale: { enabled: true, block_ratio: 0.95, smooth_ratio: 0.15 }\n"
      "    outline:       { enabled: false, black_ratio: 0.8 }\n"
      "    color_cap:     { enabled: true, table: { 16: 8, 32: 14, 64: 30 } }\n"
      "    loop_seam:     { enabled: true, k: 2.5, anims: [idle, walk] }\n"
      "  background:\n"
      "    auto: false\n"
      "    max_colors: 96\n"
   )
   prof = P.load_profile(_write(tmp_path, text))
   assert prof.style["outline"] == "selout+light" and prof.style["materials"]["blade"] == "metal"
   assert prof.warn("outline")["enabled"] is False
   assert prof.warn("loop_seam")["k"] == 2.5
   # 표는 기본 표와 겹친다. 준 칸만 바뀐다
   assert prof.color_cap_table() == {8: 4, 16: 8, 32: 14, 48: 44, 64: 30, 128: 48, 256: 64}
   assert prof.check["background"]["max_colors"] == 96


def test_color_cap_table_string_keys_from_json():
   """템플릿(JSON)을 겹치면 열쇠가 글자다. 뒤에 겹친 쪽이 이긴다."""
   data = P.deep_merge(P.DEFAULTS, P.load_preset("topdown_action"))
   data = P.deep_merge(data, {"check": {"warn": {"color_cap": {"table": {"16": 5}}}}})
   P.validate(data)
   assert P.Profile(data).color_cap_table()[16] == 5


@pytest.mark.parametrize(
   "text, word",
   [
      ("style: { outline: thick }\n", "style.outline"),
      ("style: { light: bottom }\n", "style.light"),
      ("style: { scale: 0 }\n", "style.scale"),
      ("style: { materials: { a: plastic } }\n", "style.materials"),
      ("style: { shadow: true }\n", "모르는 항목"),
      ("check: { warn: { isolated: { max_ratio: 1.5 } } }\n", "max_ratio"),
      ("check: { warn: { isolated: { enabled: yes_please } } }\n", "enabled"),
      ("check: { warn: { isolated: { on: true } } }\n", "참거짓"),
      ("check: { warn: { jaggies: { enabled: true } } }\n", "모르는 항목"),
      ("check: { warn: { color_cap: { table: { 16: 0 } } } }\n", "color_cap.table"),
      ("check: { warn: { color_cap: { table: { big: 8 } } } }\n", "color_cap.table"),
      ("check: { warn: { near_colors: { max_delta: 300 } } }\n", "max_delta"),
      ("check: { warn: { near_colors: { min_pairs: 0 } } }\n", "min_pairs"),
      ("check: { warn: { ramp_shape: { steps: [6, 4] } } }\n", "steps"),
      ("check: { warn: { ramp_shape: { hue_min: 40, hue_max: 30 } } }\n", "hue_min"),
      ("check: { warn: { loop_seam: { k: 0 } } }\n", "loop_seam.k"),
      ("check: { warn: { loop_seam: { anims: walk } } }\n", "anims"),
      ("check: { background: { min_side: -1 } }\n", "min_side"),
      ("check: { background: { max_colors: 0 } }\n", "max_colors"),
      ("check: { background: { blur: 1 } }\n", "모르는 항목"),
   ],
)
def test_new_fields_rejected(tmp_path, text, word):
   with pytest.raises(ProfileError, match=word):
      P.load_profile(_write(tmp_path, text))


def test_warn_unknown_rule_name():
   with pytest.raises(ProfileError, match="모르는 경고 검사"):
      P.load_profile("topdown_action").warn("jaggies")


def test_load_profile_args():
   """새 명령 모듈이 부르는 길. --directions 를 덮어쓰고, 칸이 없는 args 도 받는다."""
   import argparse

   prof = P.load_profile_args(argparse.Namespace(profile="topdown_action", directions=8))
   assert prof.directions == 8
   assert P.load_profile_args(argparse.Namespace()).name == "default"
