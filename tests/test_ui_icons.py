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


# --- 낱장 폴더 들이기 ---


def make_loose(tmp_path, side=16, count=2, name="berry"):
   """낱장 아이콘 PNG 를 몇 장 쓴다."""
   folder = tmp_path / "loose"
   folder.mkdir(parents=True, exist_ok=True)
   for index in range(count):
      arr = image.new(side, side)
      arr[2 : side - 2, 2 : side - 2] = FILL
      image.save(folder / f"{name}_{index}.png", arr)
   return folder


def test_gather_folder_writes_one_json(tmp_path):
   folder = make_loose(tmp_path)
   data = icons.gather(prof(), folder, tmp_path / "out")

   assert [e["name"] for e in data["icons"]] == ["berry_0", "berry_1"]
   assert data["icons"][0]["size"] == 16
   assert (tmp_path / "out" / "berry_0.png").is_file()
   assert read_json(tmp_path / "out" / "icons.json")["icons"][0]["file"] == "berry_0.png"


def test_gather_rejects_non_square(tmp_path):
   folder = make_loose(tmp_path, count=1)
   flat = image.new(16, 8)
   flat[2:6, 2:14] = FILL
   image.save(folder / "berry_0.png", flat)
   with pytest.raises(ArtToolError, match="정사각"):
      icons.gather(prof(), folder, tmp_path / "out")


def test_gather_size_outside_family(tmp_path):
   folder = make_loose(tmp_path, side=28)
   with pytest.raises(ArtToolError, match="ui.icon.sizes"):
      icons.gather(prof(), folder, tmp_path / "out")
   data = icons.gather(prof(**{"ui.icon.sizes": [28]}), folder, tmp_path / "out")
   assert data["icons"][0]["size"] == 28


def test_gather_in_place_writes_only_json(tmp_path):
   folder = make_loose(tmp_path)
   icons.gather(prof(), folder, folder)
   assert sorted(p.name for p in folder.iterdir()) == ["berry_0.png", "berry_1.png", "icons.json"]


def test_gather_then_ui_check_passes(tmp_path):
   from arttool.ui import check_ui

   folder = make_loose(tmp_path)
   icons.gather(prof(), folder, tmp_path / "out")
   report = check_ui.run(tmp_path / "out", prof(**{"ui.check.palette_strict": False}))
   assert report["status"] == "ok"
   assert report["checked"]["icons"] == 2


def test_gather_empty_folder_errors(tmp_path):
   empty = tmp_path / "빈폴더"
   empty.mkdir()
   with pytest.raises(ArtToolError, match="PNG"):
      icons.gather(prof(), empty, tmp_path / "out")


def test_gather_fit_centers(tmp_path):
   folder = tmp_path / "loose"
   folder.mkdir()
   arr = image.new(20, 20)
   arr[1:5, 1:5] = FILL
   image.save(folder / "berry_0.png", arr)

   icons.gather(prof(), folder, tmp_path / "out", fit=16)
   out = image.load(tmp_path / "out" / "berry_0.png")
   assert image.size(out) == (16, 16)
   assert image.bbox(out) == (6, 6, 10, 10)


def test_gather_fit_too_big(tmp_path):
   folder = make_loose(tmp_path, side=32, count=1)
   with pytest.raises(ArtToolError, match="보다 크다"):
      icons.gather(prof(), folder, tmp_path / "out", fit=16)
