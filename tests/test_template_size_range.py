"""6판 T1 — 목록 밖 크기 받기(size_range) · T4 9-slice 56×54 · prop_small (2026-10-07)."""
import argparse
import hashlib
import json
from pathlib import Path

import pytest

from arttool.errors import UsageError
from arttool.profile import tool_home
from arttool.template import TemplateError, schema
from arttool.template import run

# HEAD(6판 전) 소스로 렌더한 출력의 sha256. 겹 PNG · layers.json · template.json · 보고를 묶고,
# 출력 폴더와 툴 폴더 경로는 <OUT> 로 가렸다. size_range 를 새로 단 템플릿도 목록 크기로는 바이트까지 같아야 한다.
OLD_DIGESTS = {
   ("ui9_panel", "54x34"): "12e2fdc6c0e3a5459b39c32541019589a0acffb50cf0e2bfbf9a018b4591467b",
   ("ui9_panel", None): "c9e91d5820cc7ae5d0166bfef5933d07d0a4299f45aafaca14cc0eeaf2cab6fd",
   ("building", "92x77"): "1c421e20f25a780fb2bff55107e5dfc68909c29ea60bc445c5c2bcfce453bf9e",
   ("tile_base", None): "608dfd500237059021cd93ace6db7516bc33237a6c05821ea7b15611b8c85bac",
   ("char_small", "32x32"): "9e59416da03674b75485c61f4cc7f8786a1769187bd9277834bb482f26da12da",
   ("bg_screen", "180x320"): "ad2520b60042466a904f397da2ccbfcbf9c5c791db16de69164b1caa8f382e91",
   ("screen_piece", "540x60"): "abd70804d067abdc7038f0f21cb2555118f6e6a02dd1ffd130389e69dd1cff7d",
}


def _render(name, size, out):
   ns = argparse.Namespace(sub="render", name=name, size=size, out_dir=str(out), preset=None, scale=None, over=None, profile=None)
   return run.run(ns)


def _digest(out: Path, report: dict) -> str:
   marks = [s for p in (out, tool_home().resolve())
            for s in (json.dumps(str(p))[1:-1].encode(), str(p).encode(), p.as_posix().encode())]
   h = hashlib.sha256()
   for path in sorted(p for p in out.rglob("*") if p.is_file()):
      data = path.read_bytes()
      for m in marks:
         data = data.replace(m, b"<OUT>")
      h.update(path.relative_to(out).as_posix().encode() + b"\0" + data)
   text = json.dumps(report, sort_keys=True, ensure_ascii=False).encode()
   for m in marks:
      text = text.replace(m, b"<OUT>")
   h.update(text)
   return h.hexdigest()


@pytest.mark.parametrize("name,size", list(OLD_DIGESTS))
def test_listed_size_render_is_byte_identical(tmp_path, name, size):
   out = tmp_path / "out"
   assert _digest(out, _render(name, size, out)) == OLD_DIGESTS[(name, size)]


def _rules(report):
   return [w["rule"] for w in report.get("warnings", [])]


def test_free_size_inside_range_renders_with_warning(tmp_path):
   out = tmp_path / "out"
   report = _render("building", "176x123", out)
   free = [w for w in report["warnings"] if w["rule"] == "template.size_free"]
   assert len(free) == 1
   assert "176x123 은 목록 밖 크기다" in free[0]["detail"]
   assert "가장 가까운 목록 크기 : 135x144" in free[0]["detail"]
   assert json.loads((out / "template.json").read_text(encoding="utf-8"))["size"] == [176, 123]


def test_ui9_56x54(tmp_path):
   # 프리셋이 자기 크기 목록을 가져도 맨 위 size_range 는 듣는다 — 받고 template.size_free 경고
   out = tmp_path / "out"
   report = _render("ui9_panel", "56x54", out)
   free = [w for w in report["warnings"] if w["rule"] == "template.size_free"]
   assert len(free) == 1
   assert "56x54 은 이 프리셋(panel)의 정해진 크기가 아니다" in free[0]["detail"]
   assert json.loads((out / "template.json").read_text(encoding="utf-8"))["size"] == [56, 54]


def test_outside_range_is_usage_error(tmp_path):
   with pytest.raises(UsageError, match="16x16 ~ 512x512 사이"):
      _render("building", "600x100", tmp_path / "out")


def test_no_range_keeps_old_refusal(tmp_path):
   with pytest.raises(UsageError, match="받는 크기가 아니다") as info:
      _render("tile_base", "33x33", tmp_path / "out")
   assert "사이" not in str(info.value)


def _copy_template(tmp_path, name, **change) -> Path:
   data = json.loads((tool_home() / "templates" / f"{name}.json").read_text(encoding="utf-8"))
   data.update(change)
   path = tmp_path / f"{name}.json"
   path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
   return path


def test_value_misfit_becomes_usage_error(tmp_path):
   # 테두리 4px 가 3x3 에 안 들어간다 — 템플릿 탓이 아니라 사람이 준 크기 탓이라 종료 2
   path = _copy_template(tmp_path, "ui9_panel", size_range=[[1, 1], [256, 256]])
   with pytest.raises(UsageError, match="이 크기에서는 안 맞는다 : 3x3"):
      _render(str(path), "3x3", tmp_path / "out")


@pytest.mark.parametrize("bad", [
   [[16, 16]], [[16, 16], [8, 8]], [[0, 16], [32, 32]], [[-1, 16], [32, 32]], [[True, 16], [32, 32]],
   [[16.0, 16], [32, 32]], [["16", 16], [32, 32]], [[16, 16], [32, 4097]], [[16, 16], [32, 10**12]],
   "16x16", None, [[16, 16, 1], [32, 32]], [[16, 16], [32, 32], [64, 64]],
])
def test_bad_size_range_is_template_error(tmp_path, bad):
   path = _copy_template(tmp_path, "building", size_range=bad)
   with pytest.raises(TemplateError):
      schema.load(str(path))


def _show(name, size=None):
   ns = argparse.Namespace(sub="show", name=name, size=size, preset=None, profile=None)
   return run.run(ns)


def test_show_range_line():
   shown = _show("screen_piece")
   assert shown["size_line"] == "크기 : 540x60, 540x145, 540x360, 540x720 · 범위 540x60 ~ 540x720"
   assert shown["size_range"] == [[540, 60], [540, 720]]
   # 범위를 안 쓴 템플릿의 show 는 칸이 늘지 않는다
   plain = _show("tile_base")
   assert "size_line" not in plain and "size_range" not in plain


@pytest.mark.parametrize("name,size", [
   ("char_small", "241x241"), ("bg_screen", "179x400"), ("screen_piece", "541x100"),
])
def test_new_ranges_refuse_outside(tmp_path, name, size):
   with pytest.raises(UsageError, match="사이"):
      _render(name, size, tmp_path / "out")


@pytest.mark.parametrize("name,size", [
   ("char_small", "9x9"), ("char_small", "240x240"), ("char_small", "33x47"),
   ("bg_screen", "181x181"), ("screen_piece", "540x61"),
])
def test_new_ranges_edges_and_odd(tmp_path, name, size):
   report = _render(name, size, tmp_path / "out")
   assert "template.size_free" in _rules(report)


def test_prop_small_listed_and_free(tmp_path):
   for size in ("24x24", "64x64", "40x30"):
      _render("prop_small", size, tmp_path / size)
   assert "size_range" in next(t for t in run.list_templates(None)["templates"] if t["name"] == "prop_small")
