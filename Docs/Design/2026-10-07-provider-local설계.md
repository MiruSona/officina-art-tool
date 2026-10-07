# provider local 설계 — ComfyUI 로 로컬 그림 모델 부르기 (2026-10-07)

**`local` 제공자가 ComfyUI API 를 직접 부르게 한다. 1차는 「새 그림(소품 · 건물 · 이펙트)」과 「inpaint」 두 가지만. 제공자는 늘 「요청한 크기」의 PNG 를 돌려준다(512px 날것도 같이 남긴다). inpaint 의 「마스크 밖 0픽셀」은 제공자가 코드로 보장한다. 색 줄이기 · 바탕 지우기 · 검사는 기존 명령(`cutout` · `merge-colors` · `check`)으로 잇는다. 워크플로 JSON 은 기본 본보기를 툴에 넣되 모델 파일 이름은 코드 · 본보기 어디에도 안 박고 사용자 설정에서 받는다. 새 의존성 없음(표준 라이브러리 `urllib`).**

앞 문서 : `Docs/Research/2026-10-07-PixelLab로컬대체조사.md` · `2026-10-07-로컬그림모델실측1단계.md` · `2026-10-07-로컬그림모델실측2단계.md`. 진행상황 「로컬 그림 모델」 절의 「못 정한 것」 셋(범위 · 후처리 자리 · 워크플로 JSON)에 답한다.
실측 : `Docs/Research/2026-10-07-provider-local실측.md` (10-07, 본보기 그대로 돌았다 · BOX 유지)
지킨 결정 : mem `20261007-f1618254` — 제공자는 ComfyUI 주소 하나만 받는 범용 꼴, 미니PC 주소 · 경로 · 컨테이너 사정은 git 밖 local 문서에만.

## 왜 하나

- 실측 1 · 2단계로 「소품 · 건물 · 이펙트 · inpaint 는 로컬로 넘길 수 있다」가 나왔다. 그런데 지금은 실측용 Python 스크립트를 손으로 돌리고, 결과를 손으로 `cutout` · `merge-colors` 에 넣는다.
- `local` 제공자는 뼈대(38줄)뿐이다. 요청 JSON 만 쓰고 실제 호출은 「아직 안 붙였다」로 멈춘다.
- PixelLab 크레딧을 덜 쓰려면 에이전트가 `provider make --provider local` 한 줄로 그림을 얻어야 한다.

## 범위

| 안 (1차) | 밖 (2차 이후) |
| --- | --- |
| ① 새 그림 `kind=prop` (klein 4B fp8 + LoRA 기본 본보기) ② inpaint `kind=inpaint` (klein 기본 본보기) ③ ComfyUI 클라이언트(올리기 · 줄 세우기 · 기다리기 · 받기) ④ 워크플로 자리표시 채우기 ⑤ BOX 축소 · inpaint 합성 · 마스크 안 색 맞추기 ⑥ `--dry-run` ⑦ 가짜 ComfyUI 서버 시험 | 자세 편집(Qwen-Edit 4방향 후보) · idle 애니(Wan 2.2) · Qwen-Edit 기본 본보기 · Z-Image 기본 본보기 · 24px 아이콘 · 48px 타일(⑤ 미해결) · LLM 서버 끄고 켜기 · websocket 진행률 · PixelLab 실제 호출 |

**왜 이렇게 좁히나** : 1 · 2 는 둘 다 「그림 한 장 → 그림 한 장」이라 지금 `ProviderRequest` / `ProviderResult` 꼴에 그대로 들어간다. 자세는 「4방향 후보 + 손질」이라 결과를 고르는 흐름이 따로 필요하고, 애니는 「프레임 묶음 + 재양자화 · 격자 스냅」 후처리가 아직 실측 안 됐다(남은 것 ⑧). 둘을 1차에 넣으면 계약을 두 번 고치게 된다.
단 제공자는 워크플로를 가리지 않으므로, 사용자가 Qwen-Edit inpaint 워크플로를 `--workflow` 로 꽂으면 1차에서도 돈다(C 절). 2차는 「기본 본보기를 더 넣고 프레임 · 후보 결과 꼴을 넓히는 일」이다.

