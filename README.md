# ArtTool

게임에 들어가는 **2D 그림**(스프라이트·타일·UI)을 규격에 맞추고, 앵커를 뽑고, 검수해서
Unity 가 바로 쓸 데이터로 굽는 툴이다. 그림을 그려 주는 툴은 아니다.
**그림 뽑기는 PixelLab MCP(또는 PIL · 손그림)로 하고, ArtTool 은 그 뒤 손질 · 규격 · 검수를 맡는다. ArtTool 이 PixelLab 을 부르지는 않는다.**

**상태 : 스프라이트 · 타일 · UI 1차 끝 + 2026-10-04 개선 판(손질 · 비교판 · 경고 검사 · 템플릿 · 화풍 · 겹) 구현 · 보강 끝, 커밋 · 푸시 끝(`c5fa2ec`) + 2026-10-04 피드백 후속 판(새 명령 10개 · 옵션 2개) 구현 · 배선 · 실물 확인 끝, 커밋 · 푸시 끝(`e0f9c9e`) + 2026-10-05 피드백 판(외곽선 accept · `reline --from` · 보고 칸 더함) · `merge-colors` 커밋 끝(`cc41deb`) + 2026-10-05 `--dry-run` 판(받는 명령 표 · 손질 넷 지원) 커밋 · 푸시 끝(`2c28eb3`) + 2026-10-06 `--dry-run` 넓히기(지원 7 → 24, `intake` 포함) 구현 끝(시험 1655) + 2026-10-06 `merge-colors --clean` · `hue_jump` 어두운 색 헛경고 고침(시험 1709), 둘 다 커밋 전**

## 설치

이 폴더 안에 가상환경을 만들고 거기에만 깐다. 전역 pip 는 안 쓴다.
**파이썬 3.11 이상이 없으면 명령이 하나도 안 돈다.**

### 서브모듈로 붙였을 때 (한 줄)

```
powershell -NoProfile -ExecutionPolicy Bypass -File <서브모듈경로>\ArtTool\setup.ps1
```

`-ExecutionPolicy Bypass` 가 있어야 한다. 실행 정책이 `Restricted` 인 PC 에서는 없으면 스크립트가 아예 안 뜬다.
끝까지 되면 `.venv\.setup-stamp` 에 그때 시각을 적는다 — 게임 저장소의 점검 스크립트가 이 표식으로 낡음을 잰다.

`.venv` 를 만들고 깔고 연기 시험까지 한다. **받은 직후와 서브모듈을 갱신한 뒤마다** 한 번씩 돌린다
(서브모듈 사본에는 `.venv` 가 안 딸려 온다). 그다음부터 부르는 법은 `<경로>\.venv\Scripts\arttool …` 다.

### 손으로 할 때

**부르는 자리에 따라 명령 앞이 다르다.** 두 벌을 다 적어 둔다.

ArtTool 저장소 단독일 때 (저장소 뿌리에서) :

```
python -m venv .venv
.venv/Scripts/python -m pip install pillow numpy pyyaml pytest
.venv/Scripts/python -m pip install -e .
.venv/Scripts/python -m pytest tests -q
```

스튜디오 저장소(Officina)에 서브모듈로 물린 상태일 때 (스튜디오 뿌리에서) :

```
python -m venv ArtTool/.venv
ArtTool/.venv/Scripts/python -m pip install pillow numpy pyyaml pytest
ArtTool/.venv/Scripts/python -m pip install -e ArtTool
ArtTool/.venv/Scripts/python -m pytest ArtTool/tests -q
```

시험은 **1548개가 다 통과해야** 한다.

`profiles/` · `palettes/` 는 이 폴더를 기준으로 찾는다. 다른 자리에 두려면 `ARTTOOL_HOME` 을 정한다.

## 어느 길로 쓰나

**길이 둘이다.** 게임 쪽이 낱장 PNG 를 자동으로 들여오는 임포터를 갖고 있으면 아틀라스를 구울 값이 없다.
그때는 「낱장 길」로 간다.

| | 아틀라스 길 | 낱장 길 |
| --- | --- | --- |
| 언제 | 애니 프레임을 한 아틀라스로 묶어 쓸 때 | 게임 쪽에 낱장 자동 임포터가 있을 때 |
| 순서 | `normalize` → `anchors` → `check` → `bake` | (겹으로 색 변종을 만들 때 `split` → `recolor` →) `check --in 낱장폴더 [--no-ramps]` · `ui icons --in 낱장폴더 [--fit N]` → `ui check` |
| 건너뛰는 것 | — | `bake` · `ui bake` · `tile blob/place/ldtk` |

**낱장 길에서는 baseline · bbox 흔들림 규칙이 안 돈다.** 프레임 규격이 없어 잴 기준이 없다.
`check` 보고에 `"mode": "loose"` 가 박히고 두 규칙은 「낱장 모드라 건너뛴다」로 지나가며
`"skipped": ["baseline", "bbox_drift"]` 가 같이 박힌다. 도는 것은 색 수(장마다) · 램프 밖 색 · 반투명 셋이다.

**`frames.json` 이 없는 폴더를 주면 말없이 낱장 모드로 내려간다.** 그것이 앞 단계(`normalize`)가 실패한
판일 수도 있어, 낱장으로 들어갈 때 「frames.json 이 없어 낱장 모드로 본다」를 stderr 에 찍는다.
그 보고로는 `bake` 가 `--force` 없이 안 돈다.

**시안(게임에 안 넣는 그림 · 목업)을 눈으로 고를 땐 `sheet` 비교판을 쓴다.** 꼴끼리 경고 수를 견줄 땐 시안에 `check` 를 돌려도 된다.

**`check` 는 준 폴더 바로 아래 `.png` 만 본다.** 하위 폴더는 안 들어가고, 확장자는 대소문자를 안 가린다. (`--profile-map` 을 주면 하위 폴더까지 내려간다 — 명령안내 15절.)
(`ui icons` 의 낱장 폴더도 같다.)

**아이콘에 `ui check` 가 실제로 보는 것은 셋뿐이다** — 반투명 · (켰다면) 램프 밖 색 · 가족 안에서 크기가 섞였는지(경고).
최소 크기 · 홀수 · 상태 갖춤은 **프레임(9패치) 전용**이라 아이콘은 그냥 지나간다 (`ui/check_ui.py:150-154`).

