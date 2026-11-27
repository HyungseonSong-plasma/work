# FileRank: C
"""Offline execution contract tests."""

from contextlib import contextmanager
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.commands import execute as execute_command, merge as merge_command, delete as delete_command
from app.framework.model import Context, PRContext
from app.framework.registry import resolve_execution
from tests.framework.model import TestSuite, WorkflowTestContext, PARAMS, REPO, REF, ROOT, SHA
from tests.framework.registry import register


@register("execution")
class ExecutionContract(TestSuite):
    context_type = WorkflowTestContext

    def test_reject_serial_in_single_mode(self):
        @contextmanager
        def arrange(ctx):
            with ctx.patched_environment(EXECUTION="pr_merge.py - branch_delete.py"):
                with patch.object(execute_command, "run_execution") as ctx.run:
                    yield

        def act(ctx):
            return execute_command.ExecuteCommand.execute(SimpleNamespace(single=True, serial_stage=None))

        def check(ctx, error):
            ctx.run.assert_not_called()

        self.run_contract(act, check, arrange=arrange, raises=ValueError)

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
        @contextmanager
        def arrange(ctx):
            with ctx.patched_environment():
                with patch.object(merge_command.merge, "merge_pr", return_value=SHA) as ctx.merge:
                    yield

        def act(ctx):
            return merge_command.MergeCommand.execute(None)

        def check(ctx, result):
            self.assertEqual(result, 0)
            ctx.merge.assert_called_once_with(merge_command.github_api, REPO, REF, "7", SHA)

        self.run_contract(act, check, arrange=arrange)

    def test_branch_disabled_blocks_before_api(self):
        def check(ctx):
            from github.delete import delete_branch
            api, git = Mock(), Mock()
            with patch("config.load_registry", return_value={
                    "branch": {"enabled": False, "permission": "contents: write"}}):
                with self.assertRaises(ValueError):
                    delete_branch(api, git, REPO, REF, "7", SHA, "remote")
            api.assert_not_called()
            git.assert_not_called()

        self.run_contract(check=check)

    def test_branch_adapter_uses_shared_context(self):
        def check(ctx):
            from app import cli
            with ctx.patched_environment():
                with patch.object(delete_command, "delete", return_value="Deleted branch") as call:
                    self.assertEqual(cli.main(["delete", "branch"]), 0)
                    call.assert_called_once_with("branch", api=delete_command.github_api,
                        repository=REPO, run_ref=REF, number="7", sha=SHA,
                        remote=f"https://github.com/{REPO}.git")

        self.run_contract(check=check)

    def test_branch_rejects_actions_arguments(self):
        def check(ctx):
            from app import cli
            with patch.object(delete_command, "delete") as call:
                self.assertEqual(cli.main(["delete", "branch", "--run-id", "12"]), 1)
                call.assert_not_called()

        self.run_contract(check=check)

    def test_context_snapshots_environment(self):
        def snapshot(ctx):
            ctx.env = {"GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF}
            ctx.snapshot = Context(ctx.env)

        def mutate(ctx):
            ctx.env["GITHUB_REF"] = "changed"

        def check(ctx):
            self.assertEqual((ctx.snapshot.repository, ctx.snapshot.ref), (REPO, REF))

        steps = (("snapshot", snapshot), ("mutate_source", mutate))
        self.run_scenario(steps, check)

    def test_pr_context_exposes_validated_fields(self):
        def check(ctx):
            ctx = PRContext("pr_merge.py", env=ctx.environment()).validate()
            self.assertEqual((ctx.number, ctx.sha, ctx.repository, ctx.ref),
                             ("7", SHA, REPO, REF))

        self.run_contract(check=check)

    def test_execution_identifiers_need_no_physical_scripts(self):
        def check(ctx):
            self.assertFalse((ROOT / "scripts").exists())
            self.assertEqual(resolve_execution("pr_merge.py - branch_delete.py", PARAMS),
                             ("pr_merge.py", "branch_delete.py"))

        self.run_contract(check=check)

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
        def check(ctx):
            from app.framework.registry import COMMANDS
            with patch.object(COMMANDS["merge"], "workflow_execution", ()):
                self.assert_rejected(resolve_execution, "pr_merge.py", PARAMS)

        self.run_contract(check=check)

    def test_command_workflow_validation_precedes_action(self):
        cases = (
            ("trigger_wrong_event", "trigger", ["trigger"], {"GITHUB_EVENT_NAME": "workflow_dispatch"}),
            ("trigger_rerun", "trigger", ["trigger"], {"GITHUB_EVENT_NAME": "issue_comment", "GITHUB_RUN_ATTEMPT": "2"}),
            ("execute_wrong_event", "execute", ["execute", "--single"], {"GITHUB_EVENT_NAME": "issue_comment"}),
            ("execute_rerun", "execute", ["execute", "--single"], {"GITHUB_RUN_ATTEMPT": "2"}),
            ("merge_wrong_event", "merge", ["merge"], {"GITHUB_EVENT_NAME": "issue_comment"}),
            ("merge_rerun", "merge", ["merge"], {"GITHUB_RUN_ATTEMPT": "2"}),
            ("branch_wrong_event", "delete", ["delete", "branch"], {"GITHUB_EVENT_NAME": "issue_comment"}),
            ("branch_rerun", "delete", ["delete", "branch"], {"GITHUB_RUN_ATTEMPT": "2"}),
            ("actions_wrong_event", "delete", ["delete", "actions"], {"GITHUB_EVENT_NAME": "issue_comment"}),
            ("actions_rerun", "delete", ["delete", "actions"], {"GITHUB_RUN_ATTEMPT": "2"}),
        )

        def check(ctx, name, args, changes):
            from app import cli
            from app.commands import trigger as trigger_command
            with ctx.patched_environment(EXECUTION="pr_merge.py", **changes):
                with patch.object(trigger_command, "dispatch_request") as dispatch, \
                        patch.object(execute_command, "run_execution") as run, \
                        patch.object(merge_command.merge, "merge_pr") as merge, \
                        patch.object(delete_command, "delete") as delete:
                    self.assertEqual(cli.main(args), 1)
                    for action in (dispatch, run, merge, delete):
                        action.assert_not_called()

        self.run_cases(cases, check)

    def test_trigger_reports_exact_dispatch(self):
        def check(ctx):
            from app.commands import trigger as trigger_command
            from app import cli
            from app.framework.model import Context
            event = ctx.event("pr_merge.py")
            with ctx.patched_environment(GITHUB_EVENT_NAME="issue_comment"):
                with patch.object(Context, "read_event", return_value=event) as read, \
                        patch.object(trigger_command, "dispatch_request",
                                     return_value=("single_run.yml", "comment-12")) as dispatch, \
                        patch.object(Context, "report") as report:
                    self.assertEqual(cli.main(["trigger"]), 0)
                    read.assert_called_once_with()
                    dispatch.assert_called_once_with(event, REPO, REF)
                    report.assert_called_once_with(
                        "Submitted single_run.yml: comment-12",
                        "Submitted `single_run.yml` for `comment-12`.\n\n"
                        "Execution result is reported by the dispatched run.\n")

        self.run_contract(check=check)

    def test_execute_command_propagates_child_status(self):
        cases = (("single", ["execute", "--single"], "pr_merge.py", None, 5),
                 ("serial", ["execute", "--serial-stage", "2"],
                  "pr_merge.py - branch_delete.py", 2, 7))

        def check(ctx, args, expression, stage, expected):
            from app import cli
            with ctx.patched_environment(EXECUTION=expression):
                with patch.object(execute_command, "run_execution", return_value=expected) as run, \
                        patch.object(execute_command, "run_stage", return_value=expected) as serial:
                    self.assertEqual(cli.main(args), expected)
                    if stage is None:
                        run.assert_called_once_with(("pr_merge.py",))
                        serial.assert_not_called()
                    else:
                        serial.assert_called_once_with(("pr_merge.py", "branch_delete.py"), stage)
                        run.assert_not_called()

        self.run_cases(cases, check)
