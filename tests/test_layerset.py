import copy

import pytest

from arttool import image, layerset
from arttool.errors import ArtToolError

# 설계 10-2 의 예시 그대로
EXAMPLE = {
   "version": 1,
   "canvas": [32, 32],
   "layers": [
      {"name": "body", "kind": "body"},
      {"name": "cloth", "kind": "cloth"},
      {"name": "face", "kind": "face", "exclusive_with": ["hair"]},
      {"name": "hair", "kind": "hair"},
      {"name": "deco", "kind": "deco", "optional": True},
   ],
   "items": ["idle"],
   "template": "char_small",
}


def test_design_example_reads():
   ls = layerset.from_dict(EXAMPLE)
   assert ls.canvas == (32, 32)
   assert ls.names() == ["body", "cloth", "face", "hair", "deco"]
   assert ls.layer("deco").optional is True
   assert ls.layer("face").exclusive_with == ("hair",)
   assert ls.items == ["idle"] and ls.template == "char_small"


def test_round_trip(tmp_path):
   ls = layerset.from_dict(EXAMPLE)
   file = layerset.save(tmp_path / "set", ls)
   assert file.name == "layers.json"
   again = layerset.load(tmp_path / "set")
   assert again == ls
   assert layerset.load(file) == ls
   assert again.to_dict() == EXAMPLE


def test_skeleton_without_items_or_template():
   """template render 가 쓰는 뼈대 — 그림 없이 목록만."""
   data = {"version": 1, "canvas": [16, 16], "layers": [{"name": "fx", "kind": "fx"}]}
   ls = layerset.from_dict(data)
   assert ls.items == [] and ls.template is None
   assert ls.to_dict() == {**data, "items": []}


def test_exclusive_pairs_are_symmetric_and_ordered():
   data = copy.deepcopy(EXAMPLE)
   data["layers"][3]["exclusive_with"] = ["face"]  # 양쪽에 적어도 한 짝
   assert layerset.from_dict(data).exclusive_pairs() == [("face", "hair")]


def _broken(**change):
   data = copy.deepcopy(EXAMPLE)
   for key, value in change.items():
      data[key] = value
   return data


@pytest.mark.parametrize(
   "data, word",
   [
      (_broken(version=3), "version"),
      (_broken(canvas=[32]), "canvas"),
      (_broken(canvas=[0, 32]), "canvas"),
      (_broken(layers=[]), "하나 이상"),
      (_broken(extra=1), "모르는 칸"),
      (_broken(layers=[{"name": "body", "kind": "body", "z": 1}]), "모르는 칸"),
      (_broken(layers=[{"name": "body", "kind": "skin"}]), "kind"),
      (_broken(layers=[{"name": "../up", "kind": "body"}]), "이름"),
      (_broken(layers=[{"name": "body", "kind": "body"}, {"name": "Body", "kind": "cloth"}]), "겹친다"),
      (_broken(layers=[{"name": "face", "kind": "face", "exclusive_with": ["hat"]}]), "없는 겹"),
      (_broken(layers=[{"name": "face", "kind": "face", "exclusive_with": ["face"]}]), "자기 자신"),
      (_broken(layers=[{"name": "deco", "kind": "deco", "optional": "yes"}]), "optional"),
      (_broken(items=["idle", "IDLE"]), "겹친다"),
      (_broken(items=["a/b"]), "이름"),
      (_broken(template=3), "template"),
   ],
)
def test_bad_layerset_rejected(data, word):
   with pytest.raises(ArtToolError, match=word):
      layerset.from_dict(data)


def test_load_missing(tmp_path):
   with pytest.raises(ArtToolError, match="목록이 없다"):
      layerset.load(tmp_path)


def test_read_item_and_canvas_rule(tmp_path):
   ls = layerset.from_dict(EXAMPLE)
   layerset.save(tmp_path, ls)
   body = image.new(32, 32)
   body[5, 5] = (1, 2, 3, 255)
   image.save(layerset.image_path(tmp_path, "body", "idle"), body)
   image.save(layerset.image_path(tmp_path, "hair", "idle"), image.new(32, 32))

   parts = layerset.read_item(tmp_path, ls, "idle")
   assert list(parts) == ["body", "hair"]  # 없는 겹은 빠지고 순서는 쌓는 순서
   assert tuple(parts["body"][5, 5]) == (1, 2, 3, 255)

   image.save(layerset.image_path(tmp_path, "face", "idle"), image.new(16, 16))
   with pytest.raises(ArtToolError, match="canvas 와 다르다"):
      layerset.read_item(tmp_path, ls, "idle")


def test_image_path_rejects_escape(tmp_path):
   with pytest.raises(ArtToolError):
      layerset.image_path(tmp_path, "..", "idle")


def test_check_rig_order():
   ls = layerset.from_dict(EXAMPLE)
   layerset.check_rig_order(ls, ["body", "cloth", "face", "hair", "deco"])
   with pytest.raises(ArtToolError, match="layer_order"):
      layerset.check_rig_order(ls, ["body", "hair"])
