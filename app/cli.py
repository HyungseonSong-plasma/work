# FileRank: C
"""One command-line entry point for the work execution system."""

import argparse
import sys
from urllib.error import HTTPError, URLError
from subprocess import SubprocessError

from app import commands  # Load the explicitly registered command modules.
from app.framework.registry import configured_commands


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python3 -m app")
    subparsers = parser.add_subparsers(dest="command", required=True)
    registered = configured_commands()
    for name, command in registered.items():
        command.bind(subparsers, name)
    args = parser.parse_args(argv)
    try:
        return registered[args.command].execute(args)
    except HTTPError as error:
        print(f"GitHub API request failed: HTTP {error.code}", file=sys.stderr)
    except (URLError, ValueError, KeyError, TypeError, OSError,
            SubprocessError) as error:
        print(f"{args.command}: operation not confirmed: {error}", file=sys.stderr)
    return 1
