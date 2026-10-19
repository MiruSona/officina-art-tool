"""로컬 그림 모델 제공자. ComfyUI 주소가 있을 때만 켜진다 (환경변수 또는 설정 파일).

1차는 prop(새 그림) · inpaint 둘. 흐름 표는 설계 문서 1절(`Docs/Design/2026-10-07-provider-local설계.md`).
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from .. import image
from ..errors import ArtToolError, UsageError
from ..jsonio import write_json
from ..paths import resolve_root, safe_join
from . import postproc, workflow
from .base import Provider, ProviderRequest, ProviderResult
from .comfy import ComfyClient
from .local_config import ENV_ENDPOINT, LocalSettings, configured_endpoint, load_settings
from .local_plan import UPLOAD_BACKGROUND, UPLOAD_STAND_IN, Plan, build_plan

# 같은 서버를 여러 세션이 함께 써도 남의 원본을 덮지 않게 프로세스마다 이름을 가른다
UPLOAD_NAMES = {"image": f"arttool_image_{os.getpid()}.png", "mask": f"arttool_mask_{os.getpid()}.png"}

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
      # 이름이 늘 prop_000 부터라 지난 판 위에 쓰면 일부만 덮여 결과 JSON 의 seed 와 그림이 어긋난다
      taken = [name for name in plan.would_write() if safe_join(root, name).exists()]
      if taken:
         raise UsageError(f"출력 폴더에 지난 판 파일이 있다 : {taken[0]}{f' 외 {len(taken) - 1}개' if len(taken) > 1 else ''}. 빈 폴더를 준다 ({root})")
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
         "clear_background": _clear_request(plan),
         "would_write": plan.would_write(),
         "warnings": plan.warnings,
      }
      if plan.kind == "inpaint":
         request["upload_background"] = list(UPLOAD_BACKGROUND)   # 바탕을 올리는 건 inpaint 뿐 — 다른 판은 칸이 없다
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
      images, raws, cleared, warnings = [], [], [], list(plan.warnings)
      outside = 0
      try:
         for index in range(len(plan.seeds)):
            out_path, raw_path, changed, count = _one_variant(client, plan, root, index, uploads, save_ids, warnings)
            images.append(str(out_path))
            raws.append(str(raw_path))
            outside += changed
            cleared.append(count)
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
         meta["cleared"] = cleared
      return ProviderResult(images=images, meta=meta, provider=self.name, cost_usd=0.0, seed=plan.seeds[0],
                            warnings=warnings)

   def _upload(self, client: ComfyClient, plan: Plan) -> dict:
      """원본 · 마스크를 정수 배율로 키우고 16 배수까지 덧대 올린다. 덧댄 칸은 안 고침.

      ComfyUI LoadImage 는 알파를 버려 투명 칸이 검정으로 들어간다. 그래서 원본은 투명 칸(덧댄 칸 포함)을
      바탕색 위에 깔아 불투명하게 올린다. 마스크 밖은 돌려받은 뒤 원본 RGBA 로 되돌리니 투명이 남는다.
      """
      if plan.kind != "inpaint":
         return {}
      source = postproc.pad_to(postproc.upscale_nearest(plan.source, plan.factor), plan.work_size)
      alpha = source[:, :, 3:4].astype(np.float32) / 255.0
      rgb = source[:, :, :3] * alpha + np.array(UPLOAD_BACKGROUND, dtype=np.float32) * (1.0 - alpha)
      source = np.dstack([np.rint(rgb).astype(np.uint8), np.full(source.shape[:2], 255, dtype=np.uint8)])
      mask = postproc.upscale_nearest(postproc.mask_picture(plan.area), plan.factor)
      mask = postproc.pad_to(mask, plan.work_size)
      image_name = client.upload_image(postproc.to_png(source), UPLOAD_NAMES["image"])
      return {"image": image_name, "mask": client.upload_image(postproc.to_png(mask), UPLOAD_NAMES["mask"])}


def _one_variant(client, plan: Plan, root: Path, index: int, uploads: dict, save_ids: list[str], warnings: list[str]):
   """variant 하나 : 줄 세우기 → 기다리기 → 받기 → raw 저장 → 덧댄 칸 잘라 내기 → 축소 → (inpaint 마무리) → 저장.

   반환 (그림 경로, raw 경로, 밖 바뀐 칸, 걷은 바탕 칸). 바탕색인데 갇혀 남긴 칸은 warnings 에 더한다.
   """
   prompt_id = client.queue_prompt(plan.filled(index, uploads))
   found = _output_images(client.wait(prompt_id), save_ids)
   if len(found) > 1:
      warnings.append(f"결과가 {len(found)}장이라 첫 장만 썼다 ({plan.base_name(index)})")
   raw = postproc.from_png(client.fetch_image(*found[0]), max_side=2 * max(plan.work_size))
   raw_path = safe_join(root, plan.raw_name(index, image.size(raw)[0]))
   image.save(raw_path, raw)
   # 워크플로가 다른 크기로 돌려줘도 덧댄 칸은 같은 비율로 잘라 낸다 — 덧댄 칸까지 줄이면 그림이 밀린다
   raw_w, raw_h = image.size(raw)
   work_w, work_h = plan.work_size
   width, height = plan.scaled_size
   raw = raw[:round(height * raw_h / work_h), :round(width * raw_w / work_w)]
   small = postproc.downscale_box(raw, plan.size)
   changed, cleared = 0, 0
   if plan.kind == "inpaint":
      small, changed, cleared, enclosed = _finish_inpaint(plan, small)
      if enclosed:
         warnings.append(f"{plan.base_name(index)} : 바탕색인데 바깥 투명과 안 이어져 남긴 칸 {enclosed}개 "
                         "(원본 구멍이면 cutout --key 로 그 칸 색을 지운다)")
   out_path = safe_join(root, f"{plan.base_name(index)}.png")
   image.save(out_path, small)
   return out_path, raw_path, changed, cleared


def _finish_inpaint(plan: Plan, small: image.RGBA) -> tuple[image.RGBA, int, int, int]:
   """올림 바탕 걷기 → 마스크 안 색 맞추기 → 밖 원본 덮어쓰기 → 밖 바뀐 칸 세기. 밖이 0 이 아니면 계약 위반이라 멈춘다.

   snap 은 칸을 불투명으로 만들어서, 걷은 칸은 snap 범위에서 뺀다. 반환은 (그림, 밖 바뀐 칸, 걷은 칸, 갇혀 남긴 칸).
   """
   cleared = np.zeros(plan.area.shape, dtype=bool)
   enclosed = 0
   if plan.clear_tol is not None:
      small, cleared, enclosed = postproc.clear_background(small, plan.source, plan.area, UPLOAD_BACKGROUND,
                                                           plan.clear_tol)
   if plan.palette is not None:
      small = postproc.snap_colors(small, plan.area & ~cleared, plan.palette)
   small = postproc.composite_outside(small, plan.source, plan.area)
   changed = postproc.count_outside_changed(small, plan.source, plan.area)
   if changed:
      raise ArtToolError(f"inpaint 마스크 밖이 {changed}칸 바뀌었다 (계약 위반)")
   return small, changed, int(cleared.sum()), enclosed


def _clear_request(plan: Plan) -> dict | None:
   """dry-run 에 남길 올림 바탕 걷기 설정. prop · 끈 판은 None."""
   if plan.clear_tol is None:
      return None
   return {"color": list(UPLOAD_BACKGROUND), "tol": plan.clear_tol}


def _output_images(entry: dict, save_ids: list[str]) -> list[tuple[str, str, str]]:
   """history 기록에서 SaveImage 노드 결과를 id 순으로 (파일 이름, 하위 폴더, 종류) 로 모은다."""
   outputs = entry.get("outputs")
   if not isinstance(outputs, dict):
      outputs = {}
   found = []
   for node_id in save_ids:
      node = outputs.get(node_id)
      for item in (node.get("images") if isinstance(node, dict) else None) or []:
         if isinstance(item, dict) and isinstance(item.get("filename"), str):
            found.append((item["filename"], str(item.get("subfolder") or ""), str(item.get("type") or "output")))
   if not found:
      raise ArtToolError("ComfyUI 판은 끝났는데 SaveImage 결과 그림이 없다")
   return found
