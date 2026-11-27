# FileRank: C
"""Common framework for explicitly registered application commands."""

from dataclasses import dataclass
from inspect import signature
import json
import os
import re
from pathlib import Path

from github.model import github_api, require_default_ref, parse_execute_comment, validate_pr_number


@dataclass(frozen=True)
class CommandPlan:
    """Declarative execution contract; the runner owns its stage order."""

    prepare: object
    validate: object
    action: object
    report: object = None
    returns_status: bool = False

    def __post_init__(self):
        for callback, arity in ((self.prepare, 1), (self.validate, 2), (self.action, 2)):
            _validate_callback(callback, arity)
        if self.report is not None:
            _validate_callback(self.report, 2)
        if type(self.returns_status) is not bool:
            raise TypeError("Command status mode must be boolean.")


def _validate_callback(callback, arity):
    try:
        if not callable(callback):
            raise TypeError("Not callable.")
        signature(callback).bind(*([None] * arity))
    except (TypeError, ValueError) as error:
        raise TypeError("Invalid command lifecycle callback.") from error


def _identity(ctx, args):
    return ctx


class Command:
    """Registered implementations declare plans; they do not own the runner."""

    help = ""
    workflow_execution = ()
    plan = None
    targets = ()

    @classmethod
    def bind(cls, subparsers, name):
        validate_command(cls)
        parser = subparsers.add_parser(name, help=cls.help)
        cls.configure(parser)
        if any(action.dest in ("command", "handler") for action in parser._actions):
            raise TypeError("Reserved command parser destination.")
        if any(name in parser._defaults for name in ("command", "handler")):
            raise TypeError("Reserved command parser default.")

    @staticmethod
    def configure(parser):
        pass

    @classmethod
    def execute(cls, args):
        validate_command(cls)
        if cls.targets:
            target = getattr(args, "target", None)
            if not isinstance(target, str) or target not in dict(cls.targets):
                raise ValueError("Unknown deletion target.")
            plan = dict(cls.targets)[target]
        else:
            plan = cls.plan
        ctx = plan.prepare(args)
        ctx = plan.validate(ctx, args)
        result = plan.action(ctx, args)
        if plan.report is not None:
            plan.report(ctx, result)
        return result if plan.returns_status else 0


def validate_command(command):
    """Reject alternate registered execution entrypoints and malformed plans."""
    if not isinstance(command, type) or not issubclass(command, Command):
        raise TypeError("Command must extend Command model.")
    for name in ("bind", "execute"):
        if getattr(getattr(command, name), "__func__", None) is not getattr(Command, name).__func__:
            raise TypeError(f"Command may not override framework {name}.")
    _validate_callback(command.configure, 1)
    if not isinstance(command.help, str) or not command.help:
        raise TypeError("Command requires a help string.")
    targets = command.targets
    if not isinstance(targets, tuple):
        raise TypeError("Command targets must be an explicit tuple.")
    if targets:
        if command.plan is not None or any(
                not isinstance(row, tuple) or len(row) != 2
                or not isinstance(row[0], str) or not row[0]
                or type(row[1]) is not CommandPlan for row in targets):
            raise TypeError("Invalid targeted command plans.")
        names = [name for name, _ in targets]
        if len(names) != len(set(names)):
            raise TypeError("Duplicate command target.")
    elif type(command.plan) is not CommandPlan:
        raise TypeError("Command requires a lifecycle plan.")


