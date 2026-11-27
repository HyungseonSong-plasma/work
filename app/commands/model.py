# FileRank: C
"""Common framework for explicitly registered application commands."""

from abc import ABC, abstractmethod
import json
import os
from pathlib import Path


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
