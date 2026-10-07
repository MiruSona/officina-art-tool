"""7판-나-1 — 맨 폴더 모드 : `layers.json` 없이 `--order` 로 겹 묶음을 읽는다 (설계 2026-10-07 4절)."""

from __future__ import annotations

import numpy as np
import pytest

from arttool import errors, image, layerset
from arttool.errors import UsageError
from arttool.jsonio import read_json

from test_layers_ops import run_cli

W, H = 12, 10
GRAY, RED = (128, 128, 128), (200, 0, 0)


def _box(x0, y0, x1, y1, rgb, size=(W, H)):
   arr = image.new(*size)
   arr[y0:y1, x0:x1] = (*rgb, 255)
   return arr


def sub_folders(root, frames=("f2", "f10", "f1"), lid_frames=None):
   """가 꼴 : 겹마다 하위 폴더."""
   for item in frames:
      image.save(root / "bowl" / f"{item}.png", _box(2, 5, 10, 9, GRAY))
   for item in (frames if lid_frames is None else lid_frames):
      image.save(root / "lid" / f"{item}.png", _box(2, 2, 10, 5, RED))
   return root


def one_folder(root, frames=("f0", "f1")):
   """나 꼴 : 한 폴더에 `<겹>_<v>.png`."""
   for item in frames:
      image.save(root / f"bowl_{item}.png", _box(2, 5, 10, 9, GRAY))
      image.save(root / f"lid_{item}.png", _box(2, 2, 10, 5, RED))
   return root


def test_from_folder_sub_folders(tmp_path):
   ls = layerset.from_folder(sub_folders(tmp_path / "s"), ["bowl", "lid"])
   assert ls.names() == ["bowl", "lid"] and ls.canvas == (W, H)
   assert ls.items == ["f1", "f2", "f10"]                 # 자연 정렬
   assert all(layer.optional and layer.files is None for layer in ls.layers)
   assert [layer.kind for layer in ls.layers] == ["deco", "deco"]


def test_from_folder_one_folder_uses_pattern(tmp_path):
   ls = layerset.from_folder(one_folder(tmp_path / "s"), ["bowl", "lid"], masks=["lid"])
   assert ls.items == ["f0", "f1"]
   assert ls.layer("bowl").files == "bowl_{v}.png"
   assert ls.layer("lid").kind == "mask"
   assert layerset.image_path(tmp_path / "s", ls, "bowl", "f1").name == "bowl_f1.png"


def test_from_folder_refusals(tmp_path):
   root = sub_folders(tmp_path / "s")
   image.save(root / "bowl_f0.png", _box(0, 0, 1, 1, GRAY))            # 가 · 나 섞임
   with pytest.raises(UsageError, match="섞"):
      layerset.from_folder(root, ["bowl", "lid"])
   with pytest.raises(UsageError):
      layerset.from_folder(one_folder(tmp_path / "t"), ["bowl", "lid"], masks=["cup"])
   with pytest.raises(UsageError):
      layerset.from_folder(one_folder(tmp_path / "u"), ["bowl", "bowl"])
   with pytest.raises(UsageError):
      layerset.from_folder(one_folder(tmp_path / "v"), ["bo wl"])
   (tmp_path / "w").mkdir()
   with pytest.raises(errors.ArtToolError):
      layerset.from_folder(tmp_path / "w", ["bowl"])


def test_check_bare_folder_reports_inferred_and_counts(tmp_path):
   root = sub_folders(tmp_path / "s", lid_frames=("f1",))
   rep_path = tmp_path / "r.json"
   code = run_cli(["layers", "check", "--in", str(root), "--order", "bowl,lid"], rep_path)
   assert code == errors.EXIT_OK
   rep = read_json(rep_path)
   assert rep["inferred"] is True and rep["order"] == ["bowl", "lid"]
   assert rep["counts"] == {"bowl": 3, "lid": 1}
   assert [w["rule"] for w in rep["warnings"]] == ["layer_count"]        # 그림마다 layer_empty 가 쏟아지지 않는다
   assert "variants" not in rep
   assert not (root / "layers.json").exists()


def test_check_bare_one_folder_with_masks(tmp_path):
   root = one_folder(tmp_path / "s")
   rep_path = tmp_path / "r.json"
   code = run_cli(["layers", "check", "--in", str(root), "--order", "bowl,lid", "--masks", "lid", "--mask-of", "bowl"], rep_path)
   assert code == errors.EXIT_OK
   rep = read_json(rep_path)
   assert rep["mask_of"]["masks"] == ["lid"]
   assert rep["mask_of"]["items"][0]["outside"] > 0


def test_order_with_layers_json_is_usage(tmp_path):
   root = sub_folders(tmp_path / "s")
   layerset.save(root, layerset.from_folder(root, ["bowl", "lid"]))
   assert run_cli(["layers", "check", "--in", str(root), "--order", "bowl,lid"]) == errors.EXIT_USAGE


def test_masks_without_order_is_usage(tmp_path):
   root = sub_folders(tmp_path / "s")
   assert run_cli(["layers", "check", "--in", str(root), "--masks", "lid"]) == errors.EXIT_USAGE


def test_bare_folder_without_order_still_says_no_list(tmp_path):
   root = sub_folders(tmp_path / "s")
   assert run_cli(["layers", "check", "--in", str(root)]) == errors.EXIT_ERROR


def test_view_bare_folder(tmp_path):
   root = one_folder(tmp_path / "s")
   rep_path = tmp_path / "r.json"
   assert run_cli(["layers", "view", "--in", str(root), "--order", "bowl,lid", "--out", str(tmp_path / "v.png")], rep_path) == errors.EXIT_OK
   rep = read_json(rep_path)
   assert rep["inferred"] is True and rep["items"] == 2


def test_fill_bare_folder_keeps_form_and_no_layers_json(tmp_path):
   root = one_folder(tmp_path / "s")
   mask = _box(0, 0, W, 2, (255, 255, 255))
   image.save(tmp_path / "m.png", mask)
   out = tmp_path / "out"
   rep_path = tmp_path / "r.json"
   code = run_cli(["layers", "fill", "--in", str(root), "--order", "bowl,lid", "--mask", str(tmp_path / "m.png"),
                   "--nearest", "lid", "--out", str(out)], rep_path)
   assert code == errors.EXIT_OK
   assert not (out / "layers.json").exists()
   assert sorted(p.name for p in out.iterdir()) == ["bowl_f0.png", "bowl_f1.png", "lid_f0.png", "lid_f1.png"]
   assert np.all(image.load(out / "lid_f0.png")[0:2, 2:10, :3] == RED)
   assert read_json(rep_path)["inferred"] is True
