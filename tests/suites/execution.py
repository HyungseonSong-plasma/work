# FileRank: C
"""Offline execution contract tests."""

from contextlib import contextmanager
import sys
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from app.commands import execute as execute_command, merge as merge_command, delete as delete_command
from libs.workflow import Context, PRContext
from app.wiring import resolve_execution
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
                self.assert_rejected(PRContext("pr_merge.py", resolve=resolve_execution).validate)

        self.run_cases(cases, check)

    def test_merge_adapter(self):
        @contextmanager
        def arrange(ctx):
            with ctx.patched_environment():
                with patch.object(merge_command.merge, "MERGE") as ctx.merge:
                    ctx.merge.execute.return_value = SHA
                    yield

        def act(ctx):
            return merge_command.MergeCommand.execute(None)

        def check(ctx, result):
            self.assertEqual(result, 0)
            ctx.merge.execute.assert_called_once_with(
                merge_command.merge.MergeOperation(merge_command.CLIENT.request, REPO, REF, "7", SHA))

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
                    call.assert_called_once_with("branch", api=delete_command.CLIENT.request,
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
            ctx = PRContext("pr_merge.py", env=ctx.environment(), resolve=resolve_execution).validate()
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
            from app.wiring import COMMANDS
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
                        patch.object(merge_command.merge, "MERGE") as merge, \
                        patch.object(delete_command, "delete") as delete:
                    self.assertEqual(cli.main(args), 1)
                    for action in (dispatch, run, merge.execute, delete):
                        action.assert_not_called()

        self.run_cases(cases, check)

    def test_trigger_reports_exact_dispatch(self):
        def check(ctx):
            from app.commands import trigger as trigger_command
            from app import cli
            from libs.workflow import Context
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

    def test_merge_domain_exact_review_and_guarded_put(self):
        def check(ctx):
            from github.merge import MERGE, MergeOperation
            root = "repos/example/work"
            endpoint = root + "/pulls/7"
            api = Mock(side_effect=[{"default_branch": "main"}, ctx.pull_request(),
                                    {"merged": True, "sha": "b" * 40}])
            self.assertEqual(MERGE.execute(MergeOperation(api, REPO, REF, 7, SHA)), "b" * 40)
            self.assertEqual(api.call_args_list, [
                call("GET", root), call("GET", endpoint),
                call("PUT", endpoint + "/merge", {"sha": SHA, "merge_method": "merge"})])

        self.run_contract(check=check)

    def test_merge_domain_invalid_inputs_stop_before_remote_review(self):
        cases = (("boolean_pr", True, SHA), ("zero_pr", 0, SHA),
                 ("leading_zero", "07", SHA), ("short_sha", 7, "a" * 39),
                 ("uppercase_sha", 7, "A" * 40))
        # Each row supplies exactly the same independent reviewed input contract.
        def check(ctx, number, sha):
            from github.merge import MERGE, MergeOperation
            api = Mock()
            self.assert_rejected(MERGE.execute, MergeOperation(api, REPO, REF, number, sha))
            api.assert_not_called()

        self.run_cases(cases, check)

    def test_merge_domain_rejects_unreviewed_pr(self):
        cases = (
            ("wrong_ref", "refs/heads/other", {}),
            ("closed", REF, {"state": "closed"}),
            ("draft", REF, {"draft": True}),
            ("merged", REF, {"merged": True}),
            ("wrong_base", REF, {"base": {"ref": "other", "repo": {"full_name": REPO}}}),
            ("wrong_repository", REF, {"base": {"ref": "main", "repo": {"full_name": "other/work"}}}),
            ("wrong_sha", REF, {"head": {"sha": "b" * 40}}),
        )

        def check(ctx, ref, changes):
            from github.merge import MERGE, MergeOperation
            pr = ctx.pull_request()
            pr.update(changes)
            api = Mock(side_effect=[{"default_branch": "main"}, pr])
            self.assert_rejected(MERGE.execute, MergeOperation(api, REPO, ref, "7", SHA))
            expected = [call("GET", "repos/example/work")]
            if ref == REF:
                expected.append(call("GET", "repos/example/work/pulls/7"))
            self.assertEqual(api.call_args_list, expected)

        self.run_cases(cases, check)

    def test_merge_domain_requires_confirmed_result(self):
        cases = (("not_merged", {"merged": False, "sha": SHA}),
                 ("missing_confirmation", {"sha": SHA}),
                 ("invalid_sha", {"merged": True, "sha": "bad"}),
                 ("missing_sha", {"merged": True}))

        def check(ctx, response):
            from github.merge import MERGE, MergeOperation
            root = "repos/example/work"
            api = Mock(side_effect=[{"default_branch": "main"}, ctx.pull_request(), response])
            self.assert_rejected(MERGE.execute, MergeOperation(api, REPO, REF, "7", SHA))
            self.assertEqual(api.call_args_list, [
                call("GET", root), call("GET", root + "/pulls/7"),
                call("PUT", root + "/pulls/7/merge", {"sha": SHA, "merge_method": "merge"})])

        self.run_cases(cases, check)

    def test_guarded_json_mutation_rejects_invalid_prepared_request(self):
        cases = (("foreign_object", None), ("read_method", "GET"),
                 ("delete_method", "DELETE"), ("unknown_method", "INVALID"))

        def check(ctx, method):
            from libs.github import JsonMutation, guarded_json_mutation
            api, confirm = Mock(), Mock()
            foreign = Mock()
            prepared = (foreign if method is None else
                        JsonMutation(api, method, "repos/example/work", {}))
            prepare = Mock(return_value=prepared)
            frame = guarded_json_mutation(prepare, confirm)
            with self.assertRaisesRegex(TypeError, "Expected a prepared JSON mutation"):
                frame.execute(ctx)
            prepare.assert_called_once_with(ctx)
            api.assert_not_called()
            foreign.execute.assert_not_called()
            confirm.assert_not_called()

        self.run_cases(cases, check)

    def test_guarded_json_mutation_fixed_executor_and_failure(self):
        cases = (("success", None), ("prepare_failure", "prepare"),
                 ("api_failure", "mutate"), ("confirm_failure", "confirm"))

        def check(ctx, failure):
            from libs.github import JsonMutation, guarded_json_mutation
            result = {"merged": True, "sha": SHA}
            api = Mock(side_effect=ValueError("mutate") if failure == "mutate" else None,
                       return_value=result)
            request = JsonMutation(api, "PUT", "repos/example/work/pulls/7/merge", {"sha": SHA})
            prepare = Mock(side_effect=ValueError("prepare") if failure == "prepare" else None,
                           return_value=request)
            confirm = Mock(side_effect=ValueError("confirm") if failure == "confirm" else None,
                           return_value=SHA)
            trace = Mock()
            for name, callback in (("prepare", prepare), ("api", api), ("confirm", confirm)):
                trace.attach_mock(callback, name)
            frame = guarded_json_mutation(prepare, confirm)
            self.assertEqual(frame.contract.stages, ("prepare", "mutate", "confirm"))
            self.assertIs(frame.callbacks[1], JsonMutation.execute)
            if failure:
                with self.assertRaisesRegex(ValueError, failure):
                    frame.execute(ctx)
            else:
                self.assertEqual(frame.execute(ctx), SHA)
            expected = [call.prepare(ctx)]
            if failure != "prepare":
                expected.append(call.api("PUT", "repos/example/work/pulls/7/merge", {"sha": SHA}))
            if failure not in ("prepare", "mutate"):
                expected.append(call.confirm(result))
            self.assertEqual(trace.mock_calls, expected)

        self.run_cases(cases, check)

    def test_merge_operation_does_not_reuse_review_state(self):
        def check(ctx):
            from github.merge import MERGE, MergeOperation
            from dataclasses import FrozenInstanceError
            root = "repos/example/work"
            pr = ctx.pull_request()
            invalid = dict(pr, draft=True)
            api = Mock(side_effect=[{"default_branch": "main"}, pr, {"merged": True, "sha": SHA},
                                    {"default_branch": "main"}, invalid])
            operation = MergeOperation(api, REPO, REF, 7, SHA)
            self.assertEqual(MERGE.execute(operation), SHA)
            self.assertEqual(operation.pr_number, 7)
            with self.assertRaises(FrozenInstanceError):
                operation.expected_head_sha = "b" * 40
            self.assert_rejected(MERGE.execute, operation)
            self.assertEqual(api.call_args_list, [
                call("GET", root), call("GET", root + "/pulls/7"),
                call("PUT", root + "/pulls/7/merge", {"sha": SHA, "merge_method": "merge"}),
                call("GET", root), call("GET", root + "/pulls/7")])

        self.run_contract(check=check)

    def test_workflow_library_import_is_domain_independent(self):
        def check(ctx):
            import subprocess
            import sys
            code = ("import sys; import libs.workflow; "
                    "assert not any(name.split('.')[0] in ('app', 'tests', 'github', 'config') "
                    "for name in sys.modules)")
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((ROOT / "app" / "framework").exists())

        self.run_contract(check=check)

    def test_pr_context_injected_resolver_order(self):
        cases = (("success", {}, False, True),
                 ("wrong_event", {"GITHUB_EVENT_NAME": "issue_comment"}, False, False),
                 ("rerun", {"GITHUB_RUN_ATTEMPT": "2"}, False, False),
                 ("resolver_rejection", {}, True, True),
                 ("invalid_parameters", {"EXECUTION_INPUTS": "{}"}, False, True))

        def check(ctx, changes, reject, calls_resolver):
            resolver = Mock(side_effect=ValueError("Rejected execution.") if reject else None)
            context = PRContext("custom.py", env=ctx.environment(**changes), resolve=resolver)
            if changes or reject:
                self.assert_rejected(context.validate)
                self.assertFalse(hasattr(context, "number"))
                self.assertFalse(hasattr(context, "sha"))
            else:
                self.assertIs(context.validate(), context)
                self.assertEqual((context.number, context.sha), ("7", SHA))
            if calls_resolver:
                resolver.assert_called_once_with("custom.py", changes.get("EXECUTION_INPUTS", PARAMS))
            else:
                resolver.assert_not_called()

        self.run_cases(cases, check)

    def test_pr_plan_preflight_and_resolver_precede_action(self):
        cases = (("valid", None), ("preflight_reject", "preflight"),
                 ("resolve_reject", "resolve"), ("wrong_event", "event"))

        def check(ctx, failure):
            from libs.workflow import pr_plan
            from libs.command import Command
            from unittest.mock import call
            args = object()
            trace = Mock()
            preflight = Mock(side_effect=ValueError("preflight") if failure == "preflight" else None)
            resolver = Mock(side_effect=ValueError("resolve") if failure == "resolve" else None)
            action = Mock(return_value="confirmed")
            report = Mock()
            for name, callback in (("preflight", preflight), ("resolve", resolver),
                                   ("action", action), ("report", report)):
                trace.attach_mock(callback, name)

            class Sample(Command):
                help = "Workflow contract"
                plan = pr_plan("custom.py", action, resolve=resolver,
                               preflight=preflight, report=report)

            changes = {"GITHUB_EVENT_NAME": "issue_comment"} if failure == "event" else {}
            with ctx.patched_environment(**changes):
                if failure:
                    self.assert_rejected(Sample.execute, args)
                else:
                    self.assertEqual(Sample.execute(args), 0)
            expected = [call.preflight(args)]
            if failure not in ("preflight", "event"):
                expected.append(call.resolve("custom.py", PARAMS))
            if not failure:
                validated, actual_args = action.call_args.args
                self.assertEqual((validated.number, validated.sha), ("7", SHA))
                self.assertIs(actual_args, args)
                expected.extend([call.action(validated, args), call.report(validated, "confirmed")])
            self.assertEqual(trace.mock_calls, expected)

        self.run_cases(cases, check)
