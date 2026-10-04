"""`extend period` 시험 (피드백 후속 설계 3-5). 그림은 모두 코드로 만든 울타리 띠다."""

from __future__ import annotations

from argparse import Namespace

import numpy as np
import pytest

from arttool import errors, image
from arttool.extend import period

POST = (60, 40, 30, 255)
RAIL = (170, 120, 70, 255)
POST_W = 4


def _fence(length: int, step: int, height: int = 12, start: int = 5) -> np.ndarray:
   """가로 띠 : 위아래 난간 두 줄 + step 마다 기둥 하나 (기둥 폭 4)."""
   arr = image.new(length, height)
   arr[3:5, :] = RAIL
   arr[8:10, :] = RAIL
   for x in range(start, length, step):
      arr[:, x : x + POST_W] = POST
   return arr


def _args(path, **extra) -> Namespace:
   values = {"in_file": str(path), "axis": "x", "tile": None, "out_file": None, "fit": None, "report": None}
   values.update(extra)
   return Namespace(**values)


def _save(tmp_path, arr, name="fence.png"):
   path = tmp_path / name
   image.save(path, arr)
   return path


def _rules(result) -> list[str]:
   return [w["rule"] for w in result["warnings"]]


def _post_columns(arr: np.ndarray) -> int:
   """맨 윗줄이 기둥 색인 열 수 (난간은 윗줄에 없다)."""
   return int(np.sum(np.all(arr[0] == POST, axis=1)))


def test_period_finds_37(tmp_path):
   result = period.run(_args(_save(tmp_path, _fence(37 * 5, 37))))
   assert result["period"] == 37
   assert result["status"] == "ok"
   assert result["score"] < period.WEAK_SCORE


def test_period_prefers_smallest_not_multiple(tmp_path):
   """기둥 두 개에 하나꼴로 색이 조금 다르면 24 가 꼭 맞고 12 는 조금 어긋난다. 그래도 12 를 고른다."""
   arr = _fence(12 * 16, 12)
   for x in range(5 + 12, arr.shape[1], 24):
      arr[:, x : x + POST_W] = (64, 40, 30, 255)
   result = period.run(_args(_save(tmp_path, arr)))
   assert result["period"] == 12


def test_period_axis_y(tmp_path):
   vertical = _fence(29 * 6, 29).transpose(1, 0, 2).copy()
   result = period.run(_args(_save(tmp_path, vertical), axis="y"))
   assert result["period"] == 29
   assert result["axis"] == "y"


def test_period_not_multiple_warns(tmp_path):
   result = period.run(_args(_save(tmp_path, _fence(37 * 5, 37)), tile=32))
   assert "period.not_multiple" in _rules(result)
   found = next(w for w in result["warnings"] if w["rule"] == "period.not_multiple")
   assert found["items"] == [32, 64]
   assert result["status"] == "warn"


def test_period_weak_warns_on_noise(tmp_path):
   rng = np.random.default_rng(3)
   noise = rng.integers(0, 256, size=(16, 200, 4), dtype=np.uint8)
   noise[:, :, 3] = 255
   result = period.run(_args(_save(tmp_path, noise)))
   assert "period.weak" in _rules(result)


def test_period_weak_warns_on_smooth_gradient(tmp_path):
   """되풀이 없는 매끈한 그림(멀수록 다른 그림)에서 작은 p 를 단위로 믿지 않는다."""
   arr = image.new(120, 8)
   arr[:, :, 0] = np.arange(120, dtype=np.uint8)[None, :] * 2
   arr[:, :, 3] = 255
   result = period.run(_args(_save(tmp_path, arr)))
   assert "period.weak" in _rules(result)


def test_period_not_found_short_strip(tmp_path):
   result = period.run(_args(_save(tmp_path, _fence(7, 3, start=0))))
   assert result["period"] is None
   assert "period.not_found" in _rules(result)
   assert result["status"] == "warn"


def test_period_fit_to_32_keeps_post_columns(tmp_path):
   source = _save(tmp_path, _fence(37 * 5, 37))
   out = tmp_path / "unit.png"
   result = period.run(_args(source, tile=32, out_file=str(out)))
   unit = image.load(out)
   assert image.size(unit) == (32, 12)
   assert _post_columns(unit) == POST_W
   assert len(result["removed"]) == 5
   assert result["duplicated"] == []
   assert result["width"] == 32


def test_period_fit_grows_by_duplicating(tmp_path):
   source = _save(tmp_path, _fence(29 * 5, 29))
   out = tmp_path / "unit.png"
   result = period.run(_args(source, fit=32, out_file=str(out)))
   unit = image.load(out)
   assert image.size(unit) == (32, 12)
   assert _post_columns(unit) == POST_W
   assert len(result["duplicated"]) == 3


def test_period_fit_out_of_range_exit2(tmp_path):
   source = _save(tmp_path, _fence(37 * 5, 37))
   with pytest.raises(errors.UsageError):
      period.run(_args(source, fit=20, out_file=str(tmp_path / "unit.png")))


def test_period_out_without_period_exit1(tmp_path):
   source = _save(tmp_path, _fence(7, 3, start=0))
   with pytest.raises(errors.ArtToolError) as caught:
      period.run(_args(source, out_file=str(tmp_path / "unit.png")))
   assert not isinstance(caught.value, errors.UsageError)
   assert not (tmp_path / "unit.png").exists()


def test_period_refuses_overwrite_input(tmp_path):
   source = _save(tmp_path, _fence(37 * 5, 37))
   before = source.read_bytes()
   with pytest.raises(errors.UsageError):
      period.run(_args(source, out_file=str(source)))
   assert source.read_bytes() == before
