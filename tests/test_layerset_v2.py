"""4-가-1·2 : layers.json 버전 1/2 · 덧칸 meta · 작은 겹 size·offset."""
import json

import numpy as np

import pytest

from arttool import image, layerset
from arttool.errors import UsageError
from arttool.sprite import layerops

V1 = {
   "version": 1,
   "canvas": [16, 16],
   "layers": [{"name": "body", "kind": "body"}, {"name": "hat", "kind": "deco", "optional": True}],
   "items": ["idle"],
   "template": "char_small",
}


def _v2(**layer_extra):
   cheek = {"name": "cheek", "kind": "face", "size": [3, 2], "offset": [10, 12], **layer_extra}
   return {"version": 2, "canvas": [16, 16], "layers": [{"name": "body", "kind": "body"}, cheek], "items": ["idle"]}


# ---- 버전 1 은 바이트까지 그대로 ----

def test_v1_round_trip_is_byte_identical(tmp_path):
   src = tmp_path / "a"
   layerset.save(src, layerset.from_dict(V1))
   first = (src / "layers.json").read_bytes()
   layerset.save(tmp_path / "b", layerset.load(src))
   assert (tmp_path / "b" / "layers.json").read_bytes() == first
   data = json.loads(first)
   assert data["version"] == 1 and list(data) == ["version", "canvas", "layers", "items", "template"]
   assert data["layers"] == V1["layers"]


def test_v2_without_new_keys_is_written_as_v1(tmp_path):
   data = dict(V1, version=2)
   path = layerset.save(tmp_path, layerset.from_dict(data))
   assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1


@pytest.mark.parametrize("change", [
   {"meta": {"pivot": [1, 1]}},
   {"layers": [{"name": "body", "kind": "body", "meta": {}}]},
   {"layers": [{"name": "body", "kind": "body", "size": [2, 2], "offset": [0, 0]}]},
])
def test_v1_with_v2_keys_rejected(change):
   with pytest.raises(UsageError, match="version 2 로 올려라"):
      layerset.from_dict(dict(V1, **change))


@pytest.mark.parametrize("data", [dict(V1, version=3), dict(V1, version=True), dict(V1, version="2"), dict(V1, version=2, colour=1)])
def test_unknown_version_or_key_rejected(data):
   with pytest.raises(layerset.ArtToolError):
      layerset.from_dict(data)


# ---- meta ----

def test_meta_kept_on_round_trip(tmp_path):
   data = _v2(meta={"pivot": [1, 1], "note": "볼"})
   data["meta"] = {"author": "a"}
   path = layerset.save(tmp_path, layerset.from_dict(data))
   back = json.loads(path.read_text(encoding="utf-8"))
   assert back["version"] == 2 and back["meta"] == {"author": "a"}
   assert back["layers"][1]["meta"] == {"pivot": [1, 1], "note": "볼"}
   assert back["layers"][1]["size"] == [3, 2] and back["layers"][1]["offset"] == [10, 12]


def test_meta_only_makes_v2(tmp_path):
   path = layerset.save(tmp_path, layerset.from_dict(dict(V1, version=2, meta={"x": 1})))
   assert json.loads(path.read_text(encoding="utf-8"))["version"] == 2


def _deep(n):
   node = {}
   for _ in range(n):
      node = {"a": node}
   return node


@pytest.mark.parametrize("meta, word", [
   ([1, 2], "사전"),
   ({"big": "x" * (64 * 1024)}, "너무 크다"),
   (_deep(40), "너무 깊다"),
   ({"n": float("nan")}, "JSON"),
])
def test_bad_meta_rejected(meta, word):
   with pytest.raises(UsageError, match=word):
      layerset.from_dict(dict(V1, version=2, meta=meta))


# ---- size · offset 검사 ----

