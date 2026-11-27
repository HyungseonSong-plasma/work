# FileRank: C
"""Branch and Actions deletion command with independent target validation."""

from app.framework.model import Command, pr_plan, actions_plan
from app.framework.registry import register
from github.delete import delete
from github.model import github_api, delete_resource


def check_branch_inputs(args):
    if (args.runs or args.request_id or args.source_pr or
            any(value is not None for value in
                (args.run_id, args.expected_head_sha, args.expected_run_attempt))):
        raise ValueError("Actions inputs are not valid for branch deletion.")


def branch_action(ctx, args):
    return delete("branch", api=github_api, repository=ctx.repository,
                  run_ref=ctx.ref, number=ctx.number, sha=ctx.sha, remote=ctx.remote)


def branch_report(ctx, result):
    ctx.report(result)


def actions_action(ctx, args):
    delete("actions_batch", api=github_api, remove=delete_resource,
           repository=ctx.repository, run_ref=ctx.ref, current_run_id=ctx.run_id,
           targets=ctx.targets, report=ctx.report)

@register("delete")
class DeleteCommand(Command):
    help = "Delete a reviewed PR branch or explicitly approved Actions runs"
    workflow_execution = ("branch_delete.py", "branch")
    targets = (
        ("branch", pr_plan("branch_delete.py", branch_action,
                           preflight=check_branch_inputs, report=branch_report)),
        ("actions", actions_plan(actions_action)),
    )

    @staticmethod
    def configure(parser):
        parser.add_argument("target", choices=("branch", "actions"))
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--runs", default="")
        parser.add_argument("--expected-head-sha")
        parser.add_argument("--expected-run-attempt", type=int)
        parser.add_argument("--request-id", default="")
        parser.add_argument("--source-pr", default="")
