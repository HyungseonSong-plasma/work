# FileRank: C
"""Offline routing contract tests."""

from unittest.mock import Mock, MagicMock, patch

from github import trigger
from app.commands.trigger import route_registry
from app.wiring import resolve_execution
from libs.github import WorkflowRegistry
from libs.testing import TestSuite
from tests.fixtures import WorkflowTestContext, REPO, REF
from tests.wiring import register


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
            self.assertEqual(trigger.dispatch_request(ctx.event(expression), REPO, REF, dispatch,
                                                      routes=route_registry, resolve=resolve_execution),
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
            registry = route_registry if registered else WorkflowRegistry()
            self.assert_rejected(trigger.dispatch_request, request, repository, ref, dispatch,
                                 routes=registry, resolve=resolve_execution)
            dispatch.assert_not_called()

        self.run_cases(cases, check)

    def test_workflow_registry_extends_without_routing_branch(self):
        def register_route(ctx):
            ctx.registry = WorkflowRegistry()
            ctx.registry.register(("first.py", "second.py", "third.py"), "new_run.yml")

        def check(ctx):
            self.assertEqual(ctx.registry.resolve(iter(("first.py", "second.py", "third.py"))),
                             "new_run.yml")

        steps = (("register", register_route),)
        self.run_scenario(steps, check)

    def test_workflow_registry_preserves_order(self):
        def register_route(ctx):
            ctx.registry = WorkflowRegistry()
            ctx.registry.register(("first.py", "second.py"), "serial.yml")

        def check(ctx):
            self.assert_rejected(ctx.registry.resolve, ("second.py", "first.py"))

        steps = (("register", register_route),)
        self.run_scenario(steps, check)

    def test_workflow_registry_rejects_duplicate(self):
        def register(ctx):
            ctx.registry = WorkflowRegistry()
            ctx.registry.register(("first.py",), "single.yml")

        def reject_duplicate(ctx):
            self.assert_rejected(ctx.registry.register, ("first.py",), "other.yml")

        def check(ctx):
            self.assertEqual(ctx.registry.resolve(("first.py",)), "single.yml")

        steps = (
            ("register", register),
            ("reject_duplicate", reject_duplicate),
        )
        self.run_scenario(steps, check)

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
        from libs.github import validate_sha, validate_pr_number, require_default_ref
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
        def check(ctx):
            with patch.object(trigger, "owner_comment", wraps=trigger.owner_comment) as parse:
                trigger.dispatch_request(ctx.event("pr_merge.py"), REPO, REF, Mock(),
                                         routes=route_registry, resolve=resolve_execution)
                parse.assert_called_once()

        self.run_contract(check=check)

    def test_rest_transport_exact_request_and_response(self):
        cases = (("json_get", "GET", None), ("json_put", "PUT", {"sha": "a" * 40}))

        def check(ctx, method, payload):
            from libs.github import GitHubClient
            from io import BytesIO
            import os
            response = MagicMock()
            response.__enter__.return_value = BytesIO(b'{"confirmed": true}')
            send = Mock(return_value=response)
            with patch.dict(os.environ, {"GITHUB_API_URL": "https://api.example.test/",
                                         "GH_TOKEN": "offline-fixture"}, clear=True):
                result = GitHubClient(send).request(method, "repos/example/work", payload)
            self.assertEqual(result, {"confirmed": True})
            send.assert_called_once()
            request = send.call_args.args[0]
            self.assertEqual(send.call_args.kwargs, {"timeout": 30})
            self.assertEqual(request.full_url, "https://api.example.test/repos/example/work")
            self.assertEqual(request.get_method(), method)
            self.assertEqual(request.data, None if payload is None else b'{"sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}')
            self.assertEqual(dict(request.header_items()), {
                "Authorization": "Bearer offline-fixture",
                "Accept": "application/vnd.github+json",
                "Content-type": "application/json",
                "X-github-api-version": "2022-11-28"})
            response.__exit__.assert_called_once_with(None, None, None)

        self.run_cases(cases, check)

    def test_rest_mutations_require_explicit_status_and_exact_request(self):
        cases = (
            ("dispatch_200", "POST", 200, True), ("dispatch_204", "POST", 204, True),
            ("dispatch_202", "POST", 202, False), ("dispatch_201", "POST", 201, False),
            ("delete_204", "DELETE", 204, True), ("delete_200", "DELETE", 200, False),
            ("delete_202", "DELETE", 202, False),
        )

        def check(ctx, method, status, allowed):
            from libs.github import GitHubClient
            import os
            response = MagicMock()
            response.__enter__.return_value.status = status
            send = Mock(return_value=response)
            if method == "POST":
                operation = lambda: GitHubClient(send).dispatch(REPO, "single_run.yml",
                    {"ref": "main", "inputs": {"request_id": "comment-12"}})
                endpoint = "/repos/example/work/actions/workflows/single_run.yml/dispatches"
                data = b'{"ref": "main", "inputs": {"request_id": "comment-12"}}'
            else:
                operation = lambda: GitHubClient(send).delete("repos/example/work/actions/runs/12")
                endpoint = "/repos/example/work/actions/runs/12"
                data = None
            with patch.dict(os.environ, {"GITHUB_API_URL": "https://api.example.test",
                                         "GH_TOKEN": "offline-fixture"}, clear=True):
                if allowed:
                    self.assertIsNone(operation())
                else:
                    self.assert_rejected(operation)
            send.assert_called_once()
            request = send.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.example.test" + endpoint)
            self.assertEqual(request.get_method(), method)
            self.assertEqual(request.data, data)
            self.assertEqual(send.call_args.kwargs, {"timeout": 30})
            response.__exit__.assert_called_once()

        self.run_cases(cases, check)

    def test_rest_transport_does_not_retry_ambiguous_failure(self):
        cases = (("dispatch_timeout", "dispatch"), ("delete_timeout", "delete"),
                 ("json_timeout", "json"))

        def check(ctx, operation):
            from libs.github import GitHubClient
            import os
            send = Mock(side_effect=TimeoutError("ambiguous response"))
            with patch.dict(os.environ, {"GITHUB_API_URL": "https://api.example.test",
                                         "GH_TOKEN": "offline-fixture"}, clear=True):
                with self.assertRaisesRegex(TimeoutError, "ambiguous response"):
                    if operation == "dispatch":
                        GitHubClient(send).dispatch(REPO, "single_run.yml", {"ref": "main"})
                    elif operation == "delete":
                        GitHubClient(send).delete("repos/example/work/actions/runs/12")
                    else:
                        GitHubClient(send).request("PUT", "repos/example/work/pulls/7/merge", {"sha": "a" * 40})
            send.assert_called_once()
            self.assertEqual(send.call_args.kwargs, {"timeout": 30})

        self.run_cases(cases, check)

    def test_rest_json_transport_rejects_invalid_response_and_closes(self):
        def check(ctx):
            from libs.github import GitHubClient
            from io import BytesIO
            import json
            import os
            response = MagicMock()
            response.__enter__.return_value = BytesIO(b"not JSON")
            send = Mock(return_value=response)
            with patch.dict(os.environ, {"GITHUB_API_URL": "https://api.example.test",
                                         "GH_TOKEN": "offline-fixture"}, clear=True):
                with self.assertRaises(json.JSONDecodeError):
                    GitHubClient(send).request("GET", "repos/example/work")
            send.assert_called_once()
            response.__exit__.assert_called_once()
            self.assertIs(response.__exit__.call_args.args[0], json.JSONDecodeError)

        self.run_contract(check=check)

    def test_domain_imports_without_application_layer(self):
        def check(ctx):
            from tests.fixtures import import_probe
            result = import_probe(("libs.github", "github.trigger", "github.actions", "github.delete", "github.merge"),
                                  ("app",))
            self.assertEqual(result.returncode, 0, result.stderr)

        self.run_contract(check=check)

    def test_injected_route_resolver_cannot_dispatch_on_rejection(self):
        def check(ctx):
            resolver = Mock(side_effect=ValueError("rejected execution"))
            routes = Mock()
            dispatch = Mock()
            event = ctx.event("pr_merge.py")
            with self.assertRaisesRegex(ValueError, "rejected execution"):
                trigger.dispatch_request(event, REPO, REF, dispatch,
                                         routes=routes, resolve=resolver)
            resolver.assert_called_once_with("pr_merge.py",
                '{"pr_number": 7, "expected_head_sha": "' + "a" * 40 + '"}')
            routes.resolve.assert_not_called()
            dispatch.assert_not_called()

        self.run_contract(check=check)

    def test_github_library_import_is_domain_independent(self):
        def check(ctx):
            from tests.fixtures import import_probe
            result = import_probe(("libs.github",),
                                  ("app", "tests", "github", "config"))
            self.assertEqual(result.returncode, 0, result.stderr)

        self.run_contract(check=check)
