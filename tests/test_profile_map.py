"""`check --profile-map` — 그림마다 다른 프로필 (3판 설계 2-1 · 시험 목록 1~4)."""

from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from arttool import check as check_mod
from arttool import profile_map as pm
from arttool.cli import main
from arttool.errors import UsageError


def _png(path, colors: int, alpha: int = 255):
   """가로로 색 `colors` 개를 칠한 그림. alpha 를 낮추면 반투명 칸이 생긴다."""
   arr = np.zeros((8, max(colors, 1) * 2, 4), np.uint8)
   for i in range(colors):
      arr[:, i * 2:i * 2 + 2] = (20 + i * 9, 40, 200 - i * 7, alpha)
   path.parent.mkdir(parents=True, exist_ok=True)
   Image.fromarray(arr, "RGBA").save(path)


def _setup(tmp_path, map_text: str):
   (tmp_path / "profiles").mkdir()
   (tmp_path / "profiles" / "base.yaml").write_text("name: base\ncheck:\n  max_colors: 4\n", encoding="utf-8")
   (tmp_path / "profiles" / "body.yaml").write_text("name: body\ncheck:\n  max_colors: 10\n", encoding="utf-8")
   map_file = tmp_path / "map.yaml"
   map_file.write_text(map_text, encoding="utf-8")
   art = tmp_path / "art"
   _png(art / "head.png", 3)
   _png(art / "Body.png", 8)
   return map_file, art


MAP = """version: 1
default: profiles/base.yaml
rules:
  - match: "body*"
    profile: profiles/body.yaml
  - match: "*.png"
    set: { check: { max_colors: 2 } }
"""


def test_glob_match():
   assert pm.glob_match("chars/*/head*.png", "chars/hero/head_a.png")
   assert not pm.glob_match("chars/*.png", "chars/hero/head.png")      # * 는 한 단
   assert pm.glob_match("chars/**", "chars/hero/x/head.png")
   assert pm.glob_match("**/x.png", "x.png")                            # ** 는 0단도
   assert pm.glob_match("HEAD.PNG", "head.png")                         # 대소문자 접기
   assert not pm.glob_match("a[", "a")                                  # 정규식 아님 — 깨진 무늬도 그냥 안 맞는다


def test_first_match_and_one_read(tmp_path, monkeypatch):
   map_file, art = _setup(tmp_path, MAP + "  - match: \"x*\"\n    profile: profiles/body.yaml\n")
   calls = []
   real = pm.load_profile
   monkeypatch.setattr(pm, "load_profile", lambda p: calls.append(p) or real(p))
   pmap = pm.load(map_file)
   assert len(calls) == 2                                               # body.yaml 두 줄이어도 한 번만 읽는다
   assert pmap.pick("body.png")[0] == "0"                               # 첫 일치 (대소문자 접기)
   assert pmap.pick("head.png")[0] == "1"
   assert pmap.pick("head.txt")[0] == "default"


def test_report_profile_per_image(tmp_path):
   map_file, art = _setup(tmp_path, MAP)
   report = check_mod.run(None, art, profile_map=pm.load(map_file))
   assert report["profile_map"]["hits"] == {"0": 1, "1": 1}
   assert report["profile_map"]["files"]["Body.png"].startswith("rule 0 · profiles/body.yaml")
   # 머리 3색은 set 한도 2 에 걸리고, 몸 8색은 body 한도 10 을 지난다
   assert report["status"] == "fail"
   bad = [line for line in report["rules"] if not line["ok"]]
   assert bad and all(line["profile"].startswith("rule 1") for line in bad)


def test_without_map_report_unchanged(tmp_path):
   _, art = _setup(tmp_path, MAP)
   prof = pm.load_profile(str(tmp_path / "profiles" / "body.yaml"))
   before = check_mod.run(prof, art)
   assert "profile_map" not in before
   assert all("profile" not in line for line in before["rules"])
   assert json.dumps(before, sort_keys=True) == json.dumps(check_mod.run_many(prof, [art]), sort_keys=True)


def test_rule_unused_warning(tmp_path):
   map_file, art = _setup(tmp_path, "version: 1\ndefault: profiles/body.yaml\nrules:\n  - match: \"nope*\"\n    set: {}\n")
   report = check_mod.run(None, art, profile_map=pm.load(map_file))
   assert any(w["rule"] == check_mod.MAP_UNUSED for w in report["warnings"])
   assert report["status"] == "ok"                                      # 경고는 status 를 안 바꾼다


@pytest.mark.parametrize("text", [
   "rules: []\n",                                                        # default 없음
   "default: ../out.yaml\n",                                             # 감옥 밖
   "default: profiles/base.yaml\nextra: 1\n",                            # 모르는 칸
   "default: profiles/base.yaml\nrules:\n  - match: a\n    set: { check: { max_colour: 2 } }\n",   # set 오타
   "default: profiles/base.yaml\nrules:\n  - match: a\n    profile: profiles/base.txt\n",
   "default: profiles/base.yaml\nrules:\n  - match: a\n    regex: b\n    set: {}\n",
])
def test_bad_map_is_usage_error(tmp_path, text):
   map_file, _ = _setup(tmp_path, text)
   with pytest.raises(UsageError):
      pm.load(map_file)


