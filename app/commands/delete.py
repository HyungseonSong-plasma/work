# FileRank: C
"""Branch and Actions deletion command with independent target validation."""

from app.framework.model import Command, PRContext, ActionsContext
from app.framework.registry import register
from github.delete import delete
from github.model import github_api, delete_resource


def delete_branch(args):
    if (args.runs or args.request_id or args.source_pr or
            any(value is not None for value in
                (args.run_id, args.expected_head_sha, args.expected_run_attempt))):
        raise ValueError("Actions inputs are not valid for branch deletion.")
    ctx = PRContext("branch_delete.py").validate()
    ctx.report(delete("branch", api=github_api, repository=ctx.repository,
                      run_ref=ctx.ref, number=ctx.number, sha=ctx.sha, remote=ctx.remote))
    return 0


def delete_actions(args):
    ctx = ActionsContext(args).validate()
    delete("actions_batch", api=github_api, remove=delete_resource,
           repository=ctx.repository, run_ref=ctx.ref, current_run_id=ctx.run_id,
           targets=ctx.targets, report=ctx.report)
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
