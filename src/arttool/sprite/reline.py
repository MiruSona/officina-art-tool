"""`reline` — 받은 그림의 외곽선을 한 색으로 맞춘다 (2026-10-04 피드백후속설계 3-6).

바깥 고리 = 불투명 칸 중 4방향 이웃(캔버스 밖 포함)에 투명이 있는 칸.

| 인자 | 고르는 칸 |
| --- | --- |
| `--pick dark` (기본) | 고리 칸 중 밝기가 「고리에서 가장 어두운 밝기 + tol」 이하 |
| `--pick all` | 고리 전부 |
| `--scope ring` (기본) | 고른 칸만 바꾼다 |
| `--from #hex[,#hex…]` | 고리 칸 중 RGB 가 그 목록에 든 칸 (`--pick` · `--tol` 과 같이 못 쓴다) |
| `--scope colors` | 고른 칸의 색과 같은 색을 그림 전체에서 바꾼다 (안쪽 선까지). `--from` 이면 고리와 상관없이 목록 색인 칸 전부 |

색은 `--color` > 프로필 `palette.outline`(`--profile` 을 줬을 때만) > 고리의 어두운 칸에서 가장 많은 색.
`--from` 이면 세 번째 길은 「목록에 없는」 고리 칸에서 그 안 가장 어두운 밝기 + 40 이하로 고른다 — 바꿀 색을 다시 고르면 아무것도 안 바뀐다.
프로필 기본값 `#000000` 이 늘 있어서, `--profile` 없이 프로필을 보면 세 번째 길이 영영 안 쓰인다.
알파는 건드리지 않는다. 경고 꼴은 `checks.warning`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..edit import dry_run_fields, is_dry_run, list_inputs, plan_outputs
from ..errors import ArtToolError, UsageError
from ..palette import parse_hex, to_hex
from ..paths import guard_outside
from ..profile import load_profile_args

VERSION = 1
PICKS = ("dark", "all")
SCOPES = ("ring", "colors")
# 합친 색이 이보다 많으면 외곽선이 아니라 음영까지 먹었을 수 있다.
MANY_COLORS = 6
# 선과 옆 면의 밝기(luma 0~255) 차가 이보다 작으면 선이 면에 묻힌다 (1판 설계 4절).
DARK_GAP = 24
MAX_DEPTH = 8


def ring_mask(arr: image.RGBA) -> np.ndarray:
   """불투명 칸 중 4방향 이웃에 투명이 있는 칸. 캔버스 밖은 투명으로 본다."""
   opaque = arr[:, :, 3] > 0
   padded = np.pad(opaque, 1)
   h, w = opaque.shape
   all_near = padded[:h, 1 : w + 1] & padded[2:, 1 : w + 1] & padded[1 : h + 1, :w] & padded[1 : h + 1, 2:]
   return opaque & ~all_near


def _pick(arr: image.RGBA, ring: np.ndarray, pick: str, tol: int) -> tuple[np.ndarray, np.ndarray]:
   """(바꿀 고리 칸, 어두운 고리 칸). 어두운 칸은 색을 고를 때도 쓴다."""
   luma = image.luma(arr)
   darkest = float(luma[ring].min())
   dark = ring & (luma <= darkest + tol)
   if pick == "all":
      return ring, dark
   return dark, dark


def _most_common(arr: image.RGBA, where: np.ndarray) -> tuple[int, int, int]:
   colors, counts = np.unique(arr[:, :, :3][where].reshape(-1, 3), axis=0, return_counts=True)
   # 수가 같으면 np.unique 의 앞쪽(색 값 오름차순) — 늘 같은 답이 나온다.
   return tuple(int(v) for v in colors[int(np.argmax(counts))])


def _color_keys(rgb: np.ndarray) -> np.ndarray:
   keys = rgb.astype(np.uint32)
   return (keys[..., 0] << 16) | (keys[..., 1] << 8) | keys[..., 2]


def reline(arr: image.RGBA, target, pick: str = "dark", scope: str = "ring", tol: int = 40, from_colors=None,
           depth: int = 1, color_dark=None, dark_gap: int = DARK_GAP) -> tuple[image.RGBA, dict]:
   """외곽선을 맞춘 그림과 보고 한 줄. target 이 None 이면 고리에서 고른다.

   from_colors 를 주면 pick 대신 목록 색인 칸을 고른다 — scope ring 은 고리 칸만, colors 는 그림 전체의 불투명 칸.
   target 이 None 이면 목록 밖 고리 칸에서 (그 안 가장 어두운 밝기 + tol 이하) 가장 많은 색을 고른다.
   """
   out = arr.copy()
   if not np.any(arr[:, :, 3] == 0):
      return out, {"changed": 0, "merged_colors": [], "target": to_hex(target) if target else None, "no_alpha": True, "changed_ring": 0, "changed_inner": 0, "changed_dark": 0}
   ring = ring_mask(arr)
   if not ring.any():
      return out, {"changed": 0, "merged_colors": [], "target": to_hex(target) if target else None, "no_alpha": False, "changed_ring": 0, "changed_inner": 0, "changed_dark": 0}

   rgb = arr[:, :, :3]
   keys = _color_keys(rgb)
   opaque = arr[:, :, 3] > 0
   info = {"no_alpha": False}
   if from_colors:
      named = np.isin(keys, _color_keys(np.array(from_colors, dtype=np.uint32)))
      area = opaque if scope == "colors" else ring
      chosen = area & named
      found = set(np.unique(keys[chosen]).tolist())
      info["from_missing"] = [to_hex(c) for c in from_colors if int(_color_keys(np.array(c, dtype=np.uint32))) not in found]
      rest = ring & ~named
      dark = np.zeros_like(ring)
      if rest.any():
         dark = _pick(arr, rest, "dark", tol)[1]   # 가장 어두운 밝기를 목록 밖 고리 칸에서 잰다
   else:
      chosen, dark = _pick(arr, ring, pick, tol)
      if scope == "colors":
         chosen = opaque & np.isin(keys, np.unique(keys[chosen]))

   if target is None and not dark.any():
      return out, {"changed": 0, "merged_colors": [], "target": None, **info, "no_target": True}
   if target is None:
      target = _most_common(arr, dark)

   paint = chosen
   if depth > 1 and scope == "ring":
      allowed = _color_keys(np.array(from_colors, dtype=np.uint32)) if from_colors else np.unique(keys[chosen])
      paint = _grow(chosen, depth_mask(arr, depth) & np.isin(keys, allowed))

   # 칸마다 색 : 안쪽 면 이웃과 밝기가 비슷하면 둘째 색 (1판 설계 4절)
   low = paint & _low_contrast(arr, paint, _luma_of(target), dark_gap)
   colors = np.empty(rgb.shape, dtype=np.uint8)
   colors[...] = target
   if color_dark is not None:
      colors[low] = color_dark
   moved = paint & np.any(rgb != colors, axis=2)
   merged = sorted({to_hex(tuple(int(v) for v in c)) for c in rgb[moved]})
   out[moved, :3] = colors[moved]
   return out, {
      "changed": int(np.count_nonzero(moved)),
      "changed_ring": int(np.count_nonzero(moved & ring)),
      "changed_inner": int(np.count_nonzero(moved & ~ring)),
      "changed_dark": int(np.count_nonzero(moved & low)) if color_dark is not None else 0,
      "merged_colors": merged, "target": to_hex(target), **info,
      "inner_left": _inner_left(keys, opaque, ring, moved) if depth == 1 and scope == "ring" else 0,
      "low_contrast": int(np.count_nonzero(moved & low)) if color_dark is None else 0,
   }


def _near(mask: np.ndarray, dy: int, dx: int) -> np.ndarray:
   """[y, x] 에 mask[y + dy, x + dx] 를 둔 판. 그림 밖은 False."""
   padded = np.pad(mask, 1)
   h, w = mask.shape
   return padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]


STEPS = ((-1, 0), (1, 0), (0, -1), (0, 1))


def depth_mask(arr: image.RGBA, depth: int) -> np.ndarray:
   """투명(그림 밖 포함)에서 4방향 걸음으로 depth 칸 안인 불투명 칸. depth 1 이면 ring_mask 와 같다."""
   left = arr[:, :, 3] > 0
   inside = np.zeros_like(left)
   for _ in range(depth):
      edge = left & ~(_near(left, -1, 0) & _near(left, 1, 0) & _near(left, 0, -1) & _near(left, 0, 1))
      inside |= edge
      left = left & ~edge
   return inside


def _grow(seed: np.ndarray, allowed: np.ndarray) -> np.ndarray:
   """seed 에서 allowed 칸만 밟아 4방향으로 이어진 칸 (seed 포함)."""
   grown = seed.copy()
   while True:
      step = allowed & ~grown & (_near(grown, -1, 0) | _near(grown, 1, 0) | _near(grown, 0, -1) | _near(grown, 0, 1))
      if not step.any():
         return grown
      grown |= step


def _luma_of(color) -> float:
   return float(image.luma(np.array([[[*color, 255]]], dtype=np.uint8))[0, 0])


def _low_contrast(arr: image.RGBA, paint: np.ndarray, line_luma: float, gap: int) -> np.ndarray:
   """안쪽 면 이웃(불투명이고 이번에 안 바뀌는 칸)의 평균 밝기가 선 색과 gap 보다 가까운 칸. 면 이웃이 없으면 False."""
   face = (arr[:, :, 3] > 0) & ~paint
   luma = image.luma(arr).astype(np.float64)
   total = np.zeros(paint.shape, dtype=np.float64)
   count = np.zeros(paint.shape, dtype=np.int32)
   for dy, dx in STEPS:
      near = _near(face, dy, dx)
      total += np.where(near, _near_values(luma, dy, dx), 0.0)
      count += near
   mean = np.divide(total, count, out=np.zeros_like(total), where=count > 0)
   return (count > 0) & (np.abs(mean - line_luma) < gap)


def _near_values(values: np.ndarray, dy: int, dx: int) -> np.ndarray:
   padded = np.pad(values, 1)
   h, w = values.shape
   return padded[1 + dy : 1 + dy + h, 1 + dx : 1 + dx + w]


def _inner_left(keys: np.ndarray, opaque: np.ndarray, ring: np.ndarray, moved: np.ndarray) -> int:
   """바꾼 고리 칸에 4방향으로 붙은, 그 칸의 옛 색과 같은 안쪽 칸 수 (2px 선의 안쪽 줄)."""
   left = np.zeros_like(moved)
   inner = opaque & ~ring & ~moved
   for dy, dx in STEPS:
      left |= inner & _near(moved, dy, dx) & (keys == _near_values(keys, dy, dx))
   return int(np.count_nonzero(left))


def _target(args) -> tuple[int, int, int] | None:
   if getattr(args, "color", None):
      return _parse(args.color, "--color")
   if getattr(args, "profile", None):
      outline = load_profile_args(args).palette.get("outline")
      if outline:        # null · 빈 글이면 「외곽선 색 없음」 — 다음 순서(고리의 어두운 색)로 간다. merge-colors 와 같은 읽기
         return _parse(str(outline), "프로필 palette.outline")
   return None


def _parse(text: str, what: str) -> tuple[int, int, int]:
   try:
      return parse_hex(text)
   except ArtToolError as exc:
      raise UsageError(f"{what} 색을 못 읽었다 : {text} (#RRGGBB 꼴)") from exc


def image_warnings(name: str, info: dict) -> list[dict]:
   found = []
   if info["no_alpha"]:
      found.append(warning("reline.no_alpha", f"{name} : 투명 칸이 없어 바깥 고리가 없다 — 그대로 복사했다", [name]))
   if info.get("no_target"):
      found.append(warning("reline.no_target", f"{name} : --from 밖의 어두운 고리 칸이 없어 바꿀 색을 못 골랐다 — --color 를 준다", [name]))
   missing = info.get("from_missing") or []
   if missing:
      found.append(warning("reline.from_missing", f"{name} : --from 색 {', '.join(missing)} 이 바꿀 자리에 한 칸도 없다 — 색 값 · --scope 를 본다", [name]))
   if len(info["merged_colors"]) > MANY_COLORS:
      hint = "--from 목록을 줄여 본다" if "from_missing" in info else "--tol 을 줄여 본다"
      found.append(warning("reline.many_colors", f"{name} : 한 색으로 합친 색이 {len(info['merged_colors'])}개 — 음영까지 먹었을 수 있다. {hint}", [name]))
   if info.get("inner_left"):
      found.append(warning("reline.inner_left", f"{name} : 바꾼 고리 칸 옆에 같은 옛 색 안쪽 칸 {info['inner_left']}칸이 남았다 — 2px 선이면 --depth 2 를 본다", [name]))
   if info.get("low_contrast"):
      found.append(warning("reline.low_contrast", f"{name} : 바꾼 칸 {info['low_contrast']}칸이 옆 면과 밝기가 비슷해 선이 묻힌다 — --color-dark 를 본다", [name]))
   return found


def _from_colors(text) -> list[tuple[int, int, int]]:
   colors = [_parse(part, "--from") for part in str(text).split(",") if part.strip()]
   if not colors:
      raise UsageError("--from 에 색이 하나 이상 있어야 한다 (#RRGGBB[,#RRGGBB…])")
   return colors


def run(args) -> dict:
   from_text = getattr(args, "from_colors", None)
   pick = getattr(args, "pick", None)
   tol = getattr(args, "tol", None)
   from_colors = None
   if from_text is not None:
      if pick is not None or tol is not None:
         raise UsageError("--from 은 --pick · --tol 과 같이 못 쓴다 (--from 이 바꿀 칸을 정한다)")
      from_colors = _from_colors(from_text)
   if pick is None:
      pick = "dark"
   if tol is None:
      tol = 40
   tol = int(tol)
   scope = getattr(args, "scope", "ring")
   if pick not in PICKS:
      raise UsageError(f"--pick 은 {' · '.join(PICKS)} 중 하나다 : {pick}")
   if scope not in SCOPES:
      raise UsageError(f"--scope 는 {' · '.join(SCOPES)} 중 하나다 : {scope}")
   if not 0 <= tol <= 255:
      raise UsageError(f"--tol 은 0~255 다 : {tol}")
   depth = getattr(args, "depth", None)
   depth = 1 if depth is None else int(depth)
   if not 1 <= depth <= MAX_DEPTH:
      raise UsageError(f"--depth 는 1~{MAX_DEPTH} 다 : {depth}")
   if depth > 1 and scope == "colors":
      raise UsageError("--depth 는 --scope colors 와 같이 못 쓴다 (colors 는 이미 그림 전체를 본다)")
   dark_text = getattr(args, "color_dark", None)
   gap = getattr(args, "dark_gap", None)
   if gap is not None and dark_text is None:
      raise UsageError("--dark-gap 은 --color-dark 와 같이 쓴다")
   color_dark = _parse(dark_text, "--color-dark") if dark_text is not None else None
   gap = DARK_GAP if gap is None else int(gap)
   if not 0 <= gap <= 255:
      raise UsageError(f"--dark-gap 은 0~255 다 : {gap}")
   target = _target(args)
   dry_run = is_dry_run(args)

   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   if Path(args.in_dir).is_dir():
      guard_outside(outs, [args.in_dir])      # 입력 폴더 안에 쓰면 다음 판에 결과를 또 읽는다
   rows, warnings = [], []
   for source, dest in zip(inputs, outs):
      result, info = reline(image.load(source), target, pick, scope, tol, from_colors, depth, color_dark, gap)
      if not dry_run:
         image.save(dest, result)
      warnings += image_warnings(source.name, info)
      info.pop("no_alpha")
      info.pop("no_target", None)
      info.pop("from_missing", None)       # 경고 reline.from_missing 에 싣는다
      info.pop("inner_left", None)         # 경고 reline.inner_left · low_contrast 에 싣는다
      info.pop("low_contrast", None)
      rows.append({"file": source.name, "out": None if dry_run else str(dest), **info})

   return {
      **dry_run_fields(dry_run, outs),
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "pick": pick,
      "scope": scope,
      "tol": tol,
      "from": [to_hex(c) for c in from_colors] if from_colors else None,
      "depth": depth,
      "color_dark": to_hex(color_dark) if color_dark else None,
      "dark_gap": gap if color_dark else None,
      "images": rows,
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
