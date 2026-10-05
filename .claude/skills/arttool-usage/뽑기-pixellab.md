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
- 화풍 그림은 캔버스보다 크면 거절된다 → `arttool style ref --in a.png --canvas WxH --out ref.png --b64 ref.txt` 가 잘라 · 32색으로 줄여 · base64 를 파일로 낸다.
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
   겹을 다 합친 한 장도 검사하려면 세 줄이다 (반투명 · 색 수 · 도트 굵기 · 떨어진 덩이) :
   ```
   arttool layers export --in set --out flat --flat
   arttool check --in flat --report flat.json          # integer_scale · isolated · color_cap 경고를 본다
   arttool sheet --in flat --kinds zoom --scale 4 --label --out flat_x4.png
   ```
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
| **흰 띠 · 흰 바탕** | `no_background` 를 줘도 불투명 흰 바탕, 또는 위아래 수십 줄 흰 띠 | `intake --key corner --shave 2`. 불투명 배경의 띠 줄 수 · 이을 줄은 `bands --mark` 로 잰다 |
| **±2 잡색** | 낱색이 수백 개 (같은 색이 RGB ±2 로 흔들림) | `check` 의 `near_colors` 가 합칠 쌍을 낸다. 화풍을 뽑을 때 `style extract` 는 알아서 합친다 |
| **도트 굵기 섞임** | 크기가 다른 그림을 키워 한 화면에 섞음 | `check` 의 `integer_scale` · `must.scale`. 그림마다 그 크기로 다시 뽑는다 |
| **반투명 가장자리** | 줄이거나 편집한 그림의 가장자리 알파가 중간값 | `check` 의 `alpha`(실패) · `must.alpha`. `cutout` 으로 다시 따거나 PIL 로 알파를 0/255 로 |
| 외곽선 색이 다름 | 「dark brown outline」을 적어도 검은 선 | `check` 의 `outline` 판정. 프로필 `style.outline` 을 정해 둔다 |
| 덜 끝난 그림 받음 | 내려받은 파일이 62바이트 오류 글 | 파일 크기를 본다. 깨진 PNG 는 `intake` 가 못 연다 |

## 7. 일 다루기

- **`wait_for_jobs` 는 계정 전체의 일을 본다.** 다른 세션 일이 끝나도 깨어난다. **내 job id 를 적어 두고 그것만 `get_image`** 한다.
- 동시 작업은 계정 전체로 10개가 상한이다 (rate limit 이 나면 끝난 뒤 다시 건다).
- `get_image` 가 떨어뜨린 파일은 이름이 임의다. **받는 즉시 뜻 있는 이름으로 복사**한다 (`raw/hair.png`).
- 앞 판의 내려받기 주소를 다음 inpaint · 편집의 그림 인자로 그대로 넘길 수 있다. 내려받기 주소는 job id 로만 된다(갤러리 id 로 만든 주소는 404). 갤러리 id 는 `source_image_id` 로 쓴다 — 8-2.
- `wait_for_jobs` 의 `eta` 는 한참 부풀어 있다. eta 를 보고 일을 접지 않는다.
- 서버 사정으로 한 판이 실패하면 같은 인자로 다시 돌린다.
- 값 : 작은 아이콘 한 장 5회 남짓 · 큰 그림(`create_image_pro`) 40회. 많이 뽑기 전에 `get_balance` 를 본다.

## 8. 더 모은 요령 (10-03 ~ 04 피드백)

### 8-1. 크기 · 캔버스