**팔레트가 아직 미정이면** `palette.ramps_file: ""` 과 `ui.check.palette_strict: false` 로 둔다.
프로필에 램프 파일을 적어 놓고 파일이 없으면 그것은 실패로 잡는다 (오타를 놓치지 않으려는 것이다).
한 판만 램프를 빼고 싶으면 `check --no-ramps` 를 쓴다 — 보고의 `skipped` 에 `ramp_colors` 가 박히고
그 보고로는 `--force` 없이 `bake` 가 안 된다.

**프로필에서 램프를 비운 것(`ramps_file: ""`)과 `--no-ramps` 는 다르다.** 앞은 「설정상 없는 검사」라
`skipped` 에 안 들어가고 `bake` 도 그냥 지나간다. 뒤는 **있는 검사를 한 판만 끈 것**이라 `bake` 가 `--force` 를 요구한다.

게임 저장소에 둘 최소 프로필은 이 정도면 된다.

```yaml
name: mozzi
preset: topdown_action
canvas: { frame: [64, 64], baseline_y: 50, center_x: 31.5 }
palette: { ramps_file: "" }          # 팔레트 미정 : 램프 규칙이 꺼진다
ui:
  icon:  { sizes: [28] }             # 낱장 아이콘 한 변. 이 밖 크기는 거절한다
  check: { palette_strict: false }
```

## 명령

```
arttool profile show   --profile slime_demo
arttool normalize      --profile P --in raw/ --out build/
arttool anchors        --profile P --in build/ --rig blob --from marker --markers markers/ --out build/anchors.json
arttool check          --profile P --in build/ --report build/check.json [--no-ramps]
arttool bake           --profile P --in build/ --out Unity/Art/ --namespace Game.Art
arttool layers compose --profile P --rig humanoid_lpc --in parts/ --out build/
arttool split          --in clean/customer.png --spec split.json --out layers/ [--rig R] [--min-piece 8]   (--list-colors 면 색 목록만)
arttool recolor        --in layers/ --spec recolor.json --out Unity/Art/Customer/ [--sheet preview.png --scale 2]
arttool tile blob      --profile P --in template6/ --out tiles47/
arttool tile place     --profile P --tileset tiles47/tileset.json --rules rules.json --size 64x64 --out map/
arttool tile ldtk      --map map/map.json --tileset tiles47/tileset.json --out map/level.ldtk
arttool tile preview   --layout layout.json --in tiles/ --out preview.png [--scale 2]
arttool tile inspect   --in tiles/ --report inspect.json [--size 32]
arttool tile seam      --in tiles/ --report seam.json [--sheet seams.png --scale 2] [--pairs] [--k 2.0]
arttool ui frame       --profile P --kind panel --size 16x16 --out build/ui/
arttool ui import      --profile P --in raw/ui/ --out build/ui/
arttool ui icons       --profile P --in raw/icons.png --cell 16 --out build/ui/   (--in 이 폴더면 낱장 들이기 · --fit N)
arttool ui check       --profile P --in build/ui/ --report build/ui/check.json [--manifest Unity/UI/ui_manifest.json]
arttool ui bake        --profile P --in build/ui/ --out Unity/UI/ --namespace Game.UI
arttool ui screen      --profile P --spec screens/pause_menu.json --out Unity/UI/
arttool ui font        --profile P --scan-root . --scan Text --out Unity/UI/Fonts/charset.txt
arttool provider list
arttool provider make  --kind character --spec req.json --out gen/ --dry-run
```

### 개선 판 명령 (2026-10-04)

자세한 인자 · 보고 칸 · 대표 문턱은 **`Docs/Guide/명령안내.md`** 에 있다. 여기는 한 줄씩만.

