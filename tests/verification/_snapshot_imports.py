# FileRank: C
"""Test-only module selection for trusted pre-D2, D2/D3 and D4 snapshots."""

from importlib import import_module
from pathlib import Path


_MODULES = frozenset(("github", "command", "testing", "workflow"))
_APPLICATION = frozenset(("app.cli", "app.commands.trigger", "app.commands.execute",
                          "app.wiring", "github.actions", "github.delete",
                          "github.merge", "github.trigger"))


def layout(root):
    root = Path(root)
    candidates = (("legacy", root / "libs"),
                  ("flat", root / "work" / "libs"),
                  ("src", root / "src" / "work" / "libs"))
    present = [(kind, folder) for kind, folder in candidates if folder.exists()]
    if len(present) != 1:
        raise ValueError("Expected exactly one snapshot library namespace.")
    kind, folder = present[0]
    if not (folder / "__init__.py").is_file():
        raise ValueError("Missing snapshot library package.")
    if kind != "legacy" and not (folder.parent / "__init__.py").is_file():
        raise ValueError("Missing work package.")
    return kind


def namespace(root):
    return "libs" if layout(root) == "legacy" else "work.libs"


def _load(root, name, kind):
    expected = (root / "src" if kind == "src" else root).joinpath(*name.split(".")).with_suffix(".py")
    if not expected.is_file():
        raise ValueError("Missing snapshot probe module.")
    module = import_module(name)
    if Path(module.__file__).resolve() != expected.resolve():
        raise ValueError("Snapshot probe module resolved outside snapshot.")
    return module


def library(name):
    if name not in _MODULES:
        raise ValueError("Unknown snapshot probe library.")
    root = Path.cwd().resolve()
    return _load(root, namespace(root) + "." + name, layout(root))


def application(name):
    if name not in _APPLICATION:
        raise ValueError("Unknown snapshot probe application module.")
    root = Path.cwd().resolve()
    kind = layout(root)
    return _load(root, ("work." if kind == "src" else "") + name, kind)
