"""템플릿 — 그리기 전에 깔아 두는 밑판 (2026-10-04 개선 설계 8절 · 9-4 · 10-3).

한 템플릿 = 값(JSON) + 가이드 PNG + 프롬프트 문장 + 그리는 순서.

- `schema` : 템플릿 JSON 찾기 · 읽기 · 검증 · 프리셋 고르기 · 크기 고르기
- `kinds`  : kind 별 처리기. 셈 · 가이드 모양 · 프레임 · 마스크 (숫자는 JSON, 그리는 법은 여기)
- `guide`  : 가이드 겹 칠하기 · 미리보기 · 견본 띠 · `--over` 확대판
- `run`    : `template list · show · render` 명령 (`run.run(args)`)

템플릿 파일은 `tool_home()/templates/<이름>.json` 에서 찾는다(프로필 · 팔레트와 같은 자리 규칙).
경로를 주면 그 파일을 읽는다 — 게임 저장소가 자기 템플릿을 둘 수 있다.
"""

from ..errors import ArtToolError


class TemplateError(ArtToolError):
   """템플릿 파일이 잘못됐다(종료 1). 잘못된 CLI 인자는 UsageError(종료 2)로 따로 낸다."""
