"""스킬 문서가 가리키는 명령 · 파일이 실제로 있는지 본다 (2026-10-04 개선 설계 6-4).

- `arttool …` 명령 줄 : 옵션(`--`)이 있고 빈칸(`…` · `[` · `<` · `|`)이 없는 줄은 cli 파서로 통째로 읽혀야 한다.
  그 밖의 줄은 앞의 명령 이름(하위 명령까지)만 본다.
- 문서가 가리키는 스크립트 · 조사 문서 · 템플릿 이름이 저장소에 있어야 한다.
"""

import re
from pathlib import Path

import pytest

from arttool import cli

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / ".claude" / "skills" / "arttool-usage"
DOCS = sorted(SKILL.glob("*.md"))
PLACEHOLDER = re.compile(r"…|\[|<|\||\\\|")
PREFIX = re.compile(r"^(?:<ArtTool>[\\/]\.venv[\\/]Scripts[\\/])?arttool\s+")


def _command_lines() -> list[tuple[str, str]]:
   """(문서 이름, 명령 줄). 인라인 코드와 코드 블록에서 `arttool ` 로 시작하는 줄."""
   found = []
   for doc in DOCS:
      text = doc.read_text(encoding="utf-8")
      spans = re.findall(r"`([^`\n]+)`", text)
      for block in re.findall(r"```[a-z]*\n(.*?)```", text, flags=re.S):
         spans.extend(block.splitlines())
      for span in spans:
         span = re.split(r"\s{2,}#", span.strip())[0].strip()   # 코드 블록 끝의 설명 주석
         if PREFIX.match(span):
            found.append((doc.name, PREFIX.sub("", span)))
   return found


LINES = _command_lines()


def test_docs_exist():
   names = {d.name for d in DOCS}
   assert {"SKILL.md", "기준.md", "뽑기-pixellab.md", "그리기-pil.md"} <= names
   head = (SKILL / "SKILL.md").read_text(encoding="utf-8").splitlines()
   assert head[0] == "---" and head[1] == "name: arttool-usage" and head[2].startswith("description: ")


def test_found_enough_lines():
   assert len(LINES) >= 30


def _parse(tokens: list[str]) -> int:
   try:
      cli.build_parser().parse_args(tokens)
   except SystemExit as stop:
      return int(stop.code or 0)
   return 0


@pytest.mark.parametrize("doc,line", LINES)
def test_command_line_parses(doc, line, capsys):
   tokens = line.replace("\\|", "|").split()
   if PLACEHOLDER.search(line) or not any(t.startswith("--") for t in tokens):
      # 빈칸이 있는 줄 · 옵션 없이 명령 이름만 든 글(「`arttool check` 는 …」) : 앞 낱말(명령 · 하위 명령)만 --help 로 본다
      head = []
      for tok in tokens:
         if tok.startswith("-") or PLACEHOLDER.search(tok):
            break
         head.append(tok)
      head = head[:2]
      code = _parse(head + ["--help"])
   else:
      code = _parse(tokens)
   capsys.readouterr()
   assert code == 0, f"{doc} : arttool {line}"


def test_referenced_files_exist():
   text = "\n".join(d.read_text(encoding="utf-8") for d in DOCS)
   for script in set(re.findall(r"(draw_\w+\.py)", text)):
      assert (SKILL / "scripts" / script).is_file(), script
   for research in set(re.findall(r"`(2026-\d\d-\d\d-[^`]+?\.md)`", text)):
      assert (ROOT / "Docs" / "Research" / research).is_file(), research
   assert (ROOT / "Docs" / "Guide" / "AI-그래픽-캐릭터-배경-가이드.html").is_file()
   templates = {p.stem for p in (ROOT / "templates").glob("*.json")}
   for name in set(re.findall(r"`(char_\w+|fx_\w+|tile_base|palette_ramp|cycle_char|motion_guide|bg_screen|icon_set|ui9_panel)`", text)):
      assert name in templates, name
