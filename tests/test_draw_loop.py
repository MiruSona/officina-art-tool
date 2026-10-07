"""draw 고리 G5 — symmetry · clip · last · dirty 시험. 그림은 모두 합성."""

import numpy as np
import pytest

from arttool import image
from arttool.draw import Canvas
from arttool.errors import ArtToolError

RED = "#C04040"
BLUE = "#4040C0"


def _filled(layer):
   return layer.mask()


def test_symmetry_mirrors_half():
   c = Canvas(8)
   body = c["body"].set_symmetry("x")
   body.dot(1, 2, RED)
   m = _filled(body)
   assert m[2, 1] and m[2, 6]
   assert int(m.sum()) == 2
   assert body.last == {"written": 2, "clipped": 0}


def test_symmetry_odd_width_center_column():
   c = Canvas((7, 5))
   body = c["body"].set_symmetry("x")
   body.dot(3, 1, RED)            # 가운데 줄
   assert int(_filled(body).sum()) == 1
   body.box(0, 3, 4, 4, BLUE)     # x 0~3 → 거울 3~6, 가운데 3 은 한 번
   assert int(_filled(body)[3].sum()) == 7
   assert body.last["written"] == 7


def test_symmetry_off_and_bad_axis():
   c = Canvas(8)
   body = c["body"].set_symmetry("x").set_symmetry(None)
   body.dot(1, 1, RED)
   assert int(_filled(body).sum()) == 1
   with pytest.raises(ArtToolError):
      body.set_symmetry("y")


def test_erase_follows_symmetry():
   c = Canvas(8)
   body = c["body"].box(0, 0, 8, 8, RED).set_symmetry("x")
   mask = np.zeros((8, 8), dtype=bool)
   mask[0, 0] = True
   body.erase(mask)
   assert not body.mask()[0, 0] and not body.mask()[0, 7]
   assert body.last == {"written": 2, "clipped": 0}


def test_clip_blocks_outside():
   c = Canvas(8)
   clip = np.zeros((8, 8), dtype=bool)
   clip[2:6, 2:6] = True
   body = c["body"].set_clip(clip)
   body.box(0, 0, 8, 8, RED)
   assert np.array_equal(body.mask(), clip)
   assert body.last == {"written": 16, "clipped": 48}


def test_symmetry_then_clip():
   c = Canvas(8)
   clip = np.zeros((8, 8), dtype=bool)
   clip[:, :4] = True             # 왼쪽 반만 허용 → 거울 칸은 잘린다
   body = c["body"].set_symmetry("x").set_clip(clip)
   body.dot(1, 1, RED)
   assert body.mask()[1, 1] and not body.mask()[1, 6]
   assert body.last == {"written": 1, "clipped": 1}


def test_erase_ignores_clip():
   c = Canvas(8)
   body = c["body"].box(0, 0, 8, 8, RED)
   clip = np.zeros((8, 8), dtype=bool)
   clip[0, 0] = True
   body.set_clip(clip)
   mask = np.zeros((8, 8), dtype=bool)
   mask[5, 5] = True
   body.erase(mask)
   assert not body.mask()[5, 5]
   assert body.last == {"written": 1, "clipped": 0}
   body.erase()
   assert not body.mask().any()
   assert body.last["written"] == 63


def test_clip_bad_input():
   c = Canvas(8)
   with pytest.raises(ArtToolError):
      c["body"].set_clip(np.zeros((4, 4), dtype=bool))
   with pytest.raises(ArtToolError):
      c["body"].set_clip(np.zeros((8, 8), dtype=np.uint8))
   c["body"].set_clip(np.ones((8, 8), dtype=bool)).set_clip(None)
   assert c["body"].clip is None


def test_same_color_written_zero():
   c = Canvas(8)
   body = c["body"].box(1, 1, 4, 4, RED)
   assert body.last["written"] == 9
   body.box(1, 1, 4, 4, RED)
   assert body.last == {"written": 0, "clipped": 0}
   body.box(1, 1, 5, 4, BLUE)     # 9 칸 색 바뀜 + 새 3 칸
   assert body.last["written"] == 12


