# FileRank: C
"""Route an authorized PR comment to one execution workflow; never execute it."""

import json

from github.actions import actions_request
from work.libs.github import (CLIENT, validate_sha, validate_pr_number, require_default_ref,
                         parse_execute_comment, is_unchanged_comment)


def owner_comment(event):
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
    return parse_execute_comment(comment["body"])


def comment_request(event):
    return _comment_parameters(event, owner_comment(event))


def _comment_parameters(event, request):
    issue = event["issue"]
    if not isinstance(request, dict) or set(request) not in (
        {"execution", "expected_head_sha"},
        {"execution", "expected_head_sha", "queue_comment_id"},
    ):
        raise ValueError("Invalid execution command fields.")
    if not isinstance(request["execution"], str):
        raise ValueError("Expected an execution string.")
    sha = validate_sha(request["expected_head_sha"])
    if "queue_comment_id" in request and (
        type(request["queue_comment_id"]) is not int
        or request["queue_comment_id"] <= 0
    ):
        raise ValueError("Invalid queue comment ID.")
    number = issue["number"]
    if type(number) is not int:
        raise ValueError("Invalid pull request number.")
    validate_pr_number(number)
    return request["execution"], json.dumps({
        "pr_number": number,
        "expected_head_sha": sha,
    })


def route_actions(event, default, request_id, request):
    from config import require_deletion

    require_deletion("actions")
    number = event["issue"]["number"]
    if type(number) is not int:
        raise ValueError("Invalid source PR number.")
    validate_pr_number(number)
    if not is_unchanged_comment(event["comment"]):
        raise ValueError("Edited approval is not accepted.")
    return "actions_delete.yml", {
        "ref": default,
        "inputs": dict(actions_request(request), request_id=request_id,
                       source_pr=str(number)),
    }


def route(event, repository, ref, *, routes, resolve):
    if event["repository"]["full_name"] != repository:
        raise ValueError("Request repository mismatch.")
    default = event["repository"]["default_branch"]
    require_default_ref(ref, default)
    request = owner_comment(event)
    comment_id = event["comment"]["id"]
    if type(comment_id) is not int or comment_id <= 0:
        raise ValueError("Invalid comment ID.")
    request_id = f"comment-{comment_id}"
    if isinstance(request, dict) and request.get("execution") == "delete actions":
        return route_actions(event, default, request_id, request)
    return _route_pr(event, default, request_id, request, routes, resolve)


def _route_pr(event, default, request_id, request, routes, resolve):
    execution, parameters = _comment_parameters(event, request)
    executions = resolve(execution, parameters)
    return routes.resolve(executions), {
        "ref": default,
        "inputs": {
            "execution": " - ".join(executions),
            "parameters": parameters,
            "request_id": request_id,
        },
    }


def dispatch_request(event, repository, ref, dispatch=CLIENT.dispatch, *, routes, resolve):
    """Validate and submit exactly one matching workflow."""
    workflow, payload = route(event, repository, ref, routes=routes, resolve=resolve)
    dispatch(repository, workflow, payload)
    return workflow, payload["inputs"]["request_id"]