| 명령 | 하는 일 |
| --- | --- |
| `cutout --in raw/ --out cut/ [--key edge\|corner\|#hex] [--tol 10] [--shave N]` | 바탕 지우기. `--shave` 면 깎아 낸 고리에서 바탕 색을 고른다 |
| `trim --in raw/ --out t/ [--pad N] [--square] [--common]` | 여백 걷기. `--common` 은 폴더에 bbox 하나(크기가 섞이면 종료 2) |
| `trim … --canvas WxH [--anchor bottom] [--margin N]` | 자른 그림을 W×H 투명 판에 다시 깐다. `--pad` · `--square` 와 같이 못 쓴다 (2026-10-06) |
| `intake --in raw/ --out clean/ [--sheet s.png] [--template t.json] [--no-trim]` | cutout → trim → check → sheet 한 번에. 배경 그림은 cutout 을 건너뛴다. 이번에 쓴 파일만 검수 |
| `sheet --in a.png b/ --out s.png [--kinds zoom,silhouette,colors4,blur,tile] [--label]` | 사람이 보는 비교판. `--scale` 은 64 까지 |
| `sheet --in f1.png f2.png --out s.png --strip` | 여백 0 · 딱지 없음 · 배율 1 · 투명 바탕으로 `--in` 순서대로 가로로 붙인다. `--kinds` · `--scale` · `--grid` 와 같이 못 쓴다 (2026-10-06) |
| `sheet … --kinds zoom,fit:24,fit:16` | `fit:N` = 긴 변을 N 으로 nearest 줄인 모습(딱지 「맞춤 N」). N 이 더 크면 원본 그대로 + 경고 `fit_upscale` (2026-10-06) |
| `check … [--no-warn] [--mode auto\|sprite\|background] [--template t.json] [--known k.json] [--baseline base.json] [--fail-on-new]` | 실패 규칙 다섯 + **경고 여덟**(`integer_scale` · `outline` · `isolated` · `color_cap` · `near_colors` · `ramp_shape` · `loop_seam` · `odd_size`). `odd_size` 는 피벗이 반 픽셀에 놓일 때 — `trim --canvas` 로 짝수로 맞춘다 (2026-10-06) |
| `check … --known k.json --baseline base.json --fail-on-new` | 알고 두는 경고를 `known` 으로 옮기고 새 경고(`new_warnings`)만 남긴다. `--fail-on-new` 로 새 경고가 있으면 종료 4. `--no-warn` 과 같이 주면 종료 2. 낡은 항목은 info `check.known_stale` (2026-10-06) |
| `measure shape --in a.png (--at x,y \| --color #hex) [--tol N] [--report s.json]` | 한 색 덩이의 가운데 · 반지름(`r` · `r_max`) · 넓이 · 상자 · 원다움을 잰다. 파일을 안 쓴다. 경고 `measure.not_round` · `measure.none`(종료 4) (2026-10-06) |
| `mask --from-shape s.json (--size w,h \| --like a.png) [--r round\|max\|수] [--invert] --out m.png` | `measure shape` 보고로 흰 원 가림판(바깥은 투명)을 만든다. 경고 `mask.clipped` (2026-10-06) |
| `check --in A B … --report c.json` | 폴더 여럿을 한 보고로. 둘 이상일 때만 `inputs` · 줄마다 `input` · `where` 앞 `<딱지>/` 가 붙는다 (2026-10-06) |
| `check --in 폴더 --profile-map 지도.yaml` | 그림마다 다른 프로필. 줄(`match` 글롭 → `profile` · `set`)을 위에서부터 처음 맞는 하나, 안 맞으면 `default`. 보고에 `profile_map` · 줄마다 `profile`. 낱장 검수만, `--profile` · `--directions` 와 같이 못 쓴다. 경고 `profile_map.rule_unused` (2026-10-06) |
| `palette check (--profile P \| --ramps r.json) [--report p.json]` | 그림 없이 램프 파일만 보고 `ramp_shape` 판정. 걸려도 종료 0. 프로필 `check.warn.ramp_shape.report: once` 면 `check` 보고 맨 위 `palette` 칸에 한 번만 실린다 (2026-10-06) |
| 환경변수 `ARTTOOL_PALETTES` | 팔레트 뿌리(절대경로 · 있는 폴더). 프로필 램프 경로를 `$palettes/…` 로 쓴다. 템플릿의 램프 절대경로는 프로필 폴더 · 툴 폴더 · 이 뿌리 아래만 믿고, 아니면 경고 `template.ramps_outside` (2026-10-06) |
| `color_cap.table_mode: replace` | 프로필의 색 한도 표를 기본 표에 겹치지 않고 통째로 바꾼다(기본 `merge`). `--set` 으로는 안 먹는다. `profile show` 가 표를 읽기 쉬운 줄로 보인다 (2026-10-06) |
| `sheet … --scale per` | 그림(줄)마다 배율을 따로 `auto`. 줄 딱지 끝 ` · ×N`, 보고 `items[].scale`. `--strip` 과 같이 못 쓴다 (2026-10-06) |
| `style extract --in refs/ --out style/ [--by-folder] [--max-colors 64] [--force]` | 기준 그림 → 팔레트 · 견본 · 프로필 조각 · 보고. **종류별(`--by-folder`)이 권장 길** |
| `template list` · `show <이름> [--size N\|WxH] [--preset P] [--base #hex] [--material M]` · `render … --out guide/ [--over a.png]` | 그리기 전 밑판(가이드 겹 · 마스크 · 프롬프트 · 순서). **템플릿 15개** |
| `layers compose\|diff\|mask\|view\|check\|export\|fill` | 겹 묶음 명령. `check --cover mask.png` 는 가림판 안 빈 칸을 실패로, `fill --mask m.png --nearest a,b --out set2/` 는 그 빈 칸을 가까운 겹에 채운다(명령안내 17절). `layers.json` 버전 2 는 `meta` · 작은 겹 `size`/`offset`. `diff --carve report\|common\|apply`. 옛 `layers --profile …` 줄은 `layers compose` 로 |
| `ui preview --in panel.png --border N\|L,B,R,T --size WxH` | 안내선 없는 9조각 늘려 보기 |
| `tile seam` | 새 칸 `bad_px` · `bad_px_min` — 이음 줄에서 크게 다른 칸이 한 줄의 15%(최소 2px) 미만이면 통과 |

### 피드백 후속 판 명령 (2026-10-04)

받은 그림을 사람이 PIL 스크립트로 손질하던 자리를 명령으로 옮겼다. 자세한 것은 `Docs/Guide/명령안내.md` 9~12절.

| 명령 | 하는 일 |
| --- | --- |
| `style ref --in a.png --canvas 128x128 --out ref.png [--crop X,Y,W,H] [--colors 32] [--b64 ref.txt]` | PixelLab 화풍 그림 준비 — 캔버스로 자르기 · 색 줄이기 · 팔레트 PNG · base64 파일 |
| `bands --in raw.png [--axis y] [--top 8] [--mark m.png]` | 흰 띠 · 몰딩 줄(조각을 이을 자리) 찾기 |
| `stitch --in top.png:0-180 mid.png:20-400 floor.png:12- --out wall.png [--axis y]` | 조각 잇기. 이음 차 24 넘으면 경고. 무늬 이어 넓히기는 `--in a.png:0-40 a.png:20-40 a.png:20-40 --axis x` |
| `tile offset --in grass.png --out shifted.png --mask cross.png [--band 16]` | 반 칸 밀기 + 가운데 십자 가림판 (inpaint 로 이음매 지우기) |
| `extend period --in fence.png [--axis x] [--tile 32] [--out unit.png] [--fit N]` | 되풀이 단위 찾기 · 타일 배수 검사 · 한 단위 잘라 맞추기 |
| `extend ring --in ring.png --border N\|L,B,R,T --size WxH --out o.png [--snap]` | 한 바퀴 그림 늘리기. 단위가 잘리면 경고, `--snap` 이면 맞는 크기로 |
| `extend canvas --in bg.png --size WxH --out o.png [--anchor bottom] [--band 1]` | 배경 늘리기 — 가장자리 줄 · 띠를 바깥으로 되풀이 |
| `reline --in raw/ --out o/ [--color #hex] [--pick dark\|all] [--scope ring\|colors] [--tol 40]` | 외곽선을 한 색으로 |
| `reline … [--depth N] [--color-dark #hex [--dark-gap N]]` | `--depth` 는 2px 선의 안쪽 줄까지(1~8, `--scope colors` 와 못 씀), `--color-dark` 는 면과 밝기가 비슷해 묻힌 선 칸만 둘째 색 (2026-10-06) |
| `reline … --from #hex[,#hex…]` | 바꿀 선 색을 직접 준다 — 고리 칸 중 그 색만(`--scope colors` 면 그림 전체의 그 색). `--pick` · `--tol` 과 같이 못 쓴다 (2026-10-05) |
| `shift --in raw/ --out o/ [--hue D] [--sat S] [--light L] [--pick #hex,…] [--dry-run]` | 색상 · 채도 · 밝기를 옮긴다 (알파 그대로). 셋 다 기본값이면 종료 2 (2026-10-06) |
| `tint --in white/ --colors #E85D5D,#5DA0E8 --out t/ [--sheet s.png] [--gif t.gif --duration 110]` | 흰 겹 × 색 곱하기 → 색마다 한 장 |
| `outline --in raw/ --out o/ [--mode black\|solid\|selout\|selout+light] [--where outside\|inside] [--width N] [--grow]` | 외곽선을 두른다. selout 계열은 램프가 없으면 종료 2. `--grow` 없이 캔버스 밖으로 나가면 경고 `outline.clipped` (2026-10-06) |
| `fill --in raw/ --out o/ --enclosed --color #hex [--max-area N]` | 틀에 갇힌 투명 칸을 채운다(대각선으로만 이어진 선도 틀). 경고 `fill.none` · `fill.large` · `fill.skipped` (2026-10-06) |
| `diff --a a/ --b b/ --alpha-only` | 두 그림(폴더)의 알파가 같은지. 다르면 종료 4. 파일을 안 쓴다 (2026-10-06) |
| `merge-colors --in raw/ --out o/ [--tol N \| --max-colors N \| --palette] [--keep #hex,…] [--per-image] [--clean] [--sheet s.png] [--dry-run]` | 가까운 색을 많이 쓰인 쪽으로 합친다 — `check` 가 `max_colors` · `near_colors` 로 걸릴 때. 평균색은 안 만든다 (2026-10-05). `--clean` 은 합친 뒤 둘레에 묻힌 잡티 점(외톨이 · 2칸)만 메운다 (2026-10-06) |
| `ui glyphs --font f.ttf (--text "…" \| --text-file t.txt)` | 글꼴에 없는 글자 찾기. 있으면 `fail`(종료 4) |
| `layers diff … --drop 겹:#hex[,#hex] [--drop-tol 24]` | 겹 떼기에서 그 겹의 이 색 칸을 뺀다 (뺨 · 옷 점이 머리 겹에 묻을 때) |
| `sheet … --grid 8 [--grid-color #hex]` | zoom 판에 원본 N 칸 눈금 · 좌표 (배율 4 이상) |

