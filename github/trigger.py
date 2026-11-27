# FileRank: C
"""Route an authorized PR comment to one execution workflow; never execute it."""

import json
import re

from config import load_registry
from github.model import WorkflowRegistry, dispatch_workflow
from scripts.execute import EXECUTIONS, resolve_execution


registry = WorkflowRegistry.from_json(load_registry("workflows"), EXECUTIONS)


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


def route(event, repository, ref):
    if event["repository"]["full_name"] != repository:
        raise ValueError("Request repository mismatch.")
    default = event["repository"]["default_branch"]
    if ref != f"refs/heads/{default}":
        raise ValueError("Trigger must run on the default branch.")
    execution, parameters = comment_request(event)
    scripts = resolve_execution(execution, parameters)
    workflow = registry.resolve(script.name for script in scripts)
    comment_id = event["comment"]["id"]
    if type(comment_id) is not int or comment_id <= 0:
        raise ValueError("Invalid comment ID.")
    return workflow, {
        "ref": default,
        "inputs": {
            "execution": " - ".join(script.name for script in scripts),
            "parameters": parameters,
            "request_id": f"comment-{comment_id}",
        },
    }


def dispatch_request(event, repository, ref, dispatch=dispatch_workflow):
    """Validate and submit exactly one matching workflow."""
    workflow, payload = route(event, repository, ref)
    dispatch(repository, workflow, payload)
    return workflow, payload["inputs"]["request_id"]
