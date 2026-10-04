"""화풍 뽑기 ① 주요 색 팔레트 (설계 9-3 ①).

차례 : 잡색 합치기 → 검정 빼기 → 몫 셈 · 버리기 → 맞닿은 색끼리 램프로 묶기 → 램프 길이 맞추기 → 전체 상한 → 색조 걸음.

색은 안에서 정수 열쇠 하나(`r << 16 | g << 8 | b`)로 다룬다. 투명 칸은 -1.
그림마다 「한 장 요약」(`stats_of` : 색별 칸 수 · 맞닿은 색 쌍 수)만 쥐고 그림 배열은 바로 놓아 준다 —
수백 장을 한꺼번에 들고 있으면 메모리가 수 GB 로 커진다(실물 #12).
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from .. import palette
from ..checks import LOW_SAT, hue_gap, hue_sat, luma
from ..checks.outline import BLACK_MAX
from ..checks.ramp import measure_ramp

DROP_SHARE = 0.002      # 몫이 이보다 작고
DROP_IMAGES = 2         # 이 장 수 미만에만 나온 색은 버린다
LINK_RATIO = 0.05       # 맞닿은 쌍 수 ≥ 적게 쓰인 쪽 칸 수 × 이 값이면 잇는다 (실측)
LINK_HUE = 35.0         # 잇는 두 색의 색조 차 상한 (도)
HUE_SPAN = 40.0         # 한 램프 안 처음 ~ 끝 색조 차 상한 (도). 이웃끼리만 보면 분홍 → 베이지 → 노랑이 사슬로 이어진다 (실물 #7)
DROPPED_SHOWN = 64      # 보고 · 견본에 적는 버린 색 수
SAMPLE_SIDE = 256       # 도트가 아닌 그림을 재료로 쓸 때(--force) 이 긴 변까지 가까운 칸 뽑기로 줄인다
SAMPLE_QUANT = 8        # 그때 RGB 각 칸을 이 걸음으로 반올림한다 (색 수만 가지 → 수천 가지)

# 램프 이름 : 가운데 칸 색조 → 이름. (끝 각도, 이름) 을 차례로 본다
HUE_NAMES = ((15, "red"), (45, "orange"), (70, "yellow"), (165, "green"), (195, "cyan"),
             (255, "blue"), (290, "purple"), (345, "pink"), (360, "red"))


def to_rgb(key: int) -> tuple[int, int, int]:
   return (key >> 16) & 255, (key >> 8) & 255, key & 255


def to_hex(key: int) -> str:
   return palette.to_hex(to_rgb(key))


def is_black(key: int) -> bool:
   """검정 · 거의 검정 (각 칸 ≤ BLACK_MAX). 외곽선 검사의 「순흑」 과 같은 문턱."""
   return max(to_rgb(key)) <= BLACK_MAX


def key_map(arr: np.ndarray) -> np.ndarray:
   """그림 → 색 열쇠 판. 알파가 0 인 칸은 -1 (검사들의 「불투명 = 알파 > 0」 과 같다)."""
   rgb = arr[:, :, :3].astype(np.int64)
   keys = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
   keys[arr[:, :, 3] == 0] = -1
   return keys


def sample_keys(arr: np.ndarray, side: int = SAMPLE_SIDE, quant: int = SAMPLE_QUANT) -> np.ndarray:
   """도트가 아닌 그림의 줄인 색 열쇠 판. 긴 변이 side 를 넘으면 가까운 칸 뽑기(nearest)로 줄이고,
   RGB 를 quant 걸음으로 반올림한다(0 과 255 는 그대로). 정확한 색이 아니라 「어림」 이다."""
   h, w = arr.shape[:2]
   step = max(1, math.ceil(max(h, w) / side))
   small = arr[::step, ::step]
   rgb = small[:, :, :3].astype(np.int64)
   rgb = np.minimum(255, (rgb + quant // 2) // quant * quant)
   keys = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
   keys[small[:, :, 3] == 0] = -1
   return keys


def _luma(key: int) -> float:
   return float(luma(np.array(to_rgb(key))))


# --- 한 장 요약 ---


def stats_of(keys: np.ndarray) -> dict:
   """색 열쇠 판 → 한 장 요약. 판은 안 쥔다.

   돌려주는 것 : colors · counts (색별 칸 수) · pairs · pair_counts (4방향으로 맞닿은 서로 다른 두 색, `작은 << 24 | 큰`)
   — 모두 int64 numpy 배열이고 colors · pairs 는 정렬돼 있다.
   """
   colors, counts = np.unique(keys[keys >= 0], return_counts=True)
   packed = []
   for a, b in ((keys[:, :-1], keys[:, 1:]), (keys[:-1], keys[1:])):
      ok = (a >= 0) & (b >= 0) & (a != b)
      lo, hi = np.minimum(a[ok], b[ok]), np.maximum(a[ok], b[ok])
      packed.append((lo << 24) | hi)
   pairs, pair_counts = np.unique(np.concatenate(packed), return_counts=True)
   return {"colors": colors.astype(np.int64), "counts": counts.astype(np.int64),
           "pairs": pairs.astype(np.int64), "pair_counts": pair_counts.astype(np.int64)}


def _lookup(values: np.ndarray, table: dict[int, int]) -> np.ndarray:
   """values 안의 색을 table 대로 바꾼 새 배열. 없는 색은 그대로."""
   if not table or values.size == 0:
      return values
   src = np.array(sorted(table), dtype=np.int64)
   dst = np.array([table[int(k)] for k in src], dtype=np.int64)
   at = np.clip(np.searchsorted(src, values), 0, len(src) - 1)
   hit = src[at] == values
   out = values.copy()
   out[hit] = dst[at[hit]]
   return out


def _sum_by(keys: np.ndarray, weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   uniq, inverse = np.unique(keys, return_inverse=True)
   return uniq, np.bincount(inverse.ravel(), weights=weights, minlength=len(uniq)).astype(weights.dtype)


def remap_stats(stats: dict, table: dict[int, int]) -> dict:
   """한 장 요약의 색을 table 대로 바꾼다. 같은 색이 된 맞닿은 쌍은 사라진다(바꾼 판에서 다시 센 것과 같다)."""
   if not table:
      return stats
   colors, counts = _sum_by(_lookup(stats["colors"], table), stats["counts"])
   lo = _lookup(stats["pairs"] >> 24, table)
   hi = _lookup(stats["pairs"] & 0xFFFFFF, table)
   ok = lo != hi
   packed = (np.minimum(lo[ok], hi[ok]) << 24) | np.maximum(lo[ok], hi[ok])
   pairs, pair_counts = _sum_by(packed, stats["pair_counts"][ok])
   return {"colors": colors, "counts": counts, "pairs": pairs, "pair_counts": pair_counts}


def _as_stats(items: list) -> list[dict]:
   """판 목록도 받는다 (부품 시험 · 한 장 셈용)."""
   return [i if isinstance(i, dict) else stats_of(i) for i in items]


def _pixel_counts(stats: list[dict]) -> Counter:
   if not stats:
      return Counter()
   colors, counts = _sum_by(np.concatenate([s["colors"] for s in stats]), np.concatenate([s["counts"] for s in stats]))
   return Counter(dict(zip(colors.tolist(), counts.tolist())))


# --- 1. 잡색 합치기 ---


def near_pairs(keys: list[int], max_delta: int) -> list[tuple[int, int, int]]:
   """색 열쇠 쌍 (a, b, 차이) 중 RGB 각 칸 차이의 최댓값 ≤ max_delta 인 것. 검사 ⑤ 와 같은 셈이다.

   색을 (max_delta + 1) 크기 상자에 나눠 이웃 상자끼리만 견준다 — 수만 가지 색도 메모리가 안 터진다.
   검사 쪽(`measure_near_colors`)은 색이 아주 많으면 건너뛸 수 있어서, 화풍 뽑기는 상한 없는 이 셈을 따로 쓴다.
   """
   if len(keys) < 2:
      return []
   colors = np.array([to_rgb(k) for k in keys], dtype=np.int32)
   step = max_delta + 1
   boxes: dict[tuple, list[int]] = {}
   for index, box in enumerate(map(tuple, (colors // step).tolist())):
      boxes.setdefault(box, []).append(index)
   out = []
   for box, members in boxes.items():
      near = [i for dr in (-1, 0, 1) for dg in (-1, 0, 1) for db in (-1, 0, 1)
              for i in boxes.get((box[0] + dr, box[1] + dg, box[2] + db), ())]
      mine, others = np.array(members), np.array(near)
      gap = np.abs(colors[mine][:, None, :] - colors[others][None, :, :]).max(axis=-1)
      for i, j in zip(*np.nonzero(gap <= max_delta)):
         a, b = int(mine[i]), int(others[j])
         if a < b:
            out.append((keys[a], keys[b], int(gap[i, j])))
   return out


def merge_noise(maps: list, max_delta: int) -> dict[int, int]:
   """RGB 각 칸 차이 ≤ max_delta 인 색을 많이 쓰인 쪽으로 합친다. 돌려주는 것 : {합쳐진 색 : 남은 색}.

   많이 쓰인 색부터 「남는 색」으로 정하고, 뒤 색은 가까운 남는 색이 있으면 그리로 간다(사슬로 멀리 끌려가지 않는다).
   """
   counts = _pixel_counts(_as_stats(maps))
   if len(counts) < 2:
      return {}
   near: dict[int, list[tuple[int, int]]] = {}
   for a, b, delta in near_pairs(sorted(counts), max_delta):
      near.setdefault(a, []).append((b, delta))
      near.setdefault(b, []).append((a, delta))

   kept: set[int] = set()
   table: dict[int, int] = {}
   for key in sorted(counts, key=lambda k: (-counts[k], k)):
      targets = [(other, delta) for other, delta in near.get(key, ()) if other in kept]
      if not targets:
         kept.add(key)
         continue
      table[key] = min(targets, key=lambda t: (-counts[t[0]], t[1], t[0]))[0]
   return table


# --- 2. 몫 셈 ---


def usage_of(maps: list) -> tuple[dict[int, float], dict[int, int], Counter]:
   """(색 → 몫, 색 → 나온 장 수, 색 → 칸 수). 몫은 장마다 비율을 낸 뒤 더하고 장 수로 나눈다 — 큰 그림 한 장이 다 먹지 않게."""
   every = _as_stats(maps)
   stats = [s for s in every if s["counts"].size]
   if not stats:
      return {}, {}, Counter()
   keys = np.concatenate([s["colors"] for s in stats])
   share = np.concatenate([s["counts"] / s["counts"].sum() for s in stats])
   colors, total_share = _sum_by(keys, share)
   _colors, images = _sum_by(keys, np.ones(len(keys), dtype=np.int64))
   n = max(1, len(every))
   return ({int(k): float(v) / n for k, v in zip(colors, total_share)},
           {int(k): int(v) for k, v in zip(colors, images)}, _pixel_counts(stats))


def pick_outline(pixels: Counter) -> int | None:
   """외곽선 색(후보) = 가장 많이 쓰인 검정 · 거의 검정. 없으면 None."""
   blacks = [k for k in pixels if is_black(k)]
   if not blacks:
      return None
   return max(blacks, key=lambda k: (pixels[k], -k))


# --- 3. 램프로 묶기 ---


def touching_pairs(maps: list, keep: set[int]) -> Counter:
   """4방향으로 맞닿은 서로 다른 두 색 쌍 수 (둘 다 keep 안). 열쇠 (작은 색, 큰 색)."""
   stats = _as_stats(maps)
   if not stats or not keep:
      return Counter()
   packed, counts = _sum_by(np.concatenate([s["pairs"] for s in stats]), np.concatenate([s["pair_counts"] for s in stats]))
   keep_arr = np.array(sorted(keep), dtype=np.int64)
   alive = np.isin(packed >> 24, keep_arr) & np.isin(packed & 0xFFFFFF, keep_arr)
   return Counter({(p >> 24, p & 0xFFFFFF): c for p, c in zip(packed[alive].tolist(), counts[alive].tolist())})


def _hue_ok(a: int, b: int) -> bool:
   """잇는 두 색의 색조가 맞나. 둘 다 회색이면 색조를 안 보고, 한쪽만 회색이면 안 잇는다(회색의 색조는 뜻이 없다)."""
   ha, sa = hue_sat(to_rgb(a))
   hb, sb = hue_sat(to_rgb(b))
   if sa < LOW_SAT and sb < LOW_SAT:
      return True
   if sa < LOW_SAT or sb < LOW_SAT:
      return False
   return hue_gap(ha, hb) <= LINK_HUE


def hue_span(hues: list[float]) -> float:
   """색조 여럿을 다 덮는 가장 짧은 호의 각도 (0 ~ 360). 360 에서 빈 틈 가장 큰 것을 뺀다."""
   if len(hues) < 2:
      return 0.0
   ordered = sorted(h % 360.0 for h in hues)
   gaps = [b - a for a, b in zip(ordered, ordered[1:])] + [ordered[0] + 360.0 - ordered[-1]]
   return 360.0 - max(gaps)


def join_arcs(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
   """색조 호 둘 (시작, 너비 — 시작에서 반시계로 너비만큼) 을 다 덮는 가장 짧은 호. 가장 짧은 호는 둘 중 한 시작에서 시작한다."""
   from_a = (a[0], max(a[1], (b[0] - a[0]) % 360.0 + b[1]))
   from_b = (b[0], max(b[1], (a[0] - b[0]) % 360.0 + a[1]))
   return min(from_a, from_b, key=lambda arc: (arc[1], arc[0]))


def group_colors(keep: set[int], pairs: Counter, pixels: Counter) -> list[list[int]]:
   """맞닿은 색끼리 이은 덩어리들. 덩어리 안은 밝기 순(어두운 → 밝은).

   강하게 맞닿은 쌍부터 잇고, 이으면 덩어리의 처음 ~ 끝 색조 차가 HUE_SPAN 을 넘는 쌍은 안 잇는다 (회색 덩어리는 색조를 안 본다).
   """
   parent = {k: k for k in keep}
   arcs: dict[int, tuple[float, float] | None] = {}     # 덩어리 색조가 든 호 (시작, 너비). 회색 덩어리는 None
   for k in keep:
      hue, sat = hue_sat(to_rgb(k))
      arcs[k] = (hue, 0.0) if sat >= LOW_SAT else None

   def root(k: int) -> int:
      while parent[k] != k:
         parent[k] = parent[parent[k]]
         k = parent[k]
      return k

   def strength(item) -> tuple:
      (a, b), count = item
      return (-count / max(1, min(pixels[a], pixels[b])), a, b)

   for (a, b), count in sorted(pairs.items(), key=strength):
      if count < LINK_RATIO * min(pixels[a], pixels[b]) or not _hue_ok(a, b):
         continue
      ra, rb = root(a), root(b)
      if ra == rb:
         continue
      joined = None
      if arcs[ra] is not None and arcs[rb] is not None:
         joined = join_arcs(arcs[ra], arcs[rb])
         if joined[1] > HUE_SPAN:
            continue
      parent[ra] = rb
      arcs[rb] = joined
   groups: dict[int, list[int]] = {}
   for k in sorted(keep):
      groups.setdefault(root(k), []).append(k)
   return [sorted(g, key=lambda k: (_luma(k), k)) for g in groups.values()]


# --- 4. 램프 길이 맞추기 ---


def _split(group: list[int], length: int) -> list[list[int]]:
   """2L 이상이면 밝기 틈이 가장 큰 곳에서 둘로 나눈다. 나눈 조각도 다시 본다."""
   if len(group) < 2 * length:
      return [group]
   lumas = [_luma(k) for k in group]
   gaps = [b - a for a, b in zip(lumas, lumas[1:])]
   cut = int(np.argmax(gaps)) + 1
   return _split(group[:cut], length) + _split(group[cut:], length)


def _shrink(group: list[int], length: int, usage: dict[int, float], moves: list[tuple[int, int, str]]) -> list[int]:
   """L 보다 길면 밝기가 가장 가까운 이웃 둘을 합친다(적게 쓰인 쪽 → 많이 쓰인 쪽)."""
   group = list(group)
   while len(group) > length:
      lumas = [_luma(k) for k in group]
      i = min(range(len(group) - 1), key=lambda j: (lumas[j + 1] - lumas[j], j))
      a, b = group[i], group[i + 1]
      small, big = (a, b) if (usage.get(a, 0.0), -a) < (usage.get(b, 0.0), -b) else (b, a)
      moves.append((small, big, "ramp_len"))
      usage[big] = usage.get(big, 0.0) + usage.pop(small, 0.0)
      group.remove(small)
   return group


def fit_length(groups: list[list[int]], length: int, usage: dict[int, float], moves: list[tuple[int, int, str]]) -> list[dict]:
   """덩어리 → 길이 L 램프들. 짧으면 밝은 쪽 끝 색을 되풀이해 채운다(설계 16-1 9번 확정).

   돌려주는 것 : [{colors (열쇠 L 개), padded (채운 칸 수)}]. 합친 색은 moves 에 (합쳐진 색, 남은 색, 까닭) 으로 더한다.
   """
   out = []
   for group in groups:
      for piece in _split(group, length):
         real = _shrink(piece, length, usage, moves)
         padded = length - len(real)
         out.append({"colors": real + [real[-1]] * padded, "padded": padded})
   return out


# --- 5 · 6. 상한 · 이름 · 색조 걸음 ---


def ramp_name(colors: list[int]) -> str:
   """가운데 칸 색으로 이름을 붙인다. 채도가 낮으면 gray."""
   hue, sat = hue_sat(to_rgb(colors[len(colors) // 2]))
   if sat < LOW_SAT:
      return "gray"
   return next(name for end, name in HUE_NAMES if hue < end)


def _named(ramps: list[dict]) -> None:
   seen: Counter = Counter()
   for ramp in ramps:
      real = ramp["colors"][: len(ramp["colors"]) - ramp["padded"]]
      base = ramp_name(real)
      seen[base] += 1
      ramp["name"] = base if seen[base] == 1 else f"{base}_{seen[base]}"


def cap_ramps(ramps: list[dict], max_colors: int, outline: int | None) -> tuple[list[dict], list[dict]]:
   """전체 색 수가 max_colors 를 넘으면 몫이 작은 램프부터 뺀다. (남은 것, 뺀 것)."""
   kept = sorted(ramps, key=lambda r: (-r["usage"], r["colors"][0]))
   removed = []

   def total() -> int:
      colors = {k for r in kept for k in r["colors"]}
      return len(colors) + (1 if outline is not None and outline not in colors else 0)

   while kept and total() > max_colors:
      removed.append(kept.pop())
   return kept, removed


def hue_step_of(ramps: list[dict], outline: int | None) -> float | None:
   """램프마다 이웃 칸 색조 차의 중앙값, 그 중앙값. 잴 수 있는 램프가 없으면 None."""
   outline_rgb = to_rgb(outline) if outline is not None else None
   medians = []
   for ramp in ramps:
      steps = measure_ramp([to_rgb(k) for k in ramp["colors"]], outline_rgb)["hue_steps"]
      if steps:
         medians.append(float(np.median(steps)))
   return round(float(np.median(medians)), 1) if medians else None


def _merge_report(moves: list[tuple[int, int, str]], kept: set[int]) -> list[dict]:
   """합치기 기록을 「마지막에 남은 색」 까지 따라가 정리한다 (리뷰 R2 의심 ④).

   잡색 a → b 뒤에 b 가 램프 길이로 c 에 합쳐졌으면 a → c 로 적는다. 끝 색이 팔레트에 없으면(상한으로 뺀 램프 ·
   버린 색 · 안 쓰는 검정 후보) 그 줄은 뺀다 — 그래서 from → to 를 그대로 색 바꾸기 표로 쓸 수 있다.
   """
   step = {a: b for a, b, _why in moves}
   out = []
   for a, _b, why in moves:
      end, seen = a, {a}
      while end in step and step[end] not in seen:
         end = step[end]
         seen.add(end)
      if end in kept and a not in kept:
         out.append({"from": to_hex(a), "to": to_hex(end), "why": why})
   return sorted(out, key=lambda m: (m["why"], m["from"]))


# --- 한 번에 ---


def build_palette(maps: list, length: int, max_colors: int, max_delta: int, black_outline: bool,
                  line_color: int | None = None) -> dict:
   """한 장 요약(또는 판) 목록 → 팔레트 한 벌. 램프가 하나도 안 남으면 `ramps` 가 빈 목록이다.

   검정 · 거의 검정은 외곽선 판정과 상관없이 늘 램프에서 빼고, 가장 많이 쓰인 것을 `outline_candidate` 로 둔다 (실물 #6).
   `black_outline` 이면 그 후보가 `outline` 이 되고 다른 검정은 그리로 합친다.
   `line_color`(한 색 선 solid 의 외곽선 색 열쇠)를 주면 그 색이 `outline` 이 되고 램프에서 빠진다 — `black_outline` 보다 앞선다.

   돌려주는 것 : ramps [{name, colors (열쇠), padded, usage}] · outline (열쇠 | None) · outline_candidate · usage {hex: 몫} ·
   hue_step · noise_merged · merged [{from, to, why}] · merge_table {from: to} · padded [{ramp, cells}] · singles [이름] ·
   dropped [{color, usage, images}] · removed_ramps · removed_colors · colors
   """
   stats = _as_stats(maps)
   noise = merge_noise(stats, max_delta)
   moves = [(a, b, "noise") for a, b in sorted(noise.items())]
   stats = [remap_stats(s, noise) for s in stats]
   usage, images, pixels = usage_of(stats)

   candidate = pick_outline(pixels)
   blacks = {k for k in usage if is_black(k)}
   outline = candidate if black_outline else None
   moves += [(k, candidate, "black") for k in sorted(blacks) if k != candidate]
   line = {line_color} if line_color is not None and line_color in usage else set()
   if line:
      outline = line_color
   dropped = sorted((k for k in usage if usage[k] < DROP_SHARE and images[k] < DROP_IMAGES and k not in blacks | line),
                    key=lambda k: (-usage[k], k))
   keep = set(usage) - set(dropped) - blacks - line

   ramps = []
   if keep:
      groups = group_colors(keep, touching_pairs(stats, keep), pixels)
      ramps = fit_length(groups, length, usage, moves)
   for ramp in ramps:
      ramp["usage"] = round(sum(usage.get(k, 0.0) for k in set(ramp["colors"])), 4)
   ramps, removed = cap_ramps(ramps, max_colors, outline)
   _named(ramps + removed)

   kept_keys = {k for r in ramps for k in r["colors"]} | ({outline} if outline is not None else set())
   merged = _merge_report(moves, kept_keys)
   removed_colors = {k for r in removed for k in r["colors"]} - kept_keys
   return {
      "ramps": ramps,
      "outline": outline,
      "outline_candidate": candidate,
      "usage": {to_hex(k): round(usage[k], 4) for k in sorted(kept_keys, key=lambda k: (-usage.get(k, 0.0), k)) if k in usage},
      "hue_step": hue_step_of(ramps, outline),
      "noise_merged": len(noise),
      "merged": merged,
      "merge_table": {m["from"]: m["to"] for m in merged},
      "padded": [{"ramp": r["name"], "cells": r["padded"]} for r in ramps if r["padded"]],
      "singles": [r["name"] for r in ramps if len(set(r["colors"])) == 1],
      "dropped": [{"color": to_hex(k), "usage": round(usage[k], 5), "images": images[k]} for k in dropped[:DROPPED_SHOWN]],
      "dropped_count": len(dropped),
      "dropped_keys": dropped,
      "removed_ramps": [{"name": r["name"], "colors": [to_hex(k) for k in r["colors"]], "usage": r["usage"]} for r in removed],
      "removed_colors": len(removed_colors),
      "colors": len(kept_keys),
   }


def top_colors(maps: list, count: int = 16) -> list[dict]:
   """배경 그림 색 요약 : 몫 큰 순 count 개 [{color, usage}]."""
   usage, _images, _pixels = usage_of(maps)
   best = sorted(usage, key=lambda k: (-usage[k], k))[:count]
   return [{"color": to_hex(k), "usage": round(usage[k], 4)} for k in best]


def percentile(values: list[float], q: float) -> float | None:
   if not values:
      return None
   return round(float(np.percentile(values, q)), 4)


def ceil_to(value: float, digits: int) -> float:
   scale = 10 ** digits
   return math.ceil(value * scale - 1e-9) / scale
