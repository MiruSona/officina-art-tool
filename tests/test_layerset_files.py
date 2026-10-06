"""4판-나 소단계 1 — layers.json 의 files 무늬와 사전 꼴 items."""

import json

import numpy as np
import pytest

from arttool import image, layerset
from arttool.errors import UsageError


def _data(**extra):
   data = {"version": 2, "canvas": [4, 4],
           "layers": [{"name": "body", "kind": "body", "files": "parts/body_{v}.png"},
                      {"name": "face", "kind": "face", "files": "parts/face_{v}.png"}],
           "items": ["idle", {"name": "hop0_smile", "pick": {"body": "hop0", "face": "01"}}]}
   data.update(extra)
   return data


def _png(path, value):
   path.parent.mkdir(parents=True, exist_ok=True)
   arr = np.zeros((4, 4, 4), np.uint8)
   arr[0, 0] = (value, 0, 0, 255)
   image.save(path, arr)


def test_round_trip_keeps_files_and_pick():
   ls = layerset.from_dict(_data())
   assert ls.layer("body").files == "parts/body_{v}.png"
   assert ls.picks == {"hop0_smile": {"body": "hop0", "face": "01"}}
   assert ls.to_dict() == _data()


def test_old_set_bytes_unchanged(tmp_path):
   data = {"version": 1, "canvas": [4, 4], "layers": [{"name": "body", "kind": "body"}], "items": ["idle"]}
   (tmp_path / "a").mkdir()
   (tmp_path / "a" / "layers.json").write_text(json.dumps(data), encoding="utf-8")
   before = layerset.save(tmp_path / "b", layerset.from_dict(data)).read_bytes()
   ls = layerset.load(tmp_path / "b")
   assert layerset.save(tmp_path / "c", ls).read_bytes() == before
   assert ls.to_dict() == data
   assert layerset.image_path(tmp_path, ls, "body", "idle") == layerset.safe_join(layerset.resolve_root(tmp_path), "body/idle.png")


@pytest.mark.parametrize("bad", [
   "parts/body.png", "parts/{v}_{v}.png", "parts/{layer}_{v}.png", "../x/{v}.png", "/abs/{v}.png",
   "C:/x/{v}.png", "parts\\{v}.png", "a//{v}.png", "./{v}.png", "{v}/body.png", "parts/{v}.gif", "a/" * 200 + "{v}.png", 3,
   # 점으로 시작 · 끝나는 마디 (Windows 가 끝 점을 뗀다) · 예약 이름 마디
   "body./{v}.png", "head/{v}..png", "...{v}.png", "head/.{v}.png", "con/{v}.png", "parts/NUL.x/{v}.png", "Lpt1/{v}.png",
   "face/{v}.png",   # 첫 마디가 다른 겹 이름 (남의 기본 폴더)
])
def test_bad_files_pattern_refused(bad):
   data = _data()
   data["layers"][0]["files"] = bad
   with pytest.raises(UsageError):
      layerset.from_dict(data)


@pytest.mark.parametrize("item", [
   {"name": "x", "pick": {"hair": "a"}},           # 없는 겹
   {"name": "x", "pick": {"body": "../a"}},        # 변형 이름
   {"name": "x", "pick": {}},                      # 빈 pick
   {"name": "x"},                                  # pick 없음
   {"name": "x", "pick": {"body": "a"}, "z": 1},   # 모르는 칸
   {"name": "x", "pick": {"body": "a" * 65}},      # 변형 이름 64자 넘음
   {"name": "x", "pick": {"body": "CON"}},         # Windows 예약 이름
   {"name": "x", "pick": {"body": "com7"}},
])
def test_bad_pick_refused(item):
   with pytest.raises(UsageError):
      layerset.from_dict(_data(items=[item]))


def test_pick_name_64_ok_and_v1_reserved_item_kept():
   layerset.from_dict(_data(items=[{"name": "x", "pick": {"body": "a" * 64}}]))
   layerset.from_dict({"version": 1, "canvas": [4, 4], "layers": [{"name": "body", "kind": "body"}], "items": ["con"]})


@pytest.mark.parametrize("items", [
   ["x_y", {"name": "a", "pick": {"head": "y"}}],     # head 무늬 body/x_{v} 가 body 기본 body/x_y 와 같은 파일
   ["X_Y", {"name": "a", "pick": {"head": "y"}}],     # 대소문자만 달라도 같다
])
def test_different_patterns_same_file_refused(items):
   data = {"version": 2, "canvas": [4, 4], "items": items,
           "layers": [{"name": "body", "kind": "body"}, {"name": "head", "kind": "hair", "files": "body2/x_{v}.png"}]}
   layerset.from_dict(data)   # 다른 폴더면 통과
   data["layers"][1]["files"] = "Body/x_{v}.png"   # 첫 마디가 다른 겹 이름 -> 거절
   with pytest.raises(UsageError):
      layerset.from_dict(data)


def test_resolved_path_collision_refused():
   data = {"version": 2, "canvas": [4, 4], "items": ["x_y", {"name": "a", "pick": {"head": "y"}}],
           "layers": [{"name": "body", "kind": "body", "files": "p/{v}.png"}, {"name": "head", "kind": "hair", "files": "p/x_{v}.png"}]}
   with pytest.raises(UsageError, match="같은 파일"):
      layerset.from_dict(data)
   data["items"] = ["x_z", {"name": "a", "pick": {"head": "y"}}]
   layerset.from_dict(data)


