# FileRank: C
"""Separately scoped Actions deletion with explicit owner approval."""

import json
import os
import re

from app.commands.model import (Command, pr_context, read_event, report,
                                repository_context, require_event)
from app.registry import register
from github.delete import delete
from github.model import github_api, delete_resource
from github.trigger import actions_request


def validate_actions_context(event, repository, ref, actor_id, workflow_ref,
                             request_id="", source_pr="", inputs=None, api=github_api):
    repo = event["repository"]
    owner = str(repo["owner"]["id"])
    if not (
        repo["full_name"] == repository
        and ref == f"refs/heads/{repo['default_branch']}"
        and workflow_ref == f"{repository}/.github/workflows/actions_delete.yml@{ref}"
    ):
        raise ValueError("Unauthorized Actions deletion workflow.")
    sender = event["sender"]
    if str(sender["id"]) != actor_id:
        raise ValueError("Workflow actor mismatch.")
    if not request_id and not source_pr:
        if actor_id != owner:
            raise ValueError("Manual deletion requires the owner.")
        return
    if not re.fullmatch(r"comment-[1-9][0-9]*", request_id) or not re.fullmatch(
            r"[1-9][0-9]*", source_pr):
        raise ValueError("Invalid source comment or PR.")
    if actor_id != owner and not (
        actor_id == "41898282" and sender["login"] == "github-actions[bot]"
    ):
        raise ValueError("Unauthorized dispatch actor.")
    root = f"repos/{repository}"
    comment_id = int(request_id.split("-", 1)[1])
    comment = api("GET", f"{root}/issues/comments/{comment_id}")
    pr = api("GET", f"{root}/pulls/{source_pr}")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not (
        comment["id"] == comment_id
        and comment["user"]["id"] == repo["owner"]["id"]
        and comment["author_association"] == "OWNER"
        and comment["created_at"] == comment["updated_at"]
        and comment["issue_url"] == f"{api_url}/{root}/issues/{source_pr}"
        and pr["number"] == int(source_pr)
        and pr["base"]["repo"]["full_name"] == repository
        and comment["body"].startswith("/execute ")
    ):
        raise ValueError("Source comment is not an unchanged owner PR request.")
    request = json.loads(comment["body"][len("/execute "):])
    if actions_request(request) != inputs:
        raise ValueError("Source approval does not match dispatch inputs.")


@register("delete")
class DeleteCommand(Command):
    help = "Delete a reviewed PR branch or explicitly approved Actions runs"
    workflow_execution = ("branch_delete.py", "branch")

    @staticmethod
    def configure(parser):
        parser.add_argument("target", choices=("branch", "actions"))
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--runs", default="")
        parser.add_argument("--expected-head-sha")
        parser.add_argument("--expected-run-attempt", type=int)
        parser.add_argument("--request-id", default="")
        parser.add_argument("--source-pr", default="")

    @staticmethod
    def execute(args):
        if args.target == "branch":
            if (args.runs or args.request_id or args.source_pr or
                    any(value is not None for value in
                        (args.run_id, args.expected_head_sha, args.expected_run_attempt))):
                raise ValueError("Actions inputs are not valid for branch deletion.")
            number, sha, repository, ref = pr_context("branch_delete.py")
            remote = os.environ["GITHUB_SERVER_URL"].rstrip("/") + f"/{repository}.git"
            report(delete("branch", api=github_api, repository=repository,
                          run_ref=ref, number=number, sha=sha, remote=remote))
            return 0

        require_event("workflow_dispatch", fresh=True)
        event = read_event()
        repository, ref = repository_context()
        if args.runs:
            if any(value is not None for value in
                   (args.run_id, args.expected_head_sha, args.expected_run_attempt)):
                raise ValueError("Choose single or batch, not both.")
            request = {"execution": "delete actions", "runs": json.loads(args.runs)}
        else:
            request = {"execution": "delete actions", "run_id": args.run_id,
                       "expected_head_sha": args.expected_head_sha,
                       "expected_run_attempt": args.expected_run_attempt}
        inputs = actions_request(request)
        validate_actions_context(
            event, repository, ref, os.environ["GITHUB_ACTOR_ID"],
            os.environ["GITHUB_WORKFLOW_REF"], args.request_id, args.source_pr, inputs)

        common = dict(api=github_api, remove=delete_resource, repository=repository,
                      run_ref=ref, current_run_id=int(os.environ["GITHUB_RUN_ID"]))
        if args.runs:
            delete("actions_batch", targets=request["runs"], report=report, **common)
        else:
            result = delete("actions", run_id=args.run_id,
                            expected_head_sha=args.expected_head_sha,
                            expected_run_attempt=args.expected_run_attempt, **common)
            report(result)
        return 0
