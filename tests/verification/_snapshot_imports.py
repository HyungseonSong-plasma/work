# FileRank: C
"""Test-only namespace selection for trusted pre-/post-D2 snapshots."""

from importlib import import_module
from pathlib import Path


_MODULES = frozenset(("github", "command", "testing", "workflow"))


def namespace(root):
    """Recognize exactly one of the two supported source layouts."""
    root = Path(root)
    old, new = root / "libs", root / "work" / "libs"
    if old.exists() == new.exists():
        raise ValueError("Expected exactly one snapshot library namespace.")
    folder = old if old.exists() else new
    if not (folder / "__init__.py").is_file():
        raise ValueError("Missing snapshot library package.")
    if folder == new and not (root / "work" / "__init__.py").is_file():
        raise ValueError("Missing work package.")
    return "libs" if folder == old else "work.libs"


def library(name):
    """Resolve only the fixed probe modules, without aliases or fallback."""
    if name not in _MODULES:
        raise ValueError("Unknown snapshot probe library.")
    root = Path.cwd().resolve()
    prefix = namespace(root)
    expected = root.joinpath(*prefix.split("."), name + ".py")
    if not expected.is_file():
        raise ValueError("Missing snapshot probe library.")
    module = import_module(prefix + "." + name)
    if Path(module.__file__).resolve() != expected.resolve():
        raise ValueError("Snapshot probe library resolved outside snapshot.")
    return module
