"""`style extract` 시험 (설계 9-6). 그림은 모두 코드로 만든 합성 그림이다."""

from __future__ import annotations

import colorsys
import hashlib
import json
import time

import numpy as np
import pytest
import yaml
from PIL import Image

from arttool import cli, errors, image, palette
from arttool.profile import load_profile


def make_ramp(base: float, steps: int = 5, step: float = 8.0) -> list[tuple[int, int, int]]:
   """어두운 → 밝은, 칸마다 색조 +step 도. 처음 ~ 끝 색조 차가 램프 상한(40°) 안에 들게 기본 8 도."""
   out = []
   for i in range(steps):
      v = 0.3 + 0.65 * i / (steps - 1)
      s = 0.75 - 0.25 * i / (steps - 1)
      r, g, b = colorsys.hsv_to_rgb(((base + i * step) % 360) / 360, s, v)
      out.append((round(r * 255), round(g * 255), round(b * 255)))
   return out


RED = make_ramp(330)
BLUE = make_ramp(190)
INK = (16, 16, 16)


def _shade(arr, mask, colors, cx, cy, r):
   """왼쪽 위가 밝게 띠로 칠한다."""
   ys, xs = np.nonzero(mask)
   t = (-(xs - cx) - (ys - cy)) / (r * 1.4142)
   idx = np.clip(((t + 1) / 2 * len(colors)).astype(int), 0, len(colors) - 1)
   for y, x, i in zip(ys, xs, idx):
      arr[y, x] = (*colors[i], 255)


