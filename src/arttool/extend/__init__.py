"""늘리기 묶음 `arttool extend` (피드백 후속 설계 3-5).

셋 다 줄 · 칸을 되풀이하거나 빼기만 한다. 크기를 늘이고 줄이는 보간은 안 한다 — 도트가 뭉개진다.

| 모듈 | 하는 일 |
| --- | --- |
| `period` | 띠에서 되풀이 단위 찾기 · 타일 크기에 맞춰 한 단위 자르기 |
| `ring` | 한 바퀴 그림(모서리 · 변 단위) 늘리기 — `ui.ninepatch.slice_stretch` 를 부르기만 한다 |
| `canvas` | 배경 늘리기 — 가장자리 띠를 바깥으로 되풀이 |
"""

from __future__ import annotations

from ..errors import UsageError


def parse_size(text: str, what: str = "--size") -> tuple[int, int]:
   """`WxH` 하나를 (너비, 높이) 로. 양수만 받는다."""
   pieces = str(text).strip().lower().split("x")
   try:
      width, height = (int(p) for p in pieces)
   except ValueError as exc:
      raise UsageError(f"{what} 는 WxH 꼴이다 : {text}") from exc
   if width <= 0 or height <= 0:
      raise UsageError(f"{what} 는 양수다 : {text}")
   return width, height
