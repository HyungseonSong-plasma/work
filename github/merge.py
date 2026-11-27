# FileRank: C
"""Merge a single, explicitly selected GitHub pull request."""

from github.framework.model import validate_pr_number, validate_sha, review_repository, matches_pr_head


def merge_pr(api, repository, ref, pr_number, expected_head_sha):
    """Validate the request and merge with an atomic head-SHA guard."""
    pr_number = validate_pr_number(pr_number)
    validate_sha(expected_head_sha)
    root, repo = review_repository(api, repository, ref)
    default_branch = repo["default_branch"]

    endpoint = f"{root}/pulls/{pr_number}"
    pr = api("GET", endpoint)
    if not (
        pr["state"] == "open"
        and pr["draft"] is False
        and pr["merged"] is False
        and matches_pr_head(pr, repository, default_branch, expected_head_sha)
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
    if result.get("merged") is not True:
        raise ValueError("GitHub did not confirm a successful merge.")
    return validate_sha(sha)
