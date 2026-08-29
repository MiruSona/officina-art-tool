"""Aseprite CLI 감싸기.

이 PC 에는 Aseprite 가 없다. 실행 파일 자리는 --exe 나 ASEPRITE_EXE 로만 받고 PATH 는 안 뒤진다.
slice 와 앵커는 서로 바꿔 쓸 수 있다. slice 의 pivot 이 x·y, slice 이름이 point 다.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..errors import ArtToolError, MissingExecutable

ENV_KEY = "ASEPRITE_EXE"
DEFAULT_TIMEOUT = 120


def find_exe(explicit: str | None = None) -> Path:
   candidate = explicit or os.environ.get(ENV_KEY)
   if not candidate:
      raise MissingExecutable(f"Aseprite 실행 파일이 없다. --exe 를 주거나 {ENV_KEY} 를 정한다")
   path = Path(candidate)
   if not path.is_file():
      raise MissingExecutable(f"Aseprite 실행 파일을 못 찾았다 : {path}")
   return path


def export_args(exe: Path, ase_file: Path, out_png: Path, out_json: Path, layer: str | None = None) -> list[str]:
   """인자 목록. 셸을 안 거치니 따옴표를 붙이지 않는다."""
   args = [
      str(exe),
      "-b",
      str(ase_file),
      "--sheet",
      str(out_png),
      "--data",
      str(out_json),
      "--format",
      "json-array",
      "--list-slices",
      "--sheet-pack",
   ]
   if layer:
      args += ["--layer", layer]
   return args


def export(ase_file: str | Path, out_png: str | Path, out_json: str | Path, layer: str | None = None, exe: str | None = None) -> dict:
   found = find_exe(exe)
   source = Path(ase_file)
   if not source.is_file():
      raise ArtToolError(f"aseprite 파일이 없다 : {source}")

   args = export_args(found, source, Path(out_png), Path(out_json), layer)
   done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", shell=False, timeout=DEFAULT_TIMEOUT)
   if done.returncode != 0:
      raise ArtToolError(f"Aseprite 가 {done.returncode} 로 끝났다 : {done.stderr.strip()[:200]}")
   return {"png": str(out_png), "json": str(out_json)}


def slices_to_points(data: dict, rig: str, anim: str, direction: str, frame: int = 0) -> list[dict]:
   """Aseprite 의 slice 목록을 앵커 점 목록으로 바꾼다."""
   points = []
   for entry in data.get("meta", {}).get("slices", []):
      name = entry.get("name")
      keys = entry.get("keys") or []
      if not name or not keys:
         raise ArtToolError(f"slice 에 이름이나 key 가 없다 : {entry}")
      key = keys[0]
      bounds = key.get("bounds") or {}
      pivot = key.get("pivot") or {"x": 0, "y": 0}
      points.append(
         {
            "rig": rig,
            "anim": anim,
            "direction": direction,
            "frame": int(key.get("frame", frame)),
            "point": name,
            "x": int(bounds.get("x", 0)) + int(pivot["x"]),
            "y": int(bounds.get("y", 0)) + int(pivot["y"]),
            "z": 0,
         }
      )
   return points


def points_to_slices(points: list[dict]) -> dict:
   """앵커 점을 Aseprite 가 읽는 slice 꼴로 되돌린다. 사람이 손볼 자리를 열어 준다."""
   slices = []
   for point in points:
      slices.append(
         {
            "name": point["point"],
            "color": "#0000ffff",
            "keys": [
               {
                  "frame": int(point["frame"]),
                  "bounds": {"x": int(point["x"]), "y": int(point["y"]), "w": 1, "h": 1},
                  "pivot": {"x": 0, "y": 0},
               }
            ],
         }
      )
   return {"meta": {"slices": slices}}
