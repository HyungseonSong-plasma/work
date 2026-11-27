# FileRank: C
"""Merge an explicitly reviewed PR through the shared command model."""

from app.framework.model import Command, pr_plan
from app.framework.registry import register
from github.framework.transport import github_api
from github import merge


def action(ctx, args):
    return merge.merge_pr(github_api, ctx.repository, ctx.ref, ctx.number, ctx.sha)


def report(ctx, result):
    ctx.report(f"Merged PR #{ctx.number}: {result}",
               f"Merged PR #{ctx.number}\n\nMerge commit: `{result}`")


@register("merge")
class MergeCommand(Command):
    help = "Merge one reviewed pull request"
    workflow_execution = ("pr_merge.py",)
    plan = pr_plan("pr_merge.py", action, report=report)
