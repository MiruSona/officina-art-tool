"""`cutout` 시험. 그림은 모두 코드로 만든 합성 그림이다."""

from __future__ import annotations

import json

import numpy as np
import pytest

from arttool import cli, errors, image
from arttool.edit.cutout import cutout, flood, image_warnings, looks_like_background, parse_key

WHITE = (255, 255, 255, 255)
RED = (200, 30, 30, 255)


def _subject(size=16, fill=WHITE):
   arr = image.new(size, size, fill)
   arr[5:11, 5:11] = RED
   return arr


def test_edge_erases_white_background():
   out, info = cutout(_subject(), parse_key("edge"))
   assert info["erased"] == 16 * 16 - 36
   assert info["bbox"] == [5, 5, 11, 11]
   assert int(np.count_nonzero(out[:, :, 3])) == 36
   assert info["seeds"] == ["#FFFFFF"]


def test_corner_key():
   out, info = cutout(_subject(), parse_key("corner"))
   assert info["bbox"] == [5, 5, 11, 11]


def test_result_has_no_soft_alpha():
   arr = _subject()
   arr[0:3, :] = (250, 250, 250, 255)  # tol 안의 살짝 다른 흰색
   out, _ = cutout(arr, "edge", tol=10)
   assert not image.has_soft_alpha(out)
   assert set(np.unique(out[:, :, 3])) <= {0, 255}


def test_gradient_does_not_leak_into_subject():
   # 바깥에서 안쪽으로 한 바퀴마다 4씩 어두워진다. 이웃끼리는 4만 달라 이웃과 견주면 끝까지 번진다.
   arr = image.new(20, 20)
   for y in range(20):
      for x in range(20):
         depth = min(x, y, 19 - x, 19 - y)
         arr[y, x] = (255 - 4 * depth,) * 3 + (255,)
   out, info = cutout(arr, "edge", tol=10)
   # 씨앗 255 와 10 안인 바깥 세 바퀴(255 · 251 · 247)만 지운다.
   assert info["erased"] == 20 * 20 - 14 * 14
   assert out[10, 10, 3] == 255
   assert info["bbox"] == [3, 3, 17, 17]


def test_white_band_needs_shave():
   # 위 · 아래에만 흰 띠 4줄 (받은 그림에서 본 꼴). 진짜 바탕은 왼 · 오른 변에 닿는다.
   arr = image.new(20, 20, WHITE)
   arr[4:16, :] = (40, 40, 120, 255)
   arr[8:12, 8:12] = RED
   _, plain = cutout(arr, "edge")
   assert plain["edge_left"] > 0  # 흰 띠만 지우고 파란 바탕이 변에 남았다
   out, shaved = cutout(arr, "edge", shave=4)
   assert shaved["edge_left"] == 0
   assert shaved["bbox"] == [8, 8, 12, 12]
   assert int(np.count_nonzero(out[:, :, 3])) == 16


def test_enclosed_ring_inside_counted():
   arr = image.new(16, 16, WHITE)
   arr[3:13, 3:13] = RED
   arr[6:10, 6:10] = WHITE  # 고리 안쪽 바탕
   out, info = cutout(arr, "edge")
   assert info["enclosed"] == 16
   assert out[7, 7, 3] == 255


def test_hex_key_erases_far_spots():
   arr = image.new(16, 16, WHITE)
   arr[3:13, 3:13] = RED
   arr[6:10, 6:10] = WHITE
   out, info = cutout(arr, parse_key("#FFFFFF"))
   assert out[7, 7, 3] == 0
   assert info["enclosed"] == 0
   assert int(np.count_nonzero(out[:, :, 3])) == 100 - 16


def test_bad_key_is_usage_error():
   with pytest.raises(errors.UsageError):
      parse_key("middle")
   with pytest.raises(errors.UsageError):
      parse_key("#GG0000")


def test_cli_folder_and_report(tmp_path, capsys):
   src = tmp_path / "raw"
   image.save(src / "a.png", _subject())
   image.save(src / "b.png", _subject(fill=(0, 255, 0, 255)))
   report = tmp_path / "r.json"
   code = cli.main(["cutout", "--in", str(src), "--out", str(tmp_path / "clean"), "--report", str(report)])
   assert code == errors.EXIT_OK
   data = json.loads(report.read_text(encoding="utf-8"))
   assert data["status"] == "ok"
   assert [r["file"] for r in data["images"]] == ["a.png", "b.png"]
   assert image.bbox(image.load(tmp_path / "clean" / "b.png")) == (5, 5, 11, 11)


def test_cli_single_file_to_png(tmp_path, capsys):
   src = tmp_path / "a.png"
   image.save(src, _subject())
   assert cli.main(["cutout", "--in", str(src), "--out", str(tmp_path / "x.png")]) == errors.EXIT_OK
   assert (tmp_path / "x.png").is_file()


