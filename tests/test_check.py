import numpy as np
import pytest

import helpers
from arttool import bake, check, image, jsonio
from arttool.errors import ArtToolError, UsageError
from arttool.sprite import normalize


def build(tmp_path, **extra):
   prof = helpers.tiny_profile(tmp_path, **extra)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   normalize.normalize(prof, raw, tmp_path / "build", ["walk"])
   return prof, tmp_path / "build"


def test_clean_build_passes(tmp_path):
   prof, out = build(tmp_path)
   report = check.run(prof, out)
   assert report["status"] == "ok"
   assert report["checked"]["frames"] == 8
   assert report["failed"] == []


def test_max_colors_fails(tmp_path):
   prof, out = build(tmp_path, **{"check.max_colors": 1})
   report = check.run(prof, out)
   assert report["status"] == "fail"
   assert "max_colors" in report["failed"]


def test_ramp_colors_fails(tmp_path):
   prof, out = build(tmp_path)
   sheet = image.load(out / "walk.png")
   sheet[13, 3] = (1, 2, 3, 255)
   image.save(out / "walk.png", sheet)
   report = check.run(prof, out)
   assert "ramp_colors" in report["failed"]
   rule = next(r for r in report["rules"] if r["rule"] == "ramp_colors")
   assert rule["items"][0]["color"] == "#010203"


def test_alpha_fails(tmp_path):
   prof, out = build(tmp_path)
   sheet = image.load(out / "walk.png")
   sheet[13, 3] = (27, 42, 74, 128)
   image.save(out / "walk.png", sheet)
   report = check.run(prof, out)
   assert "alpha" in report["failed"]


def test_baseline_fails(tmp_path):
   prof, out = build(tmp_path)
   sheet = image.load(out / "walk.png")
   sheet[15, 3] = (27, 42, 74, 255)
   image.save(out / "walk.png", sheet)
   report = check.run(prof, out)
   assert "baseline" in report["failed"]


def test_bbox_drift_fails(tmp_path):
   prof, out = build(tmp_path, **{"check.bbox_drift": 0})
   report = check.run(prof, out)
   assert "bbox_drift" in report["failed"]


def test_frame_size_mismatch(tmp_path):
   prof, out = build(tmp_path)
   other = helpers.tiny_profile(tmp_path, **{"canvas.frame": [8, 8], "canvas.baseline_y": 6, "canvas.center_x": 3.5})
   with pytest.raises(ArtToolError, match="프레임이 프로필과 다르다"):
      check.run(other, out)


def test_ramp_rule_skipped_without_file(tmp_path):
   prof, out = build(tmp_path, **{"palette.ramps_file": ""})
   report = check.run(prof, out)
   rule = next(r for r in report["rules"] if r["rule"] == "ramp_colors")
   assert rule["ok"] and "건너뛴다" in rule["detail"]


# --- 낱장 모드 ---


def loose_dir(tmp_path, count=3):
   """낱장 PNG 를 몇 장 쓴다. 색은 램프 안에 있는 것만 쓴다."""
   out = tmp_path / "loose"
   out.mkdir(parents=True, exist_ok=True)
   for index in range(count):
      image.save(out / f"icon_{index}.png", helpers.blob(8, 8))
   return out


def test_loose_folder_passes(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   assert report["status"] == "ok"
   assert report["checked"]["mode"] == "loose"
   assert report["checked"]["files"] == 3


def test_loose_single_png(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path) / "icon_0.png")
   assert report["status"] == "ok"
   assert report["checked"]["files"] == 1


