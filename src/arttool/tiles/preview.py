"""여러 장을 실제 칸 수로 조립한 미리보기 한 장. 배치표 꼴은 설계 문서 6-1.

`Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md`
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from .. import image
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json
from ..paths import check_relative, jailed_output, resolve_root, safe_join

LAYOUT_KEYS = ("size", "weights", "seed", "cells")
MAX_CELLS = 256 * 256


@dataclass
class Layout:
   cols: int
   rows: int
   grid: list[list[str | None]]
   seed: int | None
   names: list[str]


def _count(value, where: str) -> int:
   if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
      raise ArtToolError(f"{where} 는 양의 정수다 : {value!r}")
   return value


def _parse_size(raw) -> tuple[int, int]:
   if not isinstance(raw, list) or len(raw) != 2:
      raise ArtToolError(f"size 는 [가로 칸, 세로 칸] 이다 : {raw!r}")
   cols, rows = _count(raw[0], "size[0]"), _count(raw[1], "size[1]")
   if cols * rows > MAX_CELLS:
      raise ArtToolError(f"칸이 너무 크다 : {cols}x{rows} (한도 {MAX_CELLS}칸)")
   return cols, rows


def _parse_weights(raw) -> dict[str, float]:
   if not isinstance(raw, dict) or not raw:
      raise ArtToolError("weights 는 비지 않은 사전이다 (이름 → 무게)")
   out = {}
   for name, value in raw.items():
      if isinstance(value, bool) or not isinstance(value, (int, float)):
         raise ArtToolError(f"weights.{name} 는 0 이상 유한한 수다 : {value!r}")
      number = float(value) if abs(value) < 1e308 else math.inf  # 아주 큰 정수는 float() 가 넘친다
      if not math.isfinite(number) or number < 0:
         raise ArtToolError(f"weights.{name} 는 0 이상 유한한 수다 : {value!r}")
      out[str(name)] = number
   total = sum(out.values())
   if not math.isfinite(total):
      raise ArtToolError("weights 의 무게 합이 너무 커서 셀 수 없다")
   if total <= 0:
      raise ArtToolError("weights 의 무게 합이 0 이다")
   return out


def _weighted_grid(cols: int, rows: int, weights: dict[str, float], seed: int) -> list[list[str | None]]:
   picks = random.Random(seed).choices(list(weights), weights=list(weights.values()), k=cols * rows)
   return [picks[r * cols : (r + 1) * cols] for r in range(rows)]


def _parse_cells(raw, size) -> list[list[str | None]]:
   if not isinstance(raw, list) or not raw or not all(isinstance(row, list) and row for row in raw):
      raise ArtToolError("cells 는 줄 목록이고 줄마다 이름이 하나 이상이다")
   width = len(raw[0])
   if any(len(row) != width for row in raw):
      raise ArtToolError("cells 의 줄마다 칸 수가 같아야 한다")
   _parse_size([width, len(raw)])
   if size is not None and size != (width, len(raw)):
      raise ArtToolError(f"size {list(size)} 와 cells 의 칸 수 [{width}, {len(raw)}] 가 다르다")
   for row in raw:
      for name in row:
         if name is not None and (not isinstance(name, str) or not name):
            raise ArtToolError(f"cells 의 칸은 이름 문자열이나 null 이다 : {name!r}")
   return [list(row) for row in raw]


def load_layout(data) -> Layout:
   """weights(seed 로 섞기) 와 cells(자리 고정) 중 하나만 받는다."""
   if not isinstance(data, dict):
      raise ArtToolError("배치표는 JSON 사전이어야 한다")
   unknown = sorted(set(data) - set(LAYOUT_KEYS))
   if unknown:
      raise ArtToolError(f"배치표에 모르는 칸 : {', '.join(unknown)}")
   has_w, has_c = "weights" in data, "cells" in data
   if has_w == has_c:
      raise ArtToolError("배치표에는 weights 와 cells 중 하나만 있어야 한다")
   size = _parse_size(data["size"]) if "size" in data else None

   if has_c:
      if "seed" in data:
         raise ArtToolError("seed 는 weights 에만 쓴다")
      grid = _parse_cells(data["cells"], size)
      names = list(dict.fromkeys(n for row in grid for n in row if n is not None))
      return Layout(len(grid[0]), len(grid), grid, None, names)

   if size is None:
      raise ArtToolError("weights 배치표에는 size 가 있어야 한다")
   seed = data.get("seed", 0)
   if isinstance(seed, bool) or not isinstance(seed, int):
      raise ArtToolError(f"seed 는 정수다 : {seed!r}")
   weights = _parse_weights(data["weights"])
   grid = _weighted_grid(size[0], size[1], weights, seed)
   return Layout(size[0], size[1], grid, seed, list(weights))


def _tile_file(root: Path, name: str) -> Path:
   """이름은 파일 이름에서 .png 를 뗀 것. .png 를 붙여 적어도 받는다."""
   check_relative(name)  # 밖으로 나가는 이름은 경로 감옥 오류(종료 6)로 먼저 거른다
   if "/" in name or "\\" in name:
      raise ArtToolError(f"배치표 이름에 폴더를 못 넣는다 (이름 = --in 바로 아래 파일 이름) : {name}")
   rel = name if name.lower().endswith(".png") else f"{name}.png"
   path = safe_join(root, rel)
   if not path.is_file():
      raise ArtToolError(f"배치표의 이름에 맞는 타일 파일이 없다 : {name} ({path})")
   return path


def _load_tiles(root: Path, names: list[str]) -> tuple[dict[str, image.RGBA], tuple[int, int]]:
   """적힌 이름은 뽑히지 않았어도 다 읽는다. 칸 크기는 첫 타일 크기이고 섞이면 거절한다."""
   if not names:
      raise ArtToolError("배치표에 타일이 하나도 없다 (전부 null)")
   tiles = {name: image.load(_tile_file(root, name)) for name in names}
   cell = image.size(tiles[names[0]])
   for name, arr in tiles.items():
      if image.size(arr) != cell:
         raise ArtToolError(f"타일 크기가 섞였다 : {name} 는 {image.size(arr)}, 첫 타일 {names[0]} 는 {cell}")
   return tiles, cell


def run(layout_file: str | Path, in_dir: str | Path, out_file: str | Path, scale: int | None = None) -> dict:
   if scale is not None and scale <= 0:
      raise UsageError(f"--scale 은 양수여야 한다 : {scale}")
   factor = scale or 1
   source = Path(in_dir)
   if not source.is_dir():
      raise ArtToolError(f"타일 폴더가 없다 : {source}")
   layout = load_layout(read_json(layout_file))
   tiles, (cw, ch) = _load_tiles(resolve_root(source), layout.names)

   width, height = layout.cols * cw * factor, layout.rows * ch * factor
   image.check_pixels(width, height, "미리보기")

   sheet = image.new(layout.cols * cw, layout.rows * ch)
   counts: dict[str, int] = {}
   for r, row in enumerate(layout.grid):
      for c, name in enumerate(row):
         if name is None:
            continue
         image.paste(sheet, tiles[name], c * cw, r * ch)
         counts[name] = counts.get(name, 0) + 1

   out = jailed_output(out_file)
   image.save(out, image.scale_up(sheet, factor) if factor > 1 else sheet)
   return {
      "status": "ok",
      "out": str(out),
      "size": [layout.cols, layout.rows],
      "cell": [cw, ch],
      "scale": factor,
      "seed": layout.seed,
      "counts": counts,
      "grid": layout.grid,
   }
