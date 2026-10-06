"""5판-가 : sheet --bg <png> · --on --at --crop · --find."""

from __future__ import annotations

import json

import numpy as np

from arttool import cli, errors, image, sheet


def _sprite(w=4, h=4, color=(255, 0, 0, 255)):
   return image.new(w, h, color)


def _run(tmp_path, extra, name="out.png"):
   out = tmp_path / name
   rep = tmp_path / (name + ".json")
   code = cli.main(["sheet", "--in", str(tmp_path / "in"), "--scale", "2", "--out", str(out), "--report", str(rep)] + extra)
   report = json.loads(rep.read_text(encoding="utf-8")) if rep.exists() else None
   return code, out, report


def _inputs(tmp_path, arrs):
   folder = tmp_path / "in"
   folder.mkdir()
   for i, arr in enumerate(arrs):
      image.save(folder / f"{i}.png", arr)
   return folder


# ── --bg <png> ──

def test_bg_png_tiles_at_cell_scale(tmp_path):
   _inputs(tmp_path, [image.new(4, 4)])          # 다 투명 → 칸이 배경 그대로
   tile = image.new(2, 1, (10, 20, 30, 255))
   tile[0, 1] = (200, 100, 50, 255)
   image.save(tmp_path / "tile.png", tile)
   code, out, rep = _run(tmp_path, ["--bg", str(tmp_path / "tile.png")])
   assert code == errors.EXIT_OK
   assert rep["bg"] == str(tmp_path / "tile.png")
   sheet_img = image.load(out)
   cell = sheet.render_kind(image.new(4, 4), "zoom", 2, bg=tile)
   # 배율 2 : 가로 2픽셀씩 두 색이 번갈아
   assert tuple(cell[0, 0]) == (10, 20, 30, 255) and tuple(cell[0, 1]) == (10, 20, 30, 255)
   assert tuple(cell[0, 2]) == (200, 100, 50, 255)
   assert tuple(cell[7, 7]) == (200, 100, 50, 255)
   assert sheet_img.shape[0] >= 8


def test_bg_semi_transparent_tile_over_checker():
   tile = image.new(1, 1, (255, 255, 255, 0))
   cell = sheet.render_kind(image.new(2, 2), "zoom", 1, bg=tile)
   assert np.array_equal(cell, sheet.backdrop(2, 2, None))


def test_bg_color_and_missing_file(tmp_path):
   _inputs(tmp_path, [_sprite()])
   code, out, rep = _run(tmp_path, ["--bg", "#203040"])
   assert code == errors.EXIT_OK and rep["bg"] == "#203040" and "on" not in rep
   code, _, _ = _run(tmp_path, ["--bg", str(tmp_path / "nope.png")], name="b.png")
   assert code == 2
   code, _, _ = _run(tmp_path, ["--bg", "#zzzzzz"], name="c.png")
   assert code == 2


def test_bg_png_same_as_out_is_rejected(tmp_path):
   _inputs(tmp_path, [_sprite()])
   tile = tmp_path / "out.png"
   image.save(tile, _sprite(1, 1, (1, 2, 3, 255)))
   before = tile.read_bytes()
   code, _, _ = _run(tmp_path, ["--bg", str(tile)])
   assert code != errors.EXIT_OK
   assert tile.read_bytes() == before


# ── --on --at --crop ──

def _scene(tmp_path, w=10, h=6):
   scene = image.new(w, h, (0, 0, 255, 255))
   scene[0, 0] = (0, 0, 0, 0)                    # 투명 칸 하나 — 여기에만 --bg 가 보인다
   image.save(tmp_path / "scene.png", scene)
   return scene


def test_on_at_cell_is_scene_size_and_report(tmp_path):
   _inputs(tmp_path, [_sprite(), _sprite(color=(0, 255, 0, 255))])
   _scene(tmp_path)
   code, out, rep = _run(tmp_path, ["--on", str(tmp_path / "scene.png"), "--at", "2,1", "--bg", "#ffffff"])
   assert code == errors.EXIT_OK
   assert rep["on"] == {"scene": str(tmp_path / "scene.png"), "at": [2, 1], "crop": None, "find": None,
                        "find_count": None, "find_clear": False}
   assert rep["items"][0]["size"] == [4, 4]       # 보고는 입력 그림 그대로
   assert rep["warnings"] == []
   cell = sheet.render_kind(sheet.place_on(image.load(tmp_path / "scene.png"), _sprite(), 2, 1)[0], "zoom", 2,
                            bg=(255, 255, 255, 255))
   assert cell.shape[:2] == (12, 20)
   assert tuple(cell[2, 4]) == (255, 0, 0, 255)  # 얹은 자리
   assert tuple(cell[0, 0]) == (255, 255, 255, 255)  # 투명 칸에만 --bg
   assert tuple(cell[0, 2]) == (0, 0, 255, 255)


