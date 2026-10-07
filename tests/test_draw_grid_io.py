"""격자 읽기 · 덧그리기 · `grid show/apply` (draw 고리 설계 2절 · G2)."""

import json

import numpy as np
import pytest

import test_layers_ops
from arttool import cli, errors, image
from arttool.draw import Canvas, Legend
from arttool.draw.grid import parse, to_text
from arttool.errors import ArtToolError
from arttool.palette import Ramps

RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _sample():
   arr = image.new(6, 4)
   arr[0, 0:3] = (*RED, 255)
   arr[1, 2] = (*BLUE, 255)
   arr[3, 5] = (10, 20, 30, 255)
   return arr


def _back(legend, rows):
   arr = image.new(len(rows[0]), len(rows))
   for y, row in enumerate(rows):
      for x, ch in enumerate(row):
         if ch != ".":
            arr[y, x] = (*legend.color(ch), 255)
   return arr


@pytest.mark.parametrize("rulers", [False, True])
def test_round_trip(rulers):
   arr = _sample()
   legend, rows, size, origin = parse(to_text(arr, rulers=rulers))
   assert size == (6, 4) and origin == ((0, 0) if rulers else None)
   assert np.array_equal(_back(legend, rows), arr)


def test_round_trip_window_with_rulers_and_all_transparent():
   arr = _sample()
   _legend, rows, size, origin = parse(to_text(arr, box=(1, 1, 4, 3), rulers=True))
   assert size == (3, 2) and rows[0] == ".a." and origin == (1, 1)
   legend, rows, size, _origin = parse(to_text(image.new(3, 2)))
   assert len(legend) == 0 and rows == ["...", "..."]


def test_parse_errors_carry_line_numbers():
   with pytest.raises(ArtToolError, match="4째 줄 : 너비"):
      parse("a #FF0000\n\naa\naaa\n")
   with pytest.raises(ArtToolError, match="3째 줄 1째 칸 : 범례에 없는 글자 'z'"):
      parse("a #FF0000\n\naz\n")
   with pytest.raises(ArtToolError, match="1째 줄 0째 칸 : 범례가 없는데"):
      parse("ab\n")
   with pytest.raises(ArtToolError, match="2째 줄 : .*두 번"):
      parse("a #FF0000\na #00FF00\n\na\n")


def test_parse_uses_given_legend_when_text_has_none():
   given = Legend({"k": RED})
   legend, rows, _, _ = parse("# 주석\nk.k\n", given)
   assert legend is given and rows == ["k.k"]
   with pytest.raises(ArtToolError, match="'k' 가 글 안 범례"):     # 같은 글자에 다른 색
      parse("k #0000FF\n\nk\n", given)


def test_parse_merges_text_legend_with_given():
   given = Legend({"k": RED})
   merged, rows, _, _ = parse("b #0000FF\n\nbk\n", given)              # b 는 글 안, k 는 캔버스 범례에서
   assert merged.letters() == {"b": BLUE, "k": RED} and rows == ["bk"]
   assert given.letters() == {"k": RED}                               # parse 는 given 을 안 바꾼다


def test_parse_origin_from_heads_and_origin_line():
   assert parse("a #FF0000\n\n 5 a.\n 6 .a\n")[3] == (None, 5)        # 줄머리만 — x 는 모른다
   assert parse("a #FF0000\n# 원점 12,5\n\n 5 a.\n")[3] == (12, 5)
   with pytest.raises(ArtToolError, match="원점 줄 y 4"):
      parse("a #FF0000\n# 원점 12,4\n\n 5 a.\n")


def test_paste_over_keeps_dot_and_replace_erases():
   c = Canvas(4, layers=["body"])
   c["body"].box(0, 0, 4, 4, "#00FF00")
   rep = c.paste_grid("body", "a #FF0000\n\na.\n.a\n", at=(1, 1))
   assert rep == {"pixels_written": 2, "pixels_clipped": 0, "bbox": [1, 1, 3, 3]}
   assert c["body"].px(1, 1) == "#FF0000" and c["body"].px(2, 1) == "#00FF00"
   rep = c.paste_grid("body", "a #FF0000\n\na.\n", at=(0, 0), mode="replace")
   assert c["body"].px(1, 0) is None and rep["pixels_written"] == 2


