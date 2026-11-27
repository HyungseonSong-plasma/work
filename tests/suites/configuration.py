# FileRank: C
"""Offline configuration contract tests."""

from unittest.mock import patch

from app.wiring import configured_commands
from config import load_names, load_registry, require_deletion
from libs.github import WorkflowRegistry
from app.wiring import execution_ids
from libs.testing import TestSuite
from tests.fixtures import ConfigurationTestContext
from tests.wiring import register


@register("configuration")
class ConfigurationContract(TestSuite):
    context_type = ConfigurationTestContext

    def test_configured_commands_exclude_unlisted(self):
        def check(ctx):
            with patch("app.wiring.load_names", return_value=("trigger",)):
                self.assertEqual(tuple(configured_commands()), ("trigger",))

        self.run_contract(check=check)

    def test_unknown_configured_command_rejected(self):
        def check(ctx):
            with patch("app.wiring.load_names", return_value=("missing",)):
                with self.assertRaises(ValueError):
                    configured_commands()

        self.run_contract(check=check)

    def test_duplicate_names_rejected(self):
        def check(ctx):
            with patch("config.load_registry", return_value=["task", "task"]):
                with self.assertRaises(ValueError):
                    load_names("commands")

        self.run_contract(check=check)

    def test_workflow_entries_reject_invalid_routes(self):
        entry = {"execution": ["pr_merge.py"], "workflow": "single_run.yml"}
        cases = (
            ("unknown_execution", [{"execution": ["unknown.py"], "workflow": "single_run.yml"}]),
            ("duplicate_route", [entry, dict(entry)]),
        )

        def check(ctx, entries):
            self.assert_rejected(WorkflowRegistry.from_entries, entries, execution_ids())

        self.run_cases(cases, check)

    def test_deletion_config(self):
        cases = (
            ("branch", "branch", True),
            ("actions", "actions", True),
            ("issue", "issue", False),
            ("unknown", "unknown", False),
        )

        def check(ctx, target, allowed):
            if allowed:
                require_deletion(target)
            else:
                self.assert_rejected(require_deletion, target)

        self.run_cases(cases, check)

    def test_issue_cannot_be_enabled_by_config_alone(self):
        def check(ctx):
            with patch("config.load_registry", return_value={
                    "issue": {"enabled": True, "permission": "owner authorization"}}):
                with self.assertRaises(ValueError):
                    require_deletion("issue")

        self.run_contract(check=check)

    def test_toml_loader_preserves_array_order(self):
        def check(ctx):
            with ctx.registry_root({"commands.toml":
                    '# Registry order\ncommands = ["trigger", "test"]\n'}):
                self.assertEqual(load_names("commands"), ("trigger", "test"))

        self.run_contract(check=check)

    def test_toml_loader_rejects_invalid_documents(self):
        cases = (
            ("duplicate_key", 'commands = ["trigger"]\ncommands = ["test"]\n'),
            ("unexpected_root", 'commands = ["trigger"]\nextra = true\n'),
        )

        def check(ctx, content):
            with ctx.registry_root({"commands.toml": content}):
                self.assert_rejected(load_registry, "commands")

        self.run_cases(cases, check)

    def test_toml_loader_rejects_missing_and_symlink_files(self):
        cases = (("missing", False), ("symlink", True))

        def check(ctx, symlink):
            with ctx.registry_root() as root:
                if symlink:
                    target = root / "other.toml"
                    target.write_text('commands = ["trigger"]\n', encoding="utf-8")
                    (root / "commands.toml").symlink_to(target)
                self.assert_rejected(load_registry, "commands")

        self.run_cases(cases, check)

    def test_architecture_repository_contract(self):
        def check(ctx):
            from tests.architecture import repository_violations
            from tests.fixtures import ROOT
            failures = repository_violations(ROOT)
            self.assertEqual(failures, (), "\n".join(failures))

        self.run_contract(check=check)

    def test_architecture_import_rules(self):
        cases = (
            ("frame_stdlib", "libs/frame.py", "from inspect import signature", True),
            ("workflow_command", "libs/workflow.py", "from libs.command import CommandPlan", True),
            ("relative_frame", "libs/github.py", "from . import frame", True),
            ("package_frame", "libs/command.py", "from libs import frame", True),
            ("github_config", "github/trigger.py", "def route():\n    from config import load_names", True),
            ("lazy_test", "app/commands/test.py", "def action(ctx, args):\n    from tests import suites\n    from tests.wiring import build_suite", True),
            ("ordinary_test", "tests/suites/cli.py", "from app import cli", True),
            ("library_application", "libs/workflow.py", "from app.wiring import resolve_execution", False),
            ("library_domain", "libs/github.py", "import github.actions", False),
            ("library_config", "libs/testing.py", "if False:\n    import config", False),
            ("library_test", "libs/command.py", "def run():\n    import tests.fixtures", False),
            ("frame_reverse", "libs/frame.py", "from .command import Command", False),
            ("wrong_library", "libs/github.py", "from libs.testing import TestSuite", False),
            ("undeclared_library", "libs/new.py", "import json", False),
            ("external_dependency", "libs/frame.py", "import requests", False),
            ("domain_application", "github/delete.py", "from app import wiring", False),
            ("domain_test", "github/actions.py", "from tests import fixtures", False),
            ("domain_command", "github/merge.py", "from libs.command import Command", False),
            ("config_production", "config/__init__.py", "from libs.frame import Registry", False),
            ("eager_test", "app/commands/test.py", "from tests import suites", False),
            ("wrong_adapter", "app/commands/merge.py", "def action(ctx, args):\n    from tests import suites", False),
            ("wrong_function", "app/commands/test.py", "def prepare():\n    from tests import suites", False),
            ("wrong_test_target", "app/commands/test.py", "def action(ctx, args):\n    import tests.fixtures", False),
            ("direct_testing_lib", "app/cli.py", "from libs.testing import TestSuite", False),
            ("legacy_import", "tests/suites/cli.py", "from app.framework.model import Command", False),
            ("relative_legacy", "tests/suites/cli.py", "from ..framework import model", False),
            ("dynamic_module", "libs/github.py", "from importlib import import_module", False),
            ("dynamic_builtin", "libs/frame.py", "__import__('app')", False),
        )

        def check(ctx, path, source, allowed):
            from tests.architecture import source_violations
            failures = source_violations(path, source)
            self.assertEqual(not failures, allowed, failures)

        self.run_cases(cases, check)

    def test_architecture_legacy_path_and_missing_library(self):
        def check(ctx):
            from pathlib import Path
            from tempfile import TemporaryDirectory
            from tests.architecture import repository_violations, LIBRARIES, ROOTS
            with TemporaryDirectory() as directory:
                root = Path(directory)
                for package in ROOTS:
                    (root / package).mkdir()
                for module in LIBRARIES:
                    path = (root / "libs" / "__init__.py" if module == "libs" else
                            root.joinpath(*module.split(".")).with_suffix(".py"))
                    path.write_text("", encoding="utf-8")
                self.assertEqual(repository_violations(root), ())
                (root / "libs" / "frame.py").unlink()
                (root / "app" / "framework").mkdir()
                (root / "tests" / "framework.py").write_text("", encoding="utf-8")
                self.assertEqual(repository_violations(root), (
                    "Legacy framework path: app.framework",
                    "Legacy framework path: tests.framework",
                    "Missing library: libs.frame"))

        self.run_contract(check=check)

    def test_architecture_import_runtime_boundaries(self):
        cases = (
            ("frame", "libs.frame", ("app", "github", "config", "tests")),
            ("command", "libs.command", ("app", "github", "config", "tests")),
            ("github", "libs.github", ("app", "github", "config", "tests")),
            ("workflow", "libs.workflow", ("app", "github", "config", "tests")),
            ("testing", "libs.testing", ("app", "github", "config", "tests")),
            ("domain", "github.actions, github.delete, github.merge, github.trigger", ("app", "tests", "libs.testing")),
            ("cli", "app.cli", ("tests", "libs.testing")),
        )

        def check(ctx, modules, forbidden):
            import subprocess
            import sys
            from tests.fixtures import ROOT
            code = ("import sys; import " + modules + "; "
                    "assert not any(n == p or n.startswith(p + '.') "
                    "for n in sys.modules for p in " + repr(forbidden) + ")")
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

        self.run_cases(cases, check)

    def test_architecture_framework_ownership(self):
        def check(ctx):
            from app.wiring import COMMANDS
            from libs.command import Command, CommandRegistry, _COMMAND_FRAME
            from libs.frame import Frame
            from libs.github import JsonMutation
            from github.merge import MERGE
            from libs.testing import SuiteRegistry, validate_suite
            from tests.wiring import SUITES
            from tests.suites.registry_contract import RegistryContract
            self.assertIs(type(COMMANDS), CommandRegistry)
            self.assertIs(type(SUITES), SuiteRegistry)
            self.assertIs(type(_COMMAND_FRAME), Frame)
            self.assertEqual(_COMMAND_FRAME.contract.stages, ("prepare", "validate", "action", "report"))
            self.assertIs(type(MERGE), Frame)
            self.assertEqual(MERGE.contract.stages, ("prepare", "mutate", "confirm"))
            self.assertIs(MERGE.callbacks[1], JsonMutation.execute)
            for command in COMMANDS.values():
                self.assertIs(command.execute.__func__, Command.execute.__func__)
                self.assertIs(command.bind.__func__, Command.bind.__func__)
            for name, suite in SUITES.items():
                if name == "registry":
                    self.assertIs(suite, RegistryContract)
                else:
                    self.assertTrue(validate_suite(suite))

        self.run_contract(check=check)