def test_on_clipped_warning_and_crop(tmp_path):
   _inputs(tmp_path, [_sprite()])
   _scene(tmp_path)
   code, _, rep = _run(tmp_path, ["--on", str(tmp_path / "scene.png"), "--at", "8,-1"])
   assert code == errors.EXIT_OK
   assert [w["rule"] for w in rep["warnings"]] == ["on_clipped"]
   code, out, rep = _run(tmp_path, ["--on", str(tmp_path / "scene.png"), "--at", "1,1", "--crop", "1,1,4,4"], name="c.png")
   assert code == errors.EXIT_OK and rep["on"]["crop"] == [1, 1, 4, 4] and rep["warnings"] == []
   spec = _spec(tmp_path / "scene.png", at="1,1", crop="1,1,4,4", files=[tmp_path / "x.png"])
   assert spec["rel"] == [0, 0] and spec["scene"].shape[:2] == (4, 4)     # 장면은 상자로 먼저 잘린다
   cells, _ = sheet.compose_scene([_sprite()], [tmp_path / "x.png"], spec)
   assert cells[0].shape[:2] == (4, 4) and np.all(cells[0][:, :, 0] == 255)


def test_on_bad_args(tmp_path):
   _inputs(tmp_path, [_sprite()])
   _scene(tmp_path)
   scene = str(tmp_path / "scene.png")
   bad = [["--at", "1,1"],                                  # --on 없이
          ["--on", scene],                                  # --at · --find 없음
          ["--on", scene, "--at", "1"],
          ["--on", scene, "--at", "a,b"],
          ["--on", scene, "--at", "1,1", "--crop", "0,0,0,3"],
          ["--on", scene, "--at", "1,1", "--crop", "8,0,4,4"],  # 장면 밖
          ["--on", scene, "--at", "1,1", "--find", scene],
          ["--strip", "--on", scene, "--at", "1,1"]]
   for i, extra in enumerate(bad):
      code, out, _ = _run(tmp_path, extra, name=f"bad{i}.png")
      assert code == 2, extra
      assert not out.exists()


def test_on_scene_same_as_out_is_rejected(tmp_path):
   _inputs(tmp_path, [_sprite()])
   _scene(tmp_path)
   before = (tmp_path / "scene.png").read_bytes()
   code, _, _ = _run(tmp_path, ["--on", str(tmp_path / "scene.png"), "--at", "0,0"], name="scene.png")
   assert code != errors.EXIT_OK
   assert (tmp_path / "scene.png").read_bytes() == before


# ── --find ──

def test_find_spots_exact_and_ignores_alpha0():
   scene = image.new(12, 8, (0, 0, 255, 255))
   scene[3:5, 6:8] = (255, 0, 0, 255)
   old = image.new(3, 2, (255, 0, 0, 255))
   old[:, 2] = (0, 0, 0, 0)                       # 투명 칸은 비교 안 함
   assert sheet.find_spots(scene, old) == ([[6, 3]], 1)
   scene[6:8, 0:2] = (255, 0, 0, 255)
   assert sheet.find_spots(scene, old) == ([[6, 3], [0, 6]], 2)
   assert sheet.find_spots(scene, image.new(2, 2, (9, 9, 9, 255))) == ([], 0)


def test_find_cli_zero_one_many(tmp_path):
   _inputs(tmp_path, [_sprite(2, 2, (0, 255, 0, 255))])
   scene = image.new(10, 6, (0, 0, 255, 255))
   scene[2:4, 5:7] = (255, 0, 0, 255)
   image.save(tmp_path / "scene.png", scene)
   image.save(tmp_path / "old.png", _sprite(2, 2))
   base = ["--on", str(tmp_path / "scene.png"), "--find", str(tmp_path / "old.png")]
   code, _, rep = _run(tmp_path, base)
   assert code == errors.EXIT_OK and rep["on"]["at"] == [5, 2] and rep["warnings"] == []
   scene[0:2, 0:2] = (255, 0, 0, 255)
   image.save(tmp_path / "scene.png", scene)
   code, _, rep = _run(tmp_path, base, name="m.png")
   assert code == errors.EXIT_OK and rep["on"]["at"] == [0, 0]
   assert rep["warnings"][0]["rule"] == "find_many" and rep["warnings"][0]["items"] == [[0, 0], [5, 2]]
   image.save(tmp_path / "old.png", _sprite(2, 2, (7, 7, 7, 255)))
   code, _, _ = _run(tmp_path, base, name="z.png")
   assert code == 2