## 1. 흐름 한눈에

| 단계 | prop (새 그림) | inpaint | 누가 |
| --- | --- | --- | --- |
| 1 입력 준비 | — | 원본(요청 크기, 예 64px) · 마스크(같은 크기, 흰 칸 = 고칠 곳)를 NEAREST 로 작업 크기(512)까지 키움 | 제공자 |
| 2 워크플로 채우기 | 본보기/사용자 JSON 의 `$prompt` · `$seed` · `$width` … 자리를 값으로 바꿈 | 같음 + `$image` · `$mask` | 제공자 |
| 3 ComfyUI 호출 | 상태 확인 → 그림 올리기 → 줄 세우기 → 기다리기 → 받기 | 같음 | 제공자 |
| 4 날것 남기기 | `raw/<이름>_512.png` | 같음 | 제공자 |
| 5 축소 | BOX 로 요청 크기까지 | 같음 | 제공자 |
| 6 색 맞추기 | — | 마스크 안 칸만 「원본 색 + `extra_colors`」 중 가장 가까운 색으로 | 제공자 |
| 7 합성 | — | 마스크 밖 = 원본 그대로 덮어쓰기. 밖 바뀐 칸 수를 세어 `meta.outside_changed`(늘 0) | 제공자 |
| 8 바탕 지우기 | `cutout --key corner` | (원본이 이미 투명이라 보통 안 함) | 기존 명령 |
| 9 색 줄이기 | `merge-colors --max-colors 16`(또는 `--palette`) | (6 에서 끝남) | 기존 명령 |
| 10 검사 | `check` | `check` · `layers diff --template`(밖 바뀐 칸 다시 세기) | 기존 명령 |

8~10 은 스킬 문서에 「뽑은 뒤 차례」로 적는다. `intake`(cutout → trim → check) 를 써도 된다 — 단 `merge-colors` 를 그 사이에 넣어야 한다.

## 2. 후처리 자리 (B)

| 후처리 | 자리 | 까닭 |
| --- | --- | --- |
| BOX 축소 | **제공자 안** | 제공자 계약이 「요청 크기 그림」이다(`code` 도 `req.size` 로 자른다). 그리고 ArtTool 에 축소 명령이 없다 — 새 명령을 만들 만큼 쓸 데가 없다. 512 날것은 `raw/` 에 남겨 다른 축소를 해 보고 싶으면 손으로 하게 한다 |
| inpaint 합성 (밖 0픽셀) | **제공자 안, 요청 크기에서 맨 끝** | 「밖은 안 바뀐다」는 inpaint 라는 말의 뜻 자체라 결과 계약에 속한다. 워크플로 안 `ImageCompositeMasked` 는 512 에서만 0 을 보장하고, 축소 · 색 맞추기를 거치면 다시 깨질 수 있다. 그래서 **마지막 단계를 요청 크기에서 코드로** 둔다. 워크플로 쪽 합성 노드는 있어도 되고 없어도 된다 |
| inpaint 마스크 안 색 맞추기 | **제공자 안** | 합성 뒤에 `merge-colors` 를 돌리면 표가 그림 전체로 짜여 **밖 색까지 합쳐진다**. 안쪽만 원본 색에 맞추면 밖 0 과 색 수가 둘 다 지켜진다. 새 색(예 원본에 없는 초록 빛)이 필요하면 spec `extra_colors` 로 더한다 |
| 바탕 지우기 | 기존 `cutout` | 이미 있다. 모델이 흰 바탕을 낼 때만 필요하고 판단(`--key` · `--tol`)이 그림마다 다르다 |
| 새 그림 색 줄이기 | 기존 `merge-colors` | 이미 있다. `--palette`(프로필 램프) · `--keep` · `--max-colors` 고르는 게 그림마다 다르다 |
| 검사 | 기존 `check` | 이미 있다. 제공자는 그림을 만드는 자리만 맡는다(`base.py` 머리글) |

