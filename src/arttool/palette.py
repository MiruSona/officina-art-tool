"""팔레트 램프. 램프 JSON 읽기 · 정확일치 스냅 · LUT PNG 만들기."""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from . import image
from .errors import ArtToolError

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
