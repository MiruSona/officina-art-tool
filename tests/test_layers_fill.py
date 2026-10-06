"""`layers fill` — 가림판 안 빈 칸을 가장 가까운(체비셰프) 후보 겹에 채워 새 묶음으로 쓴다."""

from __future__ import annotations

import numpy as np

from arttool import errors, image, layerset
from arttool.jsonio import read_json

from test_layers_ops import run_cli, write_set

W = H = 12
RED, BLUE = (200, 0, 0), (0, 0, 200)


def _mask(path, x0, y0, x1, y1):
   arr = image.new(W, H)
   arr[y0:y1, x0:x1] = (255, 255, 255, 255)
   image.save(path, arr)
   return str(path)


def _set(tmp_path):
   """a 는 왼쪽 0~2 열, b 는 오른쪽 9~11 열. 가운데 3~8 열(0~1 행)이 빈 칸."""
   a = image.new(W, H)
   a[0:2, 0:3] = (*RED, 255)
   b = image.new(W, H)
   b[0:2, 9:12] = (*BLUE, 255)
   write_set(tmp_path / "set", {"a": a, "b": b})
   return tmp_path / "set"


def _fill(tmp_path, folder, extra=(), report=None):
   argv = ["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 12, 2),
           "--nearest", "a,b", "--out", str(tmp_path / "out"), *extra]
   return run_cli(argv, report)


def test_nearest_layer_and_tie_goes_first(tmp_path):
   folder = _set(tmp_path)
   before = (folder / "a" / "idle.png").read_bytes()
   rep = tmp_path / "r.json"
   assert _fill(tmp_path, folder, report=rep) == errors.EXIT_OK
   a = image.load(tmp_path / "out" / "a" / "idle.png")
   b = image.load(tmp_path / "out" / "b" / "idle.png")
   # 열 x 의 거리 : a = x-2, b = 9-x → 3~5 열은 a, 6~8 열은 b
   for x in range(3, 9):
      da, db = x - 2, 9 - x
      owner = a if da <= db else b
      assert owner[0, x, 3] == 255, x
   assert tuple(a[0, 5, :3]) == RED and tuple(b[0, 6, :3]) == BLUE
   assert read_json(rep)["images"] == [{"item": "idle", "filled": {"a": 6, "b": 6}}]
   assert (folder / "a" / "idle.png").read_bytes() == before            # 원본 안 바뀜
   assert (tmp_path / "out" / "layers.json").read_bytes() == (folder / "layers.json").read_bytes()


def test_tie_goes_to_first_in_list(tmp_path):
   a = image.new(W, H)
   a[0, 0] = (*RED, 255)
   b = image.new(W, H)
   b[0, 4] = (*BLUE, 255)
   write_set(tmp_path / "set", {"a": a, "b": b})
   argv = ["layers", "fill", "--in", str(tmp_path / "set"), "--mask", _mask(tmp_path / "m.png", 2, 0, 3, 1),
           "--nearest", "b,a", "--out", str(tmp_path / "out")]
   assert run_cli(argv) == errors.EXIT_OK
   assert image.load(tmp_path / "out" / "b" / "idle.png")[0, 2, 3] == 255     # 거리 2 · 2 → 목록 앞 b
   assert image.load(tmp_path / "out" / "a" / "idle.png")[0, 2, 3] == 0


def test_color_option(tmp_path):
   folder = _set(tmp_path)
   assert _fill(tmp_path, folder, ["--color", "#00FF00"]) == errors.EXIT_OK
   a = image.load(tmp_path / "out" / "a" / "idle.png")
   assert tuple(a[0, 3, :3]) == (0, 255, 0) and tuple(a[0, 0, :3]) == RED


def test_no_target_warns(tmp_path):
   folder = _set(tmp_path)
   argv = ["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 12, 2),
           "--nearest", "a", "--out", str(tmp_path / "out")]
   (folder / "a" / "idle.png").unlink()
   rep = tmp_path / "r.json"
   assert run_cli(argv, rep) == errors.EXIT_OK
   assert [w["rule"] for w in read_json(rep)["warnings"]] == ["fill_no_target"]


