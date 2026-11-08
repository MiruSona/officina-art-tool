"""도형 렌더러 (2026-11-08 도형 렌더러 설계) — 거리 함수 · 명세 읽기 · 렌더 · 도장 · 닮음 점수 · CLI."""

import json

import numpy as np
import pytest

from arttool import cli, image
from arttool.errors import ArtToolError
from arttool.shape import parse, render, similarity
from arttool.shape.render import cap_colors
from arttool.shape.sdf import Prim, lathe_polygon, polygon_distance, rotation

WHITE = "#FFFFFF"


def _spec(**extra):
   """32×32, 공 하나(반지름 10, 가운데). 흰 램프 2단."""
   data = {
      "version": 1,
      "canvas": {"size": [32, 32], "origin": [16, 16]},
      "materials": {"m": {"ramp": ["#404040", "#808080", "#C0C0C0", WHITE], "ambient": 0.0}},
      "shapes": [{"type": "sphere", "r": 10, "material": "m"}],
   }
   data.update(extra)
   return data


# --- 거리 함수 ---


def test_sphere_distance_sign():
   prim = Prim("sphere", {"r": 5.0}, "m")
   d = prim.distance(np.array([[0.0, 0, 0], [5.0, 0, 0], [8.0, 0, 0]]))
   assert d == pytest.approx([-5.0, 0.0, 3.0])


def test_lathe_is_round_and_closed():
   poly = lathe_polygon([[0, 0], [10, 0], [10, 4], [0, 4]])
   q = np.array([[1.0, 2.0], [9.0, 2.0], [11.0, 2.0], [5.0, 5.0]])
   d = polygon_distance(q, poly)
   assert d[0] < 0 and d[1] < 0 and d[2] == pytest.approx(1.0) and d[3] == pytest.approx(1.0)
   # 회전체 : x 축 · z 축 어느 쪽으로 재도 같다
   prim = Prim("lathe", {"profile": [], "_poly": poly}, "m")
   assert prim.distance(np.array([[11.0, 2, 0]]))[0] == pytest.approx(prim.distance(np.array([[0.0, 2, 11]]))[0])


def test_rotation_turns_x_to_y_about_z():
   assert rotation([0, 0, 90]) @ np.array([1.0, 0, 0]) == pytest.approx([0.0, 1.0, 0.0])


# --- 명세 읽기 ---


@pytest.mark.parametrize("patch, word", [
   ({"shapes": [{"type": "torus", "r": 1, "material": "m"}]}, r"shapes\[0\]\.type"),
   ({"shapes": [{"type": "sphere", "r": 1, "material": "x"}]}, "없는 재질"),
   ({"canvas": {"size": [0, 32]}}, "canvas.size"),
   ({"stamps": [{"on": "m", "at": [0, 0], "grid": ["ab"], "legend": {"a": WHITE}}]}, "legend 에 없는 글자"),
])
def test_bad_spec_names_the_field(patch, word):
   with pytest.raises(ArtToolError, match=word):
      parse(_spec(**patch))


def test_group_moves_children():
   spec = parse(_spec(shapes=[{"type": "group", "material": "m", "pos": [3, 0, 0], "rot": [0, 0, 90],
                               "shapes": [{"type": "sphere", "r": 1, "pos": [2, 0, 0]}]}]))
   assert spec.prims[0].pos == pytest.approx([3.0, 2.0, 0.0])
   assert spec.prims[0].material == "m"


# --- 렌더 ---


def test_render_is_deterministic_and_round():
   spec = parse(_spec())
   a, rep = render(spec)
   b, _ = render(spec)
   assert np.array_equal(a, b)
   solid = a[:, :, 3] > 0
   assert solid.sum() == pytest.approx(np.pi * 100, rel=0.06)
   assert np.array_equal(solid, solid[:, ::-1])           # 좌우 대칭 실루엣
   assert rep["colors"] <= 4 and rep["ms"] > 0


def test_light_from_top_left_is_brighter_there():
   arr, _ = render(parse(_spec()))
   assert arr[9, 9, 0] > arr[22, 22, 0]


def test_rim_and_highlight():
   data = _spec()
   data["materials"]["m"].update({"ambient": 1.0, "rim": {"below": 0.4, "index": 0}, "highlight": {"color": "#FFFF00", "above": 0.97}})
   arr, _ = render(parse(data))
   assert tuple(arr[16, 6, :3]) == (0x40, 0x40, 0x40)     # 왼쪽 가장자리 = rim
   assert ((arr[:, :, 0] == 255) & (arr[:, :, 2] == 0)).any()   # 빛 쪽 반사점


