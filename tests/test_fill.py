"""`fill --enclosed` (2판 설계 C2)."""

import numpy as np

from arttool import cli, image


def _ring(path, gap=False, diagonal=False):
   arr = np.zeros((7, 7, 4), dtype=np.uint8)
   arr[1, 1:6, 3] = arr[5, 1:6, 3] = arr[1:6, 1, 3] = arr[1:6, 5, 3] = 255
   if gap:
      arr[1, 3, 3] = 0
   if diagonal:   # 모서리를 비워 대각선으로만 잇는다
      arr[1, 1, 3] = 0
   image.save(path, arr)


def _run(tmp_path, *extra):
   out = tmp_path / "out.png"
   code = cli.main(["fill", "--in", str(tmp_path / "a.png"), "--out", str(out), "--enclosed", "--color", "#ff0000", *extra])
   return code, (image.load(out) if out.exists() else None)


def test_closed_ring_inside_only(tmp_path):
   _ring(tmp_path / "a.png")
   code, arr = _run(tmp_path)
   assert code == 0
   assert (arr[2:5, 2:5, 3] == 255).all() and (arr[2:5, 2:5, 0] == 255).all()
   assert arr[0, 0, 3] == 0


def test_open_frame_warns_none(tmp_path):
   _ring(tmp_path / "a.png", gap=True)
   code, arr = _run(tmp_path)
   assert code == 0 and arr[3, 3, 3] == 0


def test_diagonal_gap_counts_as_closed(tmp_path):
   _ring(tmp_path / "a.png", diagonal=True)
   _, arr = _run(tmp_path)
   assert arr[3, 3, 3] == 255


def test_max_area_skips(tmp_path):
   _ring(tmp_path / "a.png")
   _, arr = _run(tmp_path, "--max-area", "4")
   assert arr[3, 3, 3] == 0


def test_needs_enclosed_and_bad_color(tmp_path):
   _ring(tmp_path / "a.png")
   assert cli.main(["fill", "--in", str(tmp_path / "a.png"), "--out", str(tmp_path / "o.png"), "--color", "#ff0000"]) == 2
   assert cli.main(["fill", "--in", str(tmp_path / "a.png"), "--out", str(tmp_path / "o.png"), "--enclosed", "--color", "red"]) == 2
   assert cli.main(["fill", "--in", str(tmp_path / "a.png"), "--out", str(tmp_path / "o.png"), "--enclosed", "--color", "#ff0000", "--max-area", "0"]) == 2


def test_zero_alpha_color_refused(tmp_path):
   _ring(tmp_path / "a.png")
   assert cli.main(["fill", "--in", str(tmp_path / "a.png"), "--out", str(tmp_path / "o.png"), "--enclosed", "--color", "#ff000000"]) == 2
   assert not (tmp_path / "o.png").exists()


def test_large_warning_names_file_once(tmp_path):
   import json
   arr = np.zeros((20, 20, 4), dtype=np.uint8)
   arr[0, :, 3] = arr[19, :, 3] = arr[:, 0, 3] = arr[:, 19, 3] = arr[:, 10, 3] = 255   # 큰 갇힌 덩이 둘
   image.save(tmp_path / "a.png", arr)
   report = tmp_path / "r.json"
   code, _ = _run(tmp_path, "--report", str(report))
   assert code == 0
   large = [w for w in json.loads(report.read_text(encoding="utf-8"))["warnings"] if w["rule"] == "fill.large"]
   assert len(large) == 1 and large[0]["items"] == ["a.png"]
