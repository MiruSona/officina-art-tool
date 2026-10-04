"""`ui preview` 와 9조각 늘리기 시험. 그림은 모두 코드로 만든 합성 그림이다."""

from __future__ import annotations

import pytest

from arttool import cli, errors, image
from arttool.ui.ninepatch import slice_stretch


def _panel():
   """10x8. 각 칸 색이 (x, y) 를 담아 어느 원본 칸에서 왔는지 알 수 있다."""
   arr = image.new(10, 8)
   for y in range(8):
      for x in range(10):
         arr[y, x] = (x * 20, y * 20, 100, 255)
   return arr


BORDER = [2, 3, 2, 1]  # 왼, 아래, 오른, 위


def test_corners_are_unchanged():
   src = _panel()
   out = slice_stretch(src, BORDER, 30, 20)
   assert (out[:1, :2] == src[:1, :2]).all()  # 왼쪽 위
   assert (out[:1, -2:] == src[:1, -2:]).all()  # 오른쪽 위
   assert (out[-3:, :2] == src[-3:, :2]).all()  # 왼쪽 아래
   assert (out[-3:, -2:] == src[-3:, -2:]).all()  # 오른쪽 아래


def test_edges_stretch_one_direction_only():
   src = _panel()
   out = slice_stretch(src, BORDER, 30, 20)
   # 위 변 : 세로는 원본 1줄 그대로, 가로만 늘었다 → 원본 y 값(G)이 0 이다.
   assert set(out[0, 2:-2, 1].tolist()) == {0}
   # 왼 변 : 가로는 원본 x 0~1 그대로 → R 이 0·20 뿐.
   assert set(out[1:-3, 0, 0].tolist()) == {0}
   assert set(out[1:-3, 1, 0].tolist()) == {20}
   # 가운데 가로 칸들은 원본 가운데 열(x 2~7)에서만 온다.
   assert set(out[5, 2:-2, 0].tolist()) <= {40, 60, 80, 100, 120, 140}


def test_same_size_is_identity_and_tile_mode():
   src = _panel()
   assert (slice_stretch(src, BORDER, 10, 8) == src).all()
   tiled = slice_stretch(src, BORDER, 16, 8, mode="tile")
   # 가운데 6칸이 되풀이된다 : 결과 x 2~7 과 8~13 이 같다.
   assert (tiled[:, 2:8] == tiled[:, 8:14]).all()


def test_too_small_is_error():
   with pytest.raises(errors.ArtToolError):
      slice_stretch(_panel(), BORDER, 4, 20)
   with pytest.raises(errors.ArtToolError):
      slice_stretch(_panel(), [5, 0, 5, 0], 20, 20)


def test_cli_side_by_side(tmp_path, capsys):
   src = tmp_path / "panel.png"
   image.save(src, _panel())
   out = tmp_path / "p.png"
   argv = ["ui", "preview", "--in", str(src), "--border", "2,3,2,1", "--size", "30x20,12x8", "--out", str(out), "--scale", "2"]
   assert cli.main(argv) == errors.EXIT_OK
   assert image.size(image.load(out)) == ((30 + 4 + 12) * 2, 20 * 2)


def test_cli_reads_ninepatch_guides(tmp_path, capsys):
   panel = _panel()
   framed = image.new(12, 10)
   framed[1:9, 1:11] = panel
   black = (0, 0, 0, 255)
   framed[0, 1 + 2 : 1 + 10 - 2] = black  # 위 : 가로로 늘어나는 구간 → 왼 2 · 오른 2
   framed[1 + 1 : 1 + 8 - 3, 0] = black  # 왼 : 세로로 늘어나는 구간 → 위 1 · 아래 3
   src = tmp_path / "panel.9.png"
   image.save(src, framed)
   out = tmp_path / "p.png"
   assert cli.main(["ui", "preview", "--in", str(src), "--size", "30x20", "--out", str(out)]) == errors.EXIT_OK
   assert (image.load(out) == slice_stretch(panel, BORDER, 30, 20)).all()


def test_cli_rejects(tmp_path, capsys):
   src = tmp_path / "panel.png"
   image.save(src, _panel())
   out = str(tmp_path / "p.png")
   base = ["ui", "preview", "--in", str(src), "--out", out]
   assert cli.main(base + ["--size", "30x20"]) == errors.EXIT_USAGE  # border 없음
   assert cli.main(base + ["--border", "2,3,2,1", "--size", "4x20"]) == errors.EXIT_USAGE  # 최소 크기
   assert cli.main(base + ["--border", "5", "--size", "30x20"]) == errors.EXIT_USAGE  # border 합이 원본 이상
   assert cli.main(base + ["--border", "1,2", "--size", "30x20"]) == errors.EXIT_USAGE
   assert cli.main(["ui", "preview", "--in", str(src), "--border", "2", "--size", "30x20", "--out", str(src)]) == errors.EXIT_USAGE
