# FileRank: C
"""Merge an explicitly reviewed PR through the shared command model."""

from app.commands.model import Command, PRContext
from app.registry import register
from github.model import github_api
from github import merge


def execute():
    ctx = PRContext("pr_merge.py").validate()
    result = merge.merge_pr(github_api, ctx.repository, ctx.ref, ctx.number, ctx.sha)
    ctx.report(f"Merged PR #{ctx.number}: {result}",
               f"Merged PR #{ctx.number}\n\nMerge commit: `{result}`")
    return 0


@register("merge")
class MergeCommand(Command):
    help = "Merge one reviewed pull request"
    workflow_execution = ("pr_merge.py",)

    @staticmethod
    def execute(args):
        return execute()
