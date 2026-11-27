# FileRank: C
"""Owner-only, separately scoped Actions deletion command."""

import json
import os

from app.commands.model import Command, summary
from app.registry import register
from github.delete import delete
from github.model import github_api, delete_resource


def validate_actions_context(event, repository, ref, actor_id, workflow_ref):
    repo = event["repository"]
    owner = str(repo["owner"]["id"])
    if not (
        repo["full_name"] == repository
        and ref == f"refs/heads/{repo['default_branch']}"
        and actor_id == owner
        and str(event["sender"]["id"]) == owner
        and workflow_ref == f"{repository}/.github/workflows/actions_delete.yml@{ref}"
    ):
        raise ValueError("Unauthorized Actions deletion workflow.")


@register("delete")
class DeleteCommand(Command):
    help = "Delete an explicitly approved GitHub Actions run"

    @staticmethod
    def configure(parser):
        parser.add_argument("target", choices=("actions",))
        parser.add_argument("--run-id", type=int, required=True)
        parser.add_argument("--expected-head-sha", required=True)
        parser.add_argument("--expected-run-attempt", type=int, required=True)

    @staticmethod
    def execute(args):
        if (os.environ["GITHUB_EVENT_NAME"] != "workflow_dispatch" or
                os.environ["GITHUB_RUN_ATTEMPT"] != "1"):
            raise ValueError("Requires a fresh manual workflow dispatch.")
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
            event = json.load(stream)
        repository, ref = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"]
        validate_actions_context(
            event, repository, ref, os.environ["GITHUB_ACTOR_ID"],
            os.environ["GITHUB_WORKFLOW_REF"])
        result = delete(
            args.target, api=github_api, remove=delete_resource,
            repository=repository, run_ref=ref, run_id=args.run_id,
            expected_head_sha=args.expected_head_sha,
            expected_run_attempt=args.expected_run_attempt,
            current_run_id=int(os.environ["GITHUB_RUN_ID"]))
        print(result)
        summary(result + "\n")
        return 0
