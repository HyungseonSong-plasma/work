# FileRank: C
"""GitHub REST and isolated Git transport; no domain or framework dependencies."""

from contextlib import contextmanager
import json
import os
import subprocess
import tempfile
from urllib.request import Request, urlopen


# REST and isolated Git transport

class GitHubClient:
    """Explicit REST response contracts over one request lifecycle."""

    def __init__(self, send=urlopen):
        self.send = send

    @staticmethod
    def _request(method, endpoint, payload=None):
        """Read the current workflow's scoped token at request time."""
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

    def _execute(self, method, endpoint, payload, *, consume):
        """Open one response, consume it inside its scope, never retry."""
        with self.send(self._request(method, endpoint, payload), timeout=30) as response:
            return consume(response)

    def request(self, method, endpoint, payload=None):
        return self._execute(method, endpoint, payload, consume=json.load)

    @staticmethod
    def _confirm(response, allowed, operation):
        if response.status not in allowed:
            raise ValueError(f"Unexpected {operation} status: {response.status}")

    def _execute_status(self, method, endpoint, payload, *, allowed, operation):
        """Confirm an HTTP status inside the response scope, without decoding JSON."""
        return self._execute(method, endpoint, payload,
                             consume=lambda response: self._confirm(response, allowed, operation))

    def dispatch(self, repository, workflow, payload):
        endpoint = f"repos/{repository}/actions/workflows/{workflow}/dispatches"
        return self._execute_status("POST", endpoint, payload, allowed=(200, 204),
                                    operation="dispatch")

    def delete(self, endpoint):
        return self._execute_status("DELETE", endpoint, None, allowed=(204,),
                                    operation="deletion")


# Stateless default binding: environment and credentials are read only on requests.
CLIENT = GitHubClient()


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