@pytest.mark.parametrize("box, word", [
   ({"size": [3, 2]}, "함께"),
   ({"offset": [0, 0], "size": None}, "size"),
   ({"size": [3, 2], "offset": [-1, 0]}, "offset"),
   ({"size": [0, 2], "offset": [0, 0]}, "size"),
   ({"size": [3, 2], "offset": [14, 0]}, "넘는다"),
   ({"size": [99999, 99999], "offset": [0, 0]}, "넘는다"),
   ({"size": ["3", 2], "offset": [0, 0]}, "size"),
   ({"size": [3, 2], "offset": [True, 0]}, "offset"),
   ({"size": [3, 2, 1], "offset": [0, 0]}, "size"),
])
def test_bad_box_rejected(box, word):
   data = _v2()
   data["layers"][1] = {"name": "cheek", "kind": "face", **box}
   with pytest.raises(UsageError, match=word):
      layerset.from_dict(data)


# ---- 읽을 때 펴기 ----

def _write_set(tmp_path, cheek_size=(3, 2)):
   ls = layerset.from_dict(_v2())
   layerset.save(tmp_path, ls)
   image.save(layerset.image_path(tmp_path, layerset.LayerSet((1, 1), [layerset.Layer("body", "body")]) if "body" == ".." else layerset.LayerSet((1, 1), [layerset.Layer("body", "body")]), "body", "idle"), image.new(16, 16, (1, 2, 3, 255)))
   image.save(layerset.image_path(tmp_path, layerset.LayerSet((1, 1), [layerset.Layer("body", "body")]) if "cheek" == ".." else layerset.LayerSet((1, 1), [layerset.Layer("cheek", "body")]), "cheek", "idle"), image.new(*cheek_size, (200, 0, 0, 255)))
   return layerset.load(tmp_path)


def test_read_item_expands_small_layer(tmp_path):
   ls = _write_set(tmp_path)
   parts = layerset.read_item(tmp_path, ls, "idle")
   cheek = parts["cheek"]
   assert image.size(cheek) == (16, 16)
   alpha = cheek[..., 3]
   assert alpha[12:14, 10:13].min() == 255
   assert int((alpha > 0).sum()) == 6


def test_read_item_rejects_wrong_small_size(tmp_path):
   ls = _write_set(tmp_path, cheek_size=(4, 2))
   with pytest.raises(UsageError, match="size 와 다르다"):
      layerset.read_item(tmp_path, ls, "idle")


def test_read_raw_expands_or_keeps_raw(tmp_path):
   ls = _write_set(tmp_path)
   assert image.size(layerops._read_raw(tmp_path, ls, "idle")["cheek"]) == (16, 16)
   ls = _write_set(tmp_path, cheek_size=(5, 5))
   assert image.size(layerops._read_raw(tmp_path, ls, "idle")["cheek"]) == (5, 5)   # check 가 크기 경고를 낸다


# ---- 쓸 때 자르기 · 못 쓰는 명령 막기 ----

def test_crop_to_box_and_outside_rejected():
   ls = layerset.from_dict(_v2())
   cheek = ls.layer("cheek")
   arr = image.new(16, 16)
   arr[12:14, 10:13] = (9, 9, 9, 255)
   cut = layerset.crop_to_box(cheek, arr, "(시험)")
   assert image.size(cut) == (3, 2) and cut[..., 3].min() == 255
   assert layerset.crop_to_box(ls.layer("body"), arr, "(시험)") is arr
   arr[0, 0] = (1, 1, 1, 255)
   with pytest.raises(UsageError, match="밖에 칸 1개"):
      layerset.crop_to_box(cheek, arr, "(시험)")


def test_refuse_small():
   layerset.refuse_small(layerset.from_dict(V1), "split")
   with pytest.raises(UsageError, match="cheek"):
      layerset.refuse_small(layerset.from_dict(_v2()), "split")


def test_draw_canvas_saves_small_layer_cropped_and_reopens(tmp_path):
   from arttool.draw.canvas import Canvas
   canvas = Canvas(template=_v2())
   canvas._layers["cheek"].arr[12:14, 10:13] = (200, 0, 0, 255)
   canvas.save(tmp_path / "set")
   assert image.size(image.load(tmp_path / "set" / "cheek" / "idle.png")) == (3, 2)
   back = Canvas.open(tmp_path / "set")
   assert np.array_equal(back._layers["cheek"].arr[..., 3], canvas._layers["cheek"].arr[..., 3])
   canvas._layers["cheek"].arr[0, 0] = (1, 1, 1, 255)
   with pytest.raises(UsageError, match="밖에 칸"):
      canvas.save(tmp_path / "set2")
   assert not (tmp_path / "set2" / "body").exists()   # 거절되면 한 장도 안 쓴다


