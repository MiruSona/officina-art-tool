"""`arttool intake` 시험 — cutout → trim → check → sheet 한 번에. 그림은 코드로 만든 합성 그림이다."""

from __future__ import annotations

import hashlib

import numpy as np

from arttool import cli, image
from arttool.jsonio import read_json

WHITE = (255, 255, 255, 255)


def white_sprite(w=40, h=40, box=(10, 8, 26, 30), seed=0) -> np.ndarray:
   """흰 바탕 가운데 색 넷짜리 몸통."""
   arr = np.zeros((h, w, 4), dtype=np.uint8)
   arr[:] = WHITE
   x0, y0, x1, y1 = box
   colors = np.array([(200, 60, 50, 255), (60, 140, 200, 255), (40, 40, 60, 255), (240, 200, 120, 255)], dtype=np.uint8)
   pick = np.random.default_rng(seed).integers(0, 4, size=(y1 - y0, x1 - x0))
   arr[y0:y1, x0:x1] = colors[pick]
   return arr


def digest(folder) -> dict:
   return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir())}


def run(tmp_path, *more, raw=None):
   raw = raw or tmp_path / "raw"
   rep = tmp_path / "intake.json"
   code = cli.main(["intake", "--in", str(raw), "--out", str(tmp_path / "clean"), "--report", str(rep), *more])
   return code, (read_json(rep) if rep.is_file() else None)


def make_raw(tmp_path, *arrs):
   raw = tmp_path / "raw"
   raw.mkdir()
   for i, arr in enumerate(arrs):
      image.save(raw / f"hero{i}.png", arr)
   return raw


def test_full_chain_cuts_trims_checks_and_sheets(tmp_path):
   raw = make_raw(tmp_path, white_sprite(), white_sprite(box=(4, 4, 20, 36), seed=1))
   before = digest(raw)
   code, rep = run(tmp_path, "--sheet", str(tmp_path / "sheet.png"), "--pad", "1")
   assert code == 0
   assert rep["ran"] == ["cutout", "trim", "check", "sheet"] and rep["failed_step"] is None
   assert digest(raw) == before                                # 원본은 그대로
   out0 = image.load(tmp_path / "clean" / "hero0.png")
   assert image.size(out0) == (16 + 2, 22 + 2)                 # 몸통 16×22 + pad 1
   assert out0[0, 0, 3] == 0 and out0[1, 1, 3] == 255          # 흰 바탕이 지워지고 둘레 1칸 투명
   assert rep["steps"]["trim"]["images"][0]["offset"] == [9, 7]
   assert rep["steps"]["check"]["status"] in ("ok", "warn")
   assert (tmp_path / "sheet.png").is_file() and rep["steps"]["sheet"]["label"] in (True, False)
   assert [w["file"] for w in rep["images"]] == ["hero0.png", "hero1.png"]


def test_steps_can_be_skipped(tmp_path):
   make_raw(tmp_path, white_sprite())
   code, rep = run(tmp_path, "--no-cutout", "--no-trim", "--no-check")
   assert code == 0
   assert rep["ran"] == [] and rep["skipped"] == ["cutout", "trim", "check", "sheet"]
   assert (image.load(tmp_path / "clean" / "hero0.png") == white_sprite()).all()   # 손 안 대고 옮기기만


def test_cutout_failure_stops_there(tmp_path):
   blank = np.zeros((16, 16, 4), dtype=np.uint8)
   blank[:] = WHITE                                            # 다 바탕이라 다 지워진다
   make_raw(tmp_path, white_sprite(), blank)
   code, rep = run(tmp_path, "--sheet", str(tmp_path / "sheet.png"))
   assert code == 4
   assert rep["status"] == "fail" and rep["failed_step"] == "cutout"
   assert rep["not_reached"] == ["trim", "check", "sheet"]
   assert not (tmp_path / "clean").exists() or not any((tmp_path / "clean").iterdir())
   assert not (tmp_path / "sheet.png").exists()


def noisy_on_white() -> np.ndarray:
   arr = np.zeros((40, 40, 4), dtype=np.uint8)
   arr[:] = WHITE
   rng = np.random.default_rng(3)
   arr[5:35, 5:35, :3] = rng.integers(0, 200, size=(30, 30, 3))    # 색이 수백 개 → max_colors 실패
   return arr


def test_check_failure_still_makes_sheet(tmp_path):
   """검수에 걸려도 비교판은 만든다 — 걸린 그림을 눈으로 봐야 하니까. 실패 표시 · 종료 4 는 그대로."""
   make_raw(tmp_path, noisy_on_white())
   code, rep = run(tmp_path, "--sheet", str(tmp_path / "sheet.png"))
   assert code == 4 and rep["status"] == "fail" and rep["failed_step"] == "check"
   assert rep["steps"]["check"]["status"] == "fail"
   assert (tmp_path / "clean" / "hero0.png").is_file()              # 손질한 그림은 남는다
   assert (tmp_path / "sheet.png").is_file()                        # 비교판도 만든다
   assert rep["ran"] == ["cutout", "trim", "check", "sheet"] and rep["not_reached"] == []
   assert [i["name"] for i in rep["steps"]["sheet"]["items"]] == ["hero0.png"]


