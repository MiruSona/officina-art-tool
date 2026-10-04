"""`ui glyphs` 시험 (피드백 후속 설계 3-7). 글꼴은 툴 안 Pretendard 를 쓴다.

Pretendard 에는 「—」(U+2014) 가 있다. 없는 글자 보기로는 눈사람 「☃」(U+2603) 와 한자 「漢」 을 쓴다.
"""

from __future__ import annotations

from argparse import Namespace

import pytest

from arttool import errors, image
from arttool.ui import glyphs

pytestmark = pytest.mark.skipif(not image.has_label_font(), reason="시험 글꼴(Pretendard)이 없다")


def _args(**extra) -> Namespace:
   values = {"font": str(image.LABEL_FONT), "text": None, "text_file": None, "size": 16, "report": None}
   values.update(extra)
   return Namespace(**values)


def test_glyphs_all_present_ok():
   result = glyphs.run(_args(text="가나다 ABC 123 —…·"))
   assert result["status"] == "ok"
   assert result["missing"] == []
   assert result["method"] == "notdef_compare"
   assert result["checked"] == len(set("가나다ABC123—…·"))


def test_glyphs_missing_dash_fails():
   """설계의 「—」 자리를 이 글꼴에 없는 글자로 바꿔 본다 (「—」 는 있다고 같이 확인)."""
   result = glyphs.run(_args(text="가—☃漢"))
   assert result["status"] == "fail"
   assert result["missing"] == [{"char": "☃", "code": "U+2603"}, {"char": "漢", "code": "U+6F22"}]


def test_glyphs_skips_spaces():
   result = glyphs.run(_args(text="가 　\t\n가"))
   assert result["checked"] == 1
   assert result["status"] == "ok"


def test_glyphs_text_file_bom(tmp_path):
   path = tmp_path / "charset.txt"
   path.write_bytes("﻿가나☃\n".encode("utf-8"))
   result = glyphs.run(_args(text_file=str(path)))
   assert result["checked"] == 3
   assert [m["char"] for m in result["missing"]] == ["☃"]


def test_glyphs_text_file_cp949_warns(tmp_path):
   path = tmp_path / "charset.txt"
   path.write_bytes("가나".encode("cp949"))
   result = glyphs.run(_args(text_file=str(path)))
   assert result["checked"] == 2
   assert "glyphs.cp949" in [w["rule"] for w in result["warnings"]]


def test_glyphs_needs_one_source_exit2():
   with pytest.raises(errors.UsageError):
      glyphs.run(_args())
   with pytest.raises(errors.UsageError):
      glyphs.run(_args(text="가", text_file="x.txt"))


def test_glyphs_bad_font_exit1(tmp_path):
   broken = tmp_path / "broken.ttf"
   broken.write_bytes(b"not a font")
   for font in (str(broken), str(tmp_path / "none.ttf")):
      with pytest.raises(errors.ArtToolError) as caught:
         glyphs.run(_args(font=font, text="가"))
      assert not isinstance(caught.value, errors.UsageError)
