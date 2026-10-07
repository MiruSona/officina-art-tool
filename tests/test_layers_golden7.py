"""7판 골든 — 새 인자를 안 주면 `layers check · view · fill` · `sheet` 보고와 그림이 7판 앞(HEAD f363703)과 같다 (리뷰 7-4).

`tests/golden/layers7/golden.json` 은 옛 코드가 아래 `build` 묶음을 돌린 산출이다. 경로 칸(in · out · path)은 빼고,
PNG 는 풀어 낸 RGBA 칸의 sha256 으로 견준다(PNG 바이트는 압축기 판에 따라 달라질 수 있다).
골든을 다시 만들 일이 생기면 옛 패키지(`git archive <옛 커밋> src`)를 PYTHONPATH 앞에 두고 `collect` 를 돌린다.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from arttool import cli, image

GOLDEN = Path(__file__).parent / "golden" / "layers7" / "golden.json"
PATH_KEYS = ("in", "out", "path")
SETS = {
   "v1": {"version": 1, "canvas": [12, 12], "items": ["f0", "f1", "f2"],
          "layers": [{"name": "body", "kind": "body"}, {"name": "hair", "kind": "hair", "exclusive_with": ["body"]},
                     {"name": "fx", "kind": "fx", "optional": True}]},
   "v2": {"version": 2, "canvas": [12, 12], "items": ["f0", "f1", "f2"],
          "layers": [{"name": "body", "kind": "body"}, {"name": "hair", "kind": "hair", "files": "hair_{v}.png"},
                     {"name": "fx", "kind": "fx", "optional": True, "size": [4, 4], "offset": [1, 1]}]},
}


def build(root: Path) -> None:
   """묶음 둘(v1 하위 폴더 · v2 files 무늬 + 작은 겹)과 가림판. 리뷰어 fx.py 와 같은 그림."""
   for name, data in SETS.items():
      folder = root / name
      folder.mkdir(parents=True)
      (folder / "layers.json").write_text(json.dumps(data), encoding="utf-8")
      for i, item in enumerate(data["items"]):
         body = np.zeros((12, 12, 4), np.uint8)
         body[2:10, 2:10] = [100, 50, 20, 255]
         body[5, 5] = [0, 0, 0, 0]
         body[3 + i, 3] = [10, 200, 10, 255]
         hair = np.zeros((12, 12, 4), np.uint8)
         hair[1:4, 2:10] = [200, 0, 0, 255]
         image.save(folder / "body" / f"{item}.png", body)
         image.save(folder / "hair" / f"{item}.png" if name == "v1" else folder / f"hair_{item}.png", hair)
         if i == 0:
            side = 12 if name == "v1" else 4
            fx = np.zeros((side, side, 4), np.uint8)
            fx[1, 1] = [255, 255, 255, 255]
            image.save(folder / "fx" / f"{item}.png", fx)
   cover = np.zeros((12, 12, 4), np.uint8)
   cover[0:11, 1:11, 3] = 255
   image.save(root / "cover.png", cover)


def _strip(node):
   if isinstance(node, dict):
      return {k: _strip(v) for k, v in node.items() if k not in PATH_KEYS}
   if isinstance(node, list):
      return [_strip(v) for v in node]
   return node


def _pixels(path: Path) -> str:
   arr = image.load(path)
   return hashlib.sha256(np.ascontiguousarray(arr).tobytes() + repr(arr.shape).encode()).hexdigest()


def _json_hash(path: Path) -> str:
   text = json.dumps(json.loads(path.read_text(encoding="utf-8")), sort_keys=True, ensure_ascii=False)
   return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _files(folder: Path) -> dict:
   out = {}
   for dirpath, _, names in os.walk(folder):
      for name in sorted(names):
         path = Path(dirpath) / name
         rel = path.relative_to(folder).as_posix()
         # layers.json 은 바이트 복사라 뜻(파싱한 값)만 견준다 — 입력을 쓴 방식에 따라 바이트가 다를 수 있다
         out[rel] = _pixels(path) if name.endswith(".png") else _json_hash(path)
   return dict(sorted(out.items()))


def _run(argv, report: Path) -> dict:
   code = cli.main([*argv, "--report", str(report)])
   return {"exit": code, "report": _strip(json.loads(report.read_text(encoding="utf-8")))}


def collect(fx: Path, out: Path) -> dict:
   """옛 run.sh 와 같은 다섯 판을 묶음마다 돌려 경로를 뺀 결과로 모은다."""
   result = {}
   for name in SETS:
      o = out / name
      o.mkdir(parents=True)
      s = fx / name
      row = {
         "check": _run(["layers", "check", "--in", str(s)], o / "check.json"),
         "checkc": _run(["layers", "check", "--in", str(s), "--cover", str(fx / "cover.png")], o / "checkc.json"),
         "view": _run(["layers", "view", "--in", str(s), "--out", str(o / "view.png"), "--each", "--scale", "2"], o / "view.json"),
         "fill": _run(["layers", "fill", "--in", str(s), "--mask", str(fx / "cover.png"), "--nearest", "body,hair",
                       "--out", str(o / "filled")], o / "fill.json"),
         "sheet": _run(["sheet", "--in", str(s / "body" / "f0.png"), str(s / "body" / "f1.png"), "--out", str(o / "sheet.png"),
                        "--label"], o / "sheet.json"),
      }
      row["png"] = {"view.png": _pixels(o / "view.png"), "sheet.png": _pixels(o / "sheet.png"),
                    **{f"filled/{k}": v for k, v in _files(o / "filled").items()}}
      result[name] = row
   return result


def test_reports_and_pixels_match_before_7th(tmp_path):
   fx, out = tmp_path / "fx", tmp_path / "out"
   build(fx)
   got = collect(fx, out)
   want = json.loads(GOLDEN.read_text(encoding="utf-8"))
   for name in SETS:
      for key in ("check", "checkc", "view", "fill", "sheet", "png"):
         assert got[name][key] == want[name][key], f"{name} {key}"
