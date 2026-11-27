# FileRank: C
"""Execute registered scripts serially from the trusted checkout."""

import json
import subprocess
import sys
from pathlib import Path

from config import load_names

# Configuration is an allowlist, not an implementation or permission grant.
EXECUTIONS = frozenset(load_names("executions"))
if any(Path(name).name != name or not name.endswith(".py") or
       not name[:-3].replace("_", "").isalnum() for name in EXECUTIONS):
    raise ValueError("Expected registered script filenames.")


def resolve_execution(expression, parameters):
    if not isinstance(json.loads(parameters), dict):
        raise ValueError("Parameters must be a JSON object.")

    names = [name.strip() for name in expression.split(" - ")]
    if any(name not in EXECUTIONS for name in names):
        raise ValueError("Every execution must be a registered script.")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate execution is not allowed.")
    if {"pr_merge.py", "branch_delete.py"}.issubset(names):
        if names.index("pr_merge.py") > names.index("branch_delete.py"):
            raise ValueError("PR merge must precede branch deletion.")

    directory = Path(__file__).resolve().parent
    scripts = []
    for name in names:
        script = directory / name
        if script.is_symlink() or not script.is_file():
            raise ValueError("Registered script must be a regular file.")
        scripts.append(script)
    return scripts


def run_execution(scripts, run=subprocess.run):
    """Run in input order; never start a later script after failure."""
    from app.registry import workflow_commands
    from app import commands  # Register trusted implementations.

    routes = workflow_commands()
    scripts = tuple(scripts)
    if any(script.name not in routes for script in scripts):
        raise ValueError("Unknown execution binding.")
    for script in scripts:
        print(f"Executing {script.name}", flush=True)
        result = run(
            [sys.executable, "-m", "app", *routes[script.name]],
            cwd=Path(__file__).resolve().parents[1], check=False,
        )
        if result.returncode != 0:
            print(f"Stopped at {script.name} (exit {result.returncode}).",
                  file=sys.stderr, flush=True)
            return result.returncode if result.returncode > 0 else 1
    return 0


def run_stage(scripts, stage, run=subprocess.run):
    """Run exactly one slot of a validated two-script serial request."""
    if len(scripts) != 2 or stage not in (1, 2):
        raise ValueError("Serial execution requires exactly two scripts.")
    return run_execution([scripts[stage - 1]], run=run)
