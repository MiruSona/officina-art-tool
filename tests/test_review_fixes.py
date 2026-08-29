"""코드 리뷰 24건을 잡아 두는 시험. 구현식을 다시 쓰지 않고 결과로 잰다."""

import json

import numpy as np
import pytest

import helpers
from arttool import bake, check, image, jsonio, palette, paths, profile
from arttool.errors import ArtToolError, PathJailError, ProfileError
from arttool.sprite import anchors, normalize


def _center_of(arr):
   x0, _y0, x1, _y1 = image.bbox(arr)
   return (x0 + x1 - 1) / 2.0


# --- #1 짝수 반올림 : 중심이 center_x 와 같은가 (구현식을 다시 쓰지 않는다) ---


@pytest.mark.parametrize("width", [2, 4, 6, 8, 10, 12])
def test_even_width_lands_exactly_on_center(width, tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   art = helpers.put_on_canvas(helpers.blob(width, 6), 16, 16, 1, 2)
   assert _center_of(normalize.fit_frame(art, prof, "시험")) == float(prof.canvas["center_x"])


@pytest.mark.parametrize("width", [3, 5, 7, 9, 11])
def test_odd_width_is_never_more_than_half_off(width, tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   art = helpers.put_on_canvas(helpers.blob(width, 6), 16, 16, 1, 2)
   drift = _center_of(normalize.fit_frame(art, prof, "시험")) - float(prof.canvas["center_x"])
   assert abs(drift) <= 0.5


def test_odd_widths_all_drift_the_same_way(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   drifts = set()
   for width in (3, 5, 7, 9, 11):
      art = helpers.put_on_canvas(helpers.blob(width, 6), 16, 16, 1, 2)
      drifts.add(_center_of(normalize.fit_frame(art, prof, "시험")) - float(prof.canvas["center_x"]))
   assert len(drifts) == 1


# --- #2 east 앵커 : 프레임 통째로 반전인가, 앵커가 그림 위에 있는가 ---


def _mirror_build(tmp_path, width):
   prof = helpers.tiny_profile(tmp_path, **{"rigs.blob.anchors": ["head_top"], "anim": {"walk": {"frames": 1, "dirs": 4}}})
   raw = tmp_path / f"raw{width}"
   raw.mkdir()
   for direction in ("south", "west", "north"):
      art = helpers.put_on_canvas(helpers.blob(width, 6), 16, 16, 2, 3)
      image.save(raw / f"walk_{direction}_0.png", art)
   index = normalize.normalize(prof, raw, tmp_path / f"b{width}", ["walk"])
   grid = image.split_grid(image.load(tmp_path / f"b{width}" / "walk.png"), 16, 16)
   names = index["sheets"][0]["directions"]
   return prof, index, grid, names


@pytest.mark.parametrize("width", [5, 6, 7, 8])
def test_east_frame_is_whole_frame_flip_of_west(width, tmp_path):
   _prof, _index, grid, names = _mirror_build(tmp_path, width)
   west = grid[names.index("west")][0]
   east = grid[names.index("east")][0]
   assert np.array_equal(image.flip_x(west), east)


@pytest.mark.parametrize("width", [5, 6, 7, 8])
def test_east_anchor_sits_on_a_real_pixel(width, tmp_path):
   prof, index, grid, names = _mirror_build(tmp_path, width)
   west = grid[names.index("west")][0]
   east = grid[names.index("east")][0]

   markers = tmp_path / f"mk{width}"
   markers.mkdir()
   rows = []
   for direction in ("south", "west", "north"):
      frame = image.new(16, 16)
      box = image.bbox(grid[names.index(direction)][0])
      frame[box[1], box[0]] = (*helpers.MARKER_HEAD, 255)
      rows.append([frame])
   image.save(markers / "walk.png", image.pack_grid(rows, 16, 16))

   data = anchors.extract(prof, index, markers, "blob")
   spot = next(p for p in data["points"] if p["direction"] == "east")
   twin = next(p for p in data["points"] if p["direction"] == "west")
   assert east[spot["y"], spot["x"]][3] == 255
   assert west[twin["y"], twin["x"]][3] == 255
   assert tuple(east[spot["y"], spot["x"]]) == tuple(west[twin["y"], twin["x"]])


# --- #3 램프 길이 ---


def test_ramps_of_different_length_are_refused(tmp_path):
   path = tmp_path / "r.json"
   path.write_text(json.dumps({"ramps": {"a": ["#000000", "#111111"], "b": ["#222222"]}}), encoding="utf-8")
   with pytest.raises(ArtToolError, match="길이"):
      palette.load_ramps(path)


def test_equal_length_without_ramp_len_is_fine(tmp_path):
   path = tmp_path / "r.json"
   path.write_text(json.dumps({"ramps": {"a": ["#000000", "#111111"], "b": ["#222222", "#333333"]}}), encoding="utf-8")
   ramps = palette.load_ramps(path)
   assert ramps.ramp_len == 2
   assert image.size(palette.build_lut(ramps, ramps.names())) == (2, 2)


# --- #4 잘린 PNG · 잘린 JSON ---


def test_truncated_png(tmp_path):
   good = tmp_path / "g.png"
   image.save(good, image.new(8, 8, (255, 0, 0, 255)))
   cut = tmp_path / "cut.png"
   cut.write_bytes(good.read_bytes()[:40])
   with pytest.raises(ArtToolError, match="그림"):
      image.load(cut)


def test_not_a_png_at_all(tmp_path):
   path = tmp_path / "x.png"
   path.write_text("이건 그림이 아니다", encoding="utf-8")
   with pytest.raises(ArtToolError):
      image.load(path)


def test_truncated_json(tmp_path):
   path = tmp_path / "a.json"
   path.write_text('{"version": 1, "points":', encoding="utf-8")
   with pytest.raises(ArtToolError, match="JSON"):
      jsonio.read_json(path)


# --- #5 드라이브 상대경로 ---


def test_drive_relative_path_is_refused(tmp_path):
   root = paths.resolve_root(tmp_path / "root")
   for bad in ("C:foo", "D:foo", "c:x/y"):
      with pytest.raises(PathJailError):
         paths.safe_join(root, bad)


def test_plain_relative_still_works(tmp_path):
   root = paths.resolve_root(tmp_path / "root")
   assert paths.safe_join(root, "a/b.png").name == "b.png"


# --- #6 프로필 안 경로에도 감옥 ---


def _write_profile(tmp_path, body):
   path = tmp_path / "p.yaml"
   path.write_text(body, encoding="utf-8")
   return path


def test_ramps_file_absolute_is_refused(tmp_path):
   path = _write_profile(tmp_path, "name: a\npreset: topdown_action\npalette:\n  ramps_file: C:/Windows/win.ini\n")
   with pytest.raises((PathJailError, ProfileError)):
      profile.load_profile(str(path)).ramps_path()


def test_ramps_file_escape_is_refused(tmp_path):
   path = _write_profile(tmp_path, "name: a\npreset: topdown_action\npalette:\n  ramps_file: ../../../../Windows/win.ini\n")
   with pytest.raises((PathJailError, ProfileError)):
      profile.load_profile(str(path)).ramps_path()


def test_ramps_file_next_to_profile_is_fine(tmp_path):
   (tmp_path / "my.json").write_text(json.dumps({"ramp_len": 2, "ramps": {"a": ["#000000", "#FFFFFF"]}}), encoding="utf-8")
   path = _write_profile(tmp_path, "name: a\npreset: topdown_action\npalette:\n  ramps_file: my.json\n")
   assert profile.load_profile(str(path)).ramps_path().is_file()


# --- #7 산출물 경로 감옥 ---


def test_cli_report_outside_root_is_refused(tmp_path):
   from arttool import cli, errors

   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   build = tmp_path / "build"
   normalize.normalize(prof, raw, build, ["walk"])

   spec = tmp_path / "tiny.yaml"
   spec.write_text(
      "name: tiny\npreset: topdown_action\ncanvas:\n  frame: [16, 16]\n  baseline_y: 13\n  center_x: 7.5\n"
      "anim:\n  walk: { frames: 2, dirs: 4 }\n",
      encoding="utf-8",
   )
   outside = tmp_path / "밖" / ".." / ".." / "탈출.json"
   code = cli.main(["--profile", str(spec), "check", "--in", str(build), "--report", str(outside)])
   assert code == errors.EXIT_PATH


# --- #8 안쪽 모르는 키 ---


def test_inner_typo_key_is_refused(tmp_path):
   path = _write_profile(tmp_path, "name: t\npreset: topdown_action\ncanvas:\n  baselineY: 3\n")
   with pytest.raises(ProfileError, match="모르는 항목"):
      profile.load_profile(str(path))


def test_inner_typo_in_check_is_refused(tmp_path):
   path = _write_profile(tmp_path, "name: t\npreset: topdown_action\ncheck:\n  maxColors: 2\n")
   with pytest.raises(ProfileError, match="모르는 항목"):
      profile.load_profile(str(path))


def test_inner_typo_in_ui_is_refused(tmp_path):
   path = _write_profile(tmp_path, "name: t\npreset: topdown_action\nui:\n  generator:\n    cornerCut: cut1\n")
   with pytest.raises(ProfileError, match="모르는 항목"):
      profile.load_profile(str(path))


def test_rig_and_anim_names_stay_free(tmp_path):
   path = _write_profile(
      tmp_path,
      "name: t\npreset: topdown_action\nanim:\n  내춤: { frames: 2, dirs: 4 }\n"
      "rigs:\n  내리그:\n    method: anchor\n    anchors: [머리]\n    marker_colors: { 머리: '#FF00FF' }\n",
   )
   prof = profile.load_profile(str(path))
   assert "내춤" in prof.anim and "내리그" in prof.rigs


# --- #9 cp949 폴백 ---


def test_cp949_profile_warns(tmp_path, capsys):
   path = tmp_path / "cp.yaml"
   path.write_bytes("name: y\npreset: topdown_action\n# 한글 주석\n".encode("cp949"))
   assert profile.load_profile(str(path)).name == "y"
   assert "cp949" in capsys.readouterr().err


def test_undecodable_profile_is_profile_error(tmp_path):
   path = tmp_path / "bin.yaml"
   path.write_bytes(b"name: x\npreset: topdown_action\nbad: \x81\x30\n")
   with pytest.raises(ProfileError):
      profile.load_profile(str(path))


# --- #10 기계용 JSON 에 한국어 값 없음 ---


def test_forced_without_report_has_no_korean(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   build = tmp_path / "build"
   normalize.normalize(prof, raw, build, ["walk"])

   result = bake.bake(prof, build, tmp_path / "unity", "Game.Art", force=True)
   assert result["check"] in (None, "missing")
   text = (tmp_path / "unity" / "sprite_manifest.json").read_text(encoding="utf-8")
   assert json.loads(text)["check"] in (None, "missing")


# --- #11 줄 수 불일치 ---


def test_extra_sheet_rows_are_refused(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   build = tmp_path / "build"
   normalize.normalize(prof, raw, build, ["walk"])

   sheet = image.load(build / "walk.png")
   taller = image.new(32, 80)
   image.paste(taller, sheet, 0, 0)
   taller[70, 3] = (27, 42, 74, 255)
   image.save(build / "walk.png", taller)
   with pytest.raises(ArtToolError, match="줄"):
      check.run(prof, build)


# --- #12 ramps_file 이 적혔는데 없으면 실패 ---


def test_missing_ramps_file_fails_check(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"palette.ramps_file": "palettes/없는파일.json"})
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   build = tmp_path / "build"
   normalize.normalize(prof, raw, build, ["walk"])
   report = check.run(prof, build)
   assert report["status"] == "fail"
   assert "ramp_colors" in report["failed"]


def test_no_ramps_file_at_all_is_skipped(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"palette.ramps_file": ""})
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   build = tmp_path / "build"
   normalize.normalize(prof, raw, build, ["walk"])
   rule = next(r for r in check.run(prof, build)["rules"] if r["rule"] == "ramp_colors")
   assert rule["ok"]


# --- #13 죽은 프로필 칸 ---


def test_exact_match_off_turns_ramp_rule_into_warning(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"palette.exact_match": False})
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   build = tmp_path / "build"
   normalize.normalize(prof, raw, build, ["walk"])

   sheet = image.load(build / "walk.png")
   sheet[13, 5] = (1, 2, 3, 255)
   image.save(build / "walk.png", sheet)
   report = check.run(prof, build)
   assert "ramp_colors" not in report["failed"]


def test_dead_profile_keys_are_gone():
   text = (profile.tool_home() / "profiles" / "topdown_action.yaml").read_text(encoding="utf-8")
   assert "marker_layer:" not in text
   assert "parts:" not in text
   assert "marker_layer" not in json.dumps(profile.DEFAULTS, ensure_ascii=False)


# --- #14 pivot 두 축이 같은 규칙 ---


def test_pivot_uses_one_rule(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   frame_w, frame_h = prof.frame
   pivot = bake.pivot_of(prof)
   assert pivot["x"] == pytest.approx((float(prof.canvas["center_x"]) + 0.5) / frame_w)
   assert pivot["y"] == pytest.approx((frame_h - 1 - int(prof.canvas["baseline_y"]) + 0.5) / frame_h)


# --- #15 맨 바깥에서 Exception ---


def test_broken_frames_json_gives_one_line(tmp_path, capsys, monkeypatch):
   from arttool import cli, errors

   build = tmp_path / "build"
   build.mkdir()
   jsonio.write_json(build / "frames.json", {"version": 1, "sheets": [{"anim": "walk"}]})
   monkeypatch.delenv("ARTTOOL_DEBUG", raising=False)

   code = cli.main(["--profile", "topdown_action", "check", "--in", str(build), "--report", str(build / "r.json")])
   captured = capsys.readouterr()
   assert code != 0
   assert "Traceback" not in captured.err
   assert len(captured.err.strip().splitlines()) == 1


# --- #18 중간 폴더가 정션(링크)일 때 ---


def test_junction_in_the_middle_is_refused(tmp_path):
   import subprocess

   root = tmp_path / "root"
   root.mkdir()
   outside = tmp_path / "밖"
   outside.mkdir()
   link = root / "link"
   done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True, shell=False)
   if done.returncode != 0 or not link.exists():
      pytest.skip("이 환경에서 정션을 못 만든다")

   with pytest.raises(PathJailError):
      paths.safe_join(paths.resolve_root(root), "link/밖으로.png")


# --- #19 안 밟혔던 가지 ---


def test_marker_sheet_row_count_mismatch(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"rigs.blob.anchors": ["head_top"]})
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   index = normalize.normalize(prof, raw, tmp_path / "build", ["walk"])

   markers = tmp_path / "markers"
   markers.mkdir()
   image.save(markers / "walk.png", image.new(32, 32))
   with pytest.raises(ArtToolError, match="줄이"):
      anchors.extract(prof, index, markers, "blob")


def test_only_east_can_be_mirrored(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"rigs.blob.anchors": ["head_top"]})
   raw = tmp_path / "raw"
   helpers.write_singles(raw, prof)
   index = normalize.normalize(prof, raw, tmp_path / "build", ["walk"])
   index["sheets"][0]["mirrored"] = ["north"]

   markers = tmp_path / "markers"
   helpers.write_markers(markers, prof, directions=["south", "west", "east"])
   with pytest.raises(ArtToolError, match="east 뿐"):
      anchors.extract(prof, index, markers, "blob")


# --- #22 tmp 이름에 PID ---


def test_tmp_name_carries_pid(tmp_path, monkeypatch):
   import os

   seen = []
   real = os.replace

   def spy(src, dst):
      seen.append(str(src))
      real(src, dst)

   monkeypatch.setattr(os, "replace", spy)
   jsonio.write_json(tmp_path / "a.json", {"a": 1})
   image.save(tmp_path / "b.png", image.new(2, 2))
   assert all(str(os.getpid()) in name for name in seen)
   assert len(seen) == 2


# --- #23 실패해도 빈 폴더가 안 남는다 ---


def test_failed_run_leaves_no_empty_folder(tmp_path):
   prof = helpers.tiny_profile(tmp_path)
   out = tmp_path / "안생겨야한다"
   with pytest.raises(ArtToolError):
      normalize.normalize(prof, tmp_path / "없는입력", out, ["walk"])
   assert not out.exists()
