# FileRank: C
"""Registered task command and execution adapters."""

import os

from app.registry import register
from app.commands._summary import _summary
from github.model import github_api
from scripts import branch_delete, pr_merge
from scripts.execute import EXECUTIONS, resolve_execution


def _merge(number, sha, repository, ref):
    result = pr_merge.merge_pr(github_api, repository, ref, number, sha)
    print(f"Merged PR #{number}: {result}")
    _summary(f"Merged PR #{number}\n\nMerge commit: `{result}`\n")
    return 0


def _delete(number, sha, repository, ref):
    remote = os.environ["GITHUB_SERVER_URL"].rstrip("/") + f"/{repository}.git"
    result = branch_delete.delete_with_git(
        github_api, repository, ref, number, sha, remote,
    )
    print(result)
    return 0


TASKS = {"pr_merge.py": _merge, "branch_delete.py": _delete}


def task(script):
    if set(TASKS) != EXECUTIONS or script not in TASKS:
        raise ValueError("Unregistered task or inconsistent task registry.")
    # Validate the file and parameters before running the explicitly selected task.
    resolve_execution(script, os.environ["EXECUTION_INPUTS"])
    number, sha = branch_delete.parse_parameters(os.environ["EXECUTION_INPUTS"])
    return TASKS[script](
        number, sha, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"],
    )


@register("task")
class TaskCommand:
    help = "Run one registered task"

    @staticmethod
    def configure(parser):
        parser.add_argument("script", choices=sorted(EXECUTIONS))

    @staticmethod
    def execute(args):
        return task(args.script)
