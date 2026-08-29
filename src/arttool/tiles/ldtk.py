"""맵 JSON 을 최소 LDtk 프로젝트 파일로 쓴다. LDtkToUnity 가 읽는다."""

from __future__ import annotations

from pathlib import Path

from ..errors import ArtToolError
from ..jsonio import write_json

JSON_VERSION = "1.5.3"
TILESET_UID = 1
LAYER_UID = 2
LEVEL_UID = 3


def _tile_source(tileset: dict, index: int) -> list[int]:
   tiles = tileset["tiles"]
   if index < 0 or index >= len(tiles):
      raise ArtToolError(f"맵에 없는 타일 번호가 있다 : {index}")
   tile = tiles[index]
   return [int(tile["x"]), int(tile["y"])]


def build_project(map_data: dict, tileset: dict, identifier: str = "Level_0") -> dict:
   size = int(tileset["tile_size"])
   width = int(map_data["width"])
   height = int(map_data["height"])
   grid = map_data["grid"]

   grid_tiles = []
   for row in range(height):
      for col in range(width):
         index = int(grid[row][col])
         grid_tiles.append(
            {
               "px": [col * size, row * size],
               "src": _tile_source(tileset, index),
               "f": 0,
               "t": index,
               "d": [row * width + col],
               "a": 1,
            }
         )

   sheet_cols = int(tileset.get("sheet_cols", 8))
   sheet_rows = (int(tileset["count"]) + sheet_cols - 1) // sheet_cols
   return {
      "__header__": {"fileType": "LDtk Project JSON", "app": "arttool", "appAuthor": "arttool"},
      "jsonVersion": JSON_VERSION,
      "defaultGridSize": size,
      "worldLayout": "Free",
      "defs": {
         "tilesets": [
            {
               "uid": TILESET_UID,
               "identifier": "Blob",
               "relPath": tileset.get("sheet", "tileset.png"),
               "pxWid": sheet_cols * size,
               "pxHei": sheet_rows * size,
               "tileGridSize": size,
               "spacing": 0,
               "padding": 0,
               "customData": [],
               "enumTags": [],
            }
         ],
         "layers": [
            {
               "__type": "Tiles",
               "identifier": "Tiles",
               "uid": LAYER_UID,
               "gridSize": size,
               "tilesetDefUid": TILESET_UID,
               "displayOpacity": 1,
            }
         ],
         "entities": [],
         "enums": [],
         "externalEnums": [],
         "levelFields": [],
      },
      "levels": [
         {
            "identifier": identifier,
            "uid": LEVEL_UID,
            "worldX": 0,
            "worldY": 0,
            "pxWid": width * size,
            "pxHei": height * size,
            "bgColor": "#000000",
            "fieldInstances": [],
            "layerInstances": [
               {
                  "__identifier": "Tiles",
                  "__type": "Tiles",
                  "__cWid": width,
                  "__cHei": height,
                  "__gridSize": size,
                  "__tilesetDefUid": TILESET_UID,
                  "__tilesetRelPath": tileset.get("sheet", "tileset.png"),
                  "levelId": LEVEL_UID,
                  "layerDefUid": LAYER_UID,
                  "pxOffsetX": 0,
                  "pxOffsetY": 0,
                  "visible": True,
                  "seed": 0,
                  "gridTiles": grid_tiles,
                  "autoLayerTiles": [],
                  "entityInstances": [],
                  "intGridCsv": [],
               }
            ],
         }
      ],
   }


def write_ldtk(map_data: dict, tileset: dict, out_path: str | Path, identifier: str = "Level_0") -> dict:
   project = build_project(map_data, tileset, identifier)
   write_json(out_path, project)
   return project
