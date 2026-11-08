"""P1 검수 접촉판 : groups.json 의 경계 쌍(해밍 LINK~NEAR) 과 큰 그룹 상위를 HTML 한 장으로.

그림은 1칸=1화소로 맞춘 뒤(groups.to_cells) 회색 바탕 · nearest 정수배로 키워 data URI 로 넣는다.
결과 HTML 은 우리 그림을 담으므로 `train.local/` 에만 쓴다.

사용 (ArtTool 폴더에서) : python -I train/polish/review.py [--groups …] [--packs-root external.local] [--out …]
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))   # -I 로 돌려도 옆 파일을 찾게
import groups as grouping  # noqa: E402

BOX = 96          # 칸 하나를 이 크기 안에 맞춰 키운다
PAIRS = 30
TOP_GROUPS = 10
MEMBERS = 12      # 그룹마다 보여 줄 최대 장 수


def _thumb(arr: np.ndarray) -> str:
   h, w = arr.shape[:2]
   k = max(1, BOX // max(h, w))
   bg = Image.new("RGBA", (w, h), (grouping.GREY,) * 3 + (255,))
   bg.alpha_composite(Image.fromarray(arr, "RGBA"))
   im = bg.resize((w * k, h * k), Image.Resampling.NEAREST)
   if max(im.size) > BOX * 2:
      im.thumbnail((BOX * 2, BOX * 2), Image.Resampling.NEAREST)
   buf = io.BytesIO()
   im.convert("RGB").save(buf, "PNG")
   return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _label(item: dict) -> str:
   name = Path(item["path"]).name
   return f"{'우리' if item['side'] == 'ours' else item['pack']} · {name} · {item['size'][0]}×{item['size'][1]}"


def render(result: dict, packs_root: Path) -> str:
   items = result["items"]
   cache: dict[int, str] = {}

   def img(i: int) -> str:
      if i not in cache:
         it = items[i]
         path = Path(it["path"]) if it["side"] == "ours" else packs_root / it["path"]
         arr, why, _ = grouping._load_cells(path)
         cache[i] = _thumb(arr) if arr is not None else ""
      return f'<figure><img src="{cache[i]}"><figcaption>{html.escape(_label(items[i]))}</figcaption></figure>'

   parts = ["<h2>경계 쌍 (우리 그림이 낀 쌍 먼저, 해밍 작은 순)</h2>"]
   for n, pair in enumerate(result["near_pairs"][:PAIRS], 1):
      linked = items[pair["a"]]["group"] == items[pair["b"]]["group"]
      parts.append(f'<div class="row"><b>#{n} d={pair["d"]} p={pair["p"]} {"묶임" if linked else "안 묶임"}</b>'
                   f'{img(pair["a"])}{img(pair["b"])}</div>')
   big = sorted(result["groups"], key=lambda g: -len(g["members"]))[:TOP_GROUPS]
   parts.append("<h2>큰 그룹 상위</h2>")
   for g in big:
      shown = "".join(img(i) for i in g["members"][:MEMBERS])
      parts.append(f'<div class="row"><b>{g["id"]} {g["side"]} {len(g["members"])}장</b>{shown}</div>')
   ours_multi = [g for g in result["groups"] if g["side"] == "ours" and len(g["members"]) > 1]
   parts.append("<h2>우리 그룹 중 둘 이상 묶인 것</h2>")
   for g in ours_multi:
      shown = "".join(img(i) for i in g["members"][:MEMBERS])
      parts.append(f'<div class="row"><b>{g["id"]} {g.get("kind")} {len(g["members"])}장</b>{shown}</div>')
   style = ("body{font:12px sans-serif;background:#fff;margin:8px}.row{display:flex;flex-wrap:wrap;gap:6px;"
            "align-items:flex-start;border-top:1px solid #ccc;padding:4px 0}.row b{width:130px}"
            "figure{margin:0;width:200px}figcaption{word-break:break-all}img{image-rendering:pixelated}")
   return f"<!doctype html><meta charset='utf-8'><title>P1 그룹 검수</title><style>{style}</style>{''.join(parts)}"


def main(argv: list[str] | None = None) -> int:
   ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   ap.add_argument("--groups", default="train.local/groups.json")
   ap.add_argument("--packs-root", default="external.local")
   ap.add_argument("--out", default="train.local/review_groups.html")
   args = ap.parse_args(argv)
   result = json.loads(Path(args.groups).read_text(encoding="utf-8"))
   Path(args.out).write_text(render(result, Path(args.packs_root)), encoding="utf-8")
   print(args.out)
   return 0


if __name__ == "__main__":
   sys.exit(main())
