# FileRank: C
"""Merge an explicitly reviewed PR through the shared command model."""

from app.commands.model import Command, pr_context, report
from app.registry import register
from github.model import github_api
from scripts import pr_merge


@register("merge")
class MergeCommand(Command):
    help = "Merge one reviewed pull request"
    workflow_execution = ("pr_merge.py",)

    @staticmethod
    def execute(args):
        number, sha, repository, ref = pr_context("pr_merge.py")
        result = pr_merge.merge_pr(github_api, repository, ref, number, sha)
        report(f"Merged PR #{number}: {result}",
               f"Merged PR #{number}\n\nMerge commit: `{result}`")
        return 0
