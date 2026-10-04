"""화풍 뽑기 부품 시험 — 빛 방향 · `save_ramps` · 조각 YAML · 견본. 그림은 코드로 만든 합성 그림이다."""

from __future__ import annotations

import json

import numpy as np
import pytest
import yaml

from arttool import image, palette
from arttool.errors import ArtToolError
from arttool.style import output, ramps
from arttool.style.light import estimate_light


def _ball(bright: tuple[float, float], r: int = 10, outline: bool = False) -> np.ndarray:
   """bright 방향(dx, dy)이 밝은 공. 밝기 네 단."""
   size = 2 * r + 5
   arr = image.new(size, size)
   c = size // 2
   yy, xx = np.mgrid[0:size, 0:size]
   inside = (xx - c) ** 2 + (yy - c) ** 2 <= r * r
   proj = ((xx - c) * bright[0] + (yy - c) * bright[1]) / r
   level = np.clip(((proj + 1) / 2 * 4).astype(int), 0, 3)
   shades = [(60, 40, 90), (110, 70, 140), (170, 120, 190), (230, 200, 240)]
   for i, color in enumerate(shades):
      arr[inside & (level == i)] = (*color, 255)
   if outline:
      ring = np.zeros_like(inside)
      for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
         ring |= np.roll(inside, (dy, dx), axis=(0, 1))
      arr[ring & ~inside] = (0, 0, 0, 255)
   return arr


@pytest.mark.parametrize("direction, want", [
   ((-0.707, -0.707), "top_left"),
   ((0.0, -1.0), "top"),
   ((0.707, -0.707), "top_right"),
   ((0.0, 1.0), "bottom"),
])
def test_light_direction(direction, want):
   assert estimate_light(_ball(direction))["light"] == want


def test_light_through_black_outline():
   assert estimate_light(_ball((-0.707, -0.707), outline=True))["light"] == "top_left"


def test_flat_color_is_unknown():
   arr = image.new(20, 20)
   arr[2:18, 2:18] = (100, 100, 200, 255)
   assert estimate_light(arr)["light"] == "unknown"


def test_save_ramps_roundtrip(tmp_path):
   ramp_set = palette.Ramps("t", {"a": [(1, 2, 3), (4, 5, 6)], "b": [(7, 8, 9), (7, 8, 9)]}, (0, 0, 0), 2)
   path = palette.save_ramps(tmp_path / "p.json", ramp_set, {"comment": "x", "usage": {"#010203": 0.5}})
   back = palette.load_ramps(path)
   assert back.ramps == ramp_set.ramps and back.outline == (0, 0, 0) and back.ramp_len == 2
   assert json.loads(path.read_text(encoding="utf-8"))["comment"] == "x"


def test_save_ramps_refuses_bad_input(tmp_path):
   uneven = palette.Ramps("t", {"a": [(1, 2, 3)], "b": [(1, 1, 1), (2, 2, 2)]}, None, 2)
   with pytest.raises(ArtToolError):
      palette.save_ramps(tmp_path / "p.json", uneven)
   good = palette.Ramps("t", {"a": [(1, 2, 3)]}, None, 1)
   with pytest.raises(ArtToolError):
      palette.save_ramps(tmp_path / "p.json", good, {"ramps": {}})
   assert not (tmp_path / "p.json").exists()


def test_fragment_text_round_trips():
   entries = [
      (("palette", "ramp_len"), 6, "짝"),
      (("palette", "outline"), None, "selout"),
      (("style", "outline"), "selout+light", "5장 중 4장"),
      (("check", "warn", "color_cap", "table"), {16: 8, 32: 14}, ""),
      (("check", "warn", "isolated", "max_ratio"), 0.045, "p95"),
   ]
   text = output.fragment_text(entries, ["머리 줄"], {"style": ["light : 모름"], "tiles": ["빈 절 주석"]})
   data = yaml.safe_load(text)
   assert data == {
      "palette": {"ramp_len": 6, "outline": None},
      "style": {"outline": "selout+light"},
      "check": {"warn": {"color_cap": {"table": {16: 8, 32: 14}}, "isolated": {"max_ratio": 0.045}}},
   }
   assert "# light : 모름" in text and "# tiles : 빈 절 주석" in text


def test_swatch_marks_padded_cells():
   ramp = [{"colors": [0x101010, 0x808080, 0xF0F0F0, 0xF0F0F0], "padded": 1}]
   art = output.swatch(ramp, 0x000001, [0xFF0000], scale=1)
   cell = output.CELL
   assert art[0, 2 * cell, 3] == 255                    # 진짜 칸은 꽉 찬다
   assert art[0, 3 * cell, 3] == 0                      # 채운 칸은 가장자리가 빈다
   assert art[cell // 2, 3 * cell + cell // 2, 3] == 255
   assert tuple(art[cell, 0, :3]) == (0, 0, 1)          # 외곽선 줄
   assert tuple(art[2 * cell + cell // 2, 0, :3]) == (255, 0, 0)    # 반 칸 띄고 버린 색


def test_group_needs_touch_and_close_hue():
   """맞닿아도 색조가 멀면 안 잇고, 색조가 가까워도 안 맞닿으면 안 잇는다."""
   arr = image.new(12, 4)
   arr[:, 0:3] = (200, 40, 40, 255)      # 빨강
   arr[:, 3:6] = (220, 90, 50, 255)      # 주황빛 빨강 — 맞닿음, 색조 가까움
   arr[:, 6:9] = (40, 40, 200, 255)      # 파랑 — 맞닿음, 색조 멂
   arr[:, 10:12] = (180, 30, 30, 255)    # 빨강 — 색조 가깝지만 안 맞닿음
   maps = [ramps.key_map(arr)]
   keep = {k for k in np.unique(maps[0]).tolist() if k >= 0}
   _usage, _images, pixels = ramps.usage_of(maps)
   groups = ramps.group_colors(keep, ramps.touching_pairs(maps, keep), pixels)
   sizes = sorted(len(g) for g in groups)
   assert sizes == [1, 1, 2]
