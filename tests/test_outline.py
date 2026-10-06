"""`outline` (2판 설계 C1)."""

import numpy as np

from arttool import cli, image


def _dot(path, size=5, box=(1, 4)):
   arr = np.zeros((size, size, 4), dtype=np.uint8)
   arr[box[0]:box[1], box[0]:box[1]] = (200, 100, 50, 255)
   image.save(path, arr)


def _run(tmp_path, *extra):
   out = tmp_path / "out.png"
   code = cli.main(["outline", "--in", str(tmp_path / "a.png"), "--out", str(out), *extra])
   return code, (image.load(out) if out.exists() else None)


def test_black_outside_adds_ring(tmp_path):
   _dot(tmp_path / "a.png", size=7, box=(2, 5))
   code, arr = _run(tmp_path)
   assert code == 0
   assert int((arr[:, :, 3] > 0).sum()) > 9 and tuple(arr[1, 3, :3]) == (0, 0, 0)


def test_inside_keeps_size_and_count(tmp_path):
   _dot(tmp_path / "a.png", size=7, box=(2, 5))
   code, arr = _run(tmp_path, "--where", "inside")
   assert code == 0 and int((arr[:, :, 3] > 0).sum()) == 9 and tuple(arr[3, 3, :3]) == (200, 100, 50)


def test_clipped_warns_and_grow_enlarges(tmp_path):
   _dot(tmp_path / "a.png", size=3, box=(0, 3))
   code, arr = _run(tmp_path)
   assert code == 0 and arr.shape[:2] == (3, 3)
   code, arr = _run(tmp_path, "--grow", "--width", "2")
   assert code == 0 and arr.shape[:2] == (7, 7)


def test_solid_and_none(tmp_path):
   _dot(tmp_path / "a.png", size=7, box=(2, 5))
   code, arr = _run(tmp_path, "--mode", "solid", "--color", "#00ff00")
   assert code == 0 and tuple(arr[1, 3, :3]) == (0, 255, 0)
   code, arr = _run(tmp_path, "--mode", "none")
   assert code == 0 and int((arr[:, :, 3] > 0).sum()) == 9


def test_usage_errors(tmp_path):
   _dot(tmp_path / "a.png")
   assert _run(tmp_path, "--color", "#00ff00")[0] == 2           # solid 밖 --color
   assert _run(tmp_path, "--width", "5")[0] == 2
   assert _run(tmp_path, "--mode", "selout")[0] == 2             # 램프(프로필) 없음
   assert _run(tmp_path, "--where", "middle")[0] == 2