def test_loose_reports_per_file_colors(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   rule = next(r for r in report["rules"] if r["rule"] == "max_colors")
   assert [i["where"] for i in rule["items"]] == ["icon_0.png", "icon_1.png", "icon_2.png"]
   assert rule["items"][0]["colors"] == 2


def test_loose_alpha_fails(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   out = loose_dir(tmp_path)
   arr = image.load(out / "icon_1.png")
   arr[3, 3] = (27, 42, 74, 128)
   image.save(out / "icon_1.png", arr)
   report = check.run(prof, out)
   assert "alpha" in report["failed"]


def test_loose_skips_baseline(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   for name in ("baseline", "bbox_drift"):
      rule = next(r for r in report["rules"] if r["rule"] == name)
      assert rule["ok"] and "낱장 모드" in rule["detail"]


def test_no_ramps_flag_marks_skipped(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path), no_ramps=True)
   assert report["skipped"] == ["baseline", "bbox_drift", "ramp_colors"]
   assert [r["rule"] for r in report["rules"] if r["rule"] == "ramp_colors"] == []


def test_loose_empty_folder_errors(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   empty = tmp_path / "빈폴더"
   empty.mkdir()
   with pytest.raises(ArtToolError, match="PNG"):
      check.run(prof, empty)


# --- 2026-10-04 새 검사 일곱 · 경고 틀 (설계 7절 · 9-4 끝) ---


def rules_of(report):
   return [w["rule"] for w in report["warnings"]]


def noise(w, h, seed=0):
   rng = np.random.default_rng(seed)
   colors = np.array([(200, 60, 50, 255), (60, 140, 200, 255), (240, 220, 120, 255), (40, 40, 60, 255)], dtype=np.uint8)
   return colors[rng.integers(0, 4, size=(h, w))]


def folder(tmp_path, pictures: dict, name="work"):
   out = tmp_path / name
   out.mkdir(parents=True, exist_ok=True)
   for file, arr in pictures.items():
      image.save(out / file, arr)
   return out


def write_template(tmp_path, **data):
   path = tmp_path / "guide" / "template.json"
   jsonio.write_json(path, {"version": 1, "name": "t", **data})
   return path


def test_warnings_do_not_touch_status_or_bake(tmp_path):
   """경고가 있어도 status ok · bake 통과 (설계 7-4)."""
   prof, out = build(tmp_path, **{"check.warn.near_colors.max_delta": 255, "check.warn.near_colors.min_pairs": 1})
   report = check.run(prof, out)
   assert report["status"] == "ok" and report["failed"] == [] and report["skipped"] == []
   assert "near_colors" in rules_of(report)
   assert report["must_failed"] == []
   jsonio.write_json(out / "check.json", report)
   assert bake.bake(prof, out, tmp_path / "unity")["check"] == "ok"


def test_warning_shape_matches_ui_check(tmp_path):
   prof, out = build(tmp_path, **{"check.warn.near_colors.max_delta": 255, "check.warn.near_colors.min_pairs": 1})
   for line in check.run(prof, out)["warnings"]:
      assert set(line) >= {"rule", "ok", "detail", "items"} and line["ok"] is False


def test_no_warn_turns_warnings_off(tmp_path):
   prof, out = build(tmp_path, **{"check.warn.near_colors.max_delta": 255, "check.warn.near_colors.min_pairs": 1})
   report = check.run(prof, out, warn=False)
   assert report["warnings"] == [] and report["warnings_off"] is True
   assert report["skipped"] == []


def test_enabled_false_turns_one_check_off(tmp_path):
   prof, out = build(tmp_path, **{"check.warn.near_colors.max_delta": 255, "check.warn.near_colors.min_pairs": 1, "check.warn.near_colors.enabled": False})
   assert "near_colors" not in rules_of(check.run(prof, out))


def test_bad_mode_is_usage_error(tmp_path):
   with pytest.raises(UsageError):
      check.run(helpers.tiny_profile(tmp_path), loose_dir(tmp_path), mode="sideways")


def test_integer_scale_mixed_in_loose_folder(tmp_path):
   canvas = image.new(80, 40)
   image.paste(canvas, image.scale_up(noise(16, 16, 3), 2), 2, 2)
   image.paste(canvas, noise(16, 16, 4), 56, 10)
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, folder(tmp_path, {"mixed.png": canvas}), no_ramps=True)
   line = next(w for w in report["warnings"] if w["rule"] == "integer_scale")
   assert line["items"][0]["scales"] == [1, 2]


def test_outline_against_style(tmp_path):
   arr = image.new(24, 24)
   arr[2:22, 2:22] = (200, 80, 60, 255)
   arr[2, 2:22] = arr[21, 2:22] = (0, 0, 0, 255)
   arr[2:22, 2] = arr[2:22, 21] = (0, 0, 0, 255)
   pics = folder(tmp_path, {"black.png": arr})
   report = check.run(helpers.tiny_profile(tmp_path, **{"style.outline": "selout"}), pics, no_ramps=True)
   line = next(w for w in report["warnings"] if w["rule"] == "outline")
   assert line["items"][0]["verdict"] == "black"
   unset = check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True)
   assert "outline" not in rules_of(unset)
   assert unset["info"][0]["items"][0]["verdict"] == "black"


def test_isolated_color_cap_near_colors_in_one_run(tmp_path):
   arr = image.new(34, 34)
   arr[1:33, 1:33] = (90, 120, 160, 255)
   for y in range(3, 33, 4):
      for x in range(3, 33, 4):
         arr[y, x] = (240, 220, 120, 255)
   arr[1:33, 30] = (92, 121, 158, 255)                     # ±2 잡색 한 줄
   for i in range(20):
      arr[16, 5 + i] = (10 * i, 50, 100, 255)              # 32px 에 20색 넘게
   pics = folder(tmp_path, {"a.png": arr})
   strict = {"check.warn.isolated.max_ratio": 0.03, "check.warn.near_colors.min_pairs": 1}
   report = check.run(helpers.tiny_profile(tmp_path, **strict), pics, no_ramps=True)
   assert {"isolated", "color_cap", "near_colors"} <= set(rules_of(report))
   cap = next(w for w in report["warnings"] if w["rule"] == "color_cap")["items"][0]
   assert cap["size"] == 32 and cap["cap"] == 16
   # 기본값(isolated 0.15 · near_colors 짝 20개 이상)이면 이 그림의 외톨이 6% · 짝 1개는 안 걸린다 (실물 시험 #17 · #19)
   plain = check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True)
   assert "isolated" not in rules_of(plain) and "near_colors" not in rules_of(plain)
   assert "color_cap" in rules_of(plain)


