"""P6 고리 3 — 골드 짝 하나 빼고 굽기(LOO). 「같은 도메인(렌더러 출력 → 우리 원본) 재료로 구운 표가 손 안 댐을 이기나」.

- 짝 : `train.local/gold/pairs.json` 의 ok 짝 중 얼굴 겹(`baseline.FACE`, 바뀐 칸 0)을 뺀 것. 짝 하나 = 그룹 하나.
- 입력 = 렌더러 출력(`render`), 목표 = `baseline.gold_target`(원본을 P 에 붙임, P5 와 같은 정의).
- 조각 대신 입력 그림 전체를 쓴다. 정수 칸 이동 증강은 안 한다 — 열쇠가 자리와 무관해 세기만 똑같이 불어난다.
- 견줌 넷 : ① 손 안 댐 ② CC0 표(씨앗 0) ③ LOO 표(나머지 골드 짝만) ④ CC0 세기 + 골드 세기 × N (덧쓰기).
- 곡선 : 학습 짝 수 4 · 8 · 전부 로 줄여 같은 LOO (부분집합 씨앗 3).
- 지표 : 뺀 짝마다 `baseline.pair_counts` → 짝마다 지표 넷 → 평균 · σ(짝 사이), 짝 Δ(방법 − 손 안 댐) 평균 ± σ.

출력 `train.local/loo/loo.json` · `loo.md` · CC0 세기 캐시 `cc0_counts_seed0.npz`.
사용 (ArtTool 폴더에서) : .venv/Scripts/python -I train/polish/loo.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "train" / "polish"))

from arttool import image  # noqa: E402
from arttool.shape.polish import keys, load_model  # noqa: E402

import baseline  # noqa: E402
import table  # noqa: E402

METRICS = ("changed_hit", "unchanged_keep", "cell_acc", "near_shifted")
WEIGHTS = (100, 1000)       # ④ 골드 세기 무게
SIZES = (4, 8)              # 곡선 : 학습 짝 수 (끝 칸은 전부 = n − 1)
CURVE_SEEDS = range(3)


def table_model(tables: dict, pal: np.ndarray, light: str = "top_left") -> dict:
   """세운 표 → `polish.predict` 가 받는 모델 사전 (파일 없이 메모리에서)."""
   return {"engine": "table", "palette": pal, "light": light, "file": None,
           "tables": [(tables[n][0], tables[n][1]) for n in range(len(tables))]}


def metrics(c: dict, side: str) -> dict:
   """`pair_counts` 한 짝 → 지표 넷."""
   m = c[side]
   return {"changed_hit": m["changed_hit"] / max(m["changed"], 1), "unchanged_keep": m["unchanged_keep"] / max(m["unchanged"], 1),
           "cell_acc": m["cell_hit"] / max(m["cells"], 1), "near_shifted": m["near"]}


def summarize(per: list[dict], base: list[dict]) -> dict:
   """짝마다 지표 → 평균 · σ · 짝 Δ 평균 ± σ · Δ > 2σ."""
   out = {}
   for k in METRICS:
      v = np.array([p[k] for p in per]); b = np.array([p[k] for p in base]); d = v - b
      out[k] = {"mean": float(v.mean()), "sd": float(v.std(ddof=1)), "delta": float(d.mean()), "delta_sd": float(d.std(ddof=1)),
                "delta_gt_2sd": bool(d.mean() > 2 * d.std(ddof=1))}
   return out


def loo(data: list[tuple], pal: np.ndarray, extra: dict | None = None, weight: float = 1.0,
        size: int | None = None, seed: int = 0) -> list[dict]:
   """data = [(그룹, 렌더, 목표, 열쇠)] → 뺀 짝마다 `pair_counts`. 학습은 뺀 짝을 뺀 나머지(size 면 그중 size 개).
   extra(세기) 를 주면 그 위에 골드 세기 × weight 를 얹는다."""
   k = len(pal)
   rng = np.random.default_rng(seed)
   out = []
   for i, (g, render, target, kk) in enumerate(data):
      rest = [j for j in range(len(data)) if j != i]
      if size is not None and size < len(rest):
         rest = sorted(rng.choice(rest, size, replace=False).tolist())
      assert all(data[j][0] != g for j in rest)   # 자기 그룹은 학습에 없다
      cnt = table.count([data[j][3] for j in rest], [data[j][2] for j in rest], [data[j][2].shape for j in rest], k)
      if extra is not None:
         cnt = table.merge(extra, cnt, weight)
      model = table_model(table.resolve(cnt, k), pal)
      out.append(baseline.pair_counts(model, render, target))
   return out


def cc0_counts(pairs_npz: Path, split_json: Path, pal: np.ndarray, cache: Path) -> dict:
   """CC0 씨앗 0 학습 조각 세기 (표 굽기와 같은 몫). 캐시가 있으면 읽는다."""
   if cache.exists():
      with np.load(cache) as z:
         return {n: (z[f"pair{n}"], z[f"cnt{n}"]) for n in range(table.LEVELS - 1)}
   val = set(json.loads(split_json.read_text(encoding="utf-8"))["splits"]["0"]["val"])
   d = np.load(pairs_npz)
   tr = np.array([g not in val for g in d["group"]])
   inputs, targets, hw = d["inputs"][tr], d["targets"][tr], d["hw"][tr]
   cnt = table.count(table.crop_keys(inputs, hw, pal, "top_left"), targets, hw, len(pal))
   cache.parent.mkdir(parents=True, exist_ok=True)
   np.savez_compressed(cache, **{f"pair{n}": cnt[n][0] for n in cnt}, **{f"cnt{n}": cnt[n][1] for n in cnt})
   return cnt


def load_pairs(gold_json: Path, pal: np.ndarray) -> list[tuple]:
   gp = [p for p in json.loads(gold_json.read_text(encoding="utf-8"))["pairs"] if p["ok"] and p["group"] not in baseline.FACE]
   out = []
   for p in gp:
      render = image.load(p["render"])
      target = baseline.gold_target(image.load(p["src"]), render, pal)
      out.append((p["group"], render, target, keys(render, pal)))
   return out


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--gold", default="train.local/gold/pairs.json")
   ap.add_argument("--model", default="models.local/polish/table-seed0.json", help="② CC0 표")
   ap.add_argument("--pairs", default="train.local/pairs/seed0.npz")
   ap.add_argument("--pretrain-split", default="train.local/pretrain_split.json")
   ap.add_argument("--out", default="train.local/loo")
   args = ap.parse_args(argv)
   sys.stdout.reconfigure(encoding="utf-8")
   out = Path(args.out)
   out.mkdir(parents=True, exist_ok=True)

   cc0 = load_model(args.model)
   pal = cc0["palette"]
   data = load_pairs(Path(args.gold), pal)
   groups = [d[0] for d in data]
   cc0_per = [baseline.pair_counts(cc0, r, t) for _, r, t, _ in data]
   base = [metrics(c, "untouched") for c in cc0_per]
   runs = {"cc0": [metrics(c, "table") for c in cc0_per],
           "loo": [metrics(c, "table") for c in loo(data, pal)]}
   extra = cc0_counts(Path(args.pairs), Path(args.pretrain_split), pal, out / "cc0_counts_seed0.npz")
   gold_cells = int(sum((d[2] != table.EMPTY).sum() for d in data))
   for w in WEIGHTS:
      runs[f"cc0+gold×{w}"] = [metrics(c, "table") for c in loo(data, pal, extra, w)]
   result = {"pairs": groups, "gold_cells": gold_cells, "cc0_cells": int(extra[0][1].sum()),
             "per_pair": {"untouched": base, **runs},
             "summary": {"untouched": summarize(base, base), **{k: summarize(v, base) for k, v in runs.items()}}}

   curve = {}
   for size in (*SIZES, len(data) - 1):
      seeds = CURVE_SEEDS if size < len(data) - 1 else (0,)
      rows = [summarize([metrics(c, "table") for c in loo(data, pal, size=size, seed=s)], base) for s in seeds]
      curve[size] = {k: {"delta": float(np.mean([r[k]["delta"] for r in rows])),
                         "delta_sd_pairs": float(np.mean([r[k]["delta_sd"] for r in rows])),
                         "delta_sd_seeds": float(np.std([r[k]["delta"] for r in rows], ddof=1)) if len(rows) > 1 else 0.0,
                         "mean": float(np.mean([r[k]["mean"] for r in rows]))} for k in METRICS}
   result["curve"] = curve
   (out / "loo.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
   (out / "loo.md").write_text(render_md(result), encoding="utf-8")
   print(render_md(result))
   return 0


def render_md(r: dict) -> str:
   n = len(r["pairs"])
   L = [f"# P6 고리 3 — 골드 짝 LOO ({n} 짝, 얼굴 겹 뺌)", "",
        f"> 짝마다 지표 → 평균 ± σ(짝 사이). 짝 Δ = 방법 − 손 안 댐 (같은 짝). 골드 칸 {r['gold_cells']} · CC0 세기 칸 {r['cc0_cells']}.", "",
        "| 방법 | 바뀐 칸 맞힘 | 지킴 | 칸 정확도 | near_shifted | 칸 정확도 짝 Δ ± σ | near 짝 Δ ± σ | 둘 다 Δ > 2σ · 지킴 ≥ .9 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |"]
   for name, s in r["summary"].items():
      ok = s["cell_acc"]["delta_gt_2sd"] and s["near_shifted"]["delta_gt_2sd"] and s["unchanged_keep"]["mean"] >= 0.9
      L.append(f"| {name} | " + " | ".join(f"{s[k]['mean']:.3f} ± {s[k]['sd']:.3f}" for k in METRICS) +
               f" | {s['cell_acc']['delta']:+.3f} ± {s['cell_acc']['delta_sd']:.3f} | {s['near_shifted']['delta']:+.3f} ± {s['near_shifted']['delta_sd']:.3f} | "
               f"{'예' if ok and name != 'untouched' else '아니오'} |")
   L += ["", "곡선 (LOO 표, 학습 짝 수별 · 부분집합 씨앗 3 평균. σ = 짝 사이 / 씨앗 사이) :", "",
         "| 학습 짝 수 | 지킴 | 칸 정확도 | 칸 정확도 짝 Δ | near 짝 Δ |", "| --- | --- | --- | --- | --- |"]
   for size, c in r["curve"].items():
      L.append(f"| {size} | {c['unchanged_keep']['mean']:.3f} | {c['cell_acc']['mean']:.3f} | "
               f"{c['cell_acc']['delta']:+.3f} (σ {c['cell_acc']['delta_sd_pairs']:.3f} / {c['cell_acc']['delta_sd_seeds']:.3f}) | "
               f"{c['near_shifted']['delta']:+.3f} (σ {c['near_shifted']['delta_sd_pairs']:.3f} / {c['near_shifted']['delta_sd_seeds']:.3f}) |")
   L += ["", "짝마다 칸 정확도 (손 안 댐 / CC0 / LOO) :", "", "| 짝 | 손 안 댐 | CC0 | LOO |", "| --- | --- | --- | --- |"]
   pp = r["per_pair"]
   for i, g in enumerate(r["pairs"]):
      L.append(f"| {g} | {pp['untouched'][i]['cell_acc']:.3f} | {pp['cc0'][i]['cell_acc']:.3f} | {pp['loo'][i]['cell_acc']:.3f} |")
   return "\n".join(L) + "\n"


if __name__ == "__main__":
   raise SystemExit(main())
