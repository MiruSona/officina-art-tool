"""`check --profile-map` — 그림마다 다른 프로필 맞추기 (3판 설계 2-1).

지도 파일은 믿을 수 없는 입력이다.
- 프로필 경로는 지도 파일 폴더 아래 상대경로만 받는다 (`safe_join`). 링크 · `.yaml/.yml` 아닌 것은 거절.
- 무늬는 글롭(`fnmatchcase`)만 쓴다. 정규식은 안 쓴다.
- 모르는 칸은 거절하고, 줄 수와 파일 크기에 상한을 둔다.
겹치는 차례 : 기본(`default`) → 줄의 `profile` → 줄의 `set` → (check 가 나중에) 템플릿.
"""

from __future__ import annotations

import copy
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from .errors import ArtToolError, UsageError
from .profile import Profile, apply_table_mode, deep_merge, load_profile, reject_unknown, validate
from .paths import safe_join

MAP_KEYS = ("version", "default", "rules")
RULE_KEYS = ("match", "profile", "set")
MAX_RULES = 256                 # 줄 수 상한 — 그림마다 줄을 다 훑으니 여기서 막는다
MAX_BYTES = 256 * 1024          # 지도 파일 크기 상한
MAX_PATTERN = 256               # 무늬 한 줄 길이 상한
PROFILE_SUFFIXES = (".yaml", ".yml")
DEFAULT_LABEL = "default"


class ProfileMap:
   """읽고 검증한 지도 한 벌. 프로필은 경로마다 한 번만 읽어 `profiles` 에 둔다."""

   def __init__(self, path: Path, default: Profile, default_rel: str, rules: list[dict]):
      self.path = path
      self.default = default
      self.default_rel = default_rel
      self.rules = rules          # [{"match": str, "profile": Profile, "label": str}]

   def pick(self, rel: str) -> tuple[str, Profile, str]:
      """그림 하나의 (줄 열쇠, 프로필, 딱지). 위에서부터 첫 일치 하나만 쓴다. 안 맞으면 default."""
      for i, rule in enumerate(self.rules):
         if glob_match(rule["match"], rel):
            return str(i), rule["profile"], rule["label"]
      return DEFAULT_LABEL, self.default, f"{DEFAULT_LABEL} · {self.default_rel}"


def glob_match(pattern: str, rel: str) -> bool:
   """`/` 단위 글롭. `*` 는 한 단 안에서만, `**` 는 여러 단(0단 포함). 대소문자는 접어서 본다."""
   pat = [p for p in pattern.replace("\\", "/").casefold().split("/") if p != ""]
   parts = [p for p in rel.replace("\\", "/").casefold().split("/") if p != ""]
   # 메모 표로 푼다 — 같은 (무늬 칸, 경로 칸) 을 두 번 안 본다. `**` 가 여럿이어도 O(무늬 × 경로).
   seen: dict[tuple[int, int], bool] = {}

   def go(i: int, j: int) -> bool:
      key = (i, j)
      if key in seen:
         return seen[key]
      if i == len(pat):
         ok = j == len(parts)
      elif pat[i] == "**":
         ok = go(i + 1, j) or (j < len(parts) and go(i, j + 1))
      else:
         ok = j < len(parts) and fnmatchcase(parts[j], pat[i]) and go(i + 1, j + 1)
      seen[key] = ok
      return ok

   return go(0, 0)


