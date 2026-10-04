"""`extend ring` 시험 (피드백 후속 설계 3-5). 한 바퀴 그림은 코드로 만든다."""

from __future__ import annotations

from argparse import Namespace

import numpy as np
import pytest

from arttool import errors, image
from arttool.extend import ring

CORNER = (200, 40, 40, 255)
EDGE_A = (40, 40, 200, 255)
EDGE_B = (40, 200, 40, 255)


def _ring(width=10, height=10, border=3) -> np.ndarray:
   """모서리 빨강, 변은 파랑 · 초록 줄무늬(되풀이 단위가 보이게), 가운데 투명."""
   arr = image.new(width, height)
   for x in range(width):
      arr[:border, x] = EDGE_A if x % 2 == 0 else EDGE_B
      arr[height - border :, x] = EDGE_A if x % 2 == 0 else EDGE_B
   for y in range(height):
      arr[y, :border] = EDGE_A if y % 2 == 0 else EDGE_B
      arr[y, width - border :] = EDGE_A if y % 2 == 0 else EDGE_B
   for x0 in (0, width - border):
      for y0 in (0, height - border):
         arr[y0 : y0 + border, x0 : x0 + border] = CORNER
   return arr


def _args(path, out, **extra) -> Namespace:
   values = {"in_file": str(path), "border": "3", "size": "16x16", "out_file": str(out), "snap": False, "report": None}
   values.update(extra)
   return Namespace(**values)


def _save(tmp_path, arr, name="ring.png"):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _rules(result) -> list[str]:
   return [w["rule"] for w in result["warnings"]]


def test_ring_whole_units_no_warning(tmp_path):
   # 가운데 4 → 원하는 가운데 12 (3단위)
   source = _save(tmp_path, _ring())
   out = tmp_path / "o.png"
   result = ring.run(_args(source, out, size="18x10"))
   assert result["status"] == "ok"
   assert result["warnings"] == []
   made = image.load(out)
   assert image.size(made) == (18, 10)
   # 모서리는 그대로, 위 변은 원본 가운데를 되풀이한다
   assert tuple(made[0, 0]) == CORNER and tuple(made[0, 17]) == CORNER
   assert np.array_equal(made[0, 3:7], made[0, 7:11])


def test_ring_partial_unit_warns_with_sizes(tmp_path):
   source = _save(tmp_path, _ring())
   result = ring.run(_args(source, tmp_path / "o.png", size="17x10"))
   assert "ring.partial_unit" in _rules(result)
   assert result["status"] == "warn"
   assert result["fit_sizes"] == [[14, 10], [18, 10]]
   assert result["size"] == [17, 10]


def test_ring_snap_changes_size(tmp_path):
   source = _save(tmp_path, _ring())
   out = tmp_path / "o.png"
   result = ring.run(_args(source, out, size="17x15", snap=True))
   assert result["size"] == [18, 14]
   assert result["requested"] == [17, 15]
   assert image.size(image.load(out)) == (18, 14)
   assert "ring.partial_unit" not in _rules(result)


def test_ring_border_lbrt(tmp_path):
   arr = image.new(12, 10, EDGE_A)
   arr[:, :2] = CORNER           # 왼 2
   arr[:, 12 - 4 :] = EDGE_B     # 오른 4
   source = _save(tmp_path, arr)
   out = tmp_path / "o.png"
   result = ring.run(_args(source, out, border="2,1,4,3", size="18x13"))
   made = image.load(out)
   assert result["border"] == [2, 1, 4, 3]
   assert tuple(made[5, 1]) == CORNER and tuple(made[5, 2]) == EDGE_A
   assert tuple(made[5, 13]) == EDGE_A and tuple(made[5, 14]) == EDGE_B
   # 가운데 가로 6 → 12 (2단위), 세로 6 → 9 (1.5단위)라 세로만 어긋난다
   assert result["fit_sizes"] == [[18, 10], [18, 16]]


def test_ring_too_small_exit2(tmp_path):
   source = _save(tmp_path, _ring())
   with pytest.raises(errors.UsageError):
      ring.run(_args(source, tmp_path / "o.png", size="6x16"))
   with pytest.raises(errors.UsageError):
      ring.run(_args(source, tmp_path / "o.png", border="5"))


def test_ring_refuses_overwrite_input(tmp_path):
   source = _save(tmp_path, _ring())
   before = source.read_bytes()
   with pytest.raises(errors.UsageError):
      ring.run(_args(source, source))
   assert source.read_bytes() == before
