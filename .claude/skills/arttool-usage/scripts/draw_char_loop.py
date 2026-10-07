"""고리 그리기 본보기 — 그리고 → 글로 읽고 → 그림으로 보고 → 고치는 바퀴를 실제로 돈다 (`고리-그리기.md`).

    <ArtTool>/.venv/Scripts/python.exe draw_char_loop.py --out work/              # 32×32 sd
    <ArtTool>/.venv/Scripts/python.exe draw_char_loop.py --out work/ --size 48x64

work/guide/ 밑판 → 1바퀴(도형 + 격자 얼굴) → 2바퀴(린트가 짚은 볼 고치기) → 외곽선 한 번 → work/set/ · work/preview_x8.png.
바퀴마다 work/loop_N.png(바뀐 칸만 확대 · 자홍 테)와 work/loop_N_color.png(색 미리보기)를 남긴다. 끝 줄에 `린트 N 건` 을 찍는다.
뒤의 검사(`layers check` → `check` → `sheet` → `export`)는 draw_char_small.py 뒤쪽과 같다.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

from arttool import image
from arttool.draw import Canvas, shade
from arttool.palette import to_hex

SKIN, CLOTH, PANTS, HAIR, EYE, BLUSH = "#F6D0B0", "#E8705A", "#4C5F9E", "#6A3E2A", "#2A2238", "#F09A9A"
PARTS = ("body", "cloth", "face", "hair")

# 얼굴 왼쪽 반만 적는다 — symmetry 가 오른쪽을 채운다. 글자는 대문자(소문자는 c.legend 가 먼저 쓴다). 눈 상자 왼 위 칸이 (0, 0).
# 4째 칸은 얼굴 가운데 줄 바로 왼쪽이라 그 거울이 가운데 오른쪽 칸이 된다(입 두 칸).
FACE = f"""K {EYE}
P {BLUSH}
M {to_hex(shade(SKIN)[0])}

KK..
KK..
....
P..M
"""
# 1바퀴 린트(`lint.hole … 3칸 구멍` · 볼 한 칸 `lint.orphan`)와 격자의 얼굴 안 `.` 세 칸
# (본체 마스크가 얼굴 자리를 비워 둔다)을 보고 고친다. 볼도 두 칸으로.
FACE_FIX = f"P {BLUSH}\nS {SKIN}\n\nPP\nSS\n"


def arttool(*args: str) -> None:
   subprocess.run([sys.executable, "-m", "arttool", *args], check=True, stdout=subprocess.DEVNULL)


def load_mask(guide_dir: Path, template: str, layer: str, size) -> np.ndarray:
   path = guide_dir / f"{template}_mask_{layer}.png"
   return image.load(path)[:, :, 3] > 0 if path.is_file() else np.zeros((size[1], size[0]), dtype=bool)


def look(c: Canvas, out: Path, n: int, window) -> int:
   """바퀴 끝 보기 : 린트 줄 · 창 격자 · 바뀐 칸 그림 · 색 미리보기. 린트 건수를 돌려준다."""
   lines = c.lint().lines()
   print(f"--- {n}바퀴 : 린트 {len(lines)} 건 · 바뀐 칸 {c.changed()['count']}")
   print("\n".join(lines) or "(린트 없음)")
   print(c.to_grid(box=window, rulers=True))
   c.preview_changed(out / f"loop_{n}.png")      # 이것을 Read 로 연다 (1바퀴는 모든 칸에 테가 둘려 색은 못 본다)
   c.preview(out / f"loop_{n}_color.png", scale=8)   # 색 미리보기 — 같이 연다
   return len(lines)


def main() -> None:
   ap = argparse.ArgumentParser()
   ap.add_argument("--out", required=True, help="결과 폴더 (저장소 밖)")
   ap.add_argument("--size", default="32", help="32 · 48x64 … (char_small 기본 프리셋)")
   args = ap.parse_args()
   sys.stdout.reconfigure(encoding="utf-8")       # 격자 글의 `·` 이 콘솔 코드표에서 깨지지 않게
   out = Path(args.out)
   guide_dir = out / "guide"
   arttool("template", "render", "char_small", "--size", args.size, "--out", str(guide_dir))

   c = Canvas(template=guide_dir)
   g = c.guide
   for name in PARTS:                             # 겹마다 자기 마스크 안에만 찍힌다
      c[name].set_clip(load_mask(guide_dir, c.template_name, name, c.size))
   c.set_symmetry("x", layers=list(PARTS))        # 반쪽만 그려도 거울 · lint 가 이 겹에 asym 을 자동으로 켠다
   skin, cloth, pants, hair = shade(SKIN), shade(CLOTH), shade(PANTS), shade(HAIR)

   # 1바퀴 : 큰 덩어리는 도형, 얼굴은 격자 글. 모두 거울이라 asym 0 이 나와야 한다
   c.mark()
   c["body"].box(*g.box("head"), skin[3]).box(*g.box("legs"), pants[3])
   c["cloth"].round_box(*g.box("torso"), cloth[3], r=1)
   c["hair"].paint(np.ones((c.size[1], c.size[0]), dtype=bool), hair[3])   # clip 이 머리카락 자리로 자른다
   ex, ey = g.box("eye_box_l")[:2]
   c.paste_grid("face", FACE, at=(ex, ey))
   look(c, out, 1, g.box("head"))

   # 2바퀴 : 바뀐 글자만 다시 붙이고 그 겹의 바뀐 칸이 생각(왼 3 + 거울 3 = 6)과 같은지 본다.
   # 그늘은 빛 반대쪽(오른쪽)만 — 그 겹은 거울을 끈 채 둔다(켜 두면 asym 이 그늘 칸마다 뜬다)
   c.mark()
   c.paste_grid("face", FACE_FIX, at=(ex, ey + 3))
   print(f"얼굴 고친 칸 {c.changed()['layers']['face']} (생각 6)\n{c.diff_grid()}")
   c.set_symmetry(None, layers=["hair", "cloth"])
   for name, x1, color in (("hair", g.box("head")[2], hair[2]), ("cloth", g.box("torso")[2], cloth[2])):
      band = np.zeros((c.size[1], c.size[0]), dtype=bool)
      band[:, x1 - 2 : x1] = True
      c[name].paint(band & c[name].mask(), color)   # 이미 칠한 칸만 — 깎은 모서리를 다시 메우지 않게
   look(c, out, 2, g.box("head"))

   # 끝 : 외곽선은 맨 마지막에 한 번만 (outline 은 symmetry · clip 을 안 탄다)
   c.outline("selout", where="inside")
   final = len(c.lint(outline_mode="selout").lines())
   c.save(out / "set")
   c.preview(out / "preview_x8.png", scale=8)
   print(f"린트 {final} 건")


if __name__ == "__main__":
   main()