| 요령 | 메모 |
| --- | --- |
| **`create_image_pro` 크기 한도는 비율마다 다르다** | 받은 크기 : 508×428 · 540×440 · 540×360 · 576×384 · 272×480 · 272×608. 거절 : 540×480 (「too large for this aspect ratio (max 512x512)」). 도구 설명엔 512×512 · 16:9 는 688×384 만 있다 |
| **받아들여진 뒤 취소해도 값이 든다** | 40회 판을 바로 취소해도 25회가 빠졌다. 거절은 공짜다 → 크기 시험도 진짜 프롬프트로 건다 |
| 그림이 캔버스보다 작게 오거나 흰 띠가 둘러 온다 | 「fills the whole canvas edge to edge, no border」를 넣으면 대개 꽉 찬다 (늘 그렇진 않다 — 받은 뒤 `trim --report` 로 잰다) |
| 아래끝에서 잘려 온다 (`create_image_pro` 큰 물건) | 처음부터 위아래 여백을 넉넉히 준다. 잘린 뒤 캔버스를 늘려 inpaint 로 닫는 것보다 싸다 |
| `create_image_pro_flash` 는 캔버스를 키워도 캐릭터가 안 커진다 | 조금 큰 판이 필요하면 **기존 그림을 NEAREST 로 키워 `edit_image_pro_flash` 에 「이 크기의 1px 도트로 다시」**. 같은 사람 · 자세로 결만 고와진다. 물건은 화풍 그림 + 「same machine, bigger」 도 됐다 |
| 상태 조각(서랍 열림 등)을 한 캔버스에 맞출 때 | 편집이 물건을 아래로 밀 수 있다 — 피벗 둘레에 여유를 둔다 |
| 큰 배경을 조각으로 뽑아 이을 때 | **몰딩 · 걸레받이 같은 가로 나무 띠에서** 잇는다. 프롬프트에 「몰딩이 맨 위/아래 가장자리를 따라 곧게」를 넣어 이을 자리를 미리 만든다. 이을 줄은 `bands`, 잇기는 `stitch`. 위로만 늘리면 되면 `extend canvas` |
| 이어 붙는 바탕 (바탕 있는 256 그림) | 「seamless」 글로는 네 변이 안 이어진다. **반 칸 밀기 → 가운데 십자 16px inpaint** 가 통했다. `arttool tile offset --in g.png --out s.png --mask cross.png` 가 민 그림과 가림판을 낸다. 맨 바깥 1줄에 테두리가 와도 이 길로 지워진다 |

### 8-2. 그림 넘기기 — id · 주소 · base64

| 넘길 것 | 되는 길 | 안 되는 길 |
| --- | --- | --- |
| 앞서 뽑은 그림 | `source_image_id` (판이 **끝난 뒤**). 갤러리 그림은 `list_images` 의 `gallery:<uuid>` 에서 앞말을 뗀 uuid | 판이 끝나기 전 id → 「not found」 |
| 앞 판 결과를 다음 판에 | 내려받기 주소 `https://api.pixellab.ai/mcp/images/<job_id>/download` 를 `image_url` · `style_image_url` · `reference_images` 에 그대로 | — |
| workbench(`pixelart_workbench`) 결과 | `https://api.pixellab.ai/mcp/pixel-tools/<id>/image.png` 를 `image_url` 로 (404 가 난 날도 있다 → 갤러리 id 로) | workbench 결과 id 를 `source_image_id` 로 |
| 내 PNG | **팔레트 PNG(16~40색)로 줄여 base64.** 3~9KB 면 통과. `arttool style ref … --b64 ref.txt` 가 만든다(12KB 넘으면 경고) | 큰 RGBA PNG(57KB 급) → 잘려서 「Could not decode image」 · 「keyframe image is incomplete」. 문구에 까닭이 안 나온다 |

- 화풍 그림은 캔버스 안에 들어가야 한다 — 큰 그림은 **필요한 부분만 캔버스 크기 이하로 잘라** 넣는다(256 풀밭 → 64×64 1.4KB). 작은 화풍 그림은 가운데 놓인다.
- 돌려받은 `image_id` 와 `source_image_id` 가 같은 값으로 올 때가 있다. 원본으로 다시 편집하려면 원본의 id · 주소를 따로 적어 둔다.

### 8-3. 프롬프트 글귀 — 통한 것

