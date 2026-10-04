"""휠 설치 꾸림새 (pyproject) 지킴 시험. 실제 휠 빌드는 네트워크 · setuptools 가 있어야 해서 여기선 목록만 맞춘다."""

import tomllib
from pathlib import Path

from arttool import profile

ROOT = Path(__file__).resolve().parents[1]


def _setuptools() -> dict:
   return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]


def test_every_subpackage_is_listed():
   """packages 를 손으로 적으니 하위 꾸러미를 새로 만들고 빠뜨리면 휠에서 빠진다."""
   found = {".".join(p.parent.relative_to(ROOT / "src").parts) for p in (ROOT / "src").rglob("__init__.py")}
   listed = {name for name in _setuptools()["packages"] if not name.startswith("arttool._home")}
   assert found == listed


def test_home_copy_maps_every_data_folder():
   """profiles/ · palettes/ · templates/ 와 그 아래 폴더가 모두 arttool/_home 사본으로 들어간다."""
   dirs = _setuptools()["package-dir"]
   want = set()
   for top in ("profiles", "palettes", "templates"):
      for folder in [ROOT / top, *[p for p in (ROOT / top).rglob("*") if p.is_dir() and p.name != "__pycache__"]]:
         want.add(folder.relative_to(ROOT).as_posix())
   assert {v for k, v in dirs.items() if k.startswith(f"arttool.{profile.HOME_COPY}.")} == want


def test_tool_home_prefers_source_folder(monkeypatch):
   monkeypatch.delenv("ARTTOOL_HOME", raising=False)
   assert profile.tool_home() == ROOT
