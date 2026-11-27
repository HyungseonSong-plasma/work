# FileRank: C
"""Target-specific GitHub deletions with explicit registration and validation."""

import os
import re
import subprocess
import tempfile
from urllib.parse import quote

from config import require_deletion



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


# Preserve the existing execution/audit evidence even on explicit cleanup requests.
PROTECTED_WORKFLOWS = frozenset({
    ".github/workflows/trigger.yml",
    ".github/workflows/single_run.yml",
    ".github/workflows/serial_run.yml",
    ".github/workflows/actions_delete.yml",
})


def delete_actions_run(api, remove, repository, run_ref, run_id,
                       expected_head_sha, expected_run_attempt, current_run_id):
    """Delete exactly one reviewed, completed, non-protected Actions run."""
    require_deletion("actions")
    if any(type(value) is not int or value <= 0 for value in
           (run_id, expected_run_attempt, current_run_id)):
        raise ValueError("Expected positive integer run IDs and attempt.")
    if run_id == current_run_id:
        raise ValueError("Cannot delete the current workflow run.")
    if not isinstance(expected_head_sha, str) or not re.fullmatch(
            r"[0-9a-f]{40}", expected_head_sha):
        raise ValueError("Expected a full lowercase Git commit SHA.")
    root = f"repos/{repository}"
    repo = api("GET", root)
    if run_ref != f"refs/heads/{repo['default_branch']}":
        raise ValueError("Run only on the current default branch.")
    endpoint = f"{root}/actions/runs/{run_id}"
    run = api("GET", endpoint)
    if not (
        run["id"] == run_id
        and run["repository"]["id"] == repo["id"]
        and run["repository"]["full_name"] == repository
        and run["status"] == "completed"
        and run["head_sha"] == expected_head_sha
        and run["run_attempt"] == expected_run_attempt
    ):
        raise ValueError("Expected the reviewed completed run in this repository.")
    path = run["path"]
    if not isinstance(path, str) or not path or path.split("@", 1)[0] in PROTECTED_WORKFLOWS:
        raise ValueError("Protected or unknown workflow run.")
    # GitHub has no conditional delete by run attempt. Recheck immediately.
    if api("GET", endpoint) != run:
        raise ValueError("Run metadata changed before deletion.")
    remove(endpoint)
    return f"Deleted Actions run: {run_id}"


DELETIONS = {
    "branch": delete_branch_with_git,
    "actions": delete_actions_run,
}


def delete(target, **parameters):
    """Dispatch to one explicit deletion implementation, never discover code."""
    require_deletion(target)
    if target not in DELETIONS:
        raise ValueError("Unregistered deletion target.")
    return DELETIONS[target](**parameters)
