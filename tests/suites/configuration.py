# FileRank: C
"""Offline configuration contract tests."""

from unittest.mock import patch

from work.app.wiring import configured_commands
from work.config import load_names, load_registry, require_deletion
from work.libs.github import WorkflowRegistry
from work.app.wiring import execution_ids
from work.libs.testing import TestSuite
from tests.fixtures import ConfigurationTestContext
from tests.wiring import register


@register("configuration")
class ConfigurationContract(TestSuite):
    context_type = ConfigurationTestContext

    def test_configured_commands_exclude_unlisted(self):
        def check(ctx):
            with patch("work.app.wiring.load_names", return_value=("trigger",)):
                self.assertEqual(tuple(configured_commands()), ("trigger",))

        self.run_contract(check=check)

    def test_unknown_configured_command_rejected(self):
        def check(ctx):
            with patch("work.app.wiring.load_names", return_value=("missing",)):
                with self.assertRaises(ValueError):
                    configured_commands()

        self.run_contract(check=check)

    def test_duplicate_names_rejected(self):
        def check(ctx):
            with patch("work.config.load_registry", return_value=["task", "task"]):
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
            with patch("work.config.load_registry", return_value={
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
            ("frame_stdlib", "src/work/libs/frame.py", "from inspect import signature", True),
            ("workflow_command", "src/work/libs/workflow.py", "from work.libs.command import CommandPlan", True),
            ("transport_stdlib", "src/work/libs/_github_transport.py", "from urllib.request import Request", True),
            ("github_transport", "src/work/libs/github.py", "from work.libs._github_transport import GitHubClient", True),
            ("transport_reverse", "src/work/libs/_github_transport.py", "from work.libs.github import CLIENT", False),
            ("transport_frame", "src/work/libs/_github_transport.py", "from work.libs.frame import Frame", False),
            ("workflow_private_transport", "src/work/libs/workflow.py", "from work.libs._github_transport import CLIENT", False),
            ("app_private_transport", "src/work/app/cli.py", "from work.libs._github_transport import CLIENT", False),
            ("domain_private_transport", "src/work/github/delete.py", "from work.libs._github_transport import git_session", False),
            ("grammar_stdlib", "src/work/libs/_test_grammar.py", "import ast", True),
            ("testing_grammar", "src/work/libs/testing.py", "from work.libs._test_grammar import validate_method", True),
            ("grammar_reverse", "src/work/libs/_test_grammar.py", "from work.libs.testing import TestSuite", False),
            ("grammar_frame", "src/work/libs/_test_grammar.py", "from work.libs.frame import Registry", False),
            ("github_private_grammar", "src/work/libs/github.py", "from work.libs._test_grammar import RUNNERS", False),
            ("app_private_grammar", "src/work/app/cli.py", "from work.libs._test_grammar import RUNNERS", False),
            ("domain_private_grammar", "src/work/github/actions.py", "from work.libs._test_grammar import RUNNERS", False),
            ("relative_frame", "src/work/libs/github.py", "from . import frame", True),
            ("package_frame", "src/work/libs/command.py", "from work.libs import frame", True),
            ("github_config", "src/work/github/trigger.py", "def route():\n    from work.config import load_names", True),
            ("lazy_test", "src/work/app/commands/test.py", "def action(ctx, args):\n    from tests import suites\n    from tests.wiring import build_suite", True),
            ("ordinary_test", "tests/suites/cli.py", "from work.app import cli", True),
            ("library_application", "src/work/libs/workflow.py", "from work.app.wiring import resolve_execution", False),
            ("library_domain", "src/work/libs/github.py", "import work.github.actions", False),
            ("library_config", "src/work/libs/testing.py", "if False:\n    import work.config", False),
            ("library_test", "src/work/libs/command.py", "def run():\n    import tests.fixtures", False),
            ("frame_reverse", "src/work/libs/frame.py", "from .command import Command", False),
            ("wrong_library", "src/work/libs/github.py", "from work.libs.testing import TestSuite", False),
            ("undeclared_library", "src/work/libs/new.py", "import json", False),
            ("external_dependency", "src/work/libs/frame.py", "import requests", False),
            ("domain_application", "src/work/github/delete.py", "from work.app import wiring", False),
            ("domain_test", "src/work/github/actions.py", "from tests import fixtures", False),
            ("domain_command", "src/work/github/merge.py", "from work.libs.command import Command", False),
            ("config_production", "src/work/config/__init__.py", "from work.libs.frame import Registry", False),
            ("eager_test", "src/work/app/commands/test.py", "from tests import suites", False),
            ("wrong_adapter", "src/work/app/commands/merge.py", "def action(ctx, args):\n    from tests import suites", False),
            ("wrong_function", "src/work/app/commands/test.py", "def prepare():\n    from tests import suites", False),
            ("wrong_test_target", "src/work/app/commands/test.py", "def action(ctx, args):\n    import tests.fixtures", False),
            ("direct_testing_lib", "src/work/app/cli.py", "from work.libs.testing import TestSuite", False),
            ("legacy_import", "tests/suites/cli.py", "from work.app.framework.model import Command", False),
            ("relative_legacy", "tests/suites/cli.py", "from ..framework import model", False),
            ("dynamic_module", "src/work/libs/github.py", "from importlib import import_module", False),
            ("dynamic_builtin", "src/work/libs/frame.py", "__import__('work.app')", False),
            ("legacy_lib", "src/work/app/cli.py", "from libs.command import Command", False),
            ("legacy_app", "tests/suites/cli.py", "from app import cli", False),
            ("legacy_domain", "tests/suites/cli.py", "import github.actions", False),
            ("legacy_config", "tests/suites/cli.py", "import config", False),
            ("legacy_test_lib", "tests/suites/cli.py", "import libs", False),
            ("legacy_lib_source", "libs/frame.py", "import ast", False),
            ("bare_work", "src/work/app/cli.py", "import work", False),
            ("bare_library_package", "src/work/app/cli.py", "from work import libs", False),
            ("undeclared_work", "src/work/extra.py", "import ast", False),
            ("unknown_work_dependency", "src/work/libs/frame.py", "import work.extra", False),
            ("private_from_package", "src/work/app/cli.py", "from work.libs import _test_grammar", False),
            ("namespace_init", "src/work/__init__.py", "import work.libs", False),
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
                    (root / package).mkdir(parents=True, exist_ok=True)
                for module in LIBRARIES:
                    path = root.joinpath("src", *module.split("."))
                    path = path / "__init__.py" if module in ("work", "work.libs") else path.with_suffix(".py")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("", encoding="utf-8")
                self.assertEqual(repository_violations(root), ())
                (root / "src" / "work" / "libs" / "frame.py").unlink()
                (root / "libs").mkdir()
                (root / "app" / "framework").mkdir(parents=True)
                (root / "tests" / "framework.py").write_text("", encoding="utf-8")
                self.assertEqual(repository_violations(root), (
                    "Legacy framework path: libs",
                    "Legacy framework path: app",
                    "Legacy framework path: app.framework",
                    "Legacy framework path: tests.framework",
                    "Missing library: work.libs.frame"))

        self.run_contract(check=check)

    def test_architecture_import_runtime_boundaries(self):
        cases = (
            ("frame", "work.libs.frame", ("work.app", "work.github", "work.config", "tests")),
            ("command", "work.libs.command", ("work.app", "work.github", "work.config", "tests")),
            ("transport", "work.libs._github_transport", ("work.app", "work.github", "work.config", "tests", "work.libs.frame", "work.libs.github", "work.libs.command", "work.libs.workflow", "work.libs.testing")),
            ("github", "work.libs.github", ("work.app", "work.github", "work.config", "tests")),
            ("workflow", "work.libs.workflow", ("work.app", "work.github", "work.config", "tests")),
            ("grammar", "work.libs._test_grammar", ("work.app", "work.github", "work.config", "tests", "work.libs.frame", "work.libs.github", "work.libs.command", "work.libs.workflow", "work.libs.testing", "work.libs._github_transport")),
            ("testing", "work.libs.testing", ("work.app", "work.github", "work.config", "tests")),
            ("domain", "work.github.actions, work.github.delete, work.github.merge, work.github.trigger", ("work.app", "tests", "work.libs.testing")),
            ("cli", "work.app.cli", ("tests", "work.libs.testing")),
        )

        def check(ctx, modules, forbidden):
            from tests.fixtures import import_probe
            result = import_probe(modules.split(", "), (*forbidden, "libs", "app", "github", "config"))
            self.assertEqual(result.returncode, 0, result.stderr)

        self.run_cases(cases, check)

    def test_architecture_framework_ownership(self):
        def check(ctx):
            from work.app.wiring import COMMANDS
            from work.libs.command import Command, CommandRegistry, _COMMAND_FRAME
            from work.libs.frame import Frame
            from work.libs.github import JsonMutation
            from work.github.merge import MERGE
            from work.libs.testing import SuiteRegistry, validate_suite
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

    def test_shared_import_probe_distinguishes_module_prefixes(self):
        cases = (
            ("exact", ("json",), ("json",), False),
            ("child", ("json.decoder",), ("json",), False),
            ("specific_child", ("json",), ("json.decoder",), False),
            ("different_prefix", ("json",), ("jsonx",), True),
            ("missing_module", ("nonexistent_fixture_module_xyz",), (), False),
            ("multiple_modules", ("json", "math"), ("math",), False),
        )

        def check(ctx, modules, forbidden, allowed):
            from tests.fixtures import import_probe
            result = import_probe(modules, forbidden)
            self.assertEqual(result.returncode == 0, allowed, result.stderr)

        self.run_cases(cases, check)