def test_paste_ruled_grid_lands_on_same_place():
   """리뷰 1 : 눈금 찍은 글을 고쳐 at 없이 붙이면 읽은 자리 그대로 찍힌다."""
   c = Canvas(40, layers=["body"])
   c["body"].box(20, 30, 24, 33, "#00FF00")
   text = c.to_grid("body", box=(18, 29, 26, 34), rulers=True)
   assert "# 원점 18,29" in text
   fixed = text.replace("a #00FF00", "a #00FF00\nr #FF0000").replace("aaaa", "arra", 1)
   rep = c.paste_grid("body", fixed)
   assert rep["bbox"] == [21, 30, 23, 31] and c["body"].last["at"] == [18, 29]
   assert c["body"].px(21, 30) == "#FF0000" and c["body"].px(1, 1) is None
   with pytest.raises(ArtToolError, match="원점"):
      c.paste_grid("body", fixed, at=(0, 0))
   assert c.paste_grid("body", fixed, at=(18, 29))["pixels_written"] == 0
   with pytest.raises(ArtToolError, match="x 를 모른다"):
      c.paste_grid("body", "r #FF0000\n\n29 r\n")
   assert c.paste_grid("body", "r #FF0000\n\n29 r\n", at=(5, 29))["bbox"] == [5, 29, 6, 30]


def test_paste_text_legend_fills_from_canvas_and_registers():
   """리뷰 4 : 글 안 범례 + 캔버스 범례를 같이 쓰고, 글 안 새 색은 캔버스 범례에 들어간다."""
   c = Canvas(4, layers=["body"])
   c["body"].dot(0, 0, "#0000FF")
   c.to_grid()                                  # 파랑 = 'a'
   c.paste_grid("body", "r #FF0000\n\nra\n", at=(1, 1))
   assert c["body"].px(1, 1) == "#FF0000" and c["body"].px(2, 1) == "#0000FF"
   assert c.legend.letters() == {"a": BLUE, "r": RED}
   with pytest.raises(ArtToolError, match="'a' 가 글 안 범례"):
      c.paste_grid("body", "a #00FF00\n\na\n")
   c.paste_grid("body", "x #FF0000\n\nx\n", at=(3, 3))                  # 이미 'r' 인 색 — 글자 하나 더 안 만든다
   assert c["body"].px(3, 3) == "#FF0000" and "x" not in c.legend.letters()


def test_paste_clips_outside_canvas():
   c = Canvas(4, layers=["body"])
   rep = c.paste_grid("body", "a #FF0000\n\naaa\naaa\n", at=(2, -1))
   assert rep["pixels_written"] == 2 and rep["pixels_clipped"] == 4 and rep["bbox"] == [2, 0, 4, 1]


def test_paste_with_symmetry_mirrors_and_marks_dirty():
   c = Canvas(6, layers=["body"])
   c["body"].set_symmetry("x")
   c.paste_grid("body", "a #FF0000\n\naa\n", at=(0, 2))
   assert c["body"].px(5, 2) == "#FF0000" and c["body"].px(4, 2) == "#FF0000"
   assert int(c["body"].dirty.sum()) == 4


def test_paste_without_legend_uses_canvas_legend_or_fails():
   c = Canvas(4, layers=["body"])
   with pytest.raises(ArtToolError, match="범례가 없는데"):
      c["body"].paste_grid("a\n")
   c["body"].dot(0, 0, "#0000FF")
   c.to_grid()                                  # 파랑이 'a' 로 배정된다
   c.paste_grid("body", "a\n", at=(3, 3))
   assert c["body"].px(3, 3) == "#0000FF"


