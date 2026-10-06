"""`frames bake` — 발 줄 · 덮기 · 자르기 · 띠 · gif · 거절."""
from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from arttool import cli, errors, image
from arttool.frames import bake

RED = (255, 0, 0, 255)


def _frames(folder, feet, size=(6, 6)):
   """프레임마다 x=2 에 두 칸 세로 막대. feet[i] = 맨 아래 줄 y. 이름은 f1 · f2 · f10 순서를 시험하려고 일부러 섞는다."""
   folder.mkdir(parents=True, exist_ok=True)
   names = ["f1", "f2", "f10", "f11"][: len(feet)]
   for name, foot in zip(names, feet):
      arr = image.new(*size)
      arr[foot - 1:foot + 1, 2] = RED
      image.save(folder / f"{name}.png", arr)
   return names


def _bake(tmp_path, monkeypatch, *extra):
   monkeypatch.chdir(tmp_path)
   args = cli.build_parser().parse_args(["frames", "bake", "--in", "f", "--out", "o", *extra])
   try:
      return errors.EXIT_OK, bake.run(args)
   except errors.UsageError:
      return errors.EXIT_USAGE, None


def test_foot_auto_and_natural_order(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [3, 4, 5])
   code, rep = _bake(tmp_path, monkeypatch, "--foot", "auto")
   assert code == errors.EXIT_OK
   assert [r["name"] for r in rep["images"]] == ["f1", "f2", "f10"]
   assert [r["shift_y"] for r in rep["images"]] == [0, -1, -2]
   for name in ("f1", "f2", "f10"):
      assert image.bbox(image.load(tmp_path / "o" / f"{name}.png"))[3] - 1 == 3


def test_foot_clipped_warning(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [1, 5])
   code, rep = _bake(tmp_path, monkeypatch, "--foot", "0")
   assert len(rep["warnings"]) == 1 and "frames.foot_clipped" in json.dumps(rep["warnings"])
   assert "f10" not in json.dumps(rep["warnings"]) and "f2" in json.dumps(rep["warnings"])


def test_cover_counts_changed_cells(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [3, 4])
   mask = image.new(6, 6)
   mask[0:6, 2] = (255, 255, 255, 255)
   image.save(tmp_path / "m.png", mask)
   code, rep = _bake(tmp_path, monkeypatch, "--cover", "m.png")
   assert [r["covered"] for r in rep["images"]] == [0, 2]   # 첫 프레임이 기준 : 둘째는 두 칸이 바뀐다(4번 줄 지움 · 2번 줄 칠함)
   assert np.array_equal(image.load(tmp_path / "o" / "f2.png"), image.load(tmp_path / "f" / "f1.png"))


def test_union_crop_strip_and_gif(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [3, 4])
   code, rep = _bake(tmp_path, monkeypatch, "--crop", "union", "--strip", "s.png", "--gif", "a.gif", "--scale", "2", "--duration", "80")
   assert code == errors.EXIT_OK
   assert rep["crop"] == {"x": 2, "y": 2, "w": 1, "h": 3}
   assert image.load(tmp_path / "o" / "f1.png").shape[:2] == (3, 1)
   assert image.load(tmp_path / "s.png").shape[:2] == (6, 4)   # 2배 · 두 장 가로
   with Image.open(tmp_path / "a.gif") as gif:
      assert gif.n_frames == 2 and gif.size == (2, 6) and gif.info["duration"] == 80
   assert rep["gif"]["frames"] == 2


def test_gif_alpha_cut_warning(tmp_path, monkeypatch):
   (tmp_path / "f").mkdir()
   for i in range(2):
      arr = image.new(4, 4)
      arr[i, 1] = (0, 0, 255, 128)
      image.save(tmp_path / "f" / f"f{i}.png", arr)
   code, rep = _bake(tmp_path, monkeypatch, "--gif", "a.gif")
   assert "frames.gif_alpha_cut" in json.dumps(rep["warnings"])


@pytest.mark.parametrize("extra", [["--duration", "50"], ["--cover-from", "x.png"], ["--crop", "0,0,9,9"], ["--foot", "abc"], ["--scale", "0"]])
def test_bad_args_refused(tmp_path, monkeypatch, extra):
   _frames(tmp_path / "f", [3, 4])
   code, _ = _bake(tmp_path, monkeypatch, *extra)
   assert code == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists()


def _bake_argv(tmp_path, monkeypatch, *argv):
   """--in · --out 까지 직접 주는 판. 경로 가드 거절(ArtToolError 무리)도 거절로 센다."""
   monkeypatch.chdir(tmp_path)
   args = cli.build_parser().parse_args(["frames", "bake", *argv])
   try:
      return errors.EXIT_OK, bake.run(args)
   except errors.ArtToolError:
      return errors.EXIT_USAGE, None


