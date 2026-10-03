"""타일 이음매 검사. 이음 줄 차이를 안쪽 이웃 칸끼리의 평균 차이와 견준다. 설계 문서 6-3.

`Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md`
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .. import check, image
from ..errors import ArtToolError, UsageError
from ..paths import jailed_output

VERSION = 1
DEFAULT_K = 2.0


def _norm(arr: image.RGBA) -> np.ndarray:
   """투명 칸은 RGB 찌꺼기를 지워 0 으로. 차이 셈이 넘치지 않게 int32."""
   out = arr.astype(np.int32)
   out[arr[:, :, 3] == 0] = 0
   return out


def _diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
   """칸마다 RGBA 네 칸 차이의 합 (0 ~ 1020)."""
   return np.abs(a - b).sum(axis=-1)


def _inner(arr: np.ndarray, axis: int) -> np.ndarray:
   """안쪽 이웃 칸끼리의 차이. axis 1 이면 가로 이웃, 0 이면 세로 이웃."""
   if axis == 1:
      return _diff(arr[:, :-1], arr[:, 1:]).ravel()
   return _diff(arr[:-1], arr[1:]).ravel()


def _judge(name: str, line: dict, seam_d: np.ndarray, inner: float, k: float, point_key: str) -> dict:
   """이음 줄 평균이 안쪽 평균의 k 배를 넘으면 실패. 실패한 줄에만 넘친 자리를 적는다."""
   diff = float(seam_d.mean())
   limit = k * inner
   ok = diff <= limit
   ratio = 0.0 if diff == 0 else (diff / inner if inner > 0 else None)
   row = {
      "seam": name,
      "line": line,
      "diff": round(diff, 3),
      "inner": round(inner, 3),
      "ratio": None if ratio is None else round(ratio, 4),
      "ok": ok,
   }
   if not ok:
      row[point_key] = [int(i) for i in np.nonzero(seam_d > limit)[0]]
   return row


def check_pair(a: image.RGBA, b: image.RGBA, k: float) -> list[dict]:
   """a 오른쪽 ↔ b 왼쪽, a 아래 ↔ b 위. 한 장 검사는 a 와 b 가 같은 그림이다."""
   na, nb = _norm(a), _norm(b)
   h, w = a.shape[0], a.shape[1]
   inner_x = float(np.concatenate([_inner(na, 1), _inner(nb, 1)]).mean())
   inner_y = float(np.concatenate([_inner(na, 0), _inner(nb, 0)]).mean())
   return [
      _judge("right_left", {"x": [w - 1, 0]}, _diff(na[:, -1], nb[:, 0]), inner_x, k, "rows"),
      _judge("bottom_top", {"y": [h - 1, 0]}, _diff(na[-1], nb[0]), inner_y, k, "cols"),
   ]


def tiled3(arr: image.RGBA) -> image.RGBA:
   return np.tile(arr, (3, 3, 1))


def _check_args(k: float, sheet, scale) -> None:
   if not (math.isfinite(k) and k > 0):
      raise UsageError(f"--k 는 유한한 양수여야 한다 : {k}")
   if scale is not None and sheet is None:
      raise UsageError("--scale 은 --sheet 와 같이 쓴다")
   if scale is not None and scale <= 0:
      raise UsageError(f"--scale 은 양수여야 한다 : {scale}")


def run(in_path: str | Path, k: float = DEFAULT_K, pairs: bool = False, sheet: str | Path | None = None, scale: int | None = None) -> dict:
   _check_args(k, sheet, scale)
   items = check.load_loose(check.check_source(in_path))
   for item in items:
      w, h = image.size(item["arr"])
      if w < 2 or h < 2:
         raise ArtToolError(f"{item['where']} 가 {w}x{h} 라 안쪽 이웃이 없다. 가로·세로 2 이상이어야 한다")
   if pairs:
      first = image.size(items[0]["arr"])
      for item in items:
         if image.size(item["arr"]) != first:
            raise ArtToolError(f"--pairs 는 크기가 같아야 한다 : {item['where']} {image.size(item['arr'])} ≠ {first}")

   tiles = []
   for item in items:
      seams = check_pair(item["arr"], item["arr"], k)
      tiles.append({"name": item["where"], "size": list(image.size(item["arr"])), "ok": all(s["ok"] for s in seams), "seams": seams})
   failed = [t["name"] for t in tiles if not t["ok"]]

   report: dict = {"version": VERSION, "status": "ok", "k": k, "files": len(tiles), "tiles": tiles}
   if pairs:
      rows = []
      for a in items:
         for b in items:
            if a is b:
               continue
            seams = check_pair(a["arr"], b["arr"], k)
            rows.append({"a": a["where"], "b": b["where"], "ok": all(s["ok"] for s in seams), "seams": seams})
      report["pairs"] = rows
      failed += [f"{p['a']} → {p['b']}" for p in rows if not p["ok"]]

   sheet_path = None
   if sheet is not None:
      sheet_path = jailed_output(sheet)
      image.save(sheet_path, image.contact_sheet([tiled3(i["arr"]) for i in items], scale or 1))
   report["sheet"] = str(sheet_path) if sheet_path else None
   report["failed"] = failed
   report["status"] = "fail" if failed else "ok"
   return report
