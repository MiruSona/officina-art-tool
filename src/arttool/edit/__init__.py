"""받은 그림 손질 (`cutout` · `trim`). 둘이 같이 쓰는 입력 · 출력 규칙만 여기 둔다.

- 입력은 PNG 한 장이나 폴더(바로 아래 `.png`, `check` 와 같은 규칙).
- 출력은 폴더. 입력이 한 장이고 `--out` 이 `.png` 로 끝나면 그 파일로 쓴다.
- 원본을 안 덮는다. 출력 하나라도 입력 파일과 같으면 아무것도 쓰기 전에 거절한다.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import ArtToolError, UsageError
from ..paths import guard_not_folder, guard_overwrite, jailed_output, png_files, resolve_root, safe_join


def is_dry_run(args) -> bool:
   """`--dry-run` 이면 쓰기 앞 검사까지 다 돌고 쓰는 자리만 건너뛴다. 받는 명령은 cli.DRY_RUN_TAKES."""
   return bool(getattr(args, "dry_run", False))


def dry_run_fields(dry_run: bool, would_write) -> dict:
   """dry-run 일 때만 보고에 더할 칸 {dry_run, would_write}. 아닐 때는 빈 dict 라 보고 꼴이 그대로다."""
   if not dry_run:
      return {}
   return {"dry_run": True, "would_write": [str(p) for p in would_write if p is not None]}


def list_inputs(path: str | Path) -> list[Path]:
   source = Path(path)
   if not source.exists():
      raise ArtToolError(f"폴더·파일이 없다 : {source}")
   if source.is_file():
      if source.suffix.lower() != ".png":
         raise UsageError(f"PNG 파일이나 폴더만 받는다 : {source}")
      return [source]
   files = png_files(source)
   if not files:
      raise ArtToolError(f"PNG 가 하나도 없다 : {source}")
   return files


def plan_outputs(inputs: list[Path], in_arg: str | Path, out_arg: str | Path) -> list[Path]:
   """입력마다 쓸 자리를 정한다. 원본과 같은 자리가 하나라도 있으면 거절한다."""
   single_file = Path(in_arg).is_file() and str(out_arg).lower().endswith(".png")
   if single_file:
      outs = [jailed_output(out_arg)]
   else:
      root = resolve_root(out_arg)
      if root.is_file():
         raise UsageError(f"--out 은 폴더여야 한다 (입력이 여러 장이다) : {out_arg}")
      outs = [guard_not_folder(safe_join(root, file.name)) for file in inputs]

   # 윈도 경로는 대소문자를 안 가린다. 같은 파일을 다른 글자로 줘도 잡는다 (paths.guard_overwrite).
   guard_overwrite(outs, inputs)
   return outs
