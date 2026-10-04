"""① integer_scale 재기 · 판정. 그림은 코드로 만든다."""

import numpy as np
from PIL import Image

from arttool import image
from arttool.checks import scale

COLORS = [(200, 60, 50, 255), (60, 140, 200, 255), (240, 220, 120, 255), (40, 40, 60, 255)]
CFG = {"enabled": True, "block_ratio": 0.95, "smooth_ratio": 0.15}


def noise(w, h, seed=0, colors=COLORS):
   """색 넷을 마구 뿌린 1배 그림 — 경계가 아주 많다."""
   rng = np.random.default_rng(seed)
   pick = rng.integers(0, len(colors), size=(h, w))
   return np.array(colors, dtype=np.uint8)[pick]


def test_one_x_noise_is_scale_one():
   m = scale.measure_scale(noise(16, 16))
   assert m["scale"] == 1 and not m["mixed"]


def test_two_x_is_scale_two():
   m = scale.measure_scale(image.scale_up(noise(16, 16), 2))
   assert m["scale"] == 2
   assert m["blocks"][0]["ratios"][2] == 1.0


def test_three_and_four_x():
   assert scale.measure_scale(image.scale_up(noise(12, 12, 1), 3))["scale"] == 3
   assert scale.measure_scale(image.scale_up(noise(12, 12, 2), 4))["scale"] == 4


def test_mixed_sprites_on_transparent_canvas():
   canvas = image.new(80, 40)
   image.paste(canvas, image.scale_up(noise(16, 16, 3), 2), 2, 2)
   image.paste(canvas, noise(16, 16, 4), 56, 10)
   m = scale.measure_scale(canvas)
   assert m["mixed"] and m["scales"] == [1, 2]
   why = scale.judge_integer_scale(m, scale.measure_smooth(canvas), CFG, 1)
   assert any("섞였다" in w for w in why)


def test_two_x_person_on_one_x_background():
   """×2 로 키운 사람을 1배 배경에 붙인 그림 (설계 7-4) — 배경 모드 32칸으로 나눠 섞임을 잡는다."""
   bg = noise(128, 128, 5)
   image.paste(bg, image.scale_up(noise(16, 16, 6), 2), 32, 32)
   m = scale.measure_scale(bg, background=True)
   assert m["mixed"] and m["scales"] == [1, 2]


def test_tiny_block_is_not_judged():
   """경계 칸이 16개 미만인 덩어리는 판정에서 뺀다."""
   arr = image.new(10, 10)
   arr[3:7, 3:7] = noise(4, 4, 9)
   m = scale.measure_scale(arr)
   assert m["scale"] is None and m["blocks"][0]["edge_cells"] < scale.MIN_EDGE_CELLS


def test_one_color_flat_square_is_not_judged():
   """한 색 평면 네모는 짝수 크기라도 ×2 · ×4 로 안 잡는다."""
   arr = image.new(20, 20)
   arr[2:18, 2:18] = (200, 60, 50, 255)
   assert scale.measure_scale(arr)["scale"] is None


def test_style_scale_mismatch_warns():
   m = scale.measure_scale(image.scale_up(noise(16, 16), 2))
   smooth = scale.measure_smooth(image.scale_up(noise(16, 16), 2))
   assert scale.judge_integer_scale(m, smooth, CFG, 2) == []
   assert "style.scale" in scale.judge_integer_scale(m, smooth, CFG, 1)[0]


def test_bilinear_upscale_is_smooth():
   small = noise(16, 16, 7)
   big = np.array(Image.fromarray(small, "RGBA").resize((64, 64), Image.BILINEAR))
   big[:, :, 3] = 255
   smooth = scale.measure_smooth(big)
   assert smooth["ratio"] > CFG["smooth_ratio"]
   assert any("부드러운" in w for w in scale.judge_integer_scale(scale.measure_scale(big), smooth, CFG, 1))


def test_nearest_upscale_is_not_smooth():
   assert scale.measure_smooth(image.scale_up(noise(16, 16, 8), 4))["ratio"] == 0.0


def test_straight_line_background_is_one_x():
   """32×32 두 색을 y=8 에서 가로로 나눈 칸을 바둑판처럼 이은 배경 — 직선 경계뿐이라 배율 근거가 못 된다 (실물 시험 버그 3)."""
   cell = np.zeros((32, 32, 4), dtype=np.uint8)
   cell[:, :] = (120, 90, 60, 255)
   cell[8:, :] = (90, 140, 70, 255)
   cell[20:22, :] = (200, 200, 180, 255)                 # 2px 줄무늬도 직선
   bg = np.tile(cell, (4, 4, 1))
   m = scale.measure_scale(bg, background=True)
   assert m["scales"] == [] and not m["mixed"]
   assert all(b["scale"] is None for b in m["blocks"])
   # 꺾인 자리가 있는 칸은 그대로 잰다 — ×2 사람이 섞인 배경은 계속 잡는다
   image.paste(bg, image.scale_up(noise(16, 16, 6), 2), 32, 32)
   image.paste(bg, noise(32, 32, 7), 64, 64)
   assert scale.measure_scale(bg, background=True)["scales"] == [1, 2]


def test_smooth_skipped_for_few_colors():
   """색 ≤ 8 인 그림은 smooth 비율이 높아도 부드러운 확대로 안 본다 (실물 시험 버그 4)."""
   arr = np.zeros((64, 48, 4), dtype=np.uint8)
   arr[:, :, 3] = 255
   wave = [40, 80, 120, 160, 200, 160, 120, 80]
   for x in range(48):
      arr[:, x, :3] = wave[x % 8]                           # 오르내리는 단계 명암, 5색
   smooth = scale.measure_smooth(arr)
   assert smooth["colors"] == 5 and smooth["ratio"] > CFG["smooth_ratio"]
   assert not scale.smooth_hit(smooth, CFG)
   assert not any("부드러운" in w for w in scale.judge_integer_scale(scale.measure_scale(arr), smooth, CFG, 1))
   assert scale.smooth_hit({**smooth, "colors": 9}, CFG)


def test_smooth_message_has_three_decimals():
   """0.1504 가 「0.15 > 0.15」 로 찍히지 않는다 (실물 시험 버그 6)."""
   smooth = {"ratio": 0.1504, "smooth": 1, "candidates": 1, "colors": 300}
   why = scale.judge_integer_scale({"mixed": False, "scale": None, "scales": []}, smooth, CFG, 1)
   assert why == ["부드러운 확대 흔적 0.150 > 0.15"]


def test_components_join_u_shape_and_keep_raster_order():
   # U 자 : 윗줄에선 두 토막이 아래에서 이어진다. 대각선 한 칸도 8방향으로 붙는다. 오른쪽 아래 외딴 점은 따로.
   mask = np.zeros((6, 8), dtype=bool)
   mask[0:3, 0] = mask[0:3, 3] = True
   mask[3, 0:4] = True
   mask[4, 4] = True                    # 대각선으로 붙는다
   mask[5, 7] = True                    # 따로
   mask[0, 6] = True                    # 따로, 래스터 순서로는 두 번째
   comps = scale.components(mask)
   assert [box for _, box in comps] == [(0, 0, 5, 5), (6, 0, 7, 1), (7, 5, 8, 6)]
   assert int(comps[0][0].sum()) == 11
