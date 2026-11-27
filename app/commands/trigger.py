# FileRank: C
"""Trigger command and its workflow adapter."""

import json
import os

from app.registry import register
from app.commands._summary import _summary
from scripts.trigger import dispatch_request


def trigger():
    if (os.environ["GITHUB_EVENT_NAME"] != "issue_comment" or
            os.environ["GITHUB_RUN_ATTEMPT"] != "1"):
        raise ValueError("Only a new comment event can dispatch a workflow.")
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
        event = json.load(stream)
    workflow, request_id = dispatch_request(
        event, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"],
    )
    print(f"Submitted {workflow}: {request_id}")
    _summary(f"Submitted `{workflow}` for `{request_id}`.\n\n"
             "Execution result is reported by the dispatched run.\n")
    return 0


@register("trigger")
class TriggerCommand:
    help = "Validate a PR comment and route it"

    @staticmethod
    def configure(parser):
        pass

    @staticmethod
    def execute(args):
        return trigger()