def test_out_inside_in_or_nonempty_refused(tmp_path):
   folder = _set(tmp_path)
   argv = ["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 12, 2), "--nearest", "a"]
   assert run_cli([*argv, "--out", str(folder / "x")]) == errors.EXIT_USAGE
   (tmp_path / "busy").mkdir()
   (tmp_path / "busy" / "z.txt").write_text("z")
   assert run_cli([*argv, "--out", str(tmp_path / "busy")]) == errors.EXIT_USAGE


def test_dry_run_writes_nothing(tmp_path):
   folder = _set(tmp_path)
   rep = tmp_path / "r.json"
   assert _fill(tmp_path, folder, ["--dry-run"], rep) == errors.EXIT_OK
   assert not (tmp_path / "out").exists()
   assert any(p.endswith("layers.json") for p in read_json(rep)["would_write"])


def _small_set(tmp_path):
   """겹 a(0 열 빨강) · 작은 겹 b(상자 8~11 열, 11 열 파랑) 묶음."""
   a = image.new(W, H)
   a[0:2, 0:1] = (*RED, 255)
   ls = layerset.from_dict({"version": 2, "canvas": [W, H], "items": ["idle"], "layers": [
      {"name": "a", "kind": "deco"}, {"name": "b", "kind": "deco", "size": [4, 2], "offset": [8, 0]}]})
   folder = tmp_path / "set"
   layerset.save(folder, ls)
   image.save(folder / "a" / "idle.png", a)
   small = image.new(4, 2)
   small[:, 3] = (*BLUE, 255)
   image.save(folder / "b" / "idle.png", small)
   return folder


def test_small_layer_box_outside_goes_to_next_nearest(tmp_path):
   """작은 겹 b 는 상자 안만 받고, 상자 밖 칸은 다음으로 가까운 a 가 채운다 — 경고 없음."""
   folder = _small_set(tmp_path)
   rep = tmp_path / "r.json"
   argv = ["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 12, 2),
           "--nearest", "b,a", "--out", str(tmp_path / "out")]
   assert run_cli(argv, rep) == errors.EXIT_OK
   got = image.load(tmp_path / "out" / "b" / "idle.png")
   assert image.size(got) == (4, 2) and np.all(got[..., 3] == 255)
   # 열 x 의 거리 : a = x, b = 11-x → 6~10 열이 b 에 가깝지만 6 · 7 열은 b 상자 밖이라 a 가 채운다
   assert read_json(rep)["warnings"] == []
   out_a = image.load(tmp_path / "out" / "a" / "idle.png")
   assert np.all(out_a[0:2, 0:8, 3] == 255) and np.all(out_a[0:2, 8:12, 3] == 0)


def test_small_layer_warns_when_no_candidate_can_fill(tmp_path):
   """후보가 작은 겹 b 하나뿐이면 상자 밖 칸은 비우고 fill_outside_box 로 알린다."""
   folder = _small_set(tmp_path)
   rep = tmp_path / "r.json"
   argv = ["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 12, 2),
           "--nearest", "b", "--out", str(tmp_path / "out")]
   assert run_cli(argv, rep) == errors.EXIT_OK
   # 빈 칸 1~10 열 중 8~10 열은 b 가 채우고, 1~7 열(2행 → 14칸)은 상자 밖이라 비운다
   warns = read_json(rep)["warnings"]
   assert [w["rule"] for w in warns] == ["fill_outside_box"] and "14개" in warns[0]["detail"]
   assert np.all(image.load(tmp_path / "out" / "b" / "idle.png")[..., 3] == 255)
   assert image.load(tmp_path / "out" / "a" / "idle.png")[0, 6, 3] == 0


def test_unknown_item_message_says_picture(tmp_path, capsys):
   """--items 에 없는 이름은 「겹」 이 아니라 「그림」 으로 알린다."""
   folder = _small_set(tmp_path)
   argv = ["layers", "fill", "--in", str(folder), "--mask", _mask(tmp_path / "m.png", 0, 0, 12, 2),
           "--nearest", "b", "--items", "zzz", "--out", str(tmp_path / "out")]
   assert run_cli(argv) == errors.EXIT_USAGE
   err = capsys.readouterr().err
   assert "겹 묶음에 없는 그림 : zzz (있는 그림 : idle)" in err and "없는 겹" not in err
