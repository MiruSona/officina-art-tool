"""작은 캐릭터(SD · 치비)를 템플릿 가이드 줄과 겹 마스크에 맞춰 겹별로 그린다 (PIL 길 본보기).

    <ArtTool>/.venv/Scripts/python.exe draw_char_small.py --out work/              # 48x64 sd (머리가 몸의 절반 가까이)
    <ArtTool>/.venv/Scripts/python.exe draw_char_small.py --out work/ --size 32    # 32×32 sd (기본 프리셋, 2등신)

work/guide/ 밑판 → work/set/ 겹 묶음 → work/flat/ 합친 한 장 → 검사 → work/sheet.png 비교판.
고칠 것은 맨 위 색 상수뿐이다. 좌표는 모두 가이드(g.box · g.y)와 겹 마스크(guide/<템플릿>_mask_<겹>.png)에서 읽는다.
그래서 크기 · 프리셋을 바꿔도 같은 코드로 그려지고, `layers check --template` 의 마스크 경고가 안 난다.

귀엽게 읽히는 요령 (작은 판일수록 중요)
- 머리를 크게, 눈은 세로로 긴 진한 칸 + 왼쪽 위 흰 점 하나. 눈 사이를 넓게.
- 볼(분홍 두 칸) · 작은 입 한 칸. 얼굴 아래쪽에 모은다.
- 머리카락은 둥근 윗머리 + 들쭉날쭉한 앞머리 끝 + 밝은 띠 하나(빛이 왼쪽 위).
- 몸은 짧고 단순하게 — 옷 한 덩어리 + 그늘 한 줄, 신발은 진하게.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

from arttool import image
from arttool.draw import Canvas, shade

SKIN, CLOTH, PANTS, HAIR, EYE, BLUSH, SHOE = "#F6D0B0", "#E8705A", "#4C5F9E", "#6A3E2A", "#2A2238", "#F09A9A", "#3A2A30"


def arttool(*args: str) -> None:
   """arttool 명령 한 줄. 실패(종료 0 아님)면 여기서 멈춘다."""
   subprocess.run([sys.executable, "-m", "arttool", *args], check=True, stdout=subprocess.DEVNULL)


def load_mask(guide_dir: Path, template: str, layer: str, size) -> np.ndarray:
   """render 가 낸 겹 마스크(흰 = 그 겹이 그릴 자리). 없으면 빈 마스크."""
   path = guide_dir / f"{template}_mask_{layer}.png"
   if not path.is_file():
      return np.zeros((size[1], size[0]), dtype=bool)
   return image.load(path)[:, :, 3] > 0


def main() -> None:
   ap = argparse.ArgumentParser()
   ap.add_argument("--out", required=True, help="결과 폴더 (저장소 밖)")
   ap.add_argument("--size", default="48x64", help="48x64 · 64x80 · 32 · 16 … (모두 기본 프리셋 sd, 2등신)")
   args = ap.parse_args()
   out = Path(args.out)
   guide_dir, set_dir, flat_dir = out / "guide", out / "set", out / "flat"
   arttool("template", "render", "char_small", "--size", args.size, "--out", str(guide_dir))

   c = Canvas(template=guide_dir)            # 겹 목록 · 크기 · 가이드를 template render 결과에서 읽는다
   g = c.guide
   mask = {name: load_mask(guide_dir, c.template_name, name, c.size) for name in ("body", "cloth", "face", "hair")}
   skin, cloth, pants, hair = shade(SKIN), shade(CLOTH), shade(PANTS), shade(HAIR)   # 램프 6단, 3 = 밑색
   hx0, hy0, hx1, hy1 = g.box("head")
   tx0, ty0, tx1, ty1 = g.box("torso")
   lx0, ly0, lx1, ly1 = g.box("legs")
   base = g.y("baseline")
   head_w = hx1 - hx0
   r = max(1, head_w // 5)                    # 머리 모서리 깎기 — 클수록 둥글다

   # 1) 본체 : 머리(살색) — 얼굴 · 머리카락 자리는 그 겹이 덮으니 나중에 마스크 밖을 지운다
   c["body"].round_box(hx0, hy0, hx1, hy1, skin[3], r=r)
   c["body"].box(hx1 - max(1, head_w // 8), hy0, hx1, hy1, skin[2])      # 빛 반대쪽(오른쪽) 그늘 한 줄
   # 다리 : 위 절반은 반바지(본체 겹 — 실물 겹 묶음도 하의를 본체에 둔다), 아래는 다리 · 신발
   leg_w = max(1, (lx1 - lx0 - 2) // 2 if lx1 - lx0 >= 6 else (lx1 - lx0) // 2)
   gap = (lx1 - lx0) - 2 * leg_w
   shorts_end = ly0 + max(1, (base + 1 - ly0) // 2)
   c["body"].box(lx0, ly0, lx1, shorts_end, pants[3]).box(lx1 - 1, ly0, lx1, shorts_end, pants[2])
   for x0 in (lx0, lx0 + leg_w + gap):
      c["body"].box(x0, shorts_end, x0 + leg_w, base + 1, skin[3])
      c["body"].box(x0, base - max(0, (base - shorts_end) // 3), x0 + leg_w, base + 1, SHOE)

   # 2) 옷 : 윗옷 한 덩어리 + 오른쪽 그늘 + 옷깃(밝은 줄) + 소매 끝 손
   c["cloth"].round_box(tx0, ty0, tx1, ty1, cloth[3], r=1 if tx1 - tx0 >= 6 else 0)
   c["cloth"].box(tx1 - max(1, (tx1 - tx0) // 6), ty0, tx1, ty1, cloth[2])
   c["cloth"].box(tx0 + 1, ty0, tx1 - 1, ty0 + 1, cloth[4])
   if tx1 - tx0 >= 10 and ty1 - ty0 >= 6:
      arm = max(2, (tx1 - tx0) // 6)
      for x0 in (tx0, tx1 - arm):              # 소매와 몸통 사이 그늘 한 줄 + 손
         edge = x0 + arm if x0 == tx0 else x0 - 1
         c["cloth"].box(edge, ty0 + 2, edge + 1, ty1 - 1, cloth[2])
         c["cloth"].box(x0, ty1 - 2, x0 + arm, ty1, skin[3])

   # 3) 얼굴 : 세로로 긴 눈(32 이하는 2×2 · 1×2) + 흰 점 · 볼 · 작은 입
   for name in ("eye_box_l", "eye_box_r"):
      x0, y0, x1, y1 = g.box(name)
      c["face"].box(x0, y0, x1, y1, EYE)
      if (x1 - x0) * (y1 - y0) >= 6:          # 흰 점은 눈이 6칸 이상일 때만 — 작은 눈에 넣으면 흰자가 눈을 먹는다
         c["face"].dot(x0, y0, "#FFFFFF")
   for box in g.data.get("lines", {}).get("cheeks") or []:      # 볼 상자 목록 (작은 판에는 없다)
      c["face"].box(*box, BLUSH)
   c["face"].box(*g.box("mouth"), skin[0])

   # 4) 머리카락 : 마스크 모양 그대로 + 둥근 윗머리 + 밝은 띠 + 앞머리 끝 들쭉날쭉
   hm = mask["hair"]
   c["hair"].paint(hm, hair[3])
   c["hair"].erase(~_round(hm, r))
   ys = np.nonzero(hm.any(axis=1))[0]
   if len(ys):
      top, bottom = int(ys[0]), int(ys[-1])
      # 밝은 띠 : 윗머리 왼쪽 1/4 지점에 짧게 (빛이 왼쪽 위). 판이 크면 두 칸 띄워 한 줄 더
      band = top + max(1, (bottom - top) // 4)
      left = hx0 + r + 1
      c["hair"].paint(hm & _rows(c.size, band, band + 1) & _cols(c.size, left, left + max(2, head_w // 4)), hair[4])
      if head_w >= 24:
         c["hair"].paint(hm & _rows(c.size, band + 1, band + 2) & _cols(c.size, left + max(2, head_w // 4), left + head_w // 3), hair[4])
      # 그늘 : 오른쪽 한 줄
      c["hair"].paint(hm & _cols(c.size, hx1 - max(1, head_w // 10), hx1) & ~_rows(c.size, top, top + r), hair[2])
      # 앞머리 끝 : 이마 위 마지막 줄(머리 가운데 세로줄에서 잰다)의 세 칸마다 한 칸을 진하게, 그 위 칸도 한 칸 —
      # 머리카락 가닥이 갈라져 보인다. 옆머리는 건드리지 않는다
      mid = hx0 + head_w // 2
      fringe = int(np.nonzero(hm[:, mid])[0].max()) if hm[:, mid].any() else bottom
      for x in range(hx0 + r + 1, hx1 - r - 1, 3):
         if hm[fringe, x]:
            c["hair"].dot(x, fringe, hair[2])
            if fringe - 1 > band + 1 and hm[fringe - 1, x]:
               c["hair"].dot(x, fringe - 1, hair[2])

   # 겹 마스크 밖은 지운다 — 위 겹이 덮는 칸은 본체에서 빼고, 겹마다 자기 자리에만 남긴다
   c["body"].erase(c["hair"].mask() | c["face"].mask())
   for name in ("body", "cloth", "face", "hair"):
      if mask[name].any():
         c[name].erase(~mask[name])
   # 5) 외곽선 : 합친 실루엣 가장자리 칸을 어둡게(inside — 크기가 안 변한다). 칸마다 주인 겹에 들어간다
   c.outline("selout", where="inside")

   print(c.report())                          # 팔레트 밖 색 · exclusive 겹침 · 빈 겹 · 외곽선 두 번
   c.save(set_dir)
   c.preview(out / "preview_x8.png", scale=8)
   c.preview(out / "preview_x12.png", scale=12)
   template = str(guide_dir / "template.json")
   arttool("layers", "check", "--in", str(set_dir), "--template", template, "--report", str(out / "layers_check.json"))
   arttool("layers", "export", "--in", str(set_dir), "--out", str(flat_dir), "--flat")
   arttool("check", "--in", str(flat_dir), "--template", template, "--report", str(out / "check.json"))
   arttool("sheet", "--in", str(flat_dir), "--kinds", "zoom,silhouette,colors4", "--label", "--out", str(out / "sheet.png"))
   print(f"끝 : {out}")


def _box_mask(size, x0, y0, x1, y1) -> np.ndarray:
   m = np.zeros((size[1], size[0]), dtype=bool)
   m[max(0, y0) : max(0, y1), max(0, x0) : max(0, x1)] = True
   return m


def _rows(size, y0, y1) -> np.ndarray:
   return _box_mask(size, 0, y0, size[0], y1)


def _cols(size, x0, x1) -> np.ndarray:
   return _box_mask(size, x0, 0, x1, size[1])


def _round(m: np.ndarray, r: int) -> np.ndarray:
   """마스크의 위 두 모서리를 계단으로 r 칸 깎은 모양 (둥근 윗머리)."""
   out = m.copy()
   ys, xs = np.nonzero(m)
   if not len(ys):
      return out
   top, x0, x1 = int(ys.min()), int(xs.min()), int(xs.max())
   for i in range(r):
      cut = r - i
      out[top + i, x0 : x0 + cut] = False
      out[top + i, x1 - cut + 1 : x1 + 1] = False
   return out


if __name__ == "__main__":
   main()
