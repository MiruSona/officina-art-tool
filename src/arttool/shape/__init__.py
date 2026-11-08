"""`arttool.shape` — 도형 + 재질 명세를 화풍 규칙으로 도트로 그리는 렌더러 (2026-11-08 도형 렌더러 설계).

    from arttool.shape import load, render
    spec = load("Example/slime.shape.json")
    arr, report = render(spec, "left")
"""

from .kit import assemble
from .render import render
from .score import similarity
from .spec import Spec, load, parse
from .template import expand, expand_template

__all__ = ["Spec", "assemble", "expand", "expand_template", "load", "parse", "render", "similarity"]
