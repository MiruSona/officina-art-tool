"""local 제공자 설정 모으기. 앞이 이긴다 : spec(req.options) > 설정 파일 > 기본값. 주소만 환경변수 > 설정 파일.

칸과 차례 표는 설계 문서 4-1 절(`Docs/Design/2026-10-07-provider-local설계.md`). 저장소의 빈 본보기는 `local.example.yaml`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..errors import UsageError
from .comfy import parse_endpoint

ENV_ENDPOINT = "ARTTOOL_LOCAL_ENDPOINT"
ENV_CONFIG = "ARTTOOL_LOCAL_CONFIG"
DEFAULT_WORK_SIZE = 512
DEFAULT_TIMEOUT_S = 600.0
MAX_WORK_SIZE = 2048
SNAP_MODES = ("source", "profile", "none")
CONFIG_KEYS = ("endpoint", "models", "workflows", "work_size", "timeout_s", "heavy")
OPTION_KEYS = ("workflow", "models", "work_size", "extra_colors", "snap", "palette")
WORKFLOW_KEYS = ("prop", "inpaint")


@dataclass
class LocalSettings:
   endpoint: str = ""
   models: dict = field(default_factory=dict)
   workflow: str | None = None   # 사용자 워크플로 파일. 없으면 내장 본보기
   work_size: int = DEFAULT_WORK_SIZE
   timeout_s: float = DEFAULT_TIMEOUT_S
   heavy: list[str] = field(default_factory=list)
   snap: str = "source"
   extra_colors: list = field(default_factory=list)
   palette: list | None = None

   @property
   def host(self) -> str:
      """결과 · 로그에 남기는 주소는 host:port 까지만."""
      return parse_endpoint(self.endpoint)[1]


def read_config() -> dict:
   """ARTTOOL_LOCAL_CONFIG 의 YAML 을 읽는다. 환경변수가 없으면 빈 설정."""
   raw = os.environ.get(ENV_CONFIG)
   if not raw:
      return {}
   path = Path(raw)
   if not path.is_file():
      raise UsageError(f"{ENV_CONFIG} 가 가리키는 설정 파일이 없다 : {path.name}")
   try:
      data = yaml.safe_load(path.read_text(encoding="utf-8"))
   except (UnicodeDecodeError, yaml.YAMLError) as exc:
      raise UsageError(f"local 설정 파일을 못 읽었다 : {path.name} ({exc.__class__.__name__})") from None
   if data is None:
      return {}
   if not isinstance(data, dict):
      raise UsageError(f"local 설정 파일 맨 위는 표(키: 값)여야 한다 : {path.name}")
   return data


def configured_endpoint() -> str:
   """환경변수가 이긴다. 한 판만 다른 서버로 돌리기 쉽게."""
   env = os.environ.get(ENV_ENDPOINT)
   if env:
      return env
   endpoint = read_config().get("endpoint")
   if endpoint is None:
      return ""
   return str(endpoint)


def load_settings(kind: str, options: dict) -> LocalSettings:
   config = read_config()
   _known(config, CONFIG_KEYS, "설정 파일")
   _known(options, OPTION_KEYS, "spec")
   settings = LocalSettings(endpoint=configured_endpoint())
   settings.models = {**_models(config.get("models"), "설정 models"), **_models(options.get("models"), "spec models")}
   workflows = _table(config.get("workflows"), "설정 workflows")
   _known(workflows, WORKFLOW_KEYS, "설정 workflows")
   settings.workflow = _first(options.get("workflow"), _beside_config(workflows.get(kind)))
   settings.work_size = _work_size(_first(options.get("work_size"), config.get("work_size"), DEFAULT_WORK_SIZE))
   settings.timeout_s = _positive(_first(config.get("timeout_s"), DEFAULT_TIMEOUT_S), "timeout_s")
   settings.heavy = [str(name) for name in _list(config.get("heavy"), "설정 heavy")]
   settings.snap = _first(options.get("snap"), "source")
   if settings.snap not in SNAP_MODES:
      raise UsageError(f"snap 은 {' · '.join(SNAP_MODES)} 중 하나다 : {settings.snap!r}")
   settings.extra_colors = _list(options.get("extra_colors"), "extra_colors")
   settings.palette = options.get("palette")
   return settings


def _first(*values):
   """None 이 아닌 첫 값. 0 · 빈 글자를 「안 줌」으로 삼키지 않게 `or` 대신 쓴다."""
   for value in values:
      if value is not None:
         return value
   return None


def _known(table: dict, keys: tuple[str, ...], what: str) -> None:
   unknown = sorted(str(key) for key in table if key not in keys)
   if unknown:
      raise UsageError(f"{what}의 모르는 칸 : {', '.join(unknown)} (아는 칸 : {', '.join(keys)})")


def _beside_config(path) -> str | None:
   """설정 파일에 적은 상대 경로는 설정 파일 옆을 기준으로 푼다."""
   if not path:
      return None
   wanted = Path(str(path))
   if wanted.is_absolute():
      return str(wanted)
   return str(Path(os.environ[ENV_CONFIG]).parent / wanted)


def _table(value, what: str) -> dict:
   if value is None:
      return {}
   if not isinstance(value, dict):
      raise UsageError(f"{what} 는 표(키: 값)여야 한다")
   return dict(value)


def _models(value, what: str) -> dict:
   """빈 칸(None)은 「안 적음」으로 본다 — 본보기를 그대로 복사해도 남은 자리가 종료 2 로 잡힌다."""
   models = {}
   for key, item in _table(value, what).items():
      if item is None:
         continue
      if isinstance(item, bool) or not isinstance(item, (str, int, float)):
         raise UsageError(f"{what} 의 {key} 는 글자나 수여야 한다")
      models[str(key)] = item
   return models


def _list(value, what: str) -> list:
   if value is None:
      return []
   if not isinstance(value, list):
      raise UsageError(f"{what} 는 목록이어야 한다")
   return list(value)


def _work_size(value) -> int:
   if isinstance(value, bool) or not isinstance(value, int) or not 64 <= value <= MAX_WORK_SIZE:
      raise UsageError(f"work_size 는 64~{MAX_WORK_SIZE} 사이 정수다 : {value!r}")
   return value


def _positive(value, what: str) -> float:
   if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
      raise UsageError(f"{what} 는 0 보다 큰 수다 : {value!r}")
   return float(value)
