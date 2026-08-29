"""JSON 읽고 쓰기. 쓸 때는 tmp 에 쓰고 이름을 바꾼다."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .errors import ArtToolError
from .paths import ensure_parent


def write_json(path: str | os.PathLike, data: dict) -> None:
   file = Path(path)
   ensure_parent(file)
   # 같은 폴더에 두 프로세스가 동시에 써도 서로의 tmp 를 안 덮게 PID 를 붙인다.
   tmp = file.with_name(f"{file.name}.{os.getpid()}.tmp")
   tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
   os.replace(tmp, file)


def read_json(path: str | os.PathLike) -> dict:
   file = Path(path)
   if not file.is_file():
      raise ArtToolError(f"JSON 파일이 없다 : {file}")
   try:
      return json.loads(file.read_text(encoding="utf-8-sig"))
   except json.JSONDecodeError as exc:
      raise ArtToolError(f"JSON 을 못 읽었다 : {file} - {exc}") from exc
