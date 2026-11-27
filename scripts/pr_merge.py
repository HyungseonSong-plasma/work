# FileRank: C
"""Merge a single, explicitly selected GitHub pull request."""

import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def github_api(method, endpoint, payload=None):
    """Call the GitHub REST API using the workflow's scoped token."""
    url = os.environ["GITHUB_API_URL"].rstrip("/") + "/" + endpoint
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


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


def main():
    try:
        parameters = json.loads(os.environ["EXECUTION_INPUTS"])
        if not isinstance(parameters, dict) or set(parameters) != {"pr_number", "expected_head_sha"}:
            raise ValueError("Provide pr_number and expected_head_sha only.")
        number = parameters["pr_number"]
        if type(number) is int:
            number = str(number)
        if not isinstance(number, str) or not isinstance(parameters["expected_head_sha"], str):
            raise ValueError("Invalid parameter types.")
        sha = merge_pr(
            github_api,
            os.environ["GITHUB_REPOSITORY"],
            os.environ["GITHUB_REF"],
            number,
            parameters["expected_head_sha"],
        )
    except HTTPError as error:
        print(f"GitHub API request failed: HTTP {error.code}", file=sys.stderr)
        return 1
    except (URLError, ValueError, KeyError, TimeoutError, TypeError) as error:
        print(f"Merge could not be confirmed: {error}", file=sys.stderr)
        return 1

    print(f"Merged PR #{number}: {sha}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(f"Merged PR #{number}\n\nMerge commit: `{sha}`\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
