# PixelLab 으로 뽑기

PixelLab 은 MCP 도구로 직접 부른다(스크립트로 감싸지 않는다). ArtTool 은 그 **앞(밑판 · 프롬프트 · 마스크)과 뒤(손질 · 겹 · 검사)** 를 맡는다.
도구 이름 · 인자는 바뀔 수 있다 — **부르기 전에 그 도구의 설명을 읽는다.** 아래 요령은 실제 작업 피드백(ArtTool `Docs/Todo/` 의 작업 피드백 문서들)에서 모은 것이다.

## 1. 뽑기 전에

```
arttool template show char_small --size 48x64 --profile P          # 값 · prompt 문장 · 순서
arttool template render char_small --size 48x64 --profile P --out work/guide
```

- 캐릭터 기본 본보기는 48×64 `sd`(약 2등신). 다른 비율은 `--preset chibi|tall`. 건물 · 큰 물건 · 화면 조각은 `building` · `machine` · `screen_piece`, 말풍선은 `ui9_panel --preset bubble`.
- `show` 결과의 **`prompt`** 를 글머리로 쓴다. `--profile` 을 주면 그 게임의 외곽선 방식 · 빛 방향 · 팔레트 hex 가 채워져 있다.
- `render` 가 낸 것 : `_guide.png`(가이드 겹) · `_mask_<겹>.png`(겹 자리, 흰 = 그릴 자리) · `_fNN.png`(이펙트 프레임 밑그림) · `template.json` · `layers.json`.
  **마스크는 inpaint 의 마스크로, 프레임 밑그림은 참고 그림으로** 그대로 쓴다.
- 겹으로 나눌 캐릭터는 `char_parts` 템플릿이 겹별 마스크(머리카락 · 얼굴 · 윗옷 · 아랫옷 · 본체)와 `split.json` 초안을 준다.

## 2. 어떤 도구를 언제

| 하고 싶은 것 | 도구 | 메모 |
| --- | --- | --- |
| 한 장 뽑기 (작은 · 중간) | `create_image_pro_flash` | 4의 배수 맞춤 크기. 한 장 값이 싸다. 캔버스 한 변 256 까지 |
| 큰 그림 · 배경 한 장 | `create_image_pro` (512 까지, 값이 비싸다) · `create_image_pixflux` (400 까지) | 화면 폭 건물 · 세로 화면 배경 |
| 작은 크기 캐릭터 | **큰 그림 → 줄이기 → `edit_image_pro_flash`(글 편집) 「깨끗한 도트로 다시」** | 작은 크기의 기본 길. 얼굴 · 자세는 남고 잡티만 정리된다 |
| 일부만 다시 그리기 · 겹 | `inpaint_image` · `inpaint_image_pro_flash` | **마스크 밖을 한 픽셀도 안 바꾼다** — 겹 떼기의 바탕 |
| 같은 화풍 한 벌 | 첫 장의 `source_image_id` 를 다음 장의 화풍 그림(`style_image`)으로 | 몸 크기 · 선 굵기 · 색이 한 벌로 맞는다 |
| 일 기다리기 · 받기 | `wait_for_jobs` → `get_image` | 아래 「흔한 사고」 |
| 무엇을 고를지 모르겠다 | `agent_help` 에 묻는다 | 답이 정확한 편이다 |

## 3. 크기 · 방향 · 색은 글로 못 박는다

- **크기는 캔버스로 정한다.** 「캔버스 폭의 60%」 「키 44px」 같은 글은 안 먹는다. 그림이 캔버스를 거의 채워 오거나, 반대로 한참 작게 오기도 한다.
  → 받은 뒤 **내용 크기를 잰다** (`arttool trim --in raw --out t --report t.json` 의 `size` · `offset`).
