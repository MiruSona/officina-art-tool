"""피드백 후속 설계(2026-10-04) 새 명령을 **CLI 를 거쳐** 한 번씩 부른다 — 배선 갈래 W.

모듈 셈은 각 모듈 시험이 본다. 여기서는 「인자가 run 까지 닿나 · 보고가 써지나 · 종료 코드가 맞나」만 본다.
"""

from __future__ import annotations

import numpy as np
import pytest

from arttool import cli, errors, image
from arttool.jsonio import read_json

RED = (200, 40, 40, 255)
DARK = (20, 16, 16, 255)
WHITE = (255, 255, 255, 255)


def _save(path, arr):
   path.parent.mkdir(parents=True, exist_ok=True)
   image.save(path, arr)
   return path


def _blob(w=8, h=8, body=RED):
   """가운데 몸 + 어두운 테두리, 둘레 한 칸 투명."""
   arr = image.new(w, h)
   arr[1 : h - 1, 1 : w - 1] = DARK
   arr[2 : h - 2, 2 : w - 2] = body
   return arr


def _main(argv, report):
   code = cli.main([*argv, "--report", str(report)])
   return code, (read_json(report) if report.exists() else None)


def test_style_ref_through_cli(tmp_path):
   src = _save(tmp_path / "a.png", _blob(20, 20))
   b64 = tmp_path / "ref.txt"
   code, rep = _main(["style", "ref", "--in", str(src), "--canvas", "8x8", "--out", str(tmp_path / "r.png"), "--b64", str(b64), "--colors", "4"],
                     tmp_path / "r.json")
   assert code == errors.EXIT_OK
   assert rep["size"] == [8, 8] and rep["b64"] == str(b64) and b64.is_file()


def test_style_ref_report_cannot_be_b64(tmp_path):
   """--report 가 --b64 로 쓸 파일과 같으면 막는다 (REPORT_GUARDED)."""
   src = _save(tmp_path / "a.png", _blob())
   same = tmp_path / "same.json"
   argv = ["style", "ref", "--in", str(src), "--canvas", "8x8", "--out", str(tmp_path / "r.png"), "--b64", str(same), "--report", str(same)]
   assert cli.main(argv) == errors.EXIT_USAGE
   assert not same.exists()


def test_bands_through_cli(tmp_path):
   arr = image.new(10, 20, (90, 60, 40, 255))
   arr[:3] = WHITE
   src = _save(tmp_path / "raw.png", arr)
   mark = tmp_path / "m.png"
   code, rep = _main(["bands", "--in", str(src), "--top", "2", "--mark", str(mark)], tmp_path / "b.json")
   assert code == errors.EXIT_OK
   assert mark.is_file() and len(rep["lines"]) <= 2


def test_stitch_through_cli(tmp_path):
   top = _save(tmp_path / "top.png", image.new(6, 10, RED))
   low = _save(tmp_path / "low.png", image.new(6, 10, RED))
   out = tmp_path / "w.png"
   code, _ = _main(["stitch", "--in", f"{top}:0-4", str(low), "--out", str(out)], tmp_path / "s.json")
   assert code == errors.EXIT_OK
   assert image.size(image.load(out)) == (6, 14)


def test_tile_offset_through_cli(tmp_path):
   src = _save(tmp_path / "g.png", image.new(64, 64, (60, 140, 60, 255)))
   mask = tmp_path / "mask.png"
   code, rep = _main(["tile", "offset", "--in", str(src), "--out", str(tmp_path / "s.png"), "--mask", str(mask), "--band", "8"],
                     tmp_path / "o.json")
   assert code == errors.EXIT_OK
   assert rep["band"] == 8 and mask.is_file()


def test_tile_ldtk_still_routes(tmp_path):
   """`tile` 의 맨 끝 ldtk 갈래가 offset 배선 뒤에도 그대로 간다 (없는 맵 파일 → 종료 1)."""
   argv = ["tile", "ldtk", "--map", str(tmp_path / "none.json"), "--tileset", str(tmp_path / "t.json"), "--out", str(tmp_path / "o.ldtk")]
   assert cli.main(argv) == errors.EXIT_ERROR


def _fence(length=160, step=37):
   arr = image.new(length, 12)
   arr[3:5, :] = (120, 80, 40, 255)
   for x in range(5, length, step):
      arr[:, x : x + 4] = (70, 45, 25, 255)
   return arr


def test_extend_period_through_cli(tmp_path):
   src = _save(tmp_path / "f.png", _fence())
   code, rep = _main(["extend", "period", "--in", str(src), "--tile", "32"], tmp_path / "p.json")
   assert code == errors.EXIT_OK
   assert rep["period"] == 37
   assert any(w["rule"] == "period.not_multiple" for w in rep["warnings"])


