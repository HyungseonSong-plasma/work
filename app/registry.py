# FileRank: C
"""Explicit registration for trusted CLI commands."""

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
        COMMANDS[name] = command
        return command
    return decorator