def test_check_failure_without_sheet_flag_makes_no_sheet(tmp_path):
   make_raw(tmp_path, noisy_on_white())
   code, rep = run(tmp_path)
   assert code == 4 and rep["failed_step"] == "check"
   assert "sheet" in rep["skipped"] and "sheet" not in rep["steps"]


def test_template_goes_to_check(tmp_path):
   tpl = tmp_path / "tpl"
   assert cli.main(["template", "render", "char_small", "--size", "32", "--out", str(tpl)]) == 0
   make_raw(tmp_path, white_sprite())
   code, rep = run(tmp_path, "--template", str(tpl / "template.json"))
   assert code in (0, 4)
   assert rep["steps"]["check"]["template"]["name"] == "char_small"


def textured_background(w=200, h=160, seed=4) -> np.ndarray:
   """실물 버그 2 합성 그림 : 불투명, 밝기 230 근처 바탕에 ±10 잡무늬."""
   rng = np.random.default_rng(seed)
   arr = np.zeros((h, w, 4), dtype=np.uint8)
   arr[:, :, :3] = np.clip(230 + rng.integers(-10, 11, size=(h, w, 1)), 0, 255)
   arr[:, :, 3] = 255
   return arr


def test_opaque_background_skips_cutout(tmp_path):
   """불투명한 큰 배경은 바탕을 안 지우고 그대로 둔다 (실물 #22 / 버그 2)."""
   bg = textured_background()
   make_raw(tmp_path, bg, white_sprite())
   code, rep = run(tmp_path, "--no-check")
   assert code == 0
   rows = rep["steps"]["cutout"]["images"]
   assert rows[0]["kept_background"] is True and rows[1]["kept_background"] is False
   assert (image.load(tmp_path / "clean" / "hero0.png") == bg).all()           # 구멍 없이 그대로
   kept = [w for w in rep["warnings"] if w["rule"] == "cutout.background_kept"]
   assert kept and kept[0]["step"] == "cutout" and kept[0]["items"] == ["hero0.png"]
   assert image.size(image.load(tmp_path / "clean" / "hero1.png")) == (16, 22)   # 보통 그림은 그대로 지우고 자른다


def test_large_white_band_picture_is_still_cut(tmp_path):
   """흰 띠 · 단색 바탕 위 물건은 크고 불투명해도 배경이 아니다 — 지운 뒤 남은 칸이 변에 안 닿는다."""
   big = white_sprite(200, 200, box=(40, 30, 160, 170))
   make_raw(tmp_path, big)
   code, rep = run(tmp_path, "--no-check")
   assert code == 0 and rep["steps"]["cutout"]["images"][0]["kept_background"] is False
   assert image.size(image.load(tmp_path / "clean" / "hero0.png")) == (120, 140)


def test_top_warnings_have_step_and_check_shape(tmp_path):
   blank_row = white_sprite()
   make_raw(tmp_path, blank_row)
   code, rep = run(tmp_path, "--no-check", "--key", "#000000")     # 없는 색 → 지울 게 없어 바깥 변에 칸이 남는다
   assert rep["warnings"], rep
   for w in rep["warnings"]:
      assert set(w) == {"rule", "ok", "detail", "items", "step"} and w["ok"] is False


def test_rerun_checks_only_files_written_now(tmp_path):
   """--out 에 지난 판 PNG 가 있어도 이번에 쓴 것만 검수 · 비교판에 넣는다 (R1-L2)."""
   (tmp_path / "clean").mkdir()
   noisy = np.random.default_rng(9).integers(0, 255, size=(30, 30, 4), dtype=np.uint8)
   noisy[:, :, 3] = 255
   image.save(tmp_path / "clean" / "old.png", noisy)                  # 검수하면 색 수로 실패할 그림
   make_raw(tmp_path, white_sprite())
   code, rep = run(tmp_path, "--sheet", str(tmp_path / "sheet.png"))
   assert code == 0, rep["warnings"]
   assert rep["steps"]["check"]["checked_files"] == ["hero0.png"]
   assert rep["steps"]["check"]["not_checked"] == ["old.png"]
   assert [i["name"] for i in rep["steps"]["sheet"]["items"]] == ["hero0.png"]


def test_sheet_inside_out_or_on_input_is_refused(tmp_path):
   raw = make_raw(tmp_path, white_sprite())
   before = digest(raw)
   code, rep = run(tmp_path, "--sheet", str(tmp_path / "clean" / "sheet.png"))
   assert code == 2 and rep is None
   code, _ = run(tmp_path, "--sheet", str(raw / "hero0.png"))
   assert code == 2 and digest(raw) == before
   assert not (tmp_path / "clean").exists()


def test_bad_args_are_usage_errors(tmp_path):
   raw = make_raw(tmp_path, white_sprite())
   assert cli.main(["intake", "--in", str(raw), "--out", str(tmp_path / "a.png")]) == 2
   assert cli.main(["intake", "--in", str(raw), "--out", str(raw)]) == 2       # 원본 폴더에 쓰지 않는다
   assert cli.main(["intake", "--in", str(raw), "--out", str(tmp_path / "c"), "--tol", "999"]) == 2