def test_canvas_legend_follows_ramp_order():
   ramps = Ramps("t", {"skin": [(10, 0, 0), (20, 0, 0)], "hair": [(30, 0, 0)]}, (1, 1, 1), 2)
   c = Canvas(4, layers=["body"], ramps=ramps)
   assert c.legend.letters() == {"a": (10, 0, 0), "b": (20, 0, 0), "c": (30, 0, 0), "d": (1, 1, 1)}
   c["body"].dot(0, 0, (30, 0, 0))
   assert c.to_grid().splitlines()[-4] == "c..."


def test_canvas_to_grid_over_64_names_guide_boxes():
   c = Canvas(70, layers=["body"])
   with pytest.raises(ArtToolError, match="64"):
      c.to_grid()
   c.guide = type("G", (), {"names": lambda self: {"boxes": ["head", "torso"]}})()
   with pytest.raises(ArtToolError, match="head · torso"):
      c.to_grid()
   assert c.to_grid(box=(0, 0, 4, 4)).endswith("....\n")


# ---- CLI ----


def _set(tmp_path):
   folder = tmp_path / "set"
   test_layers_ops.write_set(folder, test_layers_ops.three_layers())
   return folder


def test_cli_grid_show_folder_and_png(tmp_path, capsys):
   folder = _set(tmp_path)
   assert cli.main(["grid", "show", "--in", str(folder), "--layer", "face"]) == 0
   out = capsys.readouterr().out
   legend, rows, size, _origin = parse(out)
   assert size == (12, 12) and rows[7][4] == "a" and legend.color("a") == test_layers_ops.EYE
   png = tmp_path / "a.png"
   image.save(png, _sample())
   assert cli.main(["grid", "show", "--in", str(png), "--rulers", "--box", "0,0,3,2"]) == 0
   assert capsys.readouterr().out.splitlines()[-2:] == ["0 aaa", "1 ..b"]


def test_cli_grid_show_over_64_exits_2(tmp_path, capsys):
   png = tmp_path / "big.png"
   image.save(png, image.new(70, 8))
   assert cli.main(["grid", "show", "--in", str(png)]) == errors.EXIT_USAGE
   assert "--box" in capsys.readouterr().err


def test_cli_grid_apply_folder(tmp_path):
   folder = _set(tmp_path)
   patch = tmp_path / "p.px"
   patch.write_text("r #FF0000\n\nrr\n", encoding="utf-8")
   out, rep = tmp_path / "out", tmp_path / "r.json"
   before = (folder / "face" / "idle.png").read_bytes()
   argv = ["grid", "apply", "--in", str(folder), "--grid", str(patch), "--layer", "face", "--at", "1,1", "--out", str(out)]
   assert cli.main([*argv, "--report", str(rep)]) == 0
   report = json.loads(rep.read_text(encoding="utf-8"))
   assert report["pixels_written"] == 2 and report["bbox"] == [1, 1, 3, 2]
   assert (folder / "face" / "idle.png").read_bytes() == before          # 원본은 그대로
   assert image.load(out / "face" / "idle.png")[1, 2].tolist() == [255, 0, 0, 255]
   assert (out / "hair" / "idle.png").read_bytes() == (folder / "hair" / "idle.png").read_bytes()


def test_cli_grid_apply_ruled_patch_without_at(tmp_path, capsys):
   png = tmp_path / "a.png"
   image.save(png, _sample())
   assert cli.main(["grid", "show", "--in", str(png), "--rulers", "--box", "2,1,3,2"]) == 0
   patch = tmp_path / "p.px"
   shown = capsys.readouterr().out
   assert "# 원점 2,1" in shown and "a #0000FF" in shown
   patch.write_text(shown.replace("a #0000FF", "a #FF0000"), encoding="utf-8")   # 파랑 칸을 빨강으로
   out, rep = tmp_path / "b.png", tmp_path / "r.json"
   assert cli.main(["grid", "apply", "--in", str(png), "--grid", str(patch), "--out", str(out), "--report", str(rep)]) == 0
   report = json.loads(rep.read_text(encoding="utf-8"))
   assert report["at"] == [2, 1] and report["bbox"] == [2, 1, 3, 2]
   assert image.load(out)[1, 2].tolist() == [*RED, 255]