**`arttool.draw`** 는 PIL 로 겹별로 그리는 파이썬 공개 모듈이다(`Canvas` · `shade` · 도형 · `outline`). 쓰는 법은 스킬의 `그리기-pil.md`.

**원본 보호** : 새 명령은 모두 **쓸 자리가 읽은 그림과 겹치면 아무것도 안 쓰고 종료 2** 다. `--report` 는 `.json` 만 받는다.
**`template render` 로 만든 폴더는 커밋하지 않는다** — `template.json` 에 이 PC 의 절대 경로가 박힌다.

**보고 꼴** : `status`(`ok` · `warn` · `fail`) · `warnings`(걸린 것만 `{rule, ok, detail, items}`) · `must_failed`(템플릿 최소 규칙을 어긴 낱말) ·
`skipped_files`(`check` 가 건너뛴 render 가이드 파일). 경고는 `status` · 종료 코드 · `bake` 를 안 바꾼다. 종료 코드는 0 · 1 · 2 · 4(아래 표).

### 프로필 새 칸

옛 프로필은 그대로 읽힌다(모두 기본값이 있다). 값은 `arttool --profile P profile show` 로 본다.

```yaml
style:                  # 이 게임은 이렇게 그린다. 템플릿 · 경고가 읽는다
  outline: unset        # unset | none | black | solid | selout | selout+light
  light: top_left       # top_left | top | top_right
  scale: 1
  materials: {}
check:
  warn:                 # 경고 여덟. 켜고 끄는 칸 이름은 enabled (on 은 YAML 이 참거짓으로 읽어 못 쓴다)
    isolated: { enabled: true, max_ratio: 0.15 }
    near_colors: { enabled: true, max_delta: 4, min_pairs: 20 }
    outline: { enabled: true, black_ratio: 0.8, accept: [] }   # accept : style.outline 말고도 통과시킬 판정 (예 [solid, selout+light])
    # integer_scale · color_cap · ramp_shape · loop_seam 도 같은 꼴
  background: { auto: true, min_side: 128, color_cap: 64, max_colors: null }
```

램프 파일(json)에는 `ramp_len_mode: fixed | max` 칸이 있다(프로필 칸이 아니다). `fixed`(기본)는 모든 램프 길이가 `ramp_len` 과 같아야 하고, `max` 는 램프마다 길이가 달라도 된다(가장 긴 것 = `ramp_len`). `bake` 는 짧은 램프를 마지막 색으로 채워 굽고 asset json 에 `rampLens` 를 더한다.
`ramp_shape` 는 한 색 램프(같은 색 되풀이)를 경고 대신 `info` `ramp_shape.single` 로 알린다 (2026-10-06).

### 스킬 — 그림 그릴 때 에이전트가 읽는 글

`.claude/skills/arttool-usage/` (`SKILL.md` · `기준.md` · `뽑기-pixellab.md` · `그리기-pil.md` · `scripts/` 예시 셋).
이 README 를 한 번 읽으면 스킬 목록에 뜬다. 서브모듈로 붙인 게임 저장소에서는 그 저장소 `CLAUDE.md` 에 아래 한 줄을 넣는다
(서브에이전트에는 목록에 안 뜨니 `SKILL.md` 를 파일로 읽게 한다).

```
도트 그림 : 그리거나 PixelLab 으로 뽑기 전에 Tools/ArtTool/.claude/skills/arttool-usage/SKILL.md 를 읽는다 (밑판 template → 그리기 → intake · check · sheet)
```

### 라이선스

비교판 · 미리보기 딱지 글꼴 **Pretendard Medium** 은 SIL Open Font License 1.1 이다. 원본 파일을 그대로 넣었고 라이선스 글은 `src/arttool/assets/fonts/OFL-Pretendard.txt` 에 있다.

공통 인자 `--profile` `--provider` `--dry-run` `--force` `--json` `--directions` 는
명령 앞에도 뒤에도 붙는다. `--json` 이면 사람용 표 대신 JSON 을 찍는다.
**`--dry-run` · `--force` · `--provider` 는 받는 명령이 정해져 있다.** 그 밖의 명령에 주면 종료 2 로 멈춘다(2026-10-05, 전에는 조용히 무시).

