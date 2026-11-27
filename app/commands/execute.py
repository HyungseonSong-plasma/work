# FileRank: C
"""Execution command and its workflow adapter."""

import subprocess
import sys
from pathlib import Path

from app.wiring import register, resolve_execution, workflow_commands
from libs.command import Command
from libs.workflow import workflow_plan


def run_execution(executions, run=subprocess.run):
    """Run in input order; never start a later command after failure."""
    routes = workflow_commands()
    executions = tuple(executions)
    if not executions or any(name not in routes for name in executions):
        raise ValueError("Unknown execution binding.")
    for name in executions:
        print(f"Executing {name}", flush=True)
        result = run(
            [sys.executable, "-m", "app", *routes[name]],
            cwd=Path(__file__).resolve().parents[2], check=False,
        )
        if result.returncode != 0:
            print(f"Stopped at {name} (exit {result.returncode}).",
                  file=sys.stderr, flush=True)
            return result.returncode if result.returncode > 0 else 1
    return 0


def run_stage(executions, stage, run=subprocess.run):
    """Run exactly one slot of a validated two-command serial request."""
    if len(executions) != 2 or stage not in (1, 2):
        raise ValueError("Serial execution requires exactly two commands.")
    return run_execution([executions[stage - 1]], run=run)


def validate(ctx, args):
    executions = resolve_execution(ctx.execution, ctx.parameters)
    if args.single:
        if len(executions) != 1:
            raise ValueError("Single execution requires exactly one command.")
    elif len(executions) != 2 or args.serial_stage not in (1, 2):
        raise ValueError("Serial execution requires exactly two commands.")
    return executions


def action(executions, args):
    if args.single:
        return run_execution(executions)
    return run_stage(executions, args.serial_stage)

@register("execute")
class ExecuteCommand(Command):
    help = "Run validated execution stages"
    workflow_execution = ()
    plan = workflow_plan("workflow_dispatch", action, validate=validate, returns_status=True)

    @staticmethod
    def configure(parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--single", action="store_true")
        mode.add_argument("--serial-stage", type=int, choices=(1, 2))
