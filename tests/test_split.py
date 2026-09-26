"""split — 그림은 전부 코드로 만든다. 설계 5-1 표의 split 줄을 하나씩 박는다."""

from __future__ import annotations

import json

import numpy as np
import pytest

import helpers
from arttool import cli, image, pieces
from arttool.errors import ArtToolError, PathJailError
from arttool.sprite import layers, split

OUT = (3, 2, 2)
SKIN = (254, 234, 205)
HAIR = (51, 46, 43)
SHIRT = (205, 58, 49)
FACE = (254, 157, 162)
ODD = (1, 200, 1)

LAYERS = ["body", "hair", "shirt", "face"]


def _px(arr, x, y, rgb):
   arr[y, x] = (*rgb, 255)


def _fill(arr, x0, y0, x1, y1, rgb):
   """끝을 뺀 네모 [x0, x1) × [y0, y1) 를 칠한다."""
   arr[y0:y1, x0:x1] = (*rgb, 255)


def doll():
   """네 색 인형 12×16. 머리카락 · 얼굴 살 · 볼 두 점 · 윗옷 · 다리."""
   arr = image.new(12, 16)
   _fill(arr, 3, 1, 9, 4, HAIR)
   _fill(arr, 3, 4, 9, 7, SKIN)
   _px(arr, 4, 5, FACE)
   _px(arr, 7, 5, FACE)
   _fill(arr, 2, 7, 10, 12, SHIRT)
   _fill(arr, 4, 12, 8, 15, SKIN)
   return arr


def base_spec(**extra):
   data = {
      "version": 1,
      "layers": list(LAYERS),
      "default": "body",
      "outline": "#030202",
      "colors": {"#FEEACD": "body", "#332E2B": "hair", "#CD3A31": "shirt", "#FE9DA2": "face"},
      "layer_opts": {"face": {"min_piece": 0}},
   }
   data.update(extra)
   return data


def spec_of(data, tmp_path=None):
   return split.load_spec(data, tmp_path or ".")


def owner_of(parts, x, y):
   hits = [name for name, layer in parts.items() if layer[y, x, 3] > 0]
   assert len(hits) == 1, hits
   return hits[0]


def write_case(tmp_path, arr, data, name="doll.png"):
   image.save(tmp_path / name, arr)
   (tmp_path / "split.json").write_text(json.dumps(data), encoding="utf-8")
   return tmp_path / name, tmp_path / "split.json"


# --- 가르기 ---


def test_four_layers_roundtrip_zero():
   parts, info = split.split_array(doll(), spec_of(base_spec()))
   assert info["roundtrip_diff"] == 0
   assert set(parts) == set(LAYERS)
   assert int(np.count_nonzero(parts["hair"][:, :, 3])) == 18
   assert int(np.count_nonzero(parts["face"][:, :, 3])) == 2
   assert int(np.count_nonzero(parts["shirt"][:, :, 3])) == 40
   assert int(np.count_nonzero(parts["body"][:, :, 3])) == 16 + 12
   for layer in parts.values():
      assert image.size(layer) == (12, 16)


def test_unmapped_color_goes_default_and_reported(tmp_path):
   arr = doll()
   _px(arr, 5, 13, ODD)
   src, spec_file = write_case(tmp_path, arr, base_spec())
   report = split.run(src, spec_file, tmp_path / "out")
   assert report["unmapped_colors"] == ["#01C801"]
   assert report["status"] == "warn"
   body = image.load(tmp_path / "out" / "body" / "doll.png")
   assert tuple(body[13, 5]) == (*ODD, 255)


def test_below_y_splits_same_color():
   arr = doll()
   _fill(arr, 4, 15, 8, 16, HAIR)  # 신발 = 머리카락과 같은 색
   rules = [{"color": "#332E2B", "below_y": 12, "to": "body"}]
   parts, info = split.split_array(arr, spec_of(base_spec(rules=rules)))
   assert owner_of(parts, 5, 15) == "body"
   assert owner_of(parts, 5, 2) == "hair"
   assert info["roundtrip_diff"] == 0


def test_box_puts_outline_eyes_on_face():
   arr = doll()
   _px(arr, 5, 5, OUT)
   _px(arr, 6, 5, OUT)
   rules = [{"color": "#030202", "box": [4, 4, 8, 7], "to": "face"}]
   parts, info = split.split_array(arr, spec_of(base_spec(rules=rules)))
   assert owner_of(parts, 5, 5) == "face"
   assert owner_of(parts, 6, 5) == "face"
   assert info["roundtrip_diff"] == 0