정리 : **「모델 출력 → 요청 크기 그림」까지가 제공자, 「그림 → 게임에 넣을 그림」은 명령 사슬.** inpaint 만 「밖 0」이 계약이라 색 맞추기까지 제공자가 한다.

## 3. 워크플로 JSON (C)

| 무엇 | 정한 것 |
| --- | --- |
| 꼴 | ComfyUI **API 꼴**(노드 id → `class_type` · `inputs`). 화면 저장 꼴(`nodes`/`links`)은 거절하고 「API 꼴로 내보내라」고 알린다 |
| 기본 본보기 | 툴 안 `src/arttool/providers/workflows/klein_prop.json` · `klein_inpaint.json` 둘. 실측 1 · 2단계 워크플로에서 옮겨 오고 **모델 · LoRA 파일 이름 자리는 전부 자리표시**로 바꾼다. `pyproject.toml` package-data 에 한 줄 |
| 덮어쓰기 | spec `workflow` (또는 설정 파일 `workflows.<kind>`)에 사용자 파일 경로. 주면 본보기 대신 그것을 쓴다 |
| 자리표시 | JSON 값이 **문자열 통째로** `"$이름"` 인 칸만 바꾼다(글 이어 붙이기 없음 → 프롬프트에 따옴표가 있어도 JSON 이 안 깨진다). 숫자 자리는 숫자로 넣는다 |
| 아는 자리 | `$prompt` `$negative` `$seed` `$width` `$height` `$image` `$mask` + 설정 `models` 의 키(예 `$unet` `$text_encoder` `$vae` `$lora` `$lora_strength`) |
| 남은 자리 | 채우고 나서 `$` 로 시작하는 문자열 값이 남으면 **종료 2** · 「채울 값이 없다 : $lora (설정 models 에 넣는다)」 |
| 결과 노드 | `SaveImage` 노드의 그림을 모은다. 여럿이면 노드 id 순. 본보기는 하나만 둔다 |

**모델 이름을 어디에 두나** : 코드 · 본보기에는 안 둔다(mem `20261007-f1618254` 「모델은 사용자가 꽂는다」). 설정 파일 `models` 표에만 둔다. 파일 이름은 ComfyUI 의 모델 폴더 안 이름이고, 그 폴더가 어디인지는 툴이 모른다.
**왜 둘 다(내장 + 덮어쓰기)인가** : 사용자 파일만 받으면 처음 쓰는 사람이 워크플로를 손으로 짜야 하고, 시험이 흔들린다(본보기가 없으면 가짜 서버 시험이 고정되지 않는다). 내장만 두면 Qwen-Edit · Z-Image 처럼 노드 모양이 다른 판을 못 꽂는다.

## 4. 설정과 인자 (D)

### 4-1. 어디서 받나 (앞이 이긴다)

| 값 | spec JSON | 설정 파일 | 환경변수 | 없으면 |
| --- | --- | --- | --- | --- |
| ComfyUI 주소 | — | `endpoint` | `ARTTOOL_LOCAL_ENDPOINT` (있던 것) | 제공자 꺼짐(목록에서 빠짐) |
| 설정 파일 경로 | — | — | `ARTTOOL_LOCAL_CONFIG` | 설정 없이 돈다 — 본보기는 모델 자리가 남아 종료 2 |
| 모델 · LoRA 이름 | `models` (키별로 덮음) | `models` | — | 종료 2 |
| 워크플로 | `workflow` | `workflows.prop` · `workflows.inpaint` | — | 내장 본보기 |
| 작업 크기 | `work_size` | `work_size` | — | 512 |
| 시간 제한 | — | `timeout_s` | — | 600초 (Qwen 1분 · Wan 1분 반 실측의 넉넉한 몫) |
| 무거운 판 표시 | — | `heavy: [이름…]` (워크플로 파일 이름) | — | 없음 |

