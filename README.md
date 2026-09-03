# ArtTool

게임에 들어가는 **2D 그림**(스프라이트·타일·UI)을 규격에 맞추고, 앵커를 뽑고, 검수해서
Unity 가 바로 쓸 데이터로 굽는 툴이다. 그림을 그려 주는 툴은 아니다.

**상태 : 스프라이트 툴 · 타일 툴 · UI 툴 1차 구현 끝**

## 설치

이 폴더 안에 가상환경을 만들고 거기에만 깐다. 전역 pip 는 안 쓴다.
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

시험은 **374개가 다 통과해야** 한다.

`profiles/` · `palettes/` 는 이 폴더를 기준으로 찾는다. 다른 자리에 두려면 `ARTTOOL_HOME` 을 정한다.

## 명령

```
arttool profile show   --profile slime_demo
arttool normalize      --profile P --in raw/ --out build/
arttool anchors        --profile P --in build/ --rig blob --from marker --markers markers/ --out build/anchors.json
arttool check          --profile P --in build/ --report build/check.json
arttool bake           --profile P --in build/ --out Unity/Art/ --namespace Game.Art
arttool layers         --profile P --rig humanoid_lpc --in parts/ --out build/
arttool tile blob      --profile P --in template6/ --out tiles47/
arttool tile place     --profile P --tileset tiles47/tileset.json --rules rules.json --size 64x64 --out map/
arttool tile ldtk      --map map/map.json --tileset tiles47/tileset.json --out map/level.ldtk
arttool ui frame       --profile P --kind panel --size 16x16 --out build/ui/
arttool ui import      --profile P --in raw/ui/ --out build/ui/
arttool ui icons       --profile P --in raw/icons.png --cell 16 --out build/ui/
arttool ui check       --profile P --in build/ui/ --report build/ui/check.json [--manifest Unity/UI/ui_manifest.json]
arttool ui bake        --profile P --in build/ui/ --out Unity/UI/ --namespace Game.UI
arttool ui screen      --profile P --spec screens/pause_menu.json --out Unity/UI/
arttool ui font        --profile P --scan-root . --scan Text --out Unity/UI/Fonts/charset.txt
arttool provider list
arttool provider make  --kind character --spec req.json --out gen/ --dry-run
```

공통 인자 `--profile` `--provider` `--dry-run` `--force` `--json` `--directions` 는
명령 앞에도 뒤에도 붙는다. `--json` 이면 사람용 표 대신 JSON 을 찍는다.

### 스프라이트 4단

| 단계 | 무엇 | 막히는 곳 |
| --- | --- | --- |
| ① `normalize` | 낱장·시트를 프레임 크기·baseline·중심에 맞춘다 | 프레임 수가 프로필과 다름 · 캔버스가 안 맞음 · 반투명 픽셀 |
| ② `anchors` | 마커 색 한 픽셀 → `anchors.json` | 부착점이 빠짐 · 마커가 2개 이상 · 마커 색이 그림 색과 겹침 |
| ③ `check` | 규칙 다섯을 돌려 보고 JSON | 색 수 · 램프 밖 색 · 반투명 · baseline · bbox 흔들림 |
| ④ `bake` | 아틀라스 · 매니페스트 · SO JSON | ③이 `ok` 가 아님 (`--force` 면 `forced: true` 가 박힌다) |

들어오는 파일 이름은 셋 중 하나다.

```
walk.png              방향이 줄, 프레임이 칸인 격자 시트
walk_south.png        한 방향짜리 가로 시트
walk_south_0.png      낱장
```

`tiles.mirror_east_from_west` 가 켜져 있으면 east 그림이 없을 때 west 를 뒤집어 만들고,
앵커 `x` 도 `frame_w - 1 - x` 로 같이 뒤집는다.

### 타일 3단

`tile blob` 은 템플릿 6장(`fill` `edge_n` `edge_w` `corner_outer` `corner_inner` `single`)의
왼쪽 위 사분면을 잘라 네 모서리에 뒤집어 붙여 47장을 만든다.
`tile place` 는 DeBroglie 를 바깥 실행 파일로 부른다 (`--exe` 나 `DEBROGLIE_EXE`).
`tile ldtk` 는 맵 JSON 을 LDtk 프로젝트 파일로 쓴다.

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
| ①ㄷ `ui icons` | 격자로 아이콘 시트를 자른다 | 칸 크기가 `icon.sizes` 밖 · 격자가 시트 크기와 안 맞음 |
| ② `ui check` | 규칙 **여섯** + 경고 둘 | 최소 크기 · 홀수 · 램프 밖 색 · 반투명 · 상태 갖춤 · **PPU 대조** |
| ③ `ui bake` | 아틀라스 · `ui_manifest.json` · `ui.uss` · 에디터 스크립트 | ②가 `ok` 가 아님 (`--force` 면 `forced: true`) |
| 곁가지 `ui screen` | 화면 JSON → UXML + USS | id 겹침 · 모르는 type · 매니페스트에 없는 `bg` |
| 곁가지 `ui font` | 텍스트를 훑어 `charset.txt` | 훑을 폴더가 없음 · 글자 0개 |

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
| `src/arttool/` | 코드. `cli.py` 는 인자만 넘기고 셈은 안 한다 |
| `src/arttool/image.py` | Pillow 를 부르는 유일한 자리. 밖으로는 numpy 배열만 오간다 |
| `src/arttool/sprite/` | ① 규격 `normalize` ② 앵커 `anchors` · 층 겹치기 `layers` · Aseprite `aseprite` |
| `src/arttool/tiles/` | ② 부풀리기 `blob` ③ 배치 `place` · LDtk `ldtk` |
| `src/arttool/ui/` | 프레임 `frame` · 9패치 `ninepatch` · 아이콘 `icons` · 검수 `check_ui` · 매니페스트 `manifest` · 굽기 `bake_ui` · 화면 `screen`·`uxml`·`uss` · 글자 `font` |
| `src/arttool/ui/unity/` | 내보낼 C# 원본. 템플릿 문자열이 아니라 진짜 `.cs` 파일이다 |
| `src/arttool/providers/` | 제공자. 밖에서는 제공자 이름을 모른다 |
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

- **Aseprite · DeBroglie · PixelLab 은 이 PC 에 없다.** 감싸는 코드는 있고 계약(인자 목록 · 요청/응답 JSON)만 시험했다.
- **Unity 에디터 스크립트 둘(`UiImportSettings.cs` · `TmpFontBaker.cs`)은 컴파일해 본 적이 없다.** Unity 가 이 PC 에 없다.
- 화면 정의의 격자 · 스크롤 · 목록 · 전환, `hover` · `focus` 상태, 커서 핫스폿은 2차다.
- `local` · `pixellab` 의 실제 호출. 지금은 `--dry-run` 요청 JSON 까지만.
- UI 툴.

설계는 `Docs/Design/2026-08-25-그림툴설계.md`, 할 일은 `Docs/Todo/그림툴.md` 를 본다.
