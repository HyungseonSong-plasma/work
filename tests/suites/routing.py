# FileRank: C
"""Offline routing contract tests."""

import unittest
from unittest.mock import Mock, patch

from github import trigger
from github.model import WorkflowRegistry
from tests.support import REPO, REF, event
from tests.registry import register


@register("routing")
class RoutingContract(unittest.TestCase):
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
