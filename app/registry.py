# FileRank: C
"""Explicit registration for trusted CLI commands."""

import json
import re
from inspect import isabstract

from config import load_names

COMMANDS = {}


def register(name):
    """Register one command with a uniform configure/execute interface."""
    def decorator(command):
        from app.commands.model import Command

        if not isinstance(name, str) or not name or name.startswith("-"):
            raise ValueError("Invalid command name.")
        if name in COMMANDS:
            raise ValueError(f"Duplicate command: {name}")
        if not isinstance(command, type) or not issubclass(command, Command) or isabstract(command):
            raise TypeError("Command must extend Command model.")
        if not all(callable(getattr(command, attr, None))
                   for attr in ("configure", "execute")):
            raise TypeError("Command requires configure and execute methods.")
        if not isinstance(getattr(command, "help", None), str) or not command.help:
            raise TypeError("Command requires a help string.")
        COMMANDS[name] = command
        return command
    return decorator


def configured_commands():
    """Select only explicitly registered implementations named in configuration."""
    names = load_names("commands")
    if any(name not in COMMANDS for name in names):
        raise ValueError("Unknown configured command.")
    return {name: COMMANDS[name] for name in names}


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
    if len(names) != len(set(names)):
        raise ValueError("Duplicate execution is not allowed.")
    if {"pr_merge.py", "branch_delete.py"}.issubset(names):
        if names.index("pr_merge.py") > names.index("branch_delete.py"):
            raise ValueError("PR merge must precede branch deletion.")
    return names
