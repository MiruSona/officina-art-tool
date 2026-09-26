"""recolor — 그림은 전부 코드로 만든다. 설계 5-1 표의 recolor 줄을 하나씩 박는다."""

from __future__ import annotations

import json

import numpy as np
import pytest

from arttool import cli, image
from arttool.errors import ArtToolError, PathJailError, UsageError
from arttool.sprite import recolor

OUT = (3, 2, 2)
OUT_NEAR = (3, 3, 2)     # 먹색과 1단 차이
OUT_FAR = (6, 2, 2)      # 3단 차이 — 안 바꾼다
HAIR = (51, 46, 43)
HAIR_LIGHT = (88, 83, 79)
HAIR_GLOSS = (146, 131, 108)
SKIN = (254, 234, 205)

FAMILIES = {
   "hair": {
      "black": {"base": "#332E2B", "light": "#58534F"},
      "brown": {"base": "#7A4E2C", "light": "#9E6C43"},
   }
}


def hair_layer():
   """6×4 머리카락 겹. 윗줄 먹색 · 몸통 기본색 · 광택 두 단 · 반투명 한 칸."""
   arr = image.new(6, 4)
   arr[0, :] = (*OUT, 255)
   arr[1:, :] = (*HAIR, 255)
   arr[1, 1] = (*HAIR_LIGHT, 255)
   arr[1, 2] = (*HAIR_GLOSS, 255)
   arr[3, 5] = (*HAIR, 128)
   return arr


def body_layer():
   arr = image.new(6, 4)
   arr[1:, 1:5] = (*SKIN, 255)
   arr[0, 1] = (*OUT_NEAR, 255)
   arr[0, 2] = (*OUT_FAR, 255)
   return arr


def hair_job(**extra):
   job = {
      "src": "hair/c.png",
      "family": "hair",
      "out": "hair_{v}.png",
      "roles": {"#332E2B": "base", "#58534F": "light", "#92836C": "light"},
   }
   job.update(extra)
   return job


def spec(jobs=None, **extra):
   data = {"version": 1, "outline": "#030202", "families": FAMILIES, "jobs": jobs or [hair_job()]}
   data.update(extra)
   return data


def setup_case(tmp_path, data):
   image.save(tmp_path / "in" / "hair" / "c.png", hair_layer())
   image.save(tmp_path / "in" / "body" / "c.png", body_layer())
   (tmp_path / "recolor.json").write_text(json.dumps(data), encoding="utf-8")
   return tmp_path / "in", tmp_path / "recolor.json"


def run_case(tmp_path, data, **kw):
   in_dir, spec_file = setup_case(tmp_path, data)
   return recolor.run(in_dir, spec_file, tmp_path / "out", **kw)


def test_one_to_one_replace(tmp_path):
   report = run_case(tmp_path, spec())
   brown = image.load(tmp_path / "out" / "hair_brown.png")
   assert tuple(brown[2, 0]) == (0x7A, 0x4E, 0x2C, 255)
   assert tuple(brown[1, 1]) == (0x9E, 0x6C, 0x43, 255)
   assert tuple(brown[0, 0]) == (*OUT, 255)
   assert [r["out"] for r in report["outputs"]] == ["hair_black.png", "hair_brown.png"]


def test_alpha_kept(tmp_path):
   run_case(tmp_path, spec())
   brown = image.load(tmp_path / "out" / "hair_brown.png")
   assert tuple(brown[3, 5]) == (0x7A, 0x4E, 0x2C, 128)
   src = hair_layer()
   assert np.array_equal(brown[:, :, 3], src[:, :, 3])


def test_same_colors_are_byte_identical(tmp_path):
   job = hair_job(roles={"#332E2B": "base", "#58534F": "light"})
   run_case(tmp_path, spec([job]))
   black = image.load(tmp_path / "out" / "hair_black.png")
   src = hair_layer()
   assert np.array_equal(black, src)


def test_many_source_colors_to_one_role(tmp_path):
   run_case(tmp_path, spec())
   brown = image.load(tmp_path / "out" / "hair_brown.png")
   assert tuple(brown[1, 1]) == tuple(brown[1, 2])   # 광택 두 단이 한 역할로


def test_swap_does_not_chain():
   arr = image.new(2, 1)
   arr[0, 0] = (1, 1, 1, 255)
   arr[0, 1] = (2, 2, 2, 255)
   out = image.replace_colors(arr, {(1, 1, 1): (2, 2, 2), (2, 2, 2): (1, 1, 1)})
   assert tuple(out[0, 0]) == (2, 2, 2, 255)
   assert tuple(out[0, 1]) == (1, 1, 1, 255)


def test_outline_unify_within_two(tmp_path):
   jobs = [hair_job(), {"src": "body/c.png", "out": "body.png"}]
   report = run_case(tmp_path, spec(jobs))
   body = image.load(tmp_path / "out" / "body.png")
   assert tuple(body[0, 1]) == (*OUT, 255)
   assert tuple(body[0, 2]) == (*OUT_FAR, 255)
   row = next(r for r in report["outputs"] if r["out"] == "body.png")
   assert row["outline_fixed"] == ["#030302"]
   assert row["unmapped_colors"] == []   # family 없는 줄은 그대로 복사가 뜻이다


def test_unmapped_color_reported(tmp_path):
   job = hair_job(roles={"#332E2B": "base", "#58534F": "light"})
   report = run_case(tmp_path, spec([job]))
   assert report["status"] == "warn"
   assert report["outputs"][1]["unmapped_colors"] == ["#92836C"]
   brown = image.load(tmp_path / "out" / "hair_brown.png")
   assert tuple(brown[1, 2]) == (*HAIR_GLOSS, 255)   # 안 바꾸고 둔다


