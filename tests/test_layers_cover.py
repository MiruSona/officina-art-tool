"""`layers check --cover` — 가림판 안 빈 칸은 fail, 겹친 칸은 경고만. 안 주면 예전과 바이트까지 같다."""

from __future__ import annotations

import numpy as np

from arttool import errors, image
from arttool.jsonio import read_json

from test_layers_ops import run_cli, three_layers, write_set

W = H = 12


def _mask(path, x0, y0, x1, y1, size=(W, H)):
   arr = image.new(*size)
   arr[y0:y1, x0:x1] = (255, 255, 255, 255)
   image.save(path, arr)
   return path


def _two(tmp_path, gap=False, clash=False):
   a = image.new(W, H)
   a[0:6, 0:6] = (200, 0, 0, 255)
   b = image.new(W, H)
   b[0:6, 6:12] = (0, 0, 200, 255)
   if gap:
      b[0, 11] = (0, 0, 0, 0)
   if clash:
      b[0, 5] = (0, 0, 200, 255)
   write_set(tmp_path / "set", {"a": a, "b": b})
   return tmp_path / "set"


def test_cover_full_is_ok(tmp_path):
   folder = _two(tmp_path)
   rep = tmp_path / "r.json"
   assert run_cli(["layers", "check", "--in", str(folder), "--cover", str(_mask(tmp_path / "m.png", 0, 0, 12, 6))], rep) == errors.EXIT_OK
   got = read_json(rep)
   assert got["cover"] == [{"item": "idle", "mask": "m.png", "cells": 72, "empty": 0, "overlap": 0}]
   assert got["status"] == "ok"


def test_cover_empty_fails(tmp_path):
   folder = _two(tmp_path, gap=True)
   rep = tmp_path / "r.json"
   assert run_cli(["layers", "check", "--in", str(folder), "--cover", str(_mask(tmp_path / "m.png", 0, 0, 12, 6))], rep) == errors.EXIT_CHECK_FAIL
   got = read_json(rep)
   assert got["failed"] == ["cover"]
   assert got["cover"][0]["empty"] == 1
   assert [w["rule"] for w in got["warnings"]] == ["cover_empty"]
   assert len(got["warnings"][0]["items"]) == 1


def test_cover_overlap_warns_only(tmp_path):
   folder = _two(tmp_path, clash=True)
   rep = tmp_path / "r.json"
   assert run_cli(["layers", "check", "--in", str(folder), "--cover", str(_mask(tmp_path / "m.png", 0, 0, 12, 6))], rep) == errors.EXIT_OK
   got = read_json(rep)
   assert got["status"] == "warn" and got["failed"] == []
   assert got["cover"][0]["overlap"] == 1
   assert [w["rule"] for w in got["warnings"]] == ["cover_overlap"]


def test_cover_outside_mask_not_counted(tmp_path):
   folder = _two(tmp_path, gap=True)   # 빈 칸 (11,0) 은 가림판 밖
   rep = tmp_path / "r.json"
   assert run_cli(["layers", "check", "--in", str(folder), "--cover", str(_mask(tmp_path / "m.png", 0, 2, 12, 6))], rep) == errors.EXIT_OK
   assert read_json(rep)["cover"][0]["empty"] == 0


def test_cover_size_mismatch_is_usage(tmp_path):
   folder = _two(tmp_path)
   bad = _mask(tmp_path / "m.png", 0, 0, 4, 4, size=(8, 8))
   assert run_cli(["layers", "check", "--in", str(folder), "--cover", str(bad)]) == errors.EXIT_USAGE


def test_cover_same_as_report_refused(tmp_path):
   folder = _two(tmp_path)
   assert run_cli(["layers", "check", "--in", str(folder), "--cover", str(tmp_path / "r.json")], tmp_path / "r.json") == errors.EXIT_USAGE


def test_no_cover_report_is_byte_identical(tmp_path):
   """--cover 를 안 주면 보고에 cover 칸이 없고, 같은 묶음을 두 번 검사한 보고가 바이트까지 같다."""
   write_set(tmp_path / "set", three_layers())
   one, two = tmp_path / "1.json", tmp_path / "2.json"
   run_cli(["layers", "check", "--in", str(tmp_path / "set")], one)
   run_cli(["layers", "check", "--in", str(tmp_path / "set")], two)
   assert one.read_bytes() == two.read_bytes()
   got = read_json(one)
   assert "cover" not in got
   assert set(got) == {"version", "status", "in", "canvas", "layers", "items", "failed", "rules", "warnings"}
   assert not any(r["rule"] == "cover" for r in got["rules"])
   assert np.array_equal(image.load(tmp_path / "set" / "hair" / "idle.png"), three_layers()["hair"])
