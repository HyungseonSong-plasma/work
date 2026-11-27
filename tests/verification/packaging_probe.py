# FileRank: C
"""Build and inspect application distributions; install each in a separate venv."""

import argparse
from email.parser import BytesParser
import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[2]
NAME = "work-framework"
VERSION = "0.1.0.dev0"
STEM = "work_framework-" + VERSION
SOURCE = frozenset(("work/__init__.py", "work/__main__.py",
    *("work/libs/" + name + ".py" for name in (
        "__init__", "_github_transport", "_test_grammar", "command", "frame", "github", "testing", "workflow")),
    *("work/app/" + name + ".py" for name in ("__init__", "cli", "wiring")),
    *("work/app/commands/" + name + ".py" for name in ("__init__", "delete", "execute", "merge", "test", "trigger")),
    *("work/github/" + name + ".py" for name in ("__init__", "_actions_retention", "actions", "delete", "merge", "trigger")),
    "work/config/__init__.py"))
RESOURCES = frozenset("work/config/" + name + ".toml" for name in
    ("actions_policy", "commands", "deletions", "executions", "tests", "workflows"))
PAYLOAD = SOURCE | RESOURCES

# This runs as a real file so SuiteRegistry can inspect the test method source.
SMOKE = r'''
import io
import os
import sys
import unittest
from contextlib import nullcontext
from importlib.metadata import distribution
from importlib.util import find_spec
from pathlib import Path
from unittest.mock import patch, Mock
from types import SimpleNamespace

import work
from work.libs import github, testing, _github_transport, _test_grammar
from work.libs.frame import FrameContract, Registry
from work.libs.command import Command, CommandRegistry, local_plan
from work.libs.workflow import Context

assert Path(work.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
for name in ("libs", "app", "github", "config", "tests"):
    assert find_spec(name) is None, name
metadata = distribution("work-framework")
assert metadata.version == "0.1.0.dev0"
assert metadata.metadata["Requires-Python"] == ">=3.11"
assert not metadata.requires
for name in ("GitHubClient", "CLIENT", "git_session"):
    assert getattr(github, name) is getattr(_github_transport, name)
for name in ("RUNNERS", "DECLARATION_CALLS", "EXPRESSION_NODES", "validate_method"):
    assert getattr(testing, name) is getattr(_test_grammar, name)

frame = FrameContract(("prepare", "action")).bind(
    action=lambda value: value * 2, prepare=lambda value: value + 1)
assert frame.execute(3) == 8
registry = Registry()
assert registry.add("x", frame, duplicate="duplicate") is frame
assert registry.resolve("x", unknown="unknown") is frame
with unittest.TestCase().assertRaises(ValueError):
    registry.add("x", None, duplicate="duplicate")
class Sample(Command):
    help = "smoke"
    plan = local_plan(lambda ctx, args: 7)

commands = CommandRegistry()
commands.register("sample")(Sample)
assert commands.configured(("sample",))["sample"].execute(None) == 7

class Suite(testing.TestSuite):
    def test_contract(self):
        def check(ctx):
            self.assertIsNotNone(ctx)
        self.run_contract(check=check)

suites = testing.SuiteRegistry()
suites.register("smoke")(Suite)
result = unittest.TextTestRunner().run(suites.build(("smoke",)))
assert result.wasSuccessful() and result.testsRun == 1
with unittest.TestCase().assertRaises(ValueError):
    testing.validate_method("def test_invalid(self):\n    pass")
routes = github.WorkflowRegistry()
routes.register(("a", "b"), "serial.yml")
assert routes.resolve(("a", "b")) == "serial.yml"
with unittest.TestCase().assertRaises(ValueError):
    routes.resolve(("b", "a"))
ctx = Context({"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ATTEMPT": "2"})
with unittest.TestCase().assertRaises(ValueError):
    ctx.require_event("workflow_dispatch", fresh=True)
requests = []
def send(request, timeout):
    requests.append((request.get_method(), timeout))
    return nullcontext(io.BytesIO(b'{"ok": true}'))
with patch.dict(os.environ, {"GITHUB_API_URL": "https://api.example.invalid",
                            "GH_TOKEN": "fixture"}, clear=True):
    assert github.GitHubClient(send).request("GET", "test") == {"ok": True}
assert requests == [("GET", 30)]
from work.app import cli
from work.app.commands import execute
from work.config import load_registry, ROOT
from work.app.wiring import workflow_commands
for name in ("actions_policy", "commands", "deletions", "executions", "tests", "workflows"):
    assert load_registry(name)
assert ROOT == Path(work.__file__).resolve().parent / "config"
assert tuple(workflow_commands()) == ("pr_merge.py", "branch_delete.py") or set(workflow_commands()) == {"pr_merge.py", "branch_delete.py"}
child = Mock(return_value=SimpleNamespace(returncode=0))
assert execute.run_execution(("pr_merge.py",), run=child) == 0
child.assert_called_once_with([sys.executable, "-E", "-s", "-m", "work", "merge"],
                              cwd=Path(work.__file__).resolve().parent.parent, check=False)
assert cli.main(["test"]) == 1
# A real child with no credentials or event must refuse before any remote request.
with patch.dict(os.environ, {"PATH": os.defpath}, clear=True):
    assert execute.run_execution(("pr_merge.py",)) == 1
print("Installed application smoke passed; canonical imports, resources, child execution and seven bindings verified.")
'''