| 인자 | 받는 명령 |
| --- | --- |
| `--dry-run` | 손질 `cutout` · `trim` · `reline` · `tint` · `merge-colors` · `intake`, 한두 장 쓰는 `stitch` · `sheet` · `bands` · `anchors` · `extend` 셋 · `style ref` · `layers mask`/`view` · `ui preview`/`font` · `tile offset`/`preview`/`ldtk`/`seam`(아무것도 안 쓰고 보고만, `would_write`) · `tile place` · `provider make`(요청 JSON 만). 파일을 안 쓰는 `check` 류 · `profile show` · `template list`/`show` · `provider list` 는 받아도 같다. 폴더째 여러 파일을 쓰는 15개는 거절 |
| `--force` | `bake` · `ui bake` · `style extract` |
| `--provider` | `provider make` |

자세한 것은 `Docs/Guide/명령안내.md` 0절.

**출력은 늘 UTF-8 이다.** 파이프 · 파일로 나가도 한글이 안 깨진다(cp949 로 받아야 하면 `PYTHONIOENCODING` 을 준다).
PowerShell 5.1 에서 `$x = arttool …` 로 받으면 콘솔 인코딩(cp949)으로 읽어 깨질 수 있다 —
받아 쓸 때는 `--report` 파일을 읽거나 먼저 `[Console]::OutputEncoding = [Text.Encoding]::UTF8` 을 준다.

### 스프라이트 4단

| 단계 | 무엇 | 막히는 곳 |
| --- | --- | --- |
| ① `normalize` | 낱장·시트를 프레임 크기·baseline·중심에 맞춘다 | 프레임 수가 프로필과 다름 · 캔버스가 안 맞음 · 반투명 픽셀 |
| ② `anchors` | 마커 색 한 픽셀 → `anchors.json` | 부착점이 빠짐 · 마커가 2개 이상 · 마커 색이 그림 색과 겹침 |
| ③ `check` | 규칙 다섯을 돌려 보고 JSON (낱장 모드는 앞 셋, `--no-ramps` 면 램프 밖 색도 뺀다) | 색 수 · 램프 밖 색 · 반투명 · baseline · bbox 흔들림 |
| ④ `bake` | 아틀라스 · 매니페스트 · SO JSON | ③이 `ok` 가 아님 (`--force` 면 `forced: true` 가 박힌다) |

**④ `bake` 는 선택이다.** 게임 쪽이 낱장 임포터로 이미 자동이면 굽지 않고 ③에서 멈춘다 (위 「어느 길로 쓰나」).

들어오는 파일 이름은 셋 중 하나다.

```
walk.png              방향이 줄, 프레임이 칸인 격자 시트
walk_south.png        한 방향짜리 가로 시트
walk_south_0.png      낱장
```

`tiles.mirror_east_from_west` 가 켜져 있으면 east 그림이 없을 때 west 를 뒤집어 만들고,
앵커 `x` 도 `frame_w - 1 - x` 로 같이 뒤집는다.

### 겹 나누기 · 색 굽기 (`split` · `recolor`)

한 장 그림을 겹(몸·머리·옷·표정…)으로 가르고, 겹마다 색 변종을 굽는다. **AI 나 사람은 표 JSON 만 쓰고 픽셀은 코드가 만진다.**
제공자를 타지 않는다. 받는 베이스 PNG 는 직접 그린 것 · PixelLab · 다른 생성기 어디서 왔든 같다 — **PixelLab 은 선택이다.**
표 꼴 전체는 `Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md` 3·4절을 본다.

| 명령 | 무엇 | 막히는 곳 |
| --- | --- | --- |
| `split --list-colors` | 색마다 개수 · bbox · y 범위를 낸다. 나누기 표를 쓸 때 읽는다 | 반투명 픽셀 |
| `split` | `<out>/<겹>/<원본>.png` + `split_report.json` + `anchors.json` | 반투명 · 표에 없는 겹 이름 · 잘못된 hex · `--rig` 의 `layer_order` 와 표 `layers` 가 다름 · **되돌림 다름이 0 이 아니면 `fail`** |
| `recolor` | 겹 × 색 벌 → PNG N장 + `recolor_report.json` (+ `--sheet` 미리보기) | `out` 에 `..` · 벌이 둘 이상인데 `out` 에 `{v}` 없음 · 같은 출력 이름 두 번 · 벌에 역할 빠짐 · **자리다름이 0 이 아니면 `fail`** |
| `split` 색상 · 회색 | 규칙 `{"hue":[340,20],"to":..,"min_sat":0.2}` 로 색상(도)으로 겹 나누기, `--gray-levels 255,180,60` 으로 밝기를 회색 단계로 | `hue` 범위 밖 · 시작=끝 · `color` 와 `hue` 같이 · 회색 단계 겹침 (명령안내 18절) |
| `layers` 변형 묶음 | `layers.json` 겹마다 `files`(`parts/body_{v}.png`), 그림마다 `items` 의 `pick` 으로 변형 고르기. `layers check` 는 `unused_variant` · `variant_size` · `variant_alpha` | 무늬 `{v}` 위치 · 없는 변형 · `exclusive_with` 짝 · `split` 으로 그림 더하기 (명령안내 18절) |

- **겹은 캔버스를 안 자른다.** 원본과 같은 크기·좌표라 Unity 에서 같은 자리에 쌓기만 하면 맞는다.
  출력 꼴이 `layers compose` 입력 꼴과 같아 `arttool layers compose --rig R --anim <원본이름>` 으로 다시 쌓으면 원본이 나온다.
- 가르는 순서는 **마스크 > 자리 규칙 > 색 표 > 외곽선 투표 > 투표 뒤 규칙(`from`·`near`)** 이다.
  `box` 는 끝을 뺀 `[x0, y0, x1, y1)`, `above_y: N` 은 `y < N`, `below_y: N` 은 `y >= N` 이다.
  외곽선 투표는 반경 1→2→3→4→6 으로 넓히고, 한 반경에서 정해진 외곽선이 다음 반경 투표에 낀다.
  표가 같으면 먼저 표를 준 겹(위 줄부터, 왼쪽부터)이 이긴다. `from: <겹>` 은 투표 뒤 그 겹으로 간 픽셀만, `near: <겹>` 은 그 겹에 붙은 픽셀만 본다.
  마스크 경로는 표 파일 폴더 아래만 받는다. 겹 이름은 대소문자만 다른 것도 겹침으로 보고 거절한다.
