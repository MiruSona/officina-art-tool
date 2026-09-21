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
      data = P.deep_merge(P.DEFAULTS, P.load_preset(name))
      P.validate(data)


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