def run(*args, cwd):
    print("+", *map(str, args), flush=True)
    subprocess.run([str(arg) for arg in args], cwd=cwd, check=True)


def check_metadata(data):
    meta = BytesParser().parsebytes(data)
    assert meta["Name"] == NAME, meta["Name"]
    assert meta["Version"] == VERSION
    assert meta["Requires-Python"] == ">=3.11"
    assert not meta.get_all("Requires-Dist"), meta.get_all("Requires-Dist")


def check_sources(files):
    assert {name for name in files if name.endswith(".py")} == SOURCE
    assert {name for name in files if name.endswith(".toml")} == RESOURCES
    for name in PAYLOAD:
        assert files[name] == (ROOT / "src" / name).read_bytes(), name


def check_archives(wheel, sdist):
    dist_info = STEM + ".dist-info/"
    with zipfile.ZipFile(wheel) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        assert len(names) == len(set(names))
        files = {name: archive.read(name) for name in names}
        assert all(name in PAYLOAD or name.startswith(dist_info) for name in files)
        check_sources(files)
        check_metadata(files[dist_info + "METADATA"])
        assert files[dist_info + "top_level.txt"].splitlines() == [b"work"]
        assert b"work = work.app.cli:main" in files[dist_info + "entry_points.txt"]
    # Never extract an untrusted archive: inspect only regular files.
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        assert all(item.isdir() or item.isfile() for item in members)
        assert all(item.name == STEM or item.name.startswith(STEM + "/") for item in members)
        names = [item.name for item in members if item.isfile()]
        assert len(names) == len(set(names))
        files = {item.name[len(STEM) + 1:]: archive.extractfile(item).read()
                 for item in members if item.isfile()}
        allowed = {"src/" + name for name in PAYLOAD} | {"README.md", "pyproject.toml", "MANIFEST.in",
                            "PKG-INFO", "setup.cfg"}
        egg = "src/work_framework.egg-info/"
        assert all(name in allowed or name.startswith(egg) for name in files)
        check_sources({name[4:]: value for name, value in files.items() if name.startswith("src/work/")})
        check_metadata(files["PKG-INFO"])
        assert files[egg + "top_level.txt"].splitlines() == [b"work"]
        for name in ("README.md", "pyproject.toml", "MANIFEST.in"):
            assert files[name] == (ROOT / name).read_bytes(), name
    for artifact in (wheel, sdist):
        print(artifact.name, hashlib.sha256(artifact.read_bytes()).hexdigest(), flush=True)


def verify_install(artifact, outside):
    env = outside / ("wheel-env" if artifact.suffix == ".whl" else "sdist-env")
    run(sys.executable, "-m", "venv", env, cwd=outside)
    python = env / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    run(python, "-m", "pip", "install", "--no-deps", artifact, cwd=outside)
    run(python, "-m", "pip", "check", cwd=outside)
    script = outside / "smoke.py"
    script.write_text(SMOKE, encoding="utf-8")
    run(python, "-I", script, cwd=outside)
    run(python, "-I", "-m", "work", "--help", cwd=outside)
    console = env / ("Scripts/work.exe" if sys.platform == "win32" else "bin/work")
    run(console, "--help", cwd=outside)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, help="Inspect existing artifacts instead of building.")
    args = parser.parse_args()
    print(sys.version, flush=True)
    with tempfile.TemporaryDirectory(prefix="work-distribution-") as directory:
        outside = Path(directory).resolve()
        dist = args.dist.resolve() if args.dist else outside / "dist"
        if args.dist is None:
            run(sys.executable, "-m", "build", "--outdir", dist, ROOT, cwd=outside)
        wheel, = dist.glob("*.whl")
        sdist, = dist.glob("*.tar.gz")
        check_archives(wheel, sdist)
        verify_install(wheel, outside)
        verify_install(sdist, outside)
    print("Distribution verification passed.", flush=True)


if __name__ == "__main__":
    main()
