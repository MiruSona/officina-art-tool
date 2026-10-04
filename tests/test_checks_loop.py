"""⑦ loop_seam 재기 · 판정."""

from arttool import image
from arttool.checks import loop


def frame(x):
   arr = image.new(16, 16)
   arr[4:12, x : x + 4] = (90, 120, 160, 255)
   return arr


def test_last_equals_first_is_a_pause():
   m = loop.measure_loop([frame(2), frame(3), frame(4), frame(2)])
   assert m["loop"] == 0
   assert "한 박자" in loop.judge_loop(m, 2.0)[0]


def test_jump_back_warns():
   m = loop.measure_loop([frame(2), frame(3), frame(4), frame(5), frame(6)])
   assert m["loop"] > 2.0 * m["median"]
   assert "튄다" in loop.judge_loop(m, 2.0)[0]


def test_ping_pong_is_fine():
   m = loop.measure_loop([frame(2), frame(3), frame(4), frame(3)])
   assert loop.judge_loop(m, 2.0) == []


def test_too_few_or_mixed_sizes():
   assert loop.measure_loop([frame(2), frame(3)]) is None
   assert loop.measure_loop([frame(2), frame(3), image.new(8, 8)]) is None


def test_group_loose_names():
   groups = loop.group_loose(["walk_south_1.png", "walk_south_0.png", "big_walk_east_10.png", "icon.png"])
   assert groups == {
      ("big_walk", "east"): [(10, "big_walk_east_10.png")],
      ("walk", "south"): [(0, "walk_south_0.png"), (1, "walk_south_1.png")],
   }
