# FileRank: C
"""Dispatch an explicitly registered script from the trusted checkout."""

import json
import os
import subprocess
import sys
from pathlib import Path

# Adding a script here grants it the workflow's permissions.
EXECUTIONS = frozenset({"pr_merge.py"})


def resolve_execution(name, parameters):
    if name not in EXECUTIONS:
        raise ValueError("Execution is not registered.")
    if not isinstance(json.loads(parameters), dict):
        raise ValueError("Parameters must be a JSON object.")
    directory = Path(__file__).resolve().parent
    script = directory / name
    if script.is_symlink() or not script.is_file():
        raise ValueError("Registered script must be a regular file.")
    return script


def main():
    try:
        script = resolve_execution(
            os.environ["EXECUTION"], os.environ["EXECUTION_INPUTS"]
        )
    except (KeyError, ValueError) as error:
        print(f"Invalid execution request: {error}", file=sys.stderr)
        return 1

    # No shell interpolation or evaluation of submitted source code.
    return subprocess.run([sys.executable, str(script)], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
