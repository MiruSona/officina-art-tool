"""`arttool palette check` — 램프 파일 하나의 모양(ramp_shape)을 그림 없이 한 번만 잰다 (3판 설계 2-4).

`check` 는 그림 묶음마다 같은 램프 경고를 되풀이해 싣는다. 이 명령은 램프 파일만 보고 한 줄씩 낸다.
판정은 `check` 와 같은 함수(`check.palette_block`)를 쓴다 — 두 길의 결과가 어긋나지 않게.

종료 코드 : 0 = 판정 끝(걸린 램프가 있어도 status 는 warn, 종료 0) · 2 = 인자 · 램프 파일 · 프로필 잘못.
파일은 안 쓴다(`--report` 는 cli 가 쓴다).
"""
from __future__ import annotations

from pathlib import Path

from .. import palette
from ..errors import ArtToolError, UsageError
from ..profile import load_profile_args

VERSION = 1


def _ramps_file(prof, ramps_arg: str | None) -> Path:
   """잴 램프 파일. `--ramps` 를 주면 그 파일, 아니면 프로필 `palette.ramps_file`(`ramps_path()` 가 `$palettes/` · 감옥을 지난다)."""
   if ramps_arg:
      file = Path(ramps_arg)
      if file.suffix.lower() != ".json":
         raise UsageError(f"--ramps 는 .json 램프 파일이다 : {ramps_arg}")
   else:
      file = prof.ramps_path()
      if file is None:
         raise UsageError("잴 램프 파일이 없다 — --ramps 를 주거나 프로필에 palette.ramps_file 을 적는다")
   if not file.is_file():
      raise UsageError(f"램프 파일이 없다 : {file}")
   return file


def run(args) -> dict:
   prof = load_profile_args(args)
   file = _ramps_file(prof, getattr(args, "ramps", None))
   try:
      ramps = palette.load_ramps(file)
   except UsageError:
      raise
   except ArtToolError as exc:
      # 깨진 램프 파일도 「파일 오류」라 종료 2 로 맞춘다 (설계 2-4).
      raise UsageError(str(exc)) from exc

   # 순환 가져오기를 피하려고 여기서 부른다 — check 가 checks 묶음을 가져온다.
   from ..check import palette_block

   block = palette_block(prof, ramps, 0)
   entry = next(iter(block.values()))
   entry.pop("used_by")  # 그림 없이 재니 「몇 장이 썼나」는 없다.
   return {
      "version": VERSION,
      "profile": prof.name,
      "status": "warn" if entry["ramp_shape"] else "ok",
      "ramps": str(file),
      "palette": block,
   }
