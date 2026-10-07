"""스킬 예시 스크립트 셋을 실제로 돌려 본다 (2026-10-04 개선 설계 6-4).

`arttool.draw` 이름이 바뀌거나 명령 인자가 바뀌면 스크립트가 낡는다 — 여기서 깨진다.
"""

import subprocess
import sys
from pathlib import Path

import pytest

from arttool.jsonio import read_json

SCRIPTS = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "arttool-usage" / "scripts"


def _run(name: str, out: Path) -> subprocess.CompletedProcess:
   done = subprocess.run(
      [sys.executable, str(SCRIPTS / name), "--out", str(out)],
      capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
   )
   assert done.returncode == 0, f"{name} 종료 {done.returncode}\n{done.stdout}\n{done.stderr}"
   return done


def _check_ok(report: Path) -> None:
   data = read_json(report)
   assert data["status"] == "ok", data
   assert data.get("must_failed") == [], data.get("must_failed")


def test_draw_char_small(tmp_path):
   out = tmp_path / "char"
   _run("draw_char_small.py", out)
   for name in ("guide/template.json", "set/layers.json", "set/body/idle.png", "set/hair/idle.png",
                "flat/idle.png", "preview_x8.png", "sheet.png"):
      assert (out / name).is_file(), name
   _check_ok(out / "check.json")
   assert read_json(out / "layers_check.json")["status"] in ("ok", "warn")


def test_draw_tile(tmp_path):
   out = tmp_path / "tile"
   _run("draw_tile.py", out)
   for name in ("set/layers.json", "tiles/grass.png", "tiles/grass_flower.png", "sheet.png"):
      assert (out / name).is_file(), name
   assert read_json(out / "seam.json")["status"] == "ok"
   assert read_json(out / "layers_check.json")["status"] == "ok"


def test_draw_fx(tmp_path):
   out = tmp_path / "fx"
   _run("draw_fx.py", out)
   frames = sorted((out / "frames").glob("burst_*.png"))
   assert len(frames) == 5
   assert (out / "sheet.png").is_file()
   _check_ok(out / "check.json")
   assert read_json(out / "check.json")["warnings"] == []


def test_draw_char_loop(tmp_path):
   out = tmp_path / "loop"
   done = _run("draw_char_loop.py", out)
   for name in ("loop_1.png", "loop_2.png", "preview_x8.png", "set/layers.json"):
      assert (out / name).is_file(), name
   last = done.stdout.strip().splitlines()[-1]          # 끝 줄 `린트 N 건`
   assert last.startswith("린트 ") and last.endswith(" 건"), last
   assert int(last.split()[1]) >= 0
   assert "얼굴 고친 칸 6 (생각 6)" in done.stdout


@pytest.mark.parametrize("name", ["draw_char_small.py", "draw_tile.py", "draw_fx.py", "draw_char_loop.py"])
def test_script_needs_out(name):
   done = subprocess.run([sys.executable, str(SCRIPTS / name)], capture_output=True, text=True, encoding="utf-8", errors="replace")
   assert done.returncode == 2
