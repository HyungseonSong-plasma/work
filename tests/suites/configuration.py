# FileRank: C
"""Offline configuration contract tests."""

from unittest.mock import patch

from app.framework.registry import configured_commands
from config import load_names, load_registry, require_deletion
from github.framework.registry import WorkflowRegistry
from app.framework.registry import execution_ids
from tests.framework.model import TestSuite, ConfigurationTestContext
from tests.framework.registry import register


@register("configuration")
class ConfigurationContract(TestSuite):
    context_type = ConfigurationTestContext

    def test_configured_commands_exclude_unlisted(self):
        def check(ctx):
            with patch("app.framework.registry.load_names", return_value=("trigger",)):
                self.assertEqual(tuple(configured_commands()), ("trigger",))

        self.run_contract(check=check)

    def test_unknown_configured_command_rejected(self):
        def check(ctx):
            with patch("app.framework.registry.load_names", return_value=("missing",)):
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
