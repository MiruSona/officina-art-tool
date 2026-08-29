"""② 이어붙이기. 템플릿 6장 → 47장 blob.

한 칸을 네 조각(쿼터 타일)으로 쪼갠다. 조각 하나는 이웃 셋(세로·가로·대각)만 보므로
경우의 수가 여덟이고, 그림은 다섯 가지면 된다.
마스크 표는 blobator(MIT) 가 쓰는 것과 같은 8비트 이웃 규칙이고 코드는 직접 썼다.
"""

from __future__ import annotations

from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from ..profile import Profile

VERSION = 1

N, NE, E, SE, S, SW, W, NW = 1, 2, 4, 8, 16, 32, 64, 128

TEMPLATE_NAMES = ("fill", "edge_n", "edge_w", "corner_outer", "corner_inner", "single")

# 조각 다섯. 이름이 곧 템플릿에서 잘라 올 자리다.
FILL, EDGE_N, EDGE_W, OUTER, INNER = "fill", "edge_n", "edge_w", "corner_outer", "corner_inner"

# 모서리 넷 : (이름, 세로 이웃, 가로 이웃, 대각 이웃, x 뒤집기, y 뒤집기)
CORNERS = (
   ("nw", N, W, NW, False, False),
   ("ne", N, E, NE, True, False),
   ("sw", S, W, SW, False, True),
   ("se", S, E, SE, True, True),
)


def normalize_mask(mask: int) -> int:
   """대각 이웃은 양옆 이웃이 둘 다 있을 때만 센다. 256가지가 47가지로 줄어든다."""
   out = mask
   for _name, vertical, horizontal, diagonal, _fx, _fy in CORNERS:
      if not (mask & vertical and mask & horizontal):
         out &= ~diagonal
   return out & 0xFF


def blob_masks() -> list[int]:
   """쓸 수 있는 마스크 47가지를 작은 것부터."""
   return sorted({normalize_mask(m) for m in range(256)})


def piece_for(mask: int, vertical: int, horizontal: int, diagonal: int) -> str:
   has_v = bool(mask & vertical)
   has_h = bool(mask & horizontal)
   if not has_v and not has_h:
      return OUTER
   if has_v and not has_h:
      return EDGE_W
   if not has_v and has_h:
      return EDGE_N
   if not mask & diagonal:
      return INNER
   return FILL


def load_templates(template_dir: str | Path, tile_size: int) -> dict[str, image.RGBA]:
   folder = Path(template_dir)
   missing = [name for name in TEMPLATE_NAMES if not (folder / f"{name}.png").is_file()]
   if missing:
      raise ArtToolError(f"템플릿 6장이 안 채워졌다. 없는 것 : {', '.join(missing)}")

   out: dict[str, image.RGBA] = {}
   for name in TEMPLATE_NAMES:
      arr = image.load(folder / f"{name}.png")
      width, height = image.size(arr)
      if (width, height) != (tile_size, tile_size):
         raise ArtToolError(f"조각 경계가 안 맞는다 : {name}.png 가 {width}x{height} 다. {tile_size}x{tile_size} 여야 한다")
      if image.has_soft_alpha(arr):
         raise ArtToolError(f"반투명 픽셀이 있다 : {name}.png")
      out[name] = arr
   return out


def _quarter(arr: image.RGBA, half: int, flip_x: bool, flip_y: bool) -> image.RGBA:
   """템플릿의 왼쪽 위 사분면을 잘라 필요한 만큼 뒤집는다."""
   piece = image.crop(arr, 0, 0, half, half)
   if flip_x:
      piece = image.flip_x(piece)
   if flip_y:
      piece = image.flip_y(piece)
   return piece


def make_tile(templates: dict[str, image.RGBA], mask: int, tile_size: int) -> image.RGBA:
   if mask == 0:
      return templates["single"].copy()

   half = tile_size // 2
   tile = image.new(tile_size, tile_size)
   for name, vertical, horizontal, diagonal, flip_x, flip_y in CORNERS:
      piece_name = piece_for(mask, vertical, horizontal, diagonal)
      piece = _quarter(templates[piece_name], half, flip_x, flip_y)
      x = half if name in ("ne", "se") else 0
      y = half if name in ("sw", "se") else 0
      image.paste(tile, piece, x, y)
   return tile


def build(prof: Profile, template_dir: str | Path, out_dir: str | Path) -> dict:
   tile_size = int(prof.tiles["size"])
   if tile_size % 2 != 0:
      raise ArtToolError(f"타일 크기가 홀수라 네 조각으로 못 쪼갠다 : {tile_size}")

   templates = load_templates(template_dir, tile_size)
   root = resolve_root(out_dir)
   masks = blob_masks()

   cols = 8
   rows = (len(masks) + cols - 1) // cols
   sheet = image.new(cols * tile_size, rows * tile_size)
   entries = []
   for index, mask in enumerate(masks):
      tile = make_tile(templates, mask, tile_size)
      name = f"blob_{mask:03d}.png"
      image.save(safe_join(root, name), tile)
      x = (index % cols) * tile_size
      y = (index // cols) * tile_size
      image.paste(sheet, tile, x, y)
      entries.append({"index": index, "mask": mask, "file": name, "x": x, "y": y})

   image.save(safe_join(root, "tileset.png"), sheet)
   lookup = {str(m): masks.index(normalize_mask(m)) for m in range(256)}
   data = {
      "version": VERSION,
      "profile": prof.name,
      "tile_size": tile_size,
      "count": len(masks),
      "sheet": "tileset.png",
      "sheet_cols": cols,
      "bits": {"n": N, "ne": NE, "e": E, "se": SE, "s": S, "sw": SW, "w": W, "nw": NW},
      "tiles": entries,
      "lookup": lookup,
   }
   write_json(safe_join(root, "tileset.json"), data)
   return data