- `--list-colors` 의 `bbox` 와 `y_range` 는 둘 다 **끝을 뺀 값**이다 (`y_range: [3, 8]` 이면 3~7 줄).
- 떨어진 작은 조각(8방향, 겹마다 `min_piece`)은 **지우지 않고 이웃 겹으로 옮긴다.** 옮길 이웃이 없으면 그대로 두고 `warn`.
  **표정 겹은 `layer_opts.<겹>.min_piece: 0`** 으로 둔다 — 눈·입이 원래 떨어진 점이다.
- `recolor` 는 밑감 색 하나 → 결과 색 하나로 바꾸고 밝기를 계산하지 않는다. 표에 없는 색은 그대로 두고 보고에 적는다 (`warn`).
  `outline` 을 주면 RGB 각 칸 차이 2 이내인 색을 그 한 색으로 맞춘다.
- 표에 없는 색 · 빈 겹 · 떠 있는 조각 · `roles` 에 적었지만 그림에 없는 색은 `warn`(종료 코드 0), 되돌림·자리 어긋남은 `fail`(종료 코드 4)이다.
  되돌림은 저장한 겹 파일을 다시 읽어 쌓아서 본다. `recolor` 출력이 밑감 원본 경로와 같으면 거절한다.
- **프로필의 `palette.swap: bake` 는 `recolor` 를 부르지 않는다.** 색 굽기는 `recolor` 를 따로 부른다.

### 타일 3단

`tile blob` 은 템플릿 6장(`fill` `edge_n` `edge_w` `corner_outer` `corner_inner` `single`)의
왼쪽 위 사분면을 잘라 네 모서리에 뒤집어 붙여 47장을 만든다.
`tile place` 는 DeBroglie 를 바깥 실행 파일로 부른다 (`--exe` 나 `DEBROGLIE_EXE`).
`tile ldtk` 는 맵 JSON 을 LDtk 프로젝트 파일로 쓴다.

#### 타일 낱장 검사 셋 (`tile preview` · `inspect` · `seam`)

PIL 이나 손으로 그린 낱장 타일을 볼 때 쓴다. 팔레트 · 제공자가 없어도 돈다.
`--in` 은 폴더 바로 아래 PNG(이름순)이거나 PNG 한 장이다. 설계는 `Docs/Design/2026-09-23-겹나누기·팔레트굽기·타일·아이콘설계.md` 6절.

| 명령 | 무엇 | 막히는 곳 |
| --- | --- | --- |
| `tile preview` | 배치표대로 여러 장을 조립한 PNG 한 장. 반복 티를 눈으로 본다 | 타일 크기가 섞임 · 배치표 이름에 맞는 파일이 없음 · `weights` 와 `cells` 를 둘 다 줌 · 256×256 칸을 넘음 |
| `tile inspect` | 장마다 크기 · bbox · 불투명 비율 · 반투명 수 · 색 수 · 네 변 닿음 · 넘친 픽셀을 한 표로 | 크기가 `--size` 와 다름 · `--size` 밖 불투명 픽셀 · 반투명(프로필 `check.allow_alpha: binary` 일 때) → `fail` |
| `tile seam` | 이음 줄(오른쪽↔왼쪽 · 아래↔위)을 본다. `--pairs` 면 변종끼리 모든 순서쌍도 | 이음 줄 평균 차이가 안쪽 이웃 평균의 `k` 배를 넘음 → `fail` |

