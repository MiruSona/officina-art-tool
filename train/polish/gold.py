"""P2 골드 셋 : 골드 홀 만들기 · 골드 짝 목록 검증 · 둘 얼리기 (작은 다듬기 모델 설계 2절).

- **골드 홀** (짝 없음) : 렌더러 실측 · 시험에 쓴 합성 명세(틀 preset · 부품 명세) × 보는 방향 × 질감 seed 를 렌더한다.
  우리 그림을 따라 그린 명세는 홀 원천 목록에 넣지 않는다 — 목록을 고르는 것은 사람 몫이고 이 파일은 그대로 돌린다.
  seed k 는 명세 맨 위 `texture` 규칙마다 seed 에 k × 101 을 더한다. 질감이 없는 명세는 k > 0 일 때 얼룩(mottle) 한 줄을 붙인다.
  같은 그림이 두 번 나오면(질감이 안 닿는 보기 등) 한 장만 두고, 빈 그림(불투명 칸 0)은 버린다.
- **골드 짝 검증** : 짝 목록(pairs.json)의 파일이 다 있는지, 렌더 · 원본으로 silhouette_iou 를 다시 셈해 적힌 값과 같은지,
  `ok` 가 문턱(iou_min)과 맞는지 본다. 짝 자체는 손으로 쓴 명세를 `arttool shape render --ref` 로 뽑아 만든다.
- **얼림** : pairs.json · holes.json 의 sha256 을 frozen.json 에 적는다. 이미 있으면 `--refreeze` 없이는 안 덮는다.

입력 경로는 모두 인자로 받는다(기본값은 `train.local/gold/` 아래). 이 파일에는 그림 경로를 적지 않는다.

사용 (ArtTool 폴더에서) :
  python -I train/polish/gold.py holes  [--sources …] [--gold …] [--seeds 3]
  python -I train/polish/gold.py verify [--gold …]
  python -I train/polish/gold.py freeze [--gold …] [--refreeze]
  python -I train/polish/gold.py all    [--sources …] [--gold …] [--seeds 3] [--refreeze]
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from arttool import image
from arttool.jsonio import read_json
from arttool.shape.kit import assemble
from arttool.shape.render import render
from arttool.shape.score import similarity
from arttool.shape.spec import parse
from arttool.shape.template import expand, is_template_spec

SEED_STEP = 101
DEFAULT_GOLD = "train.local/gold"
IOU_TOL = 1e-4     # 보고 값은 소수 넷째 자리로 반올림돼 있다


def reseed(data: dict, k: int) -> dict:
   """명세 사전의 질감 seed 를 k 번째 판으로 바꾼 사본. k = 0 이면 그대로."""
   out = copy.deepcopy(data)
   if k == 0:
      return out
   rules = out.get("texture")
   if rules:
      for rule in rules:
         rule["seed"] = int(rule.get("seed", 0)) + k * SEED_STEP
   else:
      out["texture"] = [{"kind": "mottle", "on": "*", "seed": k * SEED_STEP, "share": 0.2}]
   return out


def render_data(data: dict, base_dir: Path, where: str, view: str) -> np.ndarray:
   """`spec.load()` 와 같은 차례(틀 펼치기 → 부품 풀기 → 읽기)로 사전을 렌더한다."""
   if is_template_spec(data):
      data = expand(data, base_dir, where)
   data = assemble(data, base_dir, where)
   arr, _ = render(parse(data, where, base_dir), view)
   return arr


def make_holes(sources: list[dict], base_dir: Path, holes_dir: Path, seeds: int) -> tuple[list[dict], int]:
   """원천 목록 × 보는 방향 × seed 를 렌더해 holes_dir 에 PNG 로 둔다. (목록 줄, 겹치거나 빈 그림이라 버린 수)."""
   holes_dir.mkdir(parents=True, exist_ok=True)
   rows, seen, dup = [], set(), 0
   for src in sources:
      spec_path = (base_dir / src["spec"]).resolve()
      raw = read_json(spec_path)
      stem = src.get("name") or spec_path.name.split(".")[0]
      for view in src.get("views", ["front"]):
         for k in range(seeds):
            arr = render_data(reseed(raw, k), spec_path.parent, str(spec_path), view)
            if not (arr[:, :, 3] > 0).any():
               # 앞에서만 보이게 쓴 판 명세는 뒤에서 보면 빈 그림이 된다 — 홀로 쓸 것이 없다
               dup += 1
               continue
            digest = hashlib.sha256(arr.tobytes() + str(arr.shape).encode()).hexdigest()
            if digest in seen:
               dup += 1
               continue
            seen.add(digest)
            png = holes_dir / f"{stem}__{view}__s{k}.png"
            image.save(png, arr)
            rows.append({"name": png.stem, "spec": src["spec"], "view": view, "seed": k,
                         "size": [int(arr.shape[1]), int(arr.shape[0])], "png": png.name, "sha256": digest})
   return rows, dup


def verify_pairs(pairs: dict) -> list[str]:
   """짝 목록의 문제를 한 줄씩 돌려준다. 빈 목록이면 통과."""
   problems = []
   iou_min = pairs.get("iou_min", 0.85)
   for row in pairs["pairs"]:
      g = row["group"]
      if not Path(row["src"]).is_file():
         problems.append(f"{g} : 원본이 없다")
         continue
      if row.get("render") is None:
         if row.get("ok"):
            problems.append(f"{g} : 렌더가 없는데 ok")
         continue
      for key in ("spec", "render"):
         if not Path(row[key]).is_file():
            problems.append(f"{g} : {key} 파일이 없다")
      if not Path(row["render"]).is_file():
         continue
      img, ref = image.load(row["render"]), image.load(row["src"])
      if img.shape != ref.shape:
         problems.append(f"{g} : 크기가 다르다 {img.shape} · {ref.shape}")
         continue
      iou = similarity(img, ref)["silhouette_iou"]
      if abs(iou - (row.get("silhouette_iou") or -1)) > IOU_TOL:
         problems.append(f"{g} : iou 다시 셈 {iou} ≠ 적힌 값 {row.get('silhouette_iou')}")
      if bool(row.get("ok")) != (iou >= iou_min):
         problems.append(f"{g} : ok={row.get('ok')} 인데 iou {iou} (문턱 {iou_min})")
   return problems


def _sha256(path: Path) -> str:
   return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(gold: Path, refreeze: bool) -> dict:
   frozen = gold / "frozen.json"
   if frozen.exists() and not refreeze:
      raise SystemExit(f"이미 얼렸다 : {frozen}. 다시 얼리려면 --refreeze")
   out = {"files": {name: _sha256(gold / name) for name in ("pairs.json", "holes.json")}}
   frozen.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
   return out


def _holes(args) -> dict:
   gold, sources_path = Path(args.gold), Path(args.sources or Path(args.gold) / "hole_sources.json")
   sources = json.loads(sources_path.read_text(encoding="utf-8"))["sources"]
   rows, dup = make_holes(sources, sources_path.parent, gold / "holes", args.seeds)
   (gold / "holes.json").write_text(json.dumps({"version": 1, "seeds": args.seeds, "holes": rows}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
   return {"holes": len(rows), "dropped_duplicates": dup}


def _verify(args) -> list[str]:
   pairs = json.loads((Path(args.gold) / "pairs.json").read_text(encoding="utf-8"))
   return verify_pairs(pairs)


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("command", choices=["holes", "verify", "freeze", "all"])
   ap.add_argument("--gold", default=DEFAULT_GOLD)
   ap.add_argument("--sources", help="홀 원천 목록 JSON (기본 <gold>/hole_sources.json). 명세 경로는 이 파일 폴더 기준")
   ap.add_argument("--seeds", type=int, default=3)
   ap.add_argument("--refreeze", action="store_true")
   args = ap.parse_args(argv)

   report: dict = {}
   if args.command in ("holes", "all"):
      report.update(_holes(args))
   if args.command in ("verify", "freeze", "all"):
      problems = _verify(args)
      report["pair_problems"] = problems
      if problems:
         print(json.dumps(report, ensure_ascii=False, indent=1))
         return 1
   if args.command in ("freeze", "all"):
      report["frozen"] = freeze(Path(args.gold), args.refreeze)
   print(json.dumps(report, ensure_ascii=False, indent=1))
   return 0


if __name__ == "__main__":
   sys.exit(main())
