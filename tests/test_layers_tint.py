"""7판-나-2 — `layers view --tint` 물들인 미리보기 판 (설계 2026-10-07 2-5)."""

from __future__ import annotations

import numpy as np

from arttool import errors, image, layerset
from arttool.jsonio import read_json, write_json

from test_layers_ops import run_cli

W = H = 8
WHITE = (255, 255, 255)
GRAY = (200, 200, 200)


def _box(x0, y0, x1, y1, rgb):
   arr = image.new(W, H)
   arr[y0:y1, x0:x1] = (*rgb, 255)
   return arr


def _set(tmp_path):
   """content 흰 네모 + 층 마스크 둘(위 · 아래 반) + glass 회색 한 줄."""
   folder = tmp_path / "set"
   rows = [{"name": "content", "kind": "content"}, {"name": "glass", "kind": "deco"},
           {"name": "tier1", "kind": "mask"}, {"name": "tier2", "kind": "mask"}]
   layerset.save(folder, layerset.from_dict({"version": 2, "canvas": [W, H], "layers": rows, "items": ["f0"]}))
   image.save(folder / "content" / "f0.png", _box(0, 0, 8, 8, WHITE))
   image.save(folder / "glass" / "f0.png", _box(0, 0, 8, 1, GRAY))
   image.save(folder / "tier1" / "f0.png", _box(0, 0, 8, 4, WHITE))
   image.save(folder / "tier2" / "f0.png", _box(0, 4, 8, 8, WHITE))
   return folder


def _view(tmp_path, folder, *extra):
   rep = tmp_path / "r.json"
   code = run_cli(["layers", "view", "--in", str(folder), "--out", str(tmp_path / "v.png"), *extra], rep)
   return code, (read_json(rep) if rep.exists() else None)


def test_tint_text_makes_one_column(tmp_path, monkeypatch):
   monkeypatch.setattr(image, "has_label_font", lambda: False)   # 딱지 없이 판 크기를 셈하기 쉽게
   folder = _set(tmp_path)
   code, rep = _view(tmp_path, folder, "--tint", "content=#ff0000")
   assert code == errors.EXIT_OK
   assert rep["tints"] == ["content=#ff0000"]
   board = image.load(tmp_path / "v.png")
   # 한 줄 한 칸이라 판 = 그림 하나. 회색 glass 는 그대로, 흰 content 는 빨강
   reds = np.all(board[:, :, :3] == (255, 0, 0), axis=2)
   assert reds.any()


def test_tint_json_columns_and_mask_tiers(tmp_path, monkeypatch):
   monkeypatch.setattr(image, "has_label_font", lambda: False)
   folder = _set(tmp_path)
   table = tmp_path / "tints.json"
   write_json(table, [{"name": "apple", "tint": {"tier1": "#ff0000", "tier2": "#00ff00"}},
                      {"name": "plain", "tint": {}}])
   code, rep = _view(tmp_path, folder, "--tint", str(table), "--mask-of", "content")
   assert code == errors.EXIT_OK
   assert rep["tints"] == ["apple", "plain"]
   board = image.load(tmp_path / "v.png")
   colors = {tuple(int(v) for v in c) for c in board[:, :, :3].reshape(-1, 3)}
   assert (255, 0, 0) in colors and (0, 255, 0) in colors          # 층마다 다른 색
   assert (255, 255, 255) in colors                                # plain 칸은 흰 그대로


def test_tint_render_cells_exact(tmp_path):
   from arttool.sprite import layerops
   folder = _set(tmp_path)
   ls = layerset.load(folder)
   parts = layerset.read_item(folder, ls, "f0")
   out = layerops._tinted(ls, parts, {"tier1": (255, 0, 0), "tier2": (0, 0, 255), "glass": (0, 255, 0)}, "content", None)
   assert tuple(out[2, 2, :3]) == (255, 0, 0)          # 위 층
   assert tuple(out[6, 2, :3]) == (0, 0, 255)          # 아래 층
   assert tuple(out[0, 0, :3]) == (0, 200, 0)          # glass 는 곱하기 (200 × 255 / 255)


def test_tint_refusals(tmp_path):
   folder = _set(tmp_path)
   assert _view(tmp_path, folder, "--tint", "content=#ff0000", "--each")[0] == errors.EXIT_USAGE
   assert _view(tmp_path, folder, "--tint", "nope=#ff0000")[0] == errors.EXIT_USAGE
   assert _view(tmp_path, folder, "--tint", "content=red")[0] == errors.EXIT_USAGE
   assert _view(tmp_path, folder, "--tint", "tier1=#ff0000")[0] == errors.EXIT_USAGE     # 마스크 열쇠인데 --mask-of 없음
   assert _view(tmp_path, folder, "--mask-of", "content")[0] == errors.EXIT_USAGE        # --tint 없이
   bad = tmp_path / "bad.json"
   write_json(bad, [{"name": "a", "tint": {"content": "#ff0000"}, "extra": 1}])
   assert _view(tmp_path, folder, "--tint", str(bad))[0] == errors.EXIT_USAGE


def test_tint_max(tmp_path, monkeypatch):
   from arttool.sprite import layerops
   monkeypatch.setattr(layerops, "TINT_MAX", 1)
   folder = _set(tmp_path)
   assert _view(tmp_path, folder, "--tint", "content=#ff0000", "--tint", "content=#00ff00")[0] == errors.EXIT_USAGE


def test_view_without_tint_has_no_tints_key(tmp_path):
   folder = _set(tmp_path)
   code, rep = _view(tmp_path, folder)
   assert code == errors.EXIT_OK and "tints" not in rep