def test_near_colors_min_pairs(tmp_path):
   """짝이 min_pairs 개 이상이어야 걸린다."""
   arr = image.new(40, 4)
   for i in range(20):
      arr[0:2, 2 * i] = (10 * i, 100, 100, 255)
      arr[0:2, 2 * i + 1] = (10 * i + 2, 100, 100, 255)          # ±2 짝 20개
   pics = folder(tmp_path, {"a.png": arr})
   hit = check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True)
   line = next(w for w in hit["warnings"] if w["rule"] == "near_colors")
   assert line["items"][0]["count"] == 20
   miss = check.run(helpers.tiny_profile(tmp_path, **{"check.warn.near_colors.min_pairs": 21}), pics, no_ramps=True)
   assert "near_colors" not in rules_of(miss)


def test_near_colors_skipped_when_too_many_colors(tmp_path, monkeypatch):
   """색이 NEAR_MAX_COLORS 를 넘으면 짝을 안 세고 info 에 한 줄 (실물 시험 리뷰 R1-M2)."""
   monkeypatch.setattr(check.pixel_check, "NEAR_MAX_COLORS", 3)
   pics = folder(tmp_path, {"a.png": noise(16, 16, 1)})            # 4색
   report = check.run(helpers.tiny_profile(tmp_path, **{"check.warn.near_colors.min_pairs": 1}), pics, no_ramps=True)
   assert "near_colors" not in rules_of(report)
   skipped = next(i for i in report["info"] if i["rule"] == "near_colors.skipped")
   assert skipped["items"] == [{"where": "a.png", "colors": 4}]


def test_progress_line_on_long_run(tmp_path, monkeypatch, capsys):
   """판이 PROGRESS_EVERY 초를 넘기면 stderr 에 진행 줄이 나온다."""
   monkeypatch.setattr(check, "PROGRESS_EVERY", 0.0)
   pics = folder(tmp_path, {f"p{i}.png": helpers.blob(8, 8) for i in range(3)})
   check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True)
   err = capsys.readouterr().err
   assert "경고 검사 1/3 장" in err and "경고 검사 2/3 장" in err and "3/3" not in err


