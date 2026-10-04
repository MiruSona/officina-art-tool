"""③ isolated · ④ color_cap · ⑤ near_colors 재기 · 판정."""

import time

import numpy as np

from arttool import image
from arttool.checks import pixels

FILL = (90, 120, 160, 255)
DOT = (240, 220, 120, 255)


def square(size=32):
   arr = image.new(size + 2, size + 2)
   arr[1 : 1 + size, 1 : 1 + size] = FILL
   return arr


def test_isolated_five_percent_warns():
   arr = square()
   for y in range(3, 33, 4):
      for x in range(3, 33, 4):
         arr[y, x] = DOT
   m = pixels.measure_isolated(arr)
   assert m["ratio"] > 0.04
   assert pixels.judge_isolated(m, {"max_ratio": 0.03})
   assert len(m["points"]) <= pixels.MAX_POINTS


def test_isolated_clean_and_edge_ignored():
   arr = square()
   arr[1, 10] = DOT          # 가장자리(투명과 맞닿은) 칸은 바깥 AA 로 보고 뺀다
   arr[16, 16] = DOT         # 안쪽 한 점 — 비율로는 안 걸린다
   m = pixels.measure_isolated(arr)
   assert m["count"] == 1
   assert pixels.judge_isolated(m, {"max_ratio": 0.03}) == []


def test_cap_for_table():
   table = {8: 4, 16: 8, 32: 16, 48: 24, 64: 32}
   assert pixels.cap_for(5, table) == (8, 4)
   assert pixels.cap_for(32, table) == (32, 16)
   assert pixels.cap_for(33, table) == (48, 24)
   assert pixels.cap_for(200, table) == (64, 32)


def _striped(colors: int, size=32):
   arr = image.new(size, size)
   for x in range(size):
      arr[:, x] = (10 * (x % colors), 100, 200 - 5 * (x % colors), 255)
   return arr


def test_color_cap_32px_twenty_colors():
   m = pixels.measure_colors(_striped(20))
   assert m == {"size": 32, "colors": 20}
   assert pixels.judge_color_cap(m, 16)
   assert pixels.judge_color_cap(pixels.measure_colors(_striped(12)), 16) == []


def test_near_colors_plus_minus_two_noise():
   arr = square(10)
   arr[3, 3] = (92, 121, 158, 255)      # ±2 잡색
   arr[6, 6] = (92, 121, 158, 255)
   pairs = pixels.measure_near_colors(arr, 4)
   assert len(pairs) == 1
   assert pairs[0]["from"] == "#5C799E" and pairs[0]["to"] == "#5A78A0"
   assert pairs[0]["from_count"] == 2 and pairs[0]["delta"] == 2
   assert pixels.judge_near_colors(pairs)


def test_near_colors_far_apart_is_clean():
   arr = square(10)
   arr[3, 3] = (100, 120, 160, 255)     # 한 칸이 10 차이 — 합치기 후보 아님
   assert pixels.measure_near_colors(arr, 4) == []


# --- 2026-10-04 보강 (리뷰 R1-L1 · R1-M2 · 실물 시험 #19) ---


def test_isolated_white_dot_is_found():
   """순백 #FFFFFF 외톨이 칸도 잡는다. int32 로 엮으면 넘쳐서 빈칸 표시 -1 과 같아졌다."""
   arr = square(10)
   arr[5, 5] = (255, 255, 255, 255)
   m = pixels.measure_isolated(arr)
   assert m["count"] == 1 and m["points"] == [[5, 5]]


def test_near_colors_min_pairs():
   pairs = [{"from": "#000000"}] * 19
   assert pixels.judge_near_colors(pairs, 20) == []
   assert pixels.judge_near_colors(pairs + pairs[:1], 20)
   assert pixels.judge_near_colors(pairs[:1]) != []                  # min_pairs 기본 1 = 예전 그대로


def test_close_pairs_matches_brute_force():
   """정렬 · searchsorted 로 바꾼 셈이 모든 쌍 견주기와 같은 답을 같은 차례로 낸다."""
   rng = np.random.default_rng(3)
   colors = np.unique(rng.integers(0, 256, size=(3000, 3)), axis=0).astype(np.int32)
   colors = np.concatenate([colors, colors[:50] + 1, np.array([[0, 0, 0], [255, 255, 255]])])
   colors = np.unique(np.clip(colors, 0, 255), axis=0)
   for delta in (0, 2, 4, 9):
      gap = np.abs(colors[:, None, :].astype(int) - colors[None, :, :]).max(axis=-1)
      a, b = np.nonzero(np.triu(gap <= delta, 1))
      want = sorted(zip(a.tolist(), b.tolist(), gap[a, b].tolist()))
      assert pixels._close_pairs(colors, delta) == want


def test_near_colors_many_colors_is_fast():
   """색 수만 가지 그림도 한 번에 센다 (예전 1024² 잡음 77초)."""
   rng = np.random.default_rng(4)
   arr = np.zeros((256, 256, 4), dtype=np.uint8)
   arr[:, :, :3] = rng.integers(0, 256, size=(256, 256, 3))
   arr[:, :, 3] = 255
   start = time.perf_counter()
   pairs = pixels.measure_near_colors(arr, 4)
   assert time.perf_counter() - start < 5.0
   assert len(pairs) > 0


def test_color_count_matches_image_count():
   rng = np.random.default_rng(5)
   arr = np.zeros((40, 40, 4), dtype=np.uint8)
   arr[:, :, :3] = rng.integers(0, 6, size=(40, 40, 3)) * 50
   arr[:, :, 3] = rng.integers(0, 2, size=(40, 40)) * 255
   assert pixels.color_count(arr) == image.count_colors(arr)
   assert pixels.color_count(image.new(4, 4)) == 0