| 하고 싶은 것 | 글귀 · 설정 |
| --- | --- |
| 화풍 그림의 얼룩 · 장식을 덜 따라오게 | `style_options` 에서 **detail · shading 을 끈다.** 색 · 외곽선은 따라오고 장식만 준다(80색 → 38색). 「팔레트 복사」를 끄고 외곽선 · 음영 · 결만 따라가게 하면 화풍 그림의 구멍 · 선반이 복사되지 않는다 |
| 천장 · 윗부분만 | **천장만 있는 조각을 화풍 그림(`style_image_url`)으로** + 「ONLY the top part … Nothing else: no …」. 벽 그림을 `reference_images` 로 주면 방 전체가 다시 나온다 |
| 한 색 면 (하늘) | 「flat even color #D4EEFA, no gradient」 → 정말 한 색 |
| 얼룩 없는 바닥 | 「Even, uniform lighting everywhere: no light spots, no bright circles」 + 앞서 뽑은 바닥 조각을 화풍 그림으로 (그래도 둥근 얼룩이 오는 판이 있다) |
| 방향 돌리기 (`edit_image_pro_flash`) | 「Same character, same size, same art style, same outfit (옷을 낱낱이), same hair. Change only the pose: …」 |
| 표정 inpaint | 「keep eye color」를 꼭 넣는다 (안 넣으면 눈동자 색이 바뀐다) |
| 곱슬머리 | 「round scallop bumps (not spikes)」 · 「closed solid dark 1-pixel outline」 |
| 색 입히기용 원본 | 「흰색 ~ 밝은 회색으로」 시키면 그대로 온다 (곱하기 색 겹) |

### 8-4. 편집 · inpaint · 움직임의 버릇

- **`edit_image_pro_flash` 는 모든 점을 조금씩 다시 칠한다** (「pixel for pixel」이라 써도). 자리 · 모양은 남는다. 그래서 살 위의 작은 부위(얼굴만)를 떼면 딸려 온 살색이 달라 네모로 보인다 → 머리통 전체를 한 겹으로 뗀다.
- 겹을 얻는 다른 길 : `edit_image_pro_flash` 로 「입히기 → 그 파츠만 남기고 나머지 투명 · 잘린 자리 외곽선을 닫아라」 두 번. 가장자리 외곽선까지 그려 준다.
- inpaint 의 **「only changes」 출력은 바뀐 점이 아니라 마스크 칸 전체**를 준다. 겹 떼기에는 일반 출력 + `layers diff` 가 깨끗하다.
- 머리 inpaint 가 마스크 안의 귀 · 뺨 · 깃까지 다시 그린다 → 차이를 머리 겹으로 쓰면 색 바꿀 때 뺨이 물든다. 마스크를 「이 색 칸만」(4절 2번)으로 좁힌다.
- `no_background=true` 는 밝은 면(크림 종이 · 밝은 윗판 줄)까지 투명으로 뚫는다. 그런 그림은 `false` 로 받아 `arttool intake`(cutout)로 지운다. 「solid teal background」 같은 바탕색 지시도 흰 바탕으로 올 때가 많다.
- inpaint 로 고친 띠는 밝기가 +2 쯤 다르게 온다. 눈엔 안 보여도 `tile seam` 에는 잡힐 수 있다.
- `animate_image` 는 싸고(6~7회) 받침 자리를 지킨다. 다만 창 · 유리 속에 덩이를 그려 넣는다(「stays plain」을 적어도) → 프레임마다 그 칸을 쉬는 그림으로 덮는 손질이 필요하다.
- **도는 움직임(한 바퀴 돌기)은 `animate_image_pixminimax`** 로 뽑는다. `animate_image` 는 4분의 1 바퀴 뒤 뭉치거나 반쯤 돌다 되돌아왔다. pixminimax 는 16프레임에 360° 를 돌고 끝 그림이 첫 그림 자세로 돌아왔다(값 2회).
  - pixminimax 는 색을 바꾼다 — 첫 두 장만 원래 옅은 색이고 셋째 장부터 진해진다. **첫 1~2장은 버리고, 색은 다시 입힌다.** 빈틈에 회색 `#80807F` 을 채우는 프레임도 있다 → `arttool cutout --in raw --out cut --key #80807F` 로 지운다.
  - **꽉 찬 밑그림을 주면 꽉 찬 채로 돈다.** 빈틈 있는 밑그림을 주면 빈틈이 프레임마다 따라온다 — 밑그림이 정한다.
- 같은 씨앗(seed)을 다시 쓰면 분위기가 이어진다.

### 8-5. 값 · 일

- `create_image_pro_flash` 맞춤 크기는 판당 9회로 고정이었다. 미리 보려면 `get_pro_flash_capabilities`.
- **실제 차감이 어림보다 1.7배쯤 컸다** (보고는 `pricing_provisional` 뿐이고, 잔액은 다른 세션과 같이 줄어든다). 예산은 넉넉히 잡는다.
- `search_knowledge` 에는 그림 요령이 없다(게임 엔진 지식뿐). 도구 설명을 직접 읽는다.