class Context:
    """Per-invocation environment and reporting; no mutation of GitHub resources."""

    def __init__(self, env=None):
        self.env = dict(os.environ if env is None else env)

    @property
    def repository(self):
        return self.env["GITHUB_REPOSITORY"]

    @property
    def ref(self):
        return self.env["GITHUB_REF"]

    @property
    def actor_id(self):
        return self.env["GITHUB_ACTOR_ID"]

    @property
    def workflow_ref(self):
        return self.env["GITHUB_WORKFLOW_REF"]

    @property
    def run_id(self):
        return int(self.env["GITHUB_RUN_ID"])

    @property
    def execution(self):
        return self.env["EXECUTION"]

    @property
    def parameters(self):
        return self.env["EXECUTION_INPUTS"]

    @property
    def remote(self):
        return self.env["GITHUB_SERVER_URL"].rstrip("/") + f"/{self.repository}.git"

    def require_event(self, name, fresh=False):
        if self.env["GITHUB_EVENT_NAME"] != name or (
                fresh and self.env["GITHUB_RUN_ATTEMPT"] != "1"):
            raise ValueError(f"Requires {name}" + (" (first attempt)." if fresh else "."))
        return self

    def read_event(self):
        with open(self.env["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
            return json.load(stream)

    def summary(self, message):
        path = self.env.get("GITHUB_STEP_SUMMARY")
        if path:
            with Path(path).open("a", encoding="utf-8") as stream:
                stream.write(message)

    def report(self, message, detail=None):
        print(message, flush=True)
        self.summary((message if detail is None else detail) + "\n")


class PRContext(Context):
    """Validated PR execution parameters; remote state checks remain in handlers."""

    def __init__(self, execution, env=None):
        super().__init__(env)
        self.execution_id = execution

    def validate(self):
        from github.model import parse_pr_parameters
        from app.framework.registry import resolve_execution

        self.require_event("workflow_dispatch", fresh=True)
        resolve_execution(self.execution_id, self.parameters)
        number, sha = parse_pr_parameters(self.parameters)
        # Require repository and ref before exposing the validated PR fields.
        self.repository, self.ref
        self.number, self.sha = number, sha
        return self


class ActionsContext(Context):
    """Validate exact owner approval, then normalize single and batch targets."""

    def __init__(self, args, env=None, api=github_api):
        super().__init__(env)
        self.args = args
        self.api = api

    def validate(self):
        from github.trigger import actions_request

        self.require_event("workflow_dispatch", fresh=True)
        args = self.args
        if args.runs:
            if any(value is not None for value in
                   (args.run_id, args.expected_head_sha, args.expected_run_attempt)):
                raise ValueError("Choose single or batch, not both.")
            request = {"execution": "delete actions", "runs": json.loads(args.runs)}
        else:
            request = {"execution": "delete actions", "run_id": args.run_id,
                       "expected_head_sha": args.expected_head_sha,
                       "expected_run_attempt": args.expected_run_attempt}
        # Preserve the approved wire format during comparison, normalize afterwards.
        inputs = actions_request(request)
        self._validate_approval(self.read_event(), inputs)
        if self.run_id <= 0:
            raise ValueError("Invalid current run ID.")
        self.targets = (json.loads(inputs["runs"]) if args.runs else
                        [{"run_id": int(inputs["run_id"]),
                          "expected_head_sha": inputs["expected_head_sha"],
                          "expected_run_attempt": int(inputs["expected_run_attempt"])}])
        return self

    def _validate_approval(self, event, inputs):
        from github.trigger import actions_request

        repository, ref = self.repository, self.ref
        actor_id, workflow_ref = self.actor_id, self.workflow_ref
        request_id, source_pr = self.args.request_id, self.args.source_pr
        api = self.api
        repo = event["repository"]
        owner = str(repo["owner"]["id"])
        if not (
            repo["full_name"] == repository
            and workflow_ref == f"{repository}/.github/workflows/actions_delete.yml@{ref}"
        ):
            raise ValueError("Unauthorized Actions deletion workflow.")
        require_default_ref(ref, repo["default_branch"])
        sender = event["sender"]
        if str(sender["id"]) != actor_id:
            raise ValueError("Workflow actor mismatch.")
        if not request_id and not source_pr:
            if actor_id != owner:
                raise ValueError("Manual deletion requires the owner.")
            return
        if not re.fullmatch(r"comment-[1-9][0-9]*", request_id) or not isinstance(source_pr, str):
            raise ValueError("Invalid source comment or PR.")
        validate_pr_number(source_pr)
        if actor_id != owner and not (
            actor_id == "41898282" and sender["login"] == "github-actions[bot]"
        ):
            raise ValueError("Unauthorized dispatch actor.")
        root = f"repos/{repository}"
        comment_id = int(request_id.split("-", 1)[1])
        comment = api("GET", f"{root}/issues/comments/{comment_id}")
        pr = api("GET", f"{root}/pulls/{source_pr}")
        api_url = self.env.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        if not (
            comment["id"] == comment_id
            and comment["user"]["id"] == repo["owner"]["id"]
            and comment["author_association"] == "OWNER"
            and comment["created_at"] == comment["updated_at"]
            and comment["issue_url"] == f"{api_url}/{root}/issues/{source_pr}"
            and pr["number"] == int(source_pr)
            and pr["base"]["repo"]["full_name"] == repository
        ):
            raise ValueError("Source comment is not an unchanged owner PR request.")
        request = parse_execute_comment(comment["body"])
        if actions_request(request) != inputs:
            raise ValueError("Source approval does not match dispatch inputs.")

def local_plan(action):
    """Local commands do not require GitHub environment variables."""
    return CommandPlan(lambda args: None, _identity, action, returns_status=True)


def workflow_plan(event, action, *, validate=_identity, report=None, returns_status=False):
    """Require the expected event and first attempt before command validation."""
    def verify(ctx, args):
        ctx.require_event(event, fresh=True)
        return validate(ctx, args)

    return CommandPlan(lambda args: Context(), verify, action, report, returns_status)


def pr_plan(execution, action, *, preflight=None, report=None):
    """Enforce PR context validation, including fixed execution identifier."""
    def prepare(args):
        if preflight is not None:
            preflight(args)
        return PRContext(execution)

    return CommandPlan(prepare, lambda ctx, args: ctx.validate(), action, report)


def actions_plan(action):
    """Enforce independent Actions worker authorization before mutation."""
    return CommandPlan(lambda args: ActionsContext(args),
                       lambda ctx, args: ctx.validate(), action)
