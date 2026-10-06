"""L — 두 덩이 그림의 빛 판정 (6판 설계 6장).

그림은 시험 안에서 손으로 만든다 : 검정 외곽선을 두른 원에 한 램프(같은 색조 세 단)로 음영을 넣는다.
옛 셈 기대값(OLD)은 HEAD 소스(덩이 나누기 없던 판)로 같은 그림을 돌려 뽑은 숫자다.
"""

from __future__ import annotations

import json
import time

import numpy as np
from PIL import Image

from arttool import cli
from arttool.style.light import estimate_light

RAMP = [(230, 120, 90), (190, 80, 60), (140, 50, 35)]   # 밝음 · 중간 · 어두움 (같은 색조)
BLACK = (0, 0, 0)


def _canvas(w: int, h: int) -> np.ndarray:
   return np.zeros((h, w, 4), dtype=np.uint8)


def _disc(arr: np.ndarray, cx: int, cy: int, r: int, toward: tuple[float, float], lit: float = 0.3) -> None:
   """외곽선 두른 원. toward = 빛이 오는 쪽(단위 벡터, 오른쪽 · 아래가 +). lit 이 클수록 밝은 단이 넓다."""
   tx, ty = toward
   for y in range(cy - r - 1, cy + r + 2):
      for x in range(cx - r - 1, cx + r + 2):
         d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
         if d > r + 1:
            continue
         if d > r:
            arr[y, x] = (*BLACK, 255)
            continue
         s = ((x - cx) * tx + (y - cy) * ty) / r     # -1 ~ 1, 빛 쪽이 +
         shade = 0 if s > 1 - 2 * lit else 1 if s > -0.4 else 2
         arr[y, x] = (*RAMP[shade], 255)


UL = (-0.7071, -0.7071)   # 왼쪽 위에서 오는 빛
UR = (0.7071, -0.7071)


def _black_lines(arr: np.ndarray, xs=(), ys=()) -> None:
   """불투명 칸 위에만 검정 선을 긋는다 — 외곽선이 안을 가르는 한 캐릭터."""
   inside = arr[..., 3] > 0
   for x in xs:
      arr[inside[:, x], x] = (*BLACK, 255)
   for y in ys:
      arr[y, inside[y]] = (*BLACK, 255)


def one_piece_case(name: str) -> np.ndarray:
   """한 덩이 그림들 — 투명으로 떨어진 뜻 있는 덩이는 하나뿐이다."""
   arr = _canvas(32, 32)
   _disc(arr, 16, 16, 12, UL)
   if name == "vline1":
      _black_lines(arr, xs=(16,))
   elif name == "vline3":
      _black_lines(arr, xs=(10, 16, 22))
   elif name == "grid":
      _black_lines(arr, xs=(10, 16, 22), ys=(10, 16, 22))
   elif name == "belt":
      _black_lines(arr, ys=(17, 18))
   elif name == "speck3":
      arr[30, 0] = arr[31, 0] = arr[30, 1] = (*RAMP[2], 255)
   elif name == "speck10":
      arr[30:32, 0:5] = (*RAMP[0], 255)
   elif name == "deco12":
      # 작은 장식(12칸, 큰 덩이의 10% 미만) — 오른쪽 위에서 빛 받은 꼴
      arr[0:3, 27:31] = (*RAMP[2], 255)
      arr[0, 30] = arr[1, 30] = (*RAMP[0], 255)
   return arr


# HEAD 소스(덩이 나누기 없던 판)로 뽑은 옛 셈 값 : (light, dx, dy, shift, size)
OLD = {
   "plain": ("top_left", -5.24, -5.24, 0.2745, 27),
   "vline1": ("top_left", -5.529, -5.018, 0.2765, 27),
   "vline3": ("top_left", -5.496, -4.982, 0.2747, 27),
   "grid": ("top_left", -5.243, -5.243, 0.2746, 27),
   "belt": ("top_left", -4.87, -5.614, 0.2753, 27),
   "speck3": ("top_left", -5.014, -5.383, 0.2452, 30),
   "speck10": ("top_left", -5.49, -4.35, 0.2335, 30),
   "deco12": ("top_left", -5.428, -4.61, 0.2374, 30),
}


def test_one_piece_cases_match_old():
   # 선으로 갈린 한 덩이 · 티끌 · 작은 장식 — 한 덩이로 세고 값이 옛 셈과 똑같다
   for name, old in OLD.items():
      out = estimate_light(one_piece_case(name))
      assert out["pieces"] == 1, name
      assert out["confidence"] == "high", name
      assert (out["light"], out["dx"], out["dy"], out["shift"], out["size"]) == old, name


