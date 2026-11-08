"""P6 ① 모델 팔레트 P — 우리 그림 그룹(외부 CC0 뺌)에서 `arttool style extract` 로 64색 상한 → `models.local/polish/palette.json`.

설계 9절 결정 2 : P 는 우리 그림 화풍에서 뽑는다. P 는 색 값일 뿐이지만 우리 그림에서 왔으니 git 밖에 둔다.
우리 그림 경로는 `train.local/groups.json` 에서만 읽는다(이 파일에 안 적는다). 원본은 읽기만 하고,
style extract 가 폴더를 받으므로 임시 폴더에 번호 이름으로 복사해 넘긴다.

사용 (ArtTool 폴더에서) : .venv/Scripts/python -I train/polish/palette.py [--groups …] [--out …]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))   # -I 로 돌려도 arttool 을 찾게

from arttool import cli  # noqa: E402
from arttool.palette import load_ramps, to_hex  # noqa: E402

MAX_COLORS = 64
OURS_KINDS = ("icon", "character", "building")   # 외부 CC0(kind cc0) 는 뺀다


def our_paths(groups: dict) -> tuple[list[Path], int]:
   """우리 그룹 중 CC0 가 아닌 그룹의 그림 경로."""
   keep = {g["id"] for g in groups["groups"] if g["side"] == "ours" and g.get("kind") in OURS_KINDS}
   return [Path(i["path"]) for i in groups["items"] if i["side"] == "ours" and i["group"] in keep], len(keep)


def extract(paths: list[Path], out: Path) -> dict:
   with tempfile.TemporaryDirectory() as tmp:
      src, dst = Path(tmp) / "in", Path(tmp) / "out"
      src.mkdir()
      for n, p in enumerate(paths):
         shutil.copyfile(p, src / f"{n:04d}.png")
      report = cli.run(cli.build_parser().parse_args(
         ["style", "extract", "--in", str(src), "--out", str(dst), "--name", "polish", "--max-colors", str(MAX_COLORS)]))
      ramps = load_ramps(dst / "polish_palette.json")
   colors = sorted(ramps.colors())
   data = {"version": 1, "kind": "polish_palette", "max_colors": MAX_COLORS, "colors": [to_hex(c) for c in colors],
           "ramps": {k: [to_hex(c) for c in v] for k, v in ramps.ramps.items()},
           "outline": to_hex(ramps.outline) if ramps.outline else None,
           "sources": len(paths), "warnings": [w.get("rule", str(w)) for w in report.get("warnings", [])]}
   out.parent.mkdir(parents=True, exist_ok=True)
   out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
   return data


def load(path: Path) -> list[tuple[int, int, int]]:
   """palette.json → RGB 목록 (차례 = 모델 팔레트 번호)."""
   raw = json.loads(Path(path).read_text(encoding="utf-8"))
   return [tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)) for h in raw["colors"]]


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--groups", default="train.local/groups.json")
   ap.add_argument("--out", default="models.local/polish/palette.json")
   args = ap.parse_args(argv)
   sys.stdout.reconfigure(encoding="utf-8")
   groups = json.loads(Path(args.groups).read_text(encoding="utf-8"))
   paths, n_groups = our_paths(groups)
   data = extract(paths, Path(args.out))
   print(f"그룹 {n_groups} · 그림 {len(paths)} → 색 {len(data['colors'])} · 경고 {data['warnings']}")
   return 0


if __name__ == "__main__":
   raise SystemExit(main())
