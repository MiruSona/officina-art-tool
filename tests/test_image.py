import numpy as np
import pytest

from arttool import image
from arttool.errors import ArtToolError


def test_new_is_empty():
   arr = image.new(4, 3)
   assert image.size(arr) == (4, 3)
   assert image.bbox(arr) is None
   assert image.count_colors(arr) == 0


def test_save_and_load_roundtrip(tmp_path):
   arr = image.new(2, 2)
   arr[0, 0] = (255, 0, 0, 255)
   path = tmp_path / "a" / "b.png"
   image.save(path, arr)
   back = image.load(path)
   assert np.array_equal(arr, back)
   assert not (tmp_path / "a" / "b.png.tmp").exists()


def test_load_missing_file(tmp_path):
   with pytest.raises(ArtToolError):
      image.load(tmp_path / "없다.png")


def test_bbox_and_crop():
   arr = image.new(8, 8)
   arr[2:5, 3:6] = (0, 255, 0, 255)
   assert image.bbox(arr) == (3, 2, 6, 5)
   cut = image.crop(arr, 3, 2, 3, 3)
   assert image.size(cut) == (3, 3)
   assert image.bbox(cut) == (0, 0, 3, 3)


def test_paste_keeps_alpha():
   dst = image.new(4, 4, (10, 10, 10, 255))
   src = image.new(2, 2)
   src[0, 0] = (255, 0, 0, 255)
   image.paste(dst, src, 1, 1)
   assert tuple(dst[1, 1]) == (255, 0, 0, 255)
   assert tuple(dst[2, 2]) == (10, 10, 10, 255)


def test_paste_out_of_canvas():
   dst = image.new(4, 4)
   with pytest.raises(ArtToolError):
      image.paste(dst, image.new(2, 2), 3, 3)


def test_flip_x():
   arr = image.new(3, 1)
   arr[0, 0] = (1, 2, 3, 255)
   flipped = image.flip_x(arr)
   assert tuple(flipped[0, 2]) == (1, 2, 3, 255)


def test_soft_alpha():
   arr = image.new(2, 2)
   assert not image.has_soft_alpha(arr)
   arr[0, 0] = (1, 1, 1, 128)
   assert image.has_soft_alpha(arr)


def test_colors_ignore_transparent():
   arr = image.new(2, 2)
   arr[0, 0] = (1, 1, 1, 255)
   arr[0, 1] = (2, 2, 2, 255)
   arr[1, 0] = (9, 9, 9, 0)
   assert image.count_colors(arr) == 2


def test_count_colors_matches_row_unique_and_is_fast():
   """수 하나로 엮어 세도 줄 비교(np.unique axis=0)와 같은 값이다. 945×2048 잡음 한 장이 1초 안에 끝난다."""
   import time

   rng = np.random.default_rng(5)
   arr = rng.integers(0, 256, size=(300, 200, 4), dtype=np.uint8)
   arr[::7, :, 3] = 0                                          # 투명 칸은 안 센다
   mask = arr[:, :, 3] > 0
   rows = np.unique(arr[:, :, :3][mask].reshape(-1, 3), axis=0)
   assert image.count_colors(arr) == len(rows)
   assert image.opaque_colors(arr) == {tuple(int(v) for v in r) for r in rows}
   big = rng.integers(0, 256, size=(2048, 945, 4), dtype=np.uint8)
   big[:, :, 3] = 255
   big[0, 0, 3] = 0
   start = time.perf_counter()
   count = image.count_colors(big)                             # 큰 그림은 표시판 길
   assert time.perf_counter() - start < 1.0
   mask = big[:, :, 3] > 0
   rgb = big[:, :, :3][mask].astype(np.uint32)
   assert count == np.unique((rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]).size


def test_find_color():
   arr = image.new(4, 4)
   arr[1, 2] = (255, 0, 255, 255)
   assert image.find_color(arr, (255, 0, 255)) == [(2, 1)]


def test_split_and_pack_grid():
   arr = image.new(4, 4)
   arr[0, 0] = (1, 1, 1, 255)
   arr[2, 2] = (2, 2, 2, 255)
   rows = image.split_grid(arr, 2, 2)
   assert len(rows) == 2 and len(rows[0]) == 2
   packed = image.pack_grid(rows, 2, 2)
   assert np.array_equal(packed, arr)


def test_split_grid_bad_size():
   with pytest.raises(ArtToolError):
      image.split_grid(image.new(5, 4), 2, 2)


def test_replace_colors():
   arr = image.new(2, 1)
   arr[0, 0] = (1, 1, 1, 255)
   out = image.replace_colors(arr, {(1, 1, 1): (7, 7, 7)})
   assert tuple(out[0, 0]) == (7, 7, 7, 255)