def test_find_large_scene_is_fast():
   import time
   rng = np.random.default_rng(1)
   scene = rng.integers(0, 256, (1080, 1920, 4), dtype=np.uint8)
   old = scene[500:564, 900:964].copy()
   started = time.monotonic()
   assert sheet.find_spots(scene, old) == ([[900, 500]], 1)
   assert time.monotonic() - started < 2.0


# ── 리뷰 고침 (5판-가 리뷰) ──

def _spec(scene_path, **kw):
   from types import SimpleNamespace
   args = SimpleNamespace(on_scene=str(scene_path), at=kw.get("at"), crop=kw.get("crop"),
                          find_old=kw.get("find"), find_clear=kw.get("clear", False))
   return sheet.scene_options(args, kw.get("files", [scene_path]))


def test_crop_memory_is_box_sized(tmp_path):
   import tracemalloc
   image.save(tmp_path / "big.png", image.new(2048, 2048, (0, 0, 255, 255)))
   files = [tmp_path / f"{i}.png" for i in range(20)]
   items = [_sprite(4, 4)] * 20
   tracemalloc.start()
   try:
      spec = _spec(tmp_path / "big.png", at="1000,1000", crop="996,996,8,8", files=files)
      cells, _ = sheet.compose_scene(items, files, spec)
      _, peak = tracemalloc.get_traced_memory()
   finally:
      tracemalloc.stop()
   one = 2048 * 2048 * 4
   assert one // 2 < peak < 3 * one               # 예전엔 칸마다 장면 전체 사본(20장 = 20배). 아래 끝은 numpy 가 잡히는지
   assert all(c.shape == (8, 8, 4) for c in cells) and spec["scene"].shape == (8, 8, 4)
   assert (cells[0][4:8, 4:8] == (255, 0, 0, 255)).all() and (cells[0][0, 0] == (0, 0, 255, 255)).all()


def test_find_list_capped_with_total_count():
   scene = image.new(30, 30, (5, 6, 7, 255))
   spots, count = sheet.find_spots(scene, image.new(1, 1, (5, 6, 7, 255)))
   assert count == 900 and len(spots) == sheet.FIND_LIST_MAX == 20
   assert spots[:3] == [[0, 0], [1, 0], [2, 0]] and spots[-1] == [19, 0]


def test_find_many_report_has_total(tmp_path):
   _inputs(tmp_path, [_sprite(1, 1, (0, 255, 0, 255))])
   image.save(tmp_path / "scene.png", image.new(6, 5, (5, 6, 7, 255)))
   image.save(tmp_path / "old.png", image.new(1, 1, (5, 6, 7, 255)))
   code, _, rep = _run(tmp_path, ["--on", str(tmp_path / "scene.png"), "--find", str(tmp_path / "old.png")])
   assert code == errors.EXIT_OK and rep["on"]["find_count"] == 30
   warn = rep["warnings"][0]
   assert warn["rule"] == "find_many" and "30곳" in warn["detail"] and len(warn["items"]) == 20


def test_on_find_missing_or_bad_file_is_usage_error(tmp_path):
   _inputs(tmp_path, [_sprite()])
   image.save(tmp_path / "scene.png", image.new(10, 6, (0, 0, 255, 255)))
   (tmp_path / "bad.png").write_text("not png", encoding="utf-8")
   scene = str(tmp_path / "scene.png")
   for extra in (["--on", str(tmp_path / "none.png"), "--at", "0,0"],
                 ["--on", str(tmp_path / "bad.png"), "--at", "0,0"],
                 ["--on", scene, "--find", str(tmp_path / "none.png")],
                 ["--on", scene, "--find", str(tmp_path / "bad.png")],
                 ["--on", scene, "--at", "0,0", "--find-clear"],
                 ["--find-clear"]):
      code, _, _ = _run(tmp_path, extra, name="x.png")
      assert code == 2, extra


def test_find_clear_erases_old_opaque_cells(tmp_path):
   scene = image.new(10, 6, (0, 0, 255, 255))
   scene[2:4, 5:7] = (255, 0, 0, 255)
   image.save(tmp_path / "scene.png", scene)
   image.save(tmp_path / "old.png", _sprite(2, 2))
   new = _sprite(1, 1, (0, 255, 0, 255))
   files = [tmp_path / "n.png"]
   for clear, rest in ((False, (255, 0, 0, 255)), (True, (0, 0, 0, 0))):
      spec = _spec(tmp_path / "scene.png", find=str(tmp_path / "old.png"), clear=clear, files=files)
      cell = sheet.compose_scene([new], files, spec)[0][0]
      assert (cell[2, 5] == (0, 255, 0, 255)).all()
      assert (cell[2, 6] == rest).all() and (cell[3, 5] == rest).all() and (cell[3, 6] == rest).all()
      assert (cell[0, 0] == (0, 0, 255, 255)).all()


