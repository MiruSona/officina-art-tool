"""7판-다-1 : 작은 겹(size · offset) 묶음에 split · layers diff 쓰기. 넘겨받은 것 : draw 캔버스가 마스크 겹을 안 섞는다."""

from __future__ import annotations

import json

import numpy as np
import pytest

from arttool import cli, errors, image, layerset
from arttool.errors import UsageError
from arttool.sprite import layers as layers_mod
from arttool.sprite import split

import test_layers_ops as ops
import test_split as sp


# --- split ---


def _small_split_set(folder, face_offset, face_size):
   rows = [{"name": n, "kind": "body" if n == "body" else ("face" if n == "face" else "deco")} for n in sp.LAYERS]
   rows[sp.LAYERS.index("face")].update(size=list(face_size), offset=list(face_offset))
   layerset.save(folder, layerset.from_dict({"version": 2, "canvas": [12, 16], "layers": rows, "items": ["old"],
                                             "meta": {"author": "a"}}))


def test_split_writes_small_layer_cropped(tmp_path):
   src, spec = sp.write_case(tmp_path, sp.doll(), sp.base_spec())
   out = tmp_path / "set"
   _small_split_set(out, (4, 5), (4, 1))          # 볼 두 점 (4,5) · (7,5) 를 감싸는 상자
   rep = split.run(src, spec, out)
   assert rep["roundtrip_diff"] == 0
   face = image.load(out / "face" / "doll.png")
   assert image.size(face) == (4, 1)
   assert face[0, 0, 3] == 255 and face[0, 3, 3] == 255
   assert image.size(image.load(out / "body" / "doll.png")) == (12, 16)   # 큰 겹은 그대로
   back = layerset.load(out)
   assert back.items == ["old", "doll"] and back.meta == {"author": "a"}
   assert back.layer("face").size == (4, 1) and back.layer("face").offset == (4, 5)
   stacked = layers_mod.compose(back.names(), layerset.read_item(out, back, "doll"))
   assert np.array_equal(stacked, sp.doll())


def test_split_refuses_cells_outside_small_box(tmp_path):
   src, spec = sp.write_case(tmp_path, sp.doll(), sp.base_spec())
   out = tmp_path / "set"
   _small_split_set(out, (5, 5), (3, 1))          # (4,5) 볼 점이 상자 밖
   with pytest.raises(UsageError, match="size · offset 을 늘린다"):
      split.run(src, spec, out)
   assert not (out / "body" / "doll.png").exists()   # 거절되면 한 장도 안 쓴다
   assert layerset.load(out).items == ["old"]


def test_split_small_set_with_other_layers_refused(tmp_path):
   """겹 목록이 다른 작은 겹 묶음은 어느 상자로 자를지 모르니 쓰기 전에 거절한다."""
   src, spec = sp.write_case(tmp_path, sp.doll(), sp.base_spec())
   out = tmp_path / "set"
   layerset.save(out, layerset.from_dict({"version": 2, "canvas": [12, 16], "items": ["old"], "layers": [
      {"name": "body", "kind": "body"}, {"name": "cheek", "kind": "face", "size": [2, 2], "offset": [0, 0]}]}))
   with pytest.raises(UsageError, match="작은 겹"):
      split.run(src, spec, out)
   assert not (out / "body").exists()


# --- layers diff ---


def _small_template(tmp_path, hair_size):
   guide = tmp_path / "guide"
   guide.mkdir()
   (guide / "template.json").write_text(json.dumps({"name": "t"}), encoding="utf-8")
   layerset.save(guide, layerset.from_dict({"version": 2, "canvas": [ops.W, ops.H], "items": [], "layers": [
      {"name": "body", "kind": "body"}, {"name": "hair", "kind": "hair", "size": list(hair_size), "offset": [2, 3]}]}))
   image.save(tmp_path / "idle.png", ops.base_body())
   (tmp_path / "inp").mkdir()
   image.save(tmp_path / "inp" / "hair.png", ops.hair_result(carve=0))
   return ["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(tmp_path / "inp"),
           "--out", str(tmp_path / "set"), "--template", str(guide / "template.json")]


def test_diff_writes_small_layer_cropped(tmp_path):
   argv = _small_template(tmp_path, (8, 3))       # 머리 [2,10) × [3,6)
   assert ops.run_cli(argv, tmp_path / "r.json") == errors.EXIT_OK
   assert image.size(image.load(tmp_path / "set" / "hair" / "idle.png")) == (8, 3)
   back = layerset.load(tmp_path / "set")
   assert back.layer("hair").size == (8, 3) and back.layer("hair").offset == (2, 3)
   assert np.array_equal(ops.stacked(tmp_path / "set"), ops.hair_result(carve=0))


def test_diff_refuses_cells_outside_small_box(tmp_path, capsys):
   argv = _small_template(tmp_path, (8, 2))       # 머리 셋째 줄(y=5)이 상자 밖
   assert ops.run_cli(argv) == errors.EXIT_USAGE
   assert "size · offset 을 늘린다" in capsys.readouterr().err
   assert not (tmp_path / "set" / "hair").exists() and not (tmp_path / "set" / "layers.json").exists()


# --- draw 캔버스 : 마스크 겹은 합친 그림에 안 들어간다 ---


def test_draw_canvas_merged_leaves_out_mask_layer(tmp_path):
   from arttool.draw.canvas import Canvas
   data = {"version": 2, "canvas": [4, 4], "items": ["idle"],
           "layers": [{"name": "body", "kind": "body"}, {"name": "hit", "kind": "mask"}]}
   canvas = Canvas(template=data)
   canvas["body"].arr[1, 1] = (10, 20, 30, 255)
   canvas["hit"].arr[2, 2] = (255, 255, 255, 255)
   merged = canvas.merged()
   assert merged[2, 2, 3] == 0 and tuple(merged[1, 1]) == (10, 20, 30, 255)
   canvas.outline("solid", color="#000000")         # 마스크 칸은 외곽선을 막지도 받지도 않는다
   assert canvas["body"].arr[1, 2, 3] == 255 and canvas["hit"].arr[..., 3].sum() == 255
   assert canvas["body"].arr[2, 1, 3] == 255
   canvas.save(tmp_path / "set")                   # 마스크 겹도 묶음에는 그대로 쓴다
   back = Canvas.open(tmp_path / "set")
   assert back["hit"].arr[2, 2, 3] == 255 and back.merged()[2, 2, 3] == 0
