"""`measure shape` (2026-10-06 2판 설계 C7)."""

import json
import time

import numpy as np

from arttool import cli, errors, image

RED = (200, 30, 40, 255)


def _disc(size=32, cx=16.0, cy=12.0, r=6, color=RED, base=None):
   """칸 중심이 (cx, cy) 에서 r 안인 칸을 칠한 그림."""
   arr = np.zeros((size, size, 4), dtype=np.uint8) if base is None else base
   ys, xs = np.mgrid[0:size, 0:size]
   arr[(xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2 <= r * r] = color
   return arr


def _measure(tmp_path, arr, *extra):
   src = tmp_path / "frame.png"
   image.save(src, arr)
   report = tmp_path / "shape.json"
   code = cli.main(["measure", "shape", "--in", str(src), "--report", str(report), *extra])
   return code, json.loads(report.read_text(encoding="utf-8"))


def test_disc_at(tmp_path):
   code, data = _measure(tmp_path, _disc(), "--at", "16,12")
   assert code == 0 and data["status"] == "ok" and data["out"] is None
   shape = data["shape"]
   assert shape["center"] == [16.0, 12.0]
   assert round(shape["r"]) == 6 and shape["r_max"] <= 6
   assert shape["roundness"] >= 0.95
   assert shape["box"] == [10, 6, 12, 12]
   assert shape["area"] > 100


def test_color_picks_largest(tmp_path):
   arr = _disc(r=6)
   arr[30, 30] = RED                       # 외딴 한 칸 — 가장 큰 덩이가 아니다
   code, data = _measure(tmp_path, arr, "--color", "#c81e28")
   assert code == 0 and data["shape"]["center"] == [16.0, 12.0]


def test_tol_takes_near_colors(tmp_path):
   arr = _disc(r=6)
   arr[12, 16] = (205, 30, 40, 255)        # 가운데 한 칸만 조금 다른 색
   _, strict = _measure(tmp_path, arr, "--color", "#c81e28")
   _, loose = _measure(tmp_path, arr, "--color", "#c81e28", "--tol", "8")
   assert loose["shape"]["area"] == strict["shape"]["area"] + 1


def test_not_round_warns(tmp_path):
   arr = np.zeros((20, 40, 4), dtype=np.uint8)
   arr[5:7, 2:38] = RED                    # 긴 막대
   code, data = _measure(tmp_path, arr, "--at", "10,5")
   assert code == 0 and data["status"] == "warn"
   assert [w["rule"] for w in data["warnings"]] == ["measure.not_round"]


def test_no_color_fails(tmp_path):
   code, data = _measure(tmp_path, _disc(), "--color", "#00ff00")
   assert code == 4 and data["shape"] is None
   assert data["warnings"][0]["rule"] == "measure.none"


def test_usage_errors(tmp_path):
   src = tmp_path / "f.png"
   image.save(src, _disc())
   base = ["measure", "shape", "--in", str(src)]
   assert cli.main(base) == errors.EXIT_USAGE                                  # 둘 다 없음
   assert cli.main(base + ["--at", "1,1", "--color", "#ffffff"]) == errors.EXIT_USAGE
   assert cli.main(base + ["--at", "0,0"]) == errors.EXIT_USAGE                # 투명 칸
   assert cli.main(base + ["--at", "99,0"]) == errors.EXIT_USAGE               # 그림 밖
   assert cli.main(base + ["--at", "a,b"]) == errors.EXIT_USAGE
   assert cli.main(base + ["--color", "#c81e28", "--tol", "-1"]) == errors.EXIT_USAGE


def test_dry_run_harmless(tmp_path):
   src = tmp_path / "f.png"
   image.save(src, _disc())
   assert cli.main(["--dry-run", "measure", "shape", "--in", str(src), "--at", "16,12"]) == 0


def test_large_image_is_fast(tmp_path):
   arr = _disc(size=1500, cx=750.0, cy=750.0, r=600)
   start = time.perf_counter()
   code, data = _measure(tmp_path, arr, "--color", "#c81e28")
   assert code == 0 and data["shape"]["roundness"] >= 0.95
   assert time.perf_counter() - start < 10