- **방향은 참고 그림이 통째로 정한다.** 글로 「3/4 view」를 적어도 첫 참고 그림이 정면이면 다 정면이다.
- **타일 묶음 도구(`create_topdown_tileset` · `create_tiles_pro`)는 색과 이음매를 못 믿는다.** 색을 지켜야 하면 `create_image_pro_flash` 에 hex 를 적어 뽑고, 이음매는 `arttool tile seam` 으로 잰다. 바닥 타일은 PIL 이 낫다.
- **「~ 하지 마라」는 잘 안 듣는다.** 덮일 밑판(맨몸 · 빈 선반)은 AI 가 엉뚱한 것을 그려 넣는다 — PIL 로 메우는 쪽이 낫다.
- 화풍 그림은 캔버스보다 크면 거절된다 → 캔버스 크기 투명 판에 채워 넣는다. 32색으로 줄인 PNG 는 base64 가 작아 인자로 싣기 좋다.
- 실내 정면 배경 글머리 : `flat 2D side-scroller game background, flat elevation of one back wall only, no side walls, no ceiling, no perspective`. 「front view」만으로는 아이소메트릭 방이 섞여 온다.
- 자리를 번호 매겨 적으면(「왼쪽 70% 는 계산대 · 오른쪽 끝은 문 · 아래 3분의 1 은 빈 바닥」) 배치를 잘 따른다.

## 4. 기본체 + inpaint 로 겹 얻기

**겹은 나중에 떼지 말고 처음부터 갖고 간다.** inpaint 는 마스크 밖을 안 바꾸므로 「기본체와 다른 칸」이 곧 그 겹이다.

1. 기본체 1장을 뽑는다 (맨몸 또는 기본 옷). `base.png` 로 저장.
2. 겹마다 마스크를 정한다.
   - 템플릿 마스크 : `work/guide/char_parts_mask_hair.png` 같은 것.
   - **「이 색 칸만」 마스크** — 네모 마스크는 앞머리 · 단발 밑단을 일자로 자른다. 빼야 할 칸이 눈 · 입이면 그 색 칸만 :
     `arttool layers mask --in base.png --colors #2B2233,#C9645A --grow 1 --out mask_face.png`
3. 겹마다 inpaint → 받은 그림을 **겹 이름으로** 저장 (`inpainted/hair.png` · `inpainted/cloth_top.png`).
   색을 바꿔 쓸 파츠는 살색과 먼 색(예 : 진한 파랑)으로 뽑으면 나중에 색상만으로 가를 수 있다.
4. 겹 떼기 :
   ```
   arttool layers diff --base base.png --in inpainted --out set --template work/guide/template.json --carve report --report diff.json
   ```
   - `body` 겹 = 기본체. 나머지 = 기본체와 다른 칸.
   - 보고 `outside_mask` 가 0 이 아니면 마스크 밖이 바뀐 것이다(inpaint 가 아니었거나 다른 그림).
   - 파츠를 입히며 **기본체 윤곽(정수리 한 줄 · 어깨선)을 깎는** 일이 잦다 → 보고 `carved`.
     `--carve report`(기본) 본체 그대로 · `common` 모든 겹이 깎은 칸만 본체에서 뺀다 · `apply` 하나라도 깎은 칸은 다 뺀다.
     겹을 하나씩 켜 보며 본체가 삐져나오면 `common` 부터 해 본다.
5. 보기 · 검사 :
   ```
   arttool layers view --in set --each --scale 8 --out view.png
   arttool layers check --in set --template work/guide/template.json --report lc.json
   ```
   `layer_poke`(아래 겹이 1칸 삐짐) · `layer_exclusive`(얼굴과 머리카락이 같은 칸) · `layer_mask`(마스크 밖) 를 본다.
   나눈 겹에 **붙어 있지 않은 자잘한 조각**(옷 색이 머리 겹으로 샌 점)이 남기 쉽다 — `--each` 판에서 겹 하나씩 본다.
6. 한 장으로 받은 그림을 나눌 때는 `arttool split` 에 템플릿의 `split.json` 초안을 준다.

## 5. 받은 그림 손질 — `intake` 한 줄

```
arttool intake --in raw --out clean --sheet sheet.png --report intake.json
arttool intake --in raw --out clean --no-trim --template work/guide/template.json --report intake.json   # 템플릿 크기로 뽑은 그림
```

차례는 cutout(배경 지우기) → trim(여백 걷기) → check → sheet. 원본은 안 건드린다(`--out` 이 `--in` 과 겹치면 종료 2). 그림마다 고르는 것은 옵션 몇 개뿐이다.

