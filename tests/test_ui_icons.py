import pytest

from arttool import image, profile
from arttool.errors import ArtToolError
from arttool.jsonio import read_json
from arttool.ui import icons

FILL = (242, 237, 228, 255)


def make_sheet(tmp_path, cols=3, rows=2, cell=16, margin=0, spacing=2, blanks=()):
   width = 2 * margin + cols * cell + (cols - 1) * spacing
   height = 2 * margin + rows * cell + (rows - 1) * spacing
   arr = image.new(width, height)
   for row in range(rows):
      for col in range(cols):
         if (row, col) in blanks:
            continue
         x = margin + col * (cell + spacing)
         y = margin + row * (cell + spacing)
         arr[y + 2 : y + cell - 2, x + 2 : x + cell - 2] = FILL
   path = tmp_path / "item.png"
   image.save(path, arr)
   return path


def prof(**over):
   return profile.load_profile("topdown_action", over)


def test_grid_count():
   assert icons.grid_count(52, 16, 0, 2, "가로") == 3
   assert icons.grid_count(16, 16, 0, 2, "가로") == 1


def test_grid_mismatch():
   with pytest.raises(ArtToolError, match="시트 크기와 안 맞는다"):
      icons.grid_count(50, 16, 0, 2, "가로")


def test_grid_too_small():
   with pytest.raises(ArtToolError, match="안 들어간다"):
      icons.grid_count(8, 16, 0, 2, "가로")


def test_cut_sheet(tmp_path):
   sheet = make_sheet(tmp_path)
   data = icons.cut(prof(), sheet, tmp_path / "out")

   assert data["grid"] == [3, 2]
   assert len(data["icons"]) == 6
   assert data["icons"][0]["name"] == "item_000"
   assert data["icons"][0]["size"] == 16
   assert image.size(image.load(tmp_path / "out" / "item_000.png")) == (16, 16)
   assert (tmp_path / "out" / "icons.json").is_file()


def test_blank_cells_are_skipped(tmp_path):
   sheet = make_sheet(tmp_path, blanks={(0, 1), (1, 2)})
   data = icons.cut(prof(), sheet, tmp_path / "out")
   assert data["empty_cells"] == 2
   assert len(data["icons"]) == 4


def test_family_from_argument(tmp_path):
   sheet = make_sheet(tmp_path)
   data = icons.cut(prof(), sheet, tmp_path / "out", family="skill")
   assert data["icons"][0]["family"] == "skill"
   assert data["icons"][0]["name"] == "skill_000"


def test_cell_outside_sizes(tmp_path):
   sheet = make_sheet(tmp_path, cell=16)
   with pytest.raises(ArtToolError, match="밖이다"):
      icons.cut(prof(), sheet, tmp_path / "out", cell=24)


def test_cell_32_is_allowed(tmp_path):
   sheet = make_sheet(tmp_path, cols=2, rows=1, cell=32)
   data = icons.cut(prof(), sheet, tmp_path / "out", cell=32)
   assert len(data["icons"]) == 2
   assert data["icons"][0]["size"] == 32


def test_margin_and_spacing(tmp_path):
   sheet = make_sheet(tmp_path, cols=2, rows=2, margin=4, spacing=1)
   data = icons.cut(prof(**{"ui.icon.sheet.margin": 4, "ui.icon.sheet.spacing": 1}), sheet, tmp_path / "out")
   assert data["grid"] == [2, 2]


def test_hotspot_center_and_top_left(tmp_path):
   sheet = make_sheet(tmp_path)
   data = icons.cut(prof(), sheet, tmp_path / "out")
   assert data["icons"][0]["hotspot"] == [8, 8]

   data = icons.cut(prof(**{"ui.icon.hotspot": "top_left"}), sheet, tmp_path / "out2")
   assert data["icons"][0]["hotspot"] == [0, 0]

   data = icons.cut(prof(**{"ui.icon.hotspot": [3, 4]}), sheet, tmp_path / "out3")
   assert data["icons"][0]["hotspot"] == [3, 4]


def test_icons_json_shape(tmp_path):
   sheet = make_sheet(tmp_path)
   icons.cut(prof(), sheet, tmp_path / "out")
   data = read_json(tmp_path / "out" / "icons.json")
   assert data["version"] == 1
   assert data["cell"] == 16