- 주소는 **환경변수가 기본, 설정 파일은 보조.** 둘 다 있으면 환경변수가 이긴다(한 판만 다른 서버로 돌리기 쉽다). `http://` · `https://` 만 받는다.
- 설정 파일은 YAML(이미 의존성에 `pyyaml` 있음). 저장소에는 **빈 본보기 `local.example.yaml`** 만 두고, 실제 파일은 사용자 자리(git 밖)에 둔다. 미니PC 의 실제 값은 local 문서에만 적는다.
- 주소 · 설정 경로는 결과 JSON 에 안 적는다(`meta.endpoint` 는 `host:port` 까지만 — 키가 없는 서버라 비밀은 아니지만 공개 로그에 남지 않게).

### 4-2. spec JSON 에 더하는 칸

`size` · `prompt` · `seed` · `reference` 는 있던 것을 그대로 쓴다. 더하는 것 : `mask`(inpaint 마스크 PNG) · `negative` · `variants`(시드 여러 개, 기본 1 — 시드는 `seed`, `seed+1` …) · `workflow` · `models` · `work_size` · `extra_colors`(inpaint 색 맞추기에 더할 색).
inpaint 의 원본은 `reference` 칸이다. `size` 는 원본 크기와 같아야 한다(다르면 종료 2).

### 4-3. 호출 차례 · 기다리기

| 차례 | ComfyUI API | 실패하면 |
| --- | --- | --- |
| 1 살아 있나 | `GET /system_stats` (5초) | 닿지 않음 → **종료 5** 「ComfyUI 에 닿지 않는다 (ARTTOOL_LOCAL_ENDPOINT 를 본다)」 |
| 2 노드가 있나 | `GET /object_info` 에서 워크플로의 `class_type` 이 다 있나 | 없음 → **종료 1** 「이 노드가 서버에 없다 : UnetLoaderGGUF」 |
| 3 그림 올리기 | `POST /upload/image` (멀티파트, 이름은 `arttool_<임의>.png`) | 종료 1 |
| 4 줄 세우기 | `POST /prompt` | 400 이면 `node_errors` 를 한 줄씩 묶어 **종료 1** (모델 파일이 없을 때 여기서 걸린다) |
| 5 기다리기 | `GET /history/{id}` 를 1초마다 | `timeout_s` 넘음 → `POST /interrupt` 시도 뒤 **종료 1** 「시간 초과」 · 상태 error → 종료 1 + 서버 메시지 |
| 6 받기 | `GET /view?filename=…&type=output` | 한 장 64MB 넘음 · PNG 아님 → 종료 1 |

- websocket 은 안 쓴다(표준 라이브러리에 없다). 폴링 1초면 9초~90초 판에 충분하다.
- 서버가 준 파일 이름은 `/view` 질의에만 쓰고, 저장 이름은 툴이 정한다(`safe_join` 감옥 안). 서버 쪽 출력 폴더는 안 지운다.
- 종료 코드 표는 안 넓힌다. 5 의 뜻을 README 에 「바깥 실행 파일 · 서버 없음」으로 한 마디 넓힌다.

### 4-4. `--dry-run`

**네트워크를 하나도 안 부른다.** 하는 것 : 요청 검사 · 워크플로 읽기 · 자리표시 채우기(남은 자리 있으면 종료 2 그대로) · inpaint 면 원본/마스크 크기 맞나 보기. 쓰는 것은 지금처럼 `local_request.json` 하나 — 채운 워크플로 · 올릴 그림 목록 · 쓸 파일 목록(`would_write`) · `heavy` 경고를 담는다. 주소 환경변수는 지금처럼 있어야 한다(제공자가 켜져야 고를 수 있다).

## 5. 기존 제공자 계약과 맞춤 (E)