- **배경 그림(화면을 꽉 채운 그림)은 cutout 을 건너뛴다** — 경고 `cutout.background_kept` 만 남는다. 배경과 캐릭터를 한 폴더에 섞어 넣어도 된다.
- **check 가 `fail` 이어도 `--sheet` 비교판은 만든다.** 보고는 `status: fail` · `failed_step: check` · 종료 4 그대로라, 비교판을 열어 무엇이 틀렸는지 본다.
- 이번에 쓴 파일만 검수한다(보고 `checked_files`). 같은 `--out` 에 다시 돌려도 지난 판 그림이 섞이지 않는다.

| 옵션 | 언제 |
| --- | --- |
| `--key edge` (기본) · `corner` · `#RRGGBB` | 바탕이 네 변에서 이어지면 edge, 모서리만 바탕이면 corner, 그림 속 같은 색 구멍까지 지우려면 hex |
| `--tol N` (기본 10) | 바탕이 살짝 얼룩지면 올린다 |
| `--shave N` | 가장자리에 흰 띠가 둘러 왔을 때 바깥 N 칸을 먼저 깎는다 |
| `--pad N` · `--square` | 걷은 뒤 둘레 여백 · 정사각 |
| `--no-trim` | **템플릿 크기에 맞춰 뽑은 그림.** 걷으면 크기가 줄어 `must.canvas` 에 걸린다 |
| `--template t.json` | 템플릿 대조까지 |

보고의 `status` · `failed_step` · `warnings`, 그리고 `steps.check.must_failed` 를 본다. 「90% 넘게 지웠다」(`cutout.erased_most`) 경고는 작은 그림이면 정상이고, 큰 그림이면 키가 그림 색이었다는 뜻이다. 경고일 뿐 멈추지 않는다.

## 6. 흔한 사고와 잡는 명령

| 사고 | 증상 | 잡는 법 |
| --- | --- | --- |
| **흰 띠 · 흰 바탕** | `no_background` 를 줘도 불투명 흰 바탕, 또는 위아래 수십 줄 흰 띠 | `intake --key corner --shave 2`. 띠 줄 수는 `trim --report` 의 `offset` 으로 잰다 |
| **±2 잡색** | 낱색이 수백 개 (같은 색이 RGB ±2 로 흔들림) | `check` 의 `near_colors` 가 합칠 쌍을 낸다. 화풍을 뽑을 때 `style extract` 는 알아서 합친다 |
| **도트 굵기 섞임** | 크기가 다른 그림을 키워 한 화면에 섞음 | `check` 의 `integer_scale` · `must.scale`. 그림마다 그 크기로 다시 뽑는다 |
| **반투명 가장자리** | 줄이거나 편집한 그림의 가장자리 알파가 중간값 | `check` 의 `alpha`(실패) · `must.alpha`. `cutout` 으로 다시 따거나 PIL 로 알파를 0/255 로 |
| 외곽선 색이 다름 | 「dark brown outline」을 적어도 검은 선 | `check` 의 `outline` 판정. 프로필 `style.outline` 을 정해 둔다 |
| 덜 끝난 그림 받음 | 내려받은 파일이 62바이트 오류 글 | 파일 크기를 본다. 깨진 PNG 는 `intake` 가 못 연다 |

## 7. 일 다루기

- **`wait_for_jobs` 는 계정 전체의 일을 본다.** 다른 세션 일이 끝나도 깨어난다. **내 job id 를 적어 두고 그것만 `get_image`** 한다.
- 동시 작업은 계정 전체로 10개가 상한이다 (rate limit 이 나면 끝난 뒤 다시 건다).
- `get_image` 가 떨어뜨린 파일은 이름이 임의다. **받는 즉시 뜻 있는 이름으로 복사**한다 (`raw/hair.png`).
- 앞 판의 내려받기 주소를 다음 inpaint · 편집의 그림 인자로 그대로 넘길 수 있다. 갤러리 id 로는 안 될 때가 있다(job id 로 받는다).
- `wait_for_jobs` 의 `eta` 는 한참 부풀어 있다. eta 를 보고 일을 접지 않는다.
- 서버 사정으로 한 판이 실패하면 같은 인자로 다시 돌린다.
- 값 : 작은 아이콘 한 장 5회 남짓 · 큰 그림(`create_image_pro`) 40회. 많이 뽑기 전에 `get_balance` 를 본다.