def test_too_many_rules(tmp_path):
   rows = "".join(f"  - match: a{i}\n    set: {{}}\n" for i in range(pm.MAX_RULES + 1))
   map_file, _ = _setup(tmp_path, "default: profiles/base.yaml\nrules:\n" + rows)
   with pytest.raises(UsageError):
      pm.load(map_file)


def test_cli(tmp_path):
   map_file, art = _setup(tmp_path, MAP)
   out = tmp_path / "r.json"
   assert main(["check", "--profile-map", str(map_file), "--in", str(art), "--report", str(out)]) == 4
   assert json.loads(out.read_text(encoding="utf-8"))["profile_map"]["rules"] == 2
   # --profile 과 같이 → 2 · 지도 파일에 보고를 덮어쓰기 → 2
   assert main(["--profile", "x", "check", "--profile-map", str(map_file), "--in", str(art), "--report", str(out)]) == 2
   assert main(["check", "--profile-map", str(map_file), "--in", str(art), "--report", str(map_file)]) == 2
   assert "rules" in map_file.read_text(encoding="utf-8")               # 지도는 그대로


def test_cli_many_inputs_and_template_free(tmp_path):
   map_file, art = _setup(tmp_path, MAP)
   art2 = tmp_path / "art2"
   _png(art2 / "body_b.png", 5)
   out = tmp_path / "r.json"
   main(["check", "--profile-map", str(map_file), "--in", str(art), str(art2), "--report", str(out)])
   report = json.loads(out.read_text(encoding="utf-8"))
   assert report["checked"]["inputs"] == 2
   # 합친 보고에도 맨 위 profile_map — hits 는 입력 전체 합, files 열쇠는 <딱지>/<상대경로>
   block = report["profile_map"]
   assert block["hits"] == {"0": 2, "1": 1}
   assert set(block["files"]) == {"art/head.png", "art/Body.png", "art2/body_b.png"}


FOLDER_MAP = """version: 1
default: profiles/base.yaml
rules:
  - match: "enemy/**"
    profile: profiles/body.yaml
  - match: "ui/*.png"
    set: { check: { max_colors: 2 } }
  - match: "nope/**"
    set: {}
"""


def test_folder_patterns_walk_subfolders(tmp_path):
   """지도를 주면 하위 폴더까지 훑고, 무늬는 --in 기준 상대경로(`/`)에 맞춘다."""
   map_file, _ = _setup(tmp_path, FOLDER_MAP)
   art = tmp_path / "deep"
   _png(art / "Enemy" / "a.png", 3)
   _png(art / "ui" / "b.png", 3)
   _png(art / "c.png", 3)
   report = check_mod.run(None, art, profile_map=pm.load(map_file))
   files = report["profile_map"]["files"]
   assert set(files) == {"Enemy/a.png", "ui/b.png", "c.png"}
   assert files["Enemy/a.png"].startswith("rule 0")
   assert files["ui/b.png"].startswith("rule 1")
   assert files["c.png"].startswith("default")
   # 안 맞은 줄 하나(2번) → info rule_idle, 경고 rule_unused 는 없다
   idle = [i for i in report.get("info", []) if i["rule"] == check_mod.MAP_IDLE]
   assert len(idle) == 1 and "rules[2]" in idle[0]["detail"] and "nope/**" in idle[0]["detail"]
   assert not any(w["rule"] == check_mod.MAP_UNUSED for w in report["warnings"])


def test_many_inputs_rule_unused_judged_once(tmp_path):
   """입력 여럿 : 한 입력에서만 안 맞아도 다른 입력에서 맞았으면 rule_unused 를 안 낸다. 모두 안 맞으면 한 번만."""
   map_file, art = _setup(tmp_path, "version: 1\ndefault: profiles/body.yaml\nrules:\n  - match: \"head*\"\n    set: {}\n")
   art2 = tmp_path / "art2"
   _png(art2 / "zzz.png", 3)
   pmap = pm.load(map_file)
   report = check_mod.run_many(None, [art, art2], profile_map=pmap)
   assert not any(w["rule"] == check_mod.MAP_UNUSED for w in report["warnings"])
   assert not any(i["rule"] == check_mod.MAP_IDLE for i in report.get("info", []))
   (tmp_path / "art3").mkdir()
   _png(tmp_path / "art3" / "q.png", 3)
   both = check_mod.run_many(None, [art2, tmp_path / "art3"], profile_map=pmap)
   assert len([w for w in both["warnings"] if w["rule"] == check_mod.MAP_UNUSED]) == 1
   assert len([i for i in both["info"] if i["rule"] == check_mod.MAP_IDLE]) == 1


def test_deep_nesting_is_usage_error(tmp_path):
   map_file, _ = _setup(tmp_path, "default: profiles/base.yaml\nx: " + "[" * 5000 + "]" * 5000 + "\n")
   with pytest.raises(UsageError):
      pm.load(map_file)


def test_set_ramps_outside_jail_is_usage_error(tmp_path):
   map_file, _ = _setup(tmp_path, "default: profiles/base.yaml\nrules:\n  - match: a\n"
                                  "    set: { palette: { ramps_file: ../../../outside.json } }\n")
   with pytest.raises(UsageError, match=r"rules\[0\]"):
      pm.load(map_file)