def test_cli_grid_apply_small_layer_outside_box_refused_before_write(tmp_path, capsys):
   """리뷰 2 : 작은 겹 상자 밖 패치는 dry-run 도 실제도 같은 오류 · 반쯤 쓴 폴더를 안 남긴다."""
   folder = tmp_path / "set"
   tpl = {"version": 2, "canvas": [16, 16], "items": ["idle"],
          "layers": [{"name": "body", "kind": "body"},
                     {"name": "cheek", "kind": "face", "size": [3, 2], "offset": [10, 12]}]}
   Canvas(16, template=tpl).save(folder)
   patch = tmp_path / "p.px"
   patch.write_text("r #FF0000\n\nr\n", encoding="utf-8")
   out = tmp_path / "out"
   argv = ["grid", "apply", "--in", str(folder), "--grid", str(patch), "--layer", "cheek", "--at", "0,0", "--out", str(out)]
   assert cli.main([*argv, "--dry-run"]) == errors.EXIT_USAGE
   dry_err = capsys.readouterr().err
   assert cli.main(argv) == errors.EXIT_USAGE
   assert "상자" in dry_err and dry_err == capsys.readouterr().err
   assert not out.exists()
   assert cli.main([*argv[:-4], "--at", "11,12", "--out", str(out)]) == 0      # 상자 안이면 된다
   assert image.load(out / "cheek" / "idle.png").shape == (2, 3, 4)


def test_cli_grid_apply_png_dry_run_and_same_path(tmp_path, capsys):
   png = tmp_path / "a.png"
   image.save(png, _sample())
   patch = tmp_path / "p.px"
   patch.write_text("..\n", encoding="utf-8")
   assert cli.main(["grid", "apply", "--in", str(png), "--grid", str(patch), "--out", str(png)]) == errors.EXIT_USAGE
   out = tmp_path / "b.png"
   argv = ["grid", "apply", "--in", str(png), "--grid", str(patch), "--mode", "replace", "--out", str(out)]
   capsys.readouterr()
   assert cli.main([*argv, "--dry-run", "--json"]) == 0
   dry = json.loads(capsys.readouterr().out)
   assert dry["dry_run"] is True and not out.exists() and dry["pixels_written"] == 2
   assert cli.main(argv) == 0
   assert image.load(out)[0, 0, 3] == 0 and image.load(out)[0, 2, 3] == 255


# ---- lint CLI (G4b) ----


def test_cli_lint_png_human_and_json(tmp_path, capsys):
   arr = image.new(8, 8)
   arr[1:7, 1:7] = (*BLUE, 255)
   arr[3, 3] = (*RED, 255)
   png = tmp_path / "a.png"
   image.save(png, arr)
   before = sorted(p.name for p in tmp_path.iterdir())
   assert cli.main(["lint", "--in", str(png)]) == 0                 # 걸려도 종료 0
   lines = capsys.readouterr().out.splitlines()
   assert lines[0] == "lint.orphan body (3,3) #FF0000 8이웃에 같은 색 없음"
   assert lines[-1].startswith("warn · 이슈 1건 · symmetry")
   assert cli.main(["lint", "--in", str(png), "--json", "--rules", "hole"]) == 0
   data = json.loads(capsys.readouterr().out)
   assert set(data) == {"status", "issues", "counts", "metrics"} and data["counts"] == {"lint.hole": 0}
   assert sorted(p.name for p in tmp_path.iterdir()) == before       # 파일 안 씀


def test_cli_lint_folder_report_and_bad_rule(tmp_path, capsys):
   folder = _set(tmp_path)
   rep = tmp_path / "r.json"
   assert cli.main(["lint", "--in", str(folder), "--report", str(rep)]) == 0
   report = json.loads(rep.read_text(encoding="utf-8"))
   assert report["metrics"]["bbox"] is not None
   assert all(i["layer"] in ("body", "hair", "face", None) for i in report["issues"])
   assert cli.main(["lint", "--in", str(folder), "--rules", "nope"]) == errors.EXIT_USAGE
   assert "--rules" in capsys.readouterr().err
