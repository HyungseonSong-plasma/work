# FileRank: C
"""Offline execution contract tests."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.commands import execute as execute_command, task as task_command
from scripts import execute
from tests.suites.model import TestSuite, PARAMS, REPO, REF, ROOT, SHA
from tests.registry import register


@register("execution")
class ExecutionContract(TestSuite):
    def test_reject_serial_in_single_mode(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch",
                                     "EXECUTION": "pr_merge.py - branch_delete.py",
                                     "EXECUTION_INPUTS": PARAMS}, clear=True):
            with patch.object(execute_command, "run_execution") as run:
                with self.assertRaises(ValueError):
                    execute_command.execute(True, None)
                run.assert_not_called()

    def test_single_stage_child_uses_app(self):
        scripts = execute.resolve_execution("pr_merge.py", PARAMS)
        run = Mock(return_value=SimpleNamespace(returncode=0))
        self.assertEqual(execute.run_execution(scripts, run=run), 0)
        run.assert_called_once_with(
            [sys.executable, "-m", "app", "task", "pr_merge.py"],
            cwd=ROOT, check=False)

    def test_fail_fast(self):
        scripts = execute.resolve_execution("pr_merge.py - branch_delete.py", PARAMS)
        run = Mock(return_value=SimpleNamespace(returncode=5))
        self.assertEqual(execute.run_execution(scripts, run=run), 5)
        self.assertEqual(run.call_count, 1)

    def test_serial_stage_selects_only_delete(self):
        scripts = execute.resolve_execution("pr_merge.py - branch_delete.py", PARAMS)
        run = Mock(return_value=SimpleNamespace(returncode=0))
        self.assertEqual(execute.run_stage(scripts, 2, run=run), 0)
        self.assertEqual(run.call_args.args[0][-1], "branch_delete.py")
        self.assertEqual(run.call_count, 1)

    def test_task_parameter_validation(self):
        with patch.dict(os.environ, {"EXECUTION_INPUTS": "{}"}, clear=True):
            with self.assertRaises(ValueError):
                task_command.task("pr_merge.py")

    def test_merge_adapter(self):
        with patch.dict(os.environ, {"EXECUTION_INPUTS": PARAMS,
                                     "GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF},
                        clear=True):
            with patch.object(task_command.pr_merge, "merge_pr", return_value=SHA) as merge:
                self.assertEqual(task_command.task("pr_merge.py"), 0)
                merge.assert_called_once_with(task_command.github_api, REPO, REF, "7", SHA)

    def test_branch_disabled_blocks_before_api(self):
        from github.delete import delete_branch
        api, git = Mock(), Mock()
        with patch("config.load_registry", return_value={
                "branch": {"enabled": False, "permission": "contents: write"}}):
            with self.assertRaises(ValueError):
                delete_branch(api, git, REPO, REF, "7", SHA, "remote")
        api.assert_not_called()
        git.assert_not_called()