def test_position_diff_zero(tmp_path):
   jobs = [hair_job(), {"src": "body/c.png", "out": "body.png"}]
   report = run_case(tmp_path, spec(jobs))
   assert report["status"] == "ok"
   assert all(r["position_diff"] == 0 for r in report["outputs"])
   assert recolor.position_diff(hair_layer(), image.new(6, 4)) == 24


def test_out_with_dotdot_rejected(tmp_path):
   with pytest.raises(PathJailError):
      run_case(tmp_path, spec([hair_job(out="../hair_{v}.png")]))


def test_src_with_dotdot_rejected(tmp_path):
   with pytest.raises(PathJailError):
      run_case(tmp_path, spec([hair_job(src="../secret.png")]))


def test_out_without_variant_mark_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="덮어쓴다"):
      run_case(tmp_path, spec([hair_job(out="hair.png")]))


def test_duplicate_output_rejected(tmp_path):
   jobs = [{"src": "body/c.png", "out": "x.png"}, {"src": "hair/c.png", "out": "x.png"}]
   with pytest.raises(ArtToolError, match="두 번"):
      run_case(tmp_path, spec(jobs))
   assert not (tmp_path / "out" / "x.png").exists()


def test_missing_role_in_variant_rejected(tmp_path):
   fams = {"hair": {"black": {"base": "#332E2B"}}}
   with pytest.raises(ArtToolError, match="역할이 없다"):
      run_case(tmp_path, spec(families=fams))


def test_drop_pieces_opt_in(tmp_path):
   in_dir, spec_file = setup_case(tmp_path, spec([{"src": "hair/c.png", "out": "h.png", "drop_pieces": 3}]))
   arr = image.new(8, 4)
   arr[0:3, 0:3] = (*HAIR, 255)
   arr[3, 7] = (*HAIR, 255)
   image.save(in_dir / "hair" / "c.png", arr)
   report = recolor.run(in_dir, spec_file, tmp_path / "out")
   assert report["outputs"][0]["pieces_dropped"] == [[7, 3]]
   assert image.load(tmp_path / "out" / "h.png")[3, 7, 3] == 0


def test_sheet_size(tmp_path):
   jobs = [hair_job(), {"src": "body/c.png", "out": "body.png"}]
   data = spec(jobs, combos=[["body.png", "hair_black.png"]])
   report = run_case(tmp_path, data, sheet=tmp_path / "sheet.png", scale=2)
   assert report["combos"] == 1
   sheet = image.load(tmp_path / "sheet.png")
   # 넷(구운 셋 + 조합 하나)이 한 줄, 칸 12×8, 사이 2
   assert image.size(sheet) == (4 * 12 + 3 * 2, 8)


def test_contact_sheet_wraps_rows():
   items = [image.new(4, 4, (9, 9, 9, 255)) for _ in range(3)]
   sheet = image.contact_sheet(items, scale=2, cols=2, gap=2)
   assert image.size(sheet) == (18, 18)
   assert tuple(sheet[10, 0]) == (9, 9, 9, 255)
   assert sheet[10, 10, 3] == 0


def test_combo_unknown_name_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="구운 적 없는"):
      run_case(tmp_path, spec(combos=[["nope.png"]]))


def test_scale_without_sheet_rejected(tmp_path):
   with pytest.raises(UsageError):
      run_case(tmp_path, spec(), scale=2)


def test_cli_recolor(tmp_path, capsys):
   in_dir, spec_file = setup_case(tmp_path, spec())
   code = cli.main(["recolor", "--in", str(in_dir), "--spec", str(spec_file), "--out", str(tmp_path / "out"), "--json"])
   assert code == 0
   assert json.loads(capsys.readouterr().out)["status"] == "ok"
   assert (tmp_path / "out" / "recolor_report.json").is_file()


# --- 리뷰 뒤 더한 시험 ---


def test_output_names_differing_by_case_rejected(tmp_path):
   jobs = [{"src": "body/c.png", "out": "X.png"}, {"src": "hair/c.png", "out": "x.png"}]
   with pytest.raises(ArtToolError, match="두 번"):
      run_case(tmp_path, spec(jobs))
   assert not (tmp_path / "out").exists()


def test_output_over_source_rejected(tmp_path):
   in_dir, spec_file = setup_case(tmp_path, spec([{"src": "body/c.png", "out": "body/C.png"}]))
   before = (in_dir / "body" / "c.png").read_bytes()
   with pytest.raises(ArtToolError, match="밑감 원본"):
      recolor.run(in_dir, spec_file, in_dir)
   assert (in_dir / "body" / "c.png").read_bytes() == before


def test_output_named_like_report_rejected(tmp_path):
   with pytest.raises(ArtToolError, match="보고 파일"):
      run_case(tmp_path, spec([{"src": "body/c.png", "out": "Recolor_Report.json"}]))


def test_role_color_absent_from_image_warns(tmp_path):
   roles = {"#332E2B": "base", "#58534F": "light", "#92836C": "light", "#010101": "base"}
   report = run_case(tmp_path, spec([hair_job(roles=roles)]))
   assert report["status"] == "warn"
   assert report["outputs"][0]["roles_absent"] == ["#010101"]
   assert any("그림에 없는 색" in w for w in report["warnings"])


def test_role_hex_differing_by_case_rejected(tmp_path):
   roles = {"#332E2B": "base", "#332e2b": "light"}
   with pytest.raises(ArtToolError, match="같은 색이 두 번"):
      run_case(tmp_path, spec([hair_job(roles=roles)]))
