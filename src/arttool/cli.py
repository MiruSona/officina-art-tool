"""명령 등록만 한다. 셈은 다른 모듈이 하고 여기서는 인자를 넘겨 부르기만 한다.

새 명령(2026-10-04 개선 설계)은 늦게 부른다 — 아래 `LATE` 표. 각 갈래는 표의 모듈 파일과 함수만 만들면 바로 붙는다.
모듈이나 함수가 아직 없으면 「아직 구현 안 됨」을 종료 2 로 알린다.

약속 (설계 문서 12-1 과 같다) :
- 함수 꼴은 `run(args) -> dict`. `args` 는 argparse 결과 그대로다. 인자 이름(dest)은 `_add_*` 함수에 있다.
- 프로필이 필요하면 `arttool.profile.load_profile_args(args)` 로 읽는다(`--profile` · `--directions` 처리).
- 돌려주는 dict 의 `status` 는 `ok` · `warn` · `fail`. `fail` 이면 종료 4, 나머지는 0.
- `args.report` 가 있으면 돌려준 dict 를 cli 가 그 파일에 쓴다. 모듈은 보고 파일을 따로 안 쓴다.
- 잘못된 인자는 `UsageError`(종료 2), 그 밖의 막힘은 `ArtToolError`(종료 1)로 올린다.

| 명령 | 모듈.함수 |
| --- | --- |
| `cutout` | `arttool.edit.cutout.run` |
| `trim` | `arttool.edit.trim.run` |
| `ui preview` | `arttool.ui.ninepatch.run_preview` |
| `sheet` | `arttool.sheet.run` (`--scale per` = 그림마다 배율, 2판 C10) |
| `template list` · `show` · `render` | `arttool.template.run.run` (`args.sub` 로 가른다) |
| `style extract` | `arttool.style.extract.run` |
| `layers diff` · `mask` · `view` · `check` · `export` · `fill` | `arttool.sprite.layerops.run` (`args.sub` 로 가른다) |
| `intake` | `arttool.intake.run` |
| `frames bake` | `arttool.frames.bake.run` (발 줄 → 덮기 → 자르기 → 띠 → gif) |
| `style ref` · `bands` · `stitch` · `tile offset` | `arttool.style.ref` · `edit.bands` · `edit.stitch` · `tiles.offset` 의 `run` (피드백 후속 설계) |
| `extend period` · `ring` · `canvas` | `arttool.extend.period` · `ring` · `canvas` 의 `run` |
| `ui glyphs` · `reline` · `tint` | `arttool.ui.glyphs` · `sprite.reline` · `sprite.tint` 의 `run` |
| `merge-colors` | `arttool.sprite.merge.run` (2026-10-05) |
| `shift` | `arttool.sprite.shift.run` (2026-10-06) |
| `outline` · `fill` · `diff` | `arttool.sprite.outline` · `edit.fill` · `sprite.diff` 의 `run` (2026-10-06) |
| `measure shape` · `mask` | `arttool.measure.shape` · `edit.mask` 의 `run` (2026-10-06 2판-나) |
| `palette check` | `arttool.checks.palette_check.run` (2026-10-06 3판-가, 램프 파일만 잰다) |
| `layers compose` | 여기서 `sprite.layers.compose_sheets` 를 바로 부른다 (옛 `layers`) |
| `check --no-warn · --mode · --template` | `check.run(prof, in_dir, no_ramps, *, warn, mode, template)` — 그 세 칸을 받게 되면 넘긴다 |
| `check --known · --baseline · --fail-on-new` | `check.run(..., *, known, baseline, fail_on_new)` — 셋 중 하나라도 줬을 때만 넘긴다 |
| `check --in A B …` | `check.run_many(prof, [in…], ...)` — 하나면 `check.run` 그대로, 여럿이면 입력마다 `run` → `merge`(where 앞에 입력 딱지) → known 은 합친 뒤 한 번 (2판 C9) |
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import sys
import traceback
from pathlib import Path

from . import bake as bake_mod
from . import check as check_mod
from . import profile_map as profile_map_mod
from . import providers
from .edit import dry_run_fields, is_dry_run
from .errors import EXIT_CHECK_FAIL, EXIT_ERROR, EXIT_OK, ArtToolError, UsageError
from .jsonio import read_json, write_json
from .paths import guard_overwrite, jailed_output
from .profile import load_profile_args, show_lines as profile_show_lines
from .extend import canvas as extend_canvas_mod
from .sprite import anchors as anchors_mod
from .sprite import layers as layers_mod
from .sprite import normalize as normalize_mod
from .sprite import recolor as recolor_mod
from .sprite import split as split_mod
from .tiles import blob as blob_mod
from .tiles import inspect as inspect_mod
from .tiles import ldtk as ldtk_mod
from .tiles import place as place_mod
from .tiles import preview as preview_mod
from .tiles import seam as seam_mod
from .ui import bake_ui as ui_bake_mod
from .ui import check_ui as ui_check_mod
from .ui import font as ui_font_mod
from .ui import frame as ui_frame_mod
from .ui import icons as ui_icons_mod
from .ui import ninepatch as ui_import_mod
from .ui import screen as ui_screen_mod

# (명령, 하위 명령) → (모듈, 함수). 하위 명령이 없는 명령은 None.
LATE: dict[tuple[str, str | None], tuple[str, str]] = {
   ("cutout", None): ("arttool.edit.cutout", "run"),
   ("trim", None): ("arttool.edit.trim", "run"),
   ("ui", "preview"): ("arttool.ui.ninepatch", "run_preview"),
   ("sheet", None): ("arttool.sheet", "run"),
   ("template", "list"): ("arttool.template.run", "run"),
   ("template", "show"): ("arttool.template.run", "run"),
   ("template", "render"): ("arttool.template.run", "run"),
   ("style", "extract"): ("arttool.style.extract", "run"),
   ("layers", "diff"): ("arttool.sprite.layerops", "run"),
   ("layers", "mask"): ("arttool.sprite.layerops", "run"),
   ("layers", "view"): ("arttool.sprite.layerops", "run"),
   ("layers", "check"): ("arttool.sprite.layerops", "run"),
   ("layers", "export"): ("arttool.sprite.layerops", "run"),
   ("layers", "fill"): ("arttool.sprite.layerops", "run"),
   ("frames", "bake"): ("arttool.frames.bake", "run"),
   ("intake", None): ("arttool.intake", "run"),
   # 피드백 후속 설계(2026-10-04)
   ("style", "ref"): ("arttool.style.ref", "run"),
   ("bands", None): ("arttool.edit.bands", "run"),
   ("stitch", None): ("arttool.edit.stitch", "run"),
   ("tile", "offset"): ("arttool.tiles.offset", "run"),
   ("extend", "period"): ("arttool.extend.period", "run"),
   ("extend", "ring"): ("arttool.extend.ring", "run"),
   ("extend", "canvas"): ("arttool.extend.canvas", "run"),
   ("ui", "glyphs"): ("arttool.ui.glyphs", "run"),
   ("reline", None): ("arttool.sprite.reline", "run"),
   ("tint", None): ("arttool.sprite.tint", "run"),
   ("merge-colors", None): ("arttool.sprite.merge", "run"),
   ("shift", None): ("arttool.sprite.shift", "run"),
   ("outline", None): ("arttool.sprite.outline", "run"),
   ("fill", None): ("arttool.edit.fill", "run"),
   ("diff", None): ("arttool.sprite.diff", "run"),
   ("measure", "shape"): ("arttool.measure.shape", "run"),
   ("mask", None): ("arttool.edit.mask", "run"),
   ("palette", "check"): ("arttool.checks.palette_check", "run"),
}

# check.run 이 이 세 칸을 키워드로 받게 되면(D 갈래) 새 인자를 넘긴다.
CHECK_NEW_KWARGS = ("warn", "mode", "template")
CHECK_MODES = ("auto", "sprite", "background")
CUTOUT_KEY_HELP = "edge(네 변에서 번짐, 기본) · corner(네 모서리에서 번짐) · #RRGGBB(그 색을 그림 전체에서)"


def _utf8_streams() -> None:
   """파이프 · 파일로 나갈 때도 UTF-8 로 쓴다. Windows 는 기본이 cp949 라 한글이 깨지고 `—` 에서 죽는다.

   PYTHONIOENCODING 을 준 사람은 그 값을 따른다(비상구). backslashreplace 라 어떤 글자가 와도 안 죽는다.
   """
   if os.environ.get("PYTHONIOENCODING"):
      return
   for stream in (sys.stdout, sys.stderr):
      reconfigure = getattr(stream, "reconfigure", None)
      if reconfigure is None:
         continue
      try:
         reconfigure(encoding="utf-8", errors="backslashreplace")
      except (ValueError, OSError):
         # 이미 읽기 · 쓰기가 시작돼 바꿀 수 없는 흐름이면 그대로 둔다.
         continue


def _common() -> argparse.ArgumentParser:
   """어느 명령 뒤에도 붙일 수 있는 공통 인자. 안 주면 값을 안 넣어 앞의 값이 남는다."""
   node = argparse.ArgumentParser(add_help=False, argument_default=argparse.SUPPRESS)
   node.add_argument("--profile")
   node.add_argument("--provider")
   node.add_argument("--dry-run", action="store_true")
   node.add_argument("--force", action="store_true")
   node.add_argument("--json", action="store_true", dest="as_json")
   node.add_argument("--directions", type=int)
   return node


COMMON = _common()


def build_parser() -> argparse.ArgumentParser:
   parser = argparse.ArgumentParser(prog="arttool", description="2D 그림 규격 맞추기 · 앵커 · 검수 · 굽기")
   parser.add_argument("--profile", help="프로필 이름 또는 yaml 경로")
   # 기본값을 None 으로 둔다 — 「안 줬다」를 가려야 provider make 밖에서 준 것을 거절할 수 있다. 기본 제공자는 _run_provider 가 채운다
   parser.add_argument("--provider", default=None, help=f"그림을 만들 제공자 (기본 {providers.DEFAULT}). provider make 만 받는다")
   parser.add_argument("--dry-run", action="store_true",
                       help="쓰지 않고 보고만 낸다 (생성 명령은 요청 JSON 만 쓴다). 받는 명령이 정해져 있고 그 밖이면 종료 2")
   parser.add_argument("--force", action="store_true", help="검수를 건너뛴다. bake · ui bake · style extract 만 받는다")
   parser.add_argument("--json", action="store_true", dest="as_json", help="사람용 표 대신 JSON")
   parser.add_argument("--directions", type=int, help="방향 수를 덮어쓴다")

   subs = parser.add_subparsers(dest="command", required=True)
   _add_profile(subs)
   _add_normalize(subs)
   _add_anchors(subs)
   _add_check(subs)
   _add_bake(subs)
   _add_layers(subs)
   _add_frames(subs)
   _add_split(subs)
   _add_recolor(subs)
   _add_tile(subs)
   _add_ui(subs)
   _add_provider(subs)
   _add_cutout(subs)
   _add_trim(subs)
   _add_sheet(subs)
   _add_template(subs)
   _add_style(subs)
   _add_intake(subs)
   _add_bands(subs)
   _add_stitch(subs)
   _add_extend(subs)
   _add_reline(subs)
   _add_tint(subs)
   _add_merge(subs)
   _add_shift(subs)
   _add_outline(subs)
   _add_fill(subs)
   _add_diff(subs)
   _add_measure(subs)
   _add_mask(subs)
   _add_palette(subs)
   return parser


def _add_profile(subs) -> None:
   node = subs.add_parser("profile", help="프로필 보기")
   inner = node.add_subparsers(dest="sub", required=True)
   inner.add_parser("show", help="겹쳐진 최종 값을 찍는다", parents=[COMMON])


def _add_normalize(subs) -> None:
   node = subs.add_parser("normalize", help="① 규격 맞추기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True)
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--anim", action="append", help="이 애니메이션만. 여러 번 줄 수 있다")


def _add_anchors(subs) -> None:
   node = subs.add_parser("anchors", help="② 앵커 뽑기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="규격 맞춘 시트 폴더")
   node.add_argument("--rig", required=True)
   node.add_argument("--from", dest="source", default="marker", choices=["marker", "skeleton"])
   node.add_argument("--markers", help="마커 시트 폴더 (marker 일 때)")
   node.add_argument("--skeleton", help="estimate-skeleton JSON (skeleton 일 때)")
   node.add_argument("--out", dest="out_file", required=True)


def _add_check(subs) -> None:
   node = subs.add_parser("check", help="③ 검수", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, nargs="+",
                     help="frames.json 이 있는 폴더, 또는 낱장 PNG 폴더·파일. 여럿 주면 입력마다 판정해 한 보고로 합친다")
   node.add_argument("--report", dest="report", required=True)
   node.add_argument("--no-ramps", dest="no_ramps", action="store_true", help="램프 규칙을 건너뛴다 (팔레트 미정일 때)")
   node.add_argument("--no-warn", dest="no_warn", action="store_true", help="이번 한 판만 경고 검사를 끈다 (status 는 그대로)")
   node.add_argument("--mode", dest="mode", default="auto", choices=list(CHECK_MODES), help="배경 판정을 덮어쓴다 (기본 auto)")
   node.add_argument("--template", dest="template", help="template render 가 낸 template.json. 그 값을 검사 문턱으로 겹친다")
   node.add_argument("--profile-map", dest="profile_map",
                     help="그림마다 프로필을 고르는 지도 yaml (낱장 검수만). --profile 과 같이 못 쓴다")
   node.add_argument("--known", dest="known", action="append",
                     help="알고 두는 경고 목록 JSON [{rule, where, note}]. 맞은 경고 칸은 known 으로 옮긴다 (여러 번 줄 수 있다)")
   node.add_argument("--baseline", dest="baseline", action="append",
                     help="옛 check 보고 JSON. 그 안 경고를 알고 두는 목록으로 더한다 (여러 번 줄 수 있다)")
   node.add_argument("--fail-on-new", dest="fail_on_new", action="store_true", help="새 경고가 하나라도 남으면 fail (종료 4)")


def _add_bake(subs) -> None:
   node = subs.add_parser("bake", help="④ 굽기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True)
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--namespace", default="Game.Art")


def _add_layers(subs) -> None:
   node = subs.add_parser("layers", help="겹 묶음 명령 (compose · diff · mask · view · check · export · fill)")
   inner = node.add_subparsers(dest="sub", required=True)

   stack = inner.add_parser("compose", help="프로필 rig 의 layer_order 로 층을 겹친다 (옛 `layers`)", parents=[COMMON])
   stack.add_argument("--in", dest="in_dir", required=True)
   stack.add_argument("--out", dest="out_dir", required=True)
   stack.add_argument("--rig", required=True)
   stack.add_argument("--anim", action="append")

   diff = inner.add_parser("diff", help="기본체와 inpaint 결과의 차이로 겹을 뗀다", parents=[COMMON])
   diff.add_argument("--base", dest="base", required=True, help="기본체 PNG")
   diff.add_argument("--in", dest="in_dir", required=True, help="inpaint 결과 폴더. 파일 이름 = 겹 이름")
   diff.add_argument("--out", dest="out_dir", required=True, help="겹 묶음 폴더")
   diff.add_argument("--template", dest="template", help="template.json. 마스크 밖이 바뀐 칸을 센다")
   diff.add_argument("--carve", dest="carve", default="report", choices=["report", "common", "apply"],
                     help="깎인 윤곽 : report 본체 그대로 · 세기만(기본) · common 모든 겹이 깎은 칸만 뺀다 · apply 하나라도 깎은 칸을 다 뺀다")
   diff.add_argument("--drop", dest="drop", action="append",
                     help="겹이름:#RRGGBB[,#RRGGBB…] 그 겹에서 이 색에 가까운 칸을 뺀다 (본체가 보인다). 여러 번 줄 수 있다")
   diff.add_argument("--drop-tol", dest="drop_tol", type=int, default=24, help="--drop 색 폭. RGB 각 칸 차이의 최댓값 (기본 24)")
   diff.add_argument("--report", dest="report", help="보고 JSON")

   mask = inner.add_parser("mask", help="기본체에서 이 색 칸만 마스크로", parents=[COMMON])
   mask.add_argument("--in", dest="in_file", required=True, help="기본체 PNG")
   mask.add_argument("--colors", dest="colors", required=True, help="#RRGGBB[,#RRGGBB…]")
   mask.add_argument("--grow", dest="grow", type=int, default=0, help="N 칸 넓힌다 (기본 0)")
   mask.add_argument("--out", dest="out_file", required=True, help="마스크 PNG")

   view = inner.add_parser("view", help="겹을 켜고 끄며 합친 그림", parents=[COMMON])
   view.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더")
   pick = view.add_mutually_exclusive_group()
   pick.add_argument("--only", dest="only", help="이 겹만 (쉼표로)")
   pick.add_argument("--hide", dest="hide", help="이 겹을 빼고 (쉼표로)")
   view.add_argument("--each", dest="each", action="store_true", help="겹마다 한 칸 + 합친 것 한 칸")
   view.add_argument("--out", dest="out_file", required=True)
   view.add_argument("--scale", dest="scale", type=int, default=1)
   view.add_argument("--report", dest="report", help="보고 JSON")

   look = inner.add_parser("check", help="겹 묶음 검사 (경고, --original 다름만 fail)", parents=[COMMON])
   look.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더")
   look.add_argument("--original", dest="original", help="합친 결과와 견줄 원본 PNG")
   look.add_argument("--template", dest="template", help="template.json")
   look.add_argument("--cover", dest="cover", help="가림판 PNG (알파 > 0 = 덮여야 할 칸). 빈 칸은 fail, 겹친 칸은 경고")
   look.add_argument("--report", dest="report", help="보고 JSON")

   ship = inner.add_parser("export", help="합친 한 장 · 겹별 PNG 로 내보내기", parents=[COMMON])
   ship.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더")
   ship.add_argument("--out", dest="out_dir", required=True)
   ship.add_argument("--flat", dest="flat", action="store_true", help="합친 한 장")
   ship.add_argument("--each", dest="each", action="store_true", help="겹별 PNG (캔버스 그대로)")
   ship.add_argument("--trim-common", dest="trim_common", action="store_true", help="겹 전체에 bbox 하나로 잘라 offsets.json")
   ship.add_argument("--anchor", dest="anchor", default=split_mod.ANCHOR_KINDS[0], choices=list(split_mod.ANCHOR_KINDS))
   ship.add_argument("--report", dest="report", help="보고 JSON")

   fill = inner.add_parser("fill", help="가림판 안 빈 칸을 가장 가까운 후보 겹에 채워 새 묶음으로", parents=[COMMON])
   fill.add_argument("--in", dest="in_dir", required=True, help="겹 묶음 폴더 (안 덮는다)")
   fill.add_argument("--mask", dest="mask", required=True, help="가림판 PNG (알파 > 0 = 덮여야 할 칸, 캔버스 크기)")
   fill.add_argument("--nearest", dest="nearest", required=True, help="빈 칸을 붙일 후보 겹 (쉼표로, 거리 같으면 앞 겹)")
   fill.add_argument("--color", dest="color", help="#RRGGBB. 안 주면 가장 가까운 칸의 색")
   fill.add_argument("--items", dest="items", help="손볼 그림 (쉼표로, 기본 전부)")
   fill.add_argument("--out", dest="out_dir", required=True, help="새 묶음 폴더 (없거나 빈 폴더)")
   fill.add_argument("--report", dest="report", help="보고 JSON")


def _add_cutout(subs) -> None:
   node = subs.add_parser("cutout", help="배경 지우기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더")
   node.add_argument("--key", dest="key", default="edge", help=CUTOUT_KEY_HELP)
   node.add_argument("--tol", dest="tol", type=int, default=10, help="가까운 색 폭. RGB 각 칸 차이의 최댓값 (기본 10)")
   node.add_argument("--shave", dest="shave", type=int, default=0, help="지우기 전에 바깥 N 칸을 투명으로 (기본 0)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_trim(subs) -> None:
   node = subs.add_parser("trim", help="여백 걷기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더")
   node.add_argument("--pad", dest="pad", type=int, default=0, help="자른 뒤 둘레에 투명 N 칸 (기본 0)")
   node.add_argument("--square", dest="square", action="store_true", help="긴 변에 맞춰 정사각으로 채운다")
   node.add_argument("--common", dest="common", action="store_true", help="폴더 전체에 bbox 하나")
   node.add_argument("--canvas", dest="canvas", help="WxH — 자른 그림을 이 크기의 투명 판에 놓는다 (--pad · --square 와 같이 못 쓴다)")
   node.add_argument("--anchor", dest="anchor", help="판의 어디에 붙이나 : top · bottom · left · right · center · top-left … (기본 bottom, --canvas 필요)")
   node.add_argument("--margin", dest="margin", type=int, help="붙인 변에서 N 칸 띄운다. 가운데 놓는 축에는 안 먹는다 (기본 0, --canvas 필요)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_outline(subs) -> None:
   node = subs.add_parser("outline", help="외곽선 두르기 (바깥에 더하거나 맨 바깥 칸을 선으로)", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더 (한 장이면 .png 도 된다)")
   node.add_argument("--mode", dest="mode", default="black", help="none · black · solid · selout · selout+light (기본 black). selout 계열은 --profile 의 ramps_file 램프를 쓴다")
   node.add_argument("--where", dest="where", default="outside", help="outside = 칠한 칸 바깥에 더함(기본) · inside = 맨 바깥 칠한 칸을 선으로")
   node.add_argument("--width", dest="width", type=int, default=1, help="두께 1 ~ 4 (기본 1)")
   node.add_argument("--color", dest="color", help="--mode solid 의 색 #RRGGBB (다른 mode 에 주면 종료 2)")
   node.add_argument("--light", dest="light", default="top_left", help="selout+light 의 빛 방향 (기본 top_left)")
   node.add_argument("--grow", dest="grow", action="store_true", help="그리기 전에 캔버스를 사방 --width 만큼 늘린다")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_fill(subs) -> None:
   node = subs.add_parser("fill", help="틀에 갇힌 투명 칸 채우기 (--enclosed)", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더 (한 장이면 .png 도 된다)")
   node.add_argument("--enclosed", dest="enclosed", action="store_true", help="테두리에서 투명 칸으로 못 닿는 투명 칸을 채운다 (지금은 이 방식뿐, 꼭 준다)")
   node.add_argument("--color", dest="color", required=True, help="채울 색 #rrggbb 또는 #rrggbbaa")
   node.add_argument("--max-area", dest="max_area", type=int, help="이 칸 수보다 큰 갇힌 덩이는 안 채운다 (일부러 뚫은 창 지키기)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_diff(subs) -> None:
   node = subs.add_parser("diff", help="두 그림의 알파가 같은지 검사 (--alpha-only, 다르면 종료 4)", parents=[COMMON])
   node.add_argument("--a", dest="a", required=True, help="PNG 한 장 또는 폴더")
   node.add_argument("--b", dest="b", required=True, help="PNG 한 장 또는 폴더 (폴더면 같은 이름끼리 짝)")
   node.add_argument("--alpha-only", dest="alpha_only", action="store_true", help="알파만 견준다 (지금은 이 방식뿐, 꼭 준다)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_measure(subs) -> None:
   node = subs.add_parser("measure", help="재기 묶음 명령 (shape)")
   inner = node.add_subparsers(dest="sub", required=True)
   shape = inner.add_parser("shape", help="덩이 하나의 중심 · 반지름 · 원다움을 잰다 (파일 안 씀)", parents=[COMMON])
   shape.add_argument("--in", dest="in_path", required=True, help="PNG 한 장")
   shape.add_argument("--at", dest="at", help="x,y. 그 칸과 같은 색으로 이어진 덩이를 잰다 (--color 와 둘 중 하나)")
   shape.add_argument("--color", dest="color", help="#rrggbb. 이 색 칸 덩이 가운데 가장 큰 것을 잰다")
   shape.add_argument("--tol", dest="tol", type=int, default=0, help="색 폭. RGB 각 칸 차이의 최댓값 (기본 0)")
   shape.add_argument("--report", dest="report", help="보고 JSON (mask --from-shape 가 그대로 읽는다)")


def _add_palette(subs) -> None:
   node = subs.add_parser("palette", help="팔레트 묶음 명령 (check)")
   inner = node.add_subparsers(dest="sub", required=True)
   look = inner.add_parser("check", help="램프 파일 하나의 모양(ramp_shape)을 그림 없이 한 번 잰다 (파일 안 씀)", parents=[COMMON])
   look.add_argument("--ramps", dest="ramps", help="잴 램프 JSON. 안 주면 --profile 의 palette.ramps_file")
   look.add_argument("--report", dest="report", help="보고 JSON")


def _add_mask(subs) -> None:
   node = subs.add_parser("mask", help="measure shape 로 잰 원으로 흰 가림판 PNG", parents=[COMMON])
   node.add_argument("--from-shape", dest="from_shape", required=True, help="measure shape 보고 JSON (shape.center · shape.r)")
   node.add_argument("--size", dest="size", help="w,h 출력 크기 (--like 와 둘 중 하나)")
   node.add_argument("--like", dest="like", help="이 PNG 의 크기만 빌린다")
   node.add_argument("--r", dest="r", default="round", help="round(r 반올림, 기본) · max(r_max) · 양수")
   node.add_argument("--invert", dest="invert", action="store_true", help="원 바깥을 흰색으로")
   node.add_argument("--out", dest="out_file", required=True, help="PNG")
   node.add_argument("--report", dest="report", help="보고 JSON")

def _add_shift(subs) -> None:
   node = subs.add_parser("shift", help="색을 HSV 로 옮기기 (색상 · 채도 · 명도)", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더 (한 장이면 .png 도 된다)")
   node.add_argument("--hue", dest="hue", type=float, default=0, help="색상에 D 도 더한다 (-360~360, 기본 0)")
   node.add_argument("--sat", dest="sat", type=float, default=1.0, help="채도에 K 를 곱한다 (0 이상, 기본 1)")
   node.add_argument("--light", dest="light", type=float, default=0, help="HSV 명도(V)에 L 을 더한다 (-1~1, 기본 0)")
   node.add_argument("--pick", dest="pick", help="이 색만 옮긴다 #RRGGBB[,#RRGGBB…] (없으면 불투명 색 전부)")
   node.add_argument("--report", dest="report",
                     help="보고 JSON. 옮긴 색은 대개 ramps_file 밖이라 check 의 palette 에 걸린다 — 뒤에 merge-colors 로 램프에 붙인다")


def _add_sheet(subs) -> None:
   node = subs.add_parser("sheet", help="비교판 (확대 · 실루엣 · 4색 · 흐림 · 타일)", parents=[COMMON])
   node.add_argument("--in", dest="in_paths", required=True, nargs="+", help="PNG 또는 폴더 여럿. 그림 하나 = 한 줄")
   node.add_argument("--out", dest="out_file", required=True, help="비교판 PNG")
   node.add_argument("--kinds", dest="kinds", default="zoom", help="zoom,silhouette,colors4,blur,tile,fit:N 중 쉼표로 (기본 zoom)")
   node.add_argument("--scale", dest="scale", default="auto",
                     help="auto · per(그림마다 auto, 줄 딱지 끝에 ×N) 또는 정수 배 (기본 auto)")
   node.add_argument("--strip", dest="strip", action="store_true",
                     help="여백 0 · 딱지 없음 · 배율 1 · 투명 바탕으로 --in 순서대로 가로로 붙인다 (--kinds · --scale · --grid 와 같이 못 쓴다)")
   node.add_argument("--tile", dest="tile", type=int, default=2, choices=[2, 4], help="tile 판의 반복 수 (기본 2)")
   node.add_argument("--bg", dest="bg", default="checker", help="checker 또는 #RRGGBB (기본 checker)")
   node.add_argument("--label", dest="label", action="store_true", help="이름 · 크기 · 색 수 딱지")
   node.add_argument("--grid", dest="grid", type=int, default=0, help="zoom 판에 원본 N 칸마다 눈금선 · 좌표 (기본 0 = 끔, 배율은 4 이상으로 올린다)")
   node.add_argument("--grid-color", dest="grid_color", help="눈금선 색 #RRGGBB (기본 #FF00FF)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_template(subs) -> None:
   node = subs.add_parser("template", help="템플릿 (그리기 전 밑판)")
   inner = node.add_subparsers(dest="sub", required=True)

   listing = inner.add_parser("list", help="템플릿 목록", parents=[COMMON])
   listing.add_argument("--kind", dest="kind", help="이 kind 만")

   show = inner.add_parser("show", help="크기에 맞춘 값 · 프롬프트 · 순서", parents=[COMMON])
   show.add_argument("name", help="템플릿 이름 또는 JSON 경로")
   show.add_argument("--size", dest="size", help="예 : 32x32 · 32 (정사각)")
   show.add_argument("--preset", dest="preset", help="presets 안 이름")
   show.add_argument("--base", dest="base", help="palette 템플릿 : 바탕색 #RRGGBB")
   show.add_argument("--material", dest="material", help="palette 템플릿 : 재질 프리셋 (cloth · stone · metal …)")

   draw = inner.add_parser("render", help="가이드 겹 · 마스크 · 미리보기 · template.json 쓰기", parents=[COMMON])
   draw.add_argument("name", help="템플릿 이름 또는 JSON 경로")
   draw.add_argument("--size", dest="size", required=True, help="예 : 32x32 · 32 (정사각)")
   draw.add_argument("--out", dest="out_dir", required=True)
   draw.add_argument("--preset", dest="preset", help="presets 안 이름")
   draw.add_argument("--base", dest="base", help="palette 템플릿 : 바탕색 #RRGGBB")
   draw.add_argument("--material", dest="material", help="palette 템플릿 : 재질 프리셋 (cloth · stone · metal …)")
   draw.add_argument("--scale", dest="scale", type=int, help="미리보기 배율")
   draw.add_argument("--over", dest="over", help="가이드를 이 그림 위에 얹은 확대판도 낸다")


def _add_style(subs) -> None:
   node = subs.add_parser("style", help="화풍")
   inner = node.add_subparsers(dest="sub", required=True)

   pull = inner.add_parser("extract", help="기준 그림 폴더에서 화풍 뽑기", parents=[COMMON])
   pull.add_argument("--in", dest="in_dirs", required=True, action="append", help="기준 PNG 폴더. 여러 번 줄 수 있다")
   pull.add_argument("--out", dest="out_dir", required=True)
   pull.add_argument("--name", dest="name", help="결과 이름 (기본 첫 --in 폴더 이름)")
   pull.add_argument("--ramp-len", dest="ramp_len", type=int, help="램프 길이 (기본 프로필 palette.ramp_len)")
   pull.add_argument("--max-colors", dest="max_colors", type=int, default=None, help="전체 색 상한 (기본 64)")
   pull.add_argument("--by-folder", dest="by_folder", action="store_true",
                     help="--in 아래 하위 폴더(종류)마다 따로 뽑고 NAME_kinds.json 요약 표를 낸다")
   pull.add_argument("--mode", dest="mode", default="auto", choices=list(CHECK_MODES))
   pull.add_argument("--with-backgrounds", dest="with_backgrounds", action="store_true", help="배경 그림 색도 팔레트에 섞는다")

   ref = inner.add_parser("ref", help="PixelLab 에 넘길 화풍 그림 준비 (자르기 · 색 줄이기 · 팔레트 PNG · base64)", parents=[COMMON])
   ref.add_argument("--in", dest="in_file", required=True, help="화풍 그림 PNG")
   ref.add_argument("--canvas", dest="canvas", required=True, help="뽑을 캔버스 WxH. 이보다 크면 불투명 칸 가운데로 자른다 (키우기 · 줄이기는 안 한다)")
   ref.add_argument("--out", dest="out_file", required=True, help="팔레트 PNG")
   ref.add_argument("--crop", dest="crop", help="먼저 이 칸만 X,Y,W,H")
   ref.add_argument("--colors", dest="colors", type=int, default=32, help="색 상한 2~256 (기본 32)")
   ref.add_argument("--b64", dest="b64", help="base64 한 줄을 쓸 파일 (stdout · 보고에는 안 싣는다)")
   ref.add_argument("--max-kb", dest="max_kb", type=float, default=12.0, help="base64 가 이 KB 를 넘으면 경고 (기본 12)")
   ref.add_argument("--report", dest="report", help="보고 JSON")


def _add_intake(subs) -> None:
   node = subs.add_parser("intake", help="받은 그림 한 번에 손질 (cutout → trim → check → sheet)", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더")
   node.add_argument("--out", dest="out_dir", required=True, help="손질한 그림 폴더")
   node.add_argument("--key", dest="key", default="edge", help=CUTOUT_KEY_HELP)
   node.add_argument("--tol", dest="tol", type=int, default=10)
   node.add_argument("--shave", dest="shave", type=int, default=0)
   node.add_argument("--pad", dest="pad", type=int, default=0)
   node.add_argument("--square", dest="square", action="store_true")
   node.add_argument("--template", dest="template", help="template.json (check 에 넘긴다)")
   node.add_argument("--sheet", dest="sheet", help="주면 비교판 PNG 도 낸다")
   node.add_argument("--no-cutout", dest="no_cutout", action="store_true", help="바탕 지우기를 건너뛴다")
   node.add_argument("--no-trim", dest="no_trim", action="store_true", help="여백 걷기를 건너뛴다")
   node.add_argument("--no-check", dest="no_check", action="store_true", help="검수를 건너뛴다")
   node.add_argument("--report", dest="report", help="보고 JSON (넷을 묶은 것)")


def _add_bands(subs) -> None:
   node = subs.add_parser("bands", help="흰 띠 · 몰딩 줄 찾기 (조각을 이을 자리)", parents=[COMMON])
   node.add_argument("--in", dest="in_file", required=True, help="PNG 한 장")
   node.add_argument("--axis", dest="axis", default="y", choices=["y", "x"], help="y 가로줄(기본) · x 세로줄")
   node.add_argument("--top", dest="top", type=int, default=8, help="후보 줄 수 (기본 8)")
   node.add_argument("--mark", dest="mark", help="원본 ×2 에 줄 번호 눈금을 찍은 PNG")
   node.add_argument("--report", dest="report", help="보고 JSON (stdout 에도 같은 것)")


def _add_stitch(subs) -> None:
   node = subs.add_parser("stitch", help="조각 잇기 (파일:시작-끝 을 차례로)", parents=[COMMON])
   node.add_argument("--in", dest="in_specs", required=True, nargs="+",
                     help="파일[:시작-끝] 여럿. 끝은 안 넣고, 비우면 끝까지(12-), 구간을 빼면 그림 전체")
   node.add_argument("--out", dest="out_file", required=True, help="이은 PNG")
   node.add_argument("--axis", dest="axis", default="y", choices=["y", "x"], help="y 위→아래(기본) · x 왼→오른")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_extend(subs) -> None:
   node = subs.add_parser("extend", help="늘리기 묶음 (줄 · 칸을 되풀이하거나 빼기만, 보간 없음)")
   inner = node.add_subparsers(dest="sub", required=True)

   period = inner.add_parser("period", help="되풀이 단위 찾기 · 타일 배수 검사 · 한 단위 맞추기", parents=[COMMON])
   period.add_argument("--in", dest="in_file", required=True, help="띠 그림 PNG (울타리 · 난간 …)")
   period.add_argument("--axis", dest="axis", default="x", choices=["x", "y"], help="x 가로로 되풀이(기본) · y 세로로")
   period.add_argument("--tile", dest="tile", type=int, help="단위가 이 값의 배수인지 본다")
   period.add_argument("--out", dest="out_file", help="한 단위를 잘라 쓴 PNG")
   period.add_argument("--fit", dest="fit", type=int, help="잘라 낸 단위 길이를 N 으로 맞춘다 (단위의 ±25%% 안)")
   period.add_argument("--report", dest="report", help="보고 JSON")

   ring = inner.add_parser("ring", help="한 바퀴 그림(모서리 · 변 단위) 늘리기", parents=[COMMON])
   ring.add_argument("--in", dest="in_file", required=True, help="한 바퀴 그림 PNG")
   ring.add_argument("--border", dest="border", required=True, help="N 또는 L,B,R,T ([왼, 아래, 오른, 위])")
   ring.add_argument("--size", dest="size", required=True, help="만들 크기 WxH")
   ring.add_argument("--out", dest="out_file", required=True)
   ring.add_argument("--snap", dest="snap", action="store_true", help="변 단위가 딱 맞는 가까운 크기로 바꿔 만든다 (기본은 경고만)")
   ring.add_argument("--report", dest="report", help="보고 JSON")

   canvas = inner.add_parser("canvas", help="배경 캔버스 늘리기 (가장자리 줄 · 띠를 바깥으로 되풀이)", parents=[COMMON])
   canvas.add_argument("--in", dest="in_file", required=True, help="배경 PNG")
   canvas.add_argument("--size", dest="size", required=True, help="만들 크기 WxH (원본보다 작은 변은 안 된다)")
   canvas.add_argument("--out", dest="out_file", required=True)
   canvas.add_argument("--anchor", dest="anchor", default="bottom", choices=list(extend_canvas_mod.ANCHORS),
                       help="원본을 둘 자리 (기본 bottom — 위로 늘린다)")
   canvas.add_argument("--band", dest="band", type=int, default=1, help="되풀이할 가장자리 줄 수 (기본 1)")
   canvas.add_argument("--report", dest="report", help="보고 JSON")


def _add_reline(subs) -> None:
   node = subs.add_parser("reline", help="받은 그림의 외곽선을 한 색으로", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더")
   node.add_argument("--color", dest="color",
                     help="외곽선 색 #RRGGBB. 안 주면 --profile 의 palette.outline, 그것도 없으면 고리의 어두운 칸에서 가장 많은 색")
   # pick · tol 기본(dark · 40)은 reline.run 이 채운다. 여기서 None 이어야 --from 과 같이 준 것을 가린다
   node.add_argument("--pick", dest="pick", choices=["dark", "all"], help="dark 고리의 어두운 칸만(기본) · all 고리 전부")
   node.add_argument("--scope", dest="scope", default="ring", choices=["ring", "colors"], help="ring 고른 칸만(기본) · colors 그 색을 그림 전체에서")
   node.add_argument("--tol", dest="tol", type=int, help="dark 폭. 고리의 가장 어두운 밝기 + N 까지 (기본 40)")
   node.add_argument("--from", dest="from_colors",
                     help="바꿀 선 색 #RRGGBB[,#RRGGBB…]. 고리 칸 중 이 색인 칸만 바꾼다 (--pick · --tol 과 같이 못 쓴다)")
   node.add_argument("--depth", dest="depth", type=int,
                     help="투명에서 N 칸 안까지 본다 (1~8, 기본 1). 2 면 2px 선의 안쪽 줄도 바꾼다 (--scope ring 만)")
   node.add_argument("--color-dark", dest="color_dark", help="둘째 선 색 #RRGGBB. 옆 면과 밝기가 비슷한 칸에만 쓴다")
   node.add_argument("--dark-gap", dest="dark_gap", type=int, help="밝기 차가 G 보다 작으면 둘째 색 (기본 24, --color-dark 와 같이)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_tint(subs) -> None:
   node = subs.add_parser("tint", help="흰 겹 × 색 곱하기 → 색마다 한 장", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="흰 ~ 밝은 회색 겹 PNG 한 장 또는 폴더")
   node.add_argument("--colors", dest="colors", required=True, help="#RRGGBB[,#RRGGBB…]")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더. 이름은 <원래이름>_<RRGGBB>.png")
   node.add_argument("--sheet", dest="sheet", help="원본 + 색마다 늘어놓은 비교판 PNG")
   node.add_argument("--scale", dest="scale", type=int, default=4, help="비교판 배율 (기본 4)")
   node.add_argument("--gif", dest="gif", help="색마다 낸 그림을 순서대로 프레임으로 한 GIF")
   node.add_argument("--duration", dest="duration", type=int, help="GIF 프레임 한 장 ms (기본 110, --gif 와 같이)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_merge(subs) -> None:
   node = subs.add_parser("merge-colors", help="가까운 색 합치기 → 색 수 줄이기", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="PNG 한 장 또는 폴더(바로 아래 .png)")
   node.add_argument("--out", dest="out_dir", required=True, help="결과 폴더 (한 장이면 .png 도 된다)")
   # tol · max_colors 는 None 으로 받는다 — 셋 다 안 준 것(near_colors 문턱)과 --palette 와 같이 준 것을 merge.run 이 가린다
   node.add_argument("--tol", dest="tol", type=int, help="RGB 각 칸 차이의 최댓값 ≤ N 이면 합친다 (0~255). 셋 다 안 주면 프로필 near_colors.max_delta")
   node.add_argument("--max-colors", dest="max_colors", type=int, help="가장 가까운 짝부터 N 색까지 합친다. --tol 을 같이 주면 그 안의 짝만")
   node.add_argument("--palette", dest="palette", action="store_true", help="프로필 ramps_file 색 중 가장 가까운 색으로 (--tol · --max-colors 와 같이 못 쓴다)")
   node.add_argument("--keep", dest="keep", help="지킬 색 #RRGGBB[,#RRGGBB…] — 남는 색으로만 쓴다")
   node.add_argument("--per-image", dest="per_image", action="store_true", help="장마다 따로 합친다 (기본은 입력 전체로 표 하나)")
   node.add_argument("--clean", dest="clean", action="store_true",
                     help="합친 뒤 잡티 점(외톨이 · 2칸)을 둘레 색으로 메운다. 이웃 6/8 이 한 색이고 그 색과 가까울 때만 (기본 끔)")
   node.add_argument("--sheet", dest="sheet", help="장마다 전 · 후를 늘어놓은 비교판 PNG")
   node.add_argument("--scale", dest="scale", type=int, default=4, help="비교판 배율 (기본 4)")
   node.add_argument("--report", dest="report", help="보고 JSON")


def _add_frames(subs) -> None:
   node = subs.add_parser("frames", help="프레임 묶음 명령 (bake)")
   inner = node.add_subparsers(dest="sub", required=True)
   bake = inner.add_parser("bake", help="프레임 폴더를 발 줄 → 덮기 → 자르기 → 띠 → gif 순서로 굽는다", parents=[COMMON])
   bake.add_argument("--in", dest="in_dir", required=True, help="프레임 PNG 폴더. 이름 자연 정렬(f2 < f10) = 프레임 순서")
   bake.add_argument("--out", dest="out_dir", required=True, help="구운 프레임 폴더 (같은 이름으로 쓴다)")
   bake.add_argument("--foot", help="맨 아래 불투명 줄을 이 y 로 맞춘다. auto = 첫 프레임의 발 줄")
   bake.add_argument("--cover", help="마스크 PNG. 알파 > 0 칸을 --cover-from 그림의 같은 칸으로 덮는다")
   bake.add_argument("--cover-from", dest="cover_from", help="덮을 기준 그림 (기본 = 발 줄 맞춘 첫 프레임)")
   bake.add_argument("--crop", help="x,y,w,h 또는 union(모든 프레임 불투명 상자를 합친 것)")
   bake.add_argument("--strip", help="가로 띠 PNG 한 장")
   bake.add_argument("--gif", help="움직이는 gif")
   bake.add_argument("--duration", type=int, help="gif 한 장 ms (기본 110)")
   bake.add_argument("--loop", type=int, help="gif 반복 수 (기본 0 = 끝없이)")
   bake.add_argument("--scale", type=int, default=1, help="띠 · gif 만 키운다 (프레임 PNG 는 원래 크기)")


def _add_split(subs) -> None:
   node = subs.add_parser("split", help="한 장 → 겹 여러 장 (나누기 표)", parents=[COMMON])
   node.add_argument("--in", dest="in_file", required=True, help="한 장 PNG")
   node.add_argument("--spec", help="나누기 표 split.json")
   node.add_argument("--out", dest="out", required=True, help="겹 폴더. --list-colors 면 색 목록 JSON 파일")
   node.add_argument("--rig", help="주면 프로필 rigs.<rig>.layer_order 와 표의 layers 가 같아야 한다")
   node.add_argument("--min-piece", dest="min_piece", type=int, help=f"떨어진 조각 기본 크기 (기본 {split_mod.DEFAULT_MIN_PIECE})")
   node.add_argument("--gray-levels", dest="gray_levels", help="겹으로 나눈 뒤 밝기를 이 회색 단계로 (예 255,220,180)")
   node.add_argument("--list-colors", dest="list_colors", action="store_true", help="나누지 않고 색 목록만 낸다")


def _add_recolor(subs) -> None:
   node = subs.add_parser("recolor", help="겹 + 색표 → N장", parents=[COMMON])
   node.add_argument("--in", dest="in_dir", required=True, help="밑감 겹 폴더")
   node.add_argument("--spec", required=True, help="색표 recolor.json")
   node.add_argument("--out", dest="out_dir", required=True)
   node.add_argument("--sheet", help="구운 그림과 조합을 늘어놓은 미리보기 PNG")
   node.add_argument("--scale", type=int, help="미리보기 배율 (--sheet 와 같이)")


def _add_tile(subs) -> None:
   node = subs.add_parser("tile", help="타일 명령 묶음")
   inner = node.add_subparsers(dest="sub", required=True)

   grow = inner.add_parser("blob", help="② 템플릿 6장 → 47장", parents=[COMMON])
   grow.add_argument("--in", dest="in_dir", required=True)
   grow.add_argument("--out", dest="out_dir", required=True)

   put = inner.add_parser("place", help="③ 배치 (DeBroglie)", parents=[COMMON])
   put.add_argument("--tileset", required=True, help="tileset.json")
   put.add_argument("--rules", required=True)
   put.add_argument("--size", required=True, help="예 : 64x64")
   put.add_argument("--out", dest="out_dir", required=True)
   put.add_argument("--exe", help="DeBroglie 실행 파일")
   put.add_argument("--seed", type=int)

   to_ldtk = inner.add_parser("ldtk", help="맵 JSON → LDtk 파일", parents=[COMMON])
   to_ldtk.add_argument("--map", dest="map_file", required=True)
   to_ldtk.add_argument("--tileset", required=True)
   to_ldtk.add_argument("--out", dest="out_file", required=True)

   show = inner.add_parser("preview", help="낱장 여러 장 → 실제 칸 수로 조립한 미리보기", parents=[COMMON])
   show.add_argument("--layout", required=True, help="배치표 layout.json (weights+seed 또는 cells)")
   show.add_argument("--in", dest="in_dir", required=True, help="타일 PNG 폴더. 배치표 이름 = 파일 이름")
   show.add_argument("--out", dest="out_file", required=True, help="미리보기 PNG")
   show.add_argument("--scale", type=int, help="배율 (기본 1, NEAREST)")

   look = inner.add_parser("inspect", help="낱장 한 표 (크기 · bbox · 반투명 · 네 변 · 넘친 픽셀)", parents=[COMMON])
   look.add_argument("--in", dest="in_dir", required=True, help="타일 PNG 폴더 또는 PNG 한 장")
   look.add_argument("--report", required=True)
   look.add_argument("--size", type=int, help="타일 한 변. 안 주면 프로필 tiles.size")

   join = inner.add_parser("seam", help="이음매 검사 (3×3 이어 붙이기)", parents=[COMMON])
   join.add_argument("--in", dest="in_dir", required=True, help="타일 PNG 폴더 또는 PNG 한 장")
   join.add_argument("--report", required=True)
   join.add_argument("--k", type=float, default=seam_mod.DEFAULT_K, help=f"이음 줄 차이가 안쪽 평균의 몇 배를 넘으면 실패 (기본 {seam_mod.DEFAULT_K})")
   join.add_argument("--pairs", action="store_true", help="변종끼리 모든 순서쌍(A 오른쪽 ↔ B 왼쪽, A 아래 ↔ B 위)도 본다")
   join.add_argument("--sheet", help="3×3 으로 이은 그림을 늘어놓은 PNG")
   join.add_argument("--scale", type=int, help="--sheet 배율")

   shift = inner.add_parser("offset", help="반 칸 밀기 + 가운데 십자 가림판 (inpaint 로 이음매 지우기)", parents=[COMMON])
   shift.add_argument("--in", dest="in_file", required=True, help="바탕 타일 PNG")
   shift.add_argument("--out", dest="out_file", required=True, help="반 칸 민 PNG")
   shift.add_argument("--mask", dest="mask", required=True, help="가림판 PNG (검정 바탕 + 흰 십자 = 다시 그릴 자리)")
   shift.add_argument("--band", dest="band", type=int, default=16, help="십자 띠 폭, 짝수 (기본 16)")
   shift.add_argument("--report", dest="report", help="보고 JSON")


def _add_ui(subs) -> None:
   node = subs.add_parser("ui", help="UI 명령 묶음")
   inner = node.add_subparsers(dest="sub", required=True)

   draw = inner.add_parser("frame", help="①ㄱ 프레임 그리기", parents=[COMMON])
   draw.add_argument("--kind", required=True, choices=list(ui_frame_mod.KINDS))
   draw.add_argument("--size", help="예 : 16x16. 안 주면 프로필의 ui.frame.source")
   draw.add_argument("--out", dest="out_dir", required=True)

   bring = inner.add_parser("import", help="①ㄴ .9.png 들여오기", parents=[COMMON])
   bring.add_argument("--in", dest="in_dir", required=True)
   bring.add_argument("--out", dest="out_dir", required=True)

   cut = inner.add_parser("icons", help="①ㄷ 아이콘 들이기", parents=[COMMON])
   cut.add_argument("--in", dest="in_file", required=True, help="아이콘 시트 PNG, 또는 낱장 PNG 폴더")
   cut.add_argument("--cell", type=int, help="시트를 자를 칸 크기. 시트 파일에만 쓴다")
   cut.add_argument("--family", help="아이콘 가족 이름. 안 주면 시트·폴더 이름")
   cut.add_argument("--fit", type=int, help="낱장을 N×N 가운데에 맞춘다. 폴더에만 쓰고, 제자리면 원본을 덮어쓴다")
   cut.add_argument("--out", dest="out_dir", required=True)

   look = inner.add_parser("check", help="② UI 검수", parents=[COMMON])
   look.add_argument("--in", dest="in_dir", required=True)
   look.add_argument("--report", required=True)
   look.add_argument("--manifest", default=None, help="구워 둔 ui_manifest.json. 주면 PPU 를 대조한다")

   burn = inner.add_parser("bake", help="③ UI 굽기", parents=[COMMON])
   burn.add_argument("--in", dest="in_dir", required=True)
   burn.add_argument("--out", dest="out_dir", required=True)
   burn.add_argument("--namespace", default="Game.UI")
   burn.add_argument("--assets-root", dest="assets_root", default=None)

   page = inner.add_parser("screen", help="화면 JSON → UXML · USS", parents=[COMMON])
   page.add_argument("--spec", required=True)
   page.add_argument("--out", dest="out_dir", required=True)
   page.add_argument("--manifest", default=None)
   page.add_argument("--assets-root", dest="assets_root", default=None)

   glyph = inner.add_parser("font", help="글자 뽑기", parents=[COMMON])
   glyph.add_argument("--scan", action="append", help="훑을 폴더. 뿌리 아래 상대경로만. 여러 번 줄 수 있다")
   glyph.add_argument("--scan-root", dest="scan_root", default=None, help="훑을 뿌리. 안 주면 프로필 파일 폴더")
   glyph.add_argument("--out", dest="out_file", required=True)

   stretch = inner.add_parser("preview", help="안내선 없는 9조각을 늘려 본다", parents=[COMMON])
   stretch.add_argument("--in", dest="in_file", required=True, help="판넬 PNG (.9.png 면 --border 를 빼도 된다)")
   stretch.add_argument("--border", dest="border", help="N 또는 L,B,R,T ([왼, 아래, 오른, 위])")
   stretch.add_argument("--size", dest="size", required=True, help="WxH[,WxH…] 여럿이면 옆으로 나란히")
   stretch.add_argument("--out", dest="out_file", required=True)
   stretch.add_argument("--mode", dest="mode", default="stretch", choices=["stretch", "tile"], help="stretch(Unity Sliced, 기본) · tile")
   stretch.add_argument("--scale", dest="scale", type=int, default=1, help="배율 (기본 1)")

   glyphs = inner.add_parser("glyphs", help="글꼴에 없는 글자 찾기 (없으면 fail)", parents=[COMMON])
   glyphs.add_argument("--font", dest="font", required=True, help="ttf · otf 글꼴 파일")
   glyphs.add_argument("--text", dest="text", help="검사할 글자 (--text-file 과 둘 중 하나)")
   glyphs.add_argument("--text-file", dest="text_file", help="글자 파일 (ui font 가 낸 것 그대로)")
   glyphs.add_argument("--size", dest="size", type=int, default=16, help="그려 볼 글자 크기 (기본 16)")
   glyphs.add_argument("--report", dest="report", help="보고 JSON")


def _add_provider(subs) -> None:
   node = subs.add_parser("provider", help="제공자")
   inner = node.add_subparsers(dest="sub", required=True)
   inner.add_parser("list", help="켜진 제공자 목록", parents=[COMMON])

   make = inner.add_parser("make", help="그림 만들기 요청", parents=[COMMON])
   make.add_argument("--kind", required=True, choices=list(providers.KINDS))
   make.add_argument("--spec", help="ProviderRequest JSON 파일")
   make.add_argument("--out", dest="out_dir", required=True)


def _profile(args):
   return load_profile_args(args)


def _command_key(args) -> tuple[str, str | None]:
   return args.command, getattr(args, "sub", None)


def _import_late(module_name: str, label: str):
   """모듈을 부를 때 읽는다. 그 모듈(또는 그 위 꾸러미)이 아직 없을 때만 「아직 구현 안 됨」으로 바꾼다.

   모듈 안에서 다른 것이 없어 난 ModuleNotFoundError 는 진짜 오류라 그대로 올린다.
   """
   try:
      return importlib.import_module(module_name)
   except ModuleNotFoundError as exc:
      missing = exc.name or ""
      if missing and (module_name == missing or module_name.startswith(missing + ".")):
         raise UsageError(f"아직 구현 안 됨 : {label} ({module_name} 이 없다)") from exc
      raise


def _run_late(args, module_name: str, func_name: str) -> dict:
   label = " ".join(part for part in _command_key(args) if part)
   func = getattr(_import_late(module_name, label), func_name, None)
   if not callable(func):
      raise UsageError(f"아직 구현 안 됨 : {label} ({module_name}.{func_name} 이 없다)")
   result = func(args)
   report = getattr(args, "report", None)
   if report and isinstance(result, dict):
      write_json(jailed_output(report), result)
   return result


# --report 와 견줄 인자들 — 읽는 파일 · 쓰는 그림. 보고 JSON 이 이 중 하나를 덮으면 안 된다 (리뷰 R1-M5)
REPORT_GUARDED = ("in_dir", "in_file", "base", "original", "template", "spec", "manifest", "layout", "tileset",
                  "rules", "map_file", "skeleton", "markers", "out_file", "out_dir", "sheet", "out",
                  "b64", "mark", "mask", "font", "text_file", "gif", "known", "baseline",
                  "in_path", "from_shape", "like", "profile_map", "ramps", "cover")


def _guard_report(args) -> None:
   """`--report` 는 `.json` 만 받고, 입력 · 출력 경로와 같으면 거절한다. 명령을 돌리기 **전에** 본다.

   PNG 를 --report 로 주면 원본 그림이 JSON 으로 바뀌던 사고를 막는다. 같은 경로 견주기는 `paths.guard_overwrite` 한 곳을 쓴다.
   """
   report = getattr(args, "report", None)
   if not report:
      return
   if Path(str(report)).suffix.lower() != ".json":
      raise UsageError(f"--report 는 .json 파일만 받는다 : {report}")
   reads = []
   for name in REPORT_GUARDED:
      value = getattr(args, name, None)
      for one in value if isinstance(value, (list, tuple)) else [value]:
         if isinstance(one, (str, os.PathLike)):
            reads.append(one)
   guard_overwrite([report], reads, "--report")


# 공통 인자를 실제로 쓰는 명령 (2026-10-05). 표 밖 명령에 그 인자가 오면 조용히 무시하지 않고 종료 2 로 거절한다.
# dry-run 은 세 무리로 나눈다. 새 명령은 셋 중 한 곳에 꼭 넣는다 — 빠뜨리면 test_dry_run 이 깨진다.
DRY_RUN_TAKES = {
   ("cutout", None), ("trim", None), ("reline", None), ("tint", None), ("merge-colors", None), ("shift", None),   # 안 쓰고 보고만
   ("outline", None), ("fill", None), ("mask", None),
   ("intake", None),                                                                            # 검수용 임시 폴더만 쓰고 지운다
   # 정해진 파일 한두 개를 쓰는 명령 (2026-10-06) — 안 쓰고 보고만
   ("stitch", None), ("sheet", None), ("bands", None), ("anchors", None),
   ("extend", "period"), ("extend", "ring"), ("extend", "canvas"), ("style", "ref"),
   ("layers", "mask"), ("layers", "view"), ("ui", "preview"), ("ui", "font"),
   ("layers", "fill"),                                                                          # 새 묶음 폴더 — 쓸 목록을 보고만
   ("frames", "bake"),                                                                          # 프레임 폴더 · 띠 · gif — 쓸 목록을 보고만
   ("tile", "offset"), ("tile", "preview"), ("tile", "ldtk"), ("tile", "seam"),
   ("tile", "place"), ("provider", "make"),                                                      # 바깥을 안 부르고 요청 JSON 만
}
# 파일을 안 쓰는 명령 — 쓸 것이 없어 dry-run 을 그대로 받는다 (--report 는 cli 가 쓴다). 실제로 돌려 확인함 (test_dry_run_wide)
DRY_RUN_HARMLESS = {
   ("profile", "show"), ("check", None), ("layers", "check"), ("tile", "inspect"), ("ui", "check"), ("ui", "glyphs"),
   ("template", "list"), ("template", "show"), ("provider", "list"), ("diff", None),
   ("measure", "shape"), ("palette", "check"),
}
# 폴더째 여러 파일을 쓰는 명령. 쓸 목록이 셈 중간에 정해지거나 앞 단계 산출물을 읽어 S 로 안 된다 — 까닭은 진행상황.md
DRY_RUN_REFUSED = {
   ("normalize", None), ("bake", None), ("split", None), ("recolor", None),
   ("layers", "compose"), ("layers", "diff"), ("layers", "export"),
   ("tile", "blob"),
   ("ui", "frame"), ("ui", "import"), ("ui", "icons"), ("ui", "bake"), ("ui", "screen"),
   ("template", "render"), ("style", "extract"),
}
FORCE_TAKES = {("bake", None), ("ui", "bake"), ("style", "extract")}
PROVIDER_TAKES = {("provider", "make")}


def _label(key: tuple[str, str | None]) -> str:
   return " ".join(part for part in key if part)


def _guard_common(args) -> None:
   """공통 인자를 안 쓰는 명령에 그 인자가 오면 UsageError. 명령 앞에 붙인 전역 자리도 같은 칸이라 같이 걸린다."""
   key = _command_key(args)
   checks = (
      ("--dry-run", getattr(args, "dry_run", False), DRY_RUN_TAKES | DRY_RUN_HARMLESS, DRY_RUN_TAKES),
      ("--force", getattr(args, "force", False), FORCE_TAKES, FORCE_TAKES),
      ("--provider", getattr(args, "provider", None) is not None, PROVIDER_TAKES, PROVIDER_TAKES),
   )
   for flag, given, takes, shown in checks:
      if given and key not in takes:
         names = " · ".join(sorted(_label(k) for k in shown))
         raise UsageError(f"이 명령({_label(key)})은 {flag} 인자를 안 받는다 (받는 명령 : {names})")


def run(args) -> dict:
   _guard_report(args)
   _guard_common(args)
   late = LATE.get(_command_key(args))
   if late is not None:
      return _run_late(args, *late)

   table = {
      "profile": _run_profile,
      "normalize": _run_normalize,
      "anchors": _run_anchors,
      "check": _run_check,
      "bake": _run_bake,
      "layers": _run_layers,
      "split": _run_split,
      "recolor": _run_recolor,
      "tile": _run_tile,
      "ui": _run_ui,
      "provider": _run_provider,
   }
   return table[args.command](args)


def _run_profile(args) -> dict:
   prof = _profile(args)
   # 겹친 값 그대로에 사람용 줄(한도 · 외곽선)만 덧붙인다. 다른 칸은 예전과 같다.
   return {**prof.as_dict(), "show_lines": profile_show_lines(prof)}


def _run_normalize(args) -> dict:
   return normalize_mod.normalize(_profile(args), args.in_dir, args.out_dir, args.anim)


def _run_anchors(args) -> dict:
   prof = _profile(args)
   in_dir = Path(args.in_dir)
   out = jailed_output(args.out_file)
   # 읽기 전에 : --out 이 읽을 JSON(skeleton 이나 --in 의 frames.json)이면 덮지 않는다
   guard_overwrite([out], [args.skeleton if args.source == "skeleton" else in_dir / "frames.json"])
   if args.source == "skeleton":
      if not args.skeleton:
         raise ArtToolError("--from skeleton 이면 --skeleton 파일이 있어야 한다")
      data = anchors_mod.from_skeleton_json(prof, read_json(args.skeleton), args.rig)
   else:
      if not args.markers:
         raise ArtToolError("--from marker 이면 --markers 폴더가 있어야 한다")
      index = read_json(in_dir / "frames.json")
      data = anchors_mod.extract(prof, index, args.markers, args.rig, art_dir=in_dir)
   dry_run = is_dry_run(args)
   if not dry_run:
      write_json(out, data)
   return {**dry_run_fields(dry_run, [out]), "out": None if dry_run else str(out), "points": len(data["points"])}


def _check_takes_new_args() -> bool:
   params = inspect.signature(check_mod.run).parameters
   return all(name in params for name in CHECK_NEW_KWARGS)


def _run_check(args) -> dict:
   extra = {}
   if _check_takes_new_args():
      extra = {"warn": not args.no_warn, "mode": args.mode, "template": args.template}
      # 알고 두는 경고 (2판 D). 셋 다 안 주면 키워드를 안 넘겨 보고가 지금과 같다.
      if args.known or args.baseline or args.fail_on_new:
         extra.update(known=args.known, baseline=args.baseline, fail_on_new=args.fail_on_new)
   elif args.no_warn or args.mode != "auto" or args.template:
      raise UsageError("아직 구현 안 됨 : check --no-warn · --mode · --template")
   map_file = getattr(args, "profile_map", None)
   if map_file:
      # 그림마다 프로필 (3판 2-1). 안 주면 키워드를 안 넘겨 보고가 예전과 바이트까지 같다.
      if getattr(args, "profile", None) or getattr(args, "directions", None):
         raise UsageError("--profile-map 은 --profile · --directions 와 같이 못 쓴다 (프로필은 지도가 고른다)")
      pmap = profile_map_mod.load(map_file)
      report = check_mod.run_many(pmap.default, args.in_dir, args.no_ramps, profile_map=pmap, **extra)
   else:
      report = check_mod.run_many(_profile(args), args.in_dir, args.no_ramps, **extra)
   write_json(jailed_output(args.report), report)
   return report


def _run_bake(args) -> dict:
   return bake_mod.bake(_profile(args), args.in_dir, args.out_dir, args.namespace, args.force)


def _run_layers(args) -> dict:
   """`layers compose` 만 여기로 온다. 나머지 하위 명령은 LATE 표로 간다."""
   return layers_mod.compose_sheets(_profile(args), args.rig, args.in_dir, args.out_dir, args.anim)


def _run_split(args) -> dict:
   """두 길이 인자를 나눠 쓴다. 한쪽 인자를 다른 길에 주면 조용히 무시하지 않고 거절한다."""
   if args.list_colors:
      if args.spec or args.rig or args.min_piece is not None or args.gray_levels is not None:
         raise UsageError("--list-colors 는 --spec · --rig · --min-piece · --gray-levels 와 같이 못 쓴다")
      return split_mod.run_list_colors(args.in_file, args.out)
   if not args.spec:
      raise UsageError("--spec 나누기 표가 있어야 한다 (색 목록만 보려면 --list-colors)")
   order, prof_name = None, None
   if args.rig:
      prof = _profile(args)
      order, prof_name = layers_mod.layer_order(prof, args.rig), prof.name
   min_piece = split_mod.DEFAULT_MIN_PIECE if args.min_piece is None else args.min_piece
   gray = None if args.gray_levels is None else split_mod.parse_gray_levels(args.gray_levels)
   return split_mod.run(args.in_file, args.spec, args.out, order, args.rig, prof_name, min_piece, gray)


def _run_recolor(args) -> dict:
   return recolor_mod.run(args.in_dir, args.spec, args.out_dir, args.sheet, args.scale)


def _run_tile(args) -> dict:
   if args.sub == "blob":
      data = blob_mod.build(_profile(args), args.in_dir, args.out_dir)
      return {"out": args.out_dir, "count": data["count"], "tile_size": data["tile_size"]}
   if args.sub == "place":
      return place_mod.place(
         _profile(args), args.tileset, args.rules, args.size, args.out_dir, args.exe, args.seed, args.dry_run
      )
   if args.sub == "preview":
      return preview_mod.run(args.layout, args.in_dir, args.out_file, args.scale, args.dry_run)
   if args.sub == "inspect":
      report = inspect_mod.run(_profile(args), args.in_dir, args.size)
      write_json(jailed_output(args.report), report)
      return report
   if args.sub == "seam":
      report = seam_mod.run(args.in_dir, args.k, args.pairs, args.sheet, args.scale, args.dry_run)
      write_json(jailed_output(args.report), report)
      return report
   out = jailed_output(args.out_file)
   guard_overwrite([out], [args.map_file, args.tileset])     # 입력 JSON 을 덮지 않는다
   map_data, tileset = read_json(args.map_file), read_json(args.tileset)
   if is_dry_run(args):
      ldtk_mod.build_project(map_data, tileset)      # 맵 · 타일셋이 어긋나면 dry-run 에서도 같은 오류를 낸다
      return {**dry_run_fields(True, [out]), "out": None}
   ldtk_mod.write_ldtk(map_data, tileset, out)
   return {"out": str(out)}


def _run_ui(args) -> dict:
   prof = _profile(args)
   table = {
      "frame": _ui_frame,
      "import": _ui_import,
      "icons": _ui_icons,
      "check": _ui_check,
      "bake": _ui_bake,
      "screen": _ui_screen,
      "font": _ui_font,
   }
   return table[args.sub](prof, args)


def _ui_frame(prof, args) -> dict:
   size = place_mod.parse_size(args.size) if args.size else prof.ui_frame_size()
   return ui_frame_mod.build(prof, args.kind, size, args.out_dir)


def _ui_import(prof, args) -> dict:
   return ui_import_mod.import_dir(prof, args.in_dir, args.out_dir)


def _ui_icons(prof, args) -> dict:
   """길이 둘이라 한쪽에서만 쓰는 인자가 있다. 조용히 무시하지 않고 거절한다."""
   if args.fit is not None and args.fit <= 0:
      raise ArtToolError(f"--fit 은 양수여야 한다 : {args.fit}")
   if Path(args.in_file).is_dir():
      if args.cell is not None:
         raise ArtToolError("--cell 은 시트를 자를 때만 쓴다. --in 이 폴더면 낱장 들이기라 쓸 데가 없다")
      return ui_icons_mod.gather(prof, args.in_file, args.out_dir, args.family, args.fit)
   if args.fit is not None:
      raise ArtToolError("--fit 은 낱장 폴더에만 쓴다. --in 이 시트 파일이면 --cell 로 칸 크기를 준다")
   return ui_icons_mod.cut(prof, args.in_file, args.out_dir, args.cell, args.family)


def _ui_check(prof, args) -> dict:
   report = ui_check_mod.run(args.in_dir, prof, args.manifest)
   write_json(jailed_output(args.report), report)
   return report


def _ui_bake(prof, args) -> dict:
   where = args.assets_root or ui_bake_mod.uss.ASSETS_ROOT
   return ui_bake_mod.bake(prof, args.in_dir, args.out_dir, args.namespace, args.force, where)


def _ui_screen(prof, args) -> dict:
   return ui_screen_mod.build(prof, args.spec, args.out_dir, args.manifest, args.assets_root)


def _ui_font(prof, args) -> dict:
   return ui_font_mod.build(prof, args.scan, jailed_output(args.out_file), args.scan_root, args.dry_run)


def _run_provider(args) -> dict:
   if args.sub == "list":
      return {"default": providers.DEFAULT, "providers": providers.describe()}

   spec = read_json(args.spec) if args.spec else {}
   req = providers.ProviderRequest(
      kind=args.kind,
      out_dir=Path(args.out_dir),
      size=tuple(spec.get("size", (64, 64))),
      projection=spec.get("projection", "quarter"),
      directions=int(spec.get("directions", 4)),
      frames=int(spec.get("frames", 1)),
      reference=spec.get("reference"),
      prompt=spec.get("prompt", ""),
      seed=spec.get("seed"),
      dry_run=args.dry_run,
   )
   # 안 준 것(None)만 기본 제공자. 빈 이름 "" 은 그대로 넘겨 「모르는 제공자」 오류가 나게 한다
   name = providers.DEFAULT if args.provider is None else args.provider
   return providers.get(name).make(req).to_json()


def _print_human(data) -> None:
   if isinstance(data, dict) and isinstance(data.get("providers"), list):
      for row in data["providers"]:
         mark = "켜짐" if row["available"] else "꺼짐"
         print(f"{row['name']:<10} {mark:<4} {', '.join(row['capabilities'])}")
      return
   if isinstance(data, dict) and isinstance(data.get("checked"), dict) and data["checked"].get("mode") == "loose":
      print("낱장 모드")
   if isinstance(data, dict) and isinstance(data.get("must_failed"), list) and data["must_failed"]:
      print(f"꼭 지킬 것 어김 {len(data['must_failed'])}건 : {', '.join(map(str, data['must_failed']))}")
   if isinstance(data, dict) and isinstance(data.get("warnings"), list):
      print(f"경고 {len(data['warnings'])}건")
   if isinstance(data, dict) and isinstance(data.get("show_lines"), list):
      for line in data["show_lines"]:
         print(line)
   print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
   _utf8_streams()
   args = build_parser().parse_args(argv)
   try:
      result = run(args)
   except ArtToolError as exc:
      print(f"오류 : {exc}", file=sys.stderr)
      return exc.exit_code
   except Exception as exc:
      # 여기까지 온 것은 우리가 예상 못 한 것이다. 역추적은 ARTTOOL_DEBUG=1 일 때만 보여준다.
      if os.environ.get("ARTTOOL_DEBUG") == "1":
         traceback.print_exc()
      print(f"오류 : {type(exc).__name__} : {exc}", file=sys.stderr)
      return EXIT_ERROR

   if args.as_json:
      print(json.dumps(result, ensure_ascii=False, indent=2))
   else:
      _print_human(result)
   if isinstance(result, dict) and result.get("status") == "fail":
      return EXIT_CHECK_FAIL
   return EXIT_OK


if __name__ == "__main__":
   raise SystemExit(main())
