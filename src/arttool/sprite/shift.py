"""`shift` — 색을 HSV 로 옮긴다 (2026-10-06 1판 설계 1절).

색 하나마다 `colorsys.rgb_to_hsv` → 색상 + hue/360 (돌림) · 채도 × sat · 명도(V) + light → 0~1 로 자르기 → RGB 반올림.
`check` 의 `hue_sat` 와 같은 HSV 다. `--pick` 을 주면 그 색(정확히 같은 RGB)만 옮긴다. 알파와 투명 칸은 그대로다.
색 표 `{원래 색: 새 색}` 를 `merge.apply_table` 로 한 번에 입힌다.

옮긴 색은 대개 프로필 `ramps_file` 밖으로 나간다 — 게임 팔레트에 맞출 그림이면 뒤에 `merge-colors` 로 램프에 붙인다.
"""

from __future__ import annotations

import colorsys
import math
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run, list_inputs, plan_outputs
from ..errors import UsageError
from ..paths import guard_outside
from .merge import _hex, _merged, _opaque_keys, apply_table
from .tint import parse_colors

VERSION = 1


def _key(rgb: tuple[int, int, int]) -> int:
   return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def shift_rgb(rgb: tuple[int, int, int], hue: float, sat: float, light: float) -> tuple[tuple[int, int, int], bool]:
   """색 하나를 옮긴 RGB 와, S · V 가 0~1 밖으로 나가 잘렸는지."""
   h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
   s2, v2 = s * sat, v + light
   clipped = not (0.0 <= s2 <= 1.0 and 0.0 <= v2 <= 1.0)
   r, g, b = colorsys.hsv_to_rgb((h + hue / 360.0) % 1.0, min(max(s2, 0.0), 1.0), min(max(v2, 0.0), 1.0))
   return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255))), clipped


def _numbers(args) -> tuple[float, float, float]:
   hue = float(getattr(args, "hue", 0) or 0)
   sat = float(1.0 if getattr(args, "sat", None) is None else args.sat)
   light = float(getattr(args, "light", 0) or 0)
   for name, value in (("--hue", hue), ("--sat", sat), ("--light", light)):
      if not math.isfinite(value):
         raise UsageError(f"{name} 는 유한한 수다 : {value}")
   if not -360 <= hue <= 360:
      raise UsageError(f"--hue 는 -360~360 이다 : {hue:g}")
   if sat < 0:
      raise UsageError(f"--sat 은 0 이상이다 : {sat:g}")
   if not -1 <= light <= 1:
      raise UsageError(f"--light 는 -1~1 이다 : {light:g}")
   if hue == 0 and sat == 1 and light == 0:
      raise UsageError("바꿀 것이 없다 — --hue · --sat · --light 중 하나는 기본값(0 · 1 · 0)이 아니어야 한다")
   return hue, sat, light


def _picked(args) -> list[tuple[int, int, int]] | None:
   text = getattr(args, "pick", None)
   if text is None:
      return None
   try:
      return parse_colors(text)
   except UsageError as exc:
      raise UsageError(str(exc).replace("--colors", "--pick")) from exc


def run(args) -> dict:
   hue, sat, light = _numbers(args)
   pick = _picked(args)
   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   # 입력 폴더 안에 쓰지 않는다 (다음 판에 결과를 또 읽는다)
   if Path(args.in_dir).is_dir():
      guard_outside(outs, [args.in_dir])

   dry_run = is_dry_run(args)
   pick_keys = None if pick is None else {_key(c) for c in pick}
   rows, merged, clipped, missing, gray = [], [], [], [], []
   for source, target in zip(inputs, outs):
      arr = image.load(source)
      keys, n = np.unique(_opaque_keys(arr), return_counts=True)
      counts = dict(zip(keys.tolist(), n.tolist()))
      chosen = [k for k in counts if pick_keys is None or k in pick_keys]
      if pick_keys is not None and len(chosen) < len(pick_keys):
         missing.append(source.name)
      table, hit_clip, hit_gray = {}, False, False
      for k in chosen:
         rgb = ((k >> 16) & 255, (k >> 8) & 255, k & 255)
         new, cut = shift_rgb(rgb, hue, sat, light)
         hit_clip |= cut
         hit_gray |= hue != 0 and max(rgb) == min(rgb)
         if _key(new) != k:
            table[k] = _key(new)
      if hit_clip:
         clipped.append(source.name)
      if hit_gray:
         gray.append(source.name)
      # 둘 이상의 원래 색이 같은 새 색이 되면 명암이 뭉갤 수 있다. 바뀌지 않은 고른 색과 겹쳐도 같다.
      chosen_set = set(chosen)
      landing = [table.get(k, k) for k in chosen] + [k for k in counts if k not in chosen_set]
      if len(set(landing)) < len(landing):
         merged.append(source.name)
      if not dry_run:
         image.save(target, apply_table(arr, table))
      rows.append({"file": source.name, "out": None if dry_run else str(target),
                   "changed": int(sum(counts[k] for k in table)), "colors": _merged(table, counts)})

   warnings = []
   if merged:
      warnings.append(warning("shift.merged", f"원래 색 둘 이상이 같은 새 색이 됐다 — 명암이 뭉갤 수 있다 : {', '.join(merged)}", merged))
   if clipped:
      warnings.append(warning("shift.clipped", f"--sat · --light 로 채도나 명도가 0~1 밖으로 나가 잘렸다 : {', '.join(clipped)}", clipped))
   if missing:
      wanted = ", ".join(_hex(_key(c)) for c in pick)
      warnings.append(warning("shift.pick_missing", f"--pick 색({wanted}) 중 그림에 없는 색이 있다 : {', '.join(missing)}", missing))
   if gray:
      warnings.append(warning("shift.gray", f"채도 0(회색) 색은 --hue 로 색상이 안 움직인다 : {', '.join(gray)}", gray))

   return {
      **dry_run_fields(dry_run, outs),
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "hue": hue,
      "sat": sat,
      "light": light,
      "pick": None if pick is None else [_hex(_key(c)) for c in pick],
      "images": rows,
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