def test_loop_seam_in_loose_names(tmp_path):
   def frame(x):
      arr = image.new(16, 16)
      arr[4:12, x : x + 4] = (90, 120, 160, 255)
      return arr

   pics = {f"walk_south_{i}.png": frame(x) for i, x in enumerate([2, 3, 4, 2])}
   pics.update({f"attack_south_{i}.png": frame(x) for i, x in enumerate([2, 3, 4, 2])})
   report = check.run(helpers.tiny_profile(tmp_path), folder(tmp_path, pics), no_ramps=True)
   line = next(w for w in report["warnings"] if w["rule"] == "loop_seam")
   assert [i["where"] for i in line["items"]] == ["walk/south"]       # attack 은 anims 밖


def test_ramp_shape_runs_on_profile_ramps(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   report = check.run(prof, loose_dir(tmp_path))
   assert "ramp_shape" in rules_of(report)        # lpc_cloth 는 hue shift 가 없다
   assert "ramp_shape" not in rules_of(check.run(prof, loose_dir(tmp_path), no_ramps=True))


# --- 배경 모드 ---


def test_background_auto_and_mode_override(tmp_path):
   pics = folder(tmp_path, {"bg.png": noise(128, 128, 1)})
   prof = helpers.tiny_profile(tmp_path)
   auto = check.run(prof, pics, no_ramps=True)
   rule = next(r for r in auto["rules"] if r["rule"] == "max_colors")
   assert rule["items"][0]["background"] is True
   assert "outline" not in [i["rule"] for i in auto.get("info", [])]      # 배경은 외곽선을 안 본다
   sprite = check.run(prof, pics, no_ramps=True, mode="sprite")
   assert "background" not in next(r for r in sprite["rules"] if r["rule"] == "max_colors")["items"][0]
   small = folder(tmp_path, {"s.png": noise(16, 16, 2)}, "small")
   forced = check.run(prof, small, no_ramps=True, mode="background")
   assert next(r for r in forced["rules"] if r["rule"] == "max_colors")["items"][0]["background"] is True


def test_background_color_cap_and_max_colors(tmp_path):
   arr = np.zeros((128, 128, 4), dtype=np.uint8)
   arr[:, :, 3] = 255
   for i in range(80):
      arr[i, :, 0] = i * 3                                  # 80색
   pics = folder(tmp_path, {"bg.png": arr})
   report = check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True)
   cap = next(w for w in report["warnings"] if w["rule"] == "color_cap")["items"][0]
   assert cap["cap"] == 64 and cap["background"] is True
   assert report["status"] == "fail"                       # 기존 max_colors 48 은 그대로 실패
   loose = helpers.tiny_profile(tmp_path, **{"check.background.max_colors": 100})
   assert check.run(loose, pics, no_ramps=True)["status"] == "ok"


# --- 가이드 파일 건너뛰기 ---


def test_guide_files_are_skipped(tmp_path, capsys):
   """render 폴더(template.json 있음)에서 그 템플릿 이름이 붙은 가이드만 건너뛰고 skipped_files 에 남긴다 (리뷰 R1-H4)."""
   pics = folder(tmp_path, {
      "a.png": helpers.blob(8, 8),
      "t_guide.png": helpers.blob(8, 8),
      "t_preview.png": helpers.blob(8, 8),
      "t_over.png": helpers.blob(8, 8),
      "t_mask_hair.png": helpers.blob(8, 8),
      "_x.png": helpers.blob(8, 8),               # 이름 규칙만으로는 더 안 건너뛴다
      "game_over.png": helpers.blob(8, 8),        # 다른 이름 접두 = 보통 그림
   })
   jsonio.write_json(pics / "template.json", {"version": 1, "name": "t"})
   report = check.run(helpers.tiny_profile(tmp_path), pics)
   assert report["checked"]["files"] == 3
   assert report["skipped_files"] == ["t_guide.png", "t_mask_hair.png", "t_over.png", "t_preview.png"]
   assert "가이드 파일 4개" in capsys.readouterr().err


