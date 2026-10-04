# PIL 로 직접 그리기 — `arttool.draw`

좌표와 색을 코드로 정해 칸을 찍는 길이다. ArtTool 가상환경에 들어 있어 따로 깔 것이 없다.
**28~64px 평평한 아이콘 · 타일 · 단순 설비 · 도형 이펙트**에 맞고, 복잡한 캐릭터 · 질감에는 안 맞는다 (`SKILL.md` 「어느 길을 고르나」).

## 돌리는 법

```
<ArtTool>\.venv\Scripts\python.exe <ArtTool>\.claude\skills\arttool-usage\scripts\draw_tile.py --out work\tile
```

내 스크립트도 같은 파이썬으로 돌린다(`from arttool.draw import …` 가 된다). **결과는 저장소 밖 작업 폴더(`--out`)에 쓴다.**

## 예시 스크립트 셋 (`scripts/`)

| 파일 | 무엇 | 거치는 명령 |
| --- | --- | --- |
| `draw_char_small.py` | 48×64 `sd`(약 2등신) 캐릭터를(`--size 64x80` · `32` · `16` 도 된다 — 64 미만은 기본 sd) `char_small` 가이드 줄(머리 상자 · 눈 카드 · 몸 · 다리 · baseline)에 맞춰 겹 다섯(body · cloth · face · hair · deco)으로 그린다 | `template render` → `Canvas` → `layers check` → `layers export --flat` → `check --template` → `sheet` |
| `draw_tile.py` | 32×32 풀 타일 + 꽃 변종. 바탕 무늬는 좌표 나머지 셈으로 네 변이 이어지고, 변종은 `variant_area` 안만 바꾼다 | `template render tile_base` → `Canvas` → `layers check` → `layers export --flat` → `tile seam --pairs` → `sheet --kinds zoom,tile` |
| `draw_fx.py` | 16×16 고리 폭발 5장을 `fx_ring_burst` 공식대로 한 색으로 그리고, 템플릿 프레임 밑그림과 칸 단위로 같은지 본다 | `template render` → `Canvas` → `check --template`(프레임 수 · 색 수) → `sheet` |

고칠 값은 맨 위 상수(색 · 점 자리)뿐이다. 좌표는 가이드에서 읽는다 — 크기를 바꿔도 따라온다.

## 겹별로 그리는 순서

템플릿의 `steps` 를 따른다 (`template show <이름>` 으로 본다). 캐릭터면 :

1. `arttool template render char_small --size 48x64 --out work/guide` — 밑판(쓰기 폴더는 커밋하지 않는다). `_preview.png` 를 열어 가이드 줄 이름을 본다.
2. `c = Canvas(template="work/guide")` — 겹 목록 · 크기 · 가이드 · (화풍을 입혔으면) 팔레트를 읽는다.
3. **실루엣 겹부터** : `body` 를 한두 색으로 채워 덩어리가 읽히는지 `c.preview(…, scale=8)` 로 본다.
4. 위 겹 차례로 : `cloth` → `face`(눈 카드 · 입) → `hair` → `deco`. **위 겹이 덮는 칸은 아래 겹에서 지운다**(`erase`) — 템플릿 마스크(겹 자리)와 맞아 `layers check` 가 조용하다.
5. `c.outline(…)` — 맨 마지막에. 칸마다 그 색을 정한 겹에 들어가 겹을 끄면 둘레선도 같이 꺼진다.
6. `c.report()` 로 팔레트 밖 색 · 가이드 색 섞임 · `exclusive_with` 겹침 · 빈 겹을 본다(예외가 아니라 보고).
7. `c.save("work/set")` → `arttool layers check --in work/set --template work/guide/template.json --report lc.json`
8. `arttool layers export --in work/set --out work/flat --flat` → `arttool check --in work/flat --template work/guide/template.json --report c.json`
9. `arttool sheet --in work/flat --kinds zoom,silhouette,colors4 --label --out work/sheet.png` 를 **열어 본다.**

`layers check` 의 `layer_poke` 는 위 겹이 `face`(눈 · 입처럼 본체 위에 얹는 겹)이면 보지 않는다 — 예전에 작은 캐릭터마다 나던 「본체가 얼굴 겹 밖으로 1칸」 헛경고가 없어졌다.
`exclusive_with` 짝이 아닌 겹끼리는 4칸 넘게 이어진 띠만 알린다.

## 짧은 본보기

```python
from arttool.draw import Canvas, shade

c = Canvas(template="char_small", size=(48, 64))  # 파일 없이 템플릿 이름으로 바로 (render 결과 폴더를 줘도 된다)
g = c.guide
skin = shade("#F2C8A0")                            # 밑색 → 어두운 쪽부터 6단, [3] 이 밑색
c["body"].round_box(*g.box("head"), skin[3], r=2)
c["face"].box(*g.box("eye_box_l"), "#2B2233").box(*g.box("eye_box_r"), "#2B2233")
c.outline("selout", where="inside")
print(c.report()["warnings"])
c.save("work/set")
```

## `arttool.draw` 공개 이름

