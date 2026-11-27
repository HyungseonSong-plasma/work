# FileRank: C
"""GitHub workflow context and regulated command plan composition."""

import json
import os
from pathlib import Path

from libs.command import CommandPlan
from libs.github import parse_pr_parameters


def _identity(ctx, args):
    return ctx


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

    def __init__(self, execution, env=None, *, resolve):
        super().__init__(env)
        self.execution_id = execution
        self.resolve = resolve

    def validate(self):
        self.require_event("workflow_dispatch", fresh=True)
        self.resolve(self.execution_id, self.parameters)
        number, sha = parse_pr_parameters(self.parameters)
        # Require repository and ref before exposing the validated PR fields.
        self.repository, self.ref
        self.number, self.sha = number, sha
        return self


def _validate_context(ctx, args):
    return ctx.validate()


def context_plan(prepare, action, *, validate=_validate_context,
                 preflight=None, report=None, returns_status=False):
    """Compose a context factory and validator with the common command runner."""
    if preflight is not None:
        def prepare_context(args):
            preflight(args)
            return prepare(args)
    else:
        prepare_context = prepare
    return CommandPlan(prepare_context, validate, action, report, returns_status)


def workflow_plan(event, action, *, validate=_identity, report=None, returns_status=False):
    """Require the expected event and first attempt before command validation."""
    def verify(ctx, args):
        ctx.require_event(event, fresh=True)
        return validate(ctx, args)

    return context_plan(lambda args: Context(), action, validate=verify,
                        report=report, returns_status=returns_status)


def pr_plan(execution, action, *, resolve, preflight=None, report=None):
    """Enforce PR context validation, including fixed execution identifier."""
    return context_plan(lambda args: PRContext(execution, resolve=resolve), action,
                        preflight=preflight, report=report)
