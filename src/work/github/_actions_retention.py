# FileRank: C
"""Actions retention evidence: guarded retrieval and deterministic validation."""

import re
from datetime import datetime


def _run_path(run):
    path = run["path"]
    if not isinstance(path, str) or not path:
        raise ValueError("Unknown workflow path.")
    return path.split("@", 1)[0]


def _retention_order(run):
    """Validate GitHub's UTC creation timestamp before comparing ranks."""
    created = run.get("created_at")
    if not isinstance(created, str) or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", created):
        raise ValueError("Invalid successful-run creation timestamp.")
    try:
        datetime.strptime(created, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("Invalid successful-run creation timestamp.") from error
    return created, run["id"]


def check_retention(api, root, repository, repo_id, run, policy):
    """Apply pinned/path guards and fetch one protected workflow evidence page."""
    if run["id"] in policy["pinned_run_ids"]:
        raise ValueError("Pinned Actions evidence.")
    path = _run_path(run)
    if path not in policy["protected_workflows"]:
        return
    workflow_id = run["workflow_id"]
    if type(workflow_id) is not int or workflow_id <= 0:
        raise ValueError("Invalid workflow ID.")
    response = api("GET", f"{root}/actions/workflows/{workflow_id}/runs?status=success&per_page=100")
    validate_successful_listing(response, repository, repo_id, workflow_id, path, run, policy)


def validate_successful_listing(response, repository, repo_id, workflow_id, path, run, policy):
    """Check supplied evidence without I/O or changing the reviewed metadata."""
    runs, total = response["workflow_runs"], response["total_count"]
    if (not isinstance(runs, list) or type(total) is not int or total < 0
            or len(runs) != min(total, 100)):
        raise ValueError("Incomplete successful-run listing.")
    previous, seen = None, set()
    target_order = _retention_order(run) if run["conclusion"] == "success" else None
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
        order = _retention_order(item)
        if previous is not None and order > previous:
            raise ValueError("Successful-run listing not newest first.")
        previous = order
        seen.add(item["id"])
        if item["id"] == run["id"] and (
                order != target_order
                or item.get("head_sha") != run["head_sha"]
                or type(item.get("run_attempt")) is not int
                or item["run_attempt"] != run["run_attempt"]):
            raise ValueError("Successful target metadata differs from retention listing.")
    # Absence is only consistent beyond a complete first page of a longer listing.
    if target_order is not None and run["id"] not in seen:
        if total <= len(runs) or previous is None or target_order >= previous:
            raise ValueError("Successful target missing from retention listing.")
    if run["id"] in {item["id"] for item in runs[:policy["keep_successful"]]}:
        raise ValueError("Latest successful workflow run is retained.")
