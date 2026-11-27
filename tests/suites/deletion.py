# FileRank: C
"""Offline deletion policy and target dispatch tests."""

from copy import deepcopy
import json
from unittest.mock import Mock, patch

from app.commands.delete import validate_actions_context
from github import delete as deletion
from github.model import delete_resource
from tests.registry import register
from tests.suites.model import TestSuite, REPO, REF, SHA, event
from github import trigger


@register("deletion")
class DeletionContract(TestSuite):
    def setUp(self):
        self.repo = {"id": 1, "default_branch": "main"}
        self.run_data = {"id": 12, "repository": {"id": 1, "full_name": REPO},
                    "head_sha": SHA, "run_attempt": 1, "status": "completed",
                    "path": ".github/workflows/disposable.yml"}
        self.api = Mock(side_effect=lambda method, endpoint:
                        self.repo if endpoint == f"repos/{REPO}" else deepcopy(self.run_data))
        self.remove = Mock()
        self.parameters = dict(api=self.api, remove=self.remove, repository=REPO,
                               run_ref=REF, run_id=12, expected_head_sha=SHA,
                               expected_run_attempt=1, current_run_id=13)

    def test_actions_delete_exact_run(self):
        self.assertEqual(deletion.delete("actions", **self.parameters),
                         "Deleted Actions run: 12")
        self.remove.assert_called_once_with(f"repos/{REPO}/actions/runs/12")

    def test_branch_target_dispatch(self):
        handler = Mock(return_value="Deleted branch")
        with patch.dict(deletion.DELETIONS, {"branch": handler}):
            self.assertEqual(deletion.delete("branch", number="7"), "Deleted branch")
        handler.assert_called_once_with(number="7")

    def test_disabled_and_unknown_targets(self):
        for target in ("issue", "unknown"):
            with self.subTest(target=target):
                self.assert_rejected(deletion.delete, target)
        with patch("config.load_registry", return_value={
                "actions": {"enabled": False, "permission": "actions: write"}}):
            self.assert_rejected(deletion.delete, "actions", **self.parameters)
        self.api.assert_not_called()
        self.remove.assert_not_called()

    def test_actions_reject_invalid_or_current_id(self):
        for run_id in (True, 0, -1, 13, "12"):
            with self.subTest(run_id=run_id):
                self.assert_rejected(deletion.delete, "actions",
                                     **dict(self.parameters, run_id=run_id))
        self.api.assert_not_called()
        self.remove.assert_not_called()

    def test_actions_reject_unreviewed_metadata(self):
        for changes in ({"status": "in_progress"}, {"head_sha": "b" * 40},
                        {"run_attempt": 2}, {"id": 99},
                        {"repository": {"id": 2, "full_name": REPO}}):
            with self.subTest(changes=changes):
                original = deepcopy(self.run_data)
                self.run_data.update(changes)
                self.assert_rejected(deletion.delete, "actions", **self.parameters)
                self.run_data = original
        self.remove.assert_not_called()

    def test_actions_reject_protected_workflows(self):
        for path in deletion.PROTECTED_WORKFLOWS:
            with self.subTest(path=path):
                self.run_data["path"] = path
                self.assert_rejected(deletion.delete, "actions", **self.parameters)
        self.remove.assert_not_called()

    def test_actions_reject_changed_run_before_delete(self):
        self.api.side_effect = [self.repo, self.run_data,
                                dict(self.run_data, run_attempt=2)]
        self.assert_rejected(deletion.delete, "actions", **self.parameters)
        self.remove.assert_not_called()

    def test_actions_reject_non_default_ref(self):
        self.assert_rejected(deletion.delete, "actions",
                             **dict(self.parameters, run_ref="refs/heads/other"))
        self.remove.assert_not_called()

    def test_actions_context_requires_owner_and_workflow(self):
        event = {"repository": {"full_name": REPO, "default_branch": "main",
                                "owner": {"id": 1}}, "sender": {"id": 1}}
        workflow_ref = f"{REPO}/.github/workflows/actions_delete.yml@{REF}"
        validate_actions_context(event, REPO, REF, "1", workflow_ref)
        self.assert_rejected(validate_actions_context, event, REPO, REF, "2", workflow_ref)
        self.assert_rejected(validate_actions_context, event, REPO, REF, "1", "other")
        self.assert_rejected(validate_actions_context, dict(event, sender={"id": 2}),
                             REPO, REF, "1", workflow_ref)

    def test_rest_delete_requires_204(self):
        from unittest.mock import MagicMock
        response = MagicMock()
        send = MagicMock()
        send.return_value.__enter__.return_value = response
        with patch("github.model._request") as request:
            response.status = 204
            delete_resource("repos/example/work/actions/runs/12", send=send)
            request.assert_called_once_with("DELETE", "repos/example/work/actions/runs/12")
            response.status = 200
            self.assert_rejected(delete_resource, "repos/example/work/actions/runs/12", send=send)


    def test_owner_comment_routes_actions_only(self):
        request = event("pr_merge.py")
        request["comment"].update(created_at="now", updated_at="now")
        request["comment"]["body"] = "/execute " + json.dumps({
            "execution": "delete actions", "run_id": 12,
            "expected_head_sha": SHA, "expected_run_attempt": 1})
        dispatch = Mock()
        workflow, request_id = trigger.dispatch_request(request, REPO, REF, dispatch)
        self.assertEqual((workflow, request_id), ("actions_delete.yml", "comment-12"))
        dispatch.assert_called_once_with(REPO, workflow, {
            "ref": "main", "inputs": {"run_id": "12", "expected_head_sha": SHA,
                "expected_run_attempt": "1", "source_pr": "7", "request_id": "comment-12"}})

    def test_actions_comment_rejects_invalid_requests(self):
        for changes in ({"run_id": True}, {"queue_comment_id": 1},
                        {"expected_run_attempt": 0}, {"expected_head_sha": "bad"}):
            request = event("pr_merge.py")
            request["comment"].update(created_at="now", updated_at="now")
            body = {"execution": "delete actions", "run_id": 12,
                    "expected_head_sha": SHA, "expected_run_attempt": 1}
            request["comment"]["body"] = "/execute " + json.dumps(dict(body, **changes))
            dispatch = Mock()
            self.assert_rejected(trigger.dispatch_request, request, REPO, REF, dispatch)
            dispatch.assert_not_called()

    def test_actions_worker_revalidates_source_comment(self):
        context = {"repository": {"full_name": REPO, "default_branch": "main",
                                   "owner": {"id": 1}},
                   "sender": {"id": 41898282, "login": "github-actions[bot]"}}
        inputs = {"run_id": "12", "expected_head_sha": SHA, "expected_run_attempt": "1"}
        body = {"execution": "delete actions", "run_id": 12,
                "expected_head_sha": SHA, "expected_run_attempt": 1}
        comment = {"id": 12, "user": {"id": 1}, "author_association": "OWNER",
                   "created_at": "now", "updated_at": "now",
                   "issue_url": f"https://api.github.com/repos/{REPO}/issues/7",
                   "body": "/execute " + json.dumps(body)}
        pr = {"number": 7, "base": {"repo": {"full_name": REPO}}}
        workflow_ref = f"{REPO}/.github/workflows/actions_delete.yml@{REF}"
        def validate():
            validate_actions_context(context, REPO, REF, "41898282", workflow_ref,
                                     "comment-12", "7", inputs,
                                     api=Mock(side_effect=[comment, pr]))
        validate()
        for change in ({"updated_at": "later"}, {"user": {"id": 2}},
                       {"body": "/execute " + json.dumps(dict(body, run_id=99))}):
            with self.subTest(change=change):
                original = dict(comment)
                comment.update(change)
                self.assert_rejected(validate)
                comment.clear()
                comment.update(original)

    def test_actions_worker_rejects_bot_without_approval(self):
        context = {"repository": {"full_name": REPO, "default_branch": "main",
                                   "owner": {"id": 1}},
                   "sender": {"id": 41898282, "login": "github-actions[bot]"}}
        self.assert_rejected(validate_actions_context, context, REPO, REF, "41898282",
                             f"{REPO}/.github/workflows/actions_delete.yml@{REF}")