def test_guide_names_checked_outside_render_folder(tmp_path):
   """template.json 이 없는 폴더에서는 _preview · _over · _mask_ 이름도 보통 그림으로 검수한다."""
   names = ["game_over.png", "card_preview.png", "t_guide.png", "a_mask_b.png", "_x.png"]
   pics = folder(tmp_path, {name: helpers.blob(8, 8) for name in names})
   report = check.run(helpers.tiny_profile(tmp_path), pics)
   assert report["checked"]["files"] == 5
   assert "skipped_files" not in report
   assert not check.is_guide(pics / "card_preview.png")


def test_broken_template_json_skips_nothing(tmp_path):
   pics = folder(tmp_path, {"t_guide.png": helpers.blob(8, 8)})
   (pics / "template.json").write_text("{깨짐", encoding="utf-8")
   assert check.run(helpers.tiny_profile(tmp_path), pics)["checked"]["files"] == 1


# --- 템플릿 겹치기 · must ---


def test_template_frames_warning(tmp_path):
   pics = folder(tmp_path, {f"fx_south_{i}.png": helpers.blob(8, 8) for i in range(6)})
   tpl = write_template(tmp_path, kind="effect", size=[8, 8], check={"frames": 5})
   report = check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True, template=tpl)
   line = next(w for w in report["warnings"] if w["rule"] == "template.frames")
   assert line["items"] == [{"where": "fx/south", "frames": 6}]
   assert report["template"]["must"] == ["canvas", "alpha", "scale"]


@pytest.mark.parametrize("count, warned", [(3, False), (4, False), (2, True), (5, True)])
def test_template_frames_idle_takes_drawings_or_played(tmp_path, count, warned):
   """cycle idle (order 1-2-3-2) 은 그린 장 수 3 도, 펼친 장 수 4 도 받는다."""
   pics = folder(tmp_path, {f"idle_south_{i}.png": helpers.blob(8, 8) for i in range(count)})
   tpl = write_template(tmp_path, kind="cycle", size=[8, 8], preset="idle",
                        values={"frames": 4, "order": [1, 2, 3, 2]}, check={"frames": 4})
   report = check.run(helpers.tiny_profile(tmp_path), pics, no_ramps=True, template=tpl)
   line = [w for w in report["warnings"] if w["rule"] == "template.frames"]
   assert bool(line) == warned
   if warned:
      assert "3 또는 4장" in line[0]["detail"]


def test_frame_counts_plain_template_is_exact():
   assert check.frame_counts(5, {"kind": "effect", "values": {"order": [1, 2]}}) == {5}
   assert check.frame_counts(8, {"kind": "cycle", "values": {"frames": 8}}) == {8}


def test_must_canvas_keeps_status_and_survives_no_warn(tmp_path):
   pics = loose_dir(tmp_path)                       # 8x8 세 장
   tpl = write_template(tmp_path, kind="character", size=[16, 16])
   prof = helpers.tiny_profile(tmp_path)
   plain = check.run(prof, pics)
   report = check.run(prof, pics, template=tpl)
   assert report["status"] == plain["status"] == "ok"
   assert report["must_failed"] == ["canvas"]
   line = next(w for w in report["warnings"] if w["rule"] == "must.canvas")
   assert line["must"] is True and len(line["items"]) == 3
   quiet = check.run(prof, pics, warn=False, template=tpl)
   assert quiet["must_failed"] == ["canvas"] and rules_of(quiet) == ["must.canvas"]


def test_must_empty_list_keeps_kind_defaults(tmp_path):
   tpl = write_template(tmp_path, kind="tile", size=[8, 8], must=[])
   report = check.run(helpers.tiny_profile(tmp_path), loose_dir(tmp_path), template=tpl)
   assert report["template"]["must"] == ["canvas", "alpha", "scale", "palette"]
   tpl2 = write_template(tmp_path, kind="effect", size=[8, 8], must=["palette"])
   assert check.run(helpers.tiny_profile(tmp_path), loose_dir(tmp_path), template=tpl2)["template"]["must"] == list(check.MUST_WORDS)


