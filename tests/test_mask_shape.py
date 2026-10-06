"""`mask --from-shape` (2026-10-06 2판 설계 C8). measure shape 보고로 원을 다시 그린다."""

import json

import numpy as np

from arttool import cli, errors, image

from test_measure_shape import _disc


def _shape_report(tmp_path, arr, at="16,12"):
   src = tmp_path / "frame.png"
   image.save(src, arr)
   report = tmp_path / "shape.json"
   assert cli.main(["measure", "shape", "--in", str(src), "--at", at, "--report", str(report)]) == 0
   return src, report


def _mask(tmp_path, report, *extra):
   out = tmp_path / "mask.png"
   rep = tmp_path / "mask.json"
   code = cli.main(["mask", "--from-shape", str(report), "--out", str(out), "--report", str(rep), *extra])
   return code, out, rep


def test_round_trip_matches_disc(tmp_path):
   arr = _disc()
   src, report = _shape_report(tmp_path, arr)
   for how in ("round", "max"):
      code, out, _ = _mask(tmp_path, report, "--like", str(src), "--r", how)
      assert code == 0
      made = image.load(out)
      assert np.array_equal(made[:, :, 3] > 0, arr[:, :, 3] > 0), how
      assert (made[made[:, :, 3] > 0][:, :3] == 255).all()


def test_invert_and_size(tmp_path):
   _, report = _shape_report(tmp_path, _disc())
   _, plain, _ = _mask(tmp_path, report, "--size", "32,32")
   inside = image.load(plain)[:, :, 3] > 0
   code, out, rep = _mask(tmp_path, report, "--size", "32,32", "--invert")
   assert code == 0
   assert np.array_equal(image.load(out)[:, :, 3] > 0, ~inside)
   data = json.loads(rep.read_text(encoding="utf-8"))
   assert data["status"] == "ok" and data["invert"] is True and data["size"] == [32, 32]


def test_clipped_warns(tmp_path):
   _, report = _shape_report(tmp_path, _disc())
   code, _, rep = _mask(tmp_path, report, "--size", "16,16")
   assert code == 0
   assert [w["rule"] for w in json.loads(rep.read_text(encoding="utf-8"))["warnings"]] == ["mask.clipped"]


def test_number_radius(tmp_path):
   _, report = _shape_report(tmp_path, _disc())
   _, out, _ = _mask(tmp_path, report, "--size", "32,32", "--r", "2")
   assert int(np.count_nonzero(image.load(out)[:, :, 3])) == np.count_nonzero(_disc(r=2)[:, :, 3])


def test_usage_errors(tmp_path):
   _, report = _shape_report(tmp_path, _disc())
   empty = tmp_path / "empty.json"
   empty.write_text(json.dumps({"version": 1, "shape": None}), encoding="utf-8")
   assert _mask(tmp_path, empty, "--size", "8,8")[0] == errors.EXIT_USAGE          # shape 없음
   assert _mask(tmp_path, report)[0] == errors.EXIT_USAGE                          # 크기 없음
   assert _mask(tmp_path, report, "--size", "0,8")[0] == errors.EXIT_USAGE
   for bad in ("0", "-1", "nan", "inf", "big"):
      assert _mask(tmp_path, report, "--size", "8,8", "--r", bad)[0] == errors.EXIT_USAGE, bad
   out = tmp_path / "o.png"
   assert cli.main(["mask", "--from-shape", str(report), "--size", "8,8", "--out", str(report)]) == errors.EXIT_USAGE
   assert not out.exists()


def test_dry_run_writes_nothing(tmp_path):
   _, report = _shape_report(tmp_path, _disc())
   out = tmp_path / "dry.png"
   assert cli.main(["--dry-run", "mask", "--from-shape", str(report), "--size", "32,32", "--out", str(out)]) == 0
   assert not out.exists()


def _covers(shape: dict, mask: np.ndarray) -> bool:
   """mask.py 와 같은 셈으로 `--r max` 원을 그려 덩이 칸을 모두 덮는지 본다."""
   cx, cy = shape["center"]
   r = shape["r_max"]
   ys, xs = np.ogrid[0:mask.shape[0], 0:mask.shape[1]]
   inside = (xs + 0.5 - cx) ** 2 + (ys + 0.5 - cy) ** 2 <= r * r
   return bool(inside[mask].all())


def test_r_max_covers_every_cell():
   # 반올림한 center 로 r_max 를 재야 가림판이 가장 먼 칸까지 덮는다 (전에는 원 900개 중 86개에서 빠졌다).
   from arttool.measure.shape import measure
   for r in np.arange(0.6, 9.0, 0.37):
      for cx in (10.0, 10.13, 10.37, 10.5, 10.71):
         for cy in (11.0, 11.29, 11.5, 11.83):
            mask = _disc(size=24, cx=cx, cy=cy, r=float(r))[:, :, 3] > 0
            if mask.any():
               assert _covers(measure(mask), mask), (r, cx, cy)
   rng = np.random.default_rng(20261006)
   for _ in range(300):
      mask = rng.random((12, 12)) < 0.4
      if mask.any():
         assert _covers(measure(mask), mask)


def test_r_max_round_trip_by_cli(tmp_path):
   arr = _disc(cx=16.3, cy=12.7, r=5.4)
   src, report = _shape_report(tmp_path, arr)
   code, out, _ = _mask(tmp_path, report, "--like", str(src), "--r", "max")
   assert code == 0
   made = image.load(out)[:, :, 3] > 0
   assert made[arr[:, :, 3] > 0].all()


def test_huge_size_refused_before_alloc(tmp_path):
   _, report = _shape_report(tmp_path, _disc())
   code, out, _ = _mask(tmp_path, report, "--size", "100000,100000")
   assert code != 0
   assert not out.exists()


def test_bad_numbers_are_usage_errors(tmp_path):
   for shape in ({"center": ["a", 1], "r": 3}, {"center": [[1], 1], "r": 3}, {"center": [1, 2, 3], "r": 3},
                 {"center": [1, 2], "r": "a"}, {"center": [1, 2], "r": [1]}, {"center": [1, 2], "r": 3, "r_max": [2]}):
      path = tmp_path / "bad.json"
      path.write_text(json.dumps({"version": 1, "shape": shape}), encoding="utf-8")
      how = "max" if "r_max" in shape else "round"
      assert _mask(tmp_path, path, "--size", "8,8", "--r", how)[0] == errors.EXIT_USAGE, shape


def test_round_half_goes_up(tmp_path):
   path = tmp_path / "half.json"
   path.write_text(json.dumps({"version": 1, "shape": {"center": [4, 4], "r": 2.5}}), encoding="utf-8")
   code, _, rep = _mask(tmp_path, path, "--size", "8,8", "--r", "round")
   assert code == 0
   assert json.loads(rep.read_text(encoding="utf-8"))["r"] == 3
