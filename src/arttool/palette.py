"""팔레트 램프. 램프 JSON 읽기 · 정확일치 스냅 · LUT PNG 만들기."""

from __future__ import annotations

import colorsys
import json
import os
from pathlib import Path

import numpy as np

from . import image
from .errors import ArtToolError
from .jsonio import write_json

RGB = tuple[int, int, int]


def parse_hex(text: str) -> RGB:
   value = text.strip()
   if not value.startswith("#") or len(value) != 7:
      raise ArtToolError(f"색은 #RRGGBB 꼴이어야 한다 : {text}")
   try:
      return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
   except ValueError as exc:
      raise ArtToolError(f"색을 못 읽었다 : {text}") from exc


def to_hex(rgb: RGB) -> str:
   return "#{:02X}{:02X}{:02X}".format(*rgb)


class Ramps:
   """램프 묶음 하나. 램프 = 어두운 쪽부터 밝은 쪽까지 색 목록."""

   def __init__(self, name: str, ramps: dict[str, list[RGB]], outline: RGB | None, ramp_len: int):
      self.name = name
      self.ramps = ramps
      self.outline = outline
      self.ramp_len = ramp_len

   def colors(self) -> set[RGB]:
      out: set[RGB] = set()
      for ramp in self.ramps.values():
         out.update(ramp)
      if self.outline is not None:
         out.add(self.outline)
      return out

   def ramp(self, name: str) -> list[RGB]:
      if name not in self.ramps:
         raise ArtToolError(f"없는 램프 : {name}")
      return self.ramps[name]

   def names(self) -> list[str]:
      return list(self.ramps)


def load_ramps(path: str | os.PathLike) -> Ramps:
   file = Path(path)
   if not file.is_file():
      raise ArtToolError(f"램프 파일이 없다 : {file}")
   data = json.loads(file.read_text(encoding="utf-8-sig"))
   if not isinstance(data, dict) or "ramps" not in data:
      raise ArtToolError(f"램프 파일에 ramps 가 없다 : {file}")

   ramp_len = int(data.get("ramp_len", 0))
   ramps: dict[str, list[RGB]] = {}
   for name, colors in data["ramps"].items():
      parsed = [parse_hex(c) for c in colors]
      if ramp_len and len(parsed) != ramp_len:
         raise ArtToolError(f"램프 {name} 의 길이가 {len(parsed)} 다. {ramp_len} 이어야 한다")
      ramps[name] = parsed
   if not ramps:
      raise ArtToolError(f"램프가 하나도 없다 : {file}")

   # ramp_len 을 안 적었어도 길이가 다르면 LUT 가 굽는 중에 터진다. 여기서 막는다.
   lengths = {name: len(colors) for name, colors in ramps.items()}
   if len(set(lengths.values())) > 1:
      shown = ", ".join(f"{n}={v}" for n, v in sorted(lengths.items()))
      raise ArtToolError(f"램프 길이가 서로 다르다 : {shown} - {file}")

   outline_text = data.get("outline")
   outline = parse_hex(outline_text) if outline_text else None
   return Ramps(str(data.get("name", file.stem)), ramps, outline, ramp_len or len(next(iter(ramps.values()))))


def outside_colors(arr: image.RGBA, ramps: Ramps) -> list[RGB]:
   """램프에 없는 색 목록. 정확일치 검사에 쓴다."""
   allowed = ramps.colors()
   found = image.opaque_colors(arr)
   return sorted(found - allowed)


def snap_exact(arr: image.RGBA, ramps: Ramps) -> tuple[image.RGBA, list[RGB]]:
   """램프에 있는 색은 그대로 두고, 없는 색은 고치지 않고 알린다."""
   return arr.copy(), outside_colors(arr, ramps)


