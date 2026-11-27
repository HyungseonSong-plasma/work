# FileRank: C
"""One command-line entry point for the work execution system."""

import sys
from urllib.error import HTTPError, URLError
from subprocess import SubprocessError

from app import commands  # Load the explicitly registered command modules.
from app.wiring import configured_commands
from libs.command import run_cli


def _report_error(command, error):
    if isinstance(error, HTTPError):
        print(f"GitHub API request failed: HTTP {error.code}", file=sys.stderr)
    else:
        print(f"{command}: operation not confirmed: {error}", file=sys.stderr)
    return 1


def main(argv=None):
    return run_cli("python3 -m app", configured_commands, argv,
                   errors=(URLError, ValueError, KeyError, TypeError, OSError, SubprocessError),
                   handle_error=_report_error)
