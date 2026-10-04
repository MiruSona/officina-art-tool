"""곁가지 : 글꼴에 없는 글자 검사 `ui glyphs` (피드백 후속 설계 3-7).

글자마다 비트맵을 그려 **없는 글자 그림(notdef)과 같으면** 없는 글자로 본다. 공백이 아닌데 빈 비트맵이어도 없는 글자다.
notdef 는 유니코드 비문자(U+FFFF)로 얻는다 — 설계의 「사설 영역 글자」는 Pretendard 가 U+E000 · U+F0000 에 실제 글자를 둬서 못 쓴다.
ttf · otf 만 본다. TMP 폰트 에셋 · 비트맵 글꼴은 못 본다.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import numpy as np

from .. import image
from ..checks import warning
from ..errors import ArtToolError, UsageError
from .font import SKIP, read_text

VERSION = 1
NOTDEF_PROBE = "￿"          # 유니코드 비문자 — 어느 글꼴도 글자를 두지 않는다
SKIP_CATEGORIES = ("Cc", "Cf")   # 제어 · 서식 문자(폭 없는 이음 등)는 원래 안 그려진다


def load_font(path: str | Path, size: int):
   font_file = Path(path)
   if not font_file.is_file():
      raise ArtToolError(f"글꼴 파일이 없다 : {font_file}")
   try:
      return image.truetype(font_file, size)
   except OSError as exc:
      raise ArtToolError(f"글꼴을 못 읽었다 (ttf · otf 가 아니거나 깨졌다) : {font_file} - {exc}") from exc


def render(font, ch: str, size: int) -> np.ndarray:
   """글자 하나를 흑백 두 값으로 같은 자리에 그린 판. 판은 글자보다 넉넉하다."""
   return image.text_mask(font, ch, size * 4, size * 3, size, size // 2)


def wanted_chars(text: str) -> list[str]:
   """검사할 글자 — 처음 나온 차례로 한 번씩. 공백 · 줄바꿈 · 제어 문자는 뺀다."""
   seen: list[str] = []
   for ch in text:
      if ch in SKIP or ch.isspace() or unicodedata.category(ch) in SKIP_CATEGORIES:
         continue
      if ch not in seen:
         seen.append(ch)
   return seen


def find_missing(font, chars: list[str], size: int) -> tuple[list[str], bool]:
   """(없는 글자, notdef 가 빈 그림인가). notdef 가 비었으면 빈 비트맵 규칙만 쓴다."""
   notdef = render(font, NOTDEF_PROBE, size)
   notdef_blank = not notdef.any()
   missing = []
   for ch in chars:
      drawn = render(font, ch, size)
      if not drawn.any():
         missing.append(ch)
      elif not notdef_blank and np.array_equal(drawn, notdef):
         missing.append(ch)
   return missing, notdef_blank


def _source_text(args) -> tuple[str, str, list[dict]]:
   """(글자, 어디서 읽었나, 경고). --text · --text-file 은 하나만 준다."""
   text, text_file = args.text, args.text_file
   if (text is None) == (text_file is None):
      raise UsageError("--text 와 --text-file 중 하나만 준다")
   if text is not None:
      return str(text), "text", []
   path = Path(text_file)
   if not path.is_file():
      raise ArtToolError(f"글자 파일이 없다 : {path}")
   body, recovered = read_text(path)
   warnings = []
   if recovered:
      warnings.append(warning("glyphs.cp949", f"UTF-8 이 아니라 cp949 로 되살려 읽었다 : {path}", [str(path)]))
   return body, str(path), warnings


def run(args) -> dict:
   size = int(getattr(args, "size", 16))
   if size < 1:
      raise UsageError(f"--size 는 1 이상이다 : {size}")
   text, source, warnings = _source_text(args)
   font = load_font(args.font, size)
   chars = wanted_chars(text)

   missing, notdef_blank = find_missing(font, chars, size)
   if notdef_blank:
      warnings.append(warning("glyphs.notdef_blank",
                              "이 글꼴은 없는 글자 그림(notdef)이 비었다 — 빈 비트맵 규칙만 썼다", []))
   rows = [{"char": ch, "code": f"U+{ord(ch):04X}"} for ch in missing]
   if rows:
      warnings.append(warning("glyphs.missing",
                              f"글꼴에 없는 글자 {len(rows)}개 — 화면에 네모로 찍힌다",
                              [row["code"] for row in rows]))

   return {
      "version": VERSION,
      "status": "fail" if rows else ("warn" if warnings else "ok"),
      "font": str(args.font),
      "size": size,
      "source": source,
      "checked": len(chars),
      "missing": rows,
      "method": "empty_only" if notdef_blank else "notdef_compare",
      "warnings": warnings,
   }
