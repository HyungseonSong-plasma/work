# FileRank: C
"""Trigger command and its workflow adapter."""

from app.registry import register
from app.commands.model import Command, read_event, report, repository_context, require_event
from github.trigger import dispatch_request


def trigger():
    require_event("issue_comment", fresh=True)
    workflow, request_id = dispatch_request(read_event(), *repository_context())
    report(f"Submitted {workflow}: {request_id}",
           f"Submitted `{workflow}` for `{request_id}`.\n\n"
           "Execution result is reported by the dispatched run.\n")
    return 0


@register("trigger")
class TriggerCommand(Command):
    help = "Validate a PR comment and route it"

    @staticmethod
    def execute(args):
        return trigger()