def test_card_stamp_lands_on_exact_pixels_and_hides_on_back():
   data = _spec(stamps=[{"on": "m", "at": [-3, 2], "grid": ["##", "##"], "legend": {"#": "#FF0000"}}])
   spec = parse(data)
   front, rep = render(spec, "front")
   red = np.argwhere(np.all(front[:, :, :3] == (255, 0, 0), axis=2))
   assert sorted(map(tuple, red)) == [(13, 12), (13, 13), (14, 12), (14, 13)]   # (y, x)
   assert rep["stamped"] == 4
   back, rep_back = render(spec, "back")
   assert rep_back["stamped"] == 0 and not np.all(back[:, :, :3] == (255, 0, 0), axis=2).any()


def test_view_turns_shape_not_light():
   """옆에 붙은 작은 공은 front 에서 오른쪽, back 에서 왼쪽에 보인다."""
   data = _spec(shapes=[{"type": "sphere", "r": 6, "material": "m"}, {"type": "sphere", "r": 3, "pos": [9, 0, 0], "material": "m"}])
   spec = parse(data)
   cols = {}
   for view in ("front", "back"):
      arr, _ = render(spec, view)
      cols[view] = np.nonzero(arr[16, :, 3])[0]
   assert cols["front"].max() > 16 + 9 and cols["back"].min() < 16 - 9


def test_outline_solid_and_inner_line():
   data = _spec(outline={"mode": "solid", "color": "#112233", "inner_gap": 2},
                shapes=[{"type": "sphere", "r": 8, "material": "m"}, {"type": "sphere", "r": 3, "pos": [0, 0, 9], "material": "m"}])
   arr, rep = render(parse(data))
   assert tuple(arr[16, 16 - 9, :3]) == (0x11, 0x22, 0x33)   # 공 바깥 한 칸 = 외곽선
   assert rep["inner_line"] > 0                              # 앞 작은 공 테두리


def test_cap_colors_merges_rarest():
   arr = image.new(4, 1)
   arr[0, 0] = arr[0, 1] = (10, 10, 10, 255)
   arr[0, 2] = (12, 12, 12, 255)
   arr[0, 3] = (200, 0, 0, 255)
   assert cap_colors(arr, 2) == 1
   assert tuple(arr[0, 2, :3]) == (10, 10, 10)


def test_unknown_view_is_refused():
   with pytest.raises(ArtToolError, match="없는 보는 방향"):
      render(parse(_spec()), "top")


# --- 닮음 점수 (draw 고리 실측 2-2 의 자가 시험 넷) ---


def _ref():
   arr = image.new(16, 16)
   arr[4:12, 4:12] = (120, 60, 30, 255)
   arr[6:8, 6:10] = (20, 20, 200, 255)
   return arr


def test_score_selftests():
   ref = _ref()
   assert similarity(ref, ref)["near_shifted"] == 1.0 and similarity(ref, ref)["exact"] == 1.0
   moved = np.zeros_like(ref)
   moved[:, 1:] = ref[:, :-1]
   got = similarity(moved, ref)
   assert got["near"] < 1.0 and got["near_shifted"] == 1.0 and got["shift"] == [-1, 0]
   assert similarity(image.new(16, 16), ref)["near_shifted"] == 0.0
   bright = ref.copy()
   bright[:, :, :3] = np.minimum(255, bright[:, :, :3].astype(int) + 10)
   got = similarity(bright, ref)
   assert got["exact"] == 0.0 and got["near"] == 1.0


# --- CLI ---


def test_cli_render_writes_png_and_score(tmp_path):
   spec_file = tmp_path / "s.shape.json"
   spec_file.write_text(json.dumps(_spec()), encoding="utf-8")
   first = tmp_path / "a.png"
   assert cli.main(["shape", "render", str(spec_file), "--out", str(first)]) == 0
   out = tmp_path / "b.png"
   report = tmp_path / "r.json"
   code = cli.main(["shape", "render", str(spec_file), "--out", str(out), "--view", "back", "--ref", str(first), "--report", str(report)])
   assert code == 0
   data = json.loads(report.read_text(encoding="utf-8"))
   assert data["view"] == "back" and data["score"]["silhouette_iou"] == 1.0
   assert image.load(out).shape == (32, 32, 4)


def test_cli_refuses_non_png_and_overwriting_spec(tmp_path):
   spec_file = tmp_path / "s.json"
   spec_file.write_text(json.dumps(_spec()), encoding="utf-8")
   assert cli.main(["shape", "render", str(spec_file), "--out", str(tmp_path / "o.gif")]) == 2
   assert cli.main(["--dry-run", "shape", "render", str(spec_file), "--out", str(tmp_path / "o.png")]) == 2