def test_cli_refuses_overwrite(tmp_path, capsys):
   src = tmp_path / "raw"
   image.save(src / "a.png", _subject())
   assert cli.main(["cutout", "--in", str(src), "--out", str(src)]) == errors.EXIT_USAGE
   assert cli.main(["cutout", "--in", str(src / "a.png"), "--out", str(src / "a.png")]) == errors.EXIT_USAGE
   assert image.load(src / "a.png")[0, 0, 3] == 255


def test_cli_warns_when_almost_everything_erased(tmp_path, capsys):
   src = tmp_path / "a.png"
   image.save(src, image.new(8, 8, WHITE))
   report = tmp_path / "r.json"
   assert cli.main(["cutout", "--in", str(src), "--out", str(tmp_path / "o"), "--report", str(report)]) == errors.EXIT_OK
   data = json.loads(report.read_text(encoding="utf-8"))
   assert data["status"] == "warn"
   hit = [w for w in data["warnings"] if w["rule"] == "cutout.erased_most"]
   assert hit and "90%" in hit[0]["detail"] and hit[0]["items"] == ["a.png"]


def test_warnings_use_check_shape():
   """경고 꼴이 다른 명령과 같다 — {rule, ok: false, detail, items} (R1-M4)."""
   info = cutout(image.new(8, 8, WHITE), "edge")[1]
   found = image_warnings("a.png", info)
   assert found and all(set(w) == {"rule", "ok", "detail", "items"} and w["ok"] is False for w in found)


def _framed_icon():
   """실물 버그 1 합성 그림 : 56×56, 바깥 4칸 흰색, 그 안 2칸 틀 #5A3223, 안쪽 아무 색."""
   arr = image.new(56, 56, WHITE)
   arr[4:52, 4:52] = (0x5A, 0x32, 0x23, 255)
   rng = np.random.default_rng(1)
   arr[6:50, 6:50, :3] = rng.integers(60, 200, size=(44, 44, 3))
   return arr


def test_shave_seeds_from_shaved_ring_and_keeps_frame():
   """--shave 씨앗은 깎아 낸 고리에서 — 틀 색이 씨앗이 되어 틀을 지우던 버그 (실물 #21 / 버그 1)."""
   arr = _framed_icon()
   out, info = cutout(arr, "edge", shave=4)
   assert info["seeds"] == ["#FFFFFF"]
   assert info["bbox"] == [4, 4, 52, 52]                   # 틀이 그대로 남는다
   assert np.array_equal(out[4:52, 4:52], arr[4:52, 4:52])
   assert not out[:4, :, 3].any() and not out[:, :4, 3].any()
   assert not any(w["rule"] == "cutout.edge_left" for w in image_warnings("a", info))   # 깎았으면 틀은 남아도 된다


def test_shave_corner_key_also_uses_original_corner():
   out, info = cutout(_framed_icon(), "corner", shave=4)
   assert info["seeds"] == ["#FFFFFF"] and info["bbox"] == [4, 4, 52, 52]


def test_flood_matches_one_step_growth():
   """토막째 칠하는 번지기가 한 칸씩 넓히는 번지기와 같은 답을 낸다."""
   rng = np.random.default_rng(7)
   for _ in range(5):
      passable = rng.random((40, 50)) < 0.6
      start = np.zeros_like(passable)
      start[0, :] = True
      reach = start & passable
      while True:
         grown = reach.copy()
         grown[1:] |= reach[:-1]
         grown[:-1] |= reach[1:]
         grown[:, 1:] |= reach[:, :-1]
         grown[:, :-1] |= reach[:, 1:]
         grown &= passable
         if (grown == reach).all():
            break
         reach = grown
      assert np.array_equal(flood(start, passable), reach)


def test_flood_snake_path_is_fast():
   """구불구불한 길(꺾임 많은 바탕)도 빨리 끝난다 — 1200×1200 에서 몇 초 걸리던 것."""
   import time
   passable = np.ones((1200, 1200), dtype=bool)
   for i, y in enumerate(range(10, 1190, 20)):
      if i % 2:
         passable[y : y + 2, 20:] = False
      else:
         passable[y : y + 2, :-20] = False
   start = np.zeros_like(passable)
   start[0, 0] = True
   began = time.perf_counter()
   reach = flood(start, passable)
   assert reach[1199, 600] and time.perf_counter() - began < 5


def test_background_like_after_cutout():
   """불투명한 결 바탕(밝기 230 ± 10)은 지운 뒤에도 남은 칸이 네 변에 닿는다 — 배경 그림 신호 (실물 버그 2)."""
   rng = np.random.default_rng(2)
   arr = image.new(160, 120, (230, 230, 230, 255))
   arr[:, :, :3] = np.clip(230 + rng.integers(-10, 11, size=(120, 160, 1)), 0, 255)
   _, info = cutout(arr, "edge")
   assert info["sides_left"] >= 3 and looks_like_background(info)
   assert any(w["rule"] == "cutout.background_like" for w in image_warnings("bg", info))
   _, sprite = cutout(_subject(), "edge")
   assert sprite["sides_left"] == 0 and not looks_like_background(sprite)