def test_find_clear_cli_report(tmp_path):
   _inputs(tmp_path, [_sprite(1, 1, (0, 255, 0, 255))])
   scene = image.new(10, 6, (0, 0, 255, 255))
   scene[2:4, 5:7] = (255, 0, 0, 255)
   image.save(tmp_path / "scene.png", scene)
   image.save(tmp_path / "old.png", _sprite(2, 2))
   code, _, rep = _run(tmp_path, ["--on", str(tmp_path / "scene.png"), "--find", str(tmp_path / "old.png"), "--find-clear"])
   assert code == errors.EXIT_OK and rep["on"]["find_clear"] is True and rep["on"]["at"] == [5, 2]


def test_out_same_as_find_bg_scene_is_rejected(tmp_path):
   import hashlib
   _inputs(tmp_path, [_sprite()])
   image.save(tmp_path / "scene.png", image.new(10, 6, (0, 0, 255, 255)))
   image.save(tmp_path / "old.png", image.new(1, 1, (0, 0, 255, 255)))
   image.save(tmp_path / "tile.png", image.new(2, 2, (9, 9, 9, 255)))
   base = ["--on", str(tmp_path / "scene.png"), "--find", str(tmp_path / "old.png"), "--bg", str(tmp_path / "tile.png")]
   for name in ("scene.png", "old.png", "tile.png"):
      before = hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()
      code, _, _ = _run(tmp_path, base, name=name)
      assert code != errors.EXIT_OK, name
      assert hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() == before


def test_half_alpha_sprite_on_opaque_scene_value(tmp_path):
   image.save(tmp_path / "scene.png", image.new(4, 4, (0, 0, 255, 255)))
   files = [tmp_path / "s.png"]
   spec = _spec(tmp_path / "scene.png", at="1,1", files=files)
   cell = sheet.compose_scene([_sprite(1, 1, (255, 0, 0, 128))], files, spec)[0][0]
   # a = 128/255 : r = 255·a = 128.0 → 128, b = 255·(1-a) = 127.0 → 127, 알파 1
   assert tuple(cell[1, 1]) == (128, 0, 127, 255) and tuple(cell[0, 0]) == (0, 0, 255, 255)


def test_on_with_bg_png_shows_tile_in_transparent_scene(tmp_path):
   scene = image.new(3, 1, (0, 0, 255, 255))
   scene[0, 2] = (0, 0, 0, 0)
   image.save(tmp_path / "scene.png", scene)
   files = [tmp_path / "s.png"]
   spec = _spec(tmp_path / "scene.png", at="0,0", files=files)
   cell = sheet.compose_scene([_sprite(1, 1, (255, 0, 0, 255))], files, spec)[0][0]
   tile = image.new(1, 1, (10, 200, 30, 255))
   out = sheet.render_kind(cell, "zoom", 1, bg=tile)
   assert tuple(out[0, 0]) == (255, 0, 0, 255) and tuple(out[0, 1]) == (0, 0, 255, 255)
   assert tuple(out[0, 2]) == (10, 200, 30, 255)     # 장면의 투명 칸에 타일이 비친다


# 새 옵션 없는 sheet 가 5판 전과 같은가 — `git archive HEAD src` 옛 소스로 한 번 구한 값 (2026-10-07)
OLD_DIGEST = "b37ab76ef93c8e9ec6a4a91bdcdcb65b1eaabd624cc5e3e104c13ff7fcaa7770"


def test_sheet_without_new_options_matches_old(tmp_path):
   import hashlib
   folder = tmp_path / "in"
   folder.mkdir()
   a = image.new(5, 3, (200, 40, 40, 255))
   a[1, 2] = (0, 0, 0, 0)
   a[0, 0] = (30, 200, 90, 128)
   b = image.new(3, 4, (10, 20, 230, 255))
   b[2:, 1] = (250, 250, 0, 255)
   image.save(folder / "a.png", a)
   image.save(folder / "b.png", b)
   out = tmp_path / "out.png"
   code = cli.main(["sheet", "--in", str(folder), "--scale", "3", "--kinds", "zoom,silhouette", "--bg", "#203040",
                    "--label", "--out", str(out)])
   assert code == errors.EXIT_OK
   assert hashlib.sha256(out.read_bytes()).hexdigest() == OLD_DIGEST