def test_must_alpha_only_when_fail_rule_is_off(tmp_path):
   pics = loose_dir(tmp_path)
   arr = image.load(pics / "icon_1.png")
   arr[3, 3] = (27, 42, 74, 128)
   image.save(pics / "icon_1.png", arr)
   tpl = write_template(tmp_path, kind="character", size=[8, 8])
   binary = check.run(helpers.tiny_profile(tmp_path), pics, template=tpl)
   assert "alpha" in binary["failed"] and "must.alpha" not in rules_of(binary)
   soft = check.run(helpers.tiny_profile(tmp_path, **{"check.allow_alpha": "any"}), pics, template=tpl)
   assert soft["failed"] == [] and soft["must_failed"] == ["alpha"]


def test_must_palette_only_when_ramp_rule_is_off(tmp_path):
   pics = folder(tmp_path, {"a.png": helpers.blob(8, 8, body=(1, 2, 3))})
   tpl = write_template(tmp_path, kind="character", size=[8, 8])
   prof = helpers.tiny_profile(tmp_path)
   strict = check.run(prof, pics, template=tpl)
   assert "ramp_colors" in strict["failed"] and "palette" not in strict["must_failed"]
   off = check.run(prof, pics, no_ramps=True, template=tpl)
   assert off["must_failed"] == ["palette"]


def test_must_scale(tmp_path):
   canvas = image.new(80, 40)
   image.paste(canvas, image.scale_up(noise(16, 16, 3), 2), 2, 2)
   image.paste(canvas, noise(16, 16, 4), 56, 10)
   tpl = write_template(tmp_path, kind="effect", size=[80, 40])
   report = check.run(helpers.tiny_profile(tmp_path), folder(tmp_path, {"m.png": canvas}), no_ramps=True, warn=False, template=tpl)
   assert report["must_failed"] == ["scale"]


def test_profile_wins_unless_fixed(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"style.outline": "black"})
   tpl = check.load_template(write_template(tmp_path, kind="effect", check={"style": {"outline": "none"}, "check": {"max_colors": 3}}))
   merged, _ = check.apply_template(prof, tpl)
   assert merged.style["outline"] == "black" and merged.check["max_colors"] == 3
   fixed = check.load_template(write_template(tmp_path, kind="effect", check={"style": {"outline": "none"}}, fixed=["style.outline"]))
   assert check.apply_template(prof, fixed)[0].style["outline"] == "none"


def test_profile_applied_template_wins_whole_and_brings_ramps(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"style.outline": "black"})
   ramps = tmp_path / "game_ramps.json"
   jsonio.write_json(ramps, {"version": 1, "name": "g", "ramp_len": 2, "ramps": {"blue": ["#1B2A4A", "#3D5C9B"]}})
   tpl = write_template(tmp_path, kind="character", size=[8, 8], profile_applied=True,
                        check={"style": {"outline": "selout"}, "palette": {"ramps_file": str(ramps)}})
   merged, override = check.apply_template(prof, check.load_template(tpl))
   assert merged.style["outline"] == "selout" and override == ramps
   report = check.run(prof, loose_dir(tmp_path), template=tpl)
   assert report["status"] == "ok"                            # blob 의 두 색이 그 램프에 다 있다
   assert report["template"]["profile_applied"] is True


@pytest.mark.parametrize(
   "data, match",
   [
      ({"kind": "effect", "check": {"style": {"outline": "none"}}, "fixed": ["style.light"]}, "fixed"),
      ({"kind": "rocket"}, "kind"),
      ({"kind": "effect", "must": ["canvas", "sound"]}, "must"),
      ({"kind": "effect", "check": {"check": {"max_colours": 3}}}, "max_colours"),
   ],
)
def test_bad_template_is_usage_error(tmp_path, data, match):
   with pytest.raises(UsageError, match=match):
      check.run(helpers.tiny_profile(tmp_path), loose_dir(tmp_path), template=write_template(tmp_path, **data))
