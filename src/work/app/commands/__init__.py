# FileRank: C
"""Explicitly load trusted command modules; no filesystem discovery."""

from work.app.commands import trigger, execute, test, delete, merge

__all__ = ["trigger", "execute", "test", "delete", "merge"]