def test_outline_vote_joins_nearest_layer():
   arr = image.new(14, 3)
   _fill(arr, 0, 0, 3, 3, HAIR)
   _px(arr, 3, 1, OUT)       # 머리카락과 붙음, 살은 두 칸 떨어짐
   _fill(arr, 5, 0, 7, 3, SKIN)
   _px(arr, 13, 1, OUT)      # 반경 6 안에 아무도 없음
   parts, info = split.split_array(arr, spec_of(base_spec(layer_opts={"face": {"min_piece": 0}, "body": {"min_piece": 0}})))
   assert owner_of(parts, 3, 1) == "hair"
   assert owner_of(parts, 13, 1) == "body"   # 끝까지 못 정하면 default
   assert info["roundtrip_diff"] == 0


def test_vote_weights_closer_more():
   owner = np.full((1, 5), pieces.NONE, dtype=np.int32)
   owner[0, 0] = 1   # 거리 2
   owner[0, 3] = 2   # 거리 1
   assert pieces.vote(owner, [(2, 0)], radii=(2,)) == 2


def _forehead():
   arr = image.new(12, 8)
   _fill(arr, 3, 2, 9, 3, HAIR)
   _fill(arr, 3, 3, 9, 4, OUT)       # 이마 먹색 줄
   _fill(arr, 1, 3, 3, 4, SKIN)
   _fill(arr, 1, 4, 11, 7, SKIN)
   return arr


def test_near_rule_moves_forehead_outline_to_hair():
   plain, _ = split.split_array(_forehead(), spec_of(base_spec()))
   assert owner_of(plain, 3, 3) == "body"   # 투표만 하면 살 쪽이 이긴다

   rules = [{"color": "#030202", "above_y": 4, "near": "hair", "to": "hair"}]
   parts, info = split.split_array(_forehead(), spec_of(base_spec(rules=rules)))
   for x in range(3, 9):
      assert owner_of(parts, x, 3) == "hair"
   assert info["roundtrip_diff"] == 0


def test_mask_beats_color_table(tmp_path):
   arr = doll()
   mask = image.new(12, 16)
   mask[4, 3] = (255, 255, 255, 255)   # 머리카락 바로 아래 살색 한 칸을 머리카락으로
   image.save(tmp_path / "masks" / "hair.png", mask)
   spec = split.load_spec(base_spec(masks={"hair": "masks/hair.png"}), tmp_path)
   masks = {idx: image.load(p)[:, :, 3] > 0 for idx, p in spec.masks.items()}
   parts, info = split.split_array(arr, spec, masks)
   assert owner_of(parts, 3, 4) == "hair"
   assert info["roundtrip_diff"] == 0


def test_mask_path_cannot_leave_spec_folder(tmp_path):
   with pytest.raises(PathJailError):
      split.load_spec(base_spec(masks={"hair": "../hair.png"}), tmp_path)


# --- 떨어진 조각 ---


def test_three_point_piece_moves_to_neighbor(tmp_path):
   arr = doll()
   for x in (9, 10, 11):
      _px(arr, x, 12, HAIR)   # 윗옷 바로 아래 머리카락 색 세 점
   src, spec_file = write_case(tmp_path, arr, base_spec())
   report = split.run(src, spec_file, tmp_path / "out")
   hair = report["layers"]["hair"]
   assert hair["pieces_moved"] == [[9, 12], [10, 12], [11, 12]]
   assert hair["pieces_moved_to"] == {"shirt": 3}
   assert report["roundtrip_diff"] == 0
   shirt = image.load(tmp_path / "out" / "shirt" / "doll.png")
   assert tuple(shirt[12, 10]) == (*HAIR, 255)


def test_face_min_piece_zero_keeps_eyes():
   parts, _ = split.split_array(doll(), spec_of(base_spec()))
   assert owner_of(parts, 4, 5) == "face"
   assert owner_of(parts, 7, 5) == "face"

   loose = base_spec(layer_opts={})   # 표정도 기본 8 이면 한쪽 볼이 옮겨 간다
   parts, info = split.split_array(doll(), spec_of(loose))
   assert owner_of(parts, 7, 5) == "body"
   assert info["roundtrip_diff"] == 0


def test_floating_piece_warns(tmp_path):
   arr = image.new(30, 16)
   arr[:, :12] = doll()
   _px(arr, 27, 14, HAIR)
   _px(arr, 28, 14, HAIR)
   src, spec_file = write_case(tmp_path, arr, base_spec())
   report = split.run(src, spec_file, tmp_path / "out")
   assert report["status"] == "warn"
   assert report["layers"]["hair"]["pieces_floating"] == [[27, 14], [28, 14]]
   assert report["roundtrip_diff"] == 0


