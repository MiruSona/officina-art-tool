import json

import pytest

from arttool import image, palette
from arttool.errors import ArtToolError
from arttool.profile import tool_home


def sample_path():
   return tool_home() / "palettes" / "lpc_cloth.json"


def test_parse_hex():
   assert palette.parse_hex("#FF8000") == (255, 128, 0)
   assert palette.to_hex((255, 128, 0)) == "#FF8000"


def test_bad_hex():
   with pytest.raises(ArtToolError):
      palette.parse_hex("FF8000")


def test_load_sample_ramps():
   ramps = palette.load_ramps(sample_path())
   assert ramps.ramp_len == 6
   assert "cloth_blue" in ramps.names()
   assert len(ramps.ramp("cloth_blue")) == 6
   assert (0, 0, 0) in ramps.colors()


def test_wrong_ramp_length(tmp_path):
   path = tmp_path / "r.json"
   path.write_text(json.dumps({"ramps": {"a": ["#000000"]}, "ramp_len": 3}), encoding="utf-8")
   with pytest.raises(ArtToolError):
      palette.load_ramps(path)


def test_outside_colors():
   ramps = palette.load_ramps(sample_path())
   arr = image.new(2, 1)
   arr[0, 0] = (*ramps.ramp("cloth_blue")[0], 255)
   arr[0, 1] = (1, 2, 3, 255)
   assert palette.outside_colors(arr, ramps) == [(1, 2, 3)]


def test_snap_exact_does_not_change():
   ramps = palette.load_ramps(sample_path())
   arr = image.new(1, 1)
   arr[0, 0] = (1, 2, 3, 255)
   out, strays = palette.snap_exact(arr, ramps)
   assert tuple(out[0, 0]) == (1, 2, 3, 255)
   assert strays == [(1, 2, 3)]


def test_snap_nearest_moves_to_ramp():
   ramps = palette.load_ramps(sample_path())
   target = ramps.ramp("cloth_blue")[2]
   arr = image.new(1, 1)
   arr[0, 0] = (target[0] + 1, target[1], target[2], 255)
   out, changed = palette.snap_nearest(arr, ramps)
   assert changed == 1
   assert tuple(out[0, 0])[:3] == target
   assert palette.outside_colors(out, ramps) == []


def test_build_lut_shape():
   ramps = palette.load_ramps(sample_path())
   lut = palette.build_lut(ramps, ["cloth_blue", "cloth_red"])
   assert image.size(lut) == (6, 2)
   assert tuple(lut[0, 0])[:3] == ramps.ramp("cloth_blue")[0]
   assert tuple(lut[1, 5])[:3] == ramps.ramp("cloth_red")[5]


def test_save_lut(tmp_path):
   ramps = palette.load_ramps(sample_path())
   out = tmp_path / "lut.png"
   palette.save_lut(out, ramps)
   assert image.size(image.load(out)) == (6, len(ramps.names()))


def test_ramp_asset_json():
   ramps = palette.load_ramps(sample_path())
   data = palette.ramp_asset_json(ramps, ["gold"])
   assert data["rampLen"] == 6
   assert data["ramps"][0]["name"] == "gold"
   assert data["ramps"][0]["colors"][0].startswith("#")


# --- shade (그늘 계산, 2026-10-04 개선 설계 6-5 · 8-5 #7) ---

def _luma(rgb):
   r, g, b = rgb
   return 0.299 * r + 0.587 * g + 0.114 * b


def _hue(rgb):
   import colorsys

   return colorsys.rgb_to_hsv(*(c / 255 for c in rgb))[0] * 360


def test_shade_keeps_base_and_rises():
   ramp = palette.shade("#3C8C50", 6, 20)
   assert len(ramp) == 6
   assert ramp[3] == (0x3C, 0x8C, 0x50)  # 밑색은 가운데(6 // 2) 칸에 그대로
   lumas = [_luma(c) for c in ramp]
   assert lumas == sorted(lumas) and len(set(lumas)) == 6  # 어두운 → 밝은, 같은 칸 없음


def test_shade_hue_shift_direction():
   """초록(140°) : 밝을수록 노랑(60°) 쪽, 어두울수록 파랑(240°) 쪽."""
   ramp = palette.shade("#3C8C50", 6, 20)
   assert _hue(ramp[5]) < _hue(ramp[3]) < _hue(ramp[0])
   metal = palette.shade("#3C8C50", 6, 20, metal=True)
   assert _hue(metal[5]) > _hue(metal[3]) > _hue(metal[0])


def test_shade_does_not_overshoot_target():
   """노랑에 가까운 밑색은 노랑을 넘어가지 않는다."""
   ramp = palette.shade("#D2B43C", 5, 30)  # 약 48°
   assert all(abs(_hue(c) - 60) <= 13 for c in ramp[3:])


def test_shade_zero_step_and_base_index():
   flat = palette.shade((100, 60, 60), 4, 0, base_index=0)
   assert flat[0] == (100, 60, 60)
   assert all(abs(_hue(c) - _hue((100, 60, 60))) < 2 for c in flat)


@pytest.mark.parametrize("kwargs", [{"steps": 1}, {"steps": True}, {"hue_step": -1}, {"base_index": 6}])
def test_shade_bad_args(kwargs):
   args = {"base": "#808080", "steps": 6, "hue_step": 20}
   args.update(kwargs)
   with pytest.raises(ArtToolError):
      palette.shade(**args)


def test_shade_lut_ready():
   """shade 결과로 만든 램프 묶음이 LUT 까지 간다 (같은 길이 규칙)."""
   ramps = palette.Ramps("t", {"a": palette.shade("#A03030", 6), "b": palette.shade("#3050A0", 6)}, None, 6)
   assert palette.build_lut(ramps, ["a", "b"]).shape == (2, 6, 4)
