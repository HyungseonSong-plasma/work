# FileRank: C
"""Offline routing contract tests."""

from unittest.mock import Mock, patch

from github import trigger
from github.model import WorkflowRegistry
from tests.framework.model import TestSuite, WorkflowTestContext, REPO, REF
from tests.framework.registry import register


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
        cases = (
            ("empty_chain", (), "single.yml"),
            ("string_chain", "first.py", "single.yml"),
            ("duplicate_execution", ("first.py", "first.py"), "serial.yml"),
            ("path_workflow", ("first.py",), "../other.yml"),
            ("wrong_extension", ("first.py",), "other.py"),
        )

        def check(ctx, chain, workflow):
            registry = WorkflowRegistry()
            self.assert_rejected(registry.register, chain, workflow)

        self.run_cases(cases, check)

    def test_shared_validation_rejects_invalid_types(self):
        from github.model import validate_sha, validate_pr_number, require_default_ref
        cases = (
            ("pr_boolean", validate_pr_number, (True,)),
            ("pr_none", validate_pr_number, (None,)),
            ("pr_zero_integer", validate_pr_number, (0,)),
            ("pr_empty", validate_pr_number, ("",)),
            ("pr_zero_string", validate_pr_number, ("0",)),
            ("pr_leading_zero", validate_pr_number, ("01",)),
            ("pr_negative", validate_pr_number, ("-1",)),
            ("sha_none", validate_sha, (None,)),
            ("sha_integer", validate_sha, (1,)),
            ("sha_uppercase", validate_sha, ("A" * 40,)),
            ("sha_short", validate_sha, ("a" * 39,)),
            ("ref_empty", require_default_ref, (REF, "")),
            ("ref_other", require_default_ref, (REF, "other")),
        )

        def check(ctx, validator, args):
            self.assert_rejected(validator, *args)

        self.run_cases(cases, check)

    def test_trigger_parses_owner_comment_once(self):
        with patch.object(trigger, "owner_comment", wraps=trigger.owner_comment) as parse:
            trigger.dispatch_request(self.ctx.event("pr_merge.py"), REPO, REF, Mock())
            parse.assert_called_once()
