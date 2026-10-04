"""화풍 뽑기 보강 시험 — 실물 시험 #4 ~ #12 · 리뷰 R1-M4 · R2 의심 ④. 그림은 모두 코드로 만든 합성 그림이다."""

from __future__ import annotations

import colorsys
import json
import time
import tracemalloc

import numpy as np
import pytest
import yaml

from arttool import cli, errors, image, palette
from arttool.style import extract, output, ramps
from arttool.style.light import estimate_light

from test_style_extract import INK, VARIANTS, _refs, _run, character, make_ramp


def _args(folder, out, *more):
   return cli.build_parser().parse_args(["style", "extract", "--in", str(folder), "--out", str(out), *more])


def _hsv(h, s, v):
   r, g, b = colorsys.hsv_to_rgb((h % 360) / 360, s, v)
   return round(r * 255), round(g * 255), round(b * 255)


# --- #4 빛 : 같은 램프 안에서만 ---


def test_flat_icon_parts_are_not_light():
   """위는 어두운 남색, 아래는 밝은 노랑 — 평면으로 칠한 서로 다른 두 부분. 옛 셈은 「아래」 라 했다."""
   arr = image.new(24, 24)
   arr[2:12, 4:20] = (30, 40, 120, 255)
   arr[12:22, 4:20] = (250, 220, 90, 255)
   assert estimate_light(arr)["light"] == "unknown"


def test_light_ignores_black_outline_and_reads_each_ramp():
   """두 램프가 각자 왼쪽 위가 밝으면 왼쪽 위. 램프끼리 밝기가 크게 달라도(밝은 노랑 머리 · 어두운 파랑 몸) 안 흔들린다."""
   arr = character(outline=INK, red=make_ramp(50), blue=make_ramp(230))
   assert estimate_light(arr)["light"] == "top_left"


# --- #7 램프 색조 사슬 ---


def test_hue_span():
   assert ramps.hue_span([350, 10, 20]) == 30
   assert ramps.hue_span([0]) == 0
   assert ramps.join_arcs((350.0, 10.0), (10.0, 10.0)) == (350.0, 30.0)     # 0° 를 건너 잇는다
   assert ramps.join_arcs((0.0, 30.0), (10.0, 5.0)) == (0.0, 30.0)          # 안에 든 호


def test_hue_chain_is_cut_at_span():
   """맞닿은 색 여섯이 칸마다 색조 20° 씩 (처음 ~ 끝 100°). 이웃끼리는 다 이어지지만 한 램프는 40° 를 못 넘는다."""
   colors = [_hsv(330 + 20 * i, 0.6, 0.4 + 0.1 * i) for i in range(6)]
   arr = image.new(36, 4)
   for i, c in enumerate(colors):
      arr[:, i * 6:(i + 1) * 6] = (*c, 255)
   maps = [ramps.key_map(arr)]
   keep = {k for k in np.unique(maps[0]).tolist() if k >= 0}
   _usage, _images, pixels = ramps.usage_of(maps)
   groups = ramps.group_colors(keep, ramps.touching_pairs(maps, keep), pixels)
   assert len(groups) >= 2
   for group in groups:
      assert ramps.hue_span([ramps.hue_sat(ramps.to_rgb(k))[0] for k in group]) <= ramps.HUE_SPAN + 1e-6


# --- #6 검정은 늘 따로 ---


def test_black_never_becomes_a_ramp(tmp_path):
   """외곽선이 없는 그림에 검정 눈 · 거의 검정 칸이 있어도 검정 램프가 안 생기고 outline_candidate 로 빠진다."""
   refs = tmp_path / "refs"
   refs.mkdir()
   for i, extra in enumerate(VARIANTS):
      arr = character(**extra)
      arr[10:12, 12:14] = (0, 0, 0, 255)
      arr[10:12, 18:20] = (8, 6, 6, 255)
      image.save(refs / f"hero{i}.png", arr)
   _code, out, report = _run(tmp_path, refs, "--ramp-len", "5", "--max-colors", "64")
   for ramp in report["palette"]["ramps"]:
      assert not any(max(palette.parse_hex(c)) <= 24 for c in ramp["colors"])
   assert report["palette"]["outline_candidate"] == "#000000"
   raw = json.loads((out / "refs_palette.json").read_text(encoding="utf-8"))
   assert raw["outline"] == "#000000" or raw.get("outline_candidate") == "#000000"
   palette.load_ramps(out / "refs_palette.json")


# --- #5 상한 · R2 의심 ④ merged ---


def test_default_max_colors_is_64(tmp_path):
   args = _args(tmp_path, tmp_path / "o")
   args.max_colors = None
   assert extract._options(args)["max_colors"] == extract.DEFAULT_MAX_COLORS == 64