**계약은 지키고 넓힌다.** `Provider` 의 네 메서드(`available` · `capabilities` · `estimate` · `make`)는 그대로. 넓히는 것은 셋 :

| 무엇 | 바꿈 | 다른 제공자 영향 |
| --- | --- | --- |
| `KINDS` | `prop` · `inpaint` 더함 | 없음 (`capabilities` 에 안 넣으면 「못 만든다」 오류 그대로) |
| `ProviderRequest` | `mask` · `negative` · `variants=1` · `options: dict`(workflow · models · work_size · extra_colors) 더함. 모두 기본값 있음 | 없음. `count()` 는 `frames × directions × variants` — variants 기본 1 이라 PixelLab 견적 그대로 |
| `local.capabilities()` | `{character, tile, rotate}` → **`{prop, inpaint}`** | — (지금 셋은 거짓 광고였다. 캐릭터 · 8방향은 PixelLab 유지 결정, 타일은 미해결) |

`ProviderResult` 는 그대로. `images` = 요청 크기 PNG, `meta` 에 `raw`(512 날것 경로) · `seconds` · `workflow`(이름) · `outside_changed`(inpaint) 를 넣는다. `cost_usd` 는 0.

`--provider` 로 바꿔 끼울 수 있는 것 (받는 명령은 지금처럼 `provider make` 하나뿐) :

| kind | code | pixellab | local (1차) | 비고 |
| --- | --- | --- | --- | --- |
| `character` | 참조에서 자름 | 요청 JSON · 견적 | — | 캐릭터 베이스는 PixelLab 유지 |
| `tile` | 참조에서 자름 | 요청 JSON · 견적 | — | 48px 타일 미해결(⑤) |
| `rotate` | — | 요청 JSON · 견적 | — (2차 후보) | Qwen-Edit 4방향 후보 |
| `skeleton` | — | 요청 JSON · 견적 | — | |
| `prop` | — | — (나중) | **뽑기** | 소품 · 건물 · 이펙트 64px 급 |
| `inpaint` | — | — (나중) | **뽑기** | 밖 0픽셀 보장 |

즉 1차에서 **같은 kind 를 둘이 겹쳐 내는 자리는 없다.** 「바꿔 끼우기」는 PixelLab 쪽 `prop` · `inpaint` 가 생길 때 의미가 생긴다. PixelLab 은 지금도 MCP 로 에이전트가 직접 부르므로, 스킬 문서의 「어느 길」 표에 「소품 · inpaint 는 local 먼저, 마음에 안 들면 PixelLab MCP」 를 적는다.

## 6. 메모리 주의 (F)

**툴은 서버를 끄고 켜지 않는다. 경고만 낸다.**

| 판 | 피크 (실측) | 툴이 하는 것 |
| --- | --- | --- |
| klein fp8 (1차 기본) | +11GB | 아무것도 안 함 |
| Qwen-Edit · Wan (사용자 워크플로 · 2차) | 22~25GB | 설정 `heavy` 에 든 워크플로면 결과 · dry-run 에 경고 한 줄 「무거운 판 : 피크 ~25GB. 다른 큰 프로세스(LLM 서버 등)를 내린 뒤 돌린다」 |

까닭 : 끄고 켜기는 기계마다 다르고(서비스 이름 · 권한) 공개 툴에 미니PC 사정을 박지 않는다는 결정과 부딪친다. 다른 사람의 서버를 툴이 내리면 사고가 난다. 「무엇을 내리고 다시 띄우나」 차례는 git 밖 local 문서에 둔다.
덤 : 결과 `meta.seconds` 를 남겨 느려짐(메모리 밀림)을 사람이 알아채게 한다. `POST /free` 는 안 부른다(`--cache-none` 으로 띄우는 것을 local 문서에 적는 쪽이 낫다).

## 7. 시험 전략 (G)

### 7-1. 가짜 ComfyUI 서버 (미니PC 없이)

