# provider local 실물 실측 — klein fp8 (L10, 2026-10-07)

설계 `Docs/Design/2026-10-07-provider-local설계.md` 7-2절 · 10절 L10 의 실측이다.

## 결론

- **내장 본보기 둘(`klein_prop` · `klein_inpaint`)은 고칠 노드가 없었다.** 노드 이름 15종 · 입력 이름 · 열거값이 실물 ComfyUI 0.31 과 다 맞았고, 그대로 돌아 그림이 나왔다. 바꾼 것은 「초안」 표시 글뿐이다.
- 1 · 2단계 실측 때 쓴 klein 워크플로(`SamplerCustomAdvanced` + `Flux2Scheduler` + `EmptyFlux2LatentImage`)와 본보기(`KSampler` simple + `EmptyLatentImage`)는 **같은 시드에서 거의 같은 그림**을 냈다(칸 0.5% 만 다름). 그래서 본보기를 실측 그래프로 갈아 끼우지 않았다.
- prop 4장 장당 **10.2~11.3초**, 미니PC 메모리 피크 사용 **+14.6GB**(2초 간격 표본) · GTT 피크 9.3GB. 게임 서버를 띄운 채로 가용 41GB 아래로 안 내려갔다.
- 사슬 `cutout → merge-colors → check` 는 **끝까지 ok**. 단 문서에 적힌 `merge-colors --max-colors 16` 은 4장 묶음(2,894색)에서 종료 1 이 났다 — `--per-image` 나 `--tol` 을 같이 줘야 한다(넘긴 것 1).
- inpaint 3판 모두 `outside_changed` 0. 덧대기 경로(33×21 → 작업 495×315 → 496×320)도 실물에서 돌았다.
- 시간 초과 · 줄 지우기 · `/interrupt` 는 실물에서 뜻대로 됐다. **시간 초과는 줄 선 시간도 센다.**
- 축소는 **BOX 유지**. 반씩 세 번 LANCZOS 가 외곽이 조금 또렷하지만 색 수가 늘고 외톨이 픽셀은 비슷하다.

## 환경

| 항목 | 값 |
| --- | --- |
| 날짜 | 2026-10-07 18:33~18:42 (서버 쪽) |
| 서버 | ComfyUI 0.31.0, `--cache-none` 컨테이너. 띄우는 법 · 주소 · 터널은 git 밖 local 문서(「ArtTool provider local 설정」 절)를 본다 |
| 게임 서버 | **떠 있음**(내리지 않음). 앞뒤 모두 같은 상태 |
| LLM 서비스 | 꺼져 있음(켜지 않음) |
| 시작 때 메모리 | 사용 4.9GB · 가용 55GB |
| 모델 | klein 4B fp8 · 인코더 `qwen_3_4b` **fp8_mixed** 판(2단계 결정) · flux2 VAE · 도트 LoRA 세기 1.0. 파일 이름은 설정 YAML 에만(git 밖) |
| 작업 크기 | 512 (64px 요청 × 8배) |

## 1. 노드 맞추기

`GET /object_info` : **1.58MB · 934노드 · 0.07~0.10초**(터널 너머).

| 본보기 노드 | 추측 | 실물 | 고침 |
| --- | --- | --- | --- |
| `UNETLoader` | `unet_name` · `weight_dtype: default` | 같음(`default` · `fp8_e4m3fn` …) | 없음 |
| `CLIPLoader` | `clip_name` · `type: flux2` | 같음. `flux2` 가 열거값에 있다. `device` 는 선택 입력이라 빼도 된다 | 없음 |
| `VAELoader` · `LoraLoaderModelOnly` | `vae_name` · `lora_name` · `strength_model` | 같음 | 없음 |
| `EmptyLatentImage` | 빈 잠재 | 있음(step 8). klein 전용 `EmptyFlux2LatentImage`(step 16)도 있다. 본보기 것으로도 잘 돈다 | 없음 |
| `KSampler` | euler · simple · cfg 1 | 같음. seed 범위 0~2^64-1 | 없음 |
| `LoadImage` · `ImageToMask` | `channel: red` | 같음(`red` · `green` · `blue` · `alpha`) | 없음 |
| `SetLatentNoiseMask` | `samples` · `mask` | 같음. `InpaintModelConditioning` 도 있다(안 씀) | 없음 |
| `ImageCompositeMasked` | `destination` · `source` · `x` · `y` · `resize_source` · `mask` | 같음 | 없음 |
| `VAEEncode` · `VAEDecode` · `CLIPTextEncode` · `SaveImage` | — | 같음 | 없음 |

본보기 대 실측 그래프(같은 프롬프트 · 시드 1000) : 512 날것에서 평균 차 0.36/255, 8 넘게 다른 칸 0.5%. 눈으로 구분 안 된다.

## 2. prop 4장

프롬프트 꼴은 1단계를 따랐다 : `Pixel art style. <물건>, game prop sprite, side view, thick dark outline, limited palette, 16-bit pixel art, centered, plain solid white background`, 64×64, 시드 1000.

