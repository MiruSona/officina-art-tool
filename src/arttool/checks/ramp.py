"""⑥ ramp_shape — 램프 모양 (설계 7-2 ⑥). 그림이 아니라 램프 파일을 본다.

같은 색이 이어진 칸은 화풍 뽑기가 짧은 램프를 끝 색 되풀이로 채운 칸(설계 9-3 ①-4)으로 보고 건너뛴다.
"""

from __future__ import annotations

import numpy as np

from . import LOW_SAT, hue_gap, hue_sat, luma

WARM_HUE = 60.0     # 밝을수록 다가가는 색조 (노랑)

# 재질이 원하는 단 수 (최소, 최대). 표에 없는 재질은 프로필 steps 를 쓴다
MATERIAL_STEPS = {"goo": (4, 4), "wood": (4, 5), "stone": (5, 5), "ice": (6, 6), "gem": (7, 7)}


def _collapse(colors: list) -> tuple[list[tuple[int, int, int]], int]:
   """이어진 같은 색을 하나로. (남은 색, 건너뛴 칸 수)."""
   out: list[tuple[int, int, int]] = []
   for c in colors:
      c = tuple(int(v) for v in c[:3])
      if out and out[-1] == c:
         continue
      out.append(c)
   return out, len(colors) - len(out)


def measure_ramp(colors: list, outline=None) -> dict:
   """램프 한 줄(어두운 → 밝은) 재기. 화풍 뽑기 ⑥ hue_step · palette_ramp 템플릿도 쓴다.

   돌려주는 것 :
   - `steps` : 이어진 같은 색을 하나로 본 실제 단 수 · `padded` : 건너뛴(채운) 칸 수
   - `luma` : 칸마다 밝기 · `monotonic` : 밝기가 칸마다 오르나
   - `hue_steps` : 이웃 칸 색조 차(도, 부호 없음). 채도 0.12 미만 칸 · 외곽선 색이 낀 쌍은 뺀다
   - `hues` : 색조를 잰 칸들의 (칸 번호, 색조) — 방향 판정용
   """
   real, padded = _collapse(colors)
   outline_rgb = tuple(int(v) for v in outline[:3]) if outline is not None else None
   lumas = [float(luma(np.array(c))) for c in real]
   usable = []
   for index, c in enumerate(real):
      hue, sat = hue_sat(c)
      if sat >= LOW_SAT and c != outline_rgb:
         usable.append((index, round(hue, 2)))
   steps_between = [
      round(hue_gap(a[1], b[1]), 2) for a, b in zip(usable, usable[1:]) if b[0] == a[0] + 1
   ]
   return {
      "steps": len(real),
      "padded": padded,
      "luma": [round(v, 2) for v in lumas],
      "monotonic": all(b > a for a, b in zip(lumas, lumas[1:])),
      "hue_steps": steps_between,
      "hues": usable,
   }


def is_single(m: dict) -> bool:
   """한 색 램프인가 — 같은 색 되풀이를 접으면 1단만 남는 램프 (3판 설계 2-5 가).

   손으로 고른 한 색(예 : 눈동자 · 단추)을 `ramp_len` 칸에 맞추려고 끝 색을 되풀이한 것이다.
   그림자 · 하이라이트 칸이 없는 게 뜻이므로 모양을 따지지 않는다.
   """
   return m["steps"] == 1


def judge_ramp(m: dict, cfg: dict, material: str | None = None, len_mode: str = "fixed") -> list[str]:
   """재 둔 값 → 걸린 까닭 목록. cfg 는 프로필 `check.warn.ramp_shape`, material 은 `style.materials` 의 값.

   한 색 램프(`is_single`)는 빈 목록 — 단 수 · 밝기 · 색조를 따질 칸이 없다. 부르는 쪽이 알림(info)으로 따로 센다.
   len_mode 는 램프 파일의 `ramp_len_mode`. max 는 짧은 램프를 일부러 받는 꼴이라 단 수가 모자란 경고만 뺀다.
   너무 많은 쪽과 밝기 · 색조 판정은 fixed 와 같다.
   """
   if is_single(m):
      return []
   why = []
   low, high = MATERIAL_STEPS.get(material or "", tuple(cfg["steps"]))
   if len_mode == "max":
      low = min(low, m["steps"])
   if not low <= m["steps"] <= high:
      want = f"{low}" if low == high else f"{low}~{high}"
      pad = f" (채운 칸 {m['padded']} 뺌)" if m["padded"] else ""
      why.append(f"단 수 {m['steps']}{pad} — {material or '기본'} 은 {want}단")
   if not m["monotonic"]:
      values = " → ".join(f"{v:.1f}" for v in m["luma"])
      why.append(f"밝기(luma)가 칸마다 오르지 않는다 — {values}")

   gaps = m["hue_steps"]
   if gaps and max(gaps) < float(cfg["hue_min"]):
      why.append(f"hue shift 없음 — 이웃 칸 색조 차가 모두 {cfg['hue_min']}° 미만")
   if gaps and max(gaps) > float(cfg["hue_max"]):
      why.append(f"색조가 튄다 — {max(gaps):.0f}° > {cfg['hue_max']}°")

   direction = _direction(m["hues"], material)
   if direction:
      why.append(direction)
   return why


def _direction(hues: list, material: str | None) -> str | None:
   """밝을수록 노랑(60°) 쪽으로 가나. metal 은 반대를 기대하고, cloth 는 맨 밝은 칸을 뺀다."""
   if material == "cloth" and hues:
      hues = hues[:-1]
   if len(hues) < 2:
      return None
   dark_gap = hue_gap(hues[0][1], WARM_HUE)
   light_gap = hue_gap(hues[-1][1], WARM_HUE)
   if material == "metal":
      if light_gap < dark_gap:
         return "금속인데 밝은 쪽이 따뜻해진다 (금속은 밝을수록 차갑게)"
      return None
   if light_gap > dark_gap:
      return "밝은 쪽이 따뜻한 쪽(노랑)으로 안 간다"
   return None
