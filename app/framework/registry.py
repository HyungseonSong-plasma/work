# FileRank: C
"""Explicit registration for trusted CLI commands."""

import json
import re

from config import load_names
from libs.frame import Registry, select_registered, validate_unique

COMMANDS = Registry()


def register(name):
    """Register one command with a validated lifecycle plan."""
    def decorator(command):
        from app.framework.model import validate_command

        if not isinstance(name, str) or not name or name.startswith("-"):
            raise ValueError("Invalid command name.")
        return COMMANDS.add(name, command, duplicate=f"Duplicate command: {name}",
                            validate=validate_command)
    return decorator


def configured_commands():
    """Select only explicitly registered implementations named in configuration."""
    names = load_names("commands")
    selected = select_registered(COMMANDS, names, unknown="Unknown configured command.")
    from app.framework.model import validate_command

    for command in selected.values():
        validate_command(command)
    return selected


def workflow_commands():
    """Project the same command registry onto the restricted execution allowlist."""
    from app import commands  # Explicit trusted registrations, loaded before use.

    allowed = execution_ids()
    routes = {}
    for name, command in configured_commands().items():
        execution = command.workflow_execution
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
    if any(name not in routes for name in names):
        raise ValueError("Every execution must be a registered command.")
    validate_unique(names, "Duplicate execution is not allowed.")
    if {"pr_merge.py", "branch_delete.py"}.issubset(names):
        if names.index("pr_merge.py") > names.index("branch_delete.py"):
            raise ValueError("PR merge must precede branch deletion.")
    return names
