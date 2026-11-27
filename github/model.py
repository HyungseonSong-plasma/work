# FileRank: C
"""Shared GitHub REST API transport and workflow dispatch operations."""

import json
import os
from urllib.request import Request, urlopen


def _request(method, endpoint, payload=None):
    """Build a request using the current workflow's scoped token."""
    url = os.environ["GITHUB_API_URL"].rstrip("/") + "/" + endpoint
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    return Request(
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


def github_api(method, endpoint, payload=None, send=urlopen):
    """Call a GitHub REST endpoint that returns a JSON response."""
    with send(_request(method, endpoint, payload), timeout=30) as response:
        return json.load(response)


def dispatch_workflow(repository, workflow, payload, send=urlopen):
    """Submit a workflow once without polling or retrying ambiguous responses."""
    endpoint = f"repos/{repository}/actions/workflows/{workflow}/dispatches"
    with send(_request("POST", endpoint, payload), timeout=30) as response:
        if response.status not in (200, 204):
            raise ValueError(f"Unexpected dispatch status: {response.status}")
