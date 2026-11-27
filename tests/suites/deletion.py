# FileRank: C
"""Offline deletion policy and target dispatch tests."""

from contextlib import nullcontext
from copy import deepcopy
import json
from unittest.mock import Mock, call, patch

from github.actions import ActionsContext
from types import SimpleNamespace
from github import actions, delete as deletion
from libs.github import GitHubClient
from tests.wiring import register
from libs.testing import TestSuite
from tests.fixtures import ActionsTestContext, REPO, REF, SHA
from github import trigger
from app.commands.trigger import route_registry
from app.wiring import resolve_execution


@register("deletion")
class DeletionContract(TestSuite):
    context_type = ActionsTestContext

    def test_actions_delete_exact_run(self):
        def act(ctx):
            return deletion.delete("actions", **ctx.parameters)

        def check(ctx, result):
            self.assertEqual(result, "Deleted Actions run: 12")
            ctx.remove.assert_called_once_with(f"repos/{REPO}/actions/runs/12")

        self.run_contract(act, check)

    def test_branch_target_dispatch(self):
        def check(ctx):
            handler = Mock(return_value="Deleted branch")
            with patch.dict(deletion.DELETIONS, {"branch": handler}):
                self.assertEqual(deletion.delete("branch", number="7"), "Deleted branch")
            handler.assert_called_once_with(number="7")

        self.run_contract(check=check)

    def test_disabled_and_unknown_targets(self):
        cases = (
            ("issue", "issue", None),
            ("unknown", "unknown", None),
            ("disabled_actions", "actions",
             {"actions": {"enabled": False, "permission": "actions: write"}}),
        )

        def check(ctx, target, config):
            if config is None:
                self.assert_rejected(deletion.delete, target)
            else:
                with patch("config.load_registry", return_value=config):
                    self.assert_rejected(deletion.delete, target, **ctx.parameters)
            ctx.api.assert_not_called()
            ctx.remove.assert_not_called()

        self.run_cases(cases, check)

    def test_actions_reject_invalid_or_current_id(self):
        cases = (
            ("boolean", True),
            ("zero", 0),
            ("negative", -1),
            ("current_run", 13),
            ("string", "12"),
        )

        def check(ctx, run_id):
            self.assert_rejected(deletion.delete, "actions", **dict(ctx.parameters, run_id=run_id))
            ctx.api.assert_not_called()
            ctx.remove.assert_not_called()

        self.run_cases(cases, check)

    def test_actions_reject_unreviewed_metadata(self):
        cases = (
            ("in_progress", {"status": "in_progress"}),
            ("wrong_sha", {"head_sha": "b" * 40}),
            ("wrong_attempt", {"run_attempt": 2}),
            ("wrong_id", {"id": 99}),
            ("wrong_repository", {"repository": {"id": 2, "full_name": REPO}}),
        )

        def check(ctx, changes):
            ctx.run_data.update(changes)
            self.assert_rejected(deletion.delete, "actions", **ctx.parameters)
            ctx.remove.assert_not_called()

        self.run_cases(cases, check)

    def test_actions_reject_changed_run_or_ref(self):
        cases = (
            ("changed_run", REF, True),
            ("non_default_ref", "refs/heads/other", False),
        )

        def check(ctx, ref, changed):
            if changed:
                ctx.api.side_effect = [ctx.repo, ctx.run_data, dict(ctx.run_data, run_attempt=2)]
            self.assert_rejected(deletion.delete, "actions", **dict(ctx.parameters, run_ref=ref))
            ctx.remove.assert_not_called()

        self.run_cases(cases, check)

    def test_latest_success_retained_for_each_workflow(self):
        # Explicit expected policy, independent of the production manifest.
        cases = (
            ("trigger", ".github/workflows/trigger.yml"),
            ("single", ".github/workflows/single_run.yml"),
            ("serial", ".github/workflows/serial_run.yml"),
            ("actions_delete", ".github/workflows/actions_delete.yml"),
        )

        def check(ctx, path):
            run = dict(ctx.run_data, path=path, workflow_id=7,
                       conclusion="success", created_at="2026-11-27T10:00:00Z")
            ctx.api.side_effect = [ctx.repo, run, {"total_count": 1, "workflow_runs": [run]}]
            self.assert_rejected(deletion.delete, "actions", **ctx.parameters)
            ctx.remove.assert_not_called()

        self.run_cases(cases, check)

    def test_older_success_can_be_deleted(self):
        def check(ctx):
            run = dict(ctx.run_data, path=".github/workflows/trigger.yml", workflow_id=7,
                       conclusion="success", created_at="2026-11-27T10:00:00Z")
            newer = dict(run, id=20, created_at="2026-11-27T11:00:00Z")
            listing = {"total_count": 2, "workflow_runs": [newer, run]}
            ctx.api.side_effect = [ctx.repo, run, listing, run, listing]
            self.assertEqual(deletion.delete("actions", **ctx.parameters), "Deleted Actions run: 12")
            ctx.remove.assert_called_once()

        self.run_contract(check=check)

    def test_pinned_run_cannot_be_deleted(self):
        def arrange(ctx):
            ctx.pinned = actions.actions_policy()["pinned_run_ids"][0]
            ctx.run_data["id"] = ctx.pinned
            return nullcontext()

        def act(ctx):
            return deletion.delete("actions", **dict(ctx.parameters, run_id=ctx.pinned))

        def check(ctx, error):
            ctx.remove.assert_not_called()

        self.run_contract(act, check, arrange=arrange, raises=ValueError)

    def test_batch_preflight_rejects_before_any_delete(self):
        def arrange(ctx):
            ctx.targets = [ctx.target(), ctx.target(14)]
            ctx.api.side_effect = [ctx.repo, deepcopy(ctx.run_data),
                                   dict(ctx.run_data, id=14, status="in_progress")]
            ctx.params = ctx.batch_parameters
            return nullcontext()

        def act(ctx):
            return deletion.delete("actions_batch", targets=ctx.targets, **ctx.params)

        def check(ctx, error):
            ctx.remove.assert_not_called()

        self.run_contract(act, check, arrange=arrange, raises=ValueError)

    def test_batch_deletes_exact_targets(self):
        def check(ctx):
            targets = [ctx.target(),
                       ctx.target(14)]
            first, second = deepcopy(ctx.run_data), dict(ctx.run_data, id=14)
            ctx.api.side_effect = [ctx.repo, first, second, first, second]
            params = ctx.batch_parameters
            self.assertEqual(deletion.delete("actions_batch", targets=targets, report=Mock(), **params),
                             ["Deleted Actions run: 12", "Deleted Actions run: 14"])
            self.assertEqual([call.args[0] for call in ctx.remove.call_args_list],
                             [f"repos/{REPO}/actions/runs/12", f"repos/{REPO}/actions/runs/14"])

        self.run_contract(check=check)

    def test_batch_invalid_and_duplicate_rejected(self):
        cases = (
            ("empty", ()),
            ("duplicate", (12, 12)),
            ("boolean_id", (True,)),
            ("over_limit", tuple(range(1, 32))),
        )

        def check(ctx, ids):
            targets = [ctx.target(run_id) for run_id in ids]
            self.assert_rejected(actions.validate_actions_targets, targets)

        self.run_cases(cases, check)

    def test_batch_comment_dispatches_once(self):
        def check(ctx):
            targets = [ctx.target(),
                       ctx.target(14)]
            request = ctx.event("pr_merge.py")
            request["comment"].update(created_at="now", updated_at="now",
                body="/execute " + json.dumps({"execution": "delete actions", "runs": targets}))
            dispatch = Mock()
            self.assertEqual(trigger.dispatch_request(request, REPO, REF, dispatch,
                                         routes=route_registry, resolve=resolve_execution),
                             ("actions_delete.yml", "comment-12"))
            dispatch.assert_called_once()
            self.assertEqual(json.loads(dispatch.call_args.args[2]["inputs"]["runs"]), targets)

        self.run_contract(check=check)

    def test_actions_context_requires_owner_and_workflow(self):
        cases = (
            ("owner", False, "1", None, None, True),
            ("wrong_actor", False, "2", None, None, False),
            ("wrong_workflow", False, "1", "other", None, False),
            ("sender_mismatch", False, "1", None, {"id": 2}, False),
            ("bot_without_approval", True, "41898282", None, None, False),
        )

        def check(ctx, bot, actor, workflow, sender, allowed):
            event = ctx.approval_event(bot=bot)
            if sender is not None:
                event["sender"] = sender
            workflow = ctx.workflow_ref if workflow is None else workflow
            if allowed:
                ctx.validate_context(event, REPO, REF, actor, workflow)
            else:
                self.assert_rejected(ctx.validate_context, event, REPO, REF, actor, workflow)

        self.run_cases(cases, check)

    def test_rest_delete_requires_204(self):
        cases = (("no_content", 204, True), ("ok_not_accepted", 200, False))

        def check(ctx, status, allowed):
            from unittest.mock import MagicMock
            response = MagicMock(status=status)
            send = MagicMock()
            send.return_value.__enter__.return_value = response
            endpoint = "repos/example/work/actions/runs/12"
            with patch.object(GitHubClient, "_request") as request:
                if allowed:
                    GitHubClient(send).delete(endpoint)
                    request.assert_called_once_with("DELETE", endpoint, None)
                else:
                    self.assert_rejected(GitHubClient(send).delete, endpoint)

        self.run_cases(cases, check)

    def test_owner_comment_routes_actions_only(self):
        def check(ctx):
            request = ctx.event("pr_merge.py")
            request["comment"].update(created_at="now", updated_at="now")
            request["comment"]["body"] = "/execute " + json.dumps({
                "execution": "delete actions", "run_id": 12,
                "expected_head_sha": SHA, "expected_run_attempt": 1})
            dispatch = Mock()
            workflow, request_id = trigger.dispatch_request(request, REPO, REF, dispatch,
                                         routes=route_registry, resolve=resolve_execution)
            self.assertEqual((workflow, request_id), ("actions_delete.yml", "comment-12"))
            dispatch.assert_called_once_with(REPO, workflow, {
                "ref": "main", "inputs": {"run_id": "12", "expected_head_sha": SHA,
                    "expected_run_attempt": "1", "source_pr": "7", "request_id": "comment-12"}})

        self.run_contract(check=check)

    def test_actions_comment_rejects_invalid_requests(self):
        cases = (
            ("boolean_id", {"run_id": True}),
            ("queue_not_supported", {"queue_comment_id": 1}),
            ("zero_attempt", {"expected_run_attempt": 0}),
            ("invalid_sha", {"expected_head_sha": "bad"}),
        )

        def check(ctx, changes):
            request = ctx.event("pr_merge.py")
            request["comment"].update(created_at="now", updated_at="now")
            body = dict(ctx.target(), execution="delete actions")
            request["comment"]["body"] = "/execute " + json.dumps(dict(body, **changes))
            dispatch = Mock()
            self.assert_rejected(trigger.dispatch_request, request, REPO, REF, dispatch,
                                 routes=route_registry, resolve=resolve_execution)
            dispatch.assert_not_called()

        self.run_cases(cases, check)

    def test_actions_worker_revalidates_source_comment(self):
        body = {"execution": "delete actions", "run_id": 12,
                "expected_head_sha": SHA, "expected_run_attempt": 1}
        cases = (
            ("valid", {}, True),
            ("edited", {"updated_at": "later"}, False),
            ("wrong_owner", {"user": {"id": 2}}, False),
            ("changed_target", {"body": "/execute " + json.dumps(dict(body, run_id=99))}, False),
        )

        def check(ctx, changes, valid):
            context = ctx.approval_event(bot=True)
            inputs = {"run_id": "12", "expected_head_sha": SHA, "expected_run_attempt": "1"}
            comment = {"id": 12, "user": {"id": 1}, "author_association": "OWNER",
                       "created_at": "now", "updated_at": "now",
                       "issue_url": f"https://api.github.com/repos/{REPO}/issues/7",
                       "body": "/execute " + json.dumps(body)}
            comment.update(changes)
            pr = {"number": 7, "base": {"repo": {"full_name": REPO}}}

            def validate():
                return ctx.validate_context(context, REPO, REF, "41898282", ctx.workflow_ref,
                                            "comment-12", "7", inputs,
                                            api=Mock(side_effect=[comment, pr]))

            if valid:
                validate()
            else:
                self.assert_rejected(validate)

        self.run_cases(cases, check)

    def test_actions_context_normalizes_single_and_batch(self):
        def single(ctx):
            ctx.event_data = ctx.approval_event()
            ctx.expected = ctx.target()
            ctx.single = ctx.validate_context(ctx.event_data, REPO, REF, "1", ctx.workflow_ref)

        def batch(ctx):
            ctx.batch = ctx.validate_context(ctx.event_data, REPO, REF, "1", ctx.workflow_ref,
                                             inputs={"runs": json.dumps([ctx.expected])})

        def check(ctx):
            self.assertEqual(ctx.single.targets, [ctx.expected])
            self.assertEqual(ctx.batch.targets, ctx.single.targets)

        steps = (("single", single), ("batch", batch))
        self.run_scenario(steps, check)

    def test_actions_context_rejects_mixed_inputs_before_reading_event(self):
        def arrange(ctx):
            args = SimpleNamespace(runs="[]", run_id=12, expected_head_sha=SHA,
                                   expected_run_attempt=1, request_id="", source_pr="")
            ctx.action_ctx = ActionsContext(args, env={"GITHUB_EVENT_NAME": "workflow_dispatch",
                                                      "GITHUB_RUN_ATTEMPT": "1"}, api=ctx.api)
            ctx.read = Mock()
            return patch.object(ctx.action_ctx, "read_event", ctx.read)

        def act(ctx):
            return ctx.action_ctx.validate()

        def check(ctx, error):
            ctx.read.assert_not_called()
            ctx.api.assert_not_called()

        self.run_contract(act, check, arrange=arrange, raises=ValueError)

    def test_batch_approval_cannot_be_replaced_with_single(self):
        def approve(ctx):
            ctx.event_data = ctx.approval_event(bot=True)
            ctx.expected = ctx.target()
            ctx.comment = {"id": 12, "user": {"id": 1}, "author_association": "OWNER",
                           "created_at": "now", "updated_at": "now",
                           "issue_url": f"https://api.github.com/repos/{REPO}/issues/7",
                           "body": "/execute " + json.dumps({"execution": "delete actions",
                                                             "runs": [ctx.expected]})}
            ctx.pr = {"number": 7, "base": {"repo": {"full_name": REPO}}}
            approved = ctx.validate_context(ctx.event_data, REPO, REF, "41898282", ctx.workflow_ref,
                                           "comment-12", "7", {"runs": json.dumps([ctx.expected])},
                                           api=Mock(side_effect=[ctx.comment, ctx.pr]))
            self.assertEqual(approved.targets, [ctx.expected])

        def check(ctx):
            self.assert_rejected(ctx.validate_context, ctx.event_data, REPO, REF, "41898282",
                                 ctx.workflow_ref, "comment-12", "7",
                                 api=Mock(side_effect=[ctx.comment, ctx.pr]))

        steps = (("approve_batch", approve),)
        self.run_scenario(steps, check)

    def test_actions_command_uses_one_batch_path(self):
        def check(ctx):
            from app.commands import delete as command
            target = ctx.target()
            validated = Mock(repository=REPO, ref=REF, run_id=13, targets=[target])
            with patch("github.actions.ActionsContext") as context, \
                    patch.object(command, "delete") as delete:
                context.return_value.validate.return_value = validated
                args = SimpleNamespace(target="actions")
                self.assertEqual(command.DeleteCommand.execute(args), 0)
                context.assert_called_once_with(args)
                context.return_value.validate.assert_called_once_with()
                delete.assert_called_once_with("actions_batch", api=command.CLIENT.request,
                    remove=command.CLIENT.delete, repository=REPO, run_ref=REF,
                    current_run_id=13, targets=[target], report=validated.report)

        self.run_contract(check=check)

    def test_branch_domain_rejects_unreviewed_pr(self):
        cases = (
            ("wrong_ref", "refs/heads/other", {}),
            ("open", REF, {"state": "open"}),
            ("not_merged", REF, {"merged": False}),
            ("wrong_base", REF, {"base": {"ref": "other", "repo": {"full_name": REPO}}}),
            ("wrong_repo", REF, {"base": {"ref": "main", "repo": {"full_name": "other/work"}}}),
            ("wrong_sha", REF, {"head": {"sha": "b" * 40}}),
        )

        def check(ctx, ref, changes):
            pr = ctx.pull_request(merged=True)
            pr.update(changes)
            api = Mock(side_effect=[{"default_branch": "main"}, pr])
            git = Mock()
            self.assert_rejected(deletion.delete_branch, api, git, REPO, ref, "7", SHA, "remote")
            expected = [call("GET", "repos/example/work")]
            if ref == REF:
                expected.append(call("GET", "repos/example/work/pulls/7"))
            self.assertEqual(api.call_args_list, expected)
            git.assert_not_called()

        self.run_cases(cases, check)

    def test_branch_domain_skips_unsafe_heads(self):
        cases = (
            ("fork", "feature/topic", {"full_name": "other/work"}, "Skip: fork or missing head repository."),
            ("missing", "feature/topic", None, "Skip: fork or missing head repository."),
            ("main", "main", {"full_name": REPO}, "Skip: default or reserved branch."),
            ("master", "master", {"full_name": REPO}, "Skip: default or reserved branch."),
            ("custom_default", "stable", {"full_name": REPO}, "Skip: default or reserved branch."),
        )

        def check(ctx, branch, head_repo, expected):
            default = "stable" if branch == "stable" else "main"
            pr = ctx.pull_request(merged=True)
            pr["base"]["ref"] = default
            pr["head"].update(ref=branch, repo=head_repo)
            api = Mock(side_effect=[{"default_branch": default}, pr])
            git = Mock()
            self.assertEqual(deletion.delete_branch(api, git, REPO, f"refs/heads/{default}",
                                                    "7", SHA, "remote"), expected)
            self.assertEqual(api.call_args_list, [call("GET", "repos/example/work"),
                                                 call("GET", "repos/example/work/pulls/7")])
            git.assert_not_called()

        self.run_cases(cases, check)

    def test_branch_domain_skips_absent_changed_or_protected(self):
        cases = (
            ("absent", 2, "", None, "Skip: branch already absent."),
            ("changed_git", 0, "changed", None, "Skip: branch head has changed."),
            ("protected", 0, None, {"protected": True, "commit": {"sha": SHA}},
             "Skip: protected branch or changed head."),
            ("changed_api", 0, None, {"protected": False, "commit": {"sha": "b" * 40}},
             "Skip: protected branch or changed head."),
        )

        def check(ctx, status, output, details, expected):
            ref = "refs/heads/feature/topic"
            api = Mock(side_effect=[{"default_branch": "main"}, ctx.pull_request(merged=True), details])
            git = Mock(side_effect=[None, SimpleNamespace(returncode=status,
                stdout=f"{SHA}\t{ref}\n" if output is None else output)])
            self.assertEqual(deletion.delete_branch(api, git, REPO, REF, "7", SHA, "remote"), expected)
            calls = [call("GET", "repos/example/work"), call("GET", "repos/example/work/pulls/7")]
            if details is not None:
                calls.append(call("GET", "repos/example/work/branches/feature%2Ftopic"))
            self.assertEqual(api.call_args_list, calls)
            self.assertEqual(git.call_args_list, [
                call("check-ref-format", ref),
                call("ls-remote", "--exit-code", "--refs", "remote", ref, allowed=(0, 2))])

        self.run_cases(cases, check)

    def test_branch_domain_scans_all_pages_before_exact_lease(self):
        cases = (("clear", None, None), ("head_in_use", "head", {"full_name": REPO}),
                 ("base_in_use", "base", {"full_name": REPO}),
                 ("unknown_repository", "head", None),
                 ("fork_reference", "head", {"full_name": "other/work"}),
                 ("invalid_page", "invalid", None))

        def check(ctx, side, repository):
            root = "repos/example/work"
            ref = "refs/heads/feature/topic"
            unrelated = {"head": {"ref": "unrelated", "repo": {"full_name": REPO}},
                         "base": {"ref": "main", "repo": {"full_name": REPO}}}
            other = deepcopy(unrelated)
            if side in ("head", "base"):
                other[side] = {"ref": "feature/topic", "repo": repository}
            page = {} if side == "invalid" else [other]
            api = Mock(side_effect=[{"default_branch": "main"}, ctx.pull_request(merged=True),
                       {"protected": False, "commit": {"sha": SHA}}, [unrelated] * 100, page])
            git = Mock(side_effect=[None, SimpleNamespace(returncode=0, stdout=f"{SHA}\t{ref}\n"), None])
            args = (api, git, REPO, REF, "7", SHA, "remote")
            if side == "invalid":
                self.assert_rejected(deletion.delete_branch, *args)
            else:
                expected = ("Deleted merged PR head: feature/topic" if side is None or repository == {"full_name": "other/work"}
                            else "Skip: branch is used by an open PR.")
                self.assertEqual(deletion.delete_branch(*args), expected)
            self.assertEqual(api.call_args_list, [
                call("GET", root), call("GET", root + "/pulls/7"),
                call("GET", root + "/branches/feature%2Ftopic"),
                call("GET", root + "/pulls?state=open&per_page=100&page=1"),
                call("GET", root + "/pulls?state=open&per_page=100&page=2")])
            calls = [call("check-ref-format", ref),
                     call("ls-remote", "--exit-code", "--refs", "remote", ref, allowed=(0, 2))]
            if side is None or repository == {"full_name": "other/work"}:
                calls.append(call("push", f"--force-with-lease={ref}:{SHA}", "remote", f":{ref}"))
            self.assertEqual(git.call_args_list, calls)

        self.run_cases(cases, check)

    def test_branch_git_session_is_scoped_and_cleans_up(self):
        cases = (("success", 0), ("failure", 1))

        def check(ctx, status):
            from pathlib import Path
            import os
            observed = []

            def branch(api, git, repository, run_ref, number, sha, remote):
                directory = Path(run.call_args.args[0][-1])
                self.assertTrue(directory.is_dir())
                observed.append(directory)
                git("check-ref-format", "refs/heads/feature/topic")
                return "Done"

            with patch.object(deletion, "delete_branch", side_effect=branch) as handler, \
                    patch("libs.github.subprocess.run",
                                 side_effect=[None, SimpleNamespace(returncode=status)]) as run:
                args = (ctx.api, REPO, REF, "7", SHA, "remote")
                if status:
                    with self.assertRaisesRegex(ValueError, "Git check-ref-format failed"):
                        deletion.delete_branch_with_git(*args)
                else:
                    self.assertEqual(deletion.delete_branch_with_git(*args), "Done")
                directory = str(observed[0])
                self.assertEqual(run.call_args_list, [
                    call(["git", "init", "-q", directory], check=True),
                    call(["git", "-C", directory, "-c", "credential.helper=",
                          "-c", "credential.helper=!gh auth git-credential",
                          "check-ref-format", "refs/heads/feature/topic"],
                         env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
                         capture_output=True, text=True, timeout=60)])
                handler.assert_called_once()
                self.assertEqual(handler.call_args.args[0], ctx.api)
                self.assertEqual(handler.call_args.args[2:], args[1:])
            self.assertFalse(observed[0].exists())
            ctx.api.assert_not_called()

        self.run_cases(cases, check)

    def test_batch_domain_partial_failure_preserves_completed_reports(self):
        cases = (("metadata_changed", "metadata"), ("delete_failure", "delete"),
                 ("report_failure", "report"))

        def check(ctx, failure):
            first, second, third = (dict(ctx.run_data, id=i) for i in (12, 14, 15))
            fresh_second = dict(second, extra="changed") if failure == "metadata" else second
            ctx.api.side_effect = [ctx.repo, first, second, third, first, fresh_second]
            trace = Mock()
            report = Mock()
            trace.attach_mock(ctx.api, "api")
            trace.attach_mock(ctx.remove, "remove")
            trace.attach_mock(report, "report")
            if failure == "delete":
                ctx.remove.side_effect = [None, ValueError("delete failed")]
            if failure == "report":
                report.side_effect = ValueError("report failed")
            targets = [ctx.target(i) for i in (12, 14, 15)]
            with self.assertRaises(ValueError):
                actions.delete_actions_batch(targets=targets, report=report, **ctx.batch_parameters)
            root = "repos/example/work"
            endpoint = root + "/actions/runs/"
            expected = [call.api("GET", root),
                        call.api("GET", endpoint + "12"), call.api("GET", endpoint + "14"),
                        call.api("GET", endpoint + "15"), call.api("GET", endpoint + "12"),
                        call.remove(endpoint + "12"), call.report("Deleted Actions run: 12")]
            if failure != "report":
                expected.append(call.api("GET", endpoint + "14"))
            if failure == "delete":
                expected.append(call.remove(endpoint + "14"))
            self.assertEqual(trace.mock_calls, expected)

        self.run_cases(cases, check)

    def test_actions_retention_rejects_inconsistent_listing(self):
        cases = (("wrong_count", "count"), ("wrong_order", "order"), ("duplicate", "duplicate"),
                 ("wrong_repository", "repository"), ("wrong_workflow", "workflow"),
                 ("wrong_path", "path"), ("not_success", "conclusion"), ("empty_success", "empty"))

        def check(ctx, defect):
            run = dict(ctx.run_data, path=".github/workflows/trigger.yml", workflow_id=7,
                       conclusion="success", created_at="2026-11-27T10:00:00Z")
            newer = dict(run, id=20, created_at="2026-11-27T11:00:00Z")
            listing = [newer, run]
            if defect == "order":
                listing.reverse()
            elif defect == "duplicate":
                listing = [newer, newer]
            elif defect == "repository":
                listing[0] = dict(newer, repository={"id": 2, "full_name": REPO})
            elif defect == "workflow":
                listing[0] = dict(newer, workflow_id=8)
            elif defect == "path":
                listing[0] = dict(newer, path=".github/workflows/other.yml")
            elif defect == "conclusion":
                listing[0] = dict(newer, conclusion="failure")
            elif defect == "empty":
                listing = []
            total = 1 if defect == "count" else len(listing)
            ctx.api.side_effect = [ctx.repo, run, {"total_count": total, "workflow_runs": listing}]
            self.assert_rejected(actions.delete_actions_run, **ctx.parameters)
            self.assertEqual(ctx.api.call_args_list, [
                call("GET", "repos/example/work"),
                call("GET", "repos/example/work/actions/runs/12"),
                call("GET", "repos/example/work/actions/workflows/7/runs?status=success&per_page=100")])
            ctx.remove.assert_not_called()

        self.run_cases(cases, check)
