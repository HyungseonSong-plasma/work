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

from app import cli
from app.commands import execute as execute_command, task as task_command
from app.registry import COMMANDS, register, configured_commands
from config import load_names, require_deletion
from scripts import execute
from github import trigger
from github.model import WorkflowRegistry

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
        with patch.object(execute_command, "execute", return_value=0) as call:
            self.assertEqual(cli.main(["execute", "--single"]), 0)
            call.assert_called_once_with(True, None)

    def test_cli_serial(self):
        with patch.object(execute_command, "execute", return_value=0) as call:
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

    def test_routing_dispatches_only_one_workflow(self):
        for expression, expected in (
            ("pr_merge.py", "single_run.yml"),
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
                task_command.task("pr_merge.py")

    def test_merge_adapter(self):
        with patch.dict(os.environ, {"EXECUTION_INPUTS": PARAMS,
                                     "GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF},
                        clear=True):
            with patch.object(task_command.pr_merge, "merge_pr", return_value=SHA) as merge:
                self.assertEqual(task_command.task("pr_merge.py"), 0)
                merge.assert_called_once_with(task_command.github_api, REPO, REF, "7", SHA)

    def test_registered_command_extends_cli_without_branch(self):
        with patch.dict(COMMANDS):
            @register("sample")
            class SampleCommand:
                help = "Test-only command"

                @staticmethod
                def configure(parser):
                    parser.add_argument("--value", type=int, required=True)

                @staticmethod
                def execute(args):
                    return args.value

            with patch("app.registry.load_names", return_value=("sample",)):
                self.assertEqual(cli.main(["sample", "--value", "4"]), 4)

    def test_duplicate_registration_rejected(self):
        original = COMMANDS["trigger"]
        with self.assertRaises(ValueError):
            register("trigger")(original)
        self.assertIs(COMMANDS["trigger"], original)

    def test_invalid_registration_rejected(self):
        with self.assertRaises(TypeError):
            register("invalid")(object)
        self.assertNotIn("invalid", COMMANDS)

    def test_unknown_command_rejected(self):
        with self.assertRaises(SystemExit) as error:
            cli.main(["unregistered"])
        self.assertEqual(error.exception.code, 2)


    def test_workflow_registry_extends_without_routing_branch(self):
        registry = WorkflowRegistry()
        registry.register(("first.py", "second.py", "third.py"), "new_run.yml")
        self.assertEqual(registry.resolve(iter(("first.py", "second.py", "third.py"))),
                         "new_run.yml")

    def test_workflow_registry_preserves_order(self):
        registry = WorkflowRegistry()
        registry.register(("first.py", "second.py"), "serial.yml")
        with self.assertRaises(ValueError):
            registry.resolve(("second.py", "first.py"))

    def test_workflow_registry_rejects_duplicate(self):
        registry = WorkflowRegistry()
        registry.register(("first.py",), "single.yml")
        with self.assertRaises(ValueError):
            registry.register(("first.py",), "other.yml")
        self.assertEqual(registry.resolve(("first.py",)), "single.yml")

    def test_workflow_registry_rejects_invalid_registration(self):
        registry = WorkflowRegistry()
        for chain, workflow in (
            ((), "single.yml"),
            ("first.py", "single.yml"),
            (("first.py", "first.py"), "serial.yml"),
            (("first.py",), "../other.yml"),
            (("first.py",), "other.py"),
        ):
            with self.subTest(chain=chain, workflow=workflow):
                with self.assertRaises(ValueError):
                    registry.register(chain, workflow)

    def test_unregistered_route_does_not_dispatch(self):
        dispatch = Mock()
        with patch.object(trigger, "registry", WorkflowRegistry()):
            with self.assertRaises(ValueError):
                trigger.dispatch_request(event("pr_merge.py"), REPO, REF, dispatch)
        dispatch.assert_not_called()

    def test_reverse_chain_does_not_dispatch(self):
        dispatch = Mock()
        with self.assertRaises(ValueError):
            trigger.dispatch_request(event("branch_delete.py - pr_merge.py"),
                                     REPO, REF, dispatch)
        dispatch.assert_not_called()

    def test_wrong_repository_or_ref_does_not_dispatch(self):
        for repository, ref in (("other/work", REF), (REPO, "refs/heads/other")):
            with self.subTest(repository=repository, ref=ref):
                dispatch = Mock()
                with self.assertRaises(ValueError):
                    trigger.dispatch_request(event("pr_merge.py"), repository, ref, dispatch)
                dispatch.assert_not_called()


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

    def test_branch_disabled_blocks_before_api(self):
        from scripts.branch_delete import delete_branch
        api, git = Mock(), Mock()
        with patch("config.load_registry", return_value={
                "branch": {"enabled": False, "permission": "contents: write"}}):
            with self.assertRaises(ValueError):
                delete_branch(api, git, REPO, REF, "7", SHA, "remote")
        api.assert_not_called()
        git.assert_not_called()


if __name__ == "__main__":
    unittest.main()
