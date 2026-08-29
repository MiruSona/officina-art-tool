"""로컬 이미지 모델 제공자. 엔드포인트 설정이 있을 때만 켜진다.

미니PC 에 올릴 모델을 아직 안 골랐다. 그래서 요청 JSON 만 만들고 견적을 낸다.
"""

from __future__ import annotations

import os

from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from .base import Provider, ProviderRequest, ProviderResult

ENV_ENDPOINT = "ARTTOOL_LOCAL_ENDPOINT"


class LocalProvider(Provider):
   name = "local"

   def available(self) -> bool:
      return bool(os.environ.get(ENV_ENDPOINT))

   def capabilities(self) -> set[str]:
      return {"character", "tile", "rotate"}

   def estimate(self, req: ProviderRequest) -> float:
      return 0.0

   def make(self, req: ProviderRequest) -> ProviderResult:
      self.require_kind(req)
      root = resolve_root(req.out_dir)
      request_file = safe_join(root, "local_request.json")
      write_json(request_file, req.to_json())
      if req.dry_run:
         warn = "로컬 모델은 돈이 안 든다. 대신 미니PC 메모리를 쓴다"
         return ProviderResult(provider=self.name, cost_usd=0.0, meta={"request": str(request_file)}, warnings=[warn])
      raise ArtToolError("로컬 모델 호출은 아직 안 붙였다. --dry-run 으로 요청 JSON 만 낸다")
