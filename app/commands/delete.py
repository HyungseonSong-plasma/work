# FileRank: C
"""Branch and Actions deletion command with independent target validation."""

import json
import os

from app.commands.model import (Command, pr_context, read_event, report,
                                repository_context, require_event,
                                validate_actions_context)
from app.registry import register
from github.delete import delete
from github.model import github_api, delete_resource
from github.trigger import actions_request


def delete_branch(args):
    if (args.runs or args.request_id or args.source_pr or
            any(value is not None for value in
                (args.run_id, args.expected_head_sha, args.expected_run_attempt))):
        raise ValueError("Actions inputs are not valid for branch deletion.")
    number, sha, repository, ref = pr_context("branch_delete.py")
    remote = os.environ["GITHUB_SERVER_URL"].rstrip("/") + f"/{repository}.git"
    report(delete("branch", api=github_api, repository=repository,
                  run_ref=ref, number=number, sha=sha, remote=remote))
    return 0


def delete_actions(args):
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


def execute(args):
    if args.target == "branch":
        return delete_branch(args)
    if args.target == "actions":
        return delete_actions(args)
    raise ValueError("Unknown deletion target.")


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
        return execute(args)
