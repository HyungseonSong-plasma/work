# FileRank: C
"""Common framework for explicitly registered application commands."""

from abc import ABC, abstractmethod
import json
import os
import re
from pathlib import Path

from github.model import github_api


class Command(ABC):
    """Uniform CLI interface; commands without arguments use the default."""

    help = ""
    workflow_execution = ()  # Explicit execution ID and fixed CLI arguments.

    @classmethod
    def bind(cls, subparsers, name):
        parser = subparsers.add_parser(name, help=cls.help)
        cls.configure(parser)
        parser.set_defaults(handler=cls.execute)

    @staticmethod
    def configure(parser):
        pass

    @staticmethod
    @abstractmethod
    def execute(args):
        raise NotImplementedError


def summary(message):
    """Append a result to the current GitHub Actions job summary, if present."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(message)


def require_event(name, fresh=False):
    """Validate the event contract without inferring authorization."""
    if os.environ["GITHUB_EVENT_NAME"] != name or (
            fresh and os.environ["GITHUB_RUN_ATTEMPT"] != "1"):
        raise ValueError(f"Requires {name}" + (" (first attempt)." if fresh else "."))


def read_event():
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
        return json.load(stream)


def repository_context():
    return os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_REF"]


def pr_context(execution):
    """Validate a fixed PR execution identity and its shared input contract."""
    from github.model import parse_pr_parameters
    from scripts.execute import resolve_execution

    require_event("workflow_dispatch", fresh=True)
    raw = os.environ["EXECUTION_INPUTS"]
    resolve_execution(execution, raw)
    number, sha = parse_pr_parameters(raw)
    repository, ref = repository_context()
    return number, sha, repository, ref


def report(message, detail=None):
    print(message, flush=True)
    summary((message if detail is None else detail) + "\n")


def validate_actions_context(event, repository, ref, actor_id, workflow_ref,
                             request_id="", source_pr="", inputs=None, api=github_api):
    """Revalidate the dedicated Actions worker and exact owner approval."""
    from github.trigger import actions_request

    repo = event["repository"]
    owner = str(repo["owner"]["id"])
    if not (
        repo["full_name"] == repository
        and ref == f"refs/heads/{repo['default_branch']}"
        and workflow_ref == f"{repository}/.github/workflows/actions_delete.yml@{ref}"
    ):
        raise ValueError("Unauthorized Actions deletion workflow.")
    sender = event["sender"]
    if str(sender["id"]) != actor_id:
        raise ValueError("Workflow actor mismatch.")
    if not request_id and not source_pr:
        if actor_id != owner:
            raise ValueError("Manual deletion requires the owner.")
        return
    if not re.fullmatch(r"comment-[1-9][0-9]*", request_id) or not re.fullmatch(
            r"[1-9][0-9]*", source_pr):
        raise ValueError("Invalid source comment or PR.")
    if actor_id != owner and not (
        actor_id == "41898282" and sender["login"] == "github-actions[bot]"
    ):
        raise ValueError("Unauthorized dispatch actor.")
    root = f"repos/{repository}"
    comment_id = int(request_id.split("-", 1)[1])
    comment = api("GET", f"{root}/issues/comments/{comment_id}")
    pr = api("GET", f"{root}/pulls/{source_pr}")
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    if not (
        comment["id"] == comment_id
        and comment["user"]["id"] == repo["owner"]["id"]
        and comment["author_association"] == "OWNER"
        and comment["created_at"] == comment["updated_at"]
        and comment["issue_url"] == f"{api_url}/{root}/issues/{source_pr}"
        and pr["number"] == int(source_pr)
        and pr["base"]["repo"]["full_name"] == repository
        and comment["body"].startswith("/execute ")
    ):
        raise ValueError("Source comment is not an unchanged owner PR request.")
    request = json.loads(comment["body"][len("/execute "):])
    if actions_request(request) != inputs:
        raise ValueError("Source approval does not match dispatch inputs.")
