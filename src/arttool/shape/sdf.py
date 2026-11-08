"""거리 함수(SDF) — 점에서 도형 표면까지의 거리. 안쪽이면 음수 (도형 렌더러 설계 2-2 · 3절).

점 묶음은 (N, 3) float 배열이다. 도형 하나는 `Prim` 으로, 묶음(group)은 읽을 때 이미 풀려 있다.
광선 따라가기(sphere tracing)는 「이 점에서 이만큼은 아무것도 없다」를 믿고 그만큼 나아가므로
거리는 실제보다 크면 안 된다. 타원체만 근사라 렌더러가 걸음을 조금 줄여 쓴다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

OPS = ("union", "smooth", "subtract")


def rotation(deg) -> np.ndarray:
   """[x, y, z] 도 → 3×3 회전 행렬. x 축 → y 축 → z 축 차례로 돌린다 (R = Rz · Ry · Rx)."""
   rx, ry, rz = (math.radians(float(v)) for v in deg)
   cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
   x = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
   y = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
   z = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
   return z @ y @ x


@dataclass
class Prim:
   """풀린 도형 하나. rot · pos 는 모델 좌표 기준 최종 값(묶음까지 곱한 것)."""

   kind: str
   params: dict
   material: str
   op: str = "union"
   k: float = 0.0
   rot: np.ndarray = field(default_factory=lambda: np.eye(3))
   pos: np.ndarray = field(default_factory=lambda: np.zeros(3))
   name: str = ""

   def local(self, p: np.ndarray) -> np.ndarray:
      """모델 좌표 점 → 이 도형 좌표. (p − pos) · R  (= Rᵀ(p − pos) 를 행 벡터로)."""
      return (p - self.pos) @ self.rot

   def distance(self, p: np.ndarray) -> np.ndarray:
      return KINDS[self.kind](self.local(p), self.params)


def _sphere(p, a):
   return np.linalg.norm(p, axis=1) - a["r"]


def _ellipsoid(p, a):
   r = np.asarray(a["radii"], dtype=float)
   k0 = np.linalg.norm(p / r, axis=1)
   k1 = np.linalg.norm(p / (r * r), axis=1)
   # 가운데 한 점(k1 = 0)은 가장 짧은 반지름만큼 안쪽이다.
   safe = np.where(k1 > 1e-9, k1, 1.0)
   return np.where(k1 > 1e-9, k0 * (k0 - 1.0) / safe, -r.min())


def _capsule(p, a):
   half = a["length"] / 2.0
   q = p.copy()
   q[:, 1] -= np.clip(p[:, 1], -half, half)
   return np.linalg.norm(q, axis=1) - a["r"]


def _box(p, a):
   b = np.asarray(a["size"], dtype=float) / 2.0
   r = float(a.get("round", 0.0))
   q = np.abs(p) - (b - r)
   outside = np.linalg.norm(np.maximum(q, 0.0), axis=1)
   inside = np.minimum(q.max(axis=1), 0.0)
   return outside + inside - r


def lathe_polygon(profile) -> np.ndarray:
   """단면 [[반지름, 높이], …] → 축까지 닫은 다각형 (M, 2). 처음 · 끝이 축 위가 아니면 축 위 점을 더한다."""
   pts = [(float(r), float(y)) for r, y in profile]
   if pts[0][0] != 0.0:
      pts.insert(0, (0.0, pts[0][1]))
   if pts[-1][0] != 0.0:
      pts.append((0.0, pts[-1][1]))
   return np.array(pts, dtype=float)


def polygon_distance(q: np.ndarray, poly: np.ndarray) -> np.ndarray:
   """2D 점 (N, 2) → 닫힌 다각형까지 부호 있는 거리. 변마다 가장 가까운 거리 + 교차 수로 안팎."""
   d = np.sum((q - poly[0]) ** 2, axis=1)
   sign = np.ones(len(q))
   n = len(poly)
   for i in range(n):
      vi, vj = poly[i], poly[i - 1]
      e = vj - vi
      w = q - vi
      t = np.clip((w @ e) / max(float(e @ e), 1e-12), 0.0, 1.0)
      b = w - np.outer(t, e)
      d = np.minimum(d, np.sum(b * b, axis=1))
      c1 = q[:, 1] >= vi[1]
      c2 = q[:, 1] < vj[1]
      c3 = e[0] * w[:, 1] > e[1] * w[:, 0]
      flip = (c1 & c2 & c3) | (~c1 & ~c2 & ~c3)
      sign = np.where(flip, -sign, sign)
   return sign * np.sqrt(d)


def _lathe(p, a):
   poly = a["_poly"]
   q = np.stack([np.hypot(p[:, 0], p[:, 2]), p[:, 1]], axis=1)
   return polygon_distance(q, poly)


def _extrude(p, a):
   """돌출(extrude) : xy 평면의 2D 다각형을 z 로 두께 `depth` 만큼 민 판. 앞 · 뒤 모서리를 반지름 `round` 로 둥글린다.

   앞에서 보면 실루엣이 다각형 그대로다(z = 0 단면에서 거리가 2D 거리와 같다). 둥근 띠 안쪽 칸만 노멀이 바깥으로 기울어
   빛 쪽 가장자리는 밝고 그늘 쪽 가장자리는 어두워진다. round 가 다각형 안쪽 반지름보다 크면 앞면 전체가 둥근 베개가 된다.
   """
   d2 = polygon_distance(p[:, :2], a["_poly"])
   r = a["round"]
   wx = d2 + r
   wy = np.abs(p[:, 2]) - (a["depth"] / 2.0 - r)
   outside = np.hypot(np.maximum(wx, 0.0), np.maximum(wy, 0.0))
   inside = np.minimum(np.maximum(wx, wy), 0.0)
   return outside + inside - r


def _cone(p, a):
   """원뿔대 : y 축, 바닥(y = 0) 반지름 `r`, 꼭대기(y = height) 반지름 `top`(기본 0 = 뾰족). 회전체로 셈한다."""
   return polygon_distance(np.stack([np.hypot(p[:, 0], p[:, 2]), p[:, 1]], axis=1), a["_poly"])


KINDS = {"sphere": _sphere, "ellipsoid": _ellipsoid, "capsule": _capsule, "box": _box, "lathe": _lathe,
         "extrude": _extrude, "cone": _cone}


def smooth_min(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
   """둥글게 합치기 (다항식 smin). k = 이음매 너비(픽셀)."""
   if k <= 0:
      return np.minimum(a, b)
   h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
   return b * (1 - h) + a * h - k * h * (1 - h)


def scene(prims: list[Prim], p: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
   """여러 도형을 차례로 합친 거리와, 점마다 가장 가까운 「더하는」 도형 번호.

   op 는 앞까지 합친 몸과 합치는 법이다. 첫 도형의 op 는 union 으로 본다.
   재질은 파내기(subtract)가 아닌 도형 가운데 자기 거리가 가장 작은 것을 따른다. 그 거리는 뒤에 오는 파내기로 깎은 값이다.
   """
   total = None
   owner = np.full(len(p), -1, dtype=np.int64)
   best = np.full(len(p), np.inf)
   for i, prim in enumerate(prims):
      d = prim.distance(p)
      if prim.op != "subtract":
         closer = d < best
         best = np.where(closer, d, best)
         owner = np.where(closer, i, owner)
      if total is None:
         total = d if prim.op != "subtract" else np.full(len(p), np.inf)
      elif prim.op == "union":
         total = np.minimum(total, d)
      elif prim.op == "smooth":
         total = smooth_min(total, d, prim.k)
      else:
         total = np.maximum(total, -d)
         # 파낸 자리는 앞 도형 재질도 같이 파낸다 — 뒤에 놓인 판이 파낸 구멍으로 보여야 한다 (부품 사전 2-6절)
         best = np.maximum(best, -d)
   if total is None:
      total = np.full(len(p), np.inf)
   return total, owner
