# FileRank: C
"""CLI adapters: environment, task registration and result reporting."""

import json
import os
from pathlib import Path

from github.model import github_api
from scripts import branch_delete, pr_merge
from scripts.execute import EXECUTIONS, resolve_execution, run_execution, run_stage
from scripts.trigger import dispatch_request


def _summary(message):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(message)


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


def execute(single, stage):
    if os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch") != "workflow_dispatch":
        raise ValueError("Execution requires a workflow dispatch.")
    scripts = resolve_execution(
        os.environ["EXECUTION"], os.environ["EXECUTION_INPUTS"],
    )
    if single:
        if len(scripts) != 1:
            raise ValueError("Single execution requires exactly one script.")
        return run_execution(scripts)
    return run_stage(scripts, stage)


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