| 물건 | `meta.seconds` | 64px 색 수 | cutout | merge(`--per-image`) | check |
| --- | --- | --- | --- | --- | --- |
| wooden barrel | 11.26 | 854 | ok | 16색 | ok |
| iron lantern | 10.21 | 867 | 경고 `enclosed` 17칸(고리 안쪽) | 16색 | ok |
| stone well | 11.25 | 601 | ok | 16색 | 경고 `integer_scale`(부드러운 확대 0.199 > 0.15) |
| treasure chest | 11.27 | 916 | ok | 16색 | ok |

- 묶음 check `status: ok`(필수 실패 0). 눈으로 넷 다 쓸 만하다. 상자는 16색으로 줄이며 금색 테가 갈색 쪽으로 눌렸다.
- 메모리(미니PC `free -m` 2초 간격 201표본, 판 전체) : 사용 피크 19.5GB(시작 4.9GB → **+14.6GB**), 가용 최저 41.4GB, GTT 피크 9.3GB. 2단계 「+11GB」 보다 큰 것은 재는 법 차이(그쪽은 0.5초 `MemTotal−MemAvailable`, 이쪽은 `used`)로 본다.
- 장당 시간은 1 · 2단계(9~14초)와 비슷하다. 서버 쪽 「Prompt executed」 9.2~9.6초에 올리기 · 받기 · 폴링이 1초 남짓 붙는다.

## 3. inpaint

| 판 | 원본 | 마스크 | 작업 크기 | 초 | `outside_changed` | 결과 |
| --- | --- | --- | --- | --- | --- | --- |
| A | prop 통 64px(흰 바탕, 정리 전) | 가운데 16×16 | 512×512 | 10.40 | 0 | 경고표 모양은 그렸지만 `snap: source` 라 빨강이 나무 색으로 눌렸다 |
| A2 | 같음 + `extra_colors` 빨강 · 흰색 | 같음 | 512 | 10.29 | 0 | 빨간 경고표가 산다. 원본이 정리 전(854색)이라 check fail(색 수) |
| C | **정리한 통**(투명 바탕 16색) + `extra_colors` | 같음 | 512 | 10.24 | 0 | 빨간 경고표 · 17색 · **check ok** |
| B | 상자 조각 **33×21**(투명 칸 184개) | 14×10 | **495×315 → 496×320 덧댐** | 10.22 | 0 | 덧대기 · 자르기 돈다. 자물쇠 노랑이 원본 색으로 눌렸다 |

- 쓰는 법 교훈 : inpaint 원본은 **정리한(merge 끝난) 그림**을 쓰고, 새 색이 필요하면 `extra_colors` 를 준다. 정리 전 원본이면 check 가 색 수로 걸린다.

## 4. BOX 대 단계 축소

같은 날것 512 넷을 셋으로 줄여 `cutout --key corner` → `merge-colors --max-colors 16 --per-image` → `check`.

| 축소 | 합치기 전 색 수(통 · 등 · 우물 · 상자) | 합친 뒤 외톨이 픽셀 | check | 눈 |
| --- | --- | --- | --- | --- |
| BOX 한 번(툴 기본, 툴 출력과 바이트까지 같음) | 834 · 858 · 584 · 892 | 126 · 112 · 185 · 67 | ok, `integer_scale` 1장 | 기준 |
| LANCZOS 반씩 세 번 | 973 · 926 · 696 · 1107 | 108 · 106 · 204 · 94 | ok, `integer_scale` 1장 | 외곽선이 조금 또렷 |
| BILINEAR 반씩 세 번 | 911 · 922 · 596 · 992 | 132 · 112 · 209 · 100 | ok, `integer_scale` 2장 | 상자가 어둡게 뭉갬 |

외톨이 픽셀은 「8 이웃이 다 다른 색인 불투명 칸」으로 스크래치 스크립트가 셌다. 차이가 작고 방향이 섞여서 **BOX 를 그대로 둔다**(설계 11절 2번 결론 유지).

## 5. 리뷰 확인 목록 12개

