"""`arttool.draw` — 도트를 코드로 그리는 공개 모듈 (2026-10-04 개선 설계 6-5 · 10-4 길 ⓐ).

스킬 예시 스크립트가 이 이름들을 부른다. 이름을 바꾸면 `tests/test_skill_scripts.py` 가 깨진다.

    from arttool.draw import Canvas
    c = Canvas(template="work/guide/")
    c["body"].round_box(10, 12, 22, 30, c.pick("skin", 3), r=2)
    c.outline("selout")
    print(c.report()["warnings"])
    c.save("work/set/")
"""

from ..palette import Ramps, load_ramps, shade
from . import shapes
from .canvas import Canvas, Layer, pick
from .guide import Guide, guide
from .outline import outline

__all__ = ["Canvas", "Layer", "Guide", "Ramps", "guide", "load_ramps", "outline", "pick", "shade", "shapes"]