| 이름 | 꼴 | 하는 일 |
| --- | --- | --- |
| `Canvas` | `Canvas(size=None, *, template=None, layers=None, ramps=None, light=None, preset=None, profile=None)` | 같은 크기 겹 여럿. `template` = 템플릿 이름(`"char_small"`, `size` 같이) · `template render` 출력 폴더 · `template.json` · `layers.json` · 사전. `layers` = 템플릿 없이 겹 정하기(`["body", ("eye", "face")]` — 이름이 kind 낱말이 아니면 `(이름, kind)`). 둘 다 없으면 `body` 한 겹 |
| `c["이름"]` · `c.layer(이름)` | → `Layer` | 겹 꺼내기 |
| `c.names` · `c.size` · `c.guide` · `c.ramps` · `c.light` | 속성 | 겹 이름(아래 → 위) · (너비, 높이) · `Guide` · 팔레트 · 빛 방향 |
| `c.pick(램프, 칸)` | → `#RRGGBB` | 팔레트 램프의 칸 색. 0 = 가장 어둡게, -1 = 가장 밝게. 팔레트가 없으면 오류 |
| `c.outline(mode=None, *, layers=None, where="outside", color=None, width=1)` | | 합친 실루엣 둘레에 외곽선. `mode` = `none` · `black` · `solid` · `selout` · `selout+light` (안 주면 템플릿 화풍). `solid` 는 `color="#3A2A30"` 처럼 한 색을 준다. `width` 는 선 두께 1 ~ 4(큰 그림은 2). `where` = `outside`(바깥 — 모양이 커진다) · `inside`(가장자리 칸을 덧칠 — 크기 그대로). 칠한 색이 램프 맨 아래 칸이라 더 어두운 칸이 없으면 팔레트 `outline` 색을 쓴다. **같은 겹에 두 번 두르지 않는다** — 선이 두 겹이 된다 |
| `c.merged(only=None)` · `c.preview(path, scale=8, only=None)` | | 합친 한 장 · 키운 PNG 쓰기. `preview` 경로가 `save` 한 겹 묶음 폴더 안이면 거절한다 |
| `c.report()` | → dict | `status` · `layers`(겹별 칸 수) · `warnings`(`palette` · `guide_color` · `alpha` · `exclusive` · `outline_twice` · `outline_ramp_bottom` · `empty`) |
| `c.save(folder, item="idle")` | → layers.json 경로 | 겹 묶음 꼴 `folder/layers.json` + `folder/<겹>/<item>.png`. 같은 폴더에 다른 `item` 을 더 쓸 수 있다(프레임 · 변종) |
| `Canvas.open(folder, item="idle")` | → `Canvas` | 저장한 묶음을 다시 열어 이어 그리기. 묶음에 없는 `item` 이름이면 오류(빈 그림으로 열지 않는다) |
| `Layer` 그리기 | `dot(x, y, color, side=1)` · `line(x0, y0, x1, y1, color)` · `box(x0, y0, x1, y1, color, filled=True)` · `round_box(…, color, r=1)` · `ellipse(…, color)` · `disc(cx, cy, r, color)` · `ring(cx, cy, r, color, width=1, dash=0)` · `drop(…, color)` · `fill(x, y, color)` · `paint(mask, color)` | 모두 자기 겹을 돌려줘 이어 부른다. 상자는 끝을 뺀 `[x0, x1) × [y0, y1)`. 캔버스 밖은 잘린다. `line` 은 계단 길이가 고르다, `round_box` 는 정사각 → 모서리 깎기 |
| `Layer` 손질 | `erase(mask=None)` · `mirror()` · `recolor(old, new)` · `mask()` · `px(x, y)` | 지우기(안 주면 전부) · 왼쪽 반을 오른쪽에 거울로 · 색 바꾸기 · 칠한 칸 · 칸 색(투명이거나 캔버스 밖이면 `None`) |
| `shade` | `shade(base, steps=6, hue_step=None, metal=False, base_index=None)` → RGB 목록 | **그늘 계산** — 밑색 하나 → 어두운 쪽부터 밝은 쪽 램프. 어두울수록 차갑게, `metal=True` 면 반대. `hue_step` 을 안 주면 칸 수에 맞춘 값(칸마다 10° 이하 · 처음 ~ 끝 36° 이하 — 4칸 10° · 6칸 7.2°) |
| `pick` | `pick(ramps, name, index)` | `c.pick` 과 같은 것(팔레트를 따로 들고 있을 때) |
| `guide` · `Guide` | `guide(폴더 \| template.json \| 사전)` | `g.y("eye")` · `g.y("baseline")` 줄, `g.box("head")` 상자, `g.point(…)`, `g.names()` 로 있는 이름 보기, `g.rows` · `g.cols` · `g.dots` · `g.keep` 가이드 PNG 의 선 · 점 · 지키는 자리 |
| `load_ramps` · `Ramps` | `load_ramps("palettes/x.json")` | 팔레트 읽기. `r.names()` · `r.ramp(이름)` · `r.colors()` |
| `outline` | `outline(arr, mode, *, ramps=None, light="top_left", where="outside", color=None, width=1)` | 그림 한 장(배열)에 외곽선. 겹이 없을 때 |
| `shapes` | `shapes.box` · `dot` · `line` · `disc` · `ring` · `round_box` · `ellipse` · `drop` · `flood` · `paint` · `to_image` | 불리언 마스크를 돌려주는 도형 함수. `Layer` 메서드가 이것을 부른다 |

## 지킬 것

- **반투명은 만들지 않는다.** 알파가 255 가 아닌 색은 거절된다. 지울 때는 `erase`.
- 가이드 색(`#FF00FF` · `#00FFFF` · `#FFFF00`)을 그림에 쓰지 않는다 — `report()` 와 `check` 가 잡는다.
- 화풍을 입힌 밑판(`template render … --profile P`)을 쓰면 `Canvas` 가 그 게임 팔레트를 읽어 `c.pick` 이 되고, 팔레트 밖 색을 `report()` 가 알린다.
- 같은 그림을 색만 바꿔 여러 벌 내려면 그리기 함수의 색 상수만 바꿔 다시 돌린다 — 두 벌을 한 비교판(`sheet --in a/ b/`)에 놓고 고르게 한다.
