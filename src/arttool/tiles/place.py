"""③ 배치. DeBroglie(C#) 를 바깥 실행 파일로 부르고 표준입출력 JSON 으로 주고받는다.

이 PC 에는 DeBroglie 가 없다. 그래서 여기서는 계약(요청·응답 JSON 꼴)만 지킨다.
실행 파일 자리는 --exe 인자나 DEBROGLIE_EXE 환경변수로만 받는다. PATH 는 안 뒤진다.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from ..errors import ArtToolError, MissingExecutable
from ..jsonio import read_json, write_json
from ..paths import resolve_root, safe_join
from ..profile import Profile

VERSION = 1
ENV_KEY = "DEBROGLIE_EXE"
DEFAULT_TIMEOUT = 120


def find_exe(explicit: str | None = None) -> Path:
   candidate = explicit or os.environ.get(ENV_KEY)
   if not candidate:
      raise MissingExecutable(f"DeBroglie 실행 파일이 없다. --exe 를 주거나 {ENV_KEY} 를 정한다")
   path = Path(candidate)
   if not path.is_file():
      raise MissingExecutable(f"DeBroglie 실행 파일을 못 찾았다 : {path}")
   return path


def parse_size(text: str) -> tuple[int, int]:
   parts = text.lower().split("x")
   if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
      raise ArtToolError(f"크기는 64x64 꼴이어야 한다 : {text}")
   width, height = int(parts[0]), int(parts[1])
   if width < 1 or height < 1:
      raise ArtToolError(f"크기가 0 이하다 : {text}")
   return width, height


def build_request(prof: Profile, tileset: dict, rules: dict, width: int, height: int, seed: int | None = None) -> dict:
   if int(tileset.get("tile_size", 0)) != int(prof.tiles["size"]):
      raise ArtToolError(f"타일 크기가 프로필과 다르다 : {tileset.get('tile_size')}")
   return {
      "version": VERSION,
      "width": width,
      "height": height,
      "tile_size": int(prof.tiles["size"]),
      "tiles": [{"index": t["index"], "mask": t["mask"]} for t in tileset["tiles"]],
      "rules": rules,
      "seed": seed,
   }


def parse_response(text: str, width: int, height: int) -> dict:
   try:
      data = json.loads(text)
   except json.JSONDecodeError as exc:
      raise ArtToolError(f"DeBroglie 응답이 JSON 이 아니다 : {exc}") from exc

   status = data.get("status")
   if status == "contradiction":
      raise ArtToolError("배치 규칙이 모순이라 못 풀었다 (수축)")
   if status == "timeout":
      raise ArtToolError("배치가 시간 안에 안 끝났다")
   if status != "ok":
      raise ArtToolError(f"DeBroglie 가 알 수 없는 status 를 줬다 : {status}")

   grid = data.get("grid")
   if not isinstance(grid, list) or len(grid) != height:
      raise ArtToolError(f"응답 줄 수가 {len(grid) if isinstance(grid, list) else '?'} 다. {height} 여야 한다")
   for row in grid:
      if not isinstance(row, list) or len(row) != width:
         raise ArtToolError(f"응답 칸 수가 안 맞는다. {width} 여야 한다")
   return {"version": VERSION, "width": width, "height": height, "grid": grid}


def call_exe(exe: Path, request: dict, timeout: int = DEFAULT_TIMEOUT) -> str:
   payload = json.dumps(request, ensure_ascii=False)
   try:
      done = subprocess.run(
         [str(exe), "--stdin-json"],
         input=payload,
         capture_output=True,
         text=True,
         encoding="utf-8",
         shell=False,
         timeout=timeout,
      )
   except subprocess.TimeoutExpired as exc:
      raise ArtToolError(f"배치가 {timeout}초 안에 안 끝났다") from exc
   if done.returncode != 0:
      raise ArtToolError(f"DeBroglie 가 {done.returncode} 로 끝났다 : {done.stderr.strip()[:200]}")
   return done.stdout


def place(
   prof: Profile,
   tileset_path: str | Path,
   rules_path: str | Path,
   size: str,
   out_dir: str | Path,
   exe: str | None = None,
   seed: int | None = None,
   dry_run: bool = False,
) -> dict:
   width, height = parse_size(size)
   tileset = read_json(tileset_path)
   rules = read_json(rules_path)
   request = build_request(prof, tileset, rules, width, height, seed)

   root = resolve_root(out_dir)
   write_json(safe_join(root, "place_request.json"), request)
   if dry_run:
      return {"dry_run": True, "request": "place_request.json", "tiles": len(request["tiles"])}

   found = find_exe(exe)
   result = parse_response(call_exe(found, request), width, height)
   write_json(safe_join(root, "map.json"), result)
   return {"dry_run": False, "map": "map.json", "width": width, "height": height}
