"""⑥ ramp_shape 재기 · 판정. 램프는 palette.shade 로 만든다."""

from arttool import palette
from arttool.checks import ramp

CFG = {"enabled": True, "steps": [4, 6], "hue_min": 5, "hue_max": 30}


def test_good_ramp_passes():
   colors = palette.shade("#B03030", steps=6, hue_step=20)
   m = ramp.measure_ramp(colors)
   assert m["steps"] == 6 and m["monotonic"]
   assert ramp.judge_ramp(m, CFG) == []


def test_no_hue_shift_warns():
   colors = palette.shade("#B03030", steps=6, hue_step=0)
   why = ramp.judge_ramp(ramp.measure_ramp(colors), CFG)
   assert any("hue shift 없음" in w for w in why)


def test_hue_jump_warns():
   colors = [(60, 20, 20), (110, 40, 40), (60, 160, 60), (200, 240, 200)]
   why = ramp.judge_ramp(ramp.measure_ramp(colors), CFG)
   assert any("튄다" in w for w in why)


def test_not_monotonic_warns():
   colors = [(40, 20, 20), (120, 50, 40), (90, 40, 30), (200, 120, 90)]
   assert any("밝기" in w for w in ramp.judge_ramp(ramp.measure_ramp(colors), CFG))


def test_metal_expects_reverse_direction():
   warm = palette.shade("#7080A0", steps=6, hue_step=15)
   cold = palette.shade("#7080A0", steps=6, hue_step=15, metal=True)
   assert any("금속" in w for w in ramp.judge_ramp(ramp.measure_ramp(warm), CFG, "metal"))
   assert not any("금속" in w for w in ramp.judge_ramp(ramp.measure_ramp(cold), CFG, "metal"))
   assert any("따뜻한" in w for w in ramp.judge_ramp(ramp.measure_ramp(cold), CFG))


def test_material_steps_table():
   colors = palette.shade("#B03030", steps=6, hue_step=20)
   assert any("gem" in w for w in ramp.judge_ramp(ramp.measure_ramp(colors), CFG, "gem"))
   assert not any("단 수" in w for w in ramp.judge_ramp(ramp.measure_ramp(colors), CFG, "ice"))


def test_padded_cells_are_skipped():
   """화풍 뽑기가 끝 색 되풀이로 채운 칸은 건너뛴다 (설계 9-3 ①-4) — 밝기 단조 깨짐으로 안 본다."""
   real = palette.shade("#B03030", steps=4, hue_step=20)
   m = ramp.measure_ramp(real + [real[-1], real[-1]])
   assert m["steps"] == 4 and m["padded"] == 2 and m["monotonic"]
   assert ramp.judge_ramp(m, CFG) == []


def test_short_ramp_mentions_padding():
   real = palette.shade("#B03030", steps=3, hue_step=20)
   why = ramp.judge_ramp(ramp.measure_ramp(real + [real[-1]] * 3), CFG)
   assert any("단 수 3" in w and "채운 칸 3" in w for w in why)


def test_gray_and_outline_cells_skip_hue():
   colors = [(0, 0, 0), (60, 60, 60), (120, 120, 120), (200, 200, 200)]
   m = ramp.measure_ramp(colors, outline=(0, 0, 0))
   assert m["hue_steps"] == [] and m["hues"] == []
   assert ramp.judge_ramp(m, CFG) == []
