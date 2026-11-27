# FileRank: C
"""Merge a single, explicitly selected GitHub pull request."""

from github.framework.model import validate_pr_number, validate_sha, require_default_ref


def merge_pr(api, repository, ref, pr_number, expected_head_sha):
    """Validate the request and merge with an atomic head-SHA guard."""
    pr_number = validate_pr_number(pr_number)
    validate_sha(expected_head_sha)
    default_branch = api("GET", f"repos/{repository}")["default_branch"]
    require_default_ref(ref, default_branch)

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
    if result.get("merged") is not True:
        raise ValueError("GitHub did not confirm a successful merge.")
    return validate_sha(sha)
