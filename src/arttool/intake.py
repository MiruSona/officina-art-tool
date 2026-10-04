"""`arttool intake` — 받은 그림을 한 번에 손질한다 (설계 16-1 #13, 사용자 확정 2026-10-04).

차례 : ① cutout(바탕 지우기) → ② trim(여백 걷기) → ③ check(검수, `--template` 을 주면 템플릿도 견준다) → ④ sheet(비교판, `--sheet` 를 줄 때만).

- 원본은 안 건드린다. 손질한 그림은 `--out` 폴더에만 쓴다(`cutout` · `trim` 과 같은 원본 보호 규칙).
- 단계를 끌 수 있다 : `--no-cutout` · `--no-trim` · `--no-check`. 비교판은 `--sheet` 를 안 주면 안 만든다.
- 보고 넷을 하나로 묶는다 : `steps.<단계>` 에 그 단계 보고, 맨 위 `warnings` 에 단계 경고를
  {rule, ok, detail, items, step} 꼴로 모은다.
- 한 단계가 실패하면 거기서 멈추고 `status: fail`(종료 코드 4), `failed_step` 에 그 단계를 적는다.
  실패로 보는 것 : cutout 뒤 다 지워진 그림이 있다 · trim 할 그림이 다 비었다 · check 의 status 가 fail.
  단 check 실패 때는 비교판(`--sheet`)까지는 만든다 — 검수에 걸린 그림을 눈으로 봐야 하니까.
  「90% 넘게 지웠다」 는 실패로 올리지 않는다 — 큰 바탕 위 작은 그림 · 검은 바탕 마스크도 정상으로 그만큼 지운다.
- 불투명한 큰 배경 그림은 cutout 을 건너뛴다(그 장만, 경고 `cutout.background_kept`).
- 검수 · 비교판은 **이번에 쓴 파일만** 본다. `--sheet` 가 `--out` 안이거나 원본과 같으면 거절한다.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from . import check as check_mod
from . import image, sheet as sheet_mod
from .checks import is_background, warning
from .edit import cutout as cutout_mod
from .edit import list_inputs, plan_outputs, trim as trim_mod
from .errors import UsageError
from .paths import guard_outside, guard_overwrite, png_files
from .profile import load_profile_args

VERSION = 1
STEPS = ("cutout", "trim", "check", "sheet")
SHEET_KINDS = "zoom,silhouette"     # 받은 그림은 크게 보기 + 실루엣이면 손질 결과를 한눈에 본다


def _check_args(args) -> tuple:
   key = cutout_mod.parse_key(args.key)
   tol, shave, pad = int(args.tol), int(args.shave), int(args.pad)
   if not 0 <= tol <= 255:
      raise UsageError(f"--tol 은 0~255 다 : {tol}")
   if shave < 0:
      raise UsageError(f"--shave 는 0 이상이다 : {shave}")
   if pad < 0:
      raise UsageError(f"--pad 는 0 이상이다 : {pad}")
   if str(args.out_dir).lower().endswith(".png"):
      raise UsageError(f"--out 은 폴더다 (check 가 폴더를 본다) : {args.out_dir}")
   return key, tol, shave, pad


def _step_cutout(names: list[str], arrs: list, key, tol: int, shave: int, min_side: int) -> tuple[list, dict, bool]:
   """바탕 지우기. 불투명한 큰 배경 그림을 갉았으면 그 장은 원본 그대로 둔다 (실물 버그 2).

   「갉았다」 = `checks.is_background`(투명 칸 없음 · 짧은 변 min_side 이상) 이면서
   `cutout.looks_like_background`(지운 뒤 남은 칸이 캔버스 세 변 이상에 닿음).
   흰 띠 · 단색 바탕 위 물건은 지운 뒤 많아야 두 변에 닿아 그대로 잘라 낸다.
   """
   rows, warnings, emptied = [], [], []
   out = []
   for name, arr in zip(names, arrs):
      result, info = cutout_mod.cutout(arr, key, tol, shave)
      if is_background(arr, min_side) and cutout_mod.looks_like_background(info):
         out.append(arr)
         rows.append({"file": name, **info, "kept_background": True})
         warnings.append(warning("cutout.background_kept",
                                 f"{name} : 배경 그림으로 보여 바탕을 안 지웠다 (지우면 {info['erased']}칸이 빠지고 남은 칸이 "
                                 f"{info['sides_left']}변에 닿는다). 꼭 지워야 하면 cutout 명령을 따로 쓴다", [name]))
         continue
      out.append(result)
      rows.append({"file": name, **info, "kept_background": False})
      warnings += cutout_mod.image_warnings(name, info)
      if info["opaque_before"] and info["bbox"] is None:
         emptied.append(name)
   failed = bool(emptied)
   if failed:
      warnings.append(warning("cutout.emptied", f"다 지워진 그림 : {', '.join(emptied)}. --key · --tol 을 바꿔 본다", emptied))
   report = {"status": "fail" if failed else ("warn" if warnings else "ok"), "key": None, "tol": tol, "shave": shave,
             "min_side": min_side, "images": rows, "warnings": warnings}
   return out, report, failed


def _step_trim(names: list[str], arrs: list, pad: int, square: bool) -> tuple[list, list[str], dict, bool]:
   rows, warnings = [], []
   kept_arrs, kept_names = [], []
   for name, arr in zip(names, arrs):
      width, height = image.size(arr)
      row = {"file": name, "size_before": [width, height]}
      result = trim_mod.trim_one(arr, pad, square)
      if result is None:
         warnings.append(warning("trim.empty", f"{name} : 빈 그림이라 건너뛰었다", [name]))
         rows.append({**row, "skipped": True})
         continue
      cut, offset = result
      kept_arrs.append(cut)
      kept_names.append(name)
      rows.append({**row, "size": list(image.size(cut)), "offset": list(offset), "skipped": False})
   failed = not kept_arrs
   report = {"status": "fail" if failed else ("warn" if warnings else "ok"), "pad": pad, "square": square, "images": rows, "warnings": warnings}
   return kept_arrs, kept_names, report, failed


def _step_check(prof, args, out_root: Path, written: list[Path]) -> dict:
   """이번에 쓴 그림만 검수한다 (R1-L2). --out 에 지난 판 PNG 가 있으면 이번 것만 임시 폴더에 옮겨 본다."""
   names = {p.name for p in written}
   others = sorted(p.name for p in png_files(out_root) if p.name not in names)
   if not others:
      report = check_mod.run(prof, out_root, template=args.template)
   else:
      with tempfile.TemporaryDirectory(prefix="arttool-intake-") as tmp:
         for path in written:
            shutil.copyfile(path, Path(tmp) / path.name)
         report = check_mod.run(prof, tmp, template=args.template)
   report["checked_files"] = sorted(names)
   if others:
      report["not_checked"] = others        # --out 에 원래 있던 PNG (지난 판 등). 검수에서 뺐다
   return report


def _step_sheet(args, written: list[Path]) -> dict:
   # 폴더가 아니라 이번에 쓴 파일만 넘긴다 — 지난 판 그림이 비교판에 끼지 않는다
   return sheet_mod.run(argparse.Namespace(in_paths=[str(p) for p in written], out_file=args.sheet, kinds=SHEET_KINDS,
                                           scale="auto", tile=2, bg="checker", label=True))


def _step_warnings(step: str, report: dict) -> list[dict]:
   """단계 보고의 경고를 맨 위 꼴 {rule, ok, detail, items, step} 으로 모은다."""
   lines = []
   for w in report.get("warnings", []):
      if isinstance(w, dict):
         detail = w.get("detail") or w.get("message") or w.get("rule", "")
         line = warning(w.get("rule") or f"{step}.warning", detail, w.get("items"))
      else:
         line = warning(f"{step}.warning", str(w))
      line["step"] = step
      lines.append(line)
   return lines


def run(args) -> dict:
   key, tol, shave, pad = _check_args(args)
   square = bool(args.square)
   inputs = list_inputs(args.in_dir)
   targets = plan_outputs(inputs, args.in_dir, args.out_dir)     # 원본을 덮는 자리면 여기서 거절한다
   out_root = Path(targets[0]).parent
   if args.sheet:
      # 비교판이 원본을 덮거나, 손질한 그림 폴더 안에 들어가 다음 판에 검수 · 비교판에 끼는 것을 막는다 (R1-L2)
      guard_overwrite([args.sheet], inputs, "--sheet")
      guard_outside([args.sheet], [out_root], "--sheet")
   prof = load_profile_args(args)

   names = [p.name for p in inputs]
   arrs = [image.load(p) for p in inputs]
   steps: dict[str, dict] = {}
   skipped = [s for s, off in (("cutout", args.no_cutout), ("trim", args.no_trim), ("check", args.no_check), ("sheet", not args.sheet)) if off]
   failed_step = None

   if "cutout" not in skipped:
      arrs, steps["cutout"], failed = _step_cutout(names, arrs, key, tol, shave, int(prof.check["background"]["min_side"]))
      steps["cutout"]["key"] = args.key
      if failed:
         failed_step = "cutout"

   if failed_step is None and "trim" not in skipped:
      arrs, names, steps["trim"], failed = _step_trim(names, arrs, pad, square)
      if failed:
         failed_step = "trim"

   written: list[dict] = []
   written_paths: list[Path] = []
   if failed_step is None:
      by_name = dict(zip([p.name for p in inputs], targets))
      for name, arr in zip(names, arrs):
         image.save(by_name[name], arr)
         written.append({"file": name, "out": str(by_name[name]), "size": list(image.size(arr))})
         written_paths.append(Path(by_name[name]))

   if failed_step is None and "check" not in skipped:
      steps["check"] = _step_check(prof, args, out_root, written_paths)
      if steps["check"].get("status") == "fail":
         failed_step = "check"

   # check 가 fail 이어도 비교판은 만든다 — 검수에 걸렸을 때야말로 눈으로 봐야 한다.
   # cutout · trim 실패는 파일을 안 썼으니 그릴 것이 없다.
   if failed_step in (None, "check") and written_paths and "sheet" not in skipped:
      steps["sheet"] = _step_sheet(args, written_paths)

   warnings = [line for step in STEPS if step in steps for line in _step_warnings(step, steps[step])]
   if failed_step:
      status = "fail"
   elif any(steps[s].get("status") == "warn" for s in steps) or warnings:
      status = "warn"
   else:
      status = "ok"
   return {
      "version": VERSION,
      "status": status,
      "failed_step": failed_step,
      "in": str(args.in_dir),
      "out": str(out_root),
      "ran": [s for s in STEPS if s in steps],
      "skipped": skipped,
      "not_reached": [s for s in STEPS if s not in steps and s not in skipped],
      "images": written,
      "steps": steps,
      "warnings": warnings,
   }
