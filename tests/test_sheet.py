"""비교판 sheet · 딱지 글꼴 (설계 5절 · 5-1). 그림은 모두 코드로 만든다.

글꼴 판이 바뀌어도 안 흔들리게 딱지는 픽셀 대조를 하지 않는다.
「띠 안에 글자 칸이 있다 · 띠 밖은 그대로다 · 한글 두 글자의 모양이 다르다(빈 네모가 아니다)」만 본다.
"""

import numpy as np
import pytest

import helpers
from arttool import cli, errors, image, sheet


def _two_tone(w=8, h=8):
   """테두리 · 몸통 두 색 + 밝은 점 하나."""
   arr = helpers.blob(w, h)
   arr[2, 2] = (240, 230, 200, 255)
   return arr


def _write_inputs(tmp_path):
   folder = tmp_path / "in"
   folder.mkdir()
   image.save(folder / "용사.png", _two_tone(8, 12))
   image.save(folder / "슬라임.png", _two_tone(10, 8))
   return folder


def _main(argv):
   return cli.main(argv)


# ── image.py 에 더한 것 ──

def test_luma_weights():
   arr = image.new(3, 1, (0, 0, 0, 255))
   arr[0, 0] = (255, 0, 0, 255)
   arr[0, 1] = (0, 255, 0, 255)
   arr[0, 2] = (0, 0, 255, 255)
   assert np.allclose(image.luma(arr)[0], [0.299 * 255, 0.587 * 255, 0.114 * 255])


def test_quantize_luma_at_most_four_grays_and_keeps_transparent():
   rng = np.random.default_rng(7)
   arr = rng.integers(0, 256, size=(16, 16, 4), dtype=np.uint8)
   arr[:, :, 3] = 255
   arr[0:4, 0:4, 3] = 0
   out = image.quantize_luma(arr, 4)
   colors = image.opaque_colors(out)
   assert len(colors) == 4
   assert all(r == g == b for r, g, b in colors)
   assert np.array_equal(out[:, :, 3], arr[:, :, 3])


def test_quantize_luma_keeps_dominant_level_apart():
   """한 밝기가 칸 대부분을 차지해도 이웃 밝기와 뭉개지지 않는다."""
   arr = image.new(10, 10, (40, 120, 200, 255))
   arr[0, :] = (20, 60, 110, 255)
   arr[9, :] = (160, 210, 250, 255)
   assert image.count_colors(image.quantize_luma(arr, 4)) == 3


def test_blur_softens_edge():
   arr = image.new(8, 8, (0, 0, 0, 255))
   arr[:, 4:] = (255, 255, 255, 255)
   out = image.blur(arr, 2)
   assert 0 < out[4, 3, 0] < 255
   assert image.blur(arr, 0).tolist() == arr.tolist()


@pytest.mark.skipif(not image.has_label_font(), reason="딱지 글꼴이 없다")
def test_draw_label_two_tone_and_hangul_glyphs_differ():
   def glyph(text):
      arr = image.new(30, 17, (0, 0, 0, 255))
      image.draw_label(arr, text, 0, 1)
      return arr

   a, b = glyph("가"), glyph("힣")
   assert image.opaque_colors(a) == {(0, 0, 0), (255, 255, 255)}  # 반투명 · 중간색 없음
   assert (a[:, :, 0] == 255).sum() > 5
   assert not np.array_equal(a, b)  # 빈 네모(.notdef)면 둘이 같다


# ── 판 ──

def test_kind_sizes():
   arr = _two_tone(6, 4)
   assert sheet.kind_layer(arr, "zoom", 3).shape[:2] == (12, 18)
   assert sheet.kind_layer(arr, "silhouette", 3).shape[:2] == (12, 18)
   assert sheet.kind_layer(arr, "colors4", 3).shape[:2] == (12, 18)
   assert sheet.render_kind(arr, "blur", 3).shape[:2] == (12, 18)
   assert sheet.kind_layer(arr, "tile", 3, 2).shape[:2] == (24, 36)
   assert sheet.kind_layer(arr, "tile", 1, 4).shape[:2] == (16, 24)


def test_zoom_is_nearest():
   arr = _two_tone()
   big = sheet.kind_layer(arr, "zoom", 4)
   assert np.array_equal(big[::4, ::4], arr)
   assert image.opaque_colors(big) == image.opaque_colors(arr)


def test_silhouette_one_color_and_colors4_at_most_four():
   arr = image.new(8, 8)
   arr[2:6, 1:7] = (200, 40, 40, 255)
   arr[3, 3] = (10, 200, 90, 255)
   assert image.count_colors(sheet.kind_layer(arr, "silhouette", 2)) == 1
   assert image.count_colors(sheet.kind_layer(arr, "colors4", 2)) <= 4


