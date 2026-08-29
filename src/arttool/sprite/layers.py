"""LPC 층 겹치기. 프로필의 layer_order 순서대로 아래에서 위로 얹는다."""

from __future__ import annotations

from pathlib import Path

from .. import image
from ..errors import ArtToolError
from ..paths import resolve_root, safe_join
from ..profile import Profile


def layer_order(prof: Profile, rig_name: str) -> list[str]:
   rig = prof.rig(rig_name)
   if rig.get("method") != "layer":
      raise ArtToolError(f"{rig_name} 은 층 겹치기 rig 가 아니다 (method={rig.get('method')})")
   order = rig.get("layer_order") or []
   if not order:
      raise ArtToolError(f"{rig_name} 에 layer_order 가 비었다")
   return list(order)


def compose(order: list[str], parts: dict[str, image.RGBA]) -> image.RGBA:
   unknown = sorted(set(parts) - set(order))
   if unknown:
      raise ArtToolError(f"layer_order 에 없는 층 : {', '.join(unknown)}")

   picked = [name for name in order if name in parts]
   if not picked:
      raise ArtToolError("겹칠 층이 하나도 없다")

   base = parts[picked[0]]
   width, height = image.size(base)
   out = image.new(width, height)
   for name in picked:
      part = parts[name]
      if image.size(part) != (width, height):
         raise ArtToolError(f"층 크기가 다르다 : {name} 이 {image.size(part)} 다")
      image.paste(out, part, 0, 0)
   return out


def _read_parts(in_dir: Path, order: list[str], file_name: str) -> dict[str, image.RGBA]:
   parts = {}
   for name in order:
      path = in_dir / name / file_name
      if path.is_file():
         parts[name] = image.load(path)
   if not parts:
      raise ArtToolError(f"{file_name} 을 가진 층 폴더가 없다 : {in_dir}")
   return parts


def compose_sheets(prof: Profile, rig_name: str, in_dir: str | Path, out_dir: str | Path, anims: list[str] | None = None) -> dict:
   """층 폴더마다 든 같은 이름의 시트를 겹쳐 한 장으로 만든다."""
   source = Path(in_dir)
   if not source.is_dir():
      raise ArtToolError(f"층 폴더가 없다 : {source}")

   order = layer_order(prof, rig_name)
   root = resolve_root(out_dir)
   made = []
   for anim in anims or list(prof.anim):
      file_name = f"{anim}.png"
      parts = _read_parts(source, order, file_name)
      out_file = safe_join(root, file_name)
      image.save(out_file, compose(order, parts))
      made.append({"anim": anim, "file": file_name, "layers": [n for n in order if n in parts]})
   return {"rig": rig_name, "out": str(root), "sheets": made}
