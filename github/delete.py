# FileRank: C
"""Target-specific GitHub deletions with explicit registration and validation."""

import os
import re
import subprocess
import tempfile
from urllib.parse import quote

from config import require_deletion, load_registry



def delete_branch(api, git, repository, run_ref, number, sha, remote):
    """Derive the deletion target from GitHub, not from user-supplied refs."""
    require_deletion("branch")
    root = f"repos/{repository}"
    default = api("GET", root)["default_branch"]
    if run_ref != f"refs/heads/{default}":
        raise ValueError("Run only on the current default branch.")

    pr = api("GET", f"{root}/pulls/{number}")
    if not (
        pr["state"] == "closed"
        and pr["merged"] is True
        and pr["base"]["ref"] == default
        and pr["base"]["repo"]["full_name"] == repository
        and pr["head"]["sha"] == sha
    ):
        raise ValueError("Expected a merged PR into the default branch with matching head SHA.")
    head = pr["head"]
    if not head["repo"] or head["repo"]["full_name"] != repository:
        return "Skip: fork or missing head repository."

    branch = head["ref"]
    if branch in {default, "main", "master"}:
        return "Skip: default or reserved branch."
    ref = f"refs/heads/{branch}"
    git("check-ref-format", ref)
    current = git("ls-remote", "--exit-code", "--refs", remote, ref, allowed=(0, 2))
    if current.returncode == 2:
        return "Skip: branch already absent."
    if current.stdout.rstrip("\n") != f"{sha}\t{ref}":
        return "Skip: branch head has changed."

    details = api("GET", f"{root}/branches/{quote(branch, safe='')}")
    if details["protected"] is not False or details["commit"]["sha"] != sha:
        return "Skip: protected branch or changed head."

    # Scan every page of open PRs before deleting.
    page = 1
    while True:
        pulls = api("GET", f"{root}/pulls?state=open&per_page=100&page={page}")
        if not isinstance(pulls, list):
            raise ValueError("Invalid open PR response.")
        for other in pulls:
            for side in ("head", "base"):
                endpoint = other[side]
                if endpoint["ref"] == branch and (
                    endpoint["repo"] is None
                    or endpoint["repo"]["full_name"] == repository
                ):
                    return "Skip: branch is used by an open PR."
        if len(pulls) < 100:
            break
        page += 1

    # The server rejects the ref update if its SHA changed since verification.
    git("push", f"--force-with-lease={ref}:{sha}", remote, f":{ref}")
    return f"Deleted merged PR head: {branch}"


def delete_branch_with_git(api, repository, run_ref, number, sha, remote):
    """Use an isolated Git repository and the scoped credential helper."""
    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(["git", "init", "-q", directory], check=True)
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")

        def git(*args, allowed=(0,)):
            result = subprocess.run(
                ["git", "-C", directory, "-c", "credential.helper=",
                 "-c", "credential.helper=!gh auth git-credential", *args],
                env=env, capture_output=True, text=True, timeout=60,
            )
            if result.returncode not in allowed:
                raise ValueError(f"Git {args[0]} failed (exit {result.returncode}).")
            return result

        return delete_branch(api, git, repository, run_ref, number, sha, remote)


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
        sha = target["expected_head_sha"]
        if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise ValueError("Expected a full lowercase Git commit SHA.")
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
    if run_ref != f"refs/heads/{repo['default_branch']}":
        raise ValueError("Run only on the current default branch.")
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


DELETIONS = {
    "branch": delete_branch_with_git,
    "actions": delete_actions_run,
    "actions_batch": delete_actions_batch,
}


def delete(target, **parameters):
    """Dispatch to one explicit deletion implementation, never discover code."""
    require_deletion("actions" if target == "actions_batch" else target)
    if target not in DELETIONS:
        raise ValueError("Unregistered deletion target.")
    return DELETIONS[target](**parameters)
