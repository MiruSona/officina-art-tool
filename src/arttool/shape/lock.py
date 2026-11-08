"""팔레트 잠금 — 그림의 모든 색을 정해 둔 팔레트(게임 정본 팔레트) 안 색으로 바꾼다 (2026-11-08 보완 고리 1).

명세 맨 위 `palette_lock` 칸으로 켠다. 없으면 렌더 결과는 잠금 전과 칸까지 같다.

    "palette_lock": { "file": "game_master.json", "ramps": ["*", "!food_*"], "keep_steps": true }

| 칸 | 뜻 |
| --- | --- |
| `file` | ArtTool 램프 파일(`ramps` 사전) 또는 그 목록(색을 합친다 — 정본 + 종류별 팔레트). `real_len` 이 있으면 그 길이까지만 쓴다(짧은 램프를 채운 칸 빼기). 명세 파일 기준 상대 경로 |
| `colors` | `file` 대신 색 목록을 바로 준다 (`#RRGGBB`) |
| `ramps` | 쓸 램프 이름(글자 맞추기). `!` 로 시작하면 뺀다. 없으면 모두 |
| `keep_steps` | 기본 true. 재질 안 색을 밝기 차례대로 늘어놓고 팔레트 색도 밝기 차례로 짝지어(차례 안 뒤집힘) 단 사이 밝기 차를 지킨다. false 면 색마다 가장 가까운 색 |
| `merge_cost` | 기본 10. 서로 다른 두 단이 같은 팔레트 색으로 합쳐질 때 무는 값(색 거리 ΔE 단위). 클수록 단을 안 합친다 |
| `family` | 기본 false. true 면 「계열 지킴」 : 색마다 같은 계열(색조 차 `hue_tol` 안, 회색은 회색끼리) 팔레트 색만 짝 후보로 둔다. 곁색(hue_side)도 같은 계열 안 이웃 색으로 간다 (보완 고리 2). 종류별 팔레트 파일은 「램프」가 밝기 단이 아니라 비슷한 색 무리라서, 램프 이름이 아니라 색조로 계열을 가른다 |
| `max_de` | family 일 때 기본 14. 짝지은 색과의 ΔE 가 이보다 크면 그 색은 잠그지 않고 그대로 둔다 (같은 계열이 없을 때) |
| `hue_tol` | family 일 때 기본 35(도). 두 색 모두 채도가 있을 때 색조 차가 이보다 크면 잠그지 않는다 (파랑 → 보라 막기) |
| `profile` · `kind` | 종류별 잠금 프로필 파일(`{"kinds": {"customer": {...잠금 칸...}, "food": null}}`)에서 `kind` 칸을 읽는다. null 이면 잠금 끔. 다른 칸은 프로필 값을 덮는다 |

어떻게 바꾸나
- 색 거리는 CIE Lab ΔE(사람 눈 차이에 가까운 거리)다. 팔레트에 없는 색(예: 파란 도기)은 Lab 로 가장 가까운 계열로 간다.
- 재질마다(맞은 재질 칸끼리 · 외곽선 칸끼리) 따로 짝짓는다. 한 재질 안 색을 L(밝기) 차례로 늘어놓고,
  팔레트 색도 L 차례로 늘어놓은 뒤 「앞 색보다 어둡지 않은 팔레트 색」만 고르게 하는 동적 계획법으로
  (칸 수 × 거리) 합 + 합쳐짐 값을 가장 작게 한다. 그래서 램프 단 순서가 안 뒤집히고, 단이 둘이면 될 수 있는 한 다른 색이 된다.
"""

from __future__ import annotations

import fnmatch
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..errors import ArtToolError
from ..jsonio import read_json
from ..palette import RGB, parse_hex


@dataclass
class Lock:
   colors: list[RGB]
   keep_steps: bool = True
   merge_cost: float = 10.0
   names: list[str] = field(default_factory=list)   # 쓴 램프 이름 (보고용)
   ramps: list = field(default_factory=list)        # [(이름, [RGB])] — family 용 계열
   family: bool = False
   max_de: float = 14.0
   hue_tol: float = 35.0
   kept: int = 0                                    # family : 문턱을 넘어 안 잠근 칸 수 (보고용, apply 가 채움)


def _err(path: str, msg: str) -> ArtToolError:
   return ArtToolError(f"명세 {path} : {msg}")