def test_render_over_solid_bg_fills_transparent():
   arr = image.new(4, 4)
   arr[1, 1] = (255, 0, 0, 255)
   cell = sheet.render_kind(arr, "silhouette", 2, bg=(0, 255, 0, 255))
   assert np.all(cell[:, :, 3] == 255)
   assert image.opaque_colors(cell) == {(0, 255, 0), sheet.SILHOUETTE[:3]}


# ── 줄 그리기 ──

def test_layout_rows_places_cells_and_rejects_too_big(monkeypatch):
   a = image.new(5, 3, (255, 0, 0, 255))
   b = image.new(2, 7, (0, 0, 255, 255))
   out = sheet.layout_rows([[a, b], [b]], gap=1)
   # 열 폭 = (5, 2), 줄 높이 = (7, 7)
   assert image.size(out) == (1 + 5 + 1 + 2 + 1, 1 + 7 + 1 + 7 + 1)
   assert tuple(out[1, 1]) == (255, 0, 0, 255)
   assert tuple(out[1, 7]) == (0, 0, 255, 255)
   monkeypatch.setattr(image, "MAX_PIXELS", 50)
   with pytest.raises(errors.ArtToolError):
      sheet.layout_rows([[a, b]], gap=1)


@pytest.mark.skipif(not image.has_label_font(), reason="딱지 글꼴이 없다")
def test_layout_rows_label_band_only():
   cell = image.new(40, 10, (0, 0, 255, 255))
   plain = sheet.layout_rows([[cell]], gap=2)
   labeled = sheet.layout_rows([[cell]], row_labels=["용사 8x8"], gap=2)
   band_top = 2 + 10
   # 띠 위(그림 칸)는 딱지가 없을 때와 같다
   assert np.array_equal(labeled[:band_top], plain[:band_top])
   band = labeled[band_top : band_top + image.LABEL_PX + 4]
   assert np.any(np.all(band == sheet.LABEL_COLOR, axis=2))


@pytest.mark.skipif(not image.has_label_font(), reason="딱지 글꼴이 없다")
def test_fit_text_cuts_long_name():
   text = "아주아주긴한글파일이름_걷기_01"
   cut = sheet.fit_text(text, 40)
   assert cut.endswith(sheet.ELLIPSIS) and image.label_width(cut) <= 40
   assert sheet.fit_text("가", 100) == "가"


# ── 재기 ──

def test_measure_isolated_and_outline():
   arr = helpers.blob(8, 8)
   arr[3, 3] = (250, 0, 0, 255)  # 몸통 한가운데 외톨이 하나
   numbers = sheet.measure(arr)
   assert numbers["colors"] == 3
   assert numbers["isolated"] == 1
   # 가장자리 28칸 중 모서리 4칸은 안쪽 이웃이 없어 빠진다 → 24 / 64
   assert numbers["outline_ratio"] == round(24 / 64, 4)


# ── 명령 ──

def test_cli_sheet_report_and_same_output(tmp_path):
   folder = _write_inputs(tmp_path)
   out1, out2, rep = tmp_path / "s1.png", tmp_path / "s2.png", tmp_path / "r.json"
   kinds = "zoom,silhouette,colors4,blur,tile"
   base = ["sheet", "--in", str(folder), "--kinds", kinds, "--scale", "3", "--bg", "#203040"]
   assert _main(base + ["--out", str(out1), "--report", str(rep)]) == errors.EXIT_OK
   assert _main(base + ["--out", str(out2)]) == errors.EXIT_OK
   assert np.array_equal(image.load(out1), image.load(out2))

   from arttool.jsonio import read_json

   report = read_json(rep)
   assert report["status"] == "ok" and report["scale"] == 3
   assert [it["name"] for it in report["items"]] == ["슬라임.png", "용사.png"]
   assert report["items"][1]["size"] == [8, 12]
   assert report["items"][0]["colors"] == 3
   # 줄 2 개, 칸 다섯 (tile 은 2×2) — 크기로 확인
   width, height = report["size"]
   assert width == 4 + (10 * 3) * 4 + (10 * 3 * 2) + 4 * 4 + 4
   assert height == 4 + 8 * 3 * 2 + 4 + 12 * 3 * 2 + 4


def test_cli_sheet_auto_scale_and_files(tmp_path):
   a = tmp_path / "a.png"
   image.save(a, _two_tone(32, 16))
   rep = tmp_path / "r.json"
   assert _main(["sheet", "--in", str(a), "--out", str(tmp_path / "s.png"), "--report", str(rep)]) == errors.EXIT_OK
   from arttool.jsonio import read_json

   assert read_json(rep)["scale"] == 8  # 256 // 32


