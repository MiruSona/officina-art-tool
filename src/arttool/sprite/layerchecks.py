"""`layers check` 7판 검사 — 장 수 · 기준점 · 마스크 합집합 · 안쪽 구멍 · 전 판 견줌 · 겹끼리 같은 색 (설계 2026-10-07 2절).

`layerops.run_check` 가 `Extra` 하나를 만들어 그림마다 `item()` 을, 끝에 `finish()` 를 부른다.
새 인자를 안 주고 새 칸(`anchor`)도 없으면 아무 일도 안 한다 — 보고가 예전과 바이트까지 같다.

- 경고 한 줄 꼴은 `layerops.warning` 그대로 : `{rule, ok: false, detail, items}`. items 는 [x, y] 좌표.
- 마스크 겹(kind: mask)은 그리는 겹이 아니라 기준점 · 구멍 · 색 견줌에서 빠진다. 마스크 합집합만 마스크 겹을 본다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import image, layerset
from ..edit import fill as fill_mod
from ..errors import UsageError
from ..palette import to_hex
from ..pieces import labels
from .layerops import (
   _anchor_xy, _coverage, _items, _names, _near_colors, _opaque, _points, _read_raw, _scan_variants, _stack, mask_base, warning,
)

ANCHOR_TOL_MAX = 64
HOLES_MAX = 64          # 구멍 덩이 목록은 큰 것부터 이만큼만 보고에 싣는다
SHARED_TOL = 8          # 사례 7 의 흰 반사 · 흰 내용물은 몇 단계 다른 흰색이었다
SHARED_TOL_MAX = 64
SHARED_COLORS_MAX = 256  # 한 겹 색이 이보다 많으면 그 짝은 건너뛴다 (색 × 색 표가 커진다)
SHARED_SHOW = 8          # 경고 글에 싣는 색 수


def _int_range(value, name: str, low: int, high: int) -> int:
   if not low <= int(value) <= high:
      raise UsageError(f"{name} 은 {low}~{high} 다 : {value}")
   return int(value)


class Extra:
   """7판 검사 묶음. 인자 검사는 만들 때(그림을 읽기 전에) 다 끝낸다."""

   def __init__(self, args, folder: Path, ls: layerset.LayerSet, items: list[str], inferred: bool = False, open_before=None):
      self.ls = ls
      self.folder = folder
      self.items = items
      # 장 수 : --counts 또는 맨 폴더면 늘 (맨 폴더는 겹마다 장 수가 달라도 읽히므로 한 줄로 알린다)
      self.counts = bool(getattr(args, "counts", False)) or inferred
      if getattr(args, "counts", False) and ls.picks:
         raise UsageError("--counts : 변형 묶음(사전 꼴 items)은 장 수가 뜻이 없다 — variants 칸을 본다")
      tol = getattr(args, "anchor_tol", None)
      if tol is not None and ls.anchor is None:
         raise UsageError("--anchor-tol 은 layers.json 에 anchor 칸이 있을 때만 쓴다")
      self.anchor_tol = _int_range(tol, "--anchor-tol", 0, ANCHOR_TOL_MAX) if tol is not None else 0
      self.anchor_rows: list[dict] = []
      self._anchor_first: tuple[str, tuple[int, int]] | None = None
      self.mask_base = mask_base(ls, getattr(args, "mask_of", None))
      self.mask_rows: list[dict] = []
      self.holes = bool(getattr(args, "holes", False))
      self.holes_under = self._holes_under(getattr(args, "holes_under", None))
      self.hole_min = getattr(args, "hole_min", None)
      if self.hole_min is not None and not self.holes:
         raise UsageError("--hole-min 은 --holes 와 같이 쓴다")
      self.hole_min = 1 if self.hole_min is None else int(self.hole_min)
      if self.hole_min < 1:
         raise UsageError(f"--hole-min 은 1 이상이다 : {self.hole_min}")
      # --hole-max : 이보다 큰 구멍은 일부러 둔 빈 곳(손잡이 안)으로 보고 경고 · open 셈에서 뺀다 (7판 B3). 없으면 전부 본다
      self.hole_max = getattr(args, "hole_max", None)
      if self.hole_max is not None:
         if not self.holes:
            raise UsageError("--hole-max 는 --holes 와 같이 쓴다")
         self.hole_max = int(self.hole_max)
         if self.hole_max < 1:
            raise UsageError(f"--hole-max 는 1 이상이다 : {self.hole_max}")
      self.hole_rows: list[dict] = []
      # 전 판 : open_before(폴더) → (폴더, 묶음). 이번 판과 같은 길(layers.json 또는 같은 --order)로 연다
      self.before = None
      self.before_rows: list[dict] = []
      if getattr(args, "before", None):
         b_folder, b_ls = open_before(args.before)
         self.before = (b_folder, b_ls, _items(b_folder, b_ls))
      tol = getattr(args, "shared_tol", None)
      self.shared = bool(getattr(args, "shared_colors", False))
      if tol is not None and not self.shared:
         raise UsageError("--shared-tol 은 --shared-colors 와 같이 쓴다")
      self.shared_tol = _int_range(tol, "--shared-tol", 0, SHARED_TOL_MAX) if tol is not None else SHARED_TOL

   def _holes_under(self, text) -> list[str]:
      if not text:
         return []
      if not self.holes:   # __init__ 이 holes 를 먼저 채운다
         raise UsageError("--holes-under 는 --holes 와 같이 쓴다")
      names = _names(text, self.ls.names(), "--holes-under")
      painted = self.ls.painted()
      for name in names:
         if self.ls.layer(name).is_mask:
            raise UsageError(f"--holes-under 에 마스크 겹은 못 쓴다 — 칠한 칸이 없다 : {name}")
         if name == painted[0]:   # 위 겹만 아래 겹 구멍을 덮는다 — 맨 아래 겹은 아무것도 못 덮는다
            raise UsageError(f"--holes-under 에 맨 아래 겹을 적었다 — 덮개는 구멍 난 겹보다 위 겹이다 : {name}")
      return names

   def masks(self) -> list[str]:
      return [layer.name for layer in self.ls.layers if layer.is_mask]

   # --- 그림마다 ---

   def item(self, item: str, good: dict[str, image.RGBA], warnings: list[dict]) -> None:
      if self.ls.anchor is not None:
         self._anchor(item, good, warnings)
      if self.mask_base is not None:
         self._mask_union(item, good, warnings)
      if self.holes:
         self._holes(item, good, warnings)
      if self.before is not None:
         self._before(item, good, warnings)
      if self.shared:
         self._shared(item, good, warnings)

   def _before(self, item: str, good: dict[str, image.RGBA], warnings: list[dict]) -> None:
      """같은 그림 · 같은 겹 짝끼리 색을 견준다. 새 색 = 이번 판 불투명 색 − 전 판 불투명 색 (크기는 안 따진다)."""
      b_folder, b_ls, b_items = self.before
      if item not in b_items:
         warnings.append(warning("layer_before_missing", f"{item} : 전 판에 이 그림이 없다"))
         return
      old = _read_raw(b_folder, b_ls, item)
      for name in [n for n in self.ls.painted() if n in good]:
         if name not in old:
            warnings.append(warning("layer_before_missing", f"{item} : 전 판에 겹 {name} 이 없다"))
            continue
         now = good[name]
         fresh = sorted(image.opaque_colors(now) - image.opaque_colors(old[name]))
         cells = _near_colors(now, fresh, 0) if fresh else np.zeros(now.shape[:2], dtype=bool)
         row = {"item": item, "layer": name, "colors": [image.count_colors(old[name]), image.count_colors(now)],
                "new": len(fresh), "new_cells": int(np.count_nonzero(cells))}
         self.before_rows.append(row)
         if fresh:
            warnings.append(warning("layer_new_color", f"{item} : {name} 에 전 판에 없던 색 {len(fresh)}개 ({row['new_cells']}칸)", _points(cells)))

   def _shared(self, item: str, good: dict[str, image.RGBA], warnings: list[dict]) -> None:
      """겹 짝(쌓는 순서로 한 번씩)마다 서로 가까운 색(RGB 각 칸 차 ≤ tol)을 센다.

      칸을 색마다 훑지 않고 색 × 색 표로 센다 — 겹마다 색이 SHARED_COLORS_MAX 이하라 표가 작다.
      """
      names = [n for n in self.ls.painted() if n in good]
      table = {n: _color_counts(good[n]) for n in names}
      tol = self.shared_tol
      for i, low in enumerate(names):
         for high in names[i + 1 :]:
            (ca, na), (cb, nb) = table[low], table[high]
            if len(ca) == 0 or len(cb) == 0:
               continue
            if len(ca) > SHARED_COLORS_MAX or len(cb) > SHARED_COLORS_MAX:
               warnings.append(warning("layer_shared_skipped", f"{item} : {low} · {high} 는 색이 {SHARED_COLORS_MAX}개보다 많아 같은 색 견줌을 건너뛰었다 ({len(ca)} · {len(cb)})"))
               continue
            near_ab = _cheb(ca, cb) <= tol                     # [A 색, B 색]
            near_aa = _cheb(ca, ca) <= tol
            b_cells = near_ab.astype(np.int64) @ nb            # A 색마다 근처 B 칸 수
            a_cells = near_aa.astype(np.int64) @ na            # A 색마다 근처 A 칸 수
            hit = np.nonzero(b_cells > 0)[0]
            if len(hit) == 0:
               continue
            hit = hit[np.argsort(-(a_cells[hit] + b_cells[hit]), kind="stable")]
            colors = [tuple(int(v) for v in ca[k]) for k in hit]
            text = " · ".join(f"{to_hex(ca[k])} 근처 A {int(a_cells[k])}칸 · B {int(b_cells[k])}칸" for k in hit[:SHARED_SHOW])
            more = f" 외 {len(hit) - SHARED_SHOW}색" if len(hit) > SHARED_SHOW else ""
            spots = _near_colors(good[low], colors, tol) | _near_colors(good[high], colors, tol)
            warnings.append(warning("layer_shared_color", f"{item} : {low} · {high} : {text}{more} (--shared-tol {tol})", _points(spots)))

   def _holes(self, item: str, good: dict[str, image.RGBA], warnings: list[dict]) -> None:
      """겹마다 테두리에서 투명 칸만 따라 못 닿는 투명 칸(`fill --enclosed` 와 같은 뜻)을 덩이로 나눠 센다.

      덩이 나누기는 `pieces.labels`(numpy) — 파이썬 BFS 는 큰 그림에서 수십 초 걸린다.
      `--holes-under` 겹 중 이 겹보다 위 겹의 칠한 칸이 덩이를 다 덮으면 covered. 경고는 open 덩이만.
      """
      order = self.ls.painted()
      for name in [n for n in order if n in good]:
         enc = fill_mod.enclosed(good[name])
         label, sizes = labels(enc)
         keep = int(np.count_nonzero(sizes >= self.hole_min))   # sizes 는 큰 것부터라 앞 keep 개
         if keep == 0:
            continue
         lid = np.zeros(enc.shape, dtype=bool)
         for upper in self.holes_under:
            if order.index(upper) > order.index(name) and upper in good:
               lid |= _opaque(good[upper])
         inside = (label >= 0) & (label < keep)
         bare = np.bincount(label[inside & ~lid], minlength=keep)[:keep]   # 덩이마다 안 덮인 칸 수
         covered = bare == 0
         large = sizes[:keep] > self.hole_max if self.hole_max is not None else np.zeros(keep, dtype=bool)
         loose = ~covered & ~large                                           # 경고 · open 셈에 드는 덩이
         open_cells = inside & loose[np.where(inside, label, 0)]
         ys, xs = np.nonzero(inside)
         lab = label[ys, xs]
         x0 = np.full(keep, enc.shape[1]); y0 = np.full(keep, enc.shape[0])
         x1 = np.zeros(keep, dtype=np.int64); y1 = np.zeros(keep, dtype=np.int64)
         np.minimum.at(x0, lab, xs); np.minimum.at(y0, lab, ys)
         np.maximum.at(x1, lab, xs + 1); np.maximum.at(y1, lab, ys + 1)
         shown = min(keep, HOLES_MAX)
         row = {
            "item": item, "layer": name, "count": keep, "cells": int(sizes[:keep].sum()),
            "covered": int(covered.sum()), "open": int(loose.sum()),
            "regions": [{"box": [int(x0[i]), int(y0[i]), int(x1[i]), int(y1[i])], "cells": int(sizes[i]), "covered": bool(covered[i]),
                         **({"large": True} if large[i] else {})}
                        for i in range(shown)],
         }
         if self.hole_max is not None:   # --hole-max 를 줄 때만 — 안 주면 보고 꼴이 예전 그대로
            row["large"] = int(large.sum())
         if keep > shown:
            row["more"] = keep - shown
         self.hole_rows.append(row)
         if row["open"]:
            warnings.append(warning("layer_hole", f"{item} : {name} 안쪽 구멍 {row['open']}개 ({int(np.count_nonzero(open_cells))}칸) — 위 겹이 안 덮는다", _points(open_cells)))

   def _mask_union(self, item: str, good: dict[str, image.RGBA], warnings: list[dict]) -> None:
      """마스크 겹들을 합쳐 기준겹 불투명 영역과 견준다. 기준겹이 없는 장은 건너뛴다(빈 겹 경고가 따로 난다)."""
      base = good.get(self.mask_base)
      if base is None:
         return
      inside = _opaque(base)
      count = _coverage({n: good[n] for n in self.masks() if n in good}, inside.shape)
      cells = {
         "gap": inside & (count == 0),
         "overlap": count >= 2,
         "outside": (count > 0) & ~inside,
      }
      text = {"gap": "기준겹에 있는데 어느 마스크도 없는", "overlap": "마스크 둘 이상이 겹친", "outside": "기준겹 밖에 마스크가 있는"}
      row = {"item": item}
      for key, mask in cells.items():
         row[key] = int(np.count_nonzero(mask))
         if row[key]:
            warnings.append(warning(f"layer_mask_{key}", f"{item} : {self.mask_base} 기준 {text[key]} 칸 {row[key]}개", _points(mask)))
      self.mask_rows.append(row)

   def _anchor(self, item: str, good: dict[str, image.RGBA], warnings: list[dict]) -> None:
      """bbox 기준점 하나 (메인 결정 2026-10-07). 잴 그림 = anchor_layer 겹 하나, 없으면 마스크 겹을 뺀 겹을 다 쌓은 그림.

      이름 꼴은 `_anchor_xy` 칸 좌표(장끼리 견주기만 해서 뜻이 그대로). [x, y] 꼴은 변 좌표라
      (floor((x0 + x1) / 2), y1) — bbox 아래변(끝 뺀 y1) 가운데와 견준다 (7판 B1).
      """
      if self.ls.anchor_layer is not None:
         part = good.get(self.ls.anchor_layer)
         box = image.bbox(part) if part is not None else None
      else:
         box = image.bbox(_stack(self.ls, good))
      if box is None:   # 빈 장은 잴 것이 없다
         self.anchor_rows.append({"item": item, "at": None})
         return
      anchor = self.ls.anchor
      if isinstance(anchor, str):
         at = _anchor_xy(box, anchor)
         if self._anchor_first is None:
            self._anchor_first = (item, at)
         ref_item, want = self._anchor_first
         where = f"첫 장 {ref_item} 의 {want}"
      else:
         at = ((box[0] + box[2]) // 2, box[3])
         want, where = anchor, f"anchor {list(anchor)} (변 좌표)"
      self.anchor_rows.append({"item": item, "at": [at[0], at[1]]})
      if max(abs(at[0] - want[0]), abs(at[1] - want[1])) > self.anchor_tol:
         warnings.append(warning("layer_anchor", f"{item} : 기준점 {at} 이 {where} 와 다르다 (--anchor-tol {self.anchor_tol})", [[at[0], at[1]]]))

   # --- 끝 ---

   def finish(self, report: dict, warnings: list[dict]) -> None:
      if self.before is not None:   # 전 판에만 있는 그림도 짝이 없는 쪽이다
         for item in self.before[2]:
            if item not in self.items:
               warnings.append(warning("layer_before_missing", f"{item} : 이번 판에 이 그림이 없다 (전 판에만 있다)"))
      self._finish(report, warnings)

   def _finish(self, report: dict, warnings: list[dict]) -> None:
      """끝에 한 번. 새 칸은 report 에, 새 경고는 warnings 에 더한다 (status 를 정하기 전에 부른다)."""
      if self.counts:
         counts = {name: len(found) for name, found in _scan_variants(self.folder, self.ls).items()}
         report["counts"] = counts
         if len(set(counts.values())) > 1:
            text = " · ".join(f"{n} {c}" for n, c in counts.items())
            warnings.append(warning("layer_count", f"겹마다 장 수가 다르다 : {text}"))
      if self.ls.anchor is not None:
         report["anchors"] = self.anchor_rows
      if self.holes:
         report["holes"] = self.hole_rows
      if self.before is not None:
         report["before"] = {"in": str(self.before[0]), "items": self.before_rows}
      if self.mask_base is not None:
         report["mask_of"] = {"base": self.mask_base, "masks": self.masks(), "items": self.mask_rows}


def _color_counts(arr: image.RGBA) -> tuple[np.ndarray, np.ndarray]:
   """불투명 칸의 색 [n, 3] 과 색마다 칸 수 [n]."""
   rgb = arr[:, :, :3][_opaque(arr)].astype(np.int32)
   keys = (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]
   uniq, counts = np.unique(keys, return_counts=True)
   colors = np.stack([uniq >> 16, (uniq >> 8) & 0xFF, uniq & 0xFF], axis=1)
   return colors, counts.astype(np.int64)


def _cheb(a: np.ndarray, b: np.ndarray) -> np.ndarray:
   """색 두 목록의 RGB 각 칸 차 최댓값 표 [len(a), len(b)]."""
   return np.abs(a[:, None, :] - b[None, :, :]).max(axis=2)