def test_extend_ring_through_cli(tmp_path):
   arr = image.new(10, 10, DARK)
   arr[3:7, 3:7] = (0, 0, 0, 0)
   src = _save(tmp_path / "ring.png", arr)
   out = tmp_path / "o.png"
   code, rep = _main(["extend", "ring", "--in", str(src), "--border", "3", "--size", "15x16", "--out", str(out), "--snap"], tmp_path / "r.json")
   assert code == errors.EXIT_OK
   assert list(image.size(image.load(out))) == rep["size"] != [15, 16]


def test_extend_canvas_through_cli(tmp_path):
   src = _save(tmp_path / "bg.png", image.new(8, 8, RED))
   out = tmp_path / "o.png"
   code, _ = _main(["extend", "canvas", "--in", str(src), "--size", "8x12", "--out", str(out), "--anchor", "top"], tmp_path / "c.json")
   assert code == errors.EXIT_OK
   assert image.size(image.load(out)) == (8, 12)


def test_extend_canvas_bad_anchor_is_usage():
   with pytest.raises(SystemExit) as caught:
      cli.build_parser().parse_args(["extend", "canvas", "--in", "a", "--size", "8x8", "--out", "o", "--anchor", "middle"])
   assert caught.value.code == errors.EXIT_USAGE


@pytest.mark.skipif(not image.has_label_font(), reason="시험 글꼴(Pretendard)이 없다")
def test_ui_glyphs_missing_exits_4(tmp_path):
   font = str(image.LABEL_FONT)
   code, rep = _main(["ui", "glyphs", "--font", font, "--text", "가나"], tmp_path / "ok.json")
   assert code == errors.EXIT_OK and rep["checked"] == 2
   code, rep = _main(["ui", "glyphs", "--font", font, "--text", "가☃"], tmp_path / "miss.json")
   assert code == errors.EXIT_CHECK_FAIL
   assert [row["code"] for row in rep["missing"]] == ["U+2603"]


def test_ui_glyphs_report_cannot_be_text_file(tmp_path):
   text = tmp_path / "chars.json"
   text.write_text("가", encoding="utf-8")
   argv = ["ui", "glyphs", "--font", "f.ttf", "--text-file", str(text), "--report", str(text)]
   assert cli.main(argv) == errors.EXIT_USAGE
   assert text.read_text(encoding="utf-8") == "가"


def test_reline_through_cli(tmp_path):
   arr = _blob(8, 8)
   arr[1, 3] = (40, 30, 30, 255)
   _save(tmp_path / "raw" / "a.png", arr)
   code, rep = _main(["reline", "--in", str(tmp_path / "raw"), "--out", str(tmp_path / "o"), "--color", "#000000"], tmp_path / "l.json")
   assert code == errors.EXIT_OK
   out = image.load(tmp_path / "o" / "a.png")
   assert tuple(out[1, 3]) == (0, 0, 0, 255)
   assert rep is not None


def test_tint_through_cli(tmp_path):
   _save(tmp_path / "white" / "hair.png", _blob(6, 6, WHITE))
   sheet = tmp_path / "t.png"
   code, _ = _main(["tint", "--in", str(tmp_path / "white"), "--colors", "#E85D5D", "--out", str(tmp_path / "t"), "--sheet", str(sheet), "--scale", "2"],
                   tmp_path / "t.json")
   assert code == errors.EXIT_OK
   assert (tmp_path / "t" / "hair_E85D5D.png").is_file() and sheet.is_file()


def test_layers_diff_drop_through_cli(tmp_path):
   body = image.new(12, 12)
   body[2:12, 2:10] = (250, 220, 190, 255)
   hair = body.copy()
   hair[3:6, 2:10] = (90, 50, 30, 255)
   hair[6, 3:9] = (240, 205, 178, 255)
   _save(tmp_path / "idle.png", body)
   _save(tmp_path / "inp" / "hair.png", hair)
   argv = ["layers", "diff", "--base", str(tmp_path / "idle.png"), "--in", str(tmp_path / "inp"), "--out", str(tmp_path / "set"),
           "--drop", "hair:#FADCBE", "--drop-tol", "24"]
   code, rep = _main(argv, tmp_path / "d.json")
   assert code == errors.EXIT_OK
   assert rep["layers"]["hair"]["dropped"] == 6


def test_sheet_grid_through_cli(tmp_path):
   src = _save(tmp_path / "in.png", image.new(16, 16, RED))
   code, rep = _main(["sheet", "--in", str(src), "--out", str(tmp_path / "s.png"), "--grid", "8", "--grid-color", "#00FF00"], tmp_path / "g.json")
   assert code == errors.EXIT_OK
   assert rep["scale"] >= 4
   made = image.load(tmp_path / "s.png")
   assert np.any(np.all(made == (0, 255, 0, 255), axis=2))
