# FileRank: C
"""Explicitly load trusted command modules; no filesystem discovery."""

from app.commands import trigger, execute, task, test, delete

__all__ = ["trigger", "execute", "task", "test", "delete"]
