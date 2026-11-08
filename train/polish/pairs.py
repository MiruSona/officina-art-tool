"""P6 ② 학습 짝 — CC0 사전학습 그림 → (입력 = 납작화, 목표 = 팔레트 P 에 붙인 그림) 조각 (설계 1-3 · 3 · 5절).

- 재료는 `split.json` 의 `pretrain_groups` 만. 우리 그림은 절대 안 읽는다. 우리 그림과 겹쳐 끌려 온 그림도 뺀다.
- 목표 : 그림을 `lock.apply`(family) 로 P 에 붙이고, 계열 문턱에 걸려 안 붙은 색은 가장 가까운 P 색으로 붙인다(목표 ⊂ P).
- 입력 : 그 목표를 `flatten(seed)` 한 그림. 씨앗 8개(그림 번호 × 8 + 0..7) 중 그림마다 2개.
- 바뀐 칸 몫(목표 ≠ 입력을 P 에 붙인 색) < .02 인 짝은 뺀다 (음영 없는 타일 — 학습 · 평가 둘 다에서). 뺀 수는 점검표에.
- 조각 : 불투명 테두리(+1칸)로 자른 뒤, 한 변이 48 이하면 통째로 한 조각, 크면 32 ~ 48px 무작위 자르기(정수 칸 이동).
  불투명 몫 ≥ .3 만. 뒤집기 · 색조 돌리기 없음(빛 방향 · 화풍). 그룹당 조각 수 상한 = 평균의 3배.
- 큰 그림(시트)은 먼저 96칸 블록으로 나눈다 — `regions` 가 큰 그림에서 느리고, 시트는 어차피 남남인 그림 모음이다.
- 검증 분할 : 사전학습 그룹의 5% 를 씨앗 고정으로 뗀다(그룹 단위) → `pretrain_split.json` 에 씨앗 0 ~ 4 를 얼린다.

출력 `train.local/pairs/seed{S}.npz` (inputs (N,48,48,4) · targets (N,48,48) 팔레트 번호, 투명 255 · hw (N,2) · item · group · pack · fseed)
· `seed{S}.json` (그 씨앗의 학습 전 점검표, 설계 5절 멈춤 규칙 4) · `--merge-check` 로 모은 `train.local/pairs_check.json`.

사용 (ArtTool 폴더에서) : .venv/Scripts/python -I train/polish/pairs.py --seed 0
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "train" / "polish"))

from arttool import image  # noqa: E402
from arttool.shape import lock as lock_mod  # noqa: E402
from arttool.shape.flatten import flatten, regions  # noqa: E402
from arttool.shape.polish import nearest  # noqa: E402

import palette as palette_mod  # noqa: E402

CANVAS = 48
CROP = (32, 48)
SEEDS_PER_IMAGE = 2
SEED_POOL = 8
MIN_OPAQUE = 0.3
MIN_CHANGED = 0.02   # 바뀐 칸 몫이 이보다 적은 짝(음영이 원래 없는 타일)은 뺀다 — 배울 것이 없고 지표만 부풀린다 (메인 결정, 고리 2)
FLATTEN_REV = 2      # 이 짝을 구운 납작화 판 (flatten.py 고리 2 고침 뒤)
BLOCK = 96
GROUP_CAP = 3.0         # 그룹당 조각 상한 = 평균 × 이것
VAL_SHARE = 0.05
SPLIT_SEEDS = range(5)
EMPTY = 255


def pretrain_split(groups: list[str], seed: int) -> dict:
   """사전학습 그룹 → {train, val} (그룹 단위, 씨앗 고정)."""
   ids = sorted(groups)
   rng = np.random.default_rng(seed)
   val = sorted(rng.choice(ids, size=round(len(ids) * VAL_SHARE), replace=False).tolist())
   return {"seed": seed, "val": val}


def target_of(arr: np.ndarray, lock: lock_mod.Lock, pal: np.ndarray) -> np.ndarray:
   """그림 → P 에 붙인 그림. family 잠금 뒤 남은 P 밖 색은 가장 가까운 P 색."""
   out = arr.copy()
   solid = out[:, :, 3] > 0
   out[~solid] = 0
   out[:, :, 3] = np.where(solid, 255, 0)   # 반투명은 불투명으로 — 렌더러 출력에 반투명이 없다
   labels, _ = regions(out)
   lock_mod.apply(lock, out, labels)
   out[solid, :3] = pal[nearest(out[solid][:, :3], pal)]
   return out


def blocks(arr: np.ndarray):
   """큰 그림 → BLOCK 칸 블록들 (작으면 그대로)."""
   h, w = arr.shape[:2]
   if h <= BLOCK and w <= BLOCK:
      yield arr
      return
   for y in range(0, h, BLOCK):
      for x in range(0, w, BLOCK):
         yield arr[y:y + BLOCK, x:x + BLOCK]


def trim(arr: np.ndarray) -> np.ndarray | None:
   """불투명 테두리 + 1칸(캔버스 안)으로 자른다. 빈 그림이면 None."""
   ys, xs = np.nonzero(arr[:, :, 3] > 0)
   if not len(ys):
      return None
   return arr[max(ys.min() - 1, 0):ys.max() + 2, max(xs.min() - 1, 0):xs.max() + 2]


def crops(h: int, w: int, rng: np.random.Generator) -> list[tuple[int, int, int, int]]:
   """(y, x, ch, cw) 자르기 창. 한 변이 48 이하면 통째로, 크면 32 ~ 48 무작위."""
   if h <= CANVAS and w <= CANVAS:
      return [(0, 0, h, w)]
   n = int(min(8, np.ceil(h * w / 40.0 ** 2)))
   out = []
   for _ in range(n):
      ch, cw = (min(int(rng.integers(CROP[0], CROP[1] + 1)), d) for d in (h, w))
      out.append((int(rng.integers(0, h - ch + 1)), int(rng.integers(0, w - cw + 1)), ch, cw))
   return out


def build(seed: int, groups_path: Path, split_path: Path, palette_path: Path, ext_root: Path, limit: int | None = None):
   groups = json.loads(groups_path.read_text(encoding="utf-8"))
   split = json.loads(split_path.read_text(encoding="utf-8"))
   pre = set(split["pretrain_groups"])
   pulled = set(split.get("pulled_from_pretrain_items", []))
   pal = np.array(palette_mod.load(palette_path), dtype=np.int64)
   lock = lock_mod.Lock([tuple(int(v) for v in c) for c in pal], family=True)
   items = [(n, it) for n, it in enumerate(groups["items"]) if it["group"] in pre and n not in pulled]
   if limit:
      items = items[:limit]
   rows = defaultdict(list)
   dropped: Counter = Counter()
   started = time.perf_counter()
   for k, (n, it) in enumerate(items):
      s = int(it.get("scale") or 1)
      arr = image.load(ext_root / it["path"])[::s, ::s]
      rng = np.random.default_rng([seed, n])
      fseeds = sorted(int(v) for v in rng.choice(SEED_POOL, size=SEEDS_PER_IMAGE, replace=False))
      for block in blocks(arr):
         part = trim(block)
         if part is None:
            continue
         target = target_of(part, lock, pal)
         tidx = np.where(target[:, :, 3] > 0, nearest(target[:, :, :3], pal), EMPTY).astype(np.uint8)
         for f in fseeds:
            flat, _ = flatten(target, n * SEED_POOL + f)
            for y, x, ch, cw in crops(*part.shape[:2], rng):
               win = tidx[y:y + ch, x:x + cw]
               if (win != EMPTY).mean() < MIN_OPAQUE:
                  continue
               fwin = flat[y:y + ch, x:x + cw]
               solid = win != EMPTY
               if (nearest(fwin[:, :, :3], pal)[solid] != win[solid]).mean() < MIN_CHANGED:
                  dropped[it.get("pack", "?").split("/")[0]] += 1
                  continue
               inp = np.zeros((CANVAS, CANVAS, 4), np.uint8)
               tgt = np.full((CANVAS, CANVAS), EMPTY, np.uint8)
               inp[:ch, :cw] = fwin
               tgt[:ch, :cw] = win
               rows["inputs"].append(inp)
               rows["targets"].append(tgt)
               rows["hw"].append((ch, cw))
               rows["item"].append(n)
               rows["group"].append(it["group"])
               rows["pack"].append(it.get("pack", "?").split("/")[0])
               rows["fseed"].append(n * SEED_POOL + f)
      if k % 500 == 0:
         print(f"  {k}/{len(items)} · 조각 {len(rows['item'])} · {time.perf_counter() - started:.0f}s", flush=True)
   out = cap_groups(rows, seed)
   out["dropped_unchanged"] = dict(sorted(dropped.items()))
   return out, pal


def cap_groups(rows: dict, seed: int) -> dict:
   """그룹당 조각 수 상한 = 평균 × GROUP_CAP. 넘는 그룹은 씨앗 고정으로 골라 줄인다."""
   by = defaultdict(list)
   for i, g in enumerate(rows["group"]):
      by[g].append(i)
   cap = int(np.ceil(np.mean([len(v) for v in by.values()]) * GROUP_CAP))
   rng = np.random.default_rng(seed)
   keep = sorted(i for v in by.values() for i in (v if len(v) <= cap else rng.choice(v, cap, replace=False).tolist()))
   out = {k: [v[i] for i in keep] for k, v in rows.items()}
   out["cap"] = cap
   out["capped_groups"] = sum(1 for v in by.values() if len(v) > cap)
   return out


def check(rows: dict, split: dict, pal: np.ndarray, ours_groups: set[str]) -> dict:
   """학습 전 점검표 (설계 5절 멈춤 규칙 4) : 그룹 겹침 · 종류별 조각 수 · 팔레트 색별 목표 칸 수."""
   val = set(split["val"])
   groups = set(rows["group"])
   tr_g, va_g = groups - val, groups & val
   tg = np.stack(rows["targets"])
   va_rows = np.array([g in val for g in rows["group"]])
   counts = np.bincount(tg[tg != EMPTY], minlength=len(pal))
   counts_tr = np.bincount(tg[~va_rows][tg[~va_rows] != EMPTY], minlength=len(pal))
   warn = []
   overlap = len(tr_g & va_g) + len(groups & ours_groups)
   if overlap:
      warn.append(f"그룹 겹침 {overlap}")
   zero = [int(i) for i in np.nonzero(counts_tr == 0)[0]]
   if zero:
      warn.append(f"학습 몫 목표 칸이 0 인 팔레트 색 {len(zero)}개 : {zero}")
   return {"split_seed": split["seed"], "crops": len(rows["group"]), "crops_val": int(va_rows.sum()),
           "groups_train": len(tr_g), "groups_val": len(va_g), "group_overlap": overlap,
           "by_pack": dict(sorted(Counter(rows["pack"]).items())),
           "by_pack_val": dict(sorted(Counter(p for p, v in zip(rows["pack"], va_rows) if v).items())),
           "group_cap": rows["cap"], "capped_groups": rows["capped_groups"],
           "target_cells_by_color": counts.tolist(), "target_cells_by_color_train": counts_tr.tolist(),
           "flatten_rev": FLATTEN_REV, "min_changed": MIN_CHANGED,
           "dropped_unchanged": rows["dropped_unchanged"], "dropped_unchanged_total": sum(rows["dropped_unchanged"].values()),
           "warnings": warn}


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--seed", type=int, default=0, help="짝 씨앗 = 검증 분할 씨앗 (0 ~ 4)")
   ap.add_argument("--groups", default="train.local/groups.json")
   ap.add_argument("--split", default="train.local/split.json")
   ap.add_argument("--palette", default="models.local/polish/palette.json")
   ap.add_argument("--external", default="external.local")
   ap.add_argument("--out", default="train.local/pairs")
   ap.add_argument("--pretrain-split", default="train.local/pretrain_split.json")
   ap.add_argument("--limit", type=int, help="앞 N 장만 (시험용)")
   ap.add_argument("--merge-check", action="store_true", help="seed*.json 점검표를 pairs_check.json 하나로 모은다 (씨앗을 나란히 돌린 뒤)")
   args = ap.parse_args(argv)
   sys.stdout.reconfigure(encoding="utf-8")
   out = Path(args.out)
   if args.merge_check:
      merged = {f.stem[4:]: json.loads(f.read_text(encoding="utf-8")) for f in sorted(out.glob("seed*.json"))}
      (out.parent / "pairs_check.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
      print(f"점검표 {len(merged)}판 → {out.parent / 'pairs_check.json'}")
      return 0
   out.mkdir(parents=True, exist_ok=True)

   split = json.loads(Path(args.split).read_text(encoding="utf-8"))
   ps_path = Path(args.pretrain_split)
   if not ps_path.exists():
      # 얼림 : 한 번 쓰면 안 바꾼다 (판 사이 자 고정)
      frozen = {"version": 1, "share": VAL_SHARE, "splits": {str(s): pretrain_split(split["pretrain_groups"], s) for s in SPLIT_SEEDS}}
      ps_path.write_text(json.dumps(frozen, indent=1), encoding="utf-8")
   ps = json.loads(ps_path.read_text(encoding="utf-8"))
   vsplit = ps["splits"][str(args.seed)]

   rows, pal = build(args.seed, Path(args.groups), Path(args.split), Path(args.palette), Path(args.external), args.limit)
   groups = json.loads(Path(args.groups).read_text(encoding="utf-8"))
   ours = {g["id"] for g in groups["groups"] if g["side"] == "ours"}
   report = check(rows, vsplit, pal, ours)
   report["pretrain_split_sha256"] = hashlib.sha256(ps_path.read_bytes()).hexdigest()
   report["pair_seed"] = args.seed
   np.savez_compressed(out / f"seed{args.seed}.npz", inputs=np.stack(rows["inputs"]), targets=np.stack(rows["targets"]),
                       hw=np.array(rows["hw"], np.int16), item=np.array(rows["item"], np.int32),
                       group=np.array(rows["group"]), pack=np.array(rows["pack"]), fseed=np.array(rows["fseed"], np.int32))
   (out / f"seed{args.seed}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
   print(f"seed {args.seed} : 조각 {report['crops']} (검증 {report['crops_val']}) · 그룹 {report['groups_train']}/{report['groups_val']}"
         f" · 종류 {report['by_pack']} · 경고 {report['warnings']}")
   return 0


if __name__ == "__main__":
   raise SystemExit(main())