- **배치표**는 둘 중 하나다. 이름 = 파일 이름에서 `.png` 를 뗀 것.
  `{"size": [12, 13], "weights": {"grass_0": 6, "grass_1": 2}, "seed": 3}` — `seed` 로 섞는다 (없으면 0, 같은 seed 면 같은 그림).
  `{"cells": [["fence_l", "fence_m", "fence_r"], ["grass_0", null, "grass_0"]]}` — 자리 고정, `null` 은 빈 칸. `size` 는 주면 맞아야 한다.
  `weights` 에 적은 이름은 무게 0 이어도 파일이 있어야 한다. 무게는 0 이상 유한한 수만 받는다 (`NaN` · `Infinity` · 합이 넘치는 값은 거절).
  이름에 `/` · `\` 를 넣으면 거절한다 — `--in` 바로 아래 파일만 가리킨다. 출력의 `grid` 에 칸마다 고른 이름이 찍힌다.
- `preview` 출력과 `seam --sheet`(그리고 `recolor --sheet`)는 **8192×8192 픽셀을 넘으면 그리기 전에 거절**한다.
- `--scale 0` · `--k 0`·`inf`·`nan` · `inspect --size 0` 처럼 잘못된 인자는 종료 코드 2 다.
- `inspect` 의 `--size` 는 안 주면 프로필 `tiles.size` 다. 네 변 닿음은 왼쪽 위 `--size` 칸 안에서 본다.
  빈 타일은 `warn` 이다.
- `seam` 의 차이는 칸마다 RGBA 네 칸 차이의 합이다 (투명 칸은 RGB 를 0 으로 보고 센다).
  실패한 줄에만 `rows`(오른쪽↔왼쪽) · `cols`(아래↔위)로 어긋난 자리를 적는다. `ratio` 가 `k` 와 견준 값이다 (안쪽이 한 색이라 평균 0 인데 이음 줄만 다르면 `ratio` 는 `null` 이고 실패).
  **`k` 기본 2.0 은 실제 풀밭 타일 3장으로 쟀다** — 이어지는 풀은 1.14 이하, 이어지지 않는 울타리 모서리는 4 안팎이었다.
  `--sheet` 는 장마다 3×3 으로 이은 그림을 늘어놓는다. `--pairs` 는 크기가 같은 타일끼리만 된다.

#### 설계 문서의 이름과 다른 자리

| 설계 문서 | 실제 명령 | 왜 |
| --- | --- | --- |
| `tile source` (설계 4-2 ①) | `provider make --kind tile` | 타일 그림을 얻는 단계는 **제공자를 타는 유일한 타일 단계**라 제공자 명령으로 합쳤다. `code` 제공자면 기반 에셋에서 잘라 온다 |
| `tile place --out build/map.ldtk` | `tile place --out <폴더>` + `tile ldtk` | 배치와 LDtk 쓰기를 갈랐다. 배치는 `place_request.json`·`map.json` 을 폴더에 쓰고, 변환은 `tile ldtk` 가 한다 |

### UI 3단 + 곁가지

UI 는 새 툴이 아니라 `arttool ui …` 명령 묶음 + 프로필의 `ui:` 절이다.
스프라이트가 **시간**으로, 타일이 **공간**으로 이어진다면 UI 는 **크기**로 늘어난다.

| 단계 | 무엇 | 막히는 곳 |
| --- | --- | --- |
| ①ㄱ `ui frame` | 패널·버튼·바를 코드가 그리고 border 를 같이 적는다 | 램프에 단이 모자람 · 최소 크기 > 원본 · 원본이 홀수 |
| ①ㄴ `ui import` | `.9.png` 안내선을 읽고 1px 을 떼어 낸다 | 안내선이 네 변에 안 맞음 · 검은 구간이 2개 이상 · 안내선 없음 |
| ①ㄷ `ui icons` | 격자로 시트를 자르거나, 낱장 PNG 폴더를 그대로 들인다 | 칸 크기가 `icon.sizes` 밖 · 격자가 시트 크기와 안 맞음 · 낱장이 정사각형이 아님 · `--cell` 을 폴더에, `--fit` 을 시트에 줌 |
| ② `ui check` | 규칙 **여섯** + 경고 둘 | 최소 크기 · 홀수 · 램프 밖 색 · 반투명 · 상태 갖춤 · **PPU 대조** |
| ③ `ui bake` | 아틀라스 · `ui_manifest.json` · `ui.uss` · 에디터 스크립트 | ②가 `ok` 가 아님 (`--force` 면 `forced: true`) |
| 곁가지 `ui screen` | 화면 JSON → UXML + USS | id 겹침 · 모르는 type · 매니페스트에 없는 `bg` |
| 곁가지 `ui font` | 텍스트를 훑어 `charset.txt` | 훑을 폴더가 없음 · 글자 0개 |

**`--fit` 을 제자리(`--in` 과 `--out` 이 같은 폴더)에 쓰면 원본 PNG 를 맞춘 그림으로 덮어쓴다.**
원본을 남기려면 `--out` 을 다른 폴더로 준다. `--fit` 없이 제자리면 `icons.json` 만 새로 쓴다.
`--cell` 은 시트 파일에만, `--fit` 은 낱장 폴더에만 쓴다 — 반대로 주면 거절한다.
**속이 텅 빈 PNG 는 건너뛰고** 보고의 `empty_cells` 로 센다. 크기가 섞인 폴더면 `cell` 이 `null` 이고
`sizes` 에 나온 크기가 다 적힌다.

**`ui check` 와 `ui bake` 는 같은 폴더를 본다.** `ui frame` · `ui import` · `ui icons` 의 `--out` 을
한 폴더로 맞춰야 `border.json` 과 `icons.json` 이 한자리에 모인다.

**들여오는 그림 이름은 `<묶음>_<상태>.9.png` 다.** 뒤 조각이 `ui.generator.states` 에 있을 때만 상태로 본다 —
`dialog_box.9.png` 는 묶음 `dialog_box` · 상태 `normal` 이고, `btn_big_pressed.9.png` 는 묶음 `btn_big` · 상태 `pressed` 다.

**화면 JSON 의 `id` 와 `bg` 는 USS 선택자로 그대로 들어간다.** 그래서 영문자·밑줄로 시작하고
영숫자·밑줄·붙임표만 쓴다. `pad` · `gap` · `size` 는 0 이상 정수, `grow` 는 참·거짓만 받는다.

**`ui font` 는 `--scan-root` 아래만 훑는다.** 안 주면 프로필 파일이 있는 폴더가 뿌리다.
절대경로와 `..` 는 거절한다 — 엉뚱한 파일 내용이 `charset.txt` 로 새어 나가지 않게.

border 순서는 **[왼, 아래, 오른, 위]** 다. Unity `spriteBorder` 의 Vector4 순서라 바꾸지 않는다.

**`-unity-slice-scale` 은 툴이 반드시 적는다.** 값은 `100 / ppu` 라 PPU 16 이면 6.25 다.
빠뜨리면 테두리가 사라지는데 원인을 찾기 어렵다.

### Unity 쪽 UI 산출물 쓰는 법

`ui bake` 가 낸 폴더를 통째로 `Assets/UI/` 에 넣는다.

| 파일 | 무엇을 하나 |
| --- | --- |
| `ui_atlas.png` + `ui_manifest.json` | 둘이 **같은 폴더**에 있어야 임포터가 붙는다 |
| `Editor/UiImportSettings.cs` | `AssetPostprocessor`. Point 필터 · 무압축 · mipmap 끔 · PPU · `border` 를 `OnPreprocessTexture` 한자리에서 넣는다. 사람이 Sprite Editor 를 열 일이 없다 |
| `Editor/UiManifestData.cs` | 위 둘이 쓰는 JSON 통 클래스 |
| `ui.uss` | 모든 `bg-*` 규칙. 화면 USS 보다 먼저 읽히게 둔다 |
| `<화면>.uxml` · `<화면>.uss` | `ui screen` 산출물. 버튼 동작은 `Q<Button>("btn_resume").clicked += …` 로 코드에 둔다 |
| `UiSpecAsset.json` | ScriptableObject 용 **수치만**. 배율은 `max(1, floor(화면높이 / referenceHeight))` |
| `Editor/TmpFontBaker.cs` + `font_bake.json` | 메뉴 `Tools/ArtTool/Bake UI Font` 를 누른다. 배치 모드는 `-executeMethod <namespace>.TmpFontBaker.BakeFromArgs`. **폰트·글자 파일 자리는 `font_bake.json` 이 혼자 정한다** — `ui font --out` 을 거기 적힌 `charsetPath` 로 주면 된다 (굽기 보고의 `notes` 가 그 경로를 찍어 준다) |

**`PanelSettings` 의 `DynamicAtlasSettings` 에서 UI 아틀라스를 뺀다.** Point 텍스처가 Bilinear 동적
아틀라스에 들어가면 흐려진다. 굽기 보고의 `notes` 에도 같은 줄이 찍힌다.

**C# 은 `<out>/Editor/` 아래로 나간다.** 에디터 전용 API 를 쓰므로 `Editor` 폴더 밖에 두면 플레이어 빌드가
컴파일 오류로 깨진다. 파일 안쪽도 `#if UNITY_EDITOR` 로 감싸 두 겹으로 막았다.
`--namespace` 를 주면 세 `.cs` 의 `namespace` 줄을 그 값으로 바꿔 내보낸다.

