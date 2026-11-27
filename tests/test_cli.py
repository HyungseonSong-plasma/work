# FileRank: C
"""Offline CLI contract tests; never use GitHub credentials or mutate a repository."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import cli, commands
from scripts import execute, trigger

SHA = "a" * 40
PARAMS = json.dumps({"pr_number": 7, "expected_head_sha": SHA})
REPO = "example/work"
REF = "refs/heads/main"
ROOT = Path(__file__).resolve().parents[1]


def event(expression):
    return {
        "action": "created",
        "repository": {"full_name": REPO, "default_branch": "main", "owner": {"id": 1}},
        "comment": {"id": 12, "user": {"id": 1}, "author_association": "OWNER",
                    "body": "/execute " + json.dumps({
                        "execution": expression, "expected_head_sha": SHA})},
        "sender": {"id": 1},
        "issue": {"number": 7, "pull_request": {}},
    }


class CLIContract(unittest.TestCase):
    def test_help_starts_real_module(self):
        result = subprocess.run([sys.executable, "-m", "app", "--help"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("trigger", result.stdout)

    def test_cli_single(self):
        with patch.object(commands, "execute", return_value=0) as call:
            self.assertEqual(cli.main(["execute", "--single"]), 0)
            call.assert_called_once_with(True, None)

    def test_cli_serial(self):
        with patch.object(commands, "execute", return_value=0) as call:
            self.assertEqual(cli.main(["execute", "--serial-stage", "2"]), 0)
            call.assert_called_once_with(False, 2)

    def test_reject_unknown_task(self):
        with self.assertRaises(SystemExit) as error:
            cli.main(["task", "unregistered.py"])
        self.assertEqual(error.exception.code, 2)

    def test_reject_serial_in_single_mode(self):
        with patch.dict(os.environ, {"GITHUB_EVENT_NAME": "workflow_dispatch",
                                     "EXECUTION": "pr_merge.py - branch_delete.py",
                                     "EXECUTION_INPUTS": PARAMS}, clear=True):
            with patch.object(commands, "run_execution") as run:
                with self.assertRaises(ValueError):
                    commands.execute(True, None)
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

    def test_routing_dispatches_only_one_workflow(self):
        for expression, expected in (
            ("branch_delete.py", "single_run.yml"),
            ("pr_merge.py - branch_delete.py", "serial_run.yml"),
        ):
            with self.subTest(expression=expression):
                dispatch = Mock()
                self.assertEqual(trigger.dispatch_request(event(expression), REPO, REF, dispatch),
                                 (expected, "comment-12"))
                dispatch.assert_called_once()
                self.assertEqual(dispatch.call_args.args[1], expected)

    def test_unauthorized_dispatch_rejected(self):
        request = event("pr_merge.py")
        request["sender"]["id"] = 2
        dispatch = Mock()
        with self.assertRaises(ValueError):
            trigger.dispatch_request(request, REPO, REF, dispatch)
        dispatch.assert_not_called()

    def test_task_parameter_validation(self):
        with patch.dict(os.environ, {"EXECUTION_INPUTS": "{}"}, clear=True):
            with self.assertRaises(ValueError):
                commands.task("pr_merge.py")

    def test_merge_adapter(self):
        with patch.dict(os.environ, {"EXECUTION_INPUTS": PARAMS,
                                     "GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF},
                        clear=True):
            with patch.object(commands.pr_merge, "merge_pr", return_value=SHA) as merge:
                self.assertEqual(commands.task("pr_merge.py"), 0)
                merge.assert_called_once_with(commands.github_api, REPO, REF, "7", SHA)


if __name__ == "__main__":
    unittest.main()
