# FileRank: C
"""Explicit registration for trusted CLI commands."""

from config import load_names

COMMANDS = {}


def register(name):
    """Register one command with a uniform configure/execute interface."""
    def decorator(command):
        if not isinstance(name, str) or not name or name.startswith("-"):
            raise ValueError("Invalid command name.")
        if name in COMMANDS:
            raise ValueError(f"Duplicate command: {name}")
        if not all(callable(getattr(command, attr, None))
                   for attr in ("configure", "execute")):
            raise TypeError("Command requires configure and execute methods.")
        if not isinstance(getattr(command, "help", None), str):
            raise TypeError("Command requires a help string.")
        COMMANDS[name] = command
        return command
    return decorator


def configured_commands():
    """Select only explicitly registered implementations named in JSON."""
    names = load_names("commands")
    if any(name not in COMMANDS for name in names):
        raise ValueError("Unknown configured command.")
    return {name: COMMANDS[name] for name in names}
