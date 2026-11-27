# FileRank: C
"""Offline configuration contract tests."""

from unittest.mock import patch

from app.registry import configured_commands
from config import load_names, load_registry, require_deletion
from github.model import WorkflowRegistry
from app.registry import execution_ids
from tests.suites.model import TestSuite, ConfigurationTestContext
from tests.registry import register


@register("configuration")
class ConfigurationContract(TestSuite):
    context_type = ConfigurationTestContext

    def test_configured_commands_exclude_unlisted(self):
        with patch("app.registry.load_names", return_value=("trigger",)):
            self.assertEqual(tuple(configured_commands()), ("trigger",))

    def test_unknown_configured_command_rejected(self):
        with patch("app.registry.load_names", return_value=("missing",)):
            with self.assertRaises(ValueError):
                configured_commands()

    def test_duplicate_names_rejected(self):
        with patch("config.load_registry", return_value=["task", "task"]):
            with self.assertRaises(ValueError):
                load_names("commands")

    def test_workflow_entries_rejects_unknown_execution(self):
        with self.assertRaises(ValueError):
            WorkflowRegistry.from_entries(
                [{"execution": ["unknown.py"], "workflow": "single_run.yml"}],
                execution_ids())

    def test_workflow_entries_rejects_duplicate_routes(self):
        entry = {"execution": ["pr_merge.py"], "workflow": "single_run.yml"}
        with self.assertRaises(ValueError):
            WorkflowRegistry.from_entries([entry, entry], execution_ids())

    def test_deletion_config(self):
        require_deletion("branch")
        require_deletion("actions")
        for target in ("issue", "unknown"):
            with self.subTest(target=target):
                self.assert_rejected(require_deletion, target)

    def test_issue_cannot_be_enabled_by_config_alone(self):
        with patch("config.load_registry", return_value={
                "issue": {"enabled": True, "permission": "owner authorization"}}):
            with self.assertRaises(ValueError):
                require_deletion("issue")


    def test_toml_loader_preserves_array_order(self):
        with self.ctx.registry_root({"commands.toml":
                '# Registry order\ncommands = ["trigger", "test"]\n'}):
            self.assertEqual(load_names("commands"), ("trigger", "test"))

    def test_toml_loader_rejects_duplicate_keys(self):
        with self.ctx.registry_root({"commands.toml":
                'commands = ["trigger"]\ncommands = ["test"]\n'}):
            with self.assertRaises(ValueError):
                load_registry("commands")

    def test_toml_loader_rejects_unexpected_root(self):
        with self.ctx.registry_root({"commands.toml":
                'commands = ["trigger"]\nextra = true\n'}):
            with self.assertRaises(ValueError):
                load_registry("commands")

    def test_toml_loader_rejects_missing_and_symlink_files(self):
        with self.ctx.registry_root() as root:
            with self.assertRaises(ValueError):
                load_registry("commands")
            target = root / "other.toml"
            target.write_text('commands = ["trigger"]\n', encoding="utf-8")
            (root / "commands.toml").symlink_to(target)
            with self.assertRaises(ValueError):
                load_registry("commands")
