"""다듬기 — 납작한 그림의 칸마다 모델 팔레트 색 하나를 다시 고른다 (2026-11-08 작은 다듬기 모델 설계 4 · 7절).

모양(알파)은 그대로, 불투명 칸 색만 바꾼다. 모델 = JSON 한 장 + 엔진 파일 하나. 엔진 둘 :

- `table` : 5×5 이웃 표. 칸마다 열쇠(아래 표)를 셈해 「열쇠 → 팔레트 번호」 표에서 찾는다. numpy 만.
- `onnx` : 작은 U-Net (P8 몫). 지금은 자리만 있다.

| 열쇠 칸 (칸 하나) | 비트 |
| --- | --- |
| 가운데 색 → 모델 팔레트 번호 (RGB 가장 가까운 색) | 6 |
| 5×5 둘레 24칸이 가운데와 같은 덩어리인가 (`flatten.regions`) | 24 |
| 덩어리 안 밝기 순위 (4단) | 2 |
| 바깥 테(투명 칸)까지 거리 0 · 1 · 2 · 3+ (네 방향 직선) | 2 |
| 가장 가까운 테가 빛 쪽인가 | 1 |

물러나기 사다리 : 0 전체 열쇠 → 1 둘레를 3×3(8칸)으로 줄인 열쇠 → 2 (색, 순위, 거리) → 3 입력 색 그대로(팔레트에 붙임).
학습(`train/polish/table.py`)도 이 파일의 `keys()` 를 부른다 — 열쇠 셈이 둘로 갈라지면 표가 조용히 틀린다.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np

from .. import image
from ..draw.lint import lint as run_lint
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json
from ..palette import RGB, Ramps, parse_hex
from ..paths import guard_overwrite, jailed_output
from .flatten import _shift as _at, regions
from .score import similarity
from .spec import LIGHT_WORDS

LEVELS = 4                 # 사다리 칸 수 (마지막 칸 = 입력 색 그대로)
ENGINES = ("table", "onnx")
_RING5 = [(dx, dy) for dy in range(-2, 3) for dx in range(-2, 3) if (dx, dy) != (0, 0)]   # 24칸
_RING3 = [(dx, dy) for dy in range(-1, 2) for dx in range(-1, 2) if (dx, dy) != (0, 0)]   # 8칸
_RAYS = ((0, -1), (-1, 0), (0, 1), (1, 0))   # 위 · 왼 · 아래 · 오른 (그림 좌표, y 아래로 +)
REACH = 3                                    # 거리 3 이상은 한 칸으로 접는다


def nearest(rgb: np.ndarray, pal: np.ndarray) -> np.ndarray:
   """색 (..., 3) → 가장 가까운(RGB 거리) 팔레트 번호. 고유 색만 셈한다."""
   flat = rgb.reshape(-1, 3).astype(np.int64)
   cols, inv = np.unique(flat, axis=0, return_inverse=True)
   d = ((cols[:, None, :] - pal[None, :, :].astype(np.int64)) ** 2).sum(-1)
   return d.argmin(1)[inv.reshape(-1)].reshape(rgb.shape[:-1])


def _ranks(arr: np.ndarray, labels: np.ndarray, colors: list[list[RGB]]) -> np.ndarray:
   """칸마다 덩어리 안 밝기 순위 0 ~ 3. 덩어리 색 목록(어두운 → 밝은, 「제 색」 칸만)의 밝기 사이 어디에 드나로 센다.
   목록에 없는 색(테 · 잡티 칸)도 밝기로 자리를 찾는다."""
   rank = np.zeros(labels.shape, dtype=np.int64)
   luma = image.luma(arr)
   for i, cols in enumerate(colors):
      n = len(cols)
      if not n:
         continue
      own = labels == i
      steps = np.array(cols, dtype=float) @ np.array([0.299, 0.587, 0.114])
      at = np.minimum(np.searchsorted(np.sort(steps), luma[own] - 1e-6), n - 1)
      rank[own] = np.minimum(3, at * 4 // n)
   return rank


def _edge(solid: np.ndarray, light: str) -> tuple[np.ndarray, np.ndarray]:
   """(테까지 거리 0 ~ 3, 가장 가까운 테가 빛 쪽인가). 네 방향 직선으로 투명 칸을 찾는다.
   캔버스 밖은 테로 안 친다 — 바닥 타일처럼 캔버스를 꽉 채운 그림이 가장자리에서 테로 읽히지 않게."""
   lx, ly, _ = LIGHT_WORDS[light]
   lit = [ly > 0, lx < 0, False, lx > 0]   # 방향마다 빛 쪽인가 (그림 y 는 아래로 +, 빛 y 는 위로 +)
   dist = np.full(solid.shape, REACH, dtype=np.int64)
   side = np.zeros(solid.shape, dtype=np.int64)
   for step in range(REACH, 0, -1):         # 먼 것부터 덮어 가까운 것이 이긴다
      for k in range(len(_RAYS) - 1, -1, -1):   # 같은 거리면 앞 방향(위 · 왼)이 이긴다
         dx, dy = _RAYS[k]
         hit = ~_at(solid, dx * step, dy * step, True)
         dist = np.where(hit, step - 1, dist)
         side = np.where(hit, int(lit[k]), side)
   return dist, side


def keys(arr: np.ndarray, pal: np.ndarray, light: str = "top_left") -> np.ndarray:
   """그림 (H, W, 4) → 사다리 칸마다 열쇠 (LEVELS, H, W) int64. 투명 칸은 -1. 마지막 칸 = 입력 팔레트 번호."""
   solid = arr[:, :, 3] > 0
   out = np.full((LEVELS,) + solid.shape, -1, dtype=np.int64)
   if not solid.any():
      return out
   idx = nearest(arr[:, :, :3], pal)
   labels, colors = regions(arr)
   rank = _ranks(arr, labels, colors)
   dist, side = _edge(solid, light)
   same24 = np.zeros(solid.shape, dtype=np.int64)
   for b, (dx, dy) in enumerate(_RING5):
      same24 |= (_at(labels, dx, dy, -1) == labels).astype(np.int64) << b
   same8 = np.zeros(solid.shape, dtype=np.int64)
   for b, (dx, dy) in enumerate(_RING3):
      same8 |= (_at(labels, dx, dy, -1) == labels).astype(np.int64) << b
   tail = rank | (dist << 2) | (side << 4)          # 5비트
   levels = (idx | (same24 << 6) | (tail << 30),
             idx | (same8 << 6) | (tail << 14),
             idx | ((rank | (dist << 2)) << 6),
             idx)
   for n, k in enumerate(levels):
      out[n][solid] = k[solid]
   return out


# ── 모델 ──────────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
   return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model(path: str | Path) -> dict:
   """모델 JSON → {engine, palette (K, 3), light, tables | None, file}. 파일 sha256 이 다르면 한 줄 오류."""
   file = Path(path)
   raw = read_json(file)
   if not isinstance(raw, dict) or raw.get("kind") != "shape_polish":
      raise UsageError(f"다듬기 모델 JSON 이 아니다 (kind 가 shape_polish 가 아님) : {file}")
   engine = raw.get("engine")
   if engine not in ENGINES:
      raise UsageError(f"engine 은 {' · '.join(ENGINES)} 중 하나다 : {engine!r}")
   pal = raw.get("palette")
   if not isinstance(pal, list) or not 1 <= len(pal) <= 64:
      raise UsageError(f"palette 는 색 1 ~ 64 개 목록이다 : {file}")
   light = raw.get("light", "top_left")
   if light not in LIGHT_WORDS:
      raise UsageError(f"light 는 {' · '.join(LIGHT_WORDS)} 중 하나다 : {light!r}")
   name = raw.get("file")
   if not isinstance(name, str) or Path(name).name != name:
      raise UsageError(f"file 은 모델 JSON 옆 파일 이름 하나다 : {name!r}")
   body = file.parent / name
   if not body.is_file():
      raise ArtToolError(f"모델 파일이 없다 : {body}")
   if _sha256(body) != raw.get("sha256"):
      raise ArtToolError(f"모델 파일 sha256 이 JSON 과 다르다 (파일이 바뀌었거나 다른 모델) : {body}")
   model = {"engine": engine, "palette": np.array([parse_hex(c) for c in pal], dtype=np.int64), "light": light,
            "file": body, "tables": None}
   if engine == "onnx":
      raise ArtToolError("onnx 엔진은 아직 없다 (작은 다듬기 모델 P8 몫, 2026-11-09 접음)")
   with np.load(body, allow_pickle=False) as data:
      model["tables"] = [(data[f"keys{n}"], data[f"vals{n}"]) for n in range(LEVELS - 1)]
   return model


def predict(model: dict, arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """table 엔진 : (칸마다 팔레트 번호 (H, W), 칸마다 답한 사다리 칸 (H, W)). 투명 칸은 둘 다 -1."""
   k = keys(arr, model["palette"], model["light"])
   solid = k[-1] >= 0
   pick = np.where(solid, k[-1], -1)            # 사다리 끝 = 입력 색 그대로
   level = np.where(solid, LEVELS - 1, -1)
   todo = solid.copy()
   for n, (tk, tv) in enumerate(model["tables"]):
      if not todo.any() or not len(tk):
         continue
      q = k[n][todo]
      at = np.minimum(np.searchsorted(tk, q), len(tk) - 1)
      found = tk[at] == q
      ys, xs = np.nonzero(todo)
      pick[ys[found], xs[found]] = tv[at[found]]
      level[ys[found], xs[found]] = n
      todo[ys[found], xs[found]] = False
   return pick, level


def polish(model: dict, arr: np.ndarray) -> tuple[np.ndarray, dict]:
   """그림 → (다듬은 그림, 보고). 알파 그대로, 불투명 칸만 팔레트 색."""
   started = time.perf_counter()
   pick, level = predict(model, arr)
   solid = pick >= 0
   out = arr.copy()
   out[solid, :3] = model["palette"][pick[solid]]
   ms = (time.perf_counter() - started) * 1000.0
   pal = [tuple(int(v) for v in c) for c in model["palette"]]
   result = run_lint(out, ramps=Ramps("polish", {"polish": pal}, None, len(pal), mode="max"), light=model["light"])
   report = {
      "engine": model["engine"],
      "size": [int(arr.shape[1]), int(arr.shape[0])],
      "opaque": int(solid.sum()),
      "changed": int((solid & np.any(out[:, :, :3] != arr[:, :, :3], axis=2)).sum()),
      "colors": int(len(np.unique(out[solid][:, :3], axis=0))) if solid.any() else 0,
      "ladder": [int((level == n).sum()) for n in range(LEVELS)],
      "ms": round(ms, 1),
      "lint": {"status": result.status, "counts": result.counts},
   }
   return out, report


def run(args) -> dict:
   """`arttool shape polish <in> --out <png> --model <model.json> [--ref 원본] [--report r.json]`."""
   out = jailed_output(args.out_file)
   if out.suffix.lower() != ".png":
      raise UsageError(f"--out 은 .png 다 : {args.out_file}")
   ref = getattr(args, "ref", None)
   guard_overwrite([out], [args.in_path, args.model, ref], "--out")
   model = load_model(args.model)
   arr, report = polish(model, image.load(args.in_path))
   if ref:
      report["score"] = similarity(arr, image.load(ref))
   image.save(out, arr)
   report["out"] = str(out)
   report["status"] = "ok" if report["lint"]["status"] == "ok" else "warn"
   return report