def _hashes(folder):
   return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def test_duration_total_limit_refused_before_any_write(tmp_path, monkeypatch):
   # 400000ms × 2장 > 655350 — 예전엔 프레임 PNG 를 쓴 뒤 struct 날 오류(종료 1)로 죽었다
   _frames(tmp_path / "f", [3, 3])        # 똑같은 두 장 — Pillow 가 합쳐 지연을 더하는 최악
   code, _ = _bake(tmp_path, monkeypatch, "--gif", "a.gif", "--duration", "400000", "--strip", "s.png")
   assert code == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists() and not (tmp_path / "a.gif").exists() and not (tmp_path / "s.png").exists()
   code, _ = _bake(tmp_path, monkeypatch, "--gif", "a.gif", "--duration", str(655350 // 2))   # 딱 한도는 진짜 저장까지 통과
   assert code == errors.EXIT_OK and (tmp_path / "a.gif").exists()


def test_save_gif_duration_limit_checked_without_write(tmp_path):
   # tint --gif 도 이 write=False 검사를 쓰기 전에 거친다
   frames = [image.new(2, 2)] * 3
   with pytest.raises(errors.UsageError):
      image.save_gif(frames, tmp_path / "a.gif", 218451, write=False)
   assert image.save_gif(frames, tmp_path / "a.gif", 218450, write=False) == 0
   assert not (tmp_path / "a.gif").exists()


def test_strip_size_checked_before_scaling(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [3, 4])
   monkeypatch.setattr(image, "MAX_PIXELS", 100)       # 띠 24x12 = 288 > 100

   def boom(*_):
      raise AssertionError("크기 검사 전에 키운 그림을 만들었다")
   monkeypatch.setattr(bake, "scaled", boom)
   code, _ = _bake_argv(tmp_path, monkeypatch, "--in", "f", "--out", "o", "--strip", "s.png", "--scale", "2")
   assert code == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists() and not (tmp_path / "s.png").exists()


def test_gif_total_pixels_refused(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [2, 3, 4, 5])
   monkeypatch.setattr(bake, "GIF_MAX_TOTAL_PIXELS", 100)   # 4장 × 6x6 = 144 > 100
   code, _ = _bake(tmp_path, monkeypatch, "--gif", "a.gif")
   assert code == errors.EXIT_USAGE
   assert not (tmp_path / "o").exists() and not (tmp_path / "a.gif").exists()


@pytest.mark.parametrize("out", ["f", "f/sub"])
def test_out_same_or_inside_in_refused(tmp_path, monkeypatch, out):
   _frames(tmp_path / "f", [3, 4])
   before = _hashes(tmp_path / "f")
   code, _ = _bake_argv(tmp_path, monkeypatch, "--in", "f", "--out", out, "--foot", "0")
   assert code == errors.EXIT_USAGE
   assert _hashes(tmp_path / "f") == before


@pytest.mark.parametrize("strip", ["f/f1.png", "m.png", "o/f1.png"])
def test_strip_clashing_path_refused(tmp_path, monkeypatch, strip):
   _frames(tmp_path / "f", [3, 4])
   image.save(tmp_path / "m.png", image.new(6, 6))
   before = _hashes(tmp_path / "f")
   code, _ = _bake(tmp_path, monkeypatch, "--cover", "m.png", "--strip", strip)
   assert code == errors.EXIT_USAGE
   assert _hashes(tmp_path / "f") == before and not (tmp_path / "o").exists()


def test_too_many_frames_refused(tmp_path, monkeypatch):
   (tmp_path / "f").mkdir()
   one = image.new(1, 1)
   for i in range(bake.MAX_FRAMES + 1):
      image.save(tmp_path / "f" / f"f{i}.png", one)
   code, _ = _bake(tmp_path, monkeypatch)
   assert code == errors.EXIT_USAGE and not (tmp_path / "o").exists()


def test_natural_key_order():
   from pathlib import Path
   names = ["f10.png", "F2.png", "f1.png", "f11.png"]
   assert [p.name for p in sorted(map(Path, names), key=bake.natural_key)] == ["f1.png", "F2.png", "f10.png", "f11.png"]


def test_empty_frame_keeps_shift_zero(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [3, 4, 5])
   image.save(tmp_path / "f" / "f2.png", image.new(6, 6))   # 가운데 프레임을 비운다
   code, rep = _bake(tmp_path, monkeypatch, "--foot", "auto")
   assert code == errors.EXIT_OK
   assert [r["shift_y"] for r in rep["images"]] == [0, 0, -2]


def test_cover_ignores_rgb_under_zero_alpha(tmp_path, monkeypatch):
   (tmp_path / "f").mkdir()
   first, second = image.new(4, 4), image.new(4, 4)
   second[0, 0] = (9, 9, 9, 0)            # 알파 0 끼리 RGB 만 다르다 — 보이는 차이가 없다
   second[1, 1] = RED                     # 이 칸만 진짜 다르다
   image.save(tmp_path / "f" / "f1.png", first)
   image.save(tmp_path / "f" / "f2.png", second)
   mask = image.new(4, 4)
   mask[:, :] = (255, 255, 255, 255)
   image.save(tmp_path / "m.png", mask)
   code, rep = _bake(tmp_path, monkeypatch, "--cover", "m.png")
   assert [r["covered"] for r in rep["images"]] == [0, 1]


def test_reserved_names_include_zero():
   from arttool import layerset
   for name in ("com0", "LPT0.png", "com9", "con"):
      assert layerset._reserved(name)
   assert not layerset._reserved("com") and not layerset._reserved("com10")


def test_report_not_taken():
   # frames bake 는 --report 를 받지 않는다 — 받게 되면 REPORT_GUARDED 에 cover_from · strip 을 더한다
   with pytest.raises(SystemExit):
      cli.build_parser().parse_args(["frames", "bake", "--in", "f", "--out", "o", "--report", "r.json"])


def test_different_sizes_refused(tmp_path, monkeypatch):
   _frames(tmp_path / "f", [3])
   image.save(tmp_path / "f" / "f2.png", image.new(5, 6))
   code, _ = _bake(tmp_path, monkeypatch)
   assert code == errors.EXIT_USAGE
