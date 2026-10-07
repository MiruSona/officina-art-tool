"""draw.lint — 좌표 박힌 린트 규칙마다 걸림 · 안 걸림 · waive · rules 고르기."""

import numpy as np
import pytest

from arttool import image
from arttool.draw.lint import LintResult, lint
from arttool.draw.outline import outline
from arttool.errors import ArtToolError
from arttool.palette import Ramps

FILL = (90, 120, 160, 255)
DOT = (240, 220, 120, 255)
DARK = (40, 50, 70)
LIGHT = (200, 210, 230)


def square(size=6, pad=1):
   arr = image.new(size + 2 * pad, size + 2 * pad)
   arr[pad : pad + size, pad : pad + size] = FILL
   return arr


def ramps():
   return Ramps("t", {"blue": [DARK, FILL[:3], LIGHT]}, None, 3)


def rules_of(res):
   return [i["rule"] for i in res.issues]


def test_clean_square_has_no_issues():
   res = lint(square(), ramps=ramps())
   assert res.issues == []
   assert res.status == "ok"
   assert res.lines() == []
   assert res.metrics == {"symmetry": 1.0, "center": [3.5, 3.5], "center_offset": [0.0, 0.0],
                          "bbox": [1, 1, 7, 7], "light_guess": "unknown"}


