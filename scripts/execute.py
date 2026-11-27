# FileRank: C
"""Execute registered scripts serially from the trusted checkout."""

import json
import re
import subprocess
import sys
from pathlib import Path

# Adding a script here grants it the workflow's permissions.
EXECUTIONS = frozenset({"pr_merge.py", "branch_delete.py"})


def resolve_execution(expression, parameters):
    if not isinstance(json.loads(parameters), dict):
        raise ValueError("Parameters must be a JSON object.")

    names = [name.strip() for name in expression.split(" - ")]
    if any(name not in EXECUTIONS for name in names):
        raise ValueError("Every execution must be a registered script.")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate execution is not allowed.")
    if {"pr_merge.py", "branch_delete.py"}.issubset(names):
        if names.index("pr_merge.py") > names.index("branch_delete.py"):
            raise ValueError("PR merge must precede branch deletion.")

    directory = Path(__file__).resolve().parent
    scripts = []
    for name in names:
        script = directory / name
        if script.is_symlink() or not script.is_file():
            raise ValueError("Registered script must be a regular file.")
        scripts.append(script)
    return scripts


def run_execution(scripts, run=subprocess.run):
    """Run in input order; never start a later script after failure."""
    for script in scripts:
        print(f"Executing {script.name}", flush=True)
        result = run(
            [sys.executable, "-m", "app", "task", script.name],
            cwd=Path(__file__).resolve().parents[1], check=False,
        )
        if result.returncode != 0:
            print(f"Stopped at {script.name} (exit {result.returncode}).",
                  file=sys.stderr, flush=True)
            return result.returncode if result.returncode > 0 else 1
    return 0


def comment_request(event):
    """Accept only an owner-authored execution command on its target PR."""
    owner = event["repository"]["owner"]["id"]
    comment = event["comment"]
    issue = event["issue"]
    if not (
        event["action"] == "created"
        and "pull_request" in issue
        and comment["user"]["id"] == owner
        and event["sender"]["id"] == owner
        and comment["author_association"] == "OWNER"
    ):
        raise ValueError("Unauthorized execution comment.")
    prefix = "/execute "
    if not comment["body"].startswith(prefix):
        raise ValueError("Not an execution command.")
    request = json.loads(comment["body"][len(prefix):])
    if not isinstance(request, dict) or set(request) not in (
        {"execution", "expected_head_sha"},
        {"execution", "expected_head_sha", "queue_comment_id"},
    ):
        raise ValueError("Invalid execution command fields.")
    if not isinstance(request["execution"], str):
        raise ValueError("Expected an execution string.")
    sha = request["expected_head_sha"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected a full lowercase Git commit SHA.")
    if "queue_comment_id" in request and (
        type(request["queue_comment_id"]) is not int
        or request["queue_comment_id"] <= 0
    ):
        raise ValueError("Invalid queue comment ID.")
    number = issue["number"]
    if type(number) is not int or number <= 0:
        raise ValueError("Invalid pull request number.")
    return request["execution"], json.dumps({
        "pr_number": number,
        "expected_head_sha": sha,
    })


def run_stage(scripts, stage, run=subprocess.run):
    """Run exactly one slot of a validated two-script serial request."""
    if len(scripts) != 2 or stage not in (1, 2):
        raise ValueError("Serial execution requires exactly two scripts.")
    return run_execution([scripts[stage - 1]], run=run)
