"""`arttool shape render` — 명세 JSON 한 장 → PNG 한 장 (도형 렌더러 설계 5절).

보고 : view · yaw · 색 수 · 렌더 시간(ms) · lint 결과, `--ref` 를 주면 원본 대비 닮음(`score`).
lint 에 걸려도 `status` 는 warn 이고 종료 0 이다.
"""

from __future__ import annotations

from .. import image
from ..errors import UsageError
from ..paths import guard_overwrite, jailed_output
from . import spec as spec_mod
from .render import render
from .score import similarity


def run(args) -> dict:
   out = jailed_output(args.out_file)
   if out.suffix.lower() != ".png":
      raise UsageError(f"--out 은 .png 다 : {args.out_file}")
   guard_overwrite([out], [args.spec, getattr(args, "ref", None)], "--out")
   spec = spec_mod.load(args.spec)
   arr, report = render(spec, args.view)
   if getattr(args, "ref", None):
      report["score"] = similarity(arr, image.load(args.ref))
   image.save(out, arr)
   report["out"] = str(out)
   report["status"] = "ok" if report["lint"]["status"] == "ok" else "warn"
   return report