def snap_nearest(arr: image.RGBA, ramps: Ramps) -> tuple[image.RGBA, int]:
   """램프 밖 색을 가장 가까운 램프 색으로 바꾼다. 바꾼 색 가짓수를 같이 준다."""
   strays = outside_colors(arr, ramps)
   if not strays:
      return arr.copy(), 0

   # int16 이면 제곱이 넘쳐(255*255 > 32767) 먼 색이 가장 가까운 색으로 뽑힌다.
   allowed = np.array(sorted(ramps.colors()), dtype=np.int32)
   table: dict[RGB, RGB] = {}
   for color in strays:
      diff = allowed - np.array(color, dtype=np.int32)
      index = int(np.argmin(np.sum(diff * diff, axis=1)))
      table[color] = tuple(int(v) for v in allowed[index])
   return image.replace_colors(arr, table), len(table)


def build_lut(ramps: Ramps, names: list[str]) -> image.RGBA:
   """LUT PNG 를 만든다. 가로 = 램프 칸, 세로 = 변형 하나당 한 줄.

   셰이더는 (램프 칸, 변형 번호) 로 찍어 색을 읽는다.
   """
   if not names:
      raise ArtToolError("LUT 에 넣을 램프 이름이 없다")
   width = ramps.ramp_len
   lut = image.new(width, len(names))
   for row, name in enumerate(names):
      colors = ramps.ramp(name)
      for col in range(width):
         r, g, b = colors[col]
         lut[row, col] = (r, g, b, 255)
   return lut


def save_lut(path: str | os.PathLike, ramps: Ramps, names: list[str] | None = None) -> image.RGBA:
   lut = build_lut(ramps, names or ramps.names())
   image.save(path, lut)
   return lut


WARM_HUE = 60.0    # 노랑. 밝은 쪽이 다가가는 색조
COOL_HUE = 240.0   # 파랑. 어두운 쪽이 다가가는 색조
DEFAULT_HUE_STEP = 10.0   # shade 기본 색조 걸음의 위 한도 (도)
HUE_BUDGET = 36.0         # 기본 걸음일 때 램프 처음 ~ 끝 색조 차 한도. style extract 램프 상한 40° 아래로, RGB 반올림 몫을 남긴다


def auto_hue_step(steps: int) -> float:
   """기본 색조 걸음 : 칸마다 10° 를 넘지 않고, 처음 ~ 끝이 36° 를 넘지 않게. 4칸 10° · 5칸 9° · 6칸 7.2° · 7칸 6°."""
   return round(min(DEFAULT_HUE_STEP, HUE_BUDGET / max(1, steps - 1)), 2)


def _toward(hue: float, target: float, amount: float) -> float:
   """색조를 target 쪽으로 amount 도만큼 짧은 길로 돌린다. target 을 넘어가지 않는다."""
   gap = (target - hue + 180.0) % 360.0 - 180.0
   step = min(abs(gap), amount)
   return (hue + (step if gap >= 0 else -step)) % 360.0


