"""화풍 뽑기의 결과 꼴 — 프로필 조각 YAML 글 · 견본 PNG (설계 9-2).

조각 YAML 은 값마다 「몇 장 중 몇 장」 주석을 다느라 PyYAML 로 안 쓰고 손으로 짠다.
그래서 짠 글을 바로 다시 읽어 뜻이 같은지 본다(`fragment_text`).
"""

from __future__ import annotations

import json
import re

import numpy as np
import yaml

from .. import image
from ..errors import ArtToolError
from .ramps import to_rgb

HEADER = "# arttool style extract 가 뽑은 조각 — 보고 고쳐서 프로필에 붙인다. 자동으로 안 붙는다"
PLAIN = re.compile(r"[a-z][a-z_+]*")
YAML_WORDS = {"true", "false", "null", "yes", "no", "on", "off", "y", "n", "none"}

CELL = 16               # 견본 색 칸 한 변 (× 배율). 8 이면 램프 여럿이 64 × 116 처럼 작아 읽기 어렵다 (실물 #8)
MIN_COLS = 8            # 버린 색 줄은 이 칸 수(또는 램프 길이)에서 꺾는다


# --- 조각 YAML ---


def _scalar(value) -> str:
   if value is None:
      return "null"
   if isinstance(value, bool):
      return "true" if value else "false"
   if isinstance(value, (int, float)):
      return repr(value)
   if isinstance(value, dict):
      return "{ " + ", ".join(f"{k}: {_scalar(v)}" for k, v in value.items()) + " }"
   text = str(value)
   if PLAIN.fullmatch(text) and text not in YAML_WORDS:
      return text
   return json.dumps(text, ensure_ascii=False)


def _tree(entries: list[tuple[tuple[str, ...], object, str]]) -> dict:
   root: dict = {}
   for path, value, note in entries:
      node = root
      for part in path[:-1]:
         node = node.setdefault(part, {})
      node[path[-1]] = (value, note)
   return root


def _emit(node: dict, depth: int, notes: dict[str, list[str]], lines: list[str], where: str = "") -> None:
   pad = "  " * depth
   for key, child in node.items():
      here = f"{where}.{key}" if where else key
      if isinstance(child, dict):
         lines.append(f"{pad}{key}:")
         lines.extend(f"{pad}  # {text}" for text in notes.get(here, []))
         _emit(child, depth + 1, notes, lines, here)
         continue
      value, note = child
      tail = f"   # {note}" if note else ""
      lines.append(f"{pad}{key}: {_scalar(value)}{tail}")


def _plain(node: dict) -> dict:
   return {k: _plain(v) if isinstance(v, dict) else v[0] for k, v in node.items()}


def fragment_text(entries: list[tuple[tuple[str, ...], object, str]], head: list[str], notes: dict[str, list[str]]) -> str:
   """조각 YAML 글. entries = [(점 경로 칸들, 값, 주석)], head = 맨 위 주석 줄, notes = {절 이름 : 그 절 안 주석 줄}.

   값이 없는 절의 주석은 맨 끝에 「# 절 : …」 꼴로 모은다. 짠 글을 다시 읽어 entries 와 뜻이 다르면 ArtToolError.
   """
   tree = _tree(entries)
   lines = [HEADER] + [f"# {text}" for text in head]
   _emit(tree, 0, notes, lines)
   for section, texts in notes.items():
      if section.split(".")[0] not in tree or not _has_path(tree, section):
         lines.extend(f"# {section} : {text}" for text in texts)
   text = "\n".join(lines) + "\n"

   back = yaml.safe_load(text) or {}
   if back != _plain(tree):
      raise ArtToolError(f"조각 YAML 을 다시 읽으니 뜻이 다르다 (만든 쪽 버그) : {back}")
   return text


def _has_path(tree: dict, dotted: str) -> bool:
   node = tree
   for part in dotted.split("."):
      if not isinstance(node, dict) or part not in node:
         return False
      node = node[part]
   return True


# --- 견본 PNG ---


def swatch(ramps: list[dict], outline: int | None, discarded: list[int], scale: int = 1) -> np.ndarray:
   """램프 한 줄 = 색 칸 한 줄(CELL px × 배율). 채운 칸은 반 칸 크기로 가운데에 찍는다.

   외곽선 색이 있으면 그 아래 한 칸짜리 줄. 반 칸 띄우고 맨 아래에 버린 색(꺾어 여러 줄).
   """
   cell = CELL * max(1, int(scale))
   length = len(ramps[0]["colors"]) if ramps else 0
   cols = max(length, MIN_COLS)
   rows: list[list[tuple[int, bool]]] = [[(k, i >= length - r["padded"]) for i, k in enumerate(r["colors"])] for r in ramps]
   if outline is not None:
      rows.append([(outline, False)])
   tail = [discarded[i : i + cols] for i in range(0, len(discarded), cols)]
   gap = cell // 2 if tail else 0

   height = len(rows) * cell + gap + len(tail) * cell
   canvas = image.new(cols * cell, max(cell, height))
   for y, row in enumerate(rows):
      for x, (key, padded) in enumerate(row):
         _cell(canvas, x * cell, y * cell, cell, key, padded)
   top = len(rows) * cell + gap
   for y, row in enumerate(tail):
      for x, key in enumerate(row):
         _cell(canvas, x * cell, top + y * cell, cell, key, False)
   return canvas


def _cell(canvas: np.ndarray, x: int, y: int, cell: int, key: int, half: bool) -> None:
   color = (*to_rgb(key), 255)
   if half:
      q = cell // 4
      canvas[y + q : y + cell - q, x + q : x + cell - q] = color
      return
   canvas[y : y + cell, x : x + cell] = color
