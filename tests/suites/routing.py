# FileRank: C
"""Offline routing contract tests."""

from unittest.mock import Mock, patch

from github import trigger
from github.model import WorkflowRegistry
from tests.suites.model import TestSuite, WorkflowTestContext, REPO, REF
from tests.registry import register


@register("routing")
class RoutingContract(TestSuite):
    context_type = WorkflowTestContext

    def test_routing_dispatches_only_one_workflow(self):
        cases = (
            ("merge", "pr_merge.py", "single_run.yml"),
            ("delete", "branch_delete.py", "single_run.yml"),
            ("serial", "pr_merge.py - branch_delete.py", "serial_run.yml"),
        )

        def check(ctx, expression, expected):
            dispatch = Mock()
            self.assertEqual(trigger.dispatch_request(ctx.event(expression), REPO, REF, dispatch),
                             (expected, "comment-12"))
            dispatch.assert_called_once()
            self.assertEqual(dispatch.call_args.args[1], expected)

        self.run_cases(cases, check)

    def test_invalid_routes_do_not_dispatch(self):
        cases = (
            ("unauthorized_sender", "pr_merge.py", REPO, REF, 2, True),
            ("unregistered_route", "pr_merge.py", REPO, REF, 1, False),
            ("reverse_chain", "branch_delete.py - pr_merge.py", REPO, REF, 1, True),
            ("wrong_repository", "pr_merge.py", "other/work", REF, 1, True),
            ("wrong_ref", "pr_merge.py", REPO, "refs/heads/other", 1, True),
        )

        def check(ctx, expression, repository, ref, sender_id, registered):
            request = ctx.event(expression)
            request["sender"]["id"] = sender_id
            dispatch = Mock()
            registry = trigger.registry if registered else WorkflowRegistry()
            with patch.object(trigger, "registry", registry):
                self.assert_rejected(trigger.dispatch_request, request, repository, ref, dispatch)
            dispatch.assert_not_called()

        self.run_cases(cases, check)

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




    def test_shared_validation_rejects_invalid_types(self):
        from github.model import validate_sha, validate_pr_number, require_default_ref
        for value in (True, None, 0, "", "0", "01", "-1"):
            self.assert_rejected(validate_pr_number, value)
        for value in (None, 1, "A" * 40, "a" * 39):
            self.assert_rejected(validate_sha, value)
        self.assert_rejected(require_default_ref, REF, "")
        self.assert_rejected(require_default_ref, REF, "other")

    def test_trigger_parses_owner_comment_once(self):
        with patch.object(trigger, "owner_comment", wraps=trigger.owner_comment) as parse:
            trigger.dispatch_request(self.ctx.event("pr_merge.py"), REPO, REF, Mock())
            parse.assert_called_once()
