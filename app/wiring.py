# FileRank: C
"""Trusted project wiring: command manifest and workflow execution allowlist."""

import json
import re
from functools import partial

from config import load_names
from libs.command import CommandRegistry
from libs.workflow import (context_plan, pr_plan as workflow_pr_plan,
                           require_execution_membership)
from libs.frame import validate_unique

COMMANDS = CommandRegistry()
register = COMMANDS.register


def configured_commands():
    return COMMANDS.configured(load_names("commands"))


def workflow_commands():
    """Project the same command registry onto the restricted execution allowlist."""
    from app import commands  # Explicit trusted registrations, loaded before use.

    allowed = execution_ids()
    routes = {}
    for name, command in configured_commands().items():
        execution = getattr(command, "workflow_execution", ())
        if not isinstance(execution, tuple) or any(
                not isinstance(value, str) or not value for value in execution):
            raise ValueError("Invalid command execution binding.")
        if not execution:
            continue
        identifier, *arguments = execution
        if identifier not in allowed or identifier in routes:
            raise ValueError("Unknown or duplicate command execution binding.")
        routes[identifier] = (name, *arguments)
    if set(routes) != allowed:
        raise ValueError("Missing registered command execution binding.")
    return routes


def execution_ids():
    """Legacy wire identifiers, not paths or importable scripts."""
    names = frozenset(load_names("executions"))
    if any(not re.fullmatch(r"[A-Za-z0-9_]+\.py", name) for name in names):
        raise ValueError("Invalid execution identifier.")
    return names


def resolve_execution(expression, parameters):
    """Resolve only registered identifiers; no file lookup or dynamic import."""
    if not isinstance(json.loads(parameters), dict):
        raise ValueError("Parameters must be a JSON object.")
    if not isinstance(expression, str):
        raise ValueError("Expected an execution string.")
    names = tuple(name.strip() for name in expression.split(" - "))
    routes = workflow_commands()
    require_execution_membership(names, routes,
                                 unknown="Every execution must be a registered command.")
    validate_unique(names, "Duplicate execution is not allowed.")
    if {"pr_merge.py", "branch_delete.py"}.issubset(names):
        if names.index("pr_merge.py") > names.index("branch_delete.py"):
            raise ValueError("PR merge must precede branch deletion.")
    return names


# Bind project-specific policy to the reusable PR context factory.
pr_plan = partial(workflow_pr_plan, resolve=resolve_execution)


def actions_plan(action):
    """Connect the dedicated Actions approval context to the command lifecycle."""
    def prepare(args):
        from github.actions import ActionsContext
        return ActionsContext(args)

    return context_plan(prepare, action)