def test_orphan_inside_and_edge_found():
   arr = square()
   arr[3, 3] = DOT          # 안쪽 외톨이
   arr[1, 4] = DOT          # 가장자리 칸도 잡는다 (measure_isolated 와 달리)
   res = lint(arr, rules=["orphan"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(4, 1), (3, 3)]
   assert res.issues[1]["color"] == "#F0DC78"
   assert res.status == "warn"
   assert res.counts == {"lint.orphan": 2}
   assert lint(arr, rules=["orphan"], waive=[(4, 1)]).counts == {"lint.orphan": 1}


def test_orphan_found_on_sparse_layer():
   arr = image.new(8, 8)        # 얼굴 겹처럼 듬성한 판 : 눈 두 칸 + 이어진 입 두 칸
   arr[3, 2] = DOT
   arr[3, 5] = DOT
   arr[5, 3:5] = FILL
   res = lint(arr, rules=["orphan"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(2, 3), (5, 3)]


def test_hole_one_cell():
   arr = square()
   arr[3, 3] = (0, 0, 0, 0)   # 4방향 다 칠한 빈 칸
   arr[1, 5] = (0, 0, 0, 0)   # 가장자리 이빨 — 테두리 바깥과 이어져 구멍 아님
   res = lint(arr, rules=["lint.hole"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(3, 3)]
   assert res.issues[0]["color"] is None
   assert res.issues[0]["detail"] == "1칸 구멍 (3,3)"


def test_hole_three_cells_one_issue_per_blob():
   arr = square()
   arr[3, 2:5] = (0, 0, 0, 0)   # 이어진 세 칸 — 옛 정의(4방향 다 불투명 한 칸)로는 못 잡던 꼴
   res = lint(arr, rules=["hole"])
   assert [(i["x"], i["y"], i["detail"]) for i in res.issues] == [(2, 3, "3칸 구멍 (2,3) (3,3) (4,3)")]
   assert res.counts == {"lint.hole": 1}


def test_hole_big_frame_one_issue_lists_eight_cells():
   """액자처럼 속이 빈 그림은 칸마다가 아니라 덩어리 하나로 — 칸은 8개까지만 늘어놓는다."""
   arr = np.zeros((64, 64, 4), dtype=np.uint8)
   arr[:, :] = FILL
   arr[1:63, 1:63] = (0, 0, 0, 0)
   arr[30, 30] = FILL                                           # 속에 떠 있는 점 — 덩어리는 그대로 하나
   res = lint(arr, rules=["hole"])
   assert res.counts == {"lint.hole": 1} and (res.issues[0]["x"], res.issues[0]["y"]) == (1, 1)
   detail = res.issues[0]["detail"]
   assert detail.startswith("3843칸 구멍 (1,1) (2,1) ") and detail.endswith(" …") and detail.count("(") == 8


def test_hole_concave_open_to_border_not_found():
   arr = square()
   arr[1:5, 3:5] = (0, 0, 0, 0)    # 위에서 파고든 오목한 홈 — 그림 밖 투명과 이어진다
   assert lint(arr, rules=["hole"]).issues == []
   full = np.zeros((4, 4, 4), dtype=np.uint8)
   full[:, :] = FILL
   full[0, 1] = (0, 0, 0, 0)       # 그림 테두리 칸 자체가 빈 경우도 바깥
   assert lint(full, rules=["hole"]).issues == []


def test_stray_color_only_with_ramps():
   arr = square()
   arr[2:4, 2:4] = DOT
   assert "lint.stray_color" not in rules_of(lint(arr))
   res = lint(arr, ramps=ramps(), rules=["stray_color"])
   assert len(res.issues) == 4
   assert "팔레트 t 밖 색" in res.issues[0]["detail"]


def test_alpha_px():
   arr = square()
   arr[2, 2, 3] = 128
   res = lint(arr, rules=["alpha_px"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(2, 2)]
   assert "알파 128" in res.issues[0]["detail"]
   assert lint(square(), rules=["alpha_px"]).issues == []


def test_outline_gap_black():
   arr = outline(square(), "black")
   assert lint(arr, outline_mode="black").issues == []
   arr[0, 3] = (0, 0, 0, 0)     # 선 한 칸을 지우면 안쪽 채움 칸이 가장자리로 드러난다
   res = lint(arr, outline_mode="black", rules=["outline_gap"])
   assert (3, 1) in [(i["x"], i["y"]) for i in res.issues]
   assert "선 색 #000000 아님" in res.issues[0]["detail"]


def test_outline_gap_black_uses_palette_outline():
   r = Ramps("t", {"blue": [DARK, FILL[:3], LIGHT]}, (20, 10, 30), 3)
   arr = outline(square(), "black", ramps=r)
   assert lint(arr, ramps=r, outline_mode="black", rules=["outline_gap"]).issues == []


def test_outline_gap_solid_majority_color():
   arr = outline(square(), "solid", color="#402010")
   assert lint(arr, outline_mode="solid").issues == []
   arr[0, 4] = FILL
   res = lint(arr, outline_mode="solid", rules=["outline_gap"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(4, 0)]


def test_outline_gap_selout():
   arr = outline(square(), "selout", ramps=ramps())
   assert lint(arr, outline_mode="selout", rules=["outline_gap"]).issues == []
   bare = square()            # 선 없는 그림 : 가장자리가 안쪽과 같은 밝기
   res = lint(bare, outline_mode="selout+light", rules=["outline_gap"])
   assert res.counts["lint.outline_gap"] > 0
   assert res.issues[0]["detail"] == "안쪽 이웃보다 어둡지 않음"


def test_outline_gap_off_without_mode():
   for mode in (None, "none"):
      res = lint(square(), outline_mode=mode)
      assert "lint.outline_gap" not in res.counts


def test_waive_removes_from_all_rules():
   arr = square()
   arr[3, 3] = DOT
   arr[3, 3, 3] = 128        # orphan · alpha_px 둘 다 걸리는 칸
   assert lint(arr).counts["lint.orphan"] == 1
   res = lint(arr, waive=[(3, 3)])
   assert res.issues == []
   assert res.status == "ok"


def test_rules_pick_and_unknown():
   arr = square()
   arr[3, 3] = DOT
   arr[2, 2, 3] = 128
   res = lint(arr, rules=["alpha_px"])
   assert set(res.counts) == {"lint.alpha_px"}
   with pytest.raises(ArtToolError):
      lint(arr, rules=["lint.nope"])


def test_default_counts_and_dict_shape():
   arr = square()
   arr[3, 3] = DOT
   d = lint(arr).to_dict()
   assert set(d) == {"status", "issues", "counts", "metrics"}
   assert d["counts"] == {"lint.orphan": 1, "lint.hole": 0, "lint.alpha_px": 0}
   assert set(d["issues"][0]) == {"rule", "layer", "x", "y", "color", "detail"}
   assert d["issues"][0]["layer"] is None


def test_lines_format_with_and_without_layer():
   arr = square()
   arr[3, 3] = DOT
   res = lint(arr, rules=["orphan"])
   assert res.lines() == ["lint.orphan (3,3) #F0DC78 8이웃에 같은 색 없음"]
   res.issues[0]["layer"] = "hair"
   assert res.lines() == ["lint.orphan hair (3,3) #F0DC78 8이웃에 같은 색 없음"]
   hole = LintResult(issues=[{"rule": "lint.hole", "layer": None, "x": 1, "y": 2, "color": None, "detail": "빈 칸"}])
   assert hole.lines() == ["lint.hole (1,2) 빈 칸"]


def test_bad_input_rejected():
   with pytest.raises(ArtToolError):
      lint(np.zeros((4, 4, 3), dtype=np.uint8))
   with pytest.raises(ArtToolError):
      lint(square(), outline_mode="thick")
   with pytest.raises(ArtToolError):
      lint(square(), light="left")


# ── G4 : double · asym · light_mismatch · 수치 ──

def diagonal_with_clump():
   arr = image.new(10, 10)
   for i in (0, 1, 2, 3, 6, 7):
      arr[i, i] = DOT
   arr[4:6, 4:6] = DOT       # 1px 대각선 가운데 2×2 뭉침
   return arr


def test_double_found_on_line_only():
   res = lint(diagonal_with_clump(), rules=["double"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(4, 4)]
   assert res.issues[0]["color"] == "#F0DC78"
   assert lint(square(), rules=["double"]).issues == []    # 넓은 면은 선이 아니다
   lone = image.new(6, 6)
   lone[2:4, 2:4] = DOT                                   # 따로 떨어진 2×2 점
   assert lint(lone, rules=["double"]).issues == []


def test_new_rules_off_by_default():
   res = lint(diagonal_with_clump())
   assert not {"lint.double", "lint.asym", "lint.light_mismatch"} & set(res.counts)


def test_asym_left_cell_only():
   arr = square()
   arr[3, 2] = DOT           # 왼쪽 칸이 다름
   res = lint(arr, rules=["asym"])
   assert [(i["x"], i["y"]) for i in res.issues] == [(2, 3)]
   assert res.issues[0]["color"] == "#F0DC78"
   assert "거울 칸 (5,3)" in res.issues[0]["detail"]
   arr = square()
   arr[3, 5] = DOT           # 오른쪽이 달라도 왼쪽 짝 칸으로 짚는다
   assert [(i["x"], i["y"]) for i in lint(arr, rules=["asym"]).issues] == [(2, 3)]
   assert lint(square(), rules=["asym"]).issues == []


def test_asym_axis_and_transparent_left():
   arr = image.new(9, 3)
   arr[1, 1:6] = FILL        # 가운데 3 기준으로 대칭
   assert lint(arr, rules=["asym"], axis_x=3).issues == []
   assert lint(arr, rules=["asym"], axis_x=3).metrics["symmetry"] == 1.0
   res = lint(arr, rules=["asym"])           # 기본 축 4 : 왼쪽 (0,1) 이 비어 오른쪽 (8,1) 과 같다
   assert (3, 1) not in [(i["x"], i["y"]) for i in res.issues]
   assert res.counts["lint.asym"] > 0
   arr[1, 0] = (0, 0, 0, 0)
   arr[1, 6] = FILL
   hit = lint(arr, rules=["asym"], axis_x=3).issues
   assert [(i["x"], i["y"], i["color"]) for i in hit] == [(0, 1, None)]
   with pytest.raises(ArtToolError):
      lint(arr, axis_x=3.3)


def test_symmetry_metric():
   assert lint(square()).metrics["symmetry"] == 1.0
   arr = square()
   arr[3, 2] = DOT
   assert lint(arr).metrics["symmetry"] == round(34 / 36, 3)


def test_center_and_bbox():
   arr = image.new(4, 4)
   arr[0, 0] = FILL
   arr[1, 0] = FILL
   arr[1, 1] = FILL
   m = lint(arr).metrics
   assert m["bbox"] == [0, 0, 2, 2]
   assert m["center"] == [0.33, 0.67]
   assert m["center_offset"] == [-0.17, 0.17]


def test_empty_metrics():
   m = lint(image.new(4, 4)).metrics
   assert m == {"symmetry": None, "center": None, "center_offset": None, "bbox": None, "light_guess": "unknown"}


def shaded(level):
   """6×6 면을 칸마다 level(x, y) → 램프 칸(0 어둠 · 2 밝음)으로 칠한다."""
   arr = image.new(8, 8)
   ramp = [DARK, FILL[:3], LIGHT]
   for y in range(6):
      for x in range(6):
         arr[y + 1, x + 1] = (*ramp[level(x, y)], 255)
   return arr


def by_sum(s):
   return 2 if s < 5 else 0 if s > 5 else 1


SHADES = {
   "top_left": lambda x, y: by_sum(x + y),
   "top": lambda x, y: 2 if y < 2 else 0 if y > 3 else 1,
   "top_right": lambda x, y: by_sum((5 - x) + y),
}


@pytest.mark.parametrize("light", list(SHADES))
def test_light_guess_with_ramps(light):
   assert lint(shaded(SHADES[light]), ramps=ramps()).metrics["light_guess"] == light


@pytest.mark.parametrize("light", list(SHADES))
def test_light_guess_without_ramps_uses_luma(light):
   assert lint(shaded(SHADES[light])).metrics["light_guess"] == light


def test_light_guess_unknown():
   assert lint(square(), ramps=ramps()).metrics["light_guess"] == "unknown"          # 한 색
   below = shaded(lambda x, y: 0 if y < 2 else 2 if y > 3 else 1)                    # 밑이 밝음
   assert lint(below, ramps=ramps()).metrics["light_guess"] == "unknown"


def test_light_mismatch():
   arr = shaded(SHADES["top_right"])
   res = lint(arr, ramps=ramps(), light="top_left", rules=["light_mismatch"])
   assert len(res.issues) == 1
   i = res.issues[0]
   assert (i["x"], i["y"], i["color"]) == (None, None, None)
   assert res.lines() == ["lint.light_mismatch 명암 추정 top_right · 지정 빛 top_left"]
   assert lint(arr, ramps=ramps(), light="top_right", rules=["light_mismatch"]).issues == []
   assert lint(square(), rules=["light_mismatch"]).issues == []                      # unknown 은 안 따진다


def test_outline_color_for_solid():
   arr = outline(square(), "solid", color="#402010")
   assert lint(arr, outline_mode="solid", outline_color="#402010").issues == []
   assert lint(arr, outline_mode="solid", outline_color=(64, 32, 16)).issues == []
   res = lint(arr, outline_mode="solid", outline_color="#000000", rules=["outline_gap"])
   assert res.counts["lint.outline_gap"] == len(res.issues) > 0
   assert "선 색 #000000 아님" in res.issues[0]["detail"]
   with pytest.raises(ArtToolError):
      lint(arr, outline_mode="solid", outline_color="402010")


# ---- Canvas.lint (G4b) ----


def _hex(rgba):
   return "#{:02X}{:02X}{:02X}".format(*rgba[:3])


def test_canvas_lint_fills_layer_and_sums_counts():
   from arttool.draw import Canvas
   c = Canvas(10, layers=["body", "hair"], ramps=ramps())
   c["body"].box(1, 1, 9, 9, _hex(FILL)).dot(3, 3, _hex(DOT))     # body : 외톨이 1 + 팔레트 밖 1
   c["hair"].dot(6, 6, _hex(DOT))                                  # hair : 외톨이 1 + 팔레트 밖 1 (듬성한 겹도 잡는다)
   res = c.lint()
   assert res.status == "warn"
   assert {(i["rule"], i["layer"], i["x"], i["y"]) for i in res.issues} == {
      ("lint.orphan", "body", 3, 3), ("lint.stray_color", "body", 3, 3),
      ("lint.orphan", "hair", 6, 6), ("lint.stray_color", "hair", 6, 6)}
   assert res.counts["lint.stray_color"] == 2 and res.counts["lint.orphan"] == 2
   assert "lint.asym" not in res.counts
   assert res.metrics["bbox"] == [1, 1, 9, 9]                      # 수치는 합친 그림
   assert any(line.startswith("lint.orphan body (3,3)") for line in res.lines())


def test_canvas_lint_asym_only_on_symmetric_layer():
   from arttool.draw import Canvas
   c = Canvas(8, layers=["body", "hair"])
   c["body"].set_symmetry("x").dot(1, 1, _hex(FILL)).set_symmetry(None).dot(1, 5, _hex(FILL)).set_symmetry("x")
   c["hair"].dot(2, 3, _hex(FILL))                                 # 대칭 안 켠 겹 — asym 안 본다
   res = c.lint()
   asym = [(i["layer"], i["x"], i["y"]) for i in res.issues if i["rule"] == "lint.asym"]
   assert asym == [("body", 1, 5)]
   assert res.counts["lint.asym"] == 1
   picked = c.lint(rules=["orphan"])                               # rules 를 주면 자동 asym 없음
   assert "lint.asym" not in picked.counts


def test_canvas_lint_outline_gap_once_on_merged():
   from arttool.draw import Canvas
   c = Canvas(10, layers=["body", "hair"])
   c["body"].box(2, 2, 8, 8, _hex(FILL))
   c["hair"].box(2, 2, 8, 4, _hex(DOT))
   c.outline("black", where="inside")
   assert c.lint(outline_mode="black").counts.get("lint.outline_gap") == 0
   c["hair"].dot(4, 2, _hex(DOT))                                   # 위 가장자리 한 칸을 선 아닌 색으로
   res = c.lint(outline_mode="black", rules=["outline_gap"])
   gaps = [i for i in res.issues if i["rule"] == "lint.outline_gap"]
   assert [(i["layer"], i["x"], i["y"]) for i in gaps] == [(None, 4, 2)]   # 겹별이 아니라 합친 실루엣으로 한 번
   assert res.counts == {"lint.outline_gap": 1}


def test_canvas_lint_uses_canvas_defaults():
   from arttool.draw import Canvas
   c = Canvas(8, ramps=ramps())
   c.outline_mode = "black"
   c["body"].box(1, 1, 7, 7, _hex(FILL))
   res = c.lint()
   assert res.counts["lint.outline_gap"] > 0 and "lint.stray_color" in res.counts


def test_canvas_lint_hole_once_on_merged():
   from arttool.draw import Canvas
   c = Canvas(10, layers=["body", "face"])
   gap = np.zeros((10, 10), dtype=bool)
   gap[4, 3:6] = True
   c["body"].box(1, 1, 9, 9, _hex(FILL)).erase(gap)                              # 몸에 세 칸 구멍
   c["face"].dot(3, 2, _hex(DOT)).dot(4, 2, _hex(DOT))                          # 듬성한 겹 — 빈 칸이 많아도 구멍 아님
   res = c.lint(rules=["hole"])
   assert [(i["layer"], i["x"], i["y"], i["detail"]) for i in res.issues] == [
      (None, 3, 4, "3칸 구멍 (3,4) (4,4) (5,4)")]
   assert res.counts == {"lint.hole": 1}
   c["face"].dot(3, 4, _hex(DOT)).dot(4, 4, _hex(DOT)).dot(5, 4, _hex(DOT))   # 위 겹이 메우면 합친 그림엔 구멍 없음
   assert c.lint(rules=["hole"]).counts == {"lint.hole": 0}
