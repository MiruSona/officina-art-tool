"""P1 ② 그룹 단위 학습 · 검증 · 시험 분할 → `train.local/split.json`, 얼림 `train.local/frozen.json`.

- 우리 그룹은 종류(icon · building · character · cc0)로 층을 나눠 씨앗 고정으로 섞고 70 / 15 / 15.
  층마다 따로 반올림하면 작은 층이 0 이 되어 시험이 모자란다. 그래서 전체 몫(15%)을 먼저 정하고
  층마다 소수 몫이 큰 순서로 한 장씩 나눠 준다(최대 나머지 방식).
- 바깥 CC0 묶음 그룹은 모두 사전학습 몫. 우리 그림과 겹쳐 끌려 온 그림은 빼고 따로 적는다.
- 얼림 : groups.json · split.json 의 sha256 을 frozen.json 에 적는다. frozen.json 이 이미 있으면
  `--refreeze` 없이는 덮지 않는다(판 사이에 분할을 안 바꾼다 — 설계 2절).

사용 (ArtTool 폴더에서) : python -I train/polish/split.py [--groups …] [--out …] [--frozen …]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

SEED = 20261108
SHARES = {"val": 0.15, "test": 0.15}


def _quota(sizes: dict[str, int], share: float) -> dict[str, int]:
   """층마다 몫 개수. 합이 round(전체 × share) 가 되게 최대 나머지 방식으로 나눈다."""
   want = {k: n * share for k, n in sizes.items()}
   got = {k: math.floor(v) for k, v in want.items()}
   left = round(sum(sizes.values()) * share) - sum(got.values())
   for k in sorted(want, key=lambda k: (-(want[k] - got[k]), k)):
      if left <= 0:
         break
      if got[k] < sizes[k]:
         got[k] += 1
         left -= 1
   return got


def split_groups(groups: list[dict], seed: int = SEED) -> dict:
   strata: dict[str, list[str]] = defaultdict(list)
   for g in groups:
      if g["side"] == "ours":
         strata[g["kind"]].append(g["id"])
   sizes = {k: len(v) for k, v in strata.items()}
   val_n, test_n = _quota(sizes, SHARES["val"]), _quota(sizes, SHARES["test"])

   rng = random.Random(seed)
   out = {"train": [], "val": [], "test": []}
   by_kind = {}
   for kind in sorted(strata):
      ids = sorted(strata[kind])
      rng.shuffle(ids)
      t, v = test_n[kind], val_n[kind]
      part = {"test": ids[:t], "val": ids[t:t + v], "train": ids[t + v:]}
      for name, chosen in part.items():
         out[name] += chosen
      by_kind[kind] = {name: len(chosen) for name, chosen in part.items()}

   pretrain = [g["id"] for g in groups if g["side"] == "pack"]
   pulled = sorted(i for g in groups if g["side"] == "ours" for i in g.get("pulled_from_packs", []))
   return {"version": 1, "seed": seed, "shares": SHARES, **{k: sorted(v) for k, v in out.items()},
           "by_kind": by_kind, "pretrain_groups": pretrain, "pulled_from_pretrain_items": pulled}


def _sha256(path: Path) -> str:
   return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--groups", default="train.local/groups.json")
   ap.add_argument("--out", default="train.local/split.json")
   ap.add_argument("--frozen", default="train.local/frozen.json")
   ap.add_argument("--refreeze", action="store_true", help="이미 얼린 분할을 덮는다 (판 사이에는 쓰지 않는다)")
   args = ap.parse_args(argv)

   groups_path, out_path, frozen_path = Path(args.groups), Path(args.out), Path(args.frozen)
   if frozen_path.exists() and not args.refreeze:
      print(f"이미 얼렸다 : {frozen_path}. 다시 나누려면 --refreeze", file=sys.stderr)
      return 2
   result = split_groups(json.loads(groups_path.read_text(encoding="utf-8"))["groups"])
   out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
   frozen = {"seed": result["seed"], "files": {p.name: _sha256(p) for p in (groups_path, out_path)}}
   frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=1), encoding="utf-8")
   counts = {k: len(result[k]) for k in ("train", "val", "test", "pretrain_groups")}
   print(json.dumps({"counts": counts, "by_kind": result["by_kind"], "frozen": frozen}, ensure_ascii=False, indent=1))
   return 0


if __name__ == "__main__":
   sys.exit(main())