def load(path: str | Path) -> ProfileMap:
   """지도 파일을 읽고 검증한다. 틀리면 `UsageError`(종료 코드 2)."""
   source = Path(path)
   try:
      if source.is_symlink() or not source.is_file():
         raise UsageError(f"지도 파일이 없거나 보통 파일이 아니다 : {source}")
      if source.stat().st_size > MAX_BYTES:
         raise UsageError(f"지도 파일이 너무 크다 (상한 {MAX_BYTES} 바이트) : {source}")
      raw = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
   except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError) as exc:   # 깊은 중첩은 RecursionError 로 온다
      raise UsageError(f"지도 파일을 못 읽는다 : {source} ({exc})") from exc
   where = f"지도 {source.name}"
   if not isinstance(raw, dict):
      raise UsageError(f"{where} : 맨 위가 표(dict)가 아니다")
   _only_keys(raw, MAP_KEYS, where)
   if raw.get("version", 1) != 1:
      raise UsageError(f"{where} : version 은 1 만 안다 : {raw.get('version')!r}")
   if not isinstance(raw.get("default"), str) or not raw["default"]:
      raise UsageError(f"{where} : default 프로필 경로가 꼭 있어야 한다")
   rules_raw = raw.get("rules") or []
   if not isinstance(rules_raw, list):
      raise UsageError(f"{where} : rules 는 목록이어야 한다")
   if len(rules_raw) > MAX_RULES:
      raise UsageError(f"{where} : rules 가 너무 많다 ({len(rules_raw)} > {MAX_RULES})")

   root = source.resolve().parent
   cache: dict[Path, Profile] = {}       # 같은 프로필 파일은 한 번만 읽는다
   default = _profile_at(root, raw["default"], cache, f"{where} default")
   rules = []
   for i, rule in enumerate(rules_raw):
      rule_where = f"{where} rules[{i}]"
      if not isinstance(rule, dict):
         raise UsageError(f"{rule_where} : 표(dict)가 아니다")
      _only_keys(rule, RULE_KEYS, rule_where)
      match = rule.get("match")
      if not isinstance(match, str) or not match or len(match) > MAX_PATTERN:
         raise UsageError(f"{rule_where} : match 는 비지 않은 글자({MAX_PATTERN}자 안)여야 한다")
      if "profile" not in rule and "set" not in rule:
         raise UsageError(f"{rule_where} : profile 이나 set 중 하나는 있어야 한다")
      base, label = default, raw["default"]
      if "profile" in rule:
         if not isinstance(rule["profile"], str) or not rule["profile"]:
            raise UsageError(f"{rule_where} : profile 은 경로 글자여야 한다")
         base, label = _profile_at(root, rule["profile"], cache, rule_where), rule["profile"]
      prof = base
      if "set" in rule:
         prof = _overlay(base, rule["set"], rule_where)
         label = f"{label} + set"
      # 램프 파일 경로를 미리 풀어 본다 — 감옥 밖이면 검사 도중이 아니라 여기서 종료 2 로 막는다.
      try:
         prof.ramps_path()
      except ArtToolError as exc:
         raise UsageError(f"{rule_where} : 램프 파일 경로를 못 쓴다 ({exc})") from exc
      rules.append({"match": match, "profile": prof, "label": f"rule {i} · {label}"})
   return ProfileMap(source, default, raw["default"], rules)


def _only_keys(node: dict, allowed: tuple[str, ...], where: str) -> None:
   unknown = [str(k) for k in node if k not in allowed]
   if unknown:
      raise UsageError(f"{where} : 모르는 칸 {', '.join(sorted(unknown))} (아는 칸 : {', '.join(allowed)})")


def _profile_at(root: Path, rel: str, cache: dict[Path, Profile], where: str) -> Profile:
   """지도 폴더 감옥 안의 프로필 파일 하나를 읽는다. 읽은 것은 `cache` 에 둔다."""
   try:
      target = safe_join(root, rel)
   except ArtToolError as exc:
      raise UsageError(f"{where} : 프로필 경로가 지도 폴더 밖이다 : {rel} ({exc})") from exc
   if target.suffix.lower() not in PROFILE_SUFFIXES:
      raise UsageError(f"{where} : 프로필은 .yaml/.yml 만 받는다 : {rel}")
   if target.is_symlink() or not target.is_file():
      raise UsageError(f"{where} : 프로필 파일이 없거나 링크다 : {rel}")
   key = target.resolve()
   if key not in cache:
      try:
         cache[key] = load_profile(str(key))
      except ArtToolError as exc:
         raise UsageError(f"{where} : 프로필을 못 읽는다 : {rel} ({exc})") from exc
   return cache[key]


def _overlay(base: Profile, layer, where: str) -> Profile:
   """`set` 덧칸을 프로필 위에 겹친다. 프로필 파일과 같은 모르는 칸 거절 · 검증을 지난다."""
   if not isinstance(layer, dict):
      raise UsageError(f"{where} : set 은 표(dict)여야 한다")
   layer = copy.deepcopy(layer)
   try:
      reject_unknown(layer, where)
      merged = deep_merge(base.data, layer)
      cap_left = apply_table_mode(merged, layer, base.data, base.cap_left, where)
      validate(merged)
   except ArtToolError as exc:
      raise UsageError(f"{where} : set 이 프로필 꼴에 안 맞는다 : {exc}") from exc
   return Profile(merged, base.source, cap_left)
