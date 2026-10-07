import numpy as np
import pytest

from arttool import image
from arttool.draw.grid import LETTERS, Legend, to_text
from arttool.errors import ArtToolError

RED = (255, 0, 0)
BLUE = (0, 0, 255)
GREEN = (0, 255, 0)


def _arr(width, height):
   return image.new(width, height)


def _grid_lines(text):
   """범례와 빈 줄을 떼고 격자 줄만."""
   return text.split("\n\n", 1)[1].splitlines()


def test_legend_auto_order_and_same_color_same_letter():
   legend = Legend()
   assert legend.assign(RED) == "a"
   assert legend.assign(BLUE) == "b"
   assert legend.assign("#FF0000") == "a"
   assert legend.assign(np.array([0, 0, 255], dtype=np.uint8)) == "b"
   assert legend.text() == "a #FF0000\nb #0000FF"
   assert len(legend) == 2 and legend.color("b") == BLUE


def test_legend_order_runs_lower_upper_digits():
   legend = Legend()
   letters = [legend.assign((i, 0, 0)) for i in range(62)]
   assert "".join(letters) == LETTERS
   assert letters[26] == "A" and letters[52] == "0" and letters[-1] == "9"


def test_legend_over_62_colors_rejected():
   legend = Legend()
   for i in range(62):
      legend.assign((i, 0, 0))
   with pytest.raises(ArtToolError, match="62"):
      legend.assign((200, 0, 0))
   assert legend.assign((5, 0, 0)) == LETTERS[5]


def test_legend_preset_letters_kept_and_skipped():
   legend = Legend({"k": "#2A2238", "a": (246, 208, 176)})
   assert legend.assign((0x2A, 0x22, 0x38)) == "k"
   assert legend.assign(RED) == "b"
   assert legend.text().splitlines() == ["k #2A2238", "a #F6D0B0", "b #FF0000"]
   assert Legend({}).text() == ""


@pytest.mark.parametrize("bad", [".", "#", " ", "ab", ""])
def test_legend_bad_letters_rejected(bad):
   with pytest.raises(ArtToolError, match="범례 글자"):
      Legend({bad: RED})


def test_legend_same_color_two_letters_rejected():
   with pytest.raises(ArtToolError, match="둘에"):
      Legend({"a": RED, "b": "#FF0000"})
   with pytest.raises(ArtToolError, match="없는 글자"):
      Legend().color("z")


def test_to_text_transparent_dot_and_layout():
   arr = _arr(3, 2)
   arr[0, 1] = (*RED, 255)
   arr[1, 0] = (*BLUE, 255)
   arr[1, 2] = (*RED, 255)
   text = to_text(arr, Legend())
   assert text == "a #FF0000\nb #0000FF\n\n.a.\nb.a\n"


def test_to_text_half_alpha_is_color_by_rgb():
   arr = _arr(2, 1)
   arr[0, 0] = (*GREEN, 128)
   arr[0, 1] = (*GREEN, 255)
   assert to_text(arr, Legend()) == "a #00FF00\n\naa\n"


def test_to_text_all_transparent_keeps_shape():
   text = to_text(_arr(2, 2), None)
   assert text.startswith("#") and _grid_lines(text) == ["..", ".."]


def test_to_text_shared_legend_keeps_letters():
   legend = Legend({"k": BLUE})
   arr = _arr(2, 1)
   arr[0, 0] = (*RED, 255)
   arr[0, 1] = (*BLUE, 255)
   assert _grid_lines(to_text(arr, legend)) == ["ak"]
   assert legend.assign(RED) == "a"


def test_to_text_box_crops_with_end_excluded():
   arr = _arr(8, 8)
   arr[3, 4] = (*RED, 255)
   lines = _grid_lines(to_text(arr, Legend(), box=(2, 2, 6, 5)))
   assert lines == ["....", "..a.", "...."]


def test_to_text_box_clipped_to_canvas_and_empty_rejected():
   arr = _arr(4, 4)
   assert _grid_lines(to_text(arr, Legend(), box=(-2, 2, 10, 9))) == ["....", "...."]
   with pytest.raises(ArtToolError, match="비었다"):
      to_text(arr, Legend(), box=(5, 0, 8, 4))


def test_rulers_use_absolute_coords():
   arr = _arr(16, 16)
   arr[9, 10] = (*RED, 255)
   lines = _grid_lines(to_text(arr, Legend(), box=(8, 8, 13, 11), rulers=True))
   assert lines == [
      "   89012",
      " 8 .....",
      " 9 ..a..",
      "10 .....",
   ]


def test_rulers_single_digit_head():
   lines = _grid_lines(to_text(_arr(3, 2), Legend(), rulers=True))
   assert lines == ["  012", "0 ...", "1 ..."]


def test_over_64_without_box_rejected_with_hint():
   with pytest.raises(ArtToolError, match="box="):
      to_text(_arr(65, 10), Legend())
   with pytest.raises(ArtToolError, match="box="):
      to_text(_arr(10, 65), Legend())
   assert len(_grid_lines(to_text(_arr(64, 64), Legend()))) == 64
   assert len(_grid_lines(to_text(_arr(100, 100), Legend(), box=(0, 0, 10, 10)))) == 10
   with pytest.raises(ArtToolError, match="창이 65x10"):          # 창도 한 변 64 이하
      to_text(_arr(100, 100), Legend(), box=(0, 0, 65, 10))
   assert len(_grid_lines(to_text(_arr(100, 100), Legend(), box=(36, 0, 120, 64)))) == 64   # 캔버스로 자른 뒤 64


def test_bad_array_rejected():
   with pytest.raises(ArtToolError, match="RGBA"):
      to_text(np.zeros((4, 4, 3), dtype=np.uint8), Legend())
