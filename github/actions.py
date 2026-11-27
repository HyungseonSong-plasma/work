# FileRank: C
"""Exact Actions request, retention and deletion policies."""

import json
import re

from config import require_deletion, load_registry
from github.framework.model import validate_sha, require_default_ref


def actions_request(request):
    """Validate the single-run or exact batch request."""
    if not isinstance(request, dict) or request.get("execution") != "delete actions":
        raise ValueError("Invalid Actions deletion request.")
    if set(request) == {"execution", "runs"}:
        targets = validate_actions_targets(request["runs"])
        return {"runs": json.dumps(targets, sort_keys=True, separators=(",", ":"))}
    if set(request) != {
        "execution", "run_id", "expected_head_sha", "expected_run_attempt"
    }:
        raise ValueError("Invalid Actions deletion request.")
    target = {key: request[key] for key in
              ("run_id", "expected_head_sha", "expected_run_attempt")}
    validate_actions_targets([target])
    return {key: str(value) for key, value in target.items()}


def actions_policy():
    policy = load_registry("actions_policy")
    if not isinstance(policy, dict) or set(policy) != {
        "max_batch", "keep_successful", "protected_workflows", "pinned_run_ids"
    }:
        raise ValueError("Invalid Actions policy.")
    maximum, keep = policy["max_batch"], policy["keep_successful"]
    if type(maximum) is not int or not 1 <= maximum <= 50:
        raise ValueError("Invalid batch limit.")
    if type(keep) is not int or not 1 <= keep <= 20:
        raise ValueError("Invalid retention count.")
    paths, pins = policy["protected_workflows"], policy["pinned_run_ids"]
    if (not isinstance(paths, list) or not paths or any(
            not isinstance(path, str) or not re.fullmatch(
                r"\.github/workflows/[A-Za-z0-9_-]+\.ya?ml", path)
            for path in paths) or len(paths) != len(set(paths))):
        raise ValueError("Invalid retained workflow paths.")
    if (not isinstance(pins, list) or any(type(pin) is not int or pin <= 0
            for pin in pins) or len(pins) != len(set(pins))):
        raise ValueError("Invalid pinned run IDs.")
    return policy


def validate_actions_targets(targets, policy=None):
    policy = actions_policy() if policy is None else policy
    if not isinstance(targets, list) or not 1 <= len(targets) <= policy["max_batch"]:
        raise ValueError("Invalid Actions batch size.")
    ids = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {
            "run_id", "expected_head_sha", "expected_run_attempt"
        }:
            raise ValueError("Invalid Actions target.")
        if any(type(target[key]) is not int or target[key] <= 0
               for key in ("run_id", "expected_run_attempt")):
            raise ValueError("Expected positive integer run ID and attempt.")
        validate_sha(target["expected_head_sha"])
        if target["run_id"] in ids:
            raise ValueError("Duplicate Actions run ID.")
        ids.add(target["run_id"])
    return targets


def _run_path(run):
    path = run["path"]
    if not isinstance(path, str) or not path:
        raise ValueError("Unknown workflow path.")
    return path.split("@", 1)[0]


def _check_retention(api, root, repository, repo_id, run, policy):
    if run["id"] in policy["pinned_run_ids"]:
        raise ValueError("Pinned Actions evidence.")
    path = _run_path(run)
    if path not in policy["protected_workflows"]:
        return
    workflow_id = run["workflow_id"]
    if type(workflow_id) is not int or workflow_id <= 0:
        raise ValueError("Invalid workflow ID.")
    response = api("GET", f"{root}/actions/workflows/{workflow_id}/runs?status=success&per_page=100")
    runs, total = response["workflow_runs"], response["total_count"]
    if (not isinstance(runs, list) or len(runs) > 100 or type(total) is not int
            or total < len(runs) or len(runs) < min(total, policy["keep_successful"])):
        raise ValueError("Incomplete successful-run listing.")
    previous, seen = None, set()
    for item in runs:
        if not (
            item["workflow_id"] == workflow_id
            and item["repository"]["id"] == repo_id
            and item["repository"]["full_name"] == repository
            and _run_path(item) == path
            and item["status"] == "completed"
            and item["conclusion"] == "success"
            and type(item["id"]) is int and item["id"] > 0
            and item["id"] not in seen
        ):
            raise ValueError("Unexpected successful-run metadata.")
        order = (item["created_at"], item["id"])
        if previous is not None and order > previous:
            raise ValueError("Successful-run listing not newest first.")
        previous = order
        seen.add(item["id"])
    if run["conclusion"] == "success" and not runs:
        raise ValueError("Successful target missing from retention listing.")
    if run["id"] in {item["id"] for item in runs[:policy["keep_successful"]]}:
        raise ValueError("Latest successful workflow run is retained.")


def _review_run(api, root, repo, repository, target, policy):
    endpoint = f"{root}/actions/runs/{target['run_id']}"
    run = api("GET", endpoint)
    if not (
        run["id"] == target["run_id"]
        and run["repository"]["id"] == repo["id"]
        and run["repository"]["full_name"] == repository
        and run["status"] == "completed"
        and run["head_sha"] == target["expected_head_sha"]
        and run["run_attempt"] == target["expected_run_attempt"]
    ):
        raise ValueError("Expected the reviewed completed run in this repository.")
    _check_retention(api, root, repository, repo["id"], run, policy)
    return endpoint, run


def delete_actions_batch(api, remove, repository, run_ref, targets, current_run_id,
                         report=print):
    """Validate every target before the first DELETE, then revalidate each."""
    require_deletion("actions")
    policy = actions_policy()
    validate_actions_targets(targets, policy)
    if type(current_run_id) is not int or current_run_id <= 0:
        raise ValueError("Invalid current run ID.")
    if any(target["run_id"] == current_run_id for target in targets):
        raise ValueError("Cannot delete the current workflow run.")
    root = f"repos/{repository}"
    repo = api("GET", root)
    require_default_ref(run_ref, repo["default_branch"])
    reviewed = [_review_run(api, root, repo, repository, target, policy)
                for target in targets]
    results = []
    for target, (endpoint, run) in zip(targets, reviewed):
        fresh_endpoint, fresh = _review_run(api, root, repo, repository, target, policy)
        if fresh_endpoint != endpoint or fresh != run:
            raise ValueError("Run metadata changed before deletion.")
        remove(endpoint)
        result = f"Deleted Actions run: {target['run_id']}"
        results.append(result)
        report(result)
    return results


def delete_actions_run(api, remove, repository, run_ref, run_id,
                       expected_head_sha, expected_run_attempt, current_run_id):
    return delete_actions_batch(
        api, remove, repository, run_ref,
        [{"run_id": run_id, "expected_head_sha": expected_head_sha,
          "expected_run_attempt": expected_run_attempt}], current_run_id,
        report=lambda message: None)[0]
