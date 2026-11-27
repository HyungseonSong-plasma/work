# FileRank: C
"""Offline configuration contract tests."""

import unittest
from unittest.mock import patch

from app.registry import configured_commands
from config import load_names, require_deletion
from github.model import WorkflowRegistry
from scripts import execute
from tests.registry import register


@register("configuration")
class ConfigurationContract(unittest.TestCase):
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

    def test_workflow_json_rejects_unknown_execution(self):
        with self.assertRaises(ValueError):
            WorkflowRegistry.from_json(
                [{"execution": ["unknown.py"], "workflow": "single_run.yml"}],
                execute.EXECUTIONS)

    def test_workflow_json_rejects_duplicate_routes(self):
        entry = {"execution": ["pr_merge.py"], "workflow": "single_run.yml"}
        with self.assertRaises(ValueError):
            WorkflowRegistry.from_json([entry, entry], execute.EXECUTIONS)

    def test_deletion_config(self):
        require_deletion("branch")
        for target in ("issue", "actions", "unknown"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    require_deletion(target)

    def test_issue_cannot_be_enabled_by_json_alone(self):
        with patch("config.load_registry", return_value={
                "issue": {"enabled": True, "permission": "owner authorization"}}):
            with self.assertRaises(ValueError):
                require_deletion("issue")
