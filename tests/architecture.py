# FileRank: C
"""Project-owned static architecture contract; not a Python security sandbox."""

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path
from tokenize import open as open_source


LIBRARIES = {
    "work": frozenset(),
    "work.libs": frozenset(),
    "work.libs.frame": frozenset(),
    "work.libs.command": frozenset(("work.libs.frame",)),
    "work.libs._github_transport": frozenset(),
    "work.libs.github": frozenset(("work.libs.frame", "work.libs._github_transport")),
    "work.libs.workflow": frozenset(("work.libs.command", "work.libs.github")),
    "work.libs._test_grammar": frozenset(),
    "work.libs.testing": frozenset(("work.libs.frame", "work.libs._test_grammar")),
}
LEGACY = ("libs", "app", "app.framework", "github", "github.framework", "config",
          "work.app.framework", "work.github.framework", "tests.framework",
          "framework_tests", "tests.framework_tests")
ROOTS = ("src/work", "src/work/app", "src/work/github", "src/work/config", "tests")
DOMAIN_LIBS = frozenset(("work.libs.frame", "work.libs.github", "work.libs.workflow"))
APP_LIBS = DOMAIN_LIBS | {"work.libs.command"}
LAZY_TESTS = frozenset(("tests.suites", "tests.wiring"))


def _module(path):
    parts = Path(path).with_suffix("").parts
    if parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _targets(node, package):
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    module = node.module or ""
    if node.level:
        module = resolve_name("." * node.level + module, package)
    # Package-level from imports may name modules, so expand them explicitly.
    if module in ("work", "work.libs", "work.app", "work.github", "tests"):
        return tuple(module + "." + alias.name for alias in node.names)
    return (module,)


def _layer(module):
    parts = module.split(".")
    return ".".join(parts[:2]) if parts[0] == "work" else parts[0]


def _allowed(source, target, lazy):
    root = _layer(source)
    dependency = _layer(target)
    if any(target == name or target.startswith(name + ".") for name in LEGACY):
        return False
    if root == "tests":
        return True
    if dependency == "importlib":
        return False
    if not target.startswith("work.") and target != "work" and dependency != "tests":
        return dependency in sys.stdlib_module_names
    if source == "work.__main__":
        return target == "work.app.cli"
    if source in LIBRARIES:
        return target in LIBRARIES[source]
    if root == "work.config":
        return False
    if root == "work.github":
        return dependency in ("work.github", "work.config") or target in DOMAIN_LIBS
    if root == "work.app":
        return (dependency in ("work.app", "work.github", "work.config") or target in APP_LIBS
                or (source == "work.app.commands.test" and lazy and target in LAZY_TESTS))
    return False


def source_violations(path, source):
    """Inspect all import statements, including nested and relative imports."""
    module = _module(path)
    root = module.split(".")[0]
    if root in ("libs", "app", "github", "config") or (root == "work" and Path(path).parts[0] != "src"):
        return (f"{path}: legacy source {module}",)
    if (root == "work" and module not in LIBRARIES and module != "work.__main__"
            and _layer(module) not in ("work.app", "work.github", "work.config")):
        return (f"{path}: undeclared library module {module}",)
    package = module if Path(path).name == "__init__.py" else module.rpartition(".")[0]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        return (f"{path}:{error.lineno}: invalid Python source",)
    action_imports = {
        id(child)
        for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "action"
        for child in node.body if isinstance(child, (ast.Import, ast.ImportFrom))
    }
    failures = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            try:
                targets = _targets(node, package)
            except (ImportError, ValueError):
                failures.append(f"{path}:{node.lineno}: invalid relative import")
                continue
            for target in targets:
                if not _allowed(module, target, id(node) in action_imports):
                    failures.append(f"{path}:{node.lineno}: forbidden import {target}")
        elif root != "tests" and isinstance(node, ast.Call):
            func = node.func
            name = (func.id if isinstance(func, ast.Name) else
                    func.attr if isinstance(func, ast.Attribute) else None)
            if name in ("__import__", "import_module", "eval", "exec"):
                failures.append(f"{path}:{node.lineno}: dynamic execution/import {name}")
    return tuple(failures)


def repository_violations(root):
    """Scan source without importing production or test modules."""
    root = Path(root)
    failures = []
    for name in LEGACY:
        path = root.joinpath(*name.split(".")) if not name.startswith("work.") else root.joinpath("src", *name.split("."))
        if path.exists() or path.with_suffix(".py").exists():
            failures.append(f"Legacy framework path: {name}")
    if (root / "work").exists() or (root / "work.py").exists():
        failures.append("Legacy source path: work")
    for module in LIBRARIES:
        path = root.joinpath("src", *module.split("."))
        path = path / "__init__.py" if module in ("work", "work.libs") else path.with_suffix(".py")
        if not path.is_file():
            failures.append(f"Missing library: {module}")
    for package in ROOTS:
        folder = root / package
        if not folder.is_dir():
            failures.append(f"Missing package: {package}")
    for folder in (root / "src", root / "tests"):
        for path in sorted(folder.rglob("*.py")):
            with open_source(path) as stream:
                failures.extend(source_violations(path.relative_to(root), stream.read()))
    return tuple(failures)