`tests/fake_comfy.py` — 표준 라이브러리 `http.server` 를 스레드로 `127.0.0.1:0`(빈 포트)에 띄운다. 받는 길 : `/system_stats` · `/object_info` · `/upload/image` · `/prompt` · `/history/{id}` · `/view` · `/interrupt`. 결과 그림은 numpy 로 만든 512 PNG(바깥은 일부러 37% 바꿔 둔 「날것」 흉내). 부른 길과 횟수를 기록한다.

| 시험 | 보는 것 |
| --- | --- |
| prop 한 장 · variants 3 | 요청 크기 PNG 3장 · `raw/` 3장 · 시드가 seed, +1, +2 로 들어갔나 |
| inpaint | 마스크 밖 칸이 원본과 **바이트까지 같다**(무작위 마스크 여러 개) · 안쪽 색이 원본 색 ∪ extra_colors 안 · `outside_changed == 0` |
| 자리표시 | 따옴표 · 줄바꿈이 든 프롬프트도 JSON 이 안 깨진다 · 남은 `$lora` → 종료 2 · 화면 저장 꼴 → 종료 2 |
| 서버 없음 | 닫힌 포트 → 종료 5 |
| 노드 없음 · 400 `node_errors` · history error | 종료 1 + 메시지에 노드 이름 |
| 시간 초과 | 끝나지 않는 가짜(`timeout_s=2`) → `/interrupt` 를 불렀나 · 종료 1 |
| 큰 응답 · PNG 아님 | 종료 1 |
| dry-run | 가짜 서버 부른 횟수 0 · `local_request.json` 에 채운 워크플로 |
| 경로 | 서버가 `../x.png` 같은 이름을 줘도 저장은 감옥 안 툴 이름 |
| 계약 | `test_providers.py` 기존 시험 그대로 통과 · `local` capabilities 가 `{prop, inpaint}` |

이어지는 명령 사슬(`cutout` → `merge-colors` → `check`)은 가짜 결과로 한 번 끝까지 돌리는 시험 하나(`test_example_pipeline.py` 꼴).

### 7-2. 실물 실측

미니PC 는 「못 쓴다」가 아니라 **게임 서버가 떠 있어 메모리를 크게 먹는 판만 못 돌린다.**

| 판 | 언제 |
| --- | --- |
| klein fp8 prop · inpaint (피크 +11GB) | 게임 서버 메모리 여유를 확인한 뒤 바로 돌릴 수 있다. 1차 구현 끝의 실측 소단계(L10)가 이것 |
| Qwen-Edit · Wan 사용자 워크플로 (피크 22~25GB, LLM 서버 42GB 급과 같이 못 올림) | 게임 서버가 내려간 뒤 |

실측에서 볼 것 : 본보기 둘이 실제 ComfyUI 0.31 에서 그대로 도나 · 장당 시간이 실측 1단계(9초)와 비슷한가 · inpaint 밖 0 · 64px 소품 `cutout → merge-colors → check` ok · BOX 와 단계 축소 견줌(**실측 끝 → BOX 유지**, 10-07). 확인 명령 · 주소는 local 문서를 본다.

## 8. 건드리는 파일

