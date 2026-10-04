"""풀 바닥 타일 + 꽃 변종을 겹으로 그린다 (PIL 길 본보기).

    <ArtTool>/.venv/Scripts/python.exe draw_tile.py --out work/

work/guide/ 밑판(tile_base) → work/set/ 겹 묶음(바탕 · 변종) → work/tiles/ 합친 타일 두 장 → tile seam → 비교판.
바탕 무늬는 좌표를 타일 크기로 나눈 나머지로 찍어 네 변이 저절로 이어진다. 변종은 가운데(variant_area)만 바꾼다.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from arttool.draw import Canvas, shade

GRASS, FLOWER = "#6FA85A", "#F2D46B"
TUFTS = [(3, 5), (11, 2), (20, 7), (27, 12), (6, 18), (15, 14), (24, 24), (9, 27), (30, 30), (18, 21)]


def arttool(*args: str) -> None:
   subprocess.run([sys.executable, "-m", "arttool", *args], check=True, stdout=subprocess.DEVNULL)


def main() -> None:
   ap = argparse.ArgumentParser()
   ap.add_argument("--out", required=True, help="결과 폴더 (저장소 밖)")
   out = Path(ap.parse_args().out)
   guide_dir, set_dir, tiles = out / "guide", out / "set", out / "tiles"
   arttool("template", "render", "tile_base", "--size", "32", "--out", str(guide_dir))

   c = Canvas(template=guide_dir)              # 겹 : base · variant(optional)
   w, h = c.size
   grass, flower = shade(GRASS, steps=4, hue_step=20), shade(FLOWER, steps=4)
   base = c["base"].box(0, 0, w, h, grass[2])
   for x, y in TUFTS:                           # 풀 한 포기 = 어두운 점 2 + 밝은 점 1, 나머지 셈으로 감싼다
      base.dot(x % w, y % h, grass[1]).dot((x + 1) % w, (y + 1) % h, grass[1]).dot(x % w, (y - 1) % h, grass[3])
   c.save(set_dir, item="grass")                # 변종 겹이 빈 판 = 기본 타일

   x0, y0, x1, y1 = c.guide.box("variant_area")  # 가장자리 지키는 줄 안쪽
   cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
   for dx, dy in ((0, -1), (-1, 0), (1, 0), (0, 1)):
      c["variant"].dot(cx + dx, cy + dy, flower[2])
   c["variant"].dot(cx, cy, flower[0]).line(cx, cy + 2, cx, cy + 4, grass[0])
   print(c.report())
   c.save(set_dir, item="grass_flower")         # 같은 묶음에 그림 하나 더

   arttool("layers", "check", "--in", str(set_dir), "--template", str(guide_dir / "template.json"),
           "--report", str(out / "layers_check.json"))
   arttool("layers", "export", "--in", str(set_dir), "--out", str(tiles), "--flat")
   arttool("tile", "seam", "--in", str(tiles), "--pairs", "--report", str(out / "seam.json"))
   arttool("sheet", "--in", str(tiles), "--kinds", "zoom,tile", "--label", "--out", str(out / "sheet.png"))
   print(f"끝 : {out}")


if __name__ == "__main__":
   main()
