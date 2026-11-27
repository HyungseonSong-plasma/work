# FileRank: C
"""Merge a single, explicitly selected GitHub pull request."""

import re


def merge_pr(api, repository, ref, pr_number, expected_head_sha):
    """Validate the request and merge with an atomic head-SHA guard."""
    if not re.fullmatch(r"[1-9][0-9]*", pr_number):
        raise ValueError("Invalid pull request number.")
    if not re.fullmatch(r"[0-9a-f]{40}", expected_head_sha):
        raise ValueError("Expected a full lowercase Git commit SHA.")

    default_branch = api("GET", f"repos/{repository}")["default_branch"]
    if ref != f"refs/heads/{default_branch}":
        raise ValueError("Run this workflow on the current default branch.")

    endpoint = f"repos/{repository}/pulls/{pr_number}"
    pr = api("GET", endpoint)
    if not (
        pr["state"] == "open"
        and pr["draft"] is False
        and pr["merged"] is False
        and pr["base"]["ref"] == default_branch
        and pr["base"]["repo"]["full_name"] == repository
        and pr["head"]["sha"] == expected_head_sha
    ):
        raise ValueError(
            "PR must be open, non-draft, unmerged, target the default branch "
            "and match the expected head SHA."
        )

    # GitHub checks the expected SHA again during the merge operation.
    result = api(
        "PUT",
        f"{endpoint}/merge",
        {"sha": expected_head_sha, "merge_method": "merge"},
    )
    sha = result.get("sha")
    if result.get("merged") is not True or not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("GitHub did not confirm a successful merge.")
    return sha
