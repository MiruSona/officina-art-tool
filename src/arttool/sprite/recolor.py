"""겹 몇 장 + 색표 몇 벌 → N장. 밑감 색 하나 → 결과 색 하나, 1:1 로 바꾸고 밝기는 계산하지 않는다.

표 꼴과 검사는 `Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md` 4절.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import image, pieces
from ..errors import ArtToolError, UsageError
from ..jsonio import read_json, write_json
from ..palette import parse_hex, to_hex
from ..paths import check_relative, jailed_output, resolve_root, safe_join

VERSION = 1
REPORT_NAME = "recolor_report.json"
OUTLINE_TOLERANCE = 2
VARIANT_MARK = "{v}"

SPEC_KEYS = ("version", "outline", "families", "jobs", "combos")
JOB_KEYS = ("src", "family", "out", "roles", "drop_pieces")

RGB = tuple[int, int, int]


@dataclass
class Job:
   src: str
   out: str
   family: str | None = None
   roles: dict[RGB, str] = field(default_factory=dict)
   drop_pieces: int = 0


@dataclass
class RecolorSpec:
   outline: RGB | None
   families: dict[str, dict[str, dict[str, RGB]]]
   jobs: list[Job]
   combos: list[list[str]]


def _reject_unknown(node: dict, allowed: tuple[str, ...], where: str) -> None:
   unknown = sorted(set(node) - set(allowed))
   if unknown:
      raise ArtToolError(f"{where} 에 모르는 칸 : {', '.join(unknown)}")


def _parse_families(raw) -> dict[str, dict[str, dict[str, RGB]]]:
   if not isinstance(raw, dict):
      raise ArtToolError("families 는 사전이어야 한다")
   out = {}
   for fam, variants in raw.items():
      if not isinstance(variants, dict) or not variants:
         raise ArtToolError(f"families.{fam} 에 벌이 하나도 없다")
      out[fam] = {}
      for variant, roles in variants.items():
         if not isinstance(roles, dict) or not roles:
            raise ArtToolError(f"families.{fam}.{variant} 에 역할이 하나도 없다")
         out[fam][variant] = {role: parse_hex(str(value)) for role, value in roles.items()}
   return out


def _parse_job(row, index: int, families: dict) -> Job:
   where = f"jobs[{index}]"
   if not isinstance(row, dict):
      raise ArtToolError(f"{where} 는 사전이어야 한다")
   _reject_unknown(row, JOB_KEYS, where)
   if "src" not in row or "out" not in row:
      raise ArtToolError(f"{where} 에 src 와 out 이 있어야 한다")
   job = Job(src=str(row["src"]), out=str(row["out"]))
   check_relative(job.src)
   check_relative(job.out)

   drop = row.get("drop_pieces", 0)
   if isinstance(drop, bool) or not isinstance(drop, int) or drop < 0:
      raise ArtToolError(f"{where}.drop_pieces 는 0 이상 정수다 : {drop!r}")
   job.drop_pieces = drop

   if "family" not in row:
      if row.get("roles"):
         raise ArtToolError(f"{where} 에 family 없이 roles 만 있다")
      if VARIANT_MARK in job.out:
         raise ArtToolError(f"{where} 는 family 가 없는데 out 에 {VARIANT_MARK} 가 있다")
      return job

   job.family = str(row["family"])
   if job.family not in families:
      raise ArtToolError(f"{where} 의 family 가 families 에 없다 : {job.family}")
   variants = families[job.family]
   if VARIANT_MARK not in job.out and len(variants) > 1:
      raise ArtToolError(f"{where} 의 out 에 {VARIANT_MARK} 가 없는데 벌이 {len(variants)}개다. 같은 파일을 덮어쓴다")
   roles = row.get("roles")
   if not isinstance(roles, dict) or not roles:
      raise ArtToolError(f"{where} 에 roles 가 있어야 한다 (밑감 색 → 역할)")
   for hex_text, role in roles.items():
      rgb = parse_hex(hex_text)
      if rgb in job.roles:
         raise ArtToolError(f"{where}.roles 에 같은 색이 두 번 있다 (대소문자는 안 가린다) : {hex_text}")
      job.roles[rgb] = str(role)
   for variant, table in variants.items():
      missing = sorted(set(job.roles.values()) - set(table))
      if missing:
         raise ArtToolError(f"families.{job.family}.{variant} 에 역할이 없다 : {', '.join(missing)} ({where})")
   return job


def load_spec(data: dict) -> RecolorSpec:
   if not isinstance(data, dict):
      raise ArtToolError("색표는 JSON 사전이어야 한다")
   _reject_unknown(data, SPEC_KEYS, "색표")
   if data.get("version") != VERSION:
      raise ArtToolError(f"모르는 색표 판 번호 : {data.get('version')}")
   families = _parse_families(data.get("families") or {})
   rows = data.get("jobs")
   if not isinstance(rows, list) or not rows:
      raise ArtToolError("jobs 가 비었다")
   jobs = [_parse_job(row, i, families) for i, row in enumerate(rows)]

   combos = data.get("combos") or []
   if not isinstance(combos, list) or not all(isinstance(c, list) and c for c in combos):
      raise ArtToolError("combos 는 파일 이름 목록들의 목록이다")
   outline = parse_hex(str(data["outline"])) if data.get("outline") else None
   return RecolorSpec(outline=outline, families=families, jobs=jobs, combos=[[str(n) for n in c] for c in combos])


def _near_outline(rgb: RGB, outline: RGB) -> bool:
   return rgb != outline and all(abs(a - b) <= OUTLINE_TOLERANCE for a, b in zip(rgb, outline))


def build_table(colors: set[RGB], job: Job, variant_colors: dict[str, RGB] | None, outline: RGB | None):
   """바꿀 표 · 외곽선으로 맞춘 색 · 표에 없는 색. roles 가 외곽선 맞추기보다 먼저다."""
   table: dict[RGB, RGB] = {}
   fixed, unmapped = [], []
   for rgb in sorted(colors):
      if variant_colors is not None and rgb in job.roles:
         table[rgb] = variant_colors[job.roles[rgb]]
      elif outline is not None and _near_outline(rgb, outline):
         table[rgb] = outline
         fixed.append(rgb)
      elif variant_colors is not None and rgb != outline:
         unmapped.append(rgb)
   return table, fixed, unmapped


def position_diff(before: image.RGBA, after: image.RGBA) -> int:
   """불투명 칸 자리가 다른 픽셀 수. 색만 바꾸는 명령이라 0 이어야 한다."""
   return int(np.count_nonzero((before[:, :, 3] > 0) != (after[:, :, 3] > 0)))


def _drop(arr: image.RGBA, limit: int) -> tuple[image.RGBA, list[list[int]]]:
   out = arr.copy()
   dropped = []
   for piece in pieces.small_pieces(arr[:, :, 3] > 0, limit):
      for x, y in piece:
         out[y, x] = (0, 0, 0, 0)
         dropped.append([x, y])
   return out, dropped


def _hex_map(table: dict[RGB, RGB]) -> dict[str, str]:
   return {to_hex(a): to_hex(b) for a, b in table.items()}


def _bake_job(job: Job, arr: image.RGBA, spec: RecolorSpec) -> list[tuple[str, image.RGBA, dict]]:
   """한 줄에서 나오는 (출력 이름, 그림, 보고 줄) 목록."""
   base, dropped = _drop(arr, job.drop_pieces)
   colors = image.opaque_colors(base)
   variants: dict[str | None, dict[str, RGB] | None] = {None: None}
   if job.family is not None:
      variants = dict(spec.families[job.family])

   made = []
   for variant, variant_colors in variants.items():
      table, fixed, unmapped = build_table(colors, job, variant_colors, spec.outline)
      result = image.replace_colors(base, table)
      name = job.out if variant is None else job.out.replace(VARIANT_MARK, variant)
      absent = sorted(to_hex(c) for c in job.roles if c not in colors) if variant_colors is not None else []
      row = {
         "src": job.src,
         "family": job.family,
         "variant": variant,
         "out": name,
         "replaced": _hex_map(table),
         "outline_fixed": [to_hex(c) for c in fixed],
         "unmapped_colors": [to_hex(c) for c in unmapped],
         "roles_absent": absent,
         "pieces_dropped": dropped,
         "position_diff": position_diff(base, result),
      }
      made.append((name, result, row))
   return made


def _path_key(path: Path) -> str:
   """Windows 는 대소문자를 안 가리므로 casefold 로 견준다."""
   return str(path.resolve()).casefold()


def _check_out_name(name: str, taken: set[str], sources: set[str], out_root: Path) -> None:
   key = name.replace("\\", "/").casefold()
   if key == REPORT_NAME.casefold():
      raise ArtToolError(f"출력 이름이 보고 파일 이름과 같다 : {name}")
   if key in taken:
      raise ArtToolError(f"같은 출력 이름이 두 번 나온다 (대소문자는 안 가린다) : {name}")
   taken.add(key)
   if _path_key(safe_join(out_root, name)) in sources:
      raise ArtToolError(f"출력이 밑감 원본을 덮어쓴다 : {name}")


def _stack(names: list[str], baked: dict[str, image.RGBA]) -> image.RGBA:
   missing = [n for n in names if n not in baked]
   if missing:
      raise ArtToolError(f"combos 에 구운 적 없는 파일 : {', '.join(missing)}")
   first = baked[names[0]]
   out = image.new(*image.size(first))
   for name in names:
      if image.size(baked[name]) != image.size(first):
         raise ArtToolError(f"combos 안에 크기가 다른 그림 : {name}")
      image.paste(out, baked[name], 0, 0)
   return out


def run(in_dir: str | Path, spec_file: str | Path, out_dir: str | Path, sheet: str | Path | None = None, scale: int | None = None) -> dict:
   if scale is not None and sheet is None:
      raise UsageError("--scale 은 --sheet 와 같이 쓴다")
   if scale is not None and scale <= 0:
      raise UsageError(f"--scale 은 양수여야 한다 : {scale}")
   source = Path(in_dir)
   if not source.is_dir():
      raise ArtToolError(f"밑감 겹 폴더가 없다 : {source}")
   spec = load_spec(read_json(spec_file))
   in_root = resolve_root(source)
   out_root = resolve_root(out_dir)

   # 먼저 다 구워 이름 겹침을 본 다음에 쓴다. 반쯤 쓰고 멈추지 않게.
   sources = {_path_key(safe_join(in_root, job.src)) for job in spec.jobs}
   baked: dict[str, image.RGBA] = {}
   taken: set[str] = set()
   rows = []
   for job in spec.jobs:
      arr = image.load(safe_join(in_root, job.src))
      for name, result, row in _bake_job(job, arr, spec):
         _check_out_name(name, taken, sources, out_root)
         baked[name] = result
         rows.append(row)
   combos = [_stack(names, baked) for names in spec.combos]

   for name, result in baked.items():
      image.save(safe_join(out_root, name), result)
   sheet_path = None
   if sheet is not None:
      items = list(baked.values()) + combos
      sheet_path = jailed_output(sheet)
      image.save(sheet_path, image.contact_sheet(items, scale or 1))

   warnings = [f"{r['out']} : 표에 없는 색 {', '.join(r['unmapped_colors'])}" for r in rows if r["unmapped_colors"]]
   warnings += [f"{r['out']} : roles 에 적었지만 그림에 없는 색 {', '.join(r['roles_absent'])}" for r in rows if r["roles_absent"]]
   status = "ok"
   if warnings:
      status = "warn"
   if any(r["position_diff"] for r in rows):
      status = "fail"
   report = {
      "status": status,
      "outputs": rows,
      "combos": len(combos),
      "sheet": str(sheet_path) if sheet_path else None,
      "warnings": warnings,
      "out": str(out_root),
   }
   write_json(safe_join(out_root, REPORT_NAME), report)
   return report