def test_dirty_paint_erase_and_clear():
   c = Canvas(8)
   body = c["body"]
   assert not body.dirty.any()
   body.dot(2, 2, RED)
   assert body.dirty[2, 2] and int(body.dirty.sum()) == 1
   body.clear_dirty()
   body.dot(2, 2, RED)             # 같은 색 다시 — 안 바뀜
   assert not body.dirty.any()
   mask = np.zeros((8, 8), dtype=bool)
   mask[2, 2] = mask[4, 4] = True  # 4,4 는 빈 칸이라 안 바뀜
   body.erase(mask)
   assert body.dirty[2, 2] and int(body.dirty.sum()) == 1
   assert body.clear_dirty() is body and not body.dirty.any()


def test_dirty_mirror():
   c = Canvas(8)
   body = c["body"].dot(1, 1, RED).clear_dirty()
   body.mirror()
   assert body.dirty[1, 6] and int(body.dirty.sum()) == 1


def test_dirty_outline():
   c = Canvas(12, layers=["body", "hair"])
   c["body"].box(4, 4, 8, 8, RED).clear_dirty()
   c.outline("solid", color="#101010")
   d = c["body"].dirty
   assert d.any()
   assert np.array_equal(d, c["body"].mask() & ~np.pad(np.ones((4, 4), bool), 4))
   assert not c["hair"].dirty.any()


def test_canvas_set_many_layers():
   c = Canvas(8, layers=["body", "hair", ("eyes", "face")])
   clip = np.zeros((8, 8), dtype=bool)
   clip[:, :2] = True
   c.set_symmetry("x", layers=["body", "hair"]).set_clip(clip)
   assert c["body"].symmetry == "x" and c["hair"].symmetry == "x" and c["eyes"].symmetry is None
   assert all(c[n].clip is not None for n in c.names)
   c["eyes"].dot(1, 0, RED)
   c["eyes"].dot(5, 0, RED)
   assert int(c["eyes"].mask().sum()) == 1
   c.set_clip(None).set_symmetry(None)
   assert all(c[n].clip is None and c[n].symmetry is None for n in c.names)
   with pytest.raises(ArtToolError):
      c.set_symmetry("x", layers=["nope"])


def test_fill_is_clipped():
   c = Canvas(8)
   clip = np.zeros((8, 8), dtype=bool)
   clip[:4] = True
   body = c["body"].set_clip(clip)
   body.fill(0, 0, RED)
   assert int(body.mask().sum()) == 32
   assert body.last == {"written": 32, "clipped": 32}


# ---- G6 : mark · changed · preview_changed · diff_grid ----

MAGENTA = [255, 0, 255, 255]
BLUE_PX = [0x40, 0x40, 0xC0, 255]


def test_changed_before_mark_counts_from_start():
   c = Canvas(8, layers=["body", "hair"])
   assert c.changed() == {"count": 0, "bbox": None, "layers": {"body": 0, "hair": 0}}
   c["body"].box(1, 2, 4, 4, RED)
   c["hair"].dot(6, 6, BLUE)
   assert c.changed() == {"count": 7, "bbox": [1, 2, 7, 7], "layers": {"body": 6, "hair": 1}}


def test_mark_resets_and_chains():
   c = Canvas(8)
   c["body"].box(0, 0, 8, 8, RED)
   assert c.mark() is c
   assert c.changed()["count"] == 0
   c["body"].dot(3, 4, BLUE).dot(3, 4, BLUE)
   assert c.changed() == {"count": 1, "bbox": [3, 4, 4, 5], "layers": {"body": 1}}


def test_diff_grid_marks_only_changed():
   c = Canvas(8)
   c["body"].box(0, 0, 8, 8, RED)
   c.mark()
   c["body"].dot(2, 2, BLUE).dot(4, 3, BLUE)
   mask = np.zeros((8, 8), dtype=bool)
   mask[3, 3] = True
   c["body"].erase(mask)
   legend_block, rows = c.diff_grid().split("\n\n")
   blue = c.legend.assign((0x40, 0x40, 0xC0))
   assert legend_block == f"{blue} #4040C0"                         # 범례는 바뀐 색만 (RED 없음)
   assert rows.splitlines() == [f"{blue}··", f"·.{blue}"]