# --- 앵커 ---


def test_anchors_eight_fields_int_z_by_ten(tmp_path):
   data = base_spec(layer_opts={"face": {"min_piece": 0, "anchor": "bbox_center"}, "hair": {"anchor": "bbox_top_center"}})
   src, spec_file = write_case(tmp_path, doll(), data)
   split.run(src, spec_file, tmp_path / "out")
   points = json.loads((tmp_path / "out" / "anchors.json").read_text(encoding="utf-8"))["points"]
   assert [p["point"] for p in points] == LAYERS
   assert [p["z"] for p in points] == [0, 10, 20, 30]
   for p in points:
      assert set(p) == {"rig", "anim", "direction", "frame", "point", "x", "y", "z"}
      assert all(isinstance(p[k], int) for k in ("frame", "x", "y", "z"))
      assert (p["rig"], p["anim"], p["direction"], p["frame"]) == ("doll", "split", "south", 0)
   by = {p["point"]: (p["x"], p["y"]) for p in points}
   assert by["hair"] == (6, 1)      # bbox [3,1,9,4) 위 가운데, 5.5 → 6
   assert by["face"] == (6, 5)      # bbox [4,5,8,6) 가운데
   assert by["body"] == (6, 14)     # 기본 아래 가운데


# --- 거절 ---


def test_rig_layer_order_mismatch_rejected(tmp_path):
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   prof = helpers.tiny_profile(tmp_path)
   order = layers.layer_order(prof, "humanoid_lpc")
   with pytest.raises(ArtToolError, match="layer_order"):
      split.run(src, spec_file, tmp_path / "out", order, "humanoid_lpc")


def test_soft_alpha_rejected():
   arr = doll()
   arr[0, 0] = (1, 2, 3, 128)
   with pytest.raises(ArtToolError, match="반투명"):
      split.split_array(arr, spec_of(base_spec()))


def test_bad_hex_rejected():
   data = base_spec()
   data["colors"]["#12345"] = "body"
   with pytest.raises(ArtToolError, match="#RRGGBB"):
      spec_of(data)


def test_unknown_layer_name_rejected():
   data = base_spec()
   data["colors"]["#FFFFFF"] = "hat"
   with pytest.raises(ArtToolError, match="없는 겹 이름"):
      spec_of(data)


def test_layer_name_with_path_rejected():
   with pytest.raises(ArtToolError):
      spec_of(base_spec(layers=["body", "../hair"]))


def test_rule_without_condition_rejected():
   with pytest.raises(ArtToolError, match="조건이 없다"):
      spec_of(base_spec(rules=[{"color": "#332E2B", "to": "body"}]))


# --- 되돌림 ---


def test_output_restacks_with_layers_command(tmp_path):
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   prof = helpers.tiny_profile(tmp_path, **{"rigs.doll": {"method": "layer", "layer_order": list(LAYERS)}})
   report = split.run(src, spec_file, tmp_path / "out", layers.layer_order(prof, "doll"), "doll", prof.name)
   assert report["status"] == "ok"

   layers.compose_sheets(prof, "doll", tmp_path / "out", tmp_path / "merged", ["doll"])
   merged = image.load(tmp_path / "merged" / "doll.png")
   assert np.array_equal(merged, image.load(src))


def test_list_colors(tmp_path):
   image.save(tmp_path / "doll.png", doll())
   out = split.run_list_colors(tmp_path / "doll.png", tmp_path / "colors.json")
   assert out["colors"] == 4
   rows = json.loads((tmp_path / "colors.json").read_text(encoding="utf-8"))["colors"]
   assert rows[0] == {"hex": "#CD3A31", "count": 40, "bbox": [2, 7, 10, 12], "y_range": [7, 12]}


# --- CLI ---


def test_cli_split(tmp_path, capsys):
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   code = cli.main(["split", "--in", str(src), "--spec", str(spec_file), "--out", str(tmp_path / "out"), "--json"])
   assert code == 0
   assert json.loads(capsys.readouterr().out)["roundtrip_diff"] == 0
   assert (tmp_path / "out" / "split_report.json").is_file()


def test_cli_list_colors_rejects_spec(tmp_path, capsys):
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   code = cli.main(["split", "--in", str(src), "--list-colors", "--spec", str(spec_file), "--out", str(tmp_path / "c.json")])
   assert code == 2