@pytest.mark.parametrize("files, pick", [("p/co{v}.png", "n"), ("p/{v}x.png", "lpt1."), ("p/l{v}.png", "pt9")])
def test_filled_reserved_name_refused(files, pick):
   # 무늬 글자만 보면 멀쩡하지만 {v} 를 채우면 con.png · lpt9.png 같은 Windows 예약 이름이 되는 꼴
   data = {"version": 2, "canvas": [4, 4], "items": [{"name": "a", "pick": {"body": pick}}],
           "layers": [{"name": "body", "kind": "body", "files": files}]}
   with pytest.raises(UsageError):
      layerset.from_dict(data)
   data["items"] = [{"name": "a", "pick": {"body": "ok"}}]
   layerset.from_dict(data)


def _render(out):
   from arttool import cli
   return cli.main(["template", "render", "char_small", "--size", "32", "--out", str(out)])


def test_template_rerender_keeps_picks(tmp_path):
   """pick 만 쓴 묶음(files 없음)에 다시 render 하면 items · pick 을 그대로 잇는다."""
   assert _render(tmp_path) == 0
   data = json.loads((tmp_path / "layers.json").read_text(encoding="utf-8"))
   data["version"] = 2
   first = data["layers"][0]["name"]
   data["items"] = ["idle", {"name": "alt", "pick": {first: "v2"}}]
   (tmp_path / "layers.json").write_text(json.dumps(data), encoding="utf-8")
   assert _render(tmp_path) == 0
   ls = layerset.load(tmp_path)
   assert ls.items == ["idle", "alt"] and ls.picks == {"alt": {first: "v2"}}


@pytest.mark.parametrize("with_items", [True, False])
def test_template_rerender_refuses_files(tmp_path, with_items):
   """files 무늬를 쓰는 묶음에 다시 render 는 지원 안 한다 — 무늬를 조용히 잃지 않게 거절(종료 2)."""
   assert _render(tmp_path) == 0
   data = json.loads((tmp_path / "layers.json").read_text(encoding="utf-8"))
   data["version"] = 2
   data["layers"][0]["files"] = "parts/a_{v}.png"
   data["items"] = ["idle"] if with_items else []
   (tmp_path / "layers.json").write_text(json.dumps(data), encoding="utf-8")
   assert _render(tmp_path) == 2
   assert json.loads((tmp_path / "layers.json").read_text(encoding="utf-8")) == data


def test_v1_refuses_new_fields():
   with pytest.raises(UsageError, match="version 2"):
      layerset.from_dict(_data(version=1, layers=[{"name": "body", "kind": "body", "files": "p/{v}.png"}], items=[]))
   with pytest.raises(UsageError, match="version 2"):
      layerset.from_dict({"version": 1, "canvas": [4, 4], "layers": [{"name": "body", "kind": "body"}],
                          "items": [{"name": "x", "pick": {"body": "a"}}]})


def test_same_pattern_and_exclusive_pick_refused():
   data = _data()
   data["layers"][1]["files"] = "PARTS/body_{v}.png"
   with pytest.raises(UsageError, match="무늬가 같다"):
      layerset.from_dict(data)
   data = _data()
   data["layers"][1]["files"] = "body/{v}.png"   # 다른 겹의 기본 자리와 같다
   data["layers"][0].pop("files")
   with pytest.raises(UsageError, match="무늬가 같다"):
      layerset.from_dict(data)
   data = _data()
   data["layers"][0]["exclusive_with"] = ["face"]
   with pytest.raises(UsageError, match="exclusive_with"):
      layerset.from_dict(data)


def test_read_item_uses_pattern_and_pick(tmp_path):
   ls = layerset.from_dict(_data())
   _png(tmp_path / "parts" / "body_hop0.png", 10)
   _png(tmp_path / "parts" / "face_01.png", 20)
   _png(tmp_path / "parts" / "body_idle.png", 30)
   got = layerset.read_item(tmp_path, ls, "hop0_smile")
   assert {k: int(v[0, 0, 0]) for k, v in got.items()} == {"body": 10, "face": 20}
   assert list(layerset.read_item(tmp_path, ls, "idle")) == ["body"]   # 글자 꼴 : 변형 = 그림 이름


def test_pick_missing_file_and_collision_refused(tmp_path):
   ls = layerset.from_dict(_data())
   _png(tmp_path / "parts" / "body_hop0.png", 10)
   with pytest.raises(UsageError, match="변형 파일이 없다"):
      layerset.read_item(tmp_path, ls, "hop0_smile")
   data = _data(items=[{"name": "x", "pick": {"body": "face_a", "face": "a"}}])
   data["layers"][0]["files"] = "parts/body_{v}.png"
   data["layers"][1]["files"] = "parts/body_face_{v}.png"
   with pytest.raises(UsageError, match="같은 파일"):   # 읽을 때(파싱) 미리 거절
      layerset.from_dict(data)


def test_pick_without_layer_gives_none(tmp_path):
   ls = layerset.from_dict(_data(items=[{"name": "x", "pick": {"body": "a"}}]))
   assert layerset.image_path(tmp_path, ls, "face", "x") is None


def test_carry_meta_keeps_files_and_pick():
   old = layerset.from_dict(_data())
   fresh = layerset.LayerSet(old.canvas, [layerset.Layer("body", "body"), layerset.Layer("face", "face")],
                             ["idle", "hop0_smile", "new"])
   got = layerset.carry_meta(old, fresh)
   assert got.layer("face").files == "parts/face_{v}.png"
   assert got.picks == {"hop0_smile": {"body": "hop0", "face": "01"}}
   assert got.to_dict()["version"] == 2