def _pick(name: str, pats: list[str]) -> bool:
   keep = [p for p in pats if not p.startswith("!")] or ["*"]
   drop = [p[1:] for p in pats if p.startswith("!")]
   return any(fnmatch.fnmatchcase(name, p) for p in keep) and not any(fnmatch.fnmatchcase(name, p) for p in drop)


def read_palette(file: Path, pats: list[str] | None = None) -> tuple[list[RGB], list[str]]:
   """램프 파일 → (색 목록 겹침 없이, 쓴 램프 이름). real_len 이 있으면 그 길이까지만."""
   ramps = read_ramps(file, pats)
   out = list(dict.fromkeys(c for _, cols in ramps for c in cols))
   return out, [n for n, _ in ramps if n != "outline"]


def read_ramps(file: Path, pats: list[str] | None = None) -> list[tuple[str, list[RGB]]]:
   """램프 파일 → [(램프 이름, 색 목록)]. 외곽선 색은 램프 \"outline\" 한 색으로."""
   if not file.is_file():
      raise ArtToolError(f"palette_lock 팔레트 파일이 없다 : {file}")
   data = read_json(file)
   ramps = data.get("ramps") if isinstance(data, dict) else None
   if not isinstance(ramps, dict) or not ramps:
      raise ArtToolError(f"palette_lock 팔레트 파일에 ramps 가 없다 : {file}")
   real = data.get("real_len") or {}
   out: list[tuple[str, list[RGB]]] = []
   for name, cols in ramps.items():
      if pats and not _pick(name, pats):
         continue
      n = real.get(name, len(cols)) if isinstance(real, dict) else len(cols)
      got = [parse_hex(c) for c in cols[:n]]
      if got:
         out.append((name, got))
   if data.get("outline") and (not pats or _pick("outline", pats)):
      out.append(("outline", [parse_hex(data["outline"])]))
   if not out:
      raise ArtToolError(f"palette_lock : 고른 램프에 색이 없다 ({pats}) : {file}")
   return out


def parse(raw, base: str | os.PathLike | None, path: str = "palette_lock") -> Lock | None:
   """명세 `palette_lock` 칸 → Lock. 없으면 None. base : 상대 경로 기준 폴더."""
   if raw is None:
      return None
   if isinstance(raw, str):
      raw = {"file": raw}
   if not isinstance(raw, dict):
      raise _err(path, "사전이다 {file 또는 colors, ramps, keep_steps, merge_cost}")
   if "profile" in raw or "kind" in raw:
      raw, base = _from_profile(raw, base, path)
      if raw is None:
         return None
   pats = raw.get("ramps")
   if pats is not None and (not isinstance(pats, list) or not all(isinstance(p, str) and p for p in pats)):
      raise _err(f"{path}.ramps", "램프 이름(글자 맞추기, ! 로 빼기) 목록이다")
   if ("file" in raw) == ("colors" in raw):
      raise _err(path, "file 또는 colors 가운데 하나만 준다")
   if "file" in raw:
      files = raw["file"] if isinstance(raw["file"], list) else [raw["file"]]
      if not files or not all(isinstance(f, str) and f for f in files):
         raise _err(f"{path}.file", "램프 파일 경로 글자 또는 그 목록이다")
      ramps = []
      for f in files:
         file = Path(f)
         if not file.is_absolute() and base is not None:
            file = Path(base) / file
         ramps.extend(read_ramps(file, pats))
      colors = list(dict.fromkeys(c for _, cols in ramps for c in cols))
      names = [n for n, _ in ramps if n != "outline"]
   else:
      cols = raw["colors"]
      if not isinstance(cols, list) or not cols:
         raise _err(f"{path}.colors", "#RRGGBB 목록이다")
      try:
         colors = list(dict.fromkeys(parse_hex(c) for c in cols))
      except (ArtToolError, TypeError, AttributeError) as exc:
         raise _err(f"{path}.colors", str(exc)) from None
      names = []
      ramps = [("colors", colors)]
   keep = raw.get("keep_steps", True)
   if not isinstance(keep, bool):
      raise _err(f"{path}.keep_steps", f"true · false 다 : {keep!r}")
   cost = raw.get("merge_cost", 10.0)
   if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not 0 <= cost <= 1000 or not math.isfinite(cost):
      raise _err(f"{path}.merge_cost", f"0 ~ 1000 수다 : {cost!r}")
   family = raw.get("family", False)
   if not isinstance(family, bool):
      raise _err(f"{path}.family", f"true · false 다 : {family!r}")
   max_de = _num(raw, "max_de", 14.0, 0.0, 200.0, path)
   hue_tol = _num(raw, "hue_tol", 35.0, 0.0, 180.0, path)
   return Lock(colors, keep, float(cost), names, ramps, family, max_de, hue_tol)