# --- 리뷰 뒤 더한 시험 ---


def _rule_spec(rules, **extra):
   data = base_spec(rules=rules, layer_opts={name: {"min_piece": 0} for name in LAYERS})
   data.update(extra)
   return spec_of(data)


def test_box_end_edges_and_wide_rect():
   """가로 4 · 세로 2 네모 [2, 1, 6, 3). 끝 줄 바로 안은 들고 끝 줄은 안 든다. x·y 가 뒤바뀌면 틀린다."""
   arr = image.new(8, 5)
   arr[:, :] = (*SKIN, 255)
   for x, y in ((2, 1), (5, 2), (6, 1), (2, 3), (1, 2)):
      _px(arr, x, y, ODD)
   parts, _ = split.split_array(arr, _rule_spec([{"color": "#01C801", "box": [2, 1, 6, 3], "to": "face"}]))
   assert owner_of(parts, 2, 1) == "face"    # 왼쪽 위 모서리
   assert owner_of(parts, 5, 2) == "face"    # 끝 바로 안 (x1-1, y1-1)
   assert owner_of(parts, 6, 1) == "body"    # x = x1 은 밖
   assert owner_of(parts, 2, 3) == "body"    # y = y1 은 밖
   assert owner_of(parts, 1, 2) == "body"    # x0 앞


def test_above_below_y_edges():
   arr = image.new(3, 6)
   arr[:, 1] = (*HAIR, 255)
   rules = [{"color": "#332E2B", "above_y": 2, "to": "face"}, {"color": "#332E2B", "below_y": 4, "to": "body"}]
   parts, _ = split.split_array(arr, _rule_spec(rules))
   assert owner_of(parts, 1, 1) == "face"    # y < 2
   assert owner_of(parts, 1, 2) == "hair"    # y = 2 은 above_y 밖
   assert owner_of(parts, 1, 3) == "hair"
   assert owner_of(parts, 1, 4) == "body"    # y = 4 는 below_y 안


def test_vote_tie_first_seen_wins():
   """표가 같으면 먼저 표를 준 쪽 — 위 줄부터, 왼쪽부터 훑는다 (손 스크립트와 같다)."""
   left_hair = image.new(3, 1)
   _px(left_hair, 0, 0, HAIR)
   _px(left_hair, 1, 0, OUT)
   _px(left_hair, 2, 0, SKIN)
   parts, _ = split.split_array(left_hair, _rule_spec([]))
   assert owner_of(parts, 1, 0) == "hair"

   left_skin = left_hair[:, ::-1].copy()
   parts, _ = split.split_array(left_skin, _rule_spec([]))
   assert owner_of(parts, 1, 0) == "body"


def test_vote_radius_feeds_next_radius():
   """반경 1 에서 정해진 외곽선이 반경 2 투표에 낀다.

   [머리, 빈칸, 먹, 먹, 살] 에서 왼쪽 먹은 반경 2 에서 머리(1/3) 와 살(1/3) 이 동점이라
   투표 전 주인만 보면 먼저 본 머리가 이긴다. 반경 1 에서 살로 정해진 오른쪽 먹(1/2)이 끼면 살이 이긴다.
   """
   arr = image.new(5, 1)
   _px(arr, 0, 0, HAIR)
   _px(arr, 2, 0, OUT)
   _px(arr, 3, 0, OUT)
   _px(arr, 4, 0, SKIN)
   parts, _ = split.split_array(arr, _rule_spec([]))
   assert owner_of(parts, 3, 0) == "body"
   assert owner_of(parts, 2, 0) == "body"


def test_from_rule_without_near():
   """이마 규칙 : 몸으로 간 먹색 + y < N → 머리. 머리카락에 안 닿아 있어도 된다."""
   arr = image.new(10, 6)
   _fill(arr, 0, 0, 3, 1, HAIR)
   _fill(arr, 0, 2, 10, 6, SKIN)
   _px(arr, 8, 3, OUT)                       # 살 한가운데, 머리카락과 멀다
   _px(arr, 8, 5, OUT)                       # y 조건 밖
   rules = [{"color": "#030202", "above_y": 4, "from": "body", "to": "hair"}]
   parts, _ = split.split_array(arr, _rule_spec(rules))
   assert owner_of(parts, 8, 3) == "hair"
   assert owner_of(parts, 8, 5) == "body"

   near_only = [{"color": "#030202", "above_y": 4, "near": "hair", "to": "hair"}]
   parts, _ = split.split_array(arr, _rule_spec(near_only))
   assert owner_of(parts, 8, 3) == "body"   # near 는 닿아 있어야 한다


