---
name: arttool-usage
description: Use when making pixel art (dot) for a game — before drawing with PIL, before calling PixelLab MCP tools, or right after receiving generated images — 도트 그림을 그리거나 뽑기 직전 · PixelLab 을 부르기 직전 · 받은 그림을 손질 · 검사할 때 ArtTool 로 밑판 · 손질 · 검사 · 비교판을 쓰는 법.
---

# 도트 그림은 ArtTool 과 같이 만든다

그림을 얻는 길은 둘이다. **PixelLab(MCP 도구)으로 뽑기**와 **PIL(`arttool.draw`)로 직접 그리기**.
어느 길이든 앞뒤는 같다 — 그리기 전에 **밑판(템플릿)**, 그린 뒤에 **손질 · 검사 · 비교판**.

| 더 볼 것 | 언제 |
| --- | --- |
| `기준.md` | 「좋은 도트」 기준 · 검사 일곱이 무엇을 보나 · 색 수 · 외곽선 · 램프 · 프레임 |
| `뽑기-pixellab.md` | PixelLab 으로 뽑을 때 — 도구 고르기 · 흔한 사고 · 겹 떼기 |
| `그리기-pil.md` | PIL 로 그릴 때 — `arttool.draw` 표 · 겹별로 그리는 순서 · 예시 스크립트 셋 |
| `<ArtTool>/README.md` | 명령 전체 · 프로필 칸 · 보고 꼴 |
| `<ArtTool>/Docs/Guide/AI-그래픽-캐릭터-배경-가이드.html` | 사람이 보는 그림 안내 (예전 것) |

`<ArtTool>` 은 ArtTool 폴더다 (서브모듈이면 보통 `Tools/ArtTool`). 처음이면 그 폴더에서 `setup.ps1` 을 한 번 돌린다.
아래 `arttool …` 은 `<ArtTool>\.venv\Scripts\arttool …` 로 친다.

## 어느 길을 고르나

| 그림 | 길 | 까닭 |
| --- | --- | --- |
| 28~64px 평평한 아이콘 · 타일 · 단순 설비 · 도형 이펙트 | **PIL** | 색 · 크기가 정확하고, 값 하나 고쳐 다시 뽑는다. 공짜 · 빠름 (실측 아이콘 6장 PIL 3분 vs AI 11분) |
| 캐릭터 · 표정 · 질감 · 큰 그림 · 배경 | **PixelLab** | 좌표를 손으로 찍어서는 못 만든다 |
| 섞어서 | 둘 다 | AI 로 큰 덩어리, PIL 로 점 몇 개(볼 · 반짝이) · 이음 손질 |

## 흐름 한눈에

| # | 단계 | PIL 길 | PixelLab 길 |
| --- | --- | --- | --- |
| 0 | 화풍 정하기 (게임에 한 번) | `style extract --by-folder` 로 기준 그림을 **종류별로** 재서 팔레트 · 외곽선 방식을 뽑아 프로필에 붙인다 | 같다 |
| 1 | 템플릿 고르기 | `template list` → `template show <이름> --size WxH --profile P` | 같다 + 결과의 `prompt` 문장을 쓴다 |
| 2 | 밑판 깔기 | `template render <이름> --size N --profile P --out work/guide` | 같다. 마스크 · 프레임 밑그림을 참고 그림으로 |
| 3 | 그리기 · 뽑기 | `arttool.draw.Canvas(template=work/guide)` 로 **겹별로** 그려 `save` | 기본체 1장 → 마스크로 inpaint → `layers diff` 로 겹 떼기 |
| 4 | 받은 그림 손질 | 보통 없음 | `arttool intake --in raw --out clean --sheet s.png` 한 줄 |
| 5 | 겹 보기 · 검사 | `layers view --each` · `layers check --template` | 같다 |
| 6 | 검사 | `check --in <폴더> --template work/guide/template.json --report c.json` | 같다 |
| 7 | 사람 눈 | `sheet --kinds zoom,silhouette,colors4,blur --label` 을 **열어서 본다** | 같다 |
| 8 | 게임에 넣기 | `layers export --flat`(한 장) 또는 `--each --trim-common`(겹별) | 같다 |

