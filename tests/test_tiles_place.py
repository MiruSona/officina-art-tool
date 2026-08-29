import json

import pytest

import helpers
import test_blob
from arttool.errors import ArtToolError, MissingExecutable
from arttool.jsonio import read_json, write_json
from arttool.tiles import blob, ldtk, place


def make_tileset(tmp_path):
   prof = helpers.tiny_profile(tmp_path, **{"tiles.size": test_blob.TILE})
   templates = test_blob.write_templates(tmp_path / "t6")
   data = blob.build(prof, templates, tmp_path / "tiles47")
   return prof, data


def test_parse_size():
   assert place.parse_size("64x32") == (64, 32)


def test_parse_size_bad():
   with pytest.raises(ArtToolError):
      place.parse_size("64*32")


def test_no_exe(monkeypatch):
   monkeypatch.delenv(place.ENV_KEY, raising=False)
   with pytest.raises(MissingExecutable, match="실행 파일이 없다"):
      place.find_exe()


def test_exe_path_missing(tmp_path):
   with pytest.raises(MissingExecutable, match="못 찾았다"):
      place.find_exe(str(tmp_path / "없다.exe"))


def test_build_request_shape(tmp_path):
   prof, tileset = make_tileset(tmp_path)
   request = place.build_request(prof, tileset, {"weights": {}}, 4, 3, seed=7)
   assert request["width"] == 4 and request["height"] == 3
   assert len(request["tiles"]) == 47
   assert request["seed"] == 7
   assert request["tile_size"] == test_blob.TILE


def test_build_request_tile_size_mismatch(tmp_path):
   prof, tileset = make_tileset(tmp_path)
   tileset["tile_size"] = 999
   with pytest.raises(ArtToolError, match="타일 크기"):
      place.build_request(prof, tileset, {}, 2, 2)


def test_parse_response_ok():
   text = json.dumps({"version": 1, "status": "ok", "grid": [[0, 1], [2, 3]]})
   out = place.parse_response(text, 2, 2)
   assert out["grid"][1][1] == 3


def test_parse_response_contradiction():
   text = json.dumps({"status": "contradiction"})
   with pytest.raises(ArtToolError, match="모순"):
      place.parse_response(text, 2, 2)


def test_parse_response_timeout():
   with pytest.raises(ArtToolError, match="시간"):
      place.parse_response(json.dumps({"status": "timeout"}), 2, 2)


def test_parse_response_wrong_size():
   text = json.dumps({"status": "ok", "grid": [[0, 1]]})
   with pytest.raises(ArtToolError, match="줄 수"):
      place.parse_response(text, 2, 2)


def test_dry_run_writes_request_only(tmp_path):
   prof, tileset = make_tileset(tmp_path)
   write_json(tmp_path / "rules.json", {"weights": {}})
   out = place.place(prof, tmp_path / "tiles47" / "tileset.json", tmp_path / "rules.json", "4x4", tmp_path / "map", dry_run=True)
   assert out["dry_run"] is True
   assert (tmp_path / "map" / "place_request.json").is_file()
   assert not (tmp_path / "map" / "map.json").exists()


def test_ldtk_project(tmp_path):
   _prof, tileset = make_tileset(tmp_path)
   map_data = {"version": 1, "width": 2, "height": 2, "grid": [[0, 1], [2, 3]]}
   project = ldtk.write_ldtk(map_data, tileset, tmp_path / "map.ldtk")

   layer = project["levels"][0]["layerInstances"][0]
   assert layer["__cWid"] == 2 and len(layer["gridTiles"]) == 4
   assert layer["gridTiles"][1]["px"] == [test_blob.TILE, 0]
   assert project["defs"]["tilesets"][0]["tileGridSize"] == test_blob.TILE
   assert read_json(tmp_path / "map.ldtk")["jsonVersion"] == ldtk.JSON_VERSION


def test_ldtk_rejects_unknown_tile(tmp_path):
   _prof, tileset = make_tileset(tmp_path)
   map_data = {"version": 1, "width": 1, "height": 1, "grid": [[999]]}
   with pytest.raises(ArtToolError, match="없는 타일 번호"):
      ldtk.build_project(map_data, tileset)