def _num(raw: dict, key: str, default: float, low: float, high: float, path: str) -> float:
   v = raw.get(key, default)
   if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not low <= v <= high:
      raise _err(f"{path}.{key}", f"{low:g} ~ {high:g} 수다 : {v!r}")
   return float(v)


def _from_profile(raw: dict, base, path: str):
   """종류별 잠금 프로필 : {"kinds": {종류: 잠금 사전 또는 null}} 에서 kind 칸 → (잠금 사전 또는 None, 상대 경로 기준)."""
   prof, kind = raw.get("profile"), raw.get("kind")
   if not isinstance(prof, str) or not prof or not isinstance(kind, str) or not kind:
      raise _err(path, "profile(프로필 파일 경로)과 kind(종류 이름)를 같이 준다")
   file = Path(prof)
   if not file.is_absolute() and base is not None:
      file = Path(base) / file
   if not file.is_file():
      raise ArtToolError(f"palette_lock 프로필 파일이 없다 : {file}")
   data = read_json(file)
   kinds = data.get("kinds") if isinstance(data, dict) else None
   if not isinstance(kinds, dict):
      raise ArtToolError(f"palette_lock 프로필에 kinds 사전이 없다 : {file}")
   if kind not in kinds:
      raise _err(f"{path}.kind", f"프로필에 없는 종류 : {kind!r} (있는 것 : {' · '.join(kinds)})")
   got = kinds[kind]
   if got is None:
      return None, base
   if isinstance(got, str):
      got = {"file": got}
   if not isinstance(got, dict):
      raise ArtToolError(f"palette_lock 프로필 kinds.{kind} 는 잠금 사전 또는 null 이다 : {file}")
   rest = {k: v for k, v in raw.items() if k not in ("profile", "kind")}
   if "file" in rest or "colors" in rest:
      got = {k: v for k, v in got.items() if k not in ("file", "colors")}
   return got | rest, file.parent


# ── 색 거리 ───────────────────────────────────────────────────────────────

def to_lab(rgb: np.ndarray) -> np.ndarray:
   """sRGB (N, 3) 0 ~ 255 → CIE Lab (N, 3), D65."""
   c = np.asarray(rgb, dtype=float) / 255.0
   c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
   m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
   xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
   f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
   return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def _assign(src: np.ndarray, weight: np.ndarray, pal_lab: np.ndarray, keep_steps: bool, merge_cost: float,
            ok: np.ndarray | None = None) -> np.ndarray:
   """src 색(Lab, L 차례로 정렬됨)마다 팔레트 번호(pal_lab 도 L 차례). 차례 안 뒤집힘 + 합쳐짐 값 동적 계획법.
   ok : (n, m) 같은 계열 표 (family). 계열 밖 짝은 거리에 큰 값을 더해 피한다."""
   dist = np.sqrt(((src[:, None, :] - pal_lab[None, :, :]) ** 2).sum(-1))       # (n, m)
   if ok is not None:
      dist = dist + np.where(ok, 0.0, FAR)
   if not keep_steps:
      return dist.argmin(1)
   n, m = dist.shape
   cost = weight[:, None] * dist
   best = np.full((n, m), np.inf)
   back = np.zeros((n, m), dtype=np.int64)       # 앞 색이 고른 팔레트 번호
   best[0] = cost[0]
   for i in range(1, n):
      # 밝기가 거의 같은 두 색(곁색)은 합쳐도 단이 안 사라진다 — 밝기 차 5 L 에서 값을 다 문다
      pen = merge_cost * min(weight[i], weight[i - 1]) * min(1.0, abs(src[i, 0] - src[i - 1, 0]) / 5.0)
      # 앞 색이 j' < j 를 골랐다 (쌓인 최솟값) · 또는 같은 j (합쳐짐)
      prev_min = np.minimum.accumulate(best[i - 1])
      arg = np.zeros(m, dtype=np.int64)
      cur = 0
      for j in range(m):
         if best[i - 1, j] <= best[i - 1, cur]:
            cur = j
         arg[j] = cur
      strict = np.full(m, np.inf)
      strict[1:] = prev_min[:-1]
      strict_arg = np.zeros(m, dtype=np.int64)
      strict_arg[1:] = arg[:-1]
      same = best[i - 1] + pen
      take_same = same < strict
      best[i] = cost[i] + np.where(take_same, same, strict)
      back[i] = np.where(take_same, np.arange(m), strict_arg)
   out = np.zeros(n, dtype=np.int64)
   out[-1] = int(best[-1].argmin())
   for i in range(n - 1, 0, -1):
      out[i - 1] = back[i, out[i]]
   return out