def test_from_rule_only_takes_that_layer():
   arr = image.new(3, 1)
   _px(arr, 0, 0, SHIRT)
   _px(arr, 1, 0, OUT)
   _px(arr, 2, 0, SHIRT)
   rules = [{"color": "#030202", "from": "body", "to": "hair"}]
   parts, _ = split.split_array(arr, _rule_spec(rules))
   assert owner_of(parts, 1, 0) == "shirt"  # 옷으로 갔던 먹색이라 안 옮긴다


def test_late_rule_does_not_override_mask_or_position_rule(tmp_path):
   arr = image.new(6, 3)
   _fill(arr, 0, 0, 6, 1, HAIR)
   _px(arr, 1, 1, OUT)
   _px(arr, 4, 1, OUT)
   mask = image.new(6, 3)
   mask[1, 1] = (255, 255, 255, 255)
   image.save(tmp_path / "m.png", mask)
   rules = [
      {"color": "#030202", "box": [4, 1, 5, 2], "to": "shirt"},
      {"color": "#030202", "near": "hair", "to": "hair"},
      {"color": "#030202", "from": "face", "to": "hair"},
   ]
   data = base_spec(rules=rules, masks={"face": "m.png"}, layer_opts={n: {"min_piece": 0} for n in LAYERS})
   spec = split.load_spec(data, tmp_path)
   masks = {idx: image.load(p)[:, :, 3] > 0 for idx, p in spec.masks.items()}
   parts, _ = split.split_array(arr, spec, masks)
   assert owner_of(parts, 1, 1) == "face"    # 마스크가 이긴다
   assert owner_of(parts, 4, 1) == "shirt"   # 자리 규칙이 이긴다


def test_layer_names_differing_by_case_rejected():
   with pytest.raises(ArtToolError, match="두 번"):
      spec_of(base_spec(layers=["body", "hair", "Hair", "face"], colors={}))


def test_restack_reads_saved_files(tmp_path, monkeypatch):
   """저장한 파일이 틀리면 되돌림 검사가 잡아야 한다 (메모리 속 겹만 보면 못 잡는다)."""
   src, spec_file = write_case(tmp_path, doll(), base_spec())
   real_save = image.save

   def lossy_save(path, arr):
      if "hair" in str(path):
         arr = image.new(*image.size(arr))
      real_save(path, arr)

   monkeypatch.setattr(image, "save", lossy_save)
   report = split.run(src, spec_file, tmp_path / "out")
   assert report["status"] == "fail"
   assert report["roundtrip_diff"] == 18


def test_layer_name_equal_to_report_rejected():
   with pytest.raises(ArtToolError, match="보고 파일"):
      spec_of(base_spec(layers=["body", "hair", "shirt", "face", "Anchors.json"]))


def test_hex_differing_by_case_rejected():
   data = base_spec()
   data["colors"]["#feeacd"] = "body"
   with pytest.raises(ArtToolError, match="같은 색이 두 번"):
      spec_of(data)


def test_outline_in_colors_rejected():
   data = base_spec()
   data["colors"]["#030202"] = "body"
   with pytest.raises(ArtToolError, match="outline"):
      spec_of(data)


def test_inverted_box_rejected():
   with pytest.raises(ArtToolError, match="x0 < x1"):
      spec_of(base_spec(rules=[{"color": "#030202", "box": [8, 1, 2, 5], "to": "face"}]))


def test_moved_piece_not_checked_again():
   """머리 → 옷으로 옮긴 조각이 옷 겹에서 또 떨어진 조각으로 잡혀 다시 옮겨지지 않는다."""
   arr = image.new(14, 6)
   _fill(arr, 0, 0, 5, 3, HAIR)             # 머리 본체
   _px(arr, 10, 1, HAIR)                     # 머리 조각 — 이웃은 옷 한 점뿐
   _px(arr, 11, 1, SHIRT)
   _fill(arr, 0, 4, 5, 6, SHIRT)             # 옷 본체
   data = base_spec(layer_opts={"hair": {"min_piece": 8}, "shirt": {"min_piece": 8}, "face": {"min_piece": 0}})
   parts, info = split.split_array(arr, spec_of(data))
   assert owner_of(parts, 10, 1) == "shirt"
   assert info["pieces"][2]["pieces_moved"] == []   # 옷 겹 차례에 (10,1) 을 또 옮기지 않았다
   assert info["roundtrip_diff"] == 0
