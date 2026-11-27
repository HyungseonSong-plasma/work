# FileRank: C
"""Common framework for explicitly registered application commands."""

from abc import ABC, abstractmethod
import os
from pathlib import Path


class Command(ABC):
    """Uniform CLI interface; commands without arguments use the default."""

    help = ""

    @staticmethod
    def configure(parser):
        pass

    @staticmethod
    @abstractmethod
    def execute(args):
        raise NotImplementedError


def summary(message):
    """Append a result to the current GitHub Actions job summary, if present."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(message)