def _hue(lab: np.ndarray) -> np.ndarray:
   return np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360.0


def _hue_diff(a, b):
   d = np.abs(np.asarray(a) - np.asarray(b)) % 360.0
   return np.minimum(d, 360.0 - d)


CHROMA = 8.0   # 이보다 채도가 낮으면 회색 — 색조를 따지지 않는다
FAR = 300.0    # family : 계열 밖 짝에 더하는 거리


def _allowed(src: np.ndarray, pal: np.ndarray, hue_tol: float) -> np.ndarray:
   """(n, m) : 원본 색 i 를 팔레트 색 j 로 보내도 같은 계열인가.
   채도 있는 색 → 채도 있는(CHROMA/2 이상) 색 가운데 색조 차 hue_tol 안. 회색 → 채도 낮은(2·CHROMA 아래) 색."""
   cs = np.hypot(src[:, 1], src[:, 2])[:, None]
   cp = np.hypot(pal[:, 1], pal[:, 2])[None, :]
   dh = _hue_diff(_hue(src)[:, None], _hue(pal)[None, :])
   return np.where(cs >= CHROMA, (cp >= CHROMA / 2) & (dh <= hue_tol), cp < 2 * CHROMA)


def apply(lock: Lock, arr: np.ndarray, groups: np.ndarray) -> int:
   """arr 의 불투명 칸 색을 팔레트 색으로 바꾼다. groups : 칸마다 무리 번호(재질 번호, 외곽선 칸 -1). 바꾼 칸 수."""
   pal = np.array(lock.colors, dtype=np.int64)
   pal_lab = to_lab(pal)
   order = np.argsort(pal_lab[:, 0], kind="stable")
   pal, pal_lab = pal[order], pal_lab[order]
   solid = arr[:, :, 3] > 0
   changed = 0
   lock.kept = 0
   gpal, gpal_lab = pal, pal_lab
   for g in np.unique(groups[solid]):
      sel = solid & (groups == g)
      cols, counts = np.unique(arr[sel][:, :3].astype(np.int64), axis=0, return_counts=True)
      lab = to_lab(cols)
      srt = np.argsort(lab[:, 0], kind="stable")
      ok = None
      if lock.family:
         ok_all = _allowed(lab, pal_lab, lock.hue_tol)
         use = ok_all.any(0)
         if not use.any():
            lock.kept += int(counts.sum())
            continue
         gpal, gpal_lab = pal[use], pal_lab[use]
         ok = ok_all[:, use][srt]
      pick = _assign(lab[srt], counts[srt].astype(float), gpal_lab, lock.keep_steps, lock.merge_cost, ok)
      key = (arr[:, :, 0].astype(np.int64) << 16) | (arr[:, :, 1].astype(np.int64) << 8) | arr[:, :, 2].astype(np.int64)
      for k, j in zip(srt, pick):
         c = cols[k]
         if (gpal[j] == c).all():
            continue
         if lock.family and (not ok[list(srt).index(k), j] or _too_far(lab[k], gpal_lab[j], lock)):
            lock.kept += int(counts[k])
            continue
         hit = sel & (key == (int(c[0]) << 16 | int(c[1]) << 8 | int(c[2])))
         arr[hit, :3] = gpal[j]
         changed += int(hit.sum())
   return changed


def _too_far(a: np.ndarray, b: np.ndarray, lock: Lock) -> bool:
   """family : ΔE 가 max_de 를 넘으면 잠그지 않는다 (계열 밖 짝은 ok 표가 따로 막는다)."""
   return float(np.sqrt(((a - b) ** 2).sum())) > lock.max_de
