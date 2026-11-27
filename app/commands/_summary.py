# FileRank: C
"""Shared GitHub Actions result reporting."""

import os
from pathlib import Path


def _summary(message):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(message)
