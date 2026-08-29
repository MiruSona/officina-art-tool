"""제공자 인터페이스와 등록소.

제공자는 없는 그림을 만드는 자리만 맡는다. 규격·앵커·검수·굽기는 제공자를 안 탄다.
키가 없는 제공자는 오류가 아니라 목록에서 빠진다. 대놓고 고른 제공자만 오류로 멈춘다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..errors import ArtToolError

KINDS = ("character", "tile", "rotate", "skeleton")


@dataclass
class ProviderRequest:
   kind: str
   out_dir: Path
   size: tuple[int, int] = (64, 64)
   projection: str = "quarter"
   directions: int = 4
   frames: int = 1
   reference: str | None = None
   prompt: str = ""
   seed: int | None = None
   dry_run: bool = False

   def validate(self) -> None:
      if self.kind not in KINDS:
         raise ArtToolError(f"모르는 kind : {self.kind} (쓸 수 있는 것 : {', '.join(KINDS)})")
      if self.frames < 1 or self.directions < 1:
         raise ArtToolError("frames · directions 는 1 이상이다")

   def count(self) -> int:
      return self.frames * self.directions

   def to_json(self) -> dict:
      return {
         "kind": self.kind,
         "size": list(self.size),
         "projection": self.projection,
         "directions": self.directions,
         "frames": self.frames,
         "reference": self.reference,
         "prompt": self.prompt,
         "seed": self.seed,
      }


@dataclass
class ProviderResult:
   images: list[str] = field(default_factory=list)
   meta: dict = field(default_factory=dict)
   provider: str = ""
   cost_usd: float = 0.0
   seed: int | None = None
   warnings: list[str] = field(default_factory=list)

   def to_json(self) -> dict:
      return {
         "images": list(self.images),
         "meta": dict(self.meta),
         "provider": self.provider,
         "cost_usd": self.cost_usd,
         "seed": self.seed,
         "warnings": list(self.warnings),
      }


class Provider:
   name = "base"

   def available(self) -> bool:
      raise NotImplementedError

   def capabilities(self) -> set[str]:
      raise NotImplementedError

   def estimate(self, req: ProviderRequest) -> float:
      return 0.0

   def make(self, req: ProviderRequest) -> ProviderResult:
      raise NotImplementedError

   def require_kind(self, req: ProviderRequest) -> None:
      req.validate()
      if req.kind not in self.capabilities():
         raise ArtToolError(f"{self.name} 제공자는 {req.kind} 를 못 만든다")


_REGISTRY: dict[str, Provider] = {}


def register(provider: Provider) -> None:
   _REGISTRY[provider.name] = provider


def all_names() -> list[str]:
   return sorted(_REGISTRY)


def available_names() -> list[str]:
   return sorted(name for name, p in _REGISTRY.items() if p.available())


def get(name: str) -> Provider:
   if name not in _REGISTRY:
      raise ArtToolError(f"모르는 제공자 : {name} (있는 것 : {', '.join(all_names())})")
   provider = _REGISTRY[name]
   if not provider.available():
      raise ArtToolError(f"{name} 제공자를 골랐는데 켤 수 없다 (키·엔드포인트 설정을 본다)")
   return provider


def describe() -> list[dict]:
   rows = []
   for name in all_names():
      provider = _REGISTRY[name]
      rows.append(
         {
            "name": name,
            "available": provider.available(),
            "capabilities": sorted(provider.capabilities()),
         }
      )
   return rows
