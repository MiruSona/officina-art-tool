"""6판 T2 — 덩어리 몸 `blob` 처리기와 `char_blob` 템플릿."""
import argparse
import copy

import numpy as np
import pytest

from arttool.template import TemplateError, run
from arttool.template.kinds import Ctx, handler, resolve_values
from arttool.template import schema


def _render(size, out):
   ns = argparse.Namespace(sub="render", name="char_blob", size=size, out_dir=str(out), preset=None, scale=None, over=None, profile=None)
   return run.run(ns)


def _tpl():
   return copy.deepcopy(schema.load("char_blob"))


def _calc(size=(64, 64), **over):
   tpl = _tpl()
   values = resolve_values({**tpl["values"], **over}, size)
   kind = handler("blob")
   return kind, Ctx(tpl, size, values), values, tpl


def _box_of(mask):
   ys, xs = np.nonzero(mask)
   return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]


def test_default_64_body_box_and_margins():
   kind, ctx, _, _ = _calc()
   calc = kind.compute(ctx)
   x0, top, x1, bottom = calc["body"]
   assert (x1 - x0, bottom - top) == (42, 35)
   assert (x0, 64 - x1, top, 64 - bottom) == (11, 11, 16, 13)
   sil = kind._silhouette(ctx, calc["body"])
   assert _box_of(sil) == calc["body"]           # 실루엣이 상자를 꽉 채운다(위 · 아래 줄도 비지 않음)


def test_widest_row_and_symmetry():
   kind, ctx, _, _ = _calc()
   calc = kind.compute(ctx)
   sil = kind._silhouette(ctx, calc["body"])
   widths = sil.sum(axis=1)
   top = calc["top_y"]
   widest = np.flatnonzero(widths == widths.max())
   # 가장 넓은 줄은 몸 높이의 0.63 지점(위에서 22번째 줄) 둘레
   assert abs(int(widest.mean()) - (top + 22)) <= 1 and widths.max() == 42
   assert (sil == sil[:, ::-1]).all()


def test_face_eyes_mouth_deco_positions():
   kind, ctx, _, _ = _calc()
   calc = kind.compute(ctx)
   fx0, fy0, fx1, fy1 = calc["face_box"]
   assert (fx1 - fx0, fy1 - fy0) == (16, 8)
   assert fy0 - calc["top_y"] == 13 and fx0 + fx1 == 64  # 가운데 정렬
   (l0, _, l1, _), (r0, _, r1, _) = calc["eye_boxes"]
   assert (r0 + r1) / 2 - (l0 + l1) / 2 == 15 and l0 + r1 == 64
   mx0, _, mx1 = calc["mouth"]
   assert mx1 - mx0 == 20
   dx0, dy0, dx1, dy1 = calc["deco_box"]
   assert (dx1 - dx0, dy1 - dy0) == (14, 14)
   assert calc["top_y"] - dy0 == 4 and (dx0 + dx1) / 2 - 32 == 3


def test_frames_keep_baseline_and_area():
   kind, ctx, _, _ = _calc()
   calc = kind.compute(ctx)
   sizes = [(b[2] - b[0], b[3] - b[1]) for b in calc["frame_bodies"]]
   assert sizes == [(42, 35), (47, 29), (38, 40), (40, 37)]
   assert {b[3] for b in calc["frame_bodies"]} == {calc["baseline_y"] + 1}
   frames = kind.frames(ctx, calc)
   assert len(frames) == 4
   areas = [int((f[:, :, 3] > 0)[: calc["baseline_y"]].sum()) for f in frames]
   assert max(areas) / min(areas) < 1.2
   for f in frames:
      assert (f[calc["baseline_y"] + 1:, :, 3] == 0).all()     # 바닥 줄 아래로 안 내려간다


def test_masks_split_body_and_face():
   kind, ctx, _, _ = _calc()
   calc = kind.compute(ctx)
   m = kind.masks(ctx, calc)
   assert set(m) == {"body", "face", "deco"}
   assert not (m["body"] & m["face"]).any() and int(m["face"].sum()) == 16 * 8


@pytest.mark.parametrize("key,bad", [
   ("body_w_ratio", 0), ("body_w_ratio", 1.5), ("body_h_ratio", -0.2), ("face_w_ratio", True),
   ("foot_ratio", 1), ("eye", 0), ("eye", 2.5), ("eye", 10 ** 9), ("frame_ms", -1),
   ("frames", []), ("frames", [[1, 1]] * 17), ("frames", [[3, 1]]), ("frames", [[1.5, 1.5]]),
   ("frames", [[1, "1"]]), ("deco_rise_ratio", 1), ("body_h_ratio", 1), ("face_y_ratio", 1),
])
def test_bad_values_rejected(key, bad):
   tpl = _tpl()
   tpl["values"][key] = bad
   with pytest.raises(TemplateError):
      handler("blob").validate_values(tpl, "시험")


@pytest.mark.parametrize("size", [None, "32x32", "96x96", "48x48"])
def test_renders_other_sizes(tmp_path, size):
   report = _render(size, tmp_path)
   assert report is not None
   assert (tmp_path / "char_blob_f03.png").exists() or any(tmp_path.rglob("char_blob_f03.png"))
