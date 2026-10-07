"""`sheet --compare <폴더>` (7판-다-3 · P4) : 같은 이름 짝과 숫자만 견준다. 그림은 모두 코드로 만든다."""

import argparse

import numpy as np
import pytest

from arttool import cli, errors, image, sheet
from arttool.errors import UsageError
from arttool.jsonio import read_json


def _ns(ins, out, **over):
   values = {"in_paths": [str(p) for p in ins], "out_file": str(out), "kinds": None, "scale": None, "tile": 2, "bg": "checker",
             "label": False, "grid": 0, "grid_color": None, "strip": False, "report": None, "dry_run": False}
   values.update(over)
   return argparse.Namespace(**values)


def _before_after(tmp_path):
   """after/a.png · after/b.png 와 before/a.png (b 는 짝 없음). before 의 a 는 색 하나 · 외톨이 하나가 더 있다."""
   after, before = tmp_path / "after", tmp_path / "before"
   after.mkdir()
   before.mkdir()
   a_new = image.new(8, 8, (200, 40, 40, 255))
   a_old = a_new.copy()
   a_old[0:2, 0:2] = (20, 200, 20, 255)
   image.save(after / "a.png", a_new)
   image.save(after / "b.png", image.new(6, 6, (0, 0, 255, 255)))
   image.save(before / "a.png", a_old)
   return after, before


def test_compare_numbers_before_after_diff(tmp_path):
   after, before = _before_after(tmp_path)
   result = sheet.run(_ns([after / "a.png"], tmp_path / "s.png", compare=str(before)))
   old = sheet.measure(image.load(before / "a.png"))
   new = sheet.measure(image.load(after / "a.png"))
   (row,) = result["compare"]
   assert row["name"] == "a.png"
   assert row["colors"] == [old["colors"], new["colors"], new["colors"] - old["colors"]] == [2, 1, -1]
   assert row["isolated"] == [old["isolated"], new["isolated"], new["isolated"] - old["isolated"]]
   assert row["outline_ratio"][:2] == [old["outline_ratio"], new["outline_ratio"]]
   assert row["outline_ratio"][2] == pytest.approx(new["outline_ratio"] - old["outline_ratio"])
   assert not any(w["rule"] == "compare_missing" for w in result["warnings"])


def test_compare_missing_pair_warns(tmp_path):
   after, before = _before_after(tmp_path)
   result = sheet.run(_ns([after], tmp_path / "s.png", compare=str(before)))
   assert [row["name"] for row in result["compare"]] == ["a.png"]
   (warn,) = [w for w in result["warnings"] if w["rule"] == "compare_missing"]
   assert warn["items"] == ["b.png"]


def test_compare_does_not_change_sheet_picture(tmp_path):
   after, before = _before_after(tmp_path)
   sheet.run(_ns([after], tmp_path / "1.png"))
   sheet.run(_ns([after], tmp_path / "2.png", compare=str(before)))
   assert (tmp_path / "1.png").read_bytes() == (tmp_path / "2.png").read_bytes()


def test_without_compare_report_is_same(tmp_path):
   after, _ = _before_after(tmp_path)
   one = sheet.run(_ns([after], tmp_path / "1.png"))
   two = sheet.run(_ns([after], tmp_path / "1.png", compare=None))
   assert one == two and "compare" not in one


def test_compare_cli_report(tmp_path):
   after, before = _before_after(tmp_path)
   rep = tmp_path / "r.json"
   code = cli.main(["sheet", "--in", str(after / "a.png"), "--out", str(tmp_path / "s.png"),
                    "--compare", str(before), "--report", str(rep)])
   assert code == errors.EXIT_OK
   assert read_json(rep)["compare"][0]["colors"] == [2, 1, -1]


def test_compare_dry_run_reports_without_writing(tmp_path):
   after, before = _before_after(tmp_path)
   result = sheet.run(_ns([after / "a.png"], tmp_path / "s.png", compare=str(before), dry_run=True))
   assert result["compare"][0]["colors"] == [2, 1, -1]
   assert not (tmp_path / "s.png").exists()


def test_compare_out_inside_compare_pair_refused(tmp_path):
   """--out 이 짝 그림(--compare 폴더 안 같은 이름)을 덮으면 거절하고 짝은 그대로."""
   after, before = _before_after(tmp_path)
   target = before / "a.png"
   was = target.read_bytes()
   with pytest.raises(UsageError):
      sheet.run(_ns([after / "a.png"], target, compare=str(before)))
   assert target.read_bytes() == was


def test_compare_folder_must_exist(tmp_path):
   after, _ = _before_after(tmp_path)
   with pytest.raises(errors.ArtToolError):
      sheet.run(_ns([after / "a.png"], tmp_path / "s.png", compare=str(tmp_path / "없음")))


def test_compare_with_strip_refused(tmp_path):
   after, before = _before_after(tmp_path)
   with pytest.raises(UsageError):
      sheet.run(_ns([after / "a.png"], tmp_path / "s.png", strip=True, compare=str(before)))