@pytest.mark.skipif(not image.has_label_font(), reason="딱지 글꼴이 없다")
def test_cli_sheet_hangul_label(tmp_path):
   folder = _write_inputs(tmp_path)
   plain, labeled = tmp_path / "p.png", tmp_path / "l.png"
   assert _main(["sheet", "--in", str(folder), "--out", str(plain), "--scale", "2"]) == errors.EXIT_OK
   assert _main(["sheet", "--in", str(folder), "--out", str(labeled), "--scale", "2", "--label"]) == errors.EXIT_OK
   p, l = image.load(plain), image.load(labeled)
   assert l.shape[0] > p.shape[0]
   assert np.any(np.all(l == sheet.LABEL_COLOR, axis=2))
   assert not np.any(np.all(p == sheet.LABEL_COLOR, axis=2))


def test_cli_sheet_without_font_warns_and_still_draws(tmp_path, monkeypatch, capsys):
   monkeypatch.setattr(image, "LABEL_FONT", tmp_path / "없는글꼴.otf")
   folder = _write_inputs(tmp_path)
   out = tmp_path / "s.png"
   assert _main(["--json", "sheet", "--in", str(folder), "--out", str(out), "--label"]) == errors.EXIT_OK
   assert out.is_file()
   text = capsys.readouterr().out
   assert "label_font" in text


@pytest.mark.parametrize(
   "extra",
   [["--kinds", "zoom,nope"], ["--kinds", " , "], ["--scale", "0"], ["--scale", "x"], ["--bg", "red"]],
)
def test_cli_sheet_bad_args(tmp_path, extra):
   folder = _write_inputs(tmp_path)
   assert _main(["sheet", "--in", str(folder), "--out", str(tmp_path / "s.png")] + extra) == errors.EXIT_USAGE


def test_cli_sheet_missing_input_and_too_big(tmp_path, monkeypatch):
   assert _main(["sheet", "--in", str(tmp_path / "없음.png"), "--out", str(tmp_path / "s.png")]) == errors.EXIT_ERROR
   folder = _write_inputs(tmp_path)
   monkeypatch.setattr(image, "MAX_PIXELS", 1000)
   out = tmp_path / "big.png"
   assert _main(["sheet", "--in", str(folder), "--out", str(out), "--scale", "8"]) == errors.EXIT_ERROR
   assert not out.exists()


def test_cli_sheet_refuses_to_overwrite_input(tmp_path):
   """--out 이 입력 PNG 와 같으면 거절하고 원본은 그대로 (R1-H1)."""
   folder = _write_inputs(tmp_path)
   target = folder / "용사.png"
   before = target.read_bytes()
   assert _main(["sheet", "--in", str(folder), "--out", str(target)]) == errors.EXIT_USAGE
   assert _main(["sheet", "--in", str(target), "--out", str(folder / "용사.PNG")]) == errors.EXIT_USAGE
   assert target.read_bytes() == before


def test_cli_sheet_scale_has_upper_limit(tmp_path):
   folder = _write_inputs(tmp_path)
   assert _main(["sheet", "--in", str(folder), "--out", str(tmp_path / "s.png"), "--scale", str(sheet.SCALE_MAX + 1)]) == errors.EXIT_USAGE


def test_too_big_is_refused_before_drawing(tmp_path, monkeypatch):
   """판 크기 상한은 칸을 그리기 전에 본다 (R1-M3)."""
   folder = _write_inputs(tmp_path)
   monkeypatch.setattr(image, "MAX_PIXELS", 1000)

   def boom(*args, **kwargs):
      raise AssertionError("크기 검사 전에 칸을 그렸다")

   monkeypatch.setattr(sheet, "render_kind", boom)
   assert _main(["sheet", "--in", str(folder), "--out", str(tmp_path / "s.png"), "--scale", "8"]) == errors.EXIT_ERROR


@pytest.mark.parametrize("labels", [False, True])
def test_layout_size_matches_layout_rows(labels):
   if labels and not image.has_label_font():
      pytest.skip("딱지 글꼴이 없다")
   rows = [[image.new(5, 3), image.new(2, 7)], [image.new(9, 4)]]
   board = sheet.layout_rows(rows, ["a", "b"] if labels else None, ["x", "y"] if labels else None)
   sizes = [[image.size(c) for c in row] for row in rows]
   assert sheet.layout_size(sizes, labels, labels) == image.size(board)
   assert sheet.kind_size(3, 2, "tile", 4, 2) == (24, 16) and sheet.kind_size(3, 2, "zoom", 4) == (12, 8)
