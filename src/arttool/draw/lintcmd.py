"""`arttool lint` — 좌표 박힌 린트를 CLI 로 (draw 고리 설계 3절). 파일은 안 쓰고, 걸려도 종료 0.

입력 열기는 `grid show` 와 같다(겹 묶음 폴더 · PNG 한 장). `--template` 을 주면 팔레트 · 빛 · 외곽선 방식을 거기서 읽는다.
"""

from __future__ import annotations

from ..errors import ArtToolError, UsageError
from .canvas import Canvas
from .gridcmd import open_input
from .lint import pick_rules


def run(args) -> dict:
   rules = None
   if args.rules:
      rules = [r.strip() for r in args.rules.split(",") if r.strip()]
      try:
         pick_rules(rules)
      except ArtToolError as exc:
         raise UsageError(f"--rules : {exc}") from exc
   canvas, _folder = open_input(args)
   if args.template:
      ref = Canvas(canvas.size, template=args.template)
      canvas.ramps, canvas.light, canvas.outline_mode = ref.ramps, ref.light, ref.outline_mode
   return canvas.lint(rules=rules).to_dict()