def test_two_pieces_same_light_top_left():
   # 투명으로 떨어진 두 덩이, 앞(아래 오른쪽) 덩이가 더 밝다.
   # 옛 셈(램프 하나 = 무게중심 하나)은 이 그림을 「bottom」 으로 읽었다 (구현 첫 판에서 옛 소스로 확인).
   arr = _canvas(48, 48)
   _disc(arr, 13, 13, 10, UL, lit=0.05)
   _disc(arr, 34, 34, 10, UL, lit=0.9)
   out = estimate_light(arr)
   assert out["light"] == "top_left"
   assert out["confidence"] == "high"
   assert out["pieces"] == 2


def test_two_pieces_opposite_light_low():
   arr = _canvas(48, 24)
   _disc(arr, 11, 12, 9, UL)
   _disc(arr, 36, 12, 9, UR)
   out = estimate_light(arr)
   assert out["confidence"] == "low"
   assert out["pieces"] == 2


def test_empty_image():
   out = estimate_light(_canvas(8, 8))
   assert out["light"] == "unknown"
   assert out["confidence"] == "high"
   assert out["pieces"] == 0


def test_many_pieces():
   arr = _canvas(120, 120)
   for gy in range(6):
      for gx in range(6):
         _disc(arr, 10 + gx * 20, 10 + gy * 20, 7, UL)
   out = estimate_light(arr)
   assert out["pieces"] == 36
   assert out["confidence"] == "high"
   # 크기 기준이 그림 전체 긴 변이라 작은 덩이 여럿은 unknown 일 수 있다 — 치우침 방향만 본다
   assert out["dx"] < 0 and out["dy"] < 0


def _extract(tmp_path, arrays: list[np.ndarray], capsys) -> tuple[int, dict, str]:
   src = tmp_path / "in"
   src.mkdir()
   for i, arr in enumerate(arrays):
      Image.fromarray(arr, "RGBA").save(src / f"s{i}.png")
   code = cli.main(["style", "extract", "--in", str(src), "--out", str(tmp_path / "out"), "--name", "t"])
   report = json.loads(next((tmp_path / "out").rglob("*report.json")).read_text(encoding="utf-8"))
   return code, report, capsys.readouterr().out


def test_extract_mixed_reports_low(tmp_path, capsys):
   # 실제 길 : measure_one → 요약 → 보고 파일 · stdout
   mixed = _canvas(48, 24)
   _disc(mixed, 11, 12, 9, UL)
   _disc(mixed, 36, 12, 9, UR)
   arrays = [mixed] + [one_piece_case(n) for n in ("plain", "vline1", "speck3", "deco12")]
   code, report, out = _extract(tmp_path, arrays, capsys)
   assert code == 0
   assert report["status"] == "warn"
   assert report["light"]["low"] == 1
   assert [w for w in report["warnings"] if w["rule"] == "light_mixed"][0]["items"] == ["in/s0.png"]
   rows = {r["file"]: r for r in report["images"]}
   assert rows["in/s0.png"]["light_confidence"] == "low"
   assert all("light_confidence" not in rows[f"in/s{i}.png"] for i in range(1, 5))
   assert "light_mixed" in out


def test_extract_one_piece_has_no_low(tmp_path, capsys):
   # 작은 장식 · 티끌 · 선으로 갈린 그림만 — light_mixed 도 low 칸도 없다
   arrays = [one_piece_case(n) for n in ("plain", "vline3", "grid", "speck10", "deco12")]
   code, report, out = _extract(tmp_path, arrays, capsys)
   assert code == 0
   assert "low" not in report["light"]
   assert not any(w["rule"] == "light_mixed" for w in report["warnings"])
   assert "light_mixed" not in out


def test_noise_512_fast():
   # 칸마다 도는 파이썬 루프가 돌아오면 수십 초가 걸린다 — 문턱은 넉넉히
   rng = np.random.default_rng(7)
   colors = np.array([*RAMP, BLACK, (90, 160, 200), (50, 110, 150)], dtype=np.uint8)
   arr = _canvas(512, 512)
   arr[..., :3] = colors[rng.integers(0, len(colors), (512, 512))]
   arr[..., 3] = np.where(rng.random((512, 512)) < 0.6, 255, 0)
   start = time.perf_counter()
   estimate_light(arr)
   assert time.perf_counter() - start < 3.0


def test_many_small_pieces_fast():
   # 투명으로 떨어진 작은 덩이 수천 개 — 덩이 나누기 · 덩이별 판정이 느려지지 않는다
   arr = _canvas(512, 512)
   arr[..., :3] = RAMP[1]
   yy, xx = np.mgrid[0:512, 0:512]
   arr[..., 3] = np.where((yy % 6 < 4) & (xx % 6 < 4), 255, 0)
   arr[(yy % 6 == 0) & (xx % 6 < 4), :3] = RAMP[0]
   start = time.perf_counter()
   out = estimate_light(arr)
   assert time.perf_counter() - start < 3.0
   assert out["pieces"] > 1000
