"""② outline 재기 · 판정. 네모 하나에 외곽선 방식만 바꿔 그린다."""

import pytest

from arttool import image
from arttool.checks import outline

FILL = (200, 80, 60, 255)
SHADE = (110, 40, 35, 255)        # 채움색의 어두운 쪽 (같은 색조)
LIT_SHADE = (150, 58, 45, 255)    # 빛 쪽 외곽선 : 어둡지만 반대쪽보다 밝다
FAR_SHADE = (70, 25, 20, 255)


def box(border_top_left=None, border_bottom_right=None, size=20):
   arr = image.new(size + 4, size + 4)
   arr[2 : 2 + size, 2 : 2 + size] = FILL
   if border_top_left is not None:
      arr[2, 2 : 2 + size] = border_top_left
      arr[2 : 2 + size, 2] = border_top_left
   if border_bottom_right is not None:
      arr[1 + size, 2 : 2 + size] = border_bottom_right
      arr[2 : 2 + size, 1 + size] = border_bottom_right
   return arr


@pytest.mark.parametrize(
   "arr, want",
   [
      (box((0, 0, 0, 255), (0, 0, 0, 255)), "black"),
      (box(SHADE, SHADE), "selout"),
      (box(LIT_SHADE, FAR_SHADE), "selout+light"),
      (box(), "none"),
   ],
)
def test_verdicts(arr, want):
   assert outline.measure_outline(arr, "top_left")["verdict"] == want


def test_light_side_follows_style_light():
   """빛이 오른쪽 위에서 오면 왼쪽 위가 밝은 외곽선은 selout+light 가 아니다."""
   m = outline.measure_outline(box(LIT_SHADE, FAR_SHADE), "top_right")
   assert m["verdict"] == "selout"


def test_mixed_when_half_black():
   arr = box((0, 0, 0, 255), None)
   assert outline.measure_outline(arr)["verdict"] == "mixed"


def test_judge_against_style():
   m = outline.measure_outline(box(SHADE, SHADE))
   assert outline.judge_outline(m, "selout") == []
   assert "black" in outline.judge_outline(m, "black")[0]
   assert outline.judge_outline(m, "unset") == []


def test_empty_picture_has_no_verdict():
   m = outline.measure_outline(image.new(8, 8))
   assert m["verdict"] is None and m["edges"] == 0
   assert outline.judge_outline(m, "black") == []


def test_thin_hair_end_is_not_an_edge():
   """1px 가는 줄은 안쪽 이웃이 없어 가장자리로 안 센다."""
   arr = image.new(10, 10)
   arr[5, 1:9] = (0, 0, 0, 255)
   assert outline.measure_outline(arr)["edges"] == 0


def thick(width, line, inside, size=48):
   """두께 width 외곽선 네모. 안쪽은 inside(한 색 또는 색 목록이면 세로 띠)."""
   arr = image.new(size, size)
   arr[:, :] = line
   if isinstance(inside, list):
      for x in range(width, size - width):
         arr[width : size - width, x] = inside[(x // 3) % len(inside)]
   else:
      arr[width : size - width, width : size - width] = inside
   arr[0, :] = arr[-1, :] = arr[:, 0] = arr[:, -1] = (0, 0, 0, 0)    # 둘레 1칸 투명
   return arr


def test_two_px_dark_outline_is_not_none():
   """48×48 · 두께 2px 외곽선(밝기 50) · 안쪽 밝기 150 → 「없음」 이 아니다 (실물 시험 버그 5)."""
   arr = thick(3, (50, 50, 50, 255), (150, 150, 150, 255))         # 투명 1칸 + 외곽선 2칸
   m = outline.measure_outline(arr)
   assert m["dark_ratio"] >= 0.9                                    # 모서리 몇 칸만 띠 안에 머문다
   assert m["verdict"] == "selout"


def test_three_px_inside_brightest_is_used():
   """1~3칸 안쪽 중 가장 밝은 것과 견준다 — 3px 외곽선도 어둡게 읽힌다."""
   arr = thick(4, (60, 30, 25, 255), (200, 80, 60, 255))
   assert outline.measure_outline(arr)["dark_ratio"] >= 0.9


def test_near_black_counts_as_black():
   """밝기 20~30 의 거의 검정 외곽선은 순흑으로 센다 (BLACK_MAX 32, 실물 시험 #2)."""
   assert outline.measure_outline(box((28, 28, 30, 255), (28, 28, 30, 255)))["verdict"] == "black"
   assert outline.measure_outline(box((40, 40, 40, 255), (40, 40, 40, 255)))["black_ratio"] == 0.0


def test_gray_one_color_line_is_solid():
   """여러 색 안쪽에 회색 한 색 외곽선 → solid (실물 시험 #3)."""
   inside = [(200, 80, 60, 255), (60, 140, 200, 255), (240, 220, 120, 255)]
   m = outline.measure_outline(thick(2, (90, 90, 90, 255), inside))
   assert m["solid_share"] == 1.0 and m["inner_share"] < outline.SOLID_INNER
   assert m["verdict"] == "solid"
   assert outline.judge_outline(m, "solid") == []
   # 한 색 물체의 한 색 외곽선은 selout 과 못 가려 selout 으로 둔다
   assert outline.measure_outline(box(SHADE, SHADE))["verdict"] == "selout"


def test_share_and_small_note():
   m = outline.measure_outline(box(SHADE, SHADE, size=10))
   assert m["size"] == 10
   assert m["expected_share"] == round((4 * 10 - 4) / 100, 4)
   assert outline.small_note(m, "selout") is not None
   assert outline.small_note(m, "none") is None
