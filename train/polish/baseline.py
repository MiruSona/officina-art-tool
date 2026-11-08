"""P5 바닥 재기 — 뒤 판이 「나아졌다」 · 「진짜와 섞인다」를 말할 때 쓸 잡음 바닥 넷 (설계 2절 끝 · 6절 · 8절 P5).

| 바닥 | 재는 법 |
| --- | --- |
| A/A (학습 잡음) | 골드 짝(입력 = 렌더러 출력, 목표 = 원본을 모델 팔레트에 붙인 것)에 표 씨앗 5 → 지표 넷의 씨앗 σ |
| 평가 잡음 | 골드 짝 그룹 단위 bootstrap 1000번 (지표 = 씨앗 5 평균) → 95% 구간 |
| 진짜 대 진짜 KID | 우리 그림 25 그룹 → 48px 조각 → 그룹 단위 반씩 20번 → 손 특징(표준화) KID → 평균 · 95% 위끝 |
| 진짜 대 진짜 C2ST | 같은 반쪽끼리 로지스틱(그룹 5겹) 균형 정확도 → .5 ± .1 인지 |

- 지표 셈은 `table.evaluate` 를 짝 하나씩 불러 몫을 칸 수로 되돌린 뒤 모은다 (셈이 둘로 갈라지지 않게).
- 얼굴 겹 짝(실루엣 · near 가 이미 1.0, 칸 수 수십)은 주 표에서 빼고 따로 싣는다 — 넣으면 「다 맞힘」 이 바닥을 흐린다.
- 손 특징 · 로지스틱 · 그룹 겹은 `shortcut.py`(P4) 것을 그대로 쓴다.

출력 `train.local/baseline/baseline.json` · `baseline.md` · `frozen.json`(둘의 sha256).
사용 (ArtTool 폴더에서) : .venv/Scripts/python -I train/polish/baseline.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "train" / "polish"))

from arttool import image  # noqa: E402
from arttool.profile import load_profile  # noqa: E402
from arttool.shape import lock as lock_mod  # noqa: E402
from arttool.shape.polish import load_model, nearest  # noqa: E402

import pairs  # noqa: E402
import shortcut  # noqa: E402
import table  # noqa: E402

SEEDS = range(5)
FACE = ("o00011", "o00013", "o00014")   # 얼굴 겹 짝 — 보고만
BOOT = 1000
SPLITS = 20
CROP = 48
MIN_OPAQUE = 0.3
GROUP_CAP = 3.0          # 그룹당 조각 상한 = 평균 × 이것 (pairs.GROUP_CAP 과 같은 뜻) — 11장 그룹 둘이 덮지 않게
KID_SUBSETS = 50
KID_SIZE = 100
C2ST_BAND = (0.4, 0.6)
METRICS = ("changed_hit", "unchanged_keep", "near_shifted", "cell_acc")


# --- 1 · 2 : 골드 짝 지표 ---


def gold_target(src: np.ndarray, render: np.ndarray, pal: np.ndarray) -> np.ndarray:
   """원본 → 팔레트 번호 (H, W). 원본이나 입력이 투명한 칸은 EMPTY — 모델은 알파를 안 바꾸니 그 칸은 셀 수 없다."""
   lock = lock_mod.Lock([tuple(int(v) for v in c) for c in pal], family=True)
   snapped = pairs.target_of(src, lock, pal)
   solid = (snapped[:, :, 3] > 0) & (render[:, :, 3] > 0)
   return np.where(solid, nearest(snapped[:, :, :3], pal), table.EMPTY).astype(np.uint8)


def pair_counts(model: dict, render: np.ndarray, target: np.ndarray) -> dict:
   """`table.evaluate` 를 짝 하나로 불러 몫을 칸 수로 되돌린다. near 는 짝 하나 값."""
   h, w = render.shape[:2]
   r = table.evaluate(model, render[None], target[None], np.array([[h, w]]), np.array(["gold"]))
   cells = r["cells"]
   changed = round(r["changed_share"] * cells)
   out = {}
   for side in ("table", "untouched"):
      m = r[side]
      out[side] = {"cells": cells, "changed": changed, "changed_hit": round(m["changed_hit"] * changed),
                   "unchanged": cells - changed, "unchanged_keep": round(m["unchanged_keep"] * (cells - changed)),
                   "cell_hit": round(m["cell_acc"] * cells), "near": m["near_shifted"]}
   return out


def pooled(c: np.ndarray) -> np.ndarray:
   """칸 수 (..., 짝, 7) → 지표 넷 (..., 4). 열 = cells · changed · changed_hit · unchanged · unchanged_keep · cell_hit · near."""
   s = c.sum(-2)
   return np.stack([s[..., 2] / np.maximum(s[..., 1], 1), s[..., 4] / np.maximum(s[..., 3], 1),
                    c[..., 6].mean(-1), s[..., 5] / np.maximum(s[..., 0], 1)], -1)


def _rows(counts: list[dict], side: str) -> np.ndarray:
   keys = ("cells", "changed", "changed_hit", "unchanged", "unchanged_keep", "cell_hit", "near")
   return np.array([[c[side][k] for k in keys] for c in counts], float)


def bootstrap(c: np.ndarray, n: int = BOOT, seed: int = 0) -> np.ndarray:
   """c (씨앗, 짝, 7) → 짝(= 그룹) 단위 복원 추출 n 번의 지표 (n, 4). 지표는 씨앗 평균."""
   rng = np.random.default_rng(seed)
   idx = rng.integers(0, c.shape[1], size=(n, c.shape[1]))
   return pooled(c[:, idx].transpose(1, 0, 2, 3)).mean(1)


def interval(samples: np.ndarray) -> list[list[float]]:
   return np.percentile(samples, [2.5, 97.5], axis=0).T.round(4).tolist()


def gold_floors(gold_json: Path, model_dir: Path) -> dict:
   gp = [p for p in json.loads(gold_json.read_text(encoding="utf-8"))["pairs"] if p["ok"]]
   models = [load_model(model_dir / f"table-seed{s}.json") for s in SEEDS]
   pal = models[0]["palette"]
   if any(not np.array_equal(m["palette"], pal) for m in models):
      raise SystemExit("표 씨앗들의 팔레트가 다르다 — 같은 자로 잴 수 없다")
   data = [(p, image.load(p["render"])) for p in gp]
   data = [(p, r, gold_target(image.load(p["src"]), r, pal)) for p, r in data]
   per = [[pair_counts(m, r, t) for _, r, t in data] for m in models]          # [씨앗][짝]
   groups = [p["group"] for p, _, _ in data]
   main = np.array([g not in FACE for g in groups])
   out = {"pairs_main": [g for g, k in zip(groups, main) if k], "pairs_face": [g for g, k in zip(groups, main) if not k]}
   for name, keep in (("main", main), ("face", ~main)):
      tab = np.stack([_rows([c for c, k in zip(row, keep) if k], "table") for row in per])   # (씨앗, 짝, 7)
      base = _rows([c for c, k in zip(per[0], keep) if k], "untouched")
      seed_vals = pooled(tab)                                                                  # (씨앗, 4)
      block = {"seeds": {m: seed_vals[:, i].round(4).tolist() for i, m in enumerate(METRICS)},
               "mean": dict(zip(METRICS, seed_vals.mean(0).round(4).tolist())),
               "sigma": dict(zip(METRICS, seed_vals.std(0, ddof=1).round(4).tolist())),
               "untouched": dict(zip(METRICS, pooled(base).round(4).tolist())),
               "changed_share": round(float(tab[0, :, 1].sum() / tab[0, :, 0].sum()), 4),
               "cells": int(tab[0, :, 0].sum())}
      if name == "main":
         block["boot_ci95"] = dict(zip(METRICS, interval(bootstrap(tab))))
         block["boot_ci95_untouched"] = dict(zip(METRICS, interval(bootstrap(base[None]))))
      out[name] = block
   return out


# --- 3 · 4 : 진짜 대 진짜 ---


def real_crops(arr: np.ndarray, rng: np.random.Generator) -> list[np.ndarray]:
   """그림 → 48px 조각 (불투명 몫 ≥ .3). 테두리를 먼저 잘라 내고, 48 이하면 통째로."""
   arr = pairs.trim(arr)
   if arr is None:
      return []
   h, w = arr.shape[:2]
   if h <= CROP and w <= CROP:
      wins = [(0, 0, h, w)]
   else:
      ch, cw = min(CROP, h), min(CROP, w)
      n = int(min(8, np.ceil(h * w / 40.0 ** 2)))
      wins = [(int(rng.integers(0, h - ch + 1)), int(rng.integers(0, w - cw + 1)), ch, cw) for _ in range(n)]
   out = [arr[y:y + ch, x:x + cw].copy() for y, x, ch, cw in wins]
   return [c for c in out if (c[:, :, 3] > 0).mean() >= MIN_OPAQUE]


def real_features(ours_json: Path, seed: int = 0) -> tuple[np.ndarray, np.ndarray, list[str]]:
   """우리 그림(그룹 있는 것) → (특징 (N, D), 그룹 (N,), 특징 이름)."""
   rng = np.random.default_rng(seed)
   prof = load_profile()
   by_group: dict[str, list[np.ndarray]] = {}
   for it in json.loads(ours_json.read_text(encoding="utf-8")):
      if it.get("group"):
         by_group.setdefault(it["group"], []).extend(real_crops(image.load(it["path"]), rng))
   cap = int(np.ceil(GROUP_CAP * np.mean([len(v) for v in by_group.values()])))
   names = [k for k, _ in shortcut.FEATURES]
   rows, groups = [], []
   for g, crops in sorted(by_group.items()):
      if len(crops) > cap:
         crops = [crops[i] for i in np.sort(rng.choice(len(crops), cap, replace=False))]
      for c in crops:
         f = shortcut.features(c, prof)
         rows.append([f[k] for k in names])
         groups.append(g)
   return np.array(rows, float), np.array(groups), names


def kid(x: np.ndarray, y: np.ndarray, subsets: int = KID_SUBSETS, size: int = KID_SIZE, seed: int = 0) -> float:
   """KID = 다항 커널 (x·y/d + 1)³ 의 불편 MMD², 부분집합 평균 (Bińkowski 2018 꼴)."""
   rng = np.random.default_rng(seed)
   d = x.shape[1]
   m = min(len(x), len(y), size)
   vals = []
   for _ in range(subsets):
      a = x[rng.choice(len(x), m, replace=False)]
      b = y[rng.choice(len(y), m, replace=False)]
      kxx, kyy, kxy = ((a @ a.T / d + 1) ** 3, (b @ b.T / d + 1) ** 3, (a @ b.T / d + 1) ** 3)
      vals.append((kxx.sum() - np.trace(kxx) + kyy.sum() - np.trace(kyy)) / (m * (m - 1)) - 2 * kxy.mean())
   return float(np.mean(vals))


def c2st(x: np.ndarray, y: np.ndarray, groups: np.ndarray, seed: int = 0) -> tuple[float, np.ndarray]:
   """그룹 5겹 로지스틱 → (균형 정확도, 겹 평균 무게 (D,)). 반쪽 조각 수가 달라 균형 정확도로 본다."""
   fold = shortcut.group_folds(list(groups), y, shortcut.FOLDS, seed)
   pred = np.full(len(y), -1)
   weights = []
   for f in range(shortcut.FOLDS):
      te = fold == f
      if not te.any() or len(np.unique(y[~te])) < 2:
         continue
      tr_x, te_x = shortcut._standardize(x[~te], x[te])
      w = shortcut.fit_logistic(tr_x, y[~te])
      weights.append(w[1:])
      pred[te] = (te_x @ w[1:] + w[0] > 0).astype(int)
   recall = [float((pred[y == s] == s).mean()) for s in (0, 1)]
   return float(np.mean(recall)), np.mean(weights, 0)


def real_floors(ours_json: Path, splits: int = SPLITS, seed: int = 0) -> dict:
   x, groups, names = real_features(ours_json, seed)
   z = (x - x.mean(0)) / np.where(x.std(0) > 0, x.std(0), 1.0)    # KID 는 진짜 전체로 표준화한 공간에서
   names_g = np.unique(groups)
   rng = np.random.default_rng(seed)
   kids, accs, ws = [], [], []
   for i in range(splits):
      half = set(rng.choice(names_g, len(names_g) // 2, replace=False).tolist())
      y = np.array([int(g in half) for g in groups])
      kids.append(kid(z[y == 0], z[y == 1], seed=i))
      acc, w = c2st(x, y, groups, seed=i)
      accs.append(acc)
      ws.append(np.abs(w))
   kids, accs = np.array(kids), np.array(accs)
   inside = C2ST_BAND[0] <= accs.mean() <= C2ST_BAND[1]
   return {"crops": int(len(x)), "groups": int(len(names_g)), "crops_per_group": {g: int((groups == g).sum()) for g in names_g},
           "kid": {"mean": round(float(kids.mean()), 5), "p95": round(float(np.percentile(kids, 95)), 5),
                   "max": round(float(kids.max()), 5), "splits": kids.round(5).tolist()},
           "c2st": {"mean": round(float(accs.mean()), 4), "std": round(float(accs.std()), 4),
                    "range": [round(float(accs.min()), 4), round(float(accs.max()), 4)], "inside_band": bool(inside),
                    "splits": accs.round(4).tolist(),
                    "abs_weight": dict(sorted(zip(names, np.mean(ws, 0).round(3).tolist()), key=lambda kv: -kv[1]))}}


# --- 보고 ---


def write_md(path: Path, r: dict) -> None:
   g, f, real = r["gold"]["main"], r["gold"]["face"], r["real"]
   lines = ["# P5 바닥", "", f"> 골드 짝 주 {len(r['gold']['pairs_main'])} · 얼굴 겹 {len(r['gold']['pairs_face'])} (보고만) · "
            f"진짜 {real['groups']} 그룹 {real['crops']} 조각", "",
            "## 1. A/A (표 씨앗 5)", "", "| 지표 | 평균 | σ | 2σ | 손 안 댐 |", "| --- | --- | --- | --- | --- |"]
   lines += [f"| {m} | {g['mean'][m]} | {g['sigma'][m]} | {round(2 * g['sigma'][m], 4)} | {g['untouched'][m]} |" for m in METRICS]
   lines += ["", "## 2. 평가 잡음 (그룹 bootstrap 1000, 95%)", "", "| 지표 | 표 (씨앗 평균) | 손 안 댐 |", "| --- | --- | --- |"]
   lines += [f"| {m} | {g['boot_ci95'][m]} | {g['boot_ci95_untouched'][m]} |" for m in METRICS]
   lines += ["", "## 3. 진짜 대 진짜 KID (반씩 20번)", "", "| 평균 | 95% 위끝 | 최대 |", "| --- | --- | --- |",
             f"| {real['kid']['mean']} | {real['kid']['p95']} | {real['kid']['max']} |", "",
             "## 4. 진짜 대 진짜 C2ST (균형 정확도)", "", "| 평균 | σ | 범위 | .5 ± .1 안 |", "| --- | --- | --- | --- |",
             f"| {real['c2st']['mean']} | {real['c2st']['std']} | {real['c2st']['range']} | {'예' if real['c2st']['inside_band'] else '아니오'} |", "",
             "## 얼굴 겹 짝 (보고만)", "", "| 지표 | 평균 | σ | 손 안 댐 |", "| --- | --- | --- | --- |"]
   lines += [f"| {m} | {f['mean'][m]} | {f['sigma'][m]} | {f['untouched'][m]} |" for m in METRICS]
   lines += ["", "## 이 바닥을 어디에 쓴다", "",
             "- A/A σ : 두 판(표 · U-Net)을 견줄 때 차이가 2σ 를 넘어야 「나아짐」 (설계 5 · 8절).",
             "- bootstrap 구간 : 모든 결과표의 골드 짝 지표 옆에 붙이는 평가 잡음.",
             "- KID 바닥 : 판별기(P9) 「KID ≤ 바닥 × 2」 의 바닥 = 95% 위끝.",
             "- C2ST : 손 특징이 그룹을 외우지 않는다는 확인. 밖이면 P9 C2ST 를 읽지 않는다.", ""]
   path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--gold", default="train.local/gold/pairs.json")
   ap.add_argument("--model-dir", default="models.local/polish")
   ap.add_argument("--ours", default="train.local/ours.json")
   ap.add_argument("--out", default="train.local/baseline")
   args = ap.parse_args(argv)
   sys.stdout.reconfigure(encoding="utf-8")
   out = Path(args.out)
   out.mkdir(parents=True, exist_ok=True)
   report = {"version": 1, "gold": gold_floors(Path(args.gold), Path(args.model_dir)), "real": real_floors(Path(args.ours))}
   (out / "baseline.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
   write_md(out / "baseline.md", report)
   frozen = {name: hashlib.sha256((out / name).read_bytes()).hexdigest() for name in ("baseline.json", "baseline.md")}
   (out / "frozen.json").write_text(json.dumps({"files": frozen}, indent=1), encoding="utf-8")
   print(json.dumps({"aa_sigma": report["gold"]["main"]["sigma"], "kid": report["real"]["kid"]["p95"],
                     "c2st": report["real"]["c2st"]["mean"]}, ensure_ascii=False))
   return 0


if __name__ == "__main__":
   raise SystemExit(main())
