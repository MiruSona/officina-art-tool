"""P6 ③ 이웃 표 기준선 — 학습 짝 → 「열쇠 → 팔레트 번호」 표 · 모델 JSON · 검증 지표 (설계 4 · 5 · 7절).

- 열쇠 셈은 `arttool.shape.polish.keys()` 를 그대로 부른다 (추론과 같은 함수).
- 사다리 칸(0 · 1 · 2)마다 (열쇠, 목표 번호) 를 세어 열쇠마다 가장 많이 본 번호를 답으로 둔다.
  사다리 0칸은 본 수 ≥ 2 인 열쇠만 둔다. 칸마다 열쇠 상한 50만 — 넘으면 적게 본 열쇠부터 지운다. 마지막 칸(입력 색 그대로)은 표가 없다.
- 학습 = 짝 중 검증 그룹이 아닌 것, 검증 = `pretrain_split.json` 의 같은 씨앗 val 그룹 짝.

검증 지표 (불투명 칸, 「손 안 댐」 = 입력을 팔레트에 붙이기만 한 것) :
| 지표 | 뜻 |
| --- | --- |
| changed_hit | 목표 ≠ 손 안 댐 인 칸 중 맞힌 몫 (주) |
| unchanged_keep | 목표 = 손 안 댐 인 칸 중 그대로 둔 몫 (지킴) |
| near_shifted | 조각마다 `score.similarity` 평균 (보조) |
| ladder | 사다리 칸마다 답한 칸 몫 |

출력 : `--model-dir` 에 `table-seed{S}.npz` · `table-seed{S}.json`, `--eval` 에 지표 JSON.
사용 (ArtTool 폴더에서) : .venv/Scripts/python -I train/polish/table.py --seed 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from arttool.palette import to_hex  # noqa: E402
from arttool.shape.polish import LEVELS, keys, load_model, nearest, polish  # noqa: E402
from arttool.shape.score import similarity  # noqa: E402

CAP = 500_000
MIN_SEEN0 = 2       # 사다리 0칸(전체 열쇠)은 본 수가 이 이상일 때만 답한다 — 한 번 본 열쇠가 검정 점 잡음을 냈다 (고리 2)
EMPTY = 255


def crop_keys(inputs: np.ndarray, hw: np.ndarray, pal: np.ndarray, light: str) -> list[np.ndarray]:
   """조각마다 (LEVELS, h, w) 열쇠. 조각 크기만큼만 셈한다(48 캔버스 채움 칸은 뺀다)."""
   return [keys(inp[:h, :w], pal, light) for inp, (h, w) in zip(inputs, hw)]


def count(key_list: list[np.ndarray], targets, hw, k: int) -> dict:
   """사다리 칸마다 (열쇠 × k + 목표 번호, 본 수). 목표가 빈(EMPTY) 칸은 안 센다."""
   out = {}
   for n in range(LEVELS - 1):
      ks, ts = [], []
      for kk, tgt, (h, w) in zip(key_list, targets, hw):
         t = tgt[:h, :w].astype(np.int64)
         solid = (kk[n] >= 0) & (t != EMPTY)
         ks.append(kk[n][solid])
         ts.append(t[solid])
      out[n] = np.unique((np.concatenate(ks) * k + np.concatenate(ts)) if ks else np.zeros(0, np.int64), return_counts=True)
   return out


def merge(a: dict, b: dict, weight_b: float = 1.0) -> dict:
   """두 세기를 합친다 (b 쪽 본 수 × weight_b). CC0 표 위에 골드 짝 덧쓰기에 쓴다."""
   out = {}
   for n in a:
      pair = np.concatenate([a[n][0], b[n][0]])
      cnt = np.concatenate([a[n][1].astype(float), b[n][1] * float(weight_b)])
      u, inv = np.unique(pair, return_inverse=True)
      out[n] = (u, np.bincount(inv.reshape(-1), weights=cnt))
   return out


def resolve(counts: dict, k: int, cap: int = CAP) -> dict:
   """세기 → 사다리 칸마다 (열쇠 정렬, 답 번호, 본 수)."""
   tables = {}
   for n, (pair, cnt) in counts.items():
      key, lab = pair // k, pair % k
      if not len(pair):
         tables[n] = (key, lab.astype(np.uint8), cnt)
         continue
      # 열쇠마다 가장 많이 본 번호 : (열쇠 오름, 수 내림) 정렬 뒤 열쇠마다 첫 줄
      order = np.lexsort((-cnt, key))
      key, lab, cnt = key[order], lab[order], cnt[order]
      first = np.r_[True, key[1:] != key[:-1]]
      total = np.add.reduceat(cnt, np.nonzero(first)[0]) if len(key) else cnt
      key, lab = key[first], lab[first]
      if n == 0:
         seen = total >= MIN_SEEN0   # 표에서 빼면 추론이 사다리 1칸으로 물러난다
         key, lab, total = key[seen], lab[seen], total[seen]
      if len(key) > cap:
         keep = np.sort(np.argsort(-total, kind="stable")[:cap])
         key, lab, total = key[keep], lab[keep], total[keep]
      tables[n] = (key, lab.astype(np.uint8), total)
   return tables


def fit(key_list: list[np.ndarray], targets, hw, k: int, cap: int = CAP) -> dict:
   """사다리 칸마다 (열쇠 정렬, 답 번호, 본 수)."""
   return resolve(count(key_list, targets, hw, k), k, cap)


def save(tables: dict, pal: np.ndarray, light: str, model_dir: Path, seed: int, split_sha: str, extra: dict) -> Path:
   model_dir.mkdir(parents=True, exist_ok=True)
   npz = model_dir / f"table-seed{seed}.npz"
   np.savez_compressed(npz, **{f"keys{n}": t[0] for n, t in tables.items()}, **{f"vals{n}": t[1] for n, t in tables.items()})
   meta = {"version": 1, "kind": "shape_polish", "engine": "table", "file": npz.name,
           "sha256": hashlib.sha256(npz.read_bytes()).hexdigest(), "palette": [to_hex(tuple(int(v) for v in c)) for c in pal],
           "light": light, "train": {"seed": seed, "split_sha256": split_sha, **extra}}
   out = model_dir / f"table-seed{seed}.json"
   out.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
   return out


def evaluate(model: dict, inputs: np.ndarray, targets: np.ndarray, hw: np.ndarray, packs: np.ndarray) -> dict:
   """검증 조각 → 지표 (표 · 손 안 댐 나란히)."""
   pal = model["palette"]
   acc = {"changed": 0, "changed_hit": 0, "unchanged": 0, "unchanged_keep": 0, "cells": 0, "hit_all": 0, "base_hit_all": 0}
   ladder = np.zeros(LEVELS, np.int64)
   near_t, near_b = [], []
   by_pack: dict[str, list[int]] = {}
   for inp, tgt, (h, w), pack in zip(inputs, targets, hw, packs):
      x = inp[:h, :w]
      t = tgt[:h, :w].astype(np.int64)
      solid = t != EMPTY
      out, rep = polish(model, x)
      pick = np.where(solid, nearest(out[:, :, :3], pal), -1)
      base = np.where(solid, nearest(x[:, :, :3], pal), -1)
      ch = solid & (t != base)
      acc["changed"] += int(ch.sum())
      acc["changed_hit"] += int((ch & (pick == t)).sum())
      acc["unchanged"] += int((solid & ~ch).sum())
      acc["unchanged_keep"] += int((solid & ~ch & (pick == t)).sum())
      acc["cells"] += int(solid.sum())
      acc["hit_all"] += int((solid & (pick == t)).sum())
      acc["base_hit_all"] += int((solid & (base == t)).sum())
      ladder += np.array(rep["ladder"])
      ref = np.zeros_like(x)
      ref[solid, :3] = pal[t[solid]]
      ref[solid, 3] = 255
      based = x.copy()
      based[solid, :3] = pal[base[solid]]
      near_t.append(similarity(out, ref)["near_shifted"])
      near_b.append(similarity(based, ref)["near_shifted"])
      p = by_pack.setdefault(str(pack), [0, 0])
      p[0] += int(ch.sum())
      p[1] += int((ch & (pick == t)).sum())
   return {
      "crops": int(len(inputs)), "cells": acc["cells"],
      "changed_share": acc["changed"] / acc["cells"],
      "table": {"changed_hit": acc["changed_hit"] / max(acc["changed"], 1),
                "unchanged_keep": acc["unchanged_keep"] / max(acc["unchanged"], 1),
                "cell_acc": acc["hit_all"] / acc["cells"], "near_shifted": float(np.mean(near_t))},
      "untouched": {"changed_hit": 0.0, "unchanged_keep": 1.0, "cell_acc": acc["base_hit_all"] / acc["cells"],
                    "near_shifted": float(np.mean(near_b))},
      "ladder": (ladder / ladder.sum()).tolist(),
      "changed_hit_by_pack": {k: v[1] / max(v[0], 1) for k, v in sorted(by_pack.items())},
   }


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--seed", type=int, default=0)
   ap.add_argument("--pairs", default="train.local/pairs")
   ap.add_argument("--pretrain-split", default="train.local/pretrain_split.json")
   ap.add_argument("--palette", default="models.local/polish/palette.json")
   ap.add_argument("--model-dir", default="models.local/polish")
   ap.add_argument("--eval", default=None, help="지표 JSON (기본 train.local/table_eval/seed{S}.json)")
   ap.add_argument("--light", default="top_left")
   args = ap.parse_args(argv)
   sys.stdout.reconfigure(encoding="utf-8")

   ps_path = Path(args.pretrain_split)
   val = set(json.loads(ps_path.read_text(encoding="utf-8"))["splits"][str(args.seed)]["val"])
   data = np.load(Path(args.pairs) / f"seed{args.seed}.npz", allow_pickle=False)
   inputs, targets, hw, group, pack = data["inputs"], data["targets"], data["hw"], data["group"], data["pack"]
   is_val = np.array([g in val for g in group])
   pal_raw = json.loads(Path(args.palette).read_text(encoding="utf-8"))["colors"]
   pal = np.array([[int(h[i:i + 2], 16) for i in (1, 3, 5)] for h in pal_raw], np.int64)

   t0 = time.perf_counter()
   tr = ~is_val
   tables = fit(crop_keys(inputs[tr], hw[tr], pal, args.light), targets[tr], hw[tr], len(pal))
   fit_s = time.perf_counter() - t0
   sizes = {n: int(len(t[0])) for n, t in tables.items()}
   model_json = save(tables, pal, args.light, Path(args.model_dir), args.seed, hashlib.sha256(ps_path.read_bytes()).hexdigest(),
                     {"pairs": f"seed{args.seed}.npz", "crops": int(tr.sum()), "keys": sizes, "cap": CAP, "min_seen0": MIN_SEEN0,
                      "flatten_rev": json.loads((Path(args.pairs) / f"seed{args.seed}.json").read_text(encoding="utf-8")).get("flatten_rev", 1)})
   model = load_model(model_json)
   result = evaluate(model, inputs[is_val], targets[is_val], hw[is_val], pack[is_val])
   result.update({"seed": args.seed, "keys": sizes, "fit_s": round(fit_s, 1), "train_crops": int(tr.sum()),
                  "npz_bytes": Path(model["file"]).stat().st_size})
   out = Path(args.eval or f"train.local/table_eval/seed{args.seed}.json")
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
   print(json.dumps({k: result[k] for k in ("seed", "keys", "table", "untouched", "ladder", "changed_share")}, ensure_ascii=False))
   return 0


if __name__ == "__main__":
   raise SystemExit(main())
