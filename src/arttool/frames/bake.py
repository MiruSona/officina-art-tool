"""`frames bake` — 프레임 폴더를 한 번에 굽는다 (4-다).

처리 순서는 고정이다 : ① 발 줄 맞추기 → ② 정한 칸을 기준 그림으로 덮기 → ③ 같은 상자로 자르기 → ④ 띠 → ⑤ gif.
발 줄을 먼저 맞춰야 마스크 자리가 프레임마다 같은 몸 부위에 걸린다. 순서를 바꾸는 인자는 없다.
거절 검사(크기 · 상자 · gif 색 수)를 다 마친 뒤에 쓴다 — 거절이면 파일이 하나도 안 남게.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run, list_inputs, plan_outputs
from ..errors import UsageError
from ..paths import guard_not_folder, guard_outside, guard_overwrite, jailed_output

VERSION = 1

MAX_FRAMES = 512        # 믿을 수 없는 폴더에서 수만 장을 읽지 않게
MAX_SCALE = 64
GIF_DURATION = 110      # 한 장 ms
GIF_MAX_TOTAL_PIXELS = 4 * image.MAX_PIXELS   # gif 모든 장을 합친 픽셀 상한 (한 장 상한의 4배)
NUM_RE = re.compile(r"(\d+)")


def natural_key(path: Path) -> list:
   """`f2` < `f10` 이 되게 숫자 마디는 수로 견준다. 대소문자는 안 가린다."""
   return [int(part) if part.isdigit() else part.casefold() for part in NUM_RE.split(path.stem)]


def foot_row(arr: image.RGBA) -> int | None:
   """맨 아래 불투명 줄의 y. 빈 그림이면 None. (normalize 와 같은 image.bbox 를 쓴다)"""
   box = image.bbox(arr)
   return None if box is None else box[3] - 1


def shift_y(arr: image.RGBA, dy: int) -> tuple[image.RGBA, int]:
   """그림을 dy 만큼 세로로 옮긴다(+ 가 아래). 캔버스 밖으로 나간 불투명 칸 수도 돌려준다."""
   height = arr.shape[0]
   out = np.zeros_like(arr)
   if dy == 0:
      return arr.copy(), 0
   if abs(dy) >= height:
      return out, int(np.count_nonzero(arr[:, :, 3]))
   if dy > 0:
      out[dy:] = arr[:height - dy]
      lost = arr[height - dy:]
   else:
      out[:height + dy] = arr[-dy:]
      lost = arr[:-dy]
   return out, int(np.count_nonzero(lost[:, :, 3]))


def scaled(arr: image.RGBA, scale: int) -> image.RGBA:
   return arr if scale == 1 else np.repeat(np.repeat(arr, scale, axis=0), scale, axis=1)


def _parse_foot(text: str | None) -> int | str | None:
   if text is None or text == "auto":
      return text
   try:
      return int(text)
   except ValueError:
      raise UsageError(f"--foot 은 정수나 auto 다 : {text}") from None


def _parse_crop(text: str | None, width: int, height: int) -> tuple[int, int, int, int] | str | None:
   """`x,y,w,h` 를 (x0, y0, x1, y1) 로. 캔버스를 벗어나면 거절."""
   if text is None or text == "union":
      return text
   try:
      x, y, w, h = (int(v) for v in text.split(","))
   except ValueError:
      raise UsageError(f"--crop 은 x,y,w,h 나 union 이다 : {text}") from None
   if w <= 0 or h <= 0 or x < 0 or y < 0 or x + w > width or y + h > height:
      raise UsageError(f"--crop 상자가 캔버스({width}x{height}) 밖이다 : {text}")
   return x, y, x + w, y + h


def _limit(pixels: int, cap: int, what: str) -> None:
   """키운 그림을 만들기 전에 셈으로만 크기를 본다. 넘으면 거절(종료 2)."""
   if pixels > cap:
      raise UsageError(f"{what} 가 너무 크다 : {pixels} 픽셀 (한도 {cap})")


def _output(text: str | None, suffix: str, flag: str) -> Path | None:
   if not text:
      return None
   if not str(text).lower().endswith(suffix):
      raise UsageError(f"{flag} 는 {suffix} 로 끝나야 한다 : {text}")
   return guard_not_folder(jailed_output(text))


def run(args) -> dict:
   source = Path(args.in_dir)
   if not source.is_dir():
      raise UsageError(f"--in 은 프레임 PNG 폴더여야 한다 : {args.in_dir}")
   inputs = sorted(list_inputs(source), key=natural_key)
   if len(inputs) > MAX_FRAMES:
      raise UsageError(f"프레임이 너무 많다 : {len(inputs)} 장 (한도 {MAX_FRAMES})")
   if args.cover_from and not args.cover:
      raise UsageError("--cover-from 은 --cover 와 같이 쓴다")
   if not args.gif and (args.duration is not None or args.loop is not None):
      raise UsageError("--duration · --loop 은 --gif 와 같이 쓴다")
   scale = args.scale
   if not 1 <= scale <= MAX_SCALE:
      raise UsageError(f"--scale 은 1~{MAX_SCALE} 이다 : {scale}")
   duration = GIF_DURATION if args.duration is None else args.duration
   loop = 0 if args.loop is None else args.loop
   if duration <= 0 or loop < 0:
      raise UsageError("--duration 은 1 이상, --loop 은 0 이상이다")
   if args.gif:
      image.check_gif_duration(duration, len(inputs))
   foot = _parse_foot(args.foot)

   # 쓸 자리 : 프레임 PNG(같은 이름) · 띠 · gif. 서로 · 입력과 겹치면 거절
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   strip_path = _output(args.strip, ".png", "--strip")
   gif_path = _output(args.gif, ".gif", "--gif")
   reads = [*inputs, *(Path(p) for p in (args.cover, args.cover_from) if p)]
   if strip_path is not None:
      guard_overwrite([strip_path], outs, "--strip")
   if gif_path is not None:
      guard_overwrite([gif_path], [*outs, strip_path], "--gif")
   writes = [*outs, strip_path, gif_path]
   guard_overwrite(writes, reads)
   guard_outside(writes, [args.in_dir])

   frames = [image.load(p) for p in inputs]
   height, width = frames[0].shape[:2]
   for path, arr in zip(inputs, frames):
      if arr.shape != frames[0].shape:
         raise UsageError(f"프레임 크기가 서로 다르다 : {inputs[0].name} {width}x{height} · {path.name} {arr.shape[1]}x{arr.shape[0]}")
   crop = _parse_crop(args.crop, width, height)
   warnings = []

   # ① 발 줄
   shifts = [0] * len(frames)
   if foot is not None:
      target = foot_row(frames[0]) if foot == "auto" else foot
      if target is None:
         raise UsageError(f"--foot auto : 첫 프레임 {inputs[0].name} 이 비었다")
      if not 0 <= target < height:
         raise UsageError(f"--foot 은 0~{height - 1} 이다 : {target}")
      clipped = []
      for i, arr in enumerate(frames):
         row = foot_row(arr)
         shifts[i] = 0 if row is None else target - row
         frames[i], lost = shift_y(arr, shifts[i])
         if lost:
            clipped.append(inputs[i].stem)
      if clipped:
         warnings.append(warning("frames.foot_clipped", f"발 줄을 맞추다 캔버스 밖으로 나간 칸이 있는 프레임 {len(clipped)}장", clipped))

   # ② 덮기 — 마스크 알파 > 0 칸을 기준 그림의 같은 칸으로(알파 포함 통째)
   covered = [None] * len(frames)
   if args.cover:
      mask = image.load(args.cover)
      base = image.load(args.cover_from) if args.cover_from else frames[0].copy()
      for what, arr in (("--cover", mask), ("--cover-from", base)):
         if arr.shape != frames[0].shape:
            raise UsageError(f"{what} 크기 {arr.shape[1]}x{arr.shape[0]} 가 프레임 {width}x{height} 와 다르다")
      sel = mask[:, :, 3] > 0
      for i, arr in enumerate(frames):
         # 둘 다 알파 0 인 칸은 RGB 가 달라도 같은 칸(보이는 차이가 없다)
         differ = np.any(arr[sel] != base[sel], axis=1) & ~((arr[sel][:, 3] == 0) & (base[sel][:, 3] == 0))
         covered[i] = int(np.count_nonzero(differ))
         arr[sel] = base[sel]

   # ③ 자르기
   if crop == "union":
      boxes = [b for b in (image.bbox(a) for a in frames) if b is not None]
      if not boxes:
         raise UsageError("--crop union : 모든 프레임이 비었다")
      crop = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
   if crop is not None:
      x0, y0, x1, y1 = crop
      frames = [a[y0:y1, x0:x1].copy() for a in frames]

   # ④ ⑤ 크기 · gif 색 수 거절을 쓰기 전에 본다 — 크기는 셈으로만 구한다(키운 그림을 만들기 전에)
   fh, fw = frames[0].shape[:2]
   if strip_path is not None:
      _limit(fw * scale * len(frames) * fh * scale, image.MAX_PIXELS, f"띠 {fw * scale * len(frames)}x{fh * scale}")
   if gif_path is not None:
      _limit(fw * scale * fh * scale, image.MAX_PIXELS, f"gif 한 장 {fw * scale}x{fh * scale}")
      _limit(len(frames) * fw * fh * scale * scale, GIF_MAX_TOTAL_PIXELS, f"gif 전체 {len(frames)}장 × {fw * scale}x{fh * scale}")
   soft = image.save_gif(frames, gif_path, duration, loop=loop, scale=scale, write=False) if gif_path is not None else 0

   # 쓰는 순서 : 프레임 PNG → 띠 → gif (검사는 위에서 다 끝났다)
   dry_run = is_dry_run(args)
   if not dry_run:
      for path, arr in zip(outs, frames):
         image.save(path, arr)
      if strip_path is not None:
         image.save(strip_path, image.strip([scaled(a, scale) for a in frames]))
      if gif_path is not None:
         image.save_gif(frames, gif_path, duration, loop=loop, scale=scale)
   gif = None
   if gif_path is not None:
      if soft:
         warnings.append(warning("frames.gif_alpha_cut", f"반투명 칸 {soft} 개 — GIF 는 알파 {image.GIF_ALPHA_CUT} 밑을 투명, 위를 불투명으로 바꿨다", [soft]))
      gif = {"path": None if dry_run else str(gif_path), "frames": image.gif_frame_count(frames), "duration": duration, "loop": loop}

   rows = [{"name": p.stem, "shift_y": s, "covered": c} for p, s, c in zip(inputs, shifts, covered)]
   return {
      **dry_run_fields(dry_run, [w for w in writes if w is not None]),
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "frames": len(frames),
      "size": [fw, fh],
      "crop": None if crop is None else {"x": crop[0], "y": crop[1], "w": crop[2] - crop[0], "h": crop[3] - crop[1]},
      "images": rows,
      "gif": gif,
      "warnings": warnings,
      # dry-run 은 쓴 것이 없으니 out 이 None (쓸 자리는 would_write 에)
      "out": None if dry_run else {"frames": str(Path(outs[0]).parent), "strip": str(strip_path) if strip_path else None,
                                   "gif": str(gif_path) if gif_path else None},
   }
