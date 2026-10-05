"""`merge-colors` — 가까운 색을 합쳐 색 수를 줄인다 (2026-10-05 피드백 판 다음 1순위).

| 인자 | 합치는 길 |
| --- | --- |
| `--tol N` | RGB 각 칸 차이의 최댓값 ≤ N 인 색을 많이 쓰인 쪽으로. 셋 다 안 주면 N = 프로필 `near_colors.max_delta` |
| `--max-colors N` | 가장 가까운 짝부터 되풀이해 N 색까지. `--tol` 을 같이 주면 그 안의 짝만 |
| `--palette` | 프로필 `ramps_file` 색 중 가장 가까운 색으로 (`palette.snap_nearest` 와 같은 셈). 위 둘과 같이 못 쓴다 |

- 합친 색은 늘 **있던 색 중 많이 쓰인 쪽**이다. 평균색을 만들지 않는다. 칸 수가 같으면 색 열쇠가 작은 쪽.
- 지킬 색 = `--keep` + (`--profile` 을 줬을 때만) `palette.outline`(안 적었으면 기본 `#000000`) · 램프 색.
  남는 색으로만 쓰이고, 지킨 색끼리도 안 합친다. `--palette` 에서는 `--keep` 색도 갈 곳이 된다.
- `--tol` 이 있으면(`--max-colors` 와 같이 줘도) 원래 색 → 남는 색 거리가 늘 tol 안이다.
- 기본은 입력 전체 칸 수로 표 하나를 만들어 모든 장에 건다(프레임마다 같은 잡색이 같은 색으로 간다). `--per-image` 면 장마다.
- 알파 > 0 칸만 세고 바꾼다(`image.count_colors` 와 같은 셈). 알파 값 · 투명 칸 RGB 는 그대로.
- 색 열쇠는 `r << 16 | g << 8 | b` 정수. 거리 셈은 int64 라 넘치지 않는다.
경고 꼴은 `checks.warning`. 보고의 `merge_table` 은 `style extract` 와 같은 `{합쳐진 색: 남은 색}` 꼴이다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import LOW_SAT, hue_gap, hue_sat, warning
from ..checks.pixels import close_pair_arrays
from ..edit import list_inputs, plan_outputs
from ..errors import ArtToolError, UsageError
from ..palette import load_ramps, parse_hex, to_hex
from ..paths import guard_outside, guard_overwrite, jailed_output
from ..profile import load_profile_args
from ..style.ramps import LINK_HUE
from .recolor import position_diff

VERSION = 1
SHEET_SCALE = 4
# --max-colors 만(문턱 없이) 쓸 때 모든 짝을 견준다. 색이 이보다 많으면 짝이 수백만이라 --tol 로 먼저 거르게 한다.
FULL_PAIRS_MAX = 2048
# --tol 짝 수 상한. 잰 값(2026-10-05) : 6.5만 색 고른 잡색 그림 tol 4 → 9만 짝 · tol 8 → 60만 짝 · tol 16 → 415만 짝,
# 8.7만 색 기울기 그림 tol 4 → 169만 짝. 그 판까지는 돌고 tol 16 급(수백만)은 막는 값.
PAIRS_MAX = 2_000_000
HUE_JUMPS_SHOWN = 5      # 경고 detail · items 에 싣는 짝 수


def _rgb(key: int) -> tuple[int, int, int]:
   return (key >> 16) & 255, (key >> 8) & 255, key & 255


def _hex(key: int) -> str:
   return to_hex(_rgb(key))


def _opaque_keys(arr: image.RGBA) -> np.ndarray:
   """알파 > 0 칸의 색 열쇠 (칸 차례대로, 겹침 있음)."""
   rgb = arr[:, :, :3][arr[:, :, 3] > 0].astype(np.int64)
   return (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]


def color_counts(arrs: list[image.RGBA]) -> dict[int, int]:
   """여러 장의 색 열쇠 → 칸 수 (합). 불투명 칸만."""
   counts: dict[int, int] = {}
   for arr in arrs:
      keys, n = np.unique(_opaque_keys(arr), return_counts=True)
      for k, c in zip(keys.tolist(), n.tolist()):
         counts[k] = counts.get(k, 0) + c
   return counts


def _rgb_array(keys: list[int]) -> np.ndarray:
   arr = np.array(keys, dtype=np.int64)
   return np.stack([(arr >> 16) & 255, (arr >> 8) & 255, arr & 255], axis=1)


# --- 표 만들기 ---


def _tol_pairs(keys: list[int], tol: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
   """tol 안의 짝 (a, b 색 번호, 거리). 짝이 PAIRS_MAX 를 넘으면 거절한다 — 그 뒤 고리가 파이썬이라 수백만이면 몇 분 걸린다."""
   found = close_pair_arrays(_rgb_array(keys), tol, PAIRS_MAX)
   if found is None:
      raise ArtToolError(f"색 {len(keys)}가지에 --tol {tol} 이면 짝이 {PAIRS_MAX:,}개를 넘는다 — 색이 너무 많다. "
                         "--tol 을 줄이거나 먼저 --max-colors · --palette 로 줄인다")
   return found


def plan_tol(counts: dict[int, int], tol: int, keep: set[int]) -> dict[int, int]:
   """문턱 합치기. `style.ramps.merge_noise` 와 같은 규칙에 지킬 색을 더했다.

   지킨 색이 먼저 「남는 색」이 되고, 나머지는 많이 쓰인 색부터 본다 — 가까운 남는 색이 있으면 그리로(많이 쓰인 쪽 · 가까운 쪽 ·
   열쇠 작은 쪽 차례로 고른다), 없으면 저도 남는 색이 된다. 남는 색에만 붙으므로 사슬로 멀리 끌려가지 않는다(원래 색 → 남는 색 ≤ tol).
   """
   keys = sorted(counts)
   if len(keys) < 2:
      return {}
   a, b, gap = _tol_pairs(keys, tol)
   near: dict[int, list[tuple[int, int]]] = {}
   for i, j, delta in zip(a.tolist(), b.tolist(), gap.tolist()):
      near.setdefault(keys[i], []).append((keys[j], delta))
      near.setdefault(keys[j], []).append((keys[i], delta))

   kept = {k for k in keys if k in keep}
   table: dict[int, int] = {}
   for key in sorted(keys, key=lambda k: (-counts[k], k)):
      if key in keep:
         continue
      targets = [(other, delta) for other, delta in near.get(key, ()) if other in kept]
      if not targets:
         kept.add(key)
         continue
      table[key] = min(targets, key=lambda t: (-counts[t[0]], t[1], t[0]))[0]
   return table


def _pairs(keys: list[int], tol: int | None) -> tuple[np.ndarray, np.ndarray]:
   """견줄 짝 (a, b 색 번호). tol 이 있으면 그 안의 짝만, 없으면 모든 짝."""
   if tol is not None:
      a, b, _gap = _tol_pairs(keys, tol)
      return a, b
   if len(keys) > FULL_PAIRS_MAX:
      raise ArtToolError(f"색이 {len(keys)}가지라 --max-colors 만으로는 짝이 너무 많다 (한도 {FULL_PAIRS_MAX}) — --tol 을 같이 준다")
   a, b = np.triu_indices(len(keys), k=1)
   return a.astype(np.int64), b.astype(np.int64)


def plan_max(counts: dict[int, int], target: int, keep: set[int], tol: int | None) -> tuple[dict[int, int], int]:
   """목표 색 수 합치기. 돌려주는 것 : ({합쳐진 색 : 끝에 남은 색}, 남은 색 수).

   짝을 (체비셰프 거리 · 유클리드 제곱 · 열쇠) 차례로 한 번 늘어놓고 앞에서부터 합친다. 남는 쪽 색은 안 바뀌므로
   짝 거리를 다시 잴 일이 없다. 칸 수는 합칠 때마다 남는 쪽에 더해 다음 짝에서 「많이 쓰인 쪽」 을 다시 가린다.
   색마다 「무리」(그 색으로 모인 원래 색들)를 들고 다닌다. tol 이 있으면 진 쪽 무리가 **모두** 이긴 색과 tol 안일 때만
   합친다 — 아니면 0→4→8 처럼 사슬을 타고 tol 보다 먼 색으로 간다. 그 짝은 건너뛰고, 목표에 못 닿으면 남은 수로 알린다.
   """
   keys = sorted(counts)
   alive = len(keys)
   if alive <= target:
      return {}, alive
   a, b = _pairs(keys, tol)
   rgb = _rgb_array(keys)
   if a.size:
      locked = np.isin(a, [i for i, k in enumerate(keys) if k in keep]) & np.isin(b, [i for i, k in enumerate(keys) if k in keep])
      a, b = a[~locked], b[~locked]
   diff = rgb[a] - rgb[b]
   cheb = np.abs(diff).max(axis=1) if a.size else np.zeros(0, dtype=np.int64)
   square = (diff * diff).sum(axis=1) if a.size else np.zeros(0, dtype=np.int64)
   order = np.lexsort((b, a, square, cheb))

   live = dict(counts)
   groups: dict[int, list[int]] = {k: [k] for k in keys}     # 살아 있는 색 → 그 색으로 모인 원래 색들 (저 포함)
   # 무리의 RGB 칸마다 (최솟값, 최댓값). 무리 안 가장 먼 색까지 거리를 구성원을 다 안 돌고 잰다
   boxes = {k: (rgb[i], rgb[i]) for i, k in enumerate(keys)}
   for i in order.tolist():
      if alive <= target:
         break
      ka, kb = keys[int(a[i])], keys[int(b[i])]
      if ka not in groups or kb not in groups:
         continue
      if ka in keep:
         win, lose = ka, kb
      elif kb in keep:
         win, lose = kb, ka
      else:
         win, lose = (ka, kb) if (live[ka], -ka) >= (live[kb], -kb) else (kb, ka)
      if tol is not None and _farthest(boxes[lose], win) > tol:
         continue
      (lo_w, hi_w), (lo_l, hi_l) = boxes[win], boxes.pop(lose)
      boxes[win] = (np.minimum(lo_w, lo_l), np.maximum(hi_w, hi_l))
      groups[win] += groups.pop(lose)
      live[win] += live.pop(lose)
      alive -= 1

   table = {member: end for end, members in groups.items() for member in members if member != end}
   return table, alive


def _farthest(box: tuple[np.ndarray, np.ndarray], to: int) -> int:
   """무리의 원래 색들에서 to 까지 체비셰프 거리의 최댓값. 칸마다 끝값(최솟값 · 최댓값)이 가장 멀어서 상자만 보면 된다."""
   lo, hi = box
   point = np.array(_rgb(to), dtype=np.int64)
   return int(max(np.abs(point - lo).max(), np.abs(hi - point).max()))


def plan_palette(counts: dict[int, int], allowed: set[int]) -> dict[int, int]:
   """허락된 색 밖의 색을 가장 가까운 허락된 색으로 (유클리드 제곱, 같으면 열쇠 작은 쪽 — `snap_nearest` 와 같다)."""
   targets = sorted(allowed)
   if not targets:
      return {}
   pool = _rgb_array(targets)
   table = {}
   for key in sorted(counts):
      if key in allowed:
         continue
      diff = pool - np.array(_rgb(key), dtype=np.int64)
      table[key] = targets[int(np.argmin((diff * diff).sum(axis=1)))]
   return table


# --- 적용 ---


def apply_table(arr: image.RGBA, table: dict[int, int]) -> image.RGBA:
   """표를 한 번만 건다. 자리는 원본 색으로 찾으므로 A→B, B→C 가 A→C 로 번지지 않는다. 알파는 그대로."""
   out = arr.copy()
   opaque = arr[:, :, 3] > 0
   if not table or not opaque.any():
      return out
   keys = _opaque_keys(arr)
   src = np.array(sorted(table), dtype=np.int64)
   dst = np.array([table[int(k)] for k in src], dtype=np.int64)
   at = np.clip(np.searchsorted(src, keys), 0, len(src) - 1)
   hit = src[at] == keys
   new = np.where(hit, dst[at], keys)
   out[opaque, 0] = (new >> 16) & 255
   out[opaque, 1] = (new >> 8) & 255
   out[opaque, 2] = new & 255
   return out


def hue_jumps(table: dict[int, int]) -> list[dict]:
   """합친 짝 중 색조 차가 램프 경계(LINK_HUE)를 넘는 것. 한쪽이라도 회색(LOW_SAT 미만)이면 색조를 안 따진다."""
   found = []
   for src, dst in sorted(table.items()):
      hs, ss = hue_sat(_rgb(src))
      hd, sd = hue_sat(_rgb(dst))
      if ss < LOW_SAT or sd < LOW_SAT:
         continue
      gap = hue_gap(hs, hd)
      if gap > LINK_HUE:
         found.append({"from": _hex(src), "to": _hex(dst), "hue_diff": round(gap, 1)})
   return found


# --- 인자 ---


def _colors_arg(text, what: str) -> list[int]:
   out = []
   for part in str(text).split(","):
      if not part.strip():
         continue
      try:
         r, g, b = parse_hex(part)
      except ArtToolError as exc:
         raise UsageError(f"{what} 색을 못 읽었다 : {part.strip()} (#RRGGBB 꼴)") from exc
      out.append((r << 16) | (g << 8) | b)
   if not out:
      raise UsageError(f"{what} 에 색이 하나 이상 있어야 한다 (#RRGGBB[,#RRGGBB…])")
   return out


def _mode(args) -> tuple[str, int | None, int | None, str | None]:
   """(길, tol, max_colors, tol 이 어디서 왔나). 같이 못 쓰는 인자는 여기서 거절한다."""
   tol, max_colors = getattr(args, "tol", None), getattr(args, "max_colors", None)
   if getattr(args, "palette", False):
      if tol is not None or max_colors is not None:
         raise UsageError("--palette 는 --tol · --max-colors 와 같이 못 쓴다 (램프 색이 갈 곳을 정한다)")
      return "palette", None, None, None
   if tol is not None and not 0 <= int(tol) <= 255:
      raise UsageError(f"--tol 은 0~255 다 : {tol}")
   if max_colors is not None and int(max_colors) < 1:
      raise UsageError(f"--max-colors 는 1 이상이다 : {max_colors}")
   if max_colors is not None:
      return "max_colors", None if tol is None else int(tol), int(max_colors), None if tol is None else "--tol"
   if tol is not None:
      return "tol", int(tol), None, "--tol"
   # 셋 다 없으면 check 의 near_colors 와 같은 문턱 — 「check 가 짚은 짝 = 합치는 짝」
   return "tol", int(load_profile_args(args).warn("near_colors")["max_delta"]), None, "near_colors.max_delta"


def _profile_colors(args, need_ramps: bool) -> tuple[set[int], set[int]]:
   """(지킬 색, 램프 색). `--profile` 을 줬을 때만 본다 — 안 주면 아무 색도 저절로 지키지 않는다.

   프로필을 주면 그 프로필의 `palette.outline` 을 지킨다. 프로필 파일에 outline 을 안 적었어도 기본값 `#000000` 이
   그 프로필의 값이므로 순흑이 지켜진다(`profile show` 로 보이는 값과 같다). 안 지키려면 프로필에 `outline: null` 을 적는다.
   """
   if not getattr(args, "profile", None):
      if need_ramps:
         raise UsageError("--palette 는 --profile 이 있어야 한다 (프로필 palette.ramps_file 색으로 보낸다)")
      return set(), set()
   prof = load_profile_args(args)
   keep: set[int] = set()
   outline = prof.palette.get("outline")
   if outline:
      keep.add(_colors_arg(outline, "프로필 palette.outline")[0])
   ramps: set[int] = set()
   path = prof.ramps_path()
   if path is None:
      if need_ramps:
         raise UsageError("--palette 인데 프로필에 palette.ramps_file 이 없다")
   elif not path.is_file():
      raise UsageError(f"프로필이 가리키는 램프 파일이 없다 : {prof.palette.get('ramps_file')}")
   else:
      ramps = {(r << 16) | (g << 8) | b for r, g, b in load_ramps(path).colors()}
   return keep | ramps, ramps


def _plan(mode: str, counts: dict[int, int], tol, max_colors, keep: set[int], ramps: set[int]) -> tuple[dict[int, int], int]:
   if mode == "palette":
      table = plan_palette(counts, ramps | keep)
      return table, len(set(counts) - set(table))
   if mode == "max_colors":
      return plan_max(counts, max_colors, keep, tol)
   table = plan_tol(counts, tol, keep)
   return table, len(counts) - len(table)


def _merged(table: dict[int, int], counts: dict[int, int]) -> list[dict]:
   return [{"from": _hex(s), "to": _hex(d), "count": int(counts[s])} for s, d in sorted(table.items(), key=lambda t: (-counts[t[0]], t[0]))]


def _scope_warnings(label: str, table: dict, left: int, max_colors, keep_present: int, items: list) -> list[dict]:
   found = []
   if not table:
      found.append(warning("merge.no_change", f"{label} : 합칠 색이 없어 그대로다", items))
   if max_colors is not None and left > max_colors:
      found.append(warning("merge.target_unreached",
                           f"{label} : {left}색에서 멈췄다 (목표 {max_colors}) — 지킨 색 {keep_present}개 · --tol 안 짝만 합친다", items))
   jumps = hue_jumps(table)
   if jumps:
      shown = ", ".join(f"{j['from']}→{j['to']} ({j['hue_diff']}°)" for j in jumps[:HUE_JUMPS_SHOWN])
      found.append(warning("merge.hue_jump",
                           f"{label} : 색조가 {LINK_HUE:.0f}° 넘게 다른 색끼리 {len(jumps)}짝을 합쳤다 — 다른 램프가 섞였을 수 있다 : {shown}",
                           jumps[:HUE_JUMPS_SHOWN]))
   return found


def run(args) -> dict:
   mode, tol, max_colors, tol_from = _mode(args)
   keep_given = _colors_arg(args.keep, "--keep") if getattr(args, "keep", None) else []
   protected, ramps = _profile_colors(args, mode == "palette")
   keep = protected | set(keep_given)
   per_image = bool(getattr(args, "per_image", False))
   dry_run = bool(getattr(args, "dry_run", False))
   scale = int(getattr(args, "scale", SHEET_SCALE) or SHEET_SCALE)
   if scale < 1:
      raise UsageError(f"--scale 은 1 이상이다 : {scale}")

   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   sheet_path = jailed_output(args.sheet) if getattr(args, "sheet", None) else None
   # 아무것도 쓰기 전에 : 비교판이 결과 · 원본을 덮지 않고, 입력 폴더 안에도 안 쓴다(다음 판에 결과를 또 읽는다)
   if sheet_path is not None:
      guard_overwrite([sheet_path], [*outs, *inputs], "--sheet")
   if Path(args.in_dir).is_dir():
      guard_outside(outs, [args.in_dir])
      guard_outside([sheet_path], [args.in_dir], "--sheet")

   arrs = [image.load(source) for source in inputs]
   all_counts = color_counts(arrs)
   warnings: list[dict] = []
   missing = [_hex(k) for k in keep_given if k not in all_counts]
   if missing:
      warnings.append(warning("merge.keep_missing", f"--keep 색 {', '.join(missing)} 이 그림에 한 칸도 없다 — 색 값을 본다", missing))

   names = [source.name for source in inputs]
   shared_table = None
   if not per_image:
      shared_table, left = _plan(mode, all_counts, tol, max_colors, keep, ramps)
      warnings += _scope_warnings("입력 전체", shared_table, left, max_colors, len(keep & set(all_counts)), names)

   rows, board, results = [], [], []
   for source, dest, arr in zip(inputs, outs, arrs):
      counts = color_counts([arr])
      if per_image:
         table, left = _plan(mode, counts, tol, max_colors, keep, ramps)
         warnings += _scope_warnings(source.name, table, left, max_colors, len(keep & set(counts)), [source.name])
      else:
         table = {k: v for k, v in shared_table.items() if k in counts}
      result = apply_table(arr, table)
      results.append(result)
      row = {
         "file": source.name,
         "out": None if dry_run else str(dest),
         "colors_before": len(counts),
         "colors_after": image.count_colors(result),
         "changed": int(sum(counts[k] for k in table)),
         "position_diff": position_diff(arr, result),
      }
      if per_image:
         row["merge_table"] = {_hex(s): _hex(d) for s, d in sorted(table.items())}
         row["merged"] = _merged(table, counts)
      rows.append(row)
      board += [arr, result]

   if not dry_run:
      for dest, result in zip(outs, results):
         image.save(dest, result)
      if sheet_path is not None:
         image.save(sheet_path, image.contact_sheet(board, scale, cols=2))

   status = "warn" if warnings else "ok"
   if any(r["position_diff"] for r in rows):
      status = "fail"
   return {
      "version": VERSION,
      "status": status,
      "mode": mode,
      "tol": tol,
      "tol_from": tol_from,
      "max_colors": max_colors,
      "per_image": per_image,
      "keep": sorted(_hex(k) for k in keep),
      "dry_run": dry_run,
      "colors_before": len(all_counts),
      "colors_after": len(color_counts(results)),
      "merge_table": None if shared_table is None else {_hex(s): _hex(d) for s, d in sorted(shared_table.items())},
      "merged": None if shared_table is None else _merged(shared_table, all_counts),
      "images": rows,
      "sheet": None if sheet_path is None or dry_run else str(sheet_path),
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