def character(w=32, h=32, cx=16, cy=12, r=9, outline=None, red=RED, blue=BLUE):
   """머리(빨강 램프 원판) + 몸(파랑 램프 네모). outline 이면 둘레 1칸을 그 색으로."""
   arr = image.new(w, h)
   yy, xx = np.mgrid[0:h, 0:w]
   _shade(arr, (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r, red, cx, cy, r)
   body = (yy >= cy + r - 2) & (yy <= h - 3) & (xx >= cx - 6) & (xx <= cx + 6)
   _shade(arr, body, blue, cx, cy + r + 3, 8)
   if outline is not None:
      solid = arr[:, :, 3] > 0
      ring = np.zeros_like(solid)
      for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
         ring |= np.roll(solid, (dy, dx), axis=(0, 1))
      arr[ring & ~solid] = (*outline, 255)
   return arr


VARIANTS = [dict(), dict(cx=15, cy=13, r=10), dict(cx=17, cy=11, r=8), dict(w=40, h=40, cx=20, cy=15, r=12), dict(cx=16, cy=12, r=7)]


def background():
   arr = image.new(160, 160, (0, 0, 0, 255))
   greens = [(30, 90, 30), (40, 120, 40), (60, 150, 50), (90, 180, 70)]
   for i in range(160):
      arr[i, :, :3] = greens[(i // 10) % 4]
   return arr


def bilinear(arr, factor=4):
   img = Image.fromarray(arr, "RGBA").resize((arr.shape[1] * factor, arr.shape[0] * factor), Image.BILINEAR)
   return np.array(img)


def _refs(folder, count=5, **kw):
   for i, extra in enumerate(VARIANTS[:count]):
      image.save(folder / f"hero{i}.png", character(**{**extra, **kw}))


def _run(tmp_path, folder, *more):
   out = tmp_path / "style"
   code = cli.main(["style", "extract", "--in", str(folder), "--out", str(out), *more])
   name = folder.name
   report = json.loads((out / f"{name}_report.json").read_text(encoding="utf-8")) if (out / f"{name}_report.json").is_file() else None
   return code, out, report


def _ramp_sets(report):
   return sorted(sorted(set(r["colors"])) for r in report["palette"]["ramps"])


def _expected(*ramps):
   return sorted(sorted({palette.to_hex(c) for c in ramp}) for ramp in ramps)


def test_two_ramps_come_back(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs)
   code, out, report = _run(tmp_path, refs, "--ramp-len", "5")
   assert code == errors.EXIT_OK
   assert report["status"] == "ok", report["warnings"]
   assert _ramp_sets(report) == _expected(RED, BLUE)
   assert report["palette"]["padded"] == [] and report["palette"]["merged"] == []
   # 램프는 어두운 → 밝은 순
   for ramp in report["palette"]["ramps"]:
      assert ramp["colors"][0] in ("#4C1330", "#13434C")
   assert 6 <= report["palette"]["hue_step"] <= 10

   loaded = palette.load_ramps(out / "refs_palette.json")
   assert loaded.ramp_len == 5 and len(loaded.names()) == 2
   raw = json.loads((out / "refs_palette.json").read_text(encoding="utf-8"))
   assert set(raw) >= {"version", "name", "ramp_len", "outline", "ramps", "comment", "usage", "hue_step"}
   assert abs(sum(raw["usage"].values()) - 1.0) < 0.01
   assert (out / "refs_swatch.png").is_file()


def test_noise_is_merged(tmp_path):
   clean, noisy = tmp_path / "clean", tmp_path / "noisy"
   _refs(clean)
   rng = np.random.default_rng(7)
   noisy.mkdir()
   for i, extra in enumerate(VARIANTS):
      arr = character(**extra)
      ys, xs = np.nonzero(arr[:, :, 3] > 0)
      pick = rng.choice(len(ys), size=len(ys) // 25, replace=False)
      for j in pick:
         ch = int(rng.integers(0, 3))
         arr[ys[j], xs[j], ch] = np.clip(int(arr[ys[j], xs[j], ch]) + int(rng.choice([-2, 2])), 0, 255)
      image.save(noisy / f"hero{i}.png", arr)
   _code, _out, base = _run(tmp_path, clean, "--ramp-len", "5")
   _code, _out, got = _run(tmp_path, noisy, "--ramp-len", "5")
   assert _ramp_sets(got) == _ramp_sets(base)
   assert got["palette"]["noise_merged"] > 0
   assert all(m["why"] == "noise" for m in got["palette"]["merged"])


def test_long_ramp_merges_one(tmp_path):
   refs = tmp_path / "refs"
   long_red = make_ramp(330, steps=7, step=6)
   _refs(refs, red=long_red, r=12, w=40, h=44, cx=20, cy=14)
   _code, _out, report = _run(tmp_path, refs, "--ramp-len", "6")
   merged = [m for m in report["palette"]["merged"] if m["why"] == "ramp_len"]
   assert len(merged) == 1
   assert {len(r["colors"]) for r in report["palette"]["ramps"]} == {6}


def test_short_ramp_is_padded(tmp_path):
   refs = tmp_path / "refs"
   short = make_ramp(330, steps=3, step=15)
   _refs(refs, red=short)
   code, out, report = _run(tmp_path, refs, "--ramp-len", "6")
   assert code == errors.EXIT_OK
   red = next(r for r in report["palette"]["ramps"] if palette.to_hex(short[0]) in r["colors"])
   assert red["padded"] == 3
   assert red["colors"][2:] == [palette.to_hex(short[-1])] * 4      # 밝은 쪽 끝 되풀이
   assert {"ramp": red["name"], "cells": 3} in report["palette"]["padded"]
   palette.load_ramps(out / "refs_palette.json")       # 되풀이 칸이 있어도 읽힌다


def test_black_outline_fills_palette_outline(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs, outline=INK)
   code, out, report = _run(tmp_path, refs, "--ramp-len", "5")
   assert report["outline"]["pick"] == "black"
   assert report["palette"]["outline"] == "#101010"
   assert _ramp_sets(report) == _expected(RED, BLUE)       # 외곽선 색은 램프에 안 들어간다
   frag = yaml.safe_load((out / "refs_profile.yaml").read_text(encoding="utf-8"))
   assert frag["palette"]["outline"] == "#101010"
   assert frag["style"]["outline"] == "black"
   assert palette.load_ramps(out / "refs_palette.json").outline == INK


def test_solid_outline_fills_palette_outline(tmp_path):
   """판정이 solid(검정 아닌 한 색 선)면 외곽선 칸에 가장 많이 쓰인 색이 램프 파일 · 조각 palette.outline 에 들어간다."""
   refs = tmp_path / "refs"
   line = (70, 40, 50)
   _refs(refs, outline=line)
   _code, out, report = _run(tmp_path, refs, "--ramp-len", "5")
   assert report["outline"]["pick"] == "solid"
   assert report["palette"]["outline"] == "#462832"
   assert _ramp_sets(report) == _expected(RED, BLUE)       # 외곽선 색은 램프에 안 들어간다
   assert all(row["edge_color"] == "#462832" for row in report["images"])
   frag = yaml.safe_load((out / "refs_profile.yaml").read_text(encoding="utf-8"))
   assert frag["palette"]["outline"] == "#462832"
   assert frag["style"]["outline"] == "solid"
   assert palette.load_ramps(out / "refs_palette.json").outline == line


@pytest.mark.parametrize("steps", [5, 6])
@pytest.mark.parametrize("base", ["#B03030", "#3C8C50", "#3D5C9B", "#F2C8A0"])
def test_default_shade_ramp_comes_back_as_one(tmp_path, base, steps):
   """`shade` 기본값으로 그린 5 · 6칸 램프 그림 → style extract → 램프 하나로 돌아온다.
   옛 기본 20° 는 처음 ~ 끝이 램프 상한(40°)을 넘어 둘로 갈렸고, 10° 고정도 빨강 5칸(40.7°) · 6칸(50°)에서 갈렸다."""
   ramp = palette.shade(base, steps)
   refs = tmp_path / "refs"
   _refs(refs, red=ramp, blue=ramp)
   _code, _out, report = _run(tmp_path, refs, "--ramp-len", str(steps))
   assert _ramp_sets(report) == _expected(ramp)


def test_auto_hue_step_keeps_span_under_ramp_cap():
   """기본 걸음은 칸 수 2 ~ 8 · 아무 밑색에서도 처음 ~ 끝 색조 차가 램프 상한 40° 아래다."""
   from arttool.checks import LOW_SAT, hue_sat
   from arttool.style.ramps import HUE_SPAN, hue_span

   rng = np.random.default_rng(0)
   for _ in range(200):
      base = tuple(int(v) for v in rng.integers(30, 230, 3))
      for steps in range(2, 9):
         hues = [h for h, s in (hue_sat(c) for c in palette.shade(base, steps)) if s >= LOW_SAT]
         assert hue_span(hues) <= HUE_SPAN, (base, steps)


def test_background_does_not_change_palette(tmp_path):
   refs, mixed = tmp_path / "refs", tmp_path / "mixed"
   _refs(refs)
   _refs(mixed)
   image.save(mixed / "field.png", background())
   _code, _out, base = _run(tmp_path, refs, "--ramp-len", "5")
   _code, _out, got = _run(tmp_path, mixed, "--ramp-len", "5")
   assert _ramp_sets(got) == _ramp_sets(base)
   assert got["summary"]["backgrounds"] == 1
   assert len(got["palette"]["background_colors"]) == 4

   _run(tmp_path, mixed, "--ramp-len", "5", "--with-backgrounds", "--name", "wide")
   wide = json.loads((tmp_path / "style" / "wide_report.json").read_text(encoding="utf-8"))
   assert len(wide["palette"]["ramps"]) == 3          # 배경 초록 램프가 더해진다


def test_blurry_only_gives_no_palette(tmp_path):
   refs = tmp_path / "blurry"
   refs.mkdir()
   for i, extra in enumerate(VARIANTS):
      image.save(refs / f"b{i}.png", bilinear(character(**extra)))
   code, out, report = _run(tmp_path, refs)
   assert code == errors.EXIT_OK
   assert report["status"] == "warn"
   assert report["summary"]["not_pixel"] == 5
   assert not (out / "blurry_palette.json").exists() and not (out / "blurry_swatch.png").exists()
   assert any("절반" in w["detail"] for w in report["warnings"])
   assert "palette" not in (yaml.safe_load((out / "blurry_profile.yaml").read_text(encoding="utf-8")) or {})

   code, out, forced = _run(tmp_path, refs, "--force")
   assert code == errors.EXIT_OK
   assert (out / "blurry_palette.json").is_file()


def test_few_images_warn_and_no_check_proposal(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs, count=3)
   _code, out, report = _run(tmp_path, refs)
   assert report["status"] == "warn"
   assert any("적다" in w["detail"] for w in report["warnings"])
   frag = yaml.safe_load((out / "refs_profile.yaml").read_text(encoding="utf-8"))
   assert "check" not in frag


def test_fragment_loads_as_profile(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs, outline=INK)
   for i in range(5):    # 크기 칸 하나에 5장 이상 → color_cap 제안이 나오게
      image.save(refs / f"extra{i}.png", character(**VARIANTS[i % 3], outline=INK))
   _code, out, report = _run(tmp_path, refs)
   text = (out / "refs_profile.yaml").read_text(encoding="utf-8")
   frag = yaml.safe_load(text)
   assert frag["check"]["warn"]["color_cap"]["table"] == {32: 11}
   prof_file = tmp_path / "game.yaml"
   prof_file.write_text("name: game\n" + text, encoding="utf-8")
   prof = load_profile(str(prof_file))
   assert prof.style["outline"] == "black"
   assert prof.palette["outline"] == "#101010"
   assert prof.palette["ramp_len"] == 6
   assert prof.color_cap_table()[32] == 11


def test_light_scale_skip_when_same_as_profile(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs)
   _code, out, report = _run(tmp_path, refs)
   assert report["light"]["pick"] == "top_left"
   text = (out / "refs_profile.yaml").read_text(encoding="utf-8")
   frag = yaml.safe_load(text)
   assert "light" not in frag.get("style", {})            # 기본 top_left 와 같다
   assert "style.light : top_left" in text                 # 주석으로는 남는다


def test_sources_untouched(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs)
   before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in refs.iterdir()}
   _run(tmp_path, refs)
   after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in refs.iterdir()}
   assert before == after


def test_profile_file_untouched(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs)
   prof = tmp_path / "game.yaml"
   prof.write_text("name: game\nstyle:\n  light: top_right\n", encoding="utf-8")
   before = prof.read_bytes()
   out = tmp_path / "style"
   assert cli.main(["style", "extract", "--in", str(refs), "--out", str(out), "--profile", str(prof)]) == errors.EXIT_OK
   assert prof.read_bytes() == before
   frag = yaml.safe_load((out / "refs_profile.yaml").read_text(encoding="utf-8"))
   assert frag["style"]["light"] == "top_left"            # 프로필(top_right)과 달라 적힌다


def test_usage_errors(tmp_path):
   refs, empty = tmp_path / "refs", tmp_path / "empty"
   _refs(refs, count=1)
   empty.mkdir()
   assert cli.main(["style", "extract", "--in", str(refs), "--out", str(refs)]) == errors.EXIT_USAGE
   assert cli.main(["style", "extract", "--in", str(empty), "--out", str(tmp_path / "o")]) == errors.EXIT_USAGE
   assert cli.main(["style", "extract", "--in", str(refs), "--out", str(tmp_path / "o"), "--name", "../x"]) == errors.EXIT_USAGE
   assert cli.main(["style", "extract", "--in", str(refs), "--out", str(tmp_path / "o"), "--ramp-len", "1"]) == errors.EXIT_USAGE
   assert cli.main(["style", "extract", "--in", str(tmp_path / "nope"), "--out", str(tmp_path / "o")]) == errors.EXIT_USAGE


def test_max_colors_removes_small_ramp(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs)
   _code, _out, report = _run(tmp_path, refs, "--ramp-len", "5", "--max-colors", "6")
   assert len(report["palette"]["ramps"]) == 1
   assert report["palette"]["ramps"][0]["name"] == "red"         # 몫이 큰 쪽이 남는다
   assert report["palette"]["removed_ramps"][0]["name"] == "blue"
   assert report["status"] == "warn"


def test_big_noise_image_is_fast(tmp_path):
   """색이 수십만 가지인 큰 그림 한 장이 비슷한 색 쌍 셈으로 늘어지지 않는다."""
   refs = tmp_path / "big"
   refs.mkdir()
   rng = np.random.default_rng(1)
   noise = rng.integers(0, 256, size=(512, 512, 4), dtype=np.uint8)
   noise[:, :, 3] = 255
   image.save(refs / "noise.png", noise)
   start = time.perf_counter()
   code, _out, report = _run(tmp_path, refs)
   assert code == errors.EXIT_OK
   assert time.perf_counter() - start < 3.0
   assert report["images"][0]["pixel"] is False
   assert "near_pairs" not in report["images"][0]          # 무거운 재기를 건너뛰었다


def test_color_count_matches_check():
   """빠른 색 세기가 검사 ④ 의 measure_colors 와 같은 값을 낸다 (반투명 · 투명 찌꺼기 포함)."""
   from arttool.checks.pixels import measure_colors
   from arttool.style.extract import count_colors
   rng = np.random.default_rng(3)
   arr = rng.integers(0, 256, size=(40, 40, 4), dtype=np.uint8)
   arr[::3, :, 3] = 0
   assert count_colors(arr) == measure_colors(arr)["colors"]


@pytest.mark.parametrize("mode, backgrounds", [("sprite", 0), ("background", 5)])
def test_mode_overrides_background_guess(tmp_path, mode, backgrounds):
   refs = tmp_path / "refs"
   _refs(refs)
   _code, _out, report = _run(tmp_path, refs, "--mode", mode)
   assert report["summary"]["backgrounds"] == backgrounds
