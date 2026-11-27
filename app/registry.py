# FileRank: C
"""Explicit registration for trusted CLI commands."""

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
    allowed = set(load_names("executions"))
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