def shade(base: str | RGB, steps: int = 6, hue_step: float | None = None, metal: bool = False, base_index: int | None = None) -> list[RGB]:
   """밑색 하나 → 어두운 쪽부터 밝은 쪽까지 램프 한 줄 (그늘 계산).

   `hue_step` 을 안 주면 `auto_hue_step(steps)` — 칸마다 10° 이하, 처음 ~ 끝 36° 이하.
   옛 기본 20° 는 6칸이면 처음 ~ 끝이 100° 벌어져 `style extract` 가 램프 상한(40°)에 걸려 둘로 갈랐다.
   10° 고정도 6칸이면 50° 라 갈린다 — 그래서 칸 수에 맞춰 줄인다.

   - 밑색은 `base_index` 칸에 그대로 들어간다. 안 주면 가운데(steps // 2).
   - 밝은 칸은 색조를 노랑(60°) 쪽으로, 어두운 칸은 파랑(240°) 쪽으로 칸마다 `hue_step` 도씩 돌린다(어두울수록 차갑게).
     목표 색조를 넘어가지는 않는다. `metal` 이면 방향이 반대다.
   - 밝기는 어두운 끝이 밑색의 40%, 밝은 끝이 남은 몫의 80% 까지. 밝은 쪽은 채도를 반까지 덜어 하얗게 간다.
   - 회색(채도 0)은 색조가 뜻이 없어 밝기만 바뀐다. 아주 밝은 밑색은 위쪽 칸이 같은 색으로 나올 수 있다.
   `palette_ramp` 템플릿 처리기와 `arttool.draw` 가 같이 쓴다.
   """
   if isinstance(steps, bool) or not isinstance(steps, int) or steps < 2:
      raise ArtToolError(f"램프 칸 수는 2 이상 정수다 : {steps}")
   if hue_step is None:
      hue_step = auto_hue_step(steps)
   if not 0 <= hue_step <= 180:
      raise ArtToolError(f"색조 걸음은 0 ~ 180 도다 : {hue_step}")
   index = steps // 2 if base_index is None else base_index
   if not 0 <= index < steps:
      raise ArtToolError(f"밑색 자리가 램프 밖이다 : {index} (칸 수 {steps})")

   r, g, b = parse_hex(base) if isinstance(base, str) else base
   hue, sat, val = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
   hue *= 360.0
   light_target, dark_target = (COOL_HUE, WARM_HUE) if metal else (WARM_HUE, COOL_HUE)

   out: list[RGB] = []
   for i in range(steps):
      offset = i - index
      if offset == 0:
         out.append((int(r), int(g), int(b)))
         continue
      if offset > 0:
         t = offset / (steps - 1 - index)
         h = _toward(hue, light_target, offset * hue_step)
         s, v = sat * (1.0 - 0.5 * t), val + (1.0 - val) * 0.8 * t
      else:
         t = -offset / index
         h = _toward(hue, dark_target, -offset * hue_step)
         s, v = min(1.0, sat + 0.1 * t), val * (1.0 - 0.6 * t)
      fr, fg, fb = colorsys.hsv_to_rgb(h / 360.0, s, v)
      out.append((round(fr * 255), round(fg * 255), round(fb * 255)))
   return out


def ramp_asset_json(ramps: Ramps, names: list[str] | None = None) -> dict:
   """Unity PaletteRampAsset 용. 수치만 담는다."""
   picked = names or ramps.names()
   return {
      "version": 1,
      "name": ramps.name,
      "rampLen": ramps.ramp_len,
      "outline": to_hex(ramps.outline) if ramps.outline else None,
      "ramps": [{"name": n, "colors": [to_hex(c) for c in ramps.ramp(n)]} for n in picked],
   }


# 램프 파일의 본 칸. `save_ramps` 의 덧칸이 이 이름을 덮지 못한다.
RAMP_FILE_KEYS = ("version", "name", "ramp_len", "outline", "ramps")


def save_ramps(path: str | os.PathLike, ramps: Ramps, extra: dict | None = None) -> Path:
   """램프 묶음을 `palettes/` 꼴 JSON 으로 쓴다 (`load_ramps` 의 짝).

   `extra` 는 덧칸(`comment` · `usage` · `hue_step` 등). `load_ramps` 는 모르는 칸을 무시하므로 같이 적어도 읽힌다.
   덧칸이 본 칸 이름과 겹치면 거절한다. 길이가 다른 램프도 쓰기 전에 막는다(읽을 때 터지므로).
   """
   if not ramps.ramps:
      raise ArtToolError("쓸 램프가 하나도 없다")
   lengths = {len(colors) for colors in ramps.ramps.values()}
   if len(lengths) > 1 or lengths != {ramps.ramp_len}:
      raise ArtToolError(f"램프 길이가 ramp_len {ramps.ramp_len} 과 다르다 : {sorted(lengths)}")
   clash = sorted(set(extra or {}) & set(RAMP_FILE_KEYS))
   if clash:
      raise ArtToolError(f"덧칸이 램프 파일 본 칸과 겹친다 : {', '.join(clash)}")

   data = {
      "version": 1,
      "name": ramps.name,
      "ramp_len": ramps.ramp_len,
      "outline": to_hex(ramps.outline) if ramps.outline is not None else None,
      "ramps": {name: [to_hex(c) for c in colors] for name, colors in ramps.ramps.items()},
      **(extra or {}),
   }
   file = Path(path)
   write_json(file, data)
   return file
