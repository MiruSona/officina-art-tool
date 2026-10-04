"""고리 폭발 이펙트 다섯 장을 템플릿 프레임 공식대로 그린다 (PIL 길 본보기).

    <ArtTool>/.venv/Scripts/python.exe draw_fx.py --out work/

work/guide/ 밑판(fx_ring_burst, 흰 1색 _f00~_f04) → 같은 모양을 한 색으로 그림 → 가이드 프레임과 칸 단위로 견줌
→ work/frames/ → check --template(프레임 수 · 색 수 대조) → 비교판.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from arttool import image
from arttool.draw import Canvas

COLOR = "#FFF1B8"            # 이펙트는 1색. 게임 팔레트 밖이어도 된다(effect 템플릿은 must 에 palette 가 없다)
C = 7.5                      # 16칸 캔버스의 가운데 = (16 - 1) / 2
FRAMES = [                   # 2×2 점 → 꽉 찬 원 → 2px 고리 → 1px 고리 → 끊긴 고리
   lambda l: l.dot(7, 7, COLOR, side=2),
   lambda l: l.disc(C, C, 8, COLOR),
   lambda l: l.ring(C, C, 8, COLOR, width=2),
   lambda l: l.ring(C, C, 8, COLOR, width=1),
   lambda l: l.ring(C, C, 8, COLOR, width=1, dash=2),
]


def arttool(*args: str) -> None:
   subprocess.run([sys.executable, "-m", "arttool", *args], check=True, stdout=subprocess.DEVNULL)


def main() -> None:
   ap = argparse.ArgumentParser()
   ap.add_argument("--out", required=True, help="결과 폴더 (저장소 밖)")
   out = Path(ap.parse_args().out)
   guide_dir, frames = out / "guide", out / "frames"
   arttool("template", "render", "fx_ring_burst", "--size", "16", "--out", str(guide_dir))

   c = Canvas(template=guide_dir)              # 겹 하나 : fx
   frames.mkdir(parents=True, exist_ok=True)
   for i, draw in enumerate(FRAMES):
      c["fx"].erase()
      draw(c["fx"])
      want = image.load(guide_dir / f"fx_ring_burst_f{i:02d}.png")[:, :, 3] > 0
      if (c["fx"].mask() != want).any():       # 가이드 프레임과 모양이 다르면 멈춘다
         sys.exit(f"프레임 {i} 모양이 가이드와 다르다")
      c.preview(frames / f"burst_{i:02d}.png", scale=1)
   arttool("check", "--in", str(frames), "--template", str(guide_dir / "template.json"), "--report", str(out / "check.json"))
   arttool("sheet", "--in", str(frames), "--kinds", "zoom,silhouette", "--label", "--out", str(out / "sheet.png"))
   print(f"끝 : {out}")


if __name__ == "__main__":
   main()
