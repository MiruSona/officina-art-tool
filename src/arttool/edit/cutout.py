"""`cutout` — 받은 그림의 바탕을 지운다 (설계 4-1).

번지기 : 씨앗 칸에서 4방향으로 퍼지며, 이웃 칸 색이 **씨앗 색과** tol 안이면 지운다.
이웃 색과 견주지 않는 까닭 — 그러데이션 바탕을 따라 그림 안까지 번지는 사고를 막는다.

| --key | 씨앗 색 | 퍼지기 시작하는 칸 |
| --- | --- | --- |
| edge (기본) | 바깥 한 바퀴에서 가장 많은 색 | 바깥 한 바퀴 전부 |
| corner | 네 모서리 색 (다르면 넷 다) | 네 모서리 |
| #RRGGBB | 그 색 | 번지지 않고 그림 전체에서 가까운 칸을 지운다 |

`--shave N` 을 주면 바깥 N 칸 고리를 먼저 지우고, 씨앗 색은 **깎아 낸 고리**에서 잡는다(edge · corner).
번지기는 깎은 뒤 새 가장자리에서 시작한다.

결과 알파는 지운 칸만 0 이 된다. 반투명을 새로 만들지 않는다.
경고는 `checks.warning` 꼴 {rule, ok, detail, items} 이다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..errors import ArtToolError, UsageError
from ..palette import parse_hex, to_hex
from . import list_inputs, plan_outputs

VERSION = 1
# 이만큼 넘게 지웠으면 키가 바탕이 아니라 그림 색이었을 수 있다.
ERASED_WARN_RATIO = 0.9
# 지운 뒤 남은 칸이 이만큼 많은 캔버스 변에 닿으면 배경 그림을 갉은 것으로 본다 (looks_like_background).
BACKGROUND_SIDES = 3
SIDE_SHARE = 0.1           # 변 하나가 「닿았다」 = 그 변 칸의 10% 이상이 남았다 (실물 : 배경 0.22 ~ 1.0, 물건 찌꺼기 ≤ 0.04)
# --shave 씨앗 : 깎아 낸 고리에서 이 몫 이상인 색을 씨앗으로 (많아야 BAND_SEED_MAX 개).
BAND_SEED_SHARE = 0.25
BAND_SEED_MAX = 3


def parse_key(text: str) -> str | tuple[int, int, int]:
   value = str(text).strip()
   if value in ("edge", "corner"):
      return value
   if value.startswith("#"):
      try:
         return parse_hex(value)
      except ArtToolError as exc:
         raise UsageError(f"--key 색을 못 읽었다 : {text} (#RRGGBB 꼴)") from exc
   raise UsageError(f"--key 는 edge · corner · #RRGGBB 중 하나다 : {text}")


def _ring(height: int, width: int, inset: int) -> np.ndarray:
   """inset 칸 안쪽 네모의 바깥 한 바퀴."""
   ring = np.zeros((height, width), dtype=bool)
   y0, y1, x0, x1 = inset, height - 1 - inset, inset, width - 1 - inset
   ring[y0, x0 : x1 + 1] = True
   ring[y1, x0 : x1 + 1] = True
   ring[y0 : y1 + 1, x0] = True
   ring[y0 : y1 + 1, x1] = True
   return ring


def _near(rgb: np.ndarray, seeds: list[tuple[int, int, int]], tol: int) -> np.ndarray:
   """씨앗 색 가운데 하나와 RGB 각 칸 차이가 모두 tol 이하인 칸."""
   hit = np.zeros(rgb.shape[:2], dtype=bool)
   for seed in seeds:
      diff = np.abs(rgb - np.array(seed, dtype=np.int16)).max(axis=2)
      hit |= diff <= tol
   return hit


def _row_runs(passable: np.ndarray) -> tuple[np.ndarray, int]:
   """줄마다 passable 칸이 이어진 토막에 번호를 붙인다 (0 = 못 지나는 칸). 번호 판과 가장 큰 번호."""
   prev = np.zeros_like(passable)
   prev[:, 1:] = passable[:, :-1]
   starts = passable & ~prev
   ids = np.cumsum(starts.ravel()).reshape(passable.shape)
   ids[~passable] = 0
   return ids, int(ids.max())


def _spread(reach: np.ndarray, ids: np.ndarray, top: int) -> np.ndarray:
   """닿은 칸이 하나라도 있는 토막은 토막 전체가 닿는다."""
   hit = np.zeros(top + 1, dtype=bool)
   hit[ids[reach]] = True
   hit[0] = False
   return hit[ids]


def flood(start: np.ndarray, passable: np.ndarray) -> np.ndarray:
   """start 에서 4방향으로 passable 칸만 따라 닿는 칸 (불리언 판).

   한 칸씩 넓히면 큰 그림(2000px 대)에서 수천 번 돌아 몇 초 걸린다. 그래서 가로 토막 · 세로 토막을
   통째로 번갈아 칠한다 — 도는 횟수가 「길이 꺾이는 수」만큼으로 준다. 결과는 한 칸씩 넓힐 때와 같다.
   """
   rows, rows_top = _row_runs(passable)
   cols_t, cols_top = _row_runs(np.ascontiguousarray(passable.T))
   reach = start & passable
   count = int(np.count_nonzero(reach))
   while True:
      reach = _spread(reach, rows, rows_top)
      reach = _spread(np.ascontiguousarray(reach.T), cols_t, cols_top).T
      now = int(np.count_nonzero(reach))
      if now == count:
         return np.ascontiguousarray(reach)
      count = now


def _most_common(rgb: np.ndarray, where: np.ndarray) -> list[tuple[int, int, int]]:
   """where 칸에서 가장 많은 색 하나. 칸이 없으면 빈 목록."""
   if not where.any():
      return []
   colors, counts = np.unique(rgb[where].reshape(-1, 3), axis=0, return_counts=True)
   # 수가 같으면 np.unique 가 정한 순서(색 값 오름차순)의 앞쪽을 고른다 — 늘 같은 답이 나온다.
   return [tuple(int(v) for v in colors[int(np.argmax(counts))])]


def _seeds(rgb: np.ndarray, opaque: np.ndarray, key, band: np.ndarray | None, inset: int) -> list[tuple[int, int, int]]:
   """씨앗 색. rgb · opaque 는 **깎기 전** 그림이다.

   band 는 --shave 로 깎아 낸 고리(없으면 None). 깎은 고리에 불투명 칸이 있으면 씨앗을 거기서 잡는다 —
   깎은 뒤 새 가장자리에서 잡으면 흰 띠 안쪽의 **틀 색**이 씨앗이 되어 틀을 지운다 (실물 버그 1).
   """
   height, width = opaque.shape
   if not isinstance(key, str):
      return [key]
   if key == "corner":
      # 깎았어도 네 모서리 색은 원래 그림의 모서리(깎아 낸 고리 안)에서 먼저 본다
      insets = (0, inset) if band is not None else (inset,)
      for at in insets:
         spots = ((at, at), (at, width - 1 - at), (height - 1 - at, at), (height - 1 - at, width - 1 - at))
         found = []
         for y, x in spots:
            color = tuple(int(v) for v in rgb[y, x])
            if opaque[y, x] and color not in found:
               found.append(color)
         if found:
            return found
      return []
   if band is not None and (band & opaque).any():
      # 깎은 고리가 흰 띠 + 진짜 바탕 두 색이면(위아래만 흰 띠) 둘 다 씨앗이다. 고리의 BAND_SEED_SHARE 이상인 색만 —
      # 깎는 폭이 틀까지 먹어도 틀 색은 고리에서 몫이 작아 씨앗이 안 된다.
      colors, counts = np.unique(rgb[band & opaque].reshape(-1, 3), axis=0, return_counts=True)
      order = np.argsort(-counts, kind="stable")
      total = int(counts.sum())
      found = [tuple(int(v) for v in colors[i]) for i in order if counts[i] >= total * BAND_SEED_SHARE]
      return found[:BAND_SEED_MAX] or _most_common(rgb, band & opaque)
   return _most_common(rgb, _ring(height, width, inset) & opaque)


def _touched_sides(left: np.ndarray) -> int:
   """남은 불투명 칸이 닿은 캔버스 변의 수 (0~4). 변 길이의 SIDE_SHARE 이상 덮여야 닿은 것으로 센다 —
   단색 바탕을 지우고 남은 찌꺼기 몇 칸이 변에 붙은 것은 안 센다."""
   if not left.any():
      return 0
   return sum(int(float(side.mean()) >= SIDE_SHARE) for side in (left[0], left[-1], left[:, 0], left[:, -1]))


def cutout(arr: image.RGBA, key="edge", tol: int = 10, shave: int = 0) -> tuple[image.RGBA, dict]:
   """바탕을 지운 그림과 보고 한 줄. key 는 `parse_key` 가 돌려준 값."""
   height, width = arr.shape[:2]
   if shave * 2 >= min(width, height):
      raise UsageError(f"--shave {shave} 가 그림 {width}x{height} 를 다 깎는다")

   out = arr.copy()
   before = int(np.count_nonzero(arr[:, :, 3] > 0))
   if shave:
      inner = np.zeros((height, width), dtype=bool)
      inner[shave : height - shave, shave : width - shave] = True
      out[~inner] = 0
   else:
      inner = np.ones((height, width), dtype=bool)

   opaque = out[:, :, 3] > 0
   rgb = out[:, :, :3].astype(np.int16)
   seeds = _seeds(arr[:, :, :3].astype(np.int16), arr[:, :, 3] > 0, key, ~inner if shave else None, shave)
   near = _near(rgb, seeds, tol) & opaque if seeds else np.zeros_like(opaque)

   if isinstance(key, str):
      # 이미 투명한 칸도 지나간다. 깎은 띠는 빼야 corner 가 띠를 타고 한 바퀴를 다 돌지 않는다.
      passable = near | (~opaque & inner)
      start = np.zeros_like(opaque)
      if key == "corner":
         for y, x in ((shave, shave), (shave, width - 1 - shave), (height - 1 - shave, shave), (height - 1 - shave, width - 1 - shave)):
            start[y, x] = True
      else:
         start = _ring(height, width, shave)
      erase = flood(start, passable) & opaque
      enclosed = int(np.count_nonzero(near & ~erase))
   else:
      erase = near
      enclosed = 0

   out[erase] = 0
   left = out[:, :, 3] > 0
   erased = before - int(np.count_nonzero(left))
   box = image.bbox(out)
   info = {
      "seeds": [to_hex(s) for s in seeds],
      "erased": erased,
      "opaque_before": before,
      "bbox": list(box) if box else None,
      "enclosed": enclosed,
      "edge_left": int(np.count_nonzero(left & _ring(height, width, shave))),
      # 지운 뒤에도 남은 칸이 닿은 캔버스 변 수. 3 이상이면 바탕이 아니라 그림 전체를 갉았을 수 있다.
      # 캔버스 변 기준이라 --shave 를 주면 늘 0 이다 — 깎은 새 가장자리에는 틀이 닿는 게 정상이고, 깎으라고 한 것은 사람이다.
      "sides_left": _touched_sides(left),
      "shaved": bool(shave),
   }
   return out, info


def looks_like_background(info: dict) -> bool:
   """지운 뒤에도 남은 칸이 캔버스 세 변 이상에 닿았다 — 바탕만 지운 게 아니라 그림(배경)을 갉았다.

   흰 띠 · 단색 바탕 위 물건은 지우고 나면 많아야 두 변(바닥 · 옆)에 닿는다. 마루 · 하늘 배경은 지운 뒤에도
   남은 결이 네 변 · 세 변에 다 닿는다 (실물 버그 2). 지운 칸이 없으면 거짓.
   """
   return bool(info["erased"]) and info["sides_left"] >= BACKGROUND_SIDES


def image_warnings(name: str, info: dict) -> list[dict]:
   """그림 한 장의 경고. 꼴은 `checks.warning` — {rule, ok: false, detail, items: [파일 이름]}."""
   found = []
   if not info["seeds"]:
      found.append(warning("cutout.no_seed", f"{name} : 바깥에 불투명 칸이 없어 지울 바탕 색을 못 찾았다", [name]))
   if info["opaque_before"] and info["erased"] > info["opaque_before"] * ERASED_WARN_RATIO:
      found.append(warning("cutout.erased_most", f"{name} : 90% 넘게 지웠다 ({info['erased']}/{info['opaque_before']}). 키가 그림 색이었을 수 있다", [name]))
   if info["enclosed"]:
      found.append(warning("cutout.enclosed", f"{name} : 바탕 색인데 번지기로 못 닿은 칸 {info['enclosed']}개 (고리 안쪽 등). --key #hex 로 한 번 더", [name]))
   # 깎았으면 새 가장자리에 남은 칸은 대개 틀이다 — 「--shave 를 주라」는 말이 맞지 않는다.
   if info["edge_left"] and not info.get("shaved"):
      found.append(warning("cutout.edge_left", f"{name} : 지운 뒤에도 바깥 변에 닿은 칸 {info['edge_left']}개. 흰 띠가 남았으면 --shave", [name]))
   if looks_like_background(info):
      found.append(warning("cutout.background_like", f"{name} : 지운 뒤에도 남은 칸이 캔버스 {info['sides_left']}변에 닿는다. 배경 그림이면 cutout 을 끈다", [name]))
   return found


def run(args) -> dict:
   key = parse_key(args.key)
   tol, shave = int(args.tol), int(args.shave)
   if not 0 <= tol <= 255:
      raise UsageError(f"--tol 은 0~255 다 : {tol}")
   if shave < 0:
      raise UsageError(f"--shave 는 0 이상이다 : {shave}")

   inputs = list_inputs(args.in_dir)
   outs = plan_outputs(inputs, args.in_dir, args.out_dir)
   rows, warnings = [], []
   for source, target in zip(inputs, outs):
      result, info = cutout(image.load(source), key, tol, shave)
      image.save(target, result)
      rows.append({"file": source.name, "out": str(target), **info})
      warnings += image_warnings(source.name, info)

   return {
      "version": VERSION,
      "status": "warn" if warnings else "ok",
      "key": args.key,
      "tol": tol,
      "shave": shave,
      "images": rows,
      "warnings": warnings,
      "out": str(Path(outs[0]).parent),
   }