def test_split_refuses_set_with_small_layers(tmp_path):
   from arttool.sprite import split
   split._refuse_small_set(tmp_path)                     # 묶음 없음 → 통과
   layerset.save(tmp_path, layerset.from_dict(V1))
   split._refuse_small_set(tmp_path)                     # 옛 묶음 → 통과
   layerset.save(tmp_path, layerset.from_dict(_v2()))
   with pytest.raises(UsageError, match="split"):
      split._refuse_small_set(tmp_path)


# ---- 다시 쓸 때 meta 를 잃지 않는다 (4-가 리뷰) ----

def test_canvas_open_save_keeps_top_meta(tmp_path):
   from arttool.draw.canvas import Canvas
   data = _v2(meta={"pivot": [1, 1]})
   data["meta"] = {"author": "a"}
   layerset.save(tmp_path / "set", layerset.from_dict(data))
   Canvas.open(tmp_path / "set").save(tmp_path / "set")
   back = layerset.load(tmp_path / "set")
   assert back.meta == {"author": "a"} and back.layer("cheek").meta == {"pivot": [1, 1]}
   Canvas.open(tmp_path / "set").save(tmp_path / "other")   # 새 폴더에 써도 들고 간다
   assert layerset.load(tmp_path / "other").meta == {"author": "a"}


def test_split_adding_item_keeps_top_meta(tmp_path):
   from types import SimpleNamespace
   from arttool.sprite import split
   data = dict(V1, version=2, meta={"author": "a"})
   layerset.save(tmp_path, layerset.from_dict(data))
   path, note = split._write_layerset(tmp_path, SimpleNamespace(layers=["body", "hat"], default=0), "walk0", (16, 16))
   assert note is None and path
   back = layerset.load(tmp_path)
   assert back.items == ["idle", "walk0"] and back.meta == {"author": "a"}


def test_template_rerender_keeps_meta(tmp_path):
   from test_template_fixes import args, render
   out = tmp_path / "o"
   render(args("char_small", "32", out))
   data = json.loads((out / "layers.json").read_text(encoding="utf-8"))
   data["version"] = 2
   data["meta"] = {"author": "a"}
   data["layers"][0]["meta"] = {"note": "몸"}
   (out / "layers.json").write_text(json.dumps(data), encoding="utf-8")
   render(args("char_small", "32", out))
   back = layerset.load(out)
   assert back.meta == {"author": "a"} and back.layers[0].meta == {"note": "몸"}


def test_carry_meta_prefers_new_meta():
   old = layerset.from_dict(dict(V1, version=2, meta={"old": 1}))
   fresh = layerset.from_dict(dict(V1, version=2, meta={"new": 1}))
   assert layerset.carry_meta(old, fresh).meta == {"new": 1}
   assert layerset.carry_meta(None, fresh) is fresh


# ---- version 은 정수만 · 아주 깊은 JSON ----

@pytest.mark.parametrize("version", [2.0, 1.0])
def test_float_version_rejected(version):
   with pytest.raises(layerset.ArtToolError, match="version"):
      layerset.from_dict(dict(V1, version=version))


def test_very_deep_layers_json_is_usage_error(tmp_path):
   depth = 100_000
   text = '{"version": 2, "canvas": [16, 16], "layers": [{"name": "body", "kind": "body"}], "meta": ' + '{"a":' * depth + "{}" + "}" * depth + "}"
   (tmp_path / "layers.json").write_text(text, encoding="utf-8")
   with pytest.raises(UsageError, match="너무 깊게"):
      layerset.load(tmp_path)


def test_very_deep_layers_json_canvas_open_is_usage_error(tmp_path):
   from arttool.draw.canvas import Canvas
   depth = 100_000
   text = '{"version": 2, "canvas": [16, 16], "layers": [{"name": "body", "kind": "body"}], "meta": ' + '{"a":' * depth + "{}" + "}" * depth + "}"
   (tmp_path / "layers.json").write_text(text, encoding="utf-8")
   with pytest.raises(UsageError, match="layers.json 이 너무 깊게"):
      Canvas.open(tmp_path)