def test_cap_warning_hints_by_kind(tmp_path):
   """램프가 많은데 상한이 작으면 palette_cap 경고에 「종류별로 나눠 뽑는다」 가 붙는다."""
   refs = tmp_path / "refs"
   refs.mkdir()
   for i in range(5):
      arr = image.new(48, 48)
      for j, base in enumerate((0, 60, 120, 180, 240, 300)):
         ramp = make_ramp(base, steps=5, step=6)
         for k, c in enumerate(ramp):
            arr[j * 8:(j + 1) * 8, k * 8 + i % 2:(k + 1) * 8 + i % 2] = (*c, 255)
      image.save(refs / f"t{i}.png", arr)
   _code, _out, report = _run(tmp_path, refs, "--ramp-len", "5", "--max-colors", "6")
   cap = next(w for w in report["warnings"] if w["rule"] == "palette_cap")
   assert "종류별" in cap["detail"] and cap["items"]
   assert report["palette"]["removed_colors"] >= extract.CAP_HINT


def test_merged_only_points_into_palette(tmp_path):
   """잡색 합치기 · 길이 맞추기 줄은 끝 색까지 따라가 적고, 끝 색이 팔레트에 없는 줄(뺀 램프 안)은 뺀다."""
   refs = tmp_path / "noisy"
   refs.mkdir()
   rng = np.random.default_rng(7)
   for i, extra in enumerate(VARIANTS):
      arr = character(**extra)
      ys, xs = np.nonzero(arr[:, :, 3] > 0)
      for j in rng.choice(len(ys), size=len(ys) // 20, replace=False):
         arr[ys[j], xs[j], 0] = np.clip(int(arr[ys[j], xs[j], 0]) + 2, 0, 255)
      image.save(refs / f"hero{i}.png", arr)
   _code, _out, report = _run(tmp_path, refs, "--ramp-len", "5", "--max-colors", "6")
   pal = report["palette"]
   kept = {c for r in pal["ramps"] for c in r["colors"]}
   assert pal["noise_merged"] > len(pal["merged"]) > 0         # 뺀 파랑 램프로 간 줄은 빠졌다
   assert all(m["to"] in kept and m["from"] not in kept for m in pal["merged"])
   assert pal["merge_table"] == {m["from"]: m["to"] for m in pal["merged"]}


def test_merge_chain_is_followed():
   moves = [(1, 2, "noise"), (2, 3, "ramp_len"), (4, 5, "noise")]
   got = ramps._merge_report(moves, {3})
   assert [(m["from"], m["to"]) for m in got] == [(ramps.to_hex(1), ramps.to_hex(3)), (ramps.to_hex(2), ramps.to_hex(3))]


# --- 한 색 램프 ---


def test_single_color_ramp_is_marked(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs, red=[(200, 40, 60)] * 5)        # 머리가 한 색
   _code, out, report = _run(tmp_path, refs, "--ramp-len", "5")
   singles = report["palette"]["singles"]
   assert len(singles) == 1
   raw = json.loads((out / "refs_palette.json").read_text(encoding="utf-8"))
   assert raw["singles"] == singles
   assert palette.load_ramps(out / "refs_palette.json").ramp_len == 5


# --- #8 견본 칸 ---


def test_swatch_cell_is_big_enough():
   assert output.CELL >= 16
   art = output.swatch([{"colors": [1, 2, 3], "padded": 0}], None, [], 1)
   assert art.shape[0] >= 16


# --- #9 종류별 뽑기 ---


def test_by_folder_writes_each_kind_and_summary(tmp_path):
   root = tmp_path / "ref"
   _refs(root / "char")
   _refs(root / "char_ink", outline=INK)
   out = tmp_path / "o"
   args = _args(root, out, "--ramp-len", "5")
   args.by_folder = True
   result = extract.run(args)
   assert [r["kind"] for r in result["kinds"]] == ["char", "char_ink"]
   assert "black" in {r["outline"] for r in result["kinds"]}
   assert (out / "ref_char_report.json").is_file() and (out / "ref_char_ink_palette.json").is_file()
   saved = json.loads((out / "ref_kinds.json").read_text(encoding="utf-8"))
   assert saved["kinds"] == result["kinds"]


def test_by_folder_without_subfolders_is_usage_error(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs)
   args = _args(refs, tmp_path / "o")
   args.by_folder = True
   with pytest.raises(errors.UsageError):
      extract.run(args)


def test_split_tables_suggest_by_folder(tmp_path):
   """외곽선 표가 반반으로 갈리면 by_kind 경고 · 하위 폴더가 있으면 그 목록을 준다 · check.warn 제안은 보류 (#11)."""
   root = tmp_path / "mix"
   root.mkdir()
   for i, extra in enumerate(VARIANTS):
      image.save(root / f"a{i}.png", character(**extra))
      image.save(root / f"b{i}.png", character(**extra, outline=INK))
   _refs(root / "sub")
   _code, out, report = _run(tmp_path, root)
   assert report["outline"]["pick"] is None
   hint = next(w for w in report["warnings"] if w["rule"] == "by_kind")
   assert "--by-folder" in hint["detail"] and len(hint["items"]) == 1
   assert report["held"] and "outline" in report["held"]
   text = (out / "mix_profile.yaml").read_text(encoding="utf-8")
   assert "check" not in (yaml.safe_load(text) or {})
   assert "판정 보류" in text


def test_mostly_not_pixel_holds_proposals(tmp_path):
   """도트 그림이 5장 넘어도 도트가 아닌 그림이 절반을 넘으면 문턱 제안을 안 낸다 (실물 : 19장으로 {64: 154})."""
   from test_style_extract import bilinear
   refs = tmp_path / "most"
   _refs(refs)
   for i in range(6):
      image.save(refs / f"blur{i}.png", bilinear(character(**VARIANTS[i % 5])))
   _code, out, report = _run(tmp_path, refs)
   assert report["summary"]["pixel"] == 5 and report["summary"]["not_pixel"] == 6
   assert "절반" in report["held"]
   assert "check" not in (yaml.safe_load((out / "most_profile.yaml").read_text(encoding="utf-8")) or {})


def test_unknown_light_alone_is_not_split():
   summary = {"outline": {"total": 0, "pick": (None, 0)},
              "light": {"table": {"unknown": 8, "top_left": 3}, "pick": (None, 8), "total": 11}}
   assert extract._split_tables(summary) == []
   summary["light"]["table"] = {"unknown": 8, "top_left": 3, "bottom": 3}
   assert extract._split_tables(summary) == ["light"]


# --- #10 도트 아님 색 문턱 ---


def test_small_image_with_many_colors_is_not_pixel():
   arr = image.new(60, 60)
   for i in range(150):
      y, x = divmod(i, 15)
      arr[y * 4:(y + 1) * 4, x * 4:(x + 1) * 4] = (i, 255 - i, (i * 7) % 256, 255)
   why, seen = extract.not_pixel_reasons(arr)
   assert seen["colors"] == 150 and why and "128" in why[0]


# --- R1-M4 경고 꼴 ---


def test_warnings_are_rule_dicts(tmp_path):
   refs = tmp_path / "refs"
   _refs(refs, count=3)
   (refs / "broken.png").write_bytes(b"not a png")
   _code, _out, report = _run(tmp_path, refs)
   assert report["warnings"]
   for w in report["warnings"]:
      assert set(w) >= {"rule", "ok", "detail", "items"} and w["ok"] is False
   assert {"few_images", "unreadable"} <= {w["rule"] for w in report["warnings"]}


# --- 모르는 외곽선 판정 값 ---


def test_unknown_outline_verdict_is_counted(tmp_path, monkeypatch):
   real = extract.measure_outline

   def fake(*a, **kw):
      return {**real(*a, **kw), "verdict": "zigzag"}     # 어떤 프로필도 안 받는 값

   monkeypatch.setattr(extract, "measure_outline", fake)
   refs = tmp_path / "refs"
   _refs(refs)
   code, out, report = _run(tmp_path, refs)
   assert code == errors.EXIT_OK
   assert report["outline"]["table"] == {"zigzag": 5} and report["outline"]["pick"] == "zigzag"
   frag = yaml.safe_load((out / "refs_profile.yaml").read_text(encoding="utf-8"))
   assert "outline" not in frag.get("style", {})            # 프로필이 안 받는 값이라 안 적는다


# --- #12 --force 메모리 · 시간 ---


def photo(seed: int, side: int = 1024) -> np.ndarray:
   """도트가 아닌 큰 그림 : 부드러운 그러데이션 + 잡음 (색 수만 가지). 위쪽 1/8 은 투명 — 배경으로 안 보이게."""
   rng = np.random.default_rng(seed)
   yy, xx = np.mgrid[0:side, 0:side].astype(np.float32) / side
   arr = np.empty((side, side, 4), dtype=np.uint8)
   arr[:, :, 0] = np.clip(255 * xx + rng.normal(0, 6, (side, side)), 0, 255)
   arr[:, :, 1] = np.clip(255 * yy + rng.normal(0, 6, (side, side)), 0, 255)
   arr[:, :, 2] = np.clip(128 + 100 * np.sin(6 * xx * yy) + rng.normal(0, 6, (side, side)), 0, 255)
   arr[:, :, 3] = 255
   arr[: side // 8] = 0
   return arr


def test_force_on_big_photos_keeps_memory_small(tmp_path):
   refs = tmp_path / "photos"
   refs.mkdir()
   for i in range(6):
      image.save(refs / f"p{i}.png", photo(i))
   tracemalloc.start()
   start = time.perf_counter()
   code, _out, report = _run(tmp_path, refs, "--force")
   took = time.perf_counter() - start
   _now, peak = tracemalloc.get_traced_memory()
   tracemalloc.stop()
   assert code == errors.EXIT_OK
   assert report["summary"]["not_pixel"] == 6
   assert all(row.get("sampled") for row in report["images"])
   assert report["palette"]["sampled"] == 6 and report["palette"]["ramps"]
   assert peak < 300 * 2 ** 20, f"최대 메모리 {peak / 2 ** 20:.0f}MB"
   assert took < 30, f"{took:.1f}초"
