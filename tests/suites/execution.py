# FileRank: C
"""Offline execution contract tests."""

import sys
from unittest.mock import Mock, patch

from app.commands import execute as execute_command, merge as merge_command, delete as delete_command
from app.commands.model import Context, PRContext
from app.registry import resolve_execution
from tests.suites.model import TestSuite, WorkflowTestContext, PARAMS, REPO, REF, ROOT, SHA
from tests.registry import register


@register("execution")
class ExecutionContract(TestSuite):
    context_type = WorkflowTestContext

    def test_reject_serial_in_single_mode(self):
        with self.ctx.patched_environment(EXECUTION="pr_merge.py - branch_delete.py"):
            with patch.object(execute_command, "run_execution") as run:
                with self.assertRaises(ValueError):
                    execute_command.execute(True, None)
                run.assert_not_called()

    def test_execution_subprocess_contract(self):
        cases = (
            ("single_merge", "pr_merge.py", None, 0, ("merge",)),
            ("serial_fail_fast", "pr_merge.py - branch_delete.py", None, 5, ("merge",)),
            ("serial_delete_stage", "pr_merge.py - branch_delete.py", 2, 0, ("delete", "branch")),
        )

        def check(ctx, expression, stage, exit_code, expected):
            executions = resolve_execution(expression, PARAMS)
            run = ctx.process(exit_code)
            result = (execute_command.run_execution(executions, run=run) if stage is None
                      else execute_command.run_stage(executions, stage, run=run))
            self.assertEqual(result, exit_code)
            run.assert_called_once_with(
                [sys.executable, "-m", "app", *expected], cwd=ROOT, check=False)

        self.run_cases(cases, check)

    def test_pr_context_rejects_invalid_inputs(self):
        cases = (
            ("invalid_parameters", {"EXECUTION_INPUTS": "{}"}),
            ("wrong_event", {"GITHUB_EVENT_NAME": "issue_comment"}),
            ("rerun", {"GITHUB_RUN_ATTEMPT": "2"}),
        )

        def check(ctx, changes):
            with ctx.patched_environment(**changes):
                self.assert_rejected(PRContext("pr_merge.py").validate)

        self.run_cases(cases, check)

    def test_merge_adapter(self):
        with self.ctx.patched_environment():
            with patch.object(merge_command.merge, "merge_pr", return_value=SHA) as merge:
                self.assertEqual(merge_command.MergeCommand.execute(None), 0)
                merge.assert_called_once_with(merge_command.github_api, REPO, REF, "7", SHA)

    def test_branch_disabled_blocks_before_api(self):
        from github.delete import delete_branch
        api, git = Mock(), Mock()
        with patch("config.load_registry", return_value={
                "branch": {"enabled": False, "permission": "contents: write"}}):
            with self.assertRaises(ValueError):
                delete_branch(api, git, REPO, REF, "7", SHA, "remote")
        api.assert_not_called()
        git.assert_not_called()

    def test_branch_adapter_uses_shared_context(self):
        from app import cli
        with self.ctx.patched_environment():
            with patch.object(delete_command, "delete", return_value="Deleted branch") as call:
                self.assertEqual(cli.main(["delete", "branch"]), 0)
                call.assert_called_once_with("branch", api=delete_command.github_api,
                    repository=REPO, run_ref=REF, number="7", sha=SHA,
                    remote=f"https://github.com/{REPO}.git")

    def test_branch_rejects_actions_arguments(self):
        from app import cli
        with patch.object(delete_command, "delete") as call:
            self.assertEqual(cli.main(["delete", "branch", "--run-id", "12"]), 1)
            call.assert_not_called()

    def test_context_snapshots_environment(self):
        env = {"GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF}
        ctx = Context(env)
        env["GITHUB_REF"] = "changed"
        self.assertEqual((ctx.repository, ctx.ref), (REPO, REF))

    def test_pr_context_exposes_validated_fields(self):
        ctx = PRContext("pr_merge.py", env=self.ctx.environment()).validate()
        self.assertEqual((ctx.number, ctx.sha, ctx.repository, ctx.ref),
                         ("7", SHA, REPO, REF))

    def test_execution_identifiers_need_no_physical_scripts(self):
        self.assertFalse((ROOT / "scripts").exists())
        self.assertEqual(resolve_execution("pr_merge.py - branch_delete.py", PARAMS),
                         ("pr_merge.py", "branch_delete.py"))

    def test_registry_rejects_unknown_duplicate_reverse_or_path(self):
        cases = (
            ("unknown", "test.py"),
            ("duplicate", "pr_merge.py - pr_merge.py"),
            ("reverse", "branch_delete.py - pr_merge.py"),
            ("path", "../pr_merge.py"),
            ("empty", ""),
        )

        def check(ctx, expression):
            self.assert_rejected(resolve_execution, expression, PARAMS)

        self.run_cases(cases, check)

    def test_resolution_rejects_missing_command_binding(self):
        from app.registry import COMMANDS
        with patch.object(COMMANDS["merge"], "workflow_execution", ()):
            self.assert_rejected(resolve_execution, "pr_merge.py", PARAMS)
