# FileRank: C
"""Trigger command and its workflow adapter."""

from functools import partial

from config import load_registry
from app.wiring import register, execution_ids, resolve_execution
from libs.command import Command
from app.framework.model import workflow_plan
from github import trigger
from libs.github import WorkflowRegistry


# Trusted composition root: preserve eager route validation on CLI module loading.
route_registry = WorkflowRegistry.from_entries(load_registry("workflows"), execution_ids())
dispatch_request = partial(trigger.dispatch_request, routes=route_registry,
                           resolve=resolve_execution)


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
    workflow_execution = ()
    plan = workflow_plan("issue_comment", action, report=report)