| # | 확인 | 결과 |
| --- | --- | --- |
| ① | `/queue` delete · `prompt_id` 실은 `/interrupt` | **된다.** `timeout_s: 3` 판 → 서버 로그 「Interrupting prompt <우리 id>」 「Processing interrupted」, 뒤 줄 비었음. 종료 1 |
| ② | 16 배수 아닌 폭 | 서버는 500×300 을 **오류 없이 받아 496×288 을 돌려준다**(조용히 내림). 툴은 덧대기로 늘 16 배수를 보내므로(33×21 → 496×320) 안 걸린다 |
| ③ | seed 음수 · 2^64 | 둘 다 **400** `value_smaller_than_min` · `value_bigger_than_max`. 2^64-1 은 200 |
| ④ | RGBA 투명 원본 | `LoadImage` 는 알파를 빼고 RGB 만 쓴다 — 투명 칸이 **검정**으로 모델에 들어갔다(날것에 검은 띠). 밖은 코드가 원본으로 되돌려 결과 영향 없음 |
| ⑤ | `ImageToMask channel=red` | 맞다. 흰 네모 안만 다시 그려졌다 |
| ⑥ | 노드 이름 · 열거값 | 1절 표 — 고칠 것 없음 |
| ⑦ | 업로드 응답 꼴 | `{"name", "subfolder": "", "type": "input"}`. subfolder 를 주면 그 이름이 그대로 온다. 툴의 `subfolder/name` 조합과 맞음 |
| ⑧ | history 꼴 · 같은 seed 재실행 | 키 `prompt · outputs · status · meta`, `status.status_str: success · completed: true`. `--cache-none` 서버라 같은 seed 두 번째도 **outputs 가 찬다**(`execution_cached` 노드 0). 캐시를 켠 서버에서 비는지는 못 봄 |
| ⑨ | `/view` 질의 | `filename · subfolder · type=output` 로 PNG 받음. `../x.png` 는 400 |
| ⑩ | node_errors 길이 | 없는 LoRA 이름 → 400 본문 1,101바이트(목록 전체가 든다). 툴 메시지는 「4 LoraLoaderModelOnly : Value not in list …」 로 잘려 읽기 좋다 |
| ⑪ | `/object_info` 크기 · 시간 | 1.58MB · 934노드 · 0.07~0.10초. 판마다 한 번 불러도 짐이 아니다 |
| ⑫ | 시간 초과가 줄 선 시간도 세나 | **센다.** 판 하나(10초)를 넣고 바로 `timeout_s: 6` 판을 넣자 6초에 종료 1 「줄에서 치웠다」. 서버는 우리 둘째 판을 안 돌렸고 첫 판(남의 판 몫)은 끝까지 돌았다 |

## 6. 고친 것

| 파일 | 무엇 |
| --- | --- |
| `src/arttool/providers/workflows/klein_prop.json` · `klein_inpaint.json` | 노드 1 제목 「실물 확인 전 초안」 → 「실물 확인함(ComfyUI 0.31, L10 2026-10-07)」. 노드 · 입력은 그대로 |
| `tests/test_workflow.py` | 본보기 표시 시험을 「초안」 → 「실물 확인함」 으로 |

전체 시험 2736 통과 · 1 건너뜀.

## 7. 남은 것

- 명령안내 24절 · README 의 「본보기는 초안」 주의, local 문서 끝 「L10 에서 노드 이름부터 맞춘다」 줄은 이제 낡았다 — 걷어 낸다.
- 명령안내 「뽑은 뒤 차례」 의 `merge-colors --max-colors 16` 에 `--per-image`(또는 `--tol`)를 붙인다. 여러 장 묶음은 색이 2,048을 넘어 종료 1 이 난다.
- inpaint 원본은 정리한 그림 · 새 색은 `extra_colors` 라는 쓰는 법 한 줄을 명령안내 · 스킬에 넣는다.
- 투명 원본이 모델에 검정 바탕으로 들어가는 것(④). 지금은 결과에 문제가 없다. 마스크 가장자리가 투명 칸에 닿는 inpaint 에서 검은 테가 끼는지는 아직 안 봤다.
- 캐시를 켠 서버에서 같은 seed 재실행 때 outputs 가 비는지(⑧)는 못 봤다.
- 실측 중 서버 input 폴더에 올린 그림(`arttool_*.png`, 확인용 `arttool_probe.png` · `arttool_probe/` 하위 폴더 하나)과 output 폴더 결과는 지우지 않고 두었다.
- Qwen-Edit · Wan 무거운 판은 게임 서버가 내려간 뒤.

## 8. 재현

1. 서버 띄우기 · 터널 · 설정 YAML 은 git 밖 local 문서의 「ArtTool provider local 설정」 절을 따른다.
2. `ARTTOOL_LOCAL_CONFIG=<설정 YAML>` 뒤 `arttool provider make --provider local --kind prop --spec <spec> --out <폴더> --json`.
3. 산출물(PNG · 비교판 · 메모리 로그 · probe 스크립트)은 이번 세션 스크래치패드 `l10/` 에만 있다. 저장소에는 안 넣었다.

## 신뢰도

| 항목 | 신뢰도 | 근거 |
| --- | --- | --- |
| 본보기 둘이 실물에서 돈다 | 95% | prop 6판 · inpaint 4판을 실제로 돌려 PNG 를 눈으로 봤다 |
| 장당 시간 · 메모리 | 85% | 장당 10판 남짓, 편차 작음. 메모리는 2초 표본이라 짧은 꼭대기를 놓쳤을 수 있다 |
| 확인 목록 ①~⑫ | 90% | ⑧ 캐시 켠 서버 경우만 못 봤다. 나머지는 서버 응답 · 로그를 직접 봤다 |
| BOX 유지 판단 | 70% | 4장 · 한 시드만 견줬다 |