**사람이 고친 `.cs` 는 안 덮는다.** 내용이 툴이 내는 것과 다르면 `<이름>.cs.new` 로 옆에 쓰고
굽기 보고의 `warnings` 에 한 줄을 남긴다. 합치는 것은 사람 몫이다.

## 폴더 지도

| 경로 | 내용 |
| --- | --- |
| `setup.ps1` | 깔기 한 줄. `.venv` 만들기 → 깔기 → 연기 시험 |
| `src/arttool/` | 코드. `cli.py` 는 인자만 넘기고 셈은 안 한다 |
| `src/arttool/image.py` | Pillow 를 부르는 유일한 자리. 밖으로는 numpy 배열만 오간다 |
| `src/arttool/sprite/` | ① 규격 `normalize` ② 앵커 `anchors` · 층 겹치기 `layers` · 겹 나누기 `split` · 색 굽기 `recolor` · Aseprite `aseprite` |
| `src/arttool/pieces.py` | 8방향 덩어리 묶기 · 떨어진 조각 찾기 · 이웃 투표 (`split`·`recolor` 가 같이 쓴다) |
| `src/arttool/tiles/` | ② 부풀리기 `blob` ③ 배치 `place` · LDtk `ldtk` · 낱장 검사 `preview` · `inspect` · `seam` |
| `src/arttool/ui/` | 프레임 `frame` · 9패치 `ninepatch` · 아이콘 `icons` · 검수 `check_ui` · 매니페스트 `manifest` · 굽기 `bake_ui` · 화면 `screen`·`uxml`·`uss` · 글자 `font` |
| `src/arttool/ui/unity/` | 내보낼 C# 원본. 템플릿 문자열이 아니라 진짜 `.cs` 파일이다 |
| `src/arttool/providers/` | 제공자. 밖에서는 제공자 이름을 모른다 |
| `src/arttool/edit/` · `intake.py` · `sheet.py` | 손질(`cutout` · `trim`) · 한 번에 손질 · 비교판 |
| `src/arttool/checks/` | 경고 여덟의 「재기」 와 「판정」. `sheet` · `style` 도 재기를 같이 쓴다 |
| `src/arttool/style/` · `template/` · `draw/` | 화풍 뽑기 · 템플릿 엔진 · PIL 그리기 공개 모듈 `arttool.draw` |
| `src/arttool/layerset.py` · `sprite/layerops.py` | 겹 묶음 꼴(`layers.json`) · `layers` 묶음 명령 |
| `src/arttool/assets/fonts/` | Pretendard Medium + 라이선스 글 |
| `templates/` | 템플릿 JSON 15개 |
| `.claude/skills/arttool-usage/` | 그림 그릴 때 읽는 스킬 (위 「스킬」) |
| `Docs/Guide/명령안내.md` | 개선 판 명령의 자세한 안내 |
| `profiles/` | 프로필. `presets/` 안에 프리셋 넷 |
| `palettes/` | 램프 JSON |
| `tests/` | pytest. 시험용 그림은 코드로 만든다 |
| `Example/` | 참고 그림 (64×64, Front/Left/Back) |
| `Docs/` | 조사 · 설계 · 할 일 · 안내 |
| `Docs/Todo/진행상황.md` | **이어받는 세션이 여기부터 읽는다.** 한 줄 상태 · 지금 차례 · 주의 |
| `Docs/Guide/AI-그래픽-캐릭터-배경-가이드.html` | 캐릭터·배경 그림을 AI 로 만들 때의 안내. 브라우저로 연다 |

## 제공자

| 이름 | 켜지는 조건 | 지금 상태 |
| --- | --- | --- |
| `code` | 늘 켜짐 (기본) | 참조 그림에서 잘라 낸다 |
| `local` | `ARTTOOL_LOCAL_ENDPOINT` | 요청 JSON 만 낸다 |
| `pixellab` | `PIXELLAB_API_KEY` | 요청 JSON 과 견적만. 단가는 `PIXELLAB_COST_PER_IMAGE` |

키가 없는 제공자는 오류가 아니라 목록에서 빠진다. 대놓고 고른 제공자만 오류로 멈춘다.
키는 환경변수로만 읽고 요청 JSON · 산출물 · 로그 어디에도 안 적는다.

## 종료 코드

| 코드 | 뜻 |
| --- | --- |
| 0 | 잘 됨 |
| 1 | 일반 오류 (예상 못 한 예외도 여기로 내린다. 역추적은 `ARTTOOL_DEBUG=1` 일 때만 찍는다) |
| 2 | 인자가 잘못됨 |
| 3 | 프로필이 잘못됨 |
| 4 | 검수 실패 |
| 5 | 바깥 실행 파일 없음 |
| 6 | 경로 감옥 위반 |

## 아직 안 붙인 것

- **Aseprite · DeBroglie 는 이 PC 에 없다.** 감싸는 코드는 있고 계약(인자 목록 · 요청/응답 JSON)만 시험했다.
- `provider make --provider pixellab` 은 요청 JSON 견적만 낸다. 실제 뽑기는 PixelLab MCP 쪽 일이다(에이전트가 MCP 도구를 직접 부른다).
- **Unity 에디터 스크립트 둘(`UiImportSettings.cs` · `TmpFontBaker.cs`)은 컴파일해 본 적이 없다.** Unity 가 이 PC 에 없다.
- 화면 정의의 격자 · 스크롤 · 목록 · 전환, `hover` · `focus` 상태, 커서 핫스폿은 2차다.
- `local` 제공자의 실제 호출. 지금은 `--dry-run` 요청 JSON 까지만.

설계는 `Docs/Design/2026-08-25-그림툴설계.md` · `Docs/Design/2026-10-04-ArtTool개선설계.md`, 할 일은 `Docs/Todo/진행상황.md` · `Docs/Todo/그림툴.md` 를 본다.