| 파일 | 무엇 |
| --- | --- |
| `src/arttool/providers/base.py` | KINDS 둘 · ProviderRequest 칸 넷 · `count()` |
| `src/arttool/providers/local.py` | 전부 새로 (뼈대 대체). 흐름만 두고 아래 셋을 부른다 |
| `src/arttool/providers/comfy.py` (새) | ComfyUI 클라이언트 — 4-3 표 그대로. 그림 처리를 모른다 |
| `src/arttool/providers/workflow.py` (새) | 워크플로 읽기 · API 꼴 검사 · 자리표시 채우기 · 남은 자리 찾기 · 노드 이름 뽑기 |
| `src/arttool/providers/postproc.py` (새) | NEAREST 키우기 · BOX 줄이기 · 마스크 안 색 맞추기 · 합성 · 밖 바뀐 칸 세기 |
| `src/arttool/providers/workflows/*.json` (새) | 본보기 둘 |
| `src/arttool/cli.py` | `_run_provider` 가 spec 새 칸을 넘김. `--kind` 고르기는 KINDS 를 따라 자동 |
| `pyproject.toml` | package-data `arttool.providers` = `workflows/*.json` |
| `local.example.yaml` (새, 저장소 맨 위) | 빈 설정 본보기 — 모델 키 이름만, 값은 비움 |
| `tests/fake_comfy.py` · `tests/test_provider_local.py` (새) | 7-1 |
| `README.md` · 명령안내 · 스킬(`arttool-usage`) | 제공자 표 · 종료 5 뜻 · 「뽑은 뒤 차례」 · 「어느 길」 표 |

## 9. 기존 결정과 어긋나는 자리

| 기존 | 이번 | 왜 |
| --- | --- | --- |
| mem `20261007-f1618254` 「모델 · 워크플로 JSON 은 사용자가 꽂는다」 | 워크플로는 **기본 본보기를 툴에 넣고** 덮어쓰기를 받는다. 모델 이름은 그대로 사용자가 꽂는다 | 본보기에는 모델 이름이 안 들어가서 공개 툴에 미니PC 사정이 안 샌다. 처음 쓰는 사람 · 시험 고정을 위해 본보기가 필요하다 |
| `local` capabilities `{character, tile, rotate}` | `{prop, inpaint}` | 실측 판단(캐릭터 · 8방향 PixelLab 유지, 타일 미해결)과 맞춘다 |
| 종료 5 「바깥 실행 파일 없음」 | 「바깥 실행 파일 · 서버에 닿지 않음」 | 표를 안 늘리고 뜻만 넓힌다 |

## 10. 소단계 (H)

| 번호 | 이름 | 분류 | 크기 | 의존 | 내용 |
| --- | --- | --- | --- | --- | --- |
| L1 | 계약 넓히기 | 구현 | S | — | base.py KINDS · Request 칸 · count · 기존 시험 통과 |
| L2 | ComfyUI 클라이언트 | 구현 | M | — | comfy.py 4-3 표 · 멀티파트 올리기 · 폴링 · 크기 제한 |
| L3 | 워크플로 자리표시 | 구현 | M | — | workflow.py · API 꼴 검사 · 남은 자리 종료 2 · 본보기 둘(미니PC 의 실측 워크플로에서 옮김) |
| L4 | prop 흐름 | 구현 | M | L1 · L2 · L3 | local.py prop · BOX 축소 · raw 남기기 · variants |
| L5 | inpaint 흐름 | 구현 | M | L4 | postproc.py 키우기 · 색 맞추기 · 합성 · outside_changed |
| L6 | CLI · dry-run · 설정 | 구현 | S | L4 | spec 새 칸 · YAML 설정 · 앞이 이기는 차례 · dry-run 네트워크 0 · heavy 경고 |
| L7 | 가짜 서버 시험 | 구현 | M | L2~L6 | fake_comfy.py · 7-1 표 · 사슬 시험 하나 |
| L8 | 문서 · 스킬 | 문서 | S | L7 | README · 명령안내 · 스킬 「뽑은 뒤 차례」 · `local.example.yaml` · local 문서에 미니PC 설정 값 |
| L9 | 코드 리뷰 | 구현 | S | L8 | 커밋 묻기 전 리뷰 한 번(규칙) — 보안 점검(`security-invariants`) 포함 |
| L10 | 실물 실측 (klein) | 실측 | M | L9 | 게임 서버 메모리 여유 확인 뒤 prop 4장 · inpaint 2장 · 사슬 끝까지 |
| L11 | 실측 보고 | 문서 | S | L10 | 조사 문서 한 장 + 진행상황 |