**보고 읽는 법** — 모든 명령이 JSON 보고를 낸다.
`status` 가 `fail`(종료 4)이면 고친다. `warnings` 는 고칠 후보다(`bake` 를 안 막는다).
**`must_failed` 가 비어 있지 않으면 템플릿의 최소 규칙(크기 · 반투명 · 배율 · 팔레트)을 어긴 것이라 꼭 고친다.**

## 명령 한 줄 표

| 하고 싶은 것 | 명령 |
| --- | --- |
| 템플릿 목록 (15개) | `arttool template list [--kind effect]` |
| 값 · 프롬프트 · 순서 보기 | `arttool template show char_small --size 48x64 --profile P` |
| 밑판 · 마스크 · 프레임 밑그림 | `arttool template render char_small --size 48x64 --out work/guide` |
| 있는 그림 위에 밑판 얹어 보기 | `arttool template render char_small --size 48x64 --over a.png --out work/over` (크기가 달라도 아래 가운데 맞춤) |
| 동작 · 램프 템플릿 | `template render cycle_char --size 32 --preset walk …` · `template render palette_ramp --size 16 --base #6FA85A --material stone …` |
| 건물 · 큰 물건 · 화면 조각 · 말풍선 | `template render building --size 92x77 …` · `machine` · `screen_piece` · `template render ui9_panel --size 54x34 --preset bubble …` |
| 기준 그림 → 화풍 조각 (종류별) | `arttool style extract --in refs/ --out style/ --name mygame --by-folder` (`refs/char/` · `refs/tile/` … 하위 폴더 = 종류) |
| 받은 그림 한 번에 손질 | `arttool intake --in raw/ --out clean/ [--key edge\|corner\|#hex] [--tol N] [--shave N] [--pad N] [--template t.json] --sheet s.png --report i.json` (배경 그림은 바탕 지우기를 건너뛴다) |
| 배경만 지우기 / 여백만 걷기 | `arttool cutout --in raw --out cut --key corner --tol 10 --shave 2` · `arttool trim --in raw --out t --pad 1 [--common]` |
| 검사 | `arttool check --in clean --template work/guide/template.json --report c.json [--no-warn]` |
| 비교판 | `arttool sheet --in a.png clean/ --kinds zoom,silhouette,colors4,blur --label --out s.png` |
| 기본체 + inpaint → 겹 | `arttool layers diff --base base.png --in inpainted/ --out set/ --template t.json --carve report` |
| 「이 색 칸만」 마스크 | `arttool layers mask --in base.png --colors #2B2233 --grow 1 --out m.png` |
| 겹 켜고 끄며 보기 | `arttool layers view --in set --each --scale 8 --out v.png` |
| 겹 검사 · 내보내기 | `arttool layers check --in set --template t.json` · `arttool layers export --in set --out unity --flat` |
| 타일 이음매 | `arttool tile seam --in tiles --pairs --report seam.json` |
| 프로필 값 보기 | `arttool --profile P profile show` |

## 꼭 지킬 것

- **비교판 PNG 는 직접 열어서 본다.** 검사가 `ok` 여도 실루엣 · 4색 판에서 무엇인지 안 읽히면 다시 그린다.
- **원본은 안 고친다.** 손질 · 겹 명령은 모두 `--out` 새 폴더에 쓴다. 받은 그림은 `raw/` 에 그대로 둔다.
  쓸 자리가 읽은 그림과 겹치면 명령이 아무것도 안 쓰고 종료 2 로 멈춘다 — 다른 폴더를 준다.
- **캐릭터 크기 · 비율** : 기본 본보기는 48×64 `sd`(약 2등신 · 큰 머리). `char_small` 은 64 미만이면 sd, 64 는 `tall`(4등신)이 기본이다 — 다른 비율은 `--preset sd|chibi|tall`.
- `template render` 로 만든 `work/guide` 폴더는 커밋하지 않는다(이 PC 의 절대 경로가 박힌다).
- 숫자 문턱의 정본은 프로필 · 템플릿 파일이다. 이 스킬에 적힌 숫자는 「왜 그 값인가」를 위한 것 — 실제 값은 `profile show` · `template show` 로 본다.
- 한 화면에 도트 굵기는 하나다. 키우거나 줄인 그림을 섞지 않는다 (`check` 의 `integer_scale` 이 잡는다).
