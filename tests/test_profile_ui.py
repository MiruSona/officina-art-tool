import pytest

from arttool import palette, profile
from arttool.errors import ProfileError


def test_ui_defaults_are_there():
   prof = profile.load_profile()
   assert prof.ui["ppu"] == 16
   assert prof.ui["reference"] == [320, 180]
   assert prof.ui["generator"]["corner"] == "cut1"
   assert prof.ui["generator"]["states"] == ["normal", "pressed", "disabled"]


def test_slice_scale():
   prof = profile.load_profile("topdown_action")
   assert prof.slice_scale() == 6.25
   assert profile.load_profile("topdown_action", {"ui.ppu": 100}).slice_scale() == 1.0


def test_profiles_carry_ui():
   for name in ("topdown_action", "slime_demo"):
      prof = profile.load_profile(name)
      assert prof.ui_frame_size() == (16, 16)
      assert prof.ui["font"]["family"] == "Galmuri11"


def test_ui_panel_ramp_file():
   ramps = palette.load_ramps(profile.tool_home() / "palettes" / "ui_panel.json")
   assert ramps.ramp_len == 6
   assert "ui_panel" in ramps.names()
   first, last = ramps.ramp("ui_panel")[0], ramps.ramp("ui_panel")[5]
   assert sum(first) > sum(last)


def test_odd_frame_rejected():
   with pytest.raises(ProfileError, match="홀수"):
      profile.load_profile("topdown_action", {"ui.frame.source": [15, 16]})


def test_odd_frame_allowed_when_even_only_off():
   prof = profile.load_profile("topdown_action", {"ui.frame.source": [15, 16], "ui.frame.even_only": False})
   assert prof.ui_frame_size() == (15, 16)


def test_bad_corner():
   with pytest.raises(ProfileError, match="ui.generator.corner"):
      profile.load_profile("topdown_action", {"ui.generator.corner": "radius"})


def test_bad_state():
   with pytest.raises(ProfileError, match="모르는 상태"):
      profile.load_profile("topdown_action", {"ui.generator.states": ["normal", "wobble"]})


def test_bad_ppu():
   with pytest.raises(ProfileError, match="ui.ppu"):
      profile.load_profile("topdown_action", {"ui.ppu": 0})


def test_font_size_must_be_multiple():
   with pytest.raises(ProfileError, match="정수 배수"):
      profile.load_profile("topdown_action", {"ui.font.sizes_px": [13]})


def test_extension_needs_dot():
   with pytest.raises(ProfileError, match="점으로 시작"):
      profile.load_profile("topdown_action", {"ui.font.subset.extensions": ["txt"]})


def test_icon_size_must_be_positive():
   with pytest.raises(ProfileError, match="ui.icon.sizes"):
      profile.load_profile("topdown_action", {"ui.icon.sizes": []})


def test_bad_hotspot():
   with pytest.raises(ProfileError, match="hotspot"):
      profile.load_profile("topdown_action", {"ui.icon.hotspot": "가운데"})
   assert profile.load_profile("topdown_action", {"ui.icon.hotspot": [3, 4]}).ui["icon"]["hotspot"] == [3, 4]


def test_bad_scale_mode():
   with pytest.raises(ProfileError, match="scale_mode"):
      profile.load_profile("topdown_action", {"ui.scale_mode": "stretch"})


def test_negative_border_px():
   with pytest.raises(ProfileError, match="border_px"):
      profile.load_profile("topdown_action", {"ui.generator.border_px": -1})