`.\EffortTool\bin\effort.exe estimate` 출력(2026-10-07) : 구현 S 2분 · M 4분, 문서 S 1분 미만, 실측 M 31분 — **합 59분 (범위 7분~6시간 44분).**
주의 : mem 에 「estimate 가 L급 새 코드를 2.5배 작게 잡는다」(10-01)가 있다. L2 · L3 · L5 는 새 모듈이라 사람 눈금으로는 **구현 합 약 1.5~2시간 + 실측 30분~1시간**으로 본다.
순서 : L1 · L2 · L3 은 서로 독립(같은 폴더라 한 갈래가 차례로) → L4 → L5 · L6 → L7 → L8 → L9 → L10 → L11.

## 11. 못 정한 것

| 번호 | 무엇 | 선택지 | 추천 | 까닭 |
| --- | --- | --- | --- | --- |
| 1 | inpaint 마스크 안 색 맞추기 기본값 | ⓐ 원본 색 + extra_colors(기본) ⓑ 프로필 팔레트 ⓒ 안 맞춤 | ⓐ, `snap: profile` · `none` 을 spec 으로 고를 수 있게. 구현(10-07 리뷰) : `profile` 은 프로필 파일을 읽지 않고 spec `palette` 색 목록을 받는다 | 원본 색이 가장 잘 섞인다. `none` 은 색 수가 수백이 되어 `check` 에 걸리지만 「날것 보기」용으로 남긴다 |
| 2 | BOX 말고 다른 축소 | BOX 하나 · NEAREST 도 | BOX 하나 + `raw/` 남김. 사용자 제안(10-07) : mipmap 식 단계 축소도 본다. BOX 를 반씩 세 번 하는 것은 BOX 한 번과 같으니 필터를 달리한(LANCZOS · bilinear) 단계 축소만 뜻이 있다 — L10 실측에서 BOX 와 견줬다(**실측 끝 → BOX 유지**: 차이가 작고 방향이 섞임, `Docs/Research/2026-10-07-provider-local실측.md` 4절) | 1단계에서 BOX 가 낫다고 봤다. 24px 는 축소법으로 안 풀려 ⑤ 로 따로 본다 |
| 3 | `provider ping` 같은 상태 명령 | 만든다 · 안 만든다 | 안 만든다 | 실제 판의 1번 차례(`/system_stats`)가 같은 일을 하고, dry-run 은 네트워크 0 이 약속이다 |
| 4 | PixelLab 쪽 `prop` · `inpaint` kind | 지금 넣음 · 나중 | 나중 | PixelLab 은 MCP 로 부르고 pixellab 제공자는 아직 견적만이다 |
| 5 | Z-Image 본보기 | 1차에 넣음 · 사용자 워크플로로 | 사용자 워크플로로 | klein 이 2.4배 빠르고 화풍도 또렷했다. 본보기가 늘면 실측 · 시험도 는다 |

## 12. 신뢰도

| 항목 | 신뢰도 | 근거 |
| --- | --- | --- |
| 계약 맞춤 (base.py · cli.py) | 85% | `base.py` · `local.py` · `code.py` · `pixellab.py` · `cli.py` `_run_provider` · dry-run 표 · `test_providers.py` 를 읽었다 |
| 후처리 자리 | 80% | 실측 1 · 2단계의 흐름과 0픽셀 수치, 축소 명령이 없음을 grep 으로 확인. 색 맞추기가 안쪽 화풍을 해치는지는 안 돌려 봤다 |
| ComfyUI API 차례 | 70% | 공개 API 길(`/prompt` · `/history` · `/view` · `/upload/image` · `/object_info`)을 기억으로 적었다. 0.31 에서 그대로인지 실물로 안 봤다 — L10 에서 확인 |
| 소단계 크기 | 60% | estimate 출력 + 10-01 배율 교훈. 새 모듈 셋이라 넘칠 수 있다 |
| 전체 | **확인 못 함 (설계만)** | 문서만 썼다. 돌려 본 것 없음 — 사람이 봐야 안다 |
