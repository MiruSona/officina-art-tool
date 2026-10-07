"""local 제공자의 한 판 계획. 네트워크를 안 부른다 — dry-run 과 실제 판이 같은 계획을 쓴다.

요청 검사 · 워크플로 고르기 · 자리표시 값 모으기 · inpaint 원본/마스크 크기 검사까지 여기서 끝낸다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import image
from ..errors import UsageError
from . import postproc, workflow
from .base import MAX_VARIANTS, ProviderRequest
from .local_config import LocalSettings

# dry-run 에서 아직 안 올린 그림 자리에 넣는 이름. 실제 판은 서버가 준 이름으로 채운다
MAX_SEED = 2**64 - 1
UPLOAD_STAND_IN = {"image": "<올릴 그림 : 원본>", "mask": "<올릴 그림 : 마스크>"}


@dataclass
class Plan:
   kind: str
   size: tuple[int, int]
   factor: int
   work_size: tuple[int, int]   # 모델에 주는 크기. size × factor 를 16 의 배수까지 덧댄 것
   workflow_name: str
   template: dict
   values: dict
   seeds: list[int]
   source: image.RGBA | None = None
   area: np.ndarray | None = None   # inpaint 고칠 곳 (요청 크기, bool)
   palette: list[tuple[int, int, int]] | None = None   # inpaint 마스크 안 색 맞추기. None 이면 안 맞춤
   warnings: list[str] = field(default_factory=list)

   @property
   def scaled_size(self) -> tuple[int, int]:
      """덧대기 전 크기. 결과에서 이만큼만 잘라 쓴다."""
      return (self.size[0] * self.factor, self.size[1] * self.factor)

   def base_name(self, index: int) -> str:
      return f"{self.kind}_{index:03d}"

   def raw_name(self, index: int, width: int) -> str:
      return f"raw/{self.base_name(index)}_{width}.png"

   def filled(self, index: int, uploads: dict) -> dict:
      """variant 하나의 워크플로. uploads 는 $image · $mask 에 넣을 서버 쪽 이름."""
      values = {**self.values, **uploads, "seed": self.seeds[index]}
      return workflow.fill(self.template, values)

   def would_write(self) -> list[str]:
      names = []
      for index in range(len(self.seeds)):
         names.append(f"{self.base_name(index)}.png")
         names.append(self.raw_name(index, self.work_size[0]))
      return names


def build_plan(req: ProviderRequest, settings: LocalSettings) -> Plan:
   _check_request(req, settings.work_size)
   template, name = _pick_workflow(req.kind, settings.workflow)
   first = req.seed if req.seed is not None else random.randrange(0, 2**31)
   size = (req.size[0], req.size[1])
   factor, work_size = postproc.work_layout(size, settings.work_size)
   plan = Plan(
      kind=req.kind,
      size=size,
      factor=factor,
      work_size=work_size,
      workflow_name=name,
      template=template,
      values={},
      seeds=[int(first) + i for i in range(req.variants)],
   )
   width, height = plan.work_size
   # 모델 키가 기본 자리 이름과 겹치면 기본 자리가 이긴다
   plan.values = {**settings.models, "prompt": req.prompt, "negative": req.negative, "width": width, "height": height}
   if req.kind == "inpaint":
      _load_inpaint(plan, req)
      plan.palette = snap_palette(plan, settings)
      if plan.palette == []:
         raise UsageError("마스크 안 색을 맞출 색이 없다 (원본이 다 투명하면 extra_colors 를 준다)")
   if name in settings.heavy:
      plan.warnings.append(f"무거운 판 : {name} 은 피크 ~25GB. 다른 큰 프로세스(LLM 서버 등)를 내린 뒤 돌린다")
   plan.filled(0, dict(UPLOAD_STAND_IN))   # 남은 자리가 있으면 여기서 종료 2 — dry-run 도 같이 멈춘다
   return plan


def snap_palette(plan: Plan, settings: LocalSettings) -> list[tuple[int, int, int]] | None:
   """마스크 안 색 맞추기에 쓸 색. snap=none 이면 None."""
   extra = postproc.parse_colors(settings.extra_colors, "extra_colors")
   if settings.snap == "none":
      return None
   if settings.snap == "profile":
      if settings.palette is None:
         raise UsageError("snap 이 profile 이면 spec 에 palette 색 목록이 있어야 한다")
      return postproc.parse_colors(settings.palette, "palette") + extra
   return sorted(image.opaque_colors(plan.source)) + extra


def _check_request(req: ProviderRequest, work_size: int) -> None:
   """요청 값의 꼴 · 범위를 본다. 모두 종료 2."""
   size = req.size
   if len(size) != 2 or not all(_is_int(v) and v > 0 for v in size):
      raise UsageError(f"size 는 양의 정수 둘이다 : {list(size)!r}")
   if max(size) > work_size:
      raise UsageError(f"size 의 긴 변 {max(size)} 이 work_size {work_size} 보다 크다")
   if not _is_int(req.variants) or not 1 <= req.variants <= MAX_VARIANTS:
      raise UsageError(f"variants 는 1~{MAX_VARIANTS} 사이 정수다 : {req.variants!r}")
   if req.seed is not None:
      if not _is_int(req.seed) or req.seed < 0 or req.seed + req.variants - 1 > MAX_SEED:
         raise UsageError(f"seed 는 0 이상 정수이고 seed + variants - 1 이 2^64-1 을 넘지 않아야 한다 : {req.seed!r}")
   if not isinstance(req.prompt, str) or not isinstance(req.negative, str):
      raise UsageError("prompt · negative 는 글자여야 한다")


def _is_int(value) -> bool:
   return isinstance(value, int) and not isinstance(value, bool)


def _pick_workflow(kind: str, path: str | None) -> tuple[dict, str]:
   if path:
      return workflow.load_file(path), Path(path).name
   return workflow.load_builtin(kind), workflow.BUILTIN[kind]


def _load_inpaint(plan: Plan, req: ProviderRequest) -> None:
   if not req.reference or not req.mask:
      raise UsageError("inpaint 는 원본(reference)과 마스크(mask)가 둘 다 있어야 한다")
   source = image.load(req.reference)
   mask = image.load(req.mask)
   if image.size(source) != plan.size:
      raise UsageError(f"inpaint 원본 크기 {image.size(source)} 가 요청 size {plan.size} 와 다르다")
   if image.size(mask) != plan.size:
      raise UsageError(f"마스크 크기 {image.size(mask)} 가 원본 {plan.size} 와 다르다")
   plan.source = source
   plan.area = postproc.mask_area(mask)
   if not plan.area.any():
      raise UsageError("마스크에 흰 칸(고칠 곳)이 없다")
