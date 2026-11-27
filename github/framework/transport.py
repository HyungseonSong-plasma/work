# FileRank: C
"""GitHub REST transport and explicit response confirmation."""

from contextlib import contextmanager
import json
import os
import subprocess
import tempfile
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


def delete_resource(endpoint, send=urlopen):
    """Delete one REST resource; require explicit HTTP 204 confirmation."""
    with send(_request("DELETE", endpoint), timeout=30) as response:
        if response.status != 204:
            raise ValueError(f"Unexpected deletion status: {response.status}")


@contextmanager
def git_session():
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

        yield git
