import pytest

from arttool.errors import PathJailError
from arttool.paths import resolve_root, safe_join


def test_join_inside(tmp_path):
   root = resolve_root(tmp_path / "out")
   assert safe_join(root, "a/b.png").parent.name == "a"


def test_reject_parent(tmp_path):
   root = resolve_root(tmp_path / "out")
   with pytest.raises(PathJailError):
      safe_join(root, "../밖.png")


def test_reject_absolute(tmp_path):
   root = resolve_root(tmp_path / "out")
   with pytest.raises(PathJailError):
      safe_join(root, "C:/Windows/x.png")
   with pytest.raises(PathJailError):
      safe_join(root, "/etc/x")


def test_reject_deep_parent(tmp_path):
   root = resolve_root(tmp_path / "out")
   with pytest.raises(PathJailError):
      safe_join(root, "a/../../밖.png")
