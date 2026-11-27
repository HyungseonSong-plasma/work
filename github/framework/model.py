# FileRank: C
"""Shared GitHub input and wire validation contracts."""

import json
import re


def validate_sha(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError("Expected a full lowercase Git commit SHA.")
    return value


def validate_pr_number(value):
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
        raise ValueError("Invalid pull request number.")
    return value


def require_default_ref(ref, default):
    if not isinstance(default, str) or not default or ref != f"refs/heads/{default}":
        raise ValueError("Run only on the current default branch.")


def parse_execute_comment(body):
    prefix = "/execute "
    if not isinstance(body, str) or not body.startswith(prefix):
        raise ValueError("Not an execution command.")
    return json.loads(body[len(prefix):])


def parse_pr_parameters(raw):
    parameters = json.loads(raw)
    if not isinstance(parameters, dict) or set(parameters) != {
        "pr_number", "expected_head_sha"
    }:
        raise ValueError("Provide pr_number and expected_head_sha only.")
    return (validate_pr_number(parameters["pr_number"]),
            validate_sha(parameters["expected_head_sha"]))

def review_repository(api, repository, ref):
    """Read repository metadata and require its current default ref."""
    root = f"repos/{repository}"
    repo = api("GET", root)
    require_default_ref(ref, repo["default_branch"])
    return root, repo


def matches_pr_head(pr, repository, default, sha):
    """Compare the reviewed base repository/ref and exact head SHA."""
    return (pr["base"]["ref"] == default
            and pr["base"]["repo"]["full_name"] == repository
            and pr["head"]["sha"] == sha)
