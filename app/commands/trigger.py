# FileRank: C
"""Trigger command and its workflow adapter."""

from app.framework.registry import register
from app.framework.model import Command, workflow_plan
from github.trigger import dispatch_request


def action(ctx, args):
    return dispatch_request(ctx.read_event(), ctx.repository, ctx.ref)


def report(ctx, result):
    workflow, request_id = result
    ctx.report(f"Submitted {workflow}: {request_id}",
               f"Submitted `{workflow}` for `{request_id}`.\n\n"
               "Execution result is reported by the dispatched run.\n")


@register("trigger")
class TriggerCommand(Command):
    help = "Validate a PR comment and route it"
    plan = workflow_plan("issue_comment", action, report=report)
