"""`layers diff --drop` — 겹 떼기 색 거르기 (2026-10-04 피드백후속설계 3-6). 그림은 전부 코드로 만든다."""

from __future__ import annotations

import argparse

import numpy as np
import pytest

from arttool import image
from arttool.errors import UsageError
from arttool.jsonio import read_json
from arttool.sprite import layerops

OUT = (20, 16, 16)
SKIN = (250, 220, 190)
CHEEK = (240, 205, 178)    # inpaint 가 다시 그린 뺨 — 살색과 RGB 차 최대 15
HAIR = (90, 50, 30)
W = H = 12


def _fill(arr, x0, y0, x1, y1, rgb):
   arr[y0:y1, x0:x1] = (*rgb, 255)


def _body():
   arr = image.new(W, H)
   _fill(arr, 2, 2, 10, 12, OUT)
   _fill(arr, 3, 3, 9, 11, SKIN)
   return arr


def _hair():
   """머리 [2, 10) × [3, 6) + 마스크 안에서 다시 그려진 뺨 [3, 9) × 6 줄."""
   arr = _body()
   _fill(arr, 2, 3, 10, 6, HAIR)
   _fill(arr, 3, 6, 9, 7, CHEEK)
   return arr


def _run(tmp_path, out="set", **over):
   image.save(tmp_path / "idle.png", _body())
   inp = tmp_path / "inp"
   inp.mkdir(exist_ok=True)
   image.save(inp / "hair.png", _hair())
   values = {"sub": "diff", "base": str(tmp_path / "idle.png"), "in_dir": str(inp), "out_dir": str(tmp_path / out),
             "template": None, "carve": "report", "report": None}
   values.update(over)
   return layerops.run(argparse.Namespace(**values))


def test_drop_removes_skin_from_hair(tmp_path):
   rep = _run(tmp_path, drop=["hair:#FADCBE,#3A5BD9"])
   hair = image.load(tmp_path / "set" / "hair" / "idle.png")
   assert np.count_nonzero(hair[:, :, 3]) == 24
   assert not np.any(hair[6, :, 3])
   row = rep["layers"]["hair"]
   assert row["dropped"] == 6 and row["pixels"] == 24
   assert any(w["rule"] == "diff_dropped" for w in rep["warnings"])
   # 뺀 칸은 본체가 그대로 보인다
   body = image.load(tmp_path / "set" / "body" / "idle.png")
   assert tuple(body[6, 4, :3]) == SKIN


def test_drop_tol(tmp_path):
   rep = _run(tmp_path, drop=["hair:#FADCBE"], drop_tol=10)
   assert rep["layers"]["hair"]["dropped"] == 0
   rep = _run(tmp_path, out="set2", drop=["hair:#FADCBE"], drop_tol=15)
   assert rep["layers"]["hair"]["dropped"] == 6


def test_drop_unknown_layer_exit2(tmp_path):
   with pytest.raises(UsageError):
      _run(tmp_path, drop=["cloth:#FADCBE"])
   with pytest.raises(UsageError):
      _run(tmp_path, drop=["body:#FADCBE"])
   assert not (tmp_path / "set").exists()


def test_drop_bad_hex_exit2(tmp_path):
   for spec in ("hair:#FADCB", "hair:", "hair", "hair:skin"):
      with pytest.raises(UsageError):
         _run(tmp_path, drop=[spec])
   with pytest.raises(UsageError):
      _run(tmp_path, drop=["hair:#FADCBE"], drop_tol=-1)
   assert not (tmp_path / "set").exists()


def test_drop_absent_keeps_old_behavior(tmp_path):
   old = _run(tmp_path, out="old")
   new = _run(tmp_path, out="new", drop=None, drop_tol=24)
   assert "dropped" not in old["layers"]["hair"]
   assert old["layers"] == new["layers"] and old["warnings"] == new["warnings"]
   for name in ("hair", "body"):
      assert np.array_equal(image.load(tmp_path / "old" / name / "idle.png"), image.load(tmp_path / "new" / name / "idle.png"))
   assert read_json(tmp_path / "old" / "layers.json") == read_json(tmp_path / "new" / "layers.json")
   assert old["layers"]["hair"]["pixels"] == 30
