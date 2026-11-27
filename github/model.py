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


class WorkflowRegistry:
    """Map exact, ordered execution chains to explicitly registered workflows."""

    def __init__(self):
        self._routes = {}

    @staticmethod
    def _key(execution):
        if isinstance(execution, (str, bytes)):
            raise ValueError("Execution must be a sequence of script names.")
        key = tuple(execution)
        if not key or any(not isinstance(name, str) or not name for name in key):
            raise ValueError("Expected a nonempty execution chain.")
        if len(key) != len(set(key)):
            raise ValueError("Duplicate scripts in workflow route.")
        return key

    def register(self, execution, workflow):
        key = self._key(execution)
        if key in self._routes:
            raise ValueError("Duplicate workflow route.")
        if (not isinstance(workflow, str) or
                not workflow.endswith((".yml", ".yaml")) or
                "/" in workflow or "\\" in workflow or
                not workflow.rsplit(".", 1)[0].replace("_", "").replace("-", "").isalnum()):
            raise ValueError("Expected a workflow filename.")
        self._routes[key] = workflow

    def resolve(self, execution):
        key = self._key(execution)
        if key not in self._routes:
            raise ValueError("Unregistered workflow route.")
        return self._routes[key]
