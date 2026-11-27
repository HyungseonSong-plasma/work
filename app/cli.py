# FileRank: C
"""One command-line entry point for the work execution system."""

import argparse
import sys
from urllib.error import HTTPError, URLError
from subprocess import SubprocessError

from app import commands
from scripts.execute import EXECUTIONS


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("trigger", help="Validate a PR comment and route it")
    execute = subparsers.add_parser("execute", help="Run validated execution stages")
    mode = execute.add_mutually_exclusive_group(required=True)
    mode.add_argument("--single", action="store_true")
    mode.add_argument("--serial-stage", type=int, choices=(1, 2))
    task = subparsers.add_parser("task", help="Run one registered task")
    task.add_argument("script", choices=sorted(EXECUTIONS))
    args = parser.parse_args(argv)
    try:
        if args.command == "trigger":
            return commands.trigger()
        if args.command == "execute":
            return commands.execute(args.single, args.serial_stage)
        return commands.task(args.script)
    except HTTPError as error:
        print(f"GitHub API request failed: HTTP {error.code}", file=sys.stderr)
    except (URLError, ValueError, KeyError, TypeError, OSError,
            SubprocessError) as error:
        print(f"{args.command}: operation not confirmed: {error}", file=sys.stderr)
    return 1
