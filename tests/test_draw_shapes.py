import numpy as np
import pytest

from arttool import image
from arttool.draw import shapes
from arttool.errors import ArtToolError

S16 = (16, 16)


def test_box_filled_and_outline():
   filled = shapes.box(S16, 2, 3, 6, 5)
   assert filled.shape == (16, 16) and filled.sum() == 4 * 2
   assert filled[3, 2] and filled[4, 5] and not filled[5, 5] and not filled[3, 6]
   frame = shapes.box(S16, 0, 0, 4, 4, filled=False)
   assert frame.sum() == 12 and not frame[1, 1]


def test_box_empty_rejected():
   with pytest.raises(ArtToolError):
      shapes.box(S16, 3, 3, 3, 5)


def test_dot_and_clip():
   assert shapes.dot(S16, 7, 7, 2).sum() == 4
   assert shapes.dot(S16, 15, 15, 3).sum() == 1  # 캔버스 밖은 잘린다


def test_line_endpoints_and_even_steps():
   flat = shapes.line(S16, 0, 0, 5, 1)
   assert flat[0, 0] and flat[1, 5] and flat.sum() == 6
   # 계단 길이가 3 · 3 으로 고르다
   assert flat[0].sum() == 3 and flat[1].sum() == 3
   diag = shapes.line(S16, 0, 0, 3, 3)
   assert [tuple(p) for p in np.argwhere(diag)] == [(0, 0), (1, 1), (2, 2), (3, 3)]
   assert shapes.line(S16, 4, 4, 4, 4).sum() == 1
   # 거꾸로 그어도 같은 칸
   assert (shapes.line(S16, 5, 1, 0, 0) == flat).all()


def test_disc_fills_diameter():
   full = shapes.disc(S16, 7.5, 7.5, 8)
   assert full[7].all() and full[:, 7].all()  # 가운데 줄은 16칸 다
   assert not full[0, 0] and not full[15, 15]
   assert (full == full[::-1]).all() and (full == full[:, ::-1]).all()  # 대칭


def test_ring_is_disc_minus_inner():
   ring = shapes.ring(S16, 7.5, 7.5, 8, width=2)
   assert not ring[7, 7]
   assert ring[7, 0] and ring[7, 1] and not ring[7, 2]
   assert (ring == (shapes.disc(S16, 7.5, 7.5, 8) & ~shapes.disc(S16, 7.5, 7.5, 6))).all()


def test_ring_dash_removes_some():
   solid = shapes.ring(S16, 7.5, 7.5, 8, width=1)
   dashed = shapes.ring(S16, 7.5, 7.5, 8, width=1, dash=2)
   assert 0 < dashed.sum() < solid.sum()
   assert not (dashed & ~solid).any()


@pytest.mark.parametrize("call", [lambda: shapes.disc(S16, 1, 1, 0), lambda: shapes.ring(S16, 1, 1, 4, width=0), lambda: shapes.dot(S16, 0, 0, 0)])
def test_bad_sizes_rejected(call):
   with pytest.raises(ArtToolError):
      call()


def test_paint_no_antialias():
   arr = image.new(16, 16)
   shapes.paint(arr, shapes.disc(S16, 7.5, 7.5, 5), "#FF8800")
   alphas = set(np.unique(arr[:, :, 3]).tolist())
   assert alphas == {0, 255}  # 반투명이 없다
   assert image.count_colors(arr) == 1
   assert tuple(arr[7, 7]) == (255, 136, 0, 255)


def test_paint_size_mismatch():
   with pytest.raises(ArtToolError, match="다르다"):
      shapes.paint(image.new(8, 8), shapes.empty(S16), (0, 0, 0))


def test_to_image_white_mask():
   out = shapes.to_image(shapes.box((4, 2), 0, 0, 2, 2))
   assert out.shape == (2, 4, 4)
   assert tuple(out[0, 0]) == (255, 255, 255, 255) and out[0, 3, 3] == 0


# ---- P 갈래가 더한 도형 ----


def test_round_box_cuts_stairs():
   full = shapes.box(S16, 0, 0, 8, 8).sum()
   assert shapes.round_box(S16, 0, 0, 8, 8, r=0).sum() == full
   r1 = shapes.round_box(S16, 0, 0, 8, 8, r=1)
   assert r1.sum() == full - 4 and not r1[0, 0] and r1[0, 1] and not r1[7, 7]
   r2 = shapes.round_box(S16, 0, 0, 8, 8, r=2)[:8, :8]
   assert r2.sum() == full - 4 * 3 and not r2[0, 1] and not r2[1, 0] and r2[1, 1]
   assert (r2 == r2[::-1]).all() and (r2 == r2[:, ::-1]).all()


def test_ellipse_square_is_disc_and_wide():
   assert (shapes.ellipse(S16, 0, 0, 16, 16) == shapes.disc(S16, 7.5, 7.5, 8)).all()
   wide = shapes.ellipse(S16, 0, 4, 16, 10)
   assert wide[7].all() and not wide[3].any() and not wide[10].any()
   assert (wide == wide[:, ::-1]).all()


def test_drop_tip_on_top():
   d = shapes.drop(S16, 4, 0, 12, 14)
   rows = d.sum(axis=1)
   assert rows[0] >= 1 and rows[0] <= 2          # 끝은 1~2칸
   assert rows[10] == 8                           # 원 가운데 줄은 너비만큼
   assert not d[14:].any() and (d == d[:, ::-1]).all()
   # 위에서 원 가운데까지 넓어지기만 한다
   assert all(rows[i] <= rows[i + 1] for i in range(0, 9))
   # 낮은 상자면 타원
   assert (shapes.drop(S16, 0, 0, 8, 6) == shapes.ellipse(S16, 0, 0, 8, 6)).all()


def test_flood_four_way():
   arr = image.new(6, 6)
   shapes.paint(arr, shapes.box((6, 6), 0, 2, 6, 3), "#FF0000")   # 가로 벽
   top = shapes.flood(arr, 0, 0)
   assert top.sum() == 12 and not top[3:].any()
   assert shapes.flood(arr, 3, 2).sum() == 6
   with pytest.raises(ArtToolError):
      shapes.flood(arr, 9, 0)
