# FileRank: C
"""Delete the unchanged local head of an explicitly identified merged PR."""

import json
import os
import re
import subprocess
import tempfile
from urllib.parse import quote

from config import require_deletion


def parse_parameters(raw):
    parameters = json.loads(raw)
    if not isinstance(parameters, dict) or set(parameters) != {
        "pr_number", "expected_head_sha"
    }:
        raise ValueError("Provide pr_number and expected_head_sha only.")
    number = parameters["pr_number"]
    if type(number) is int:
        number = str(number)
    sha = parameters["expected_head_sha"]
    if not isinstance(number, str) or not re.fullmatch(r"[1-9][0-9]*", number):
        raise ValueError("Invalid pull request number.")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected a full lowercase Git commit SHA.")
    return number, sha


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


def delete_with_git(api, repository, run_ref, number, sha, remote):
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
