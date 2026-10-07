"""로컬 그림 모델 제공자. ComfyUI 주소가 있을 때만 켜진다 (환경변수 또는 설정 파일).

1차는 prop(새 그림) · inpaint 둘. 흐름 표는 설계 문서 1절(`Docs/Design/2026-10-07-provider-local설계.md`).
"""

from __future__ import annotations

import time
from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from . import postproc, workflow
from .base import Provider, ProviderRequest, ProviderResult
from .comfy import ComfyClient
from .local_config import ENV_ENDPOINT, LocalSettings, configured_endpoint, load_settings
from .local_plan import UPLOAD_STAND_IN, Plan, build_plan

__all__ = ["ENV_ENDPOINT", "LocalProvider"]


class LocalProvider(Provider):
   name = "local"

   def available(self) -> bool:
      try:
         return bool(configured_endpoint())
      except ArtToolError:
         return False   # 설정 파일이 깨졌으면 목록에서 빠진다. 대놓고 고르면 get 이 「켤 수 없다」로 멈춘다

   def capabilities(self) -> set[str]:
      return {"prop", "inpaint"}

   def estimate(self, req: ProviderRequest) -> float:
      return 0.0

   def make(self, req: ProviderRequest) -> ProviderResult:
      self.require_kind(req)
      settings = load_settings(req.kind, req.options)
      plan = build_plan(req, settings)
      root = resolve_root(req.out_dir)
      if req.dry_run:
         return self._dry_run(req, settings, plan, root)
      return self._run(settings, plan, root)

   def _dry_run(self, req: ProviderRequest, settings: LocalSettings, plan: Plan, root: Path) -> ProviderResult:
      """네트워크를 하나도 안 부른다. 채운 워크플로 · 올릴 그림 · 쓸 파일을 local_request.json 에 남긴다."""
      uploads = []
      if plan.kind == "inpaint":
         width, height = plan.work_size
         uploads = [f"{UPLOAD_STAND_IN[key]} {width}x{height}" for key in ("image", "mask")]
      request = {
         "request": req.to_json(),
         "endpoint": settings.host,
         "workflow": plan.workflow_name,
         "work_size": list(plan.work_size),
         "seeds": plan.seeds,
         "workflows": [plan.filled(index, dict(UPLOAD_STAND_IN)) for index in range(len(plan.seeds))],
         "uploads": uploads,
         "would_write": plan.would_write(),
         "warnings": plan.warnings,
      }
      request_file = safe_join(root, "local_request.json")
      write_json(request_file, request)
      warnings = ["로컬 모델은 돈이 안 든다. 대신 서버 메모리를 쓴다", *plan.warnings]
      meta = {"request": str(request_file), "would_write": plan.would_write(), "endpoint": settings.host}
      return ProviderResult(provider=self.name, cost_usd=0.0, seed=plan.seeds[0], meta=meta, warnings=warnings)

   def _run(self, settings: LocalSettings, plan: Plan, root: Path) -> ProviderResult:
      started = time.monotonic()
      client = ComfyClient(settings.endpoint, timeout_s=settings.timeout_s)
      client.system_stats()
      client.require_nodes(workflow.class_types(plan.template))
      uploads = self._upload(client, plan)
      save_ids = workflow.save_nodes(plan.template)
      images, raws, warnings = [], [], list(plan.warnings)
      outside = 0
      try:
         for index in range(len(plan.seeds)):
            out_path, raw_path, changed = _one_variant(client, plan, root, index, uploads, save_ids, warnings)
            images.append(str(out_path))
            raws.append(str(raw_path))
            outside += changed
      except ArtToolError as exc:
         if not images:
            raise
         written = ", ".join(Path(p).name for p in images)
         raise type(exc)(f"{exc} (이미 쓴 파일 {len(images)}장 : {written} · raw 는 raw/ 아래)") from exc
      meta = {
         "raw": raws,
         "seconds": round(time.monotonic() - started, 2),
         "workflow": plan.workflow_name,
         "endpoint": settings.host,
      }
      if plan.kind == "inpaint":
         meta["outside_changed"] = outside
      return ProviderResult(images=images, meta=meta, provider=self.name, cost_usd=0.0, seed=plan.seeds[0],
                            warnings=warnings)

   def _upload(self, client: ComfyClient, plan: Plan) -> dict:
      """원본 · 마스크를 정수 배율로 키우고 16 배수까지 덧대 올린다. 덧댄 칸은 투명 · 안 고침."""
      if plan.kind != "inpaint":
         return {}
      source = postproc.pad_to(postproc.upscale_nearest(plan.source, plan.factor), plan.work_size)
      mask = postproc.upscale_nearest(postproc.mask_picture(plan.area), plan.factor)
      mask = postproc.pad_to(mask, plan.work_size)
      image_name = client.upload_image(postproc.to_png(source))
      return {"image": image_name, "mask": client.upload_image(postproc.to_png(mask))}


def _one_variant(client, plan: Plan, root: Path, index: int, uploads: dict, save_ids: list[str], warnings: list[str]):
   """variant 하나 : 줄 세우기 → 기다리기 → 받기 → raw 저장 → 덧댄 칸 잘라 내기 → 축소 → (inpaint 마무리) → 저장."""
   prompt_id = client.queue_prompt(plan.filled(index, uploads))
   found = _output_images(client.wait(prompt_id), save_ids)
   if len(found) > 1:
      warnings.append(f"결과가 {len(found)}장이라 첫 장만 썼다 ({plan.base_name(index)})")
   raw = postproc.from_png(client.fetch_image(*found[0]), max_side=2 * max(plan.work_size))
   raw_path = safe_join(root, plan.raw_name(index, image.size(raw)[0]))
   image.save(raw_path, raw)
   if image.size(raw) == plan.work_size:
      width, height = plan.scaled_size
      raw = raw[:height, :width]
   small = postproc.downscale_box(raw, plan.size)
   changed = 0
   if plan.kind == "inpaint":
      small, changed = _finish_inpaint(plan, small)
   out_path = safe_join(root, f"{plan.base_name(index)}.png")
   image.save(out_path, small)
   return out_path, raw_path, changed


def _finish_inpaint(plan: Plan, small: image.RGBA) -> tuple[image.RGBA, int]:
   """마스크 안 색 맞추기 → 밖 원본 덮어쓰기 → 밖 바뀐 칸 세기. 0 이 아니면 계약 위반이라 멈춘다."""
   if plan.palette is not None:
      small = postproc.snap_colors(small, plan.area, plan.palette)
   small = postproc.composite_outside(small, plan.source, plan.area)
   changed = postproc.count_outside_changed(small, plan.source, plan.area)
   if changed:
      raise ArtToolError(f"inpaint 마스크 밖이 {changed}칸 바뀌었다 (계약 위반)")
   return small, changed


def _output_images(entry: dict, save_ids: list[str]) -> list[tuple[str, str, str]]:
   """history 기록에서 SaveImage 노드 결과를 id 순으로 (파일 이름, 하위 폴더, 종류) 로 모은다."""
   outputs = entry.get("outputs") or {}
   found = []
   for node_id in save_ids:
      for item in (outputs.get(node_id) or {}).get("images") or []:
         if isinstance(item, dict) and isinstance(item.get("filename"), str):
            found.append((item["filename"], str(item.get("subfolder") or ""), str(item.get("type") or "output")))
   if not found:
      raise ArtToolError("ComfyUI 판은 끝났는데 SaveImage 결과 그림이 없다")
   return found