def test_diff_grid_without_change_rejected():
   c = Canvas(8)
   with pytest.raises(ArtToolError, match="바뀐 칸이 없다"):
      c.diff_grid()


def test_preview_changed_crop_scale_and_magenta(tmp_path):
   c = Canvas(12)
   c["body"].box(0, 0, 12, 12, RED)
   c.mark()
   c["body"].dot(5, 5, BLUE)
   arr = image.load(c.preview_changed(tmp_path / "p.png", scale=4, pad=2))
   assert arr.shape == (5 * 4, 5 * 4, 4)                            # 창 (3,3)~(8,8)
   cell = arr[8:12, 8:12]                                           # 바뀐 칸 (5,5) → 창 안 (2,2)
   assert cell[0, 0].tolist() == MAGENTA and cell[3, 2].tolist() == MAGENTA and cell[1, 0].tolist() == MAGENTA
   assert cell[1:3, 1:3].reshape(-1, 4).tolist() == [BLUE_PX] * 4   # 테 안은 그림 그대로
   assert arr[0, 0].tolist() == [0xC0, 0x40, 0x40, 255]              # 안 바뀐 칸엔 테 없음
   assert int((arr == MAGENTA).all(axis=2).sum()) == 12             # 4x4 칸의 테두리 12px


def test_preview_changed_edge_pad_and_errors(tmp_path):
   c = Canvas(8)
   with pytest.raises(ArtToolError, match="바뀐 칸이 없다"):
      c.preview_changed(tmp_path / "none.png")
   c["body"].dot(0, 0, RED)
   assert image.load(c.preview_changed(tmp_path / "e.png", scale=3, pad=2)).shape == (9, 9, 4)   # 캔버스 밖으로 안 넓힘
   with pytest.raises(ArtToolError):
      c.preview_changed(tmp_path / "x.png", scale=0)
   with pytest.raises(ArtToolError, match="3 이상"):            # 2 이하면 테가 칸을 다 덮는다
      c.preview_changed(tmp_path / "x.png", scale=2)
   with pytest.raises(ArtToolError):
      c.preview_changed(tmp_path / "x.png", pad=-1)


def test_diff_grid_over_64_points_to_preview_changed():
   c = Canvas((80, 8))
   c["body"].dot(0, 0, RED).dot(70, 0, RED)
   with pytest.raises(ArtToolError, match="preview_changed"):
      c.diff_grid()


def test_recolor_ignores_symmetry_and_clip():
   """리뷰 3 : old 색 칸만 바뀐다 — 거울 칸의 다른 색 · clip 밖 칸도 old 색이면 바꾼다."""
   c = Canvas(8)
   body = c["body"]
   body.dot(1, 1, RED).dot(6, 1, BLUE)                          # 대칭 끈 채로 좌우 다른 색
   body.set_symmetry("x")
   clip = np.zeros((8, 8), dtype=bool)
   body.set_clip(clip)                                          # 아무 데도 못 찍는 clip
   c.mark()
   body.recolor(RED, "#00FF00")
   assert body.px(1, 1) == "#00FF00" and body.px(6, 1) == BLUE
   assert body.last == {"written": 1, "clipped": 0} and int(body.dirty.sum()) == 1


def test_preview_changed_refuses_inside_set_folder(tmp_path):
   c = Canvas(8)
   c["body"].dot(1, 1, RED)
   c.save(tmp_path / "set")
   reopened = Canvas.open(tmp_path / "set")
   assert reopened.changed()["count"] == 0                         # 연 그림이 기준
   reopened["body"].dot(2, 2, BLUE)
   for canvas in (c, reopened):
      with pytest.raises(ArtToolError):
         canvas.preview_changed(tmp_path / "set" / "p.png")
   blue = reopened.legend.assign((0x40, 0x40, 0xC0))
   assert reopened.diff_grid().endswith(f"\n\n{blue}\n")            # 기준이 연 그림이라 새 점 하나만
