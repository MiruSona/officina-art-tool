"""`outline` — 외곽선 두르기 (2026-10-06 2판 설계 C1).

셈은 `draw/outline.plan` 이 한다. 이 모듈은 읽기 → (`--grow` 면 투명으로 늘림) → plan → 칸 칠하기 → 저장 껍데기다.
selout 계열의 램프는 프로필 `ramps_file` 에서 읽는다 (`merge-colors --palette` 와 같은 자리). 없으면 UsageError.
`--where outside` 인데 `--grow` 가 없으면 캔버스 끝 밖으로 나간 칸은 못 그린다 — `outline.clipped` 로 알린다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..draw.outline import MODES, WHERE, check_light, plan
from ..edit import dry_run_fields, is_dry_run, list_inputs, plan_outputs
from ..errors import ArtToolError, UsageError
from ..palette import load_ramps
from ..paths import guard_outside
from ..profile import load_profile_args

VERSION = 1


def _options(args) -> tuple[str, str, int, str | None, str, bool]:
   mode = getattr(args, "mode", "black") or "black"
   where = getattr(args, "where", "outside") or "outside"
   width = getattr(args, "width", 1)
   color = getattr(args, "color", None)
   light = getattr(args, "light", "top_left") or "top_left"
   if mode not in MODES:
      raise UsageError(f"--mode 는 {' · '.join(MODES)} 중 하나다 : {mode}")
   if where not in WHERE:
      raise UsageError(f"--where 는 {' · '.join(WHERE)} 중 하나다 : {where}")
   if not isinstance(width, int) or isinstance(width, bool) or not 1 <= width <= 4:
      raise UsageError(f"--width 는 1 ~ 4 정수다 : {width!r}")
   if color is not None and mode != "solid":
      raise UsageError("--color 는 --mode solid 일 때만 쓴다")
   if mode == "solid" and color is None:
      raise UsageError("--mode solid 는 --color #RRGGBB 가 있어야 한다")
   try:
      check_light(light)
   except ArtToolError as exc:
      raise UsageError(f"--light : {exc}") from exc
   return mode, where, width, color, light, bool(getattr(args, "grow", False))


def _ramps(args, mode: str):
   if not mode.startswith("selout"):
      return None
   if not getattr(args, "profile", None):
      raise UsageError(f"--mode {mode} 는 --profile 이 있어야 한다 (프로필 palette.ramps_file 램프로 어둡게 한다)")
   path = load_profile_args(args).ramps_path()
   if path is None:
      raise UsageError(f"--mode {mode} 인데 프로필에 palette.ramps_file 이 없다")
   if not path.is_file():
      raise UsageError(f"프로필이 가리키는 램프 파일이 없다 : {path}")
   return load_ramps(path)


def run(args) -> dict:
   mode, where, width, color, light, grow = _options(args)
   ramps = _ramps(args, mode)
   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   if Path(args.in_dir).is_dir():
      guard_outside(outs, [args.in_dir])

   dry_run = is_dry_run(args)
   rows, clipped, notes_all = [], [], []
   for source, target in zip(inputs, outs):
      arr = image.load(source)
      height, width_px = arr.shape[:2]
      # 늘린 판에서 셈한다. --grow 가 아니면 원래 자리 밖 칸은 버리고 센다.
      padded = np.zeros((height + 2 * width, width_px + 2 * width, 4), dtype=arr.dtype)
      padded[width:width + height, width:width + width_px] = arr
      notes: list = []
      try:
         cells = plan(padded, mode, ramps=ramps, light=light, where=where, color=color, width=width, notes=notes)
      except ArtToolError as exc:
         raise UsageError(str(exc)) from exc
      if grow:
         out, off, lost = padded.copy(), 0, 0
      else:
         out, off = arr.copy(), width
         inside = [(x - off, y - off, c) for x, y, c, _ in cells
                   if 0 <= x - off < width_px and 0 <= y - off < height]
         lost = len(cells) - len(inside)
         cells = [(x, y, c, None) for x, y, c in inside]
         off = 0
      for x, y, c, _ in cells:
         out[y - off, x - off, :3] = c
         out[y - off, x - off, 3] = 255
      if lost:
         clipped.append({"where": source.name, "count": lost})
      for note in notes:
         notes_all.append({**note, "where": source.name})
      if not dry_run:
         image.save(target, out)
      rows.append({"where": source.name, "out": None if dry_run else str(target), "added": len(cells),
                   "size": [int(out.shape[1]), int(out.shape[0])]})

   warnings = []
   if clipped:
      total = sum(item["count"] for item in clipped)
      warnings.append(warning("outline.clipped", f"캔버스 끝에서 {total}칸을 못 그림 — --grow", clipped))
   for rule in sorted({n.get("rule", "note") for n in notes_all}):
      items = [n for n in notes_all if n.get("rule", "note") == rule]
      warnings.append(warning(f"outline.{rule}", f"외곽선 셈이 알린 일 : {rule}", items))
   return {
      **dry_run_fields(dry_run, outs),
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "mode": mode,
      "where": where,
      "width": width,
      "grow": grow,
      "images": rows,
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
