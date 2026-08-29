"""기본 제공자. 그림을 안 만든다. 이미 있는 에셋에서 잘라 내놓기만 한다."""

from __future__ import annotations

from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..paths import resolve_root, safe_join
from .base import Provider, ProviderRequest, ProviderResult


class CodeProvider(Provider):
   name = "code"

   def available(self) -> bool:
      return True

   def capabilities(self) -> set[str]:
      return {"character", "tile"}

   def estimate(self, req: ProviderRequest) -> float:
      return 0.0

   def make(self, req: ProviderRequest) -> ProviderResult:
      self.require_kind(req)
      if not req.reference:
         raise ArtToolError("code 제공자는 잘라 올 참조 그림이 있어야 한다")

      frames = self._cut(Path(req.reference), req)
      if req.dry_run:
         return ProviderResult(provider=self.name, meta={"would_write": len(frames)}, warnings=["dry-run 이라 안 썼다"])

      root = resolve_root(req.out_dir)
      written = []
      for index, frame in enumerate(frames):
         out = safe_join(root, f"{req.kind}_{index:03d}.png")
         image.save(out, frame)
         written.append(str(out))
      meta = {"size": list(req.size), "directions": req.directions, "frames": req.frames}
      return ProviderResult(images=written, meta=meta, provider=self.name, cost_usd=0.0, seed=req.seed)

   def _cut(self, reference: Path, req: ProviderRequest) -> list[image.RGBA]:
      want = req.count()
      frames = self._cut_dir(reference) if reference.is_dir() else self._cut_sheet(reference, req)
      if len(frames) < want:
         raise ArtToolError(f"참조 그림에서 {len(frames)}장밖에 못 잘랐다. {want}장이 필요하다")
      return frames[:want]

   def _cut_dir(self, folder: Path) -> list[image.RGBA]:
      files = sorted(folder.glob("*.png"))
      if not files:
         raise ArtToolError(f"참조 폴더에 PNG 가 없다 : {folder}")
      return [image.load(f) for f in files]

   def _cut_sheet(self, path: Path, req: ProviderRequest) -> list[image.RGBA]:
      width, height = req.size
      rows = image.split_grid(image.load(path), width, height)
      return [frame for row in rows for frame in row]
