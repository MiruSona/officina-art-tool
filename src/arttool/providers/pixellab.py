"""PixelLab 제공자. PIXELLAB_API_KEY 가 있을 때만 켜진다.

키는 환경변수로만 읽고 요청 JSON · 산출물 · 로그 어디에도 안 적는다.
단가를 아직 안 쟀다. PIXELLAB_COST_PER_IMAGE 로 넣어 주면 그 값으로 견적을 낸다.
"""

from __future__ import annotations

import os

from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from .base import Provider, ProviderRequest, ProviderResult

ENV_KEY = "PIXELLAB_API_KEY"
ENV_COST = "PIXELLAB_COST_PER_IMAGE"


class PixelLabProvider(Provider):
   name = "pixellab"

   def available(self) -> bool:
      return bool(os.environ.get(ENV_KEY))

   def capabilities(self) -> set[str]:
      return {"character", "tile", "rotate", "skeleton"}

   def unit_cost(self) -> float | None:
      raw = os.environ.get(ENV_COST)
      if not raw:
         return None
      try:
         return float(raw)
      except ValueError as exc:
         raise ArtToolError(f"{ENV_COST} 가 숫자가 아니다") from exc

   def estimate(self, req: ProviderRequest) -> float:
      unit = self.unit_cost()
      if unit is None:
         return 0.0
      return round(unit * req.count(), 4)

   def make(self, req: ProviderRequest) -> ProviderResult:
      self.require_kind(req)
      root = resolve_root(req.out_dir)
      request_file = safe_join(root, "pixellab_request.json")
      write_json(request_file, req.to_json())

      warnings = []
      if self.unit_cost() is None:
         warnings.append(f"단가를 아직 안 쟀다. {ENV_COST} 를 넣으면 견적이 나온다")
      if req.dry_run:
         meta = {"request": str(request_file), "images": req.count()}
         return ProviderResult(provider=self.name, cost_usd=self.estimate(req), meta=meta, warnings=warnings)
      raise ArtToolError("PixelLab 실제 호출은 아직 안 붙였다. --dry-run 으로 요청 JSON 과 견적만 낸다")
