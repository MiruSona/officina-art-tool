"""7판-나-3 — `layers fill --holes` 겹 자신의 안쪽 구멍을 같은 행 이웃 색으로 메운다 (설계 2026-10-07 3절)."""

from __future__ import annotations

import numpy as np

from arttool import errors, image, layerset
from arttool.jsonio import read_json

from test_layers_ops import run_cli, write_set

W = H = 12
LIGHT, DARK = (180, 180, 180), (90, 90, 90)


def _content():
   """왼쪽 반 밝은 · 오른쪽 반 어두운 네모. (5,5)·(6,5) 두 칸 구멍 — 왼 칸은 밝은 색, 오른 칸은 어두운 색이 가깝다."""
   arr = image.new(W, H)
   arr[2:10, 2:6] = (*LIGHT, 255)
   arr[2:10, 6:10] = (*DARK, 255)
   arr[5, 5] = 0
   arr[5, 6] = 0
   return arr


def _set(tmp_path, big=False):
   content = _content()
   if big:
      content[3:9, 3:4] = 0                     # 6칸 구멍 (--hole-max 로 거른다)
   lid = image.new(W, H)
   lid[0, 0] = (255, 0, 0, 255)
   write_set(tmp_path / "set", {"content": content, "lid": lid})
   return tmp_path / "set"


def _fill(tmp_path, folder, *extra):
   rep = tmp_path / "r.json"
   code = run_cli(["layers", "fill", "--in", str(folder), "--out", str(tmp_path / "out"), *extra], rep)
   return code, (read_json(rep) if rep.exists() else None)


def test_holes_copy_row_neighbour_colors(tmp_path):
   folder = _set(tmp_path)
   code, rep = _fill(tmp_path, folder, "--holes", "content")
   assert code == errors.EXIT_OK
   out = image.load(tmp_path / "out" / "content" / "idle.png")
   assert tuple(out[5, 5, :3]) == LIGHT and tuple(out[5, 6, :3]) == DARK    # 평균이 아니라 결 복사
   assert rep["images"] == [{"item": "idle", "filled": {"content": 2}, "new_colors": {"content": 0}}]
   assert rep["holes"] == ["content"] and rep["hole_max"] == 32
   # 손 안 댄 겹 · 목록은 바이트 그대로
   assert (tmp_path / "out" / "lid" / "idle.png").read_bytes() == (folder / "lid" / "idle.png").read_bytes()
   assert (tmp_path / "out" / "layers.json").read_bytes() == (folder / "layers.json").read_bytes()


def test_tie_goes_left(tmp_path):
   folder = tmp_path / "set"
   content = image.new(W, H)
   content[2:5, 2:5] = (*LIGHT, 255)
   content[3, 4] = (*DARK, 255)
   content[3, 3] = 0                             # 왼쪽 (2,3) 밝음 · 오른쪽 (4,3) 어둠, 거리 같음
   write_set(folder, {"content": content})
   _fill(tmp_path, folder, "--holes", "content")
   assert tuple(image.load(tmp_path / "out" / "content" / "idle.png")[3, 3, :3]) == LIGHT


def test_hole_max_skips_big_hole(tmp_path):
   folder = _set(tmp_path, big=True)
   code, rep = _fill(tmp_path, folder, "--holes", "content", "--hole-max", "4")
   assert code == errors.EXIT_OK
   assert rep["images"][0]["filled"] == {"content": 2}
   assert [w["rule"] for w in rep["warnings"]] == ["fill_hole_skipped"]
   out = image.load(tmp_path / "out" / "content" / "idle.png")
   assert out[4, 3, 3] == 0


def test_holes_refusals(tmp_path):
   folder = _set(tmp_path)
   image.save(tmp_path / "m.png", image.new(W, H, (255, 255, 255, 255)))
   assert _fill(tmp_path, folder)[0] == errors.EXIT_USAGE                                              # 둘 다 없음
   assert _fill(tmp_path, folder, "--holes", "content", "--mask", str(tmp_path / "m.png"), "--nearest", "lid")[0] == errors.EXIT_USAGE
   assert _fill(tmp_path, folder, "--holes", "content", "--color", "#ff0000")[0] == errors.EXIT_USAGE  # 새 색을 만든다
   assert _fill(tmp_path, folder, "--holes", "content", "--nearest", "lid")[0] == errors.EXIT_USAGE
   assert _fill(tmp_path, folder, "--holes", "nope")[0] == errors.EXIT_USAGE
   assert _fill(tmp_path, folder, "--mask", str(tmp_path / "m.png"))[0] == errors.EXIT_USAGE          # --mask 인데 --nearest 없음
   assert _fill(tmp_path, folder, "--holes", "content", "--hole-max", "0")[0] == errors.EXIT_USAGE


def test_holes_refuse_mask_layer(tmp_path):
   folder = tmp_path / "set"
   rows = [{"name": "content", "kind": "content"}, {"name": "zone", "kind": "mask"}]
   layerset.save(folder, layerset.from_dict({"version": 2, "canvas": [W, H], "layers": rows, "items": ["idle"]}))
   image.save(folder / "content" / "idle.png", _content())
   assert _fill(tmp_path, folder, "--holes", "zone")[0] == errors.EXIT_USAGE


def test_holes_dry_run_writes_nothing(tmp_path):
   folder = _set(tmp_path)
   code, rep = _fill(tmp_path, folder, "--holes", "content", "--dry-run")
   assert code == errors.EXIT_OK and rep["dry_run"] is True
   assert not (tmp_path / "out").exists()


def test_holes_bare_folder(tmp_path):
   root = tmp_path / "bare"
   image.save(root / "content_f0.png", _content())
   code, rep = _fill(tmp_path, root, "--order", "content", "--holes", "content")
   assert code == errors.EXIT_OK and rep["inferred"] is True
   assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["content_f0.png"]
   assert np.all(image.load(tmp_path / "out" / "content_f0.png")[5, 5:7, 3] == 255)
