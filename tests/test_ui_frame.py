import numpy as np
import pytest

from arttool import image, profile
from arttool.errors import ArtToolError
from arttool.jsonio import read_json
from arttool.ui import frame


def prof():
   return profile.load_profile("topdown_action")


def colors(state="normal"):
   p = prof()
   return frame.slot_colors(p, frame.load_ui_ramps(p), state)


def rgb(arr, x, y):
   return tuple(int(v) for v in arr[y, x][:3])


def test_border_matches_design():
   p = prof()
   assert frame.border_of(p, "panel") == [3, 3, 3, 3]
   assert frame.min_size(p, "panel") == [7, 7]


def test_center_stretch_is_ten():
   p = prof()
   left, _bottom, right, _top = frame.border_of(p, "panel")
   assert 16 - left - right == 10


def test_bar_has_no_top_bottom_border():
   p = prof()
   assert frame.border_of(p, "bar") == [2, 0, 2, 0]


def test_panel_pixels():
   arr = frame.draw(prof(), "panel", (16, 16), "normal")
   c = colors()
   assert tuple(arr[0, 0]) == (0, 0, 0, 0)
   assert rgb(arr, 5, 0) == c["outline"]
   assert rgb(arr, 1, 1) == c["highlight"]
   assert rgb(arr, 5, 5) == c["fill"]
   assert rgb(arr, 14, 14) == c["shadow"]


def test_shadow_wins_where_they_meet():
   arr = frame.draw(prof(), "panel", (16, 16), "normal")
   c = colors()
   assert rgb(arr, 14, 1) == c["shadow"]
   assert rgb(arr, 1, 14) == c["shadow"]


def test_cut1_clears_four_corners():
   arr = frame.draw(prof(), "panel", (16, 16), "normal")
   for x, y in ((0, 0), (15, 0), (0, 15), (15, 15)):
      assert arr[y, x][3] == 0


def test_cut2_clears_three_per_corner():
   p = profile.load_profile("topdown_action", {"ui.generator.corner": "cut2"})
   arr = frame.draw(p, "panel", (16, 16), "normal")
   for x, y in ((0, 0), (1, 0), (0, 1)):
      assert arr[y, x][3] == 0
   assert arr[1, 1][3] == 255
   assert frame.border_of(p, "panel") == [4, 4, 4, 4]


def test_square_corner_keeps_everything():
   p = profile.load_profile("topdown_action", {"ui.generator.corner": "square"})
   arr = frame.draw(p, "panel", (16, 16), "normal")
   assert arr[0, 0][3] == 255
   assert frame.border_of(p, "panel") == [2, 2, 2, 2]


def test_drawing_is_deterministic():
   first = frame.draw(prof(), "panel", (16, 16), "normal")
   second = frame.draw(prof(), "panel", (16, 16), "normal")
   assert np.array_equal(first, second)


def test_pressed_swaps_highlight_and_shadow():
   normal = colors("normal")
   pressed = colors("pressed")
   assert pressed["highlight"] == normal["shadow"]
   assert pressed["shadow"] == normal["highlight"]

   arr = frame.draw(prof(), "panel", (16, 16), "pressed")
   assert rgb(arr, 1, 1) == normal["shadow"]


def test_disabled_uses_gray_ramp():
   gray = colors("disabled")
   for value in gray.values():
      assert value[0] == value[1] == value[2]


def test_states_share_border():
   p = prof()
   borders = {frame.border_of(p, "button")[0] for _ in p.ui["generator"]["states"]}
   assert borders == {3}


def test_pressed_content_padding_moves_down():
   p = prof()
   assert frame.content_padding(p, "panel", "normal") == [3, 3, 3, 3]
   assert frame.content_padding(p, "panel", "pressed") == [3, 2, 3, 4]


def test_bar_pixels():
   p = prof()
   arr = frame.draw(p, "bar", (16, 8), "normal")
   c = colors()
   assert rgb(arr, 0, 0) == c["outline"]
   assert rgb(arr, 1, 3) == c["highlight"]
   assert rgb(arr, 14, 3) == c["shadow"]
   assert rgb(arr, 5, 0) == c["fill"]
   assert arr[0, 0][3] == 255


def test_bar_top_row_is_not_outline():
   arr = frame.draw(prof(), "bar", (16, 8), "normal")
   c = colors()
   assert rgb(arr, 8, 0) != c["outline"]


def test_ramp_too_short():
   p = profile.load_profile("topdown_action", {"ui.generator.ramp_index": {"outline": 9, "highlight": 1, "fill": 3, "shadow": 4}})
   with pytest.raises(ArtToolError, match="단이 모자란다"):
      frame.draw(p, "panel", (16, 16), "normal")


def test_too_small_for_min_size():
   with pytest.raises(ArtToolError, match="최소 크기"):
      frame.draw(prof(), "panel", (4, 4), "normal")


def test_odd_size_rejected():
   with pytest.raises(ArtToolError, match="홀수"):
      frame.draw(prof(), "panel", (15, 16), "normal")


def test_unknown_kind():
   with pytest.raises(ArtToolError, match="모르는 프레임 종류"):
      frame.draw(prof(), "창문", (16, 16), "normal")


def test_build_writes_states_and_border_json(tmp_path):
   result = frame.build(prof(), "panel", (16, 16), tmp_path / "frames")
   assert len(result["frames"]) == 3
   for state in ("normal", "pressed", "disabled"):
      assert (tmp_path / "frames" / f"panel_{state}.png").is_file()

   data = read_json(tmp_path / "frames" / "border.json")
   assert [f["name"] for f in data["frames"]] == ["panel_disabled", "panel_normal", "panel_pressed"]
   assert data["frames"][0]["border"] == [3, 3, 3, 3]


def test_build_merges_two_kinds(tmp_path):
   out = tmp_path / "frames"
   frame.build(prof(), "panel", (16, 16), out)
   frame.build(prof(), "button", (32, 16), out)
   names = [f["name"] for f in read_json(out / "border.json")["frames"]]
   assert len(names) == 6
   assert "button_normal" in names and "panel_normal" in names


def test_no_soft_alpha_and_palette_clean(tmp_path):
   p = prof()
   ramps = frame.load_ui_ramps(p)
   for state in p.ui["generator"]["states"]:
      arr = frame.draw(p, "panel", (16, 16), state)
      assert not image.has_soft_alpha(arr)
      from arttool import palette as pal

      assert pal.outside_colors(arr, ramps) == []
