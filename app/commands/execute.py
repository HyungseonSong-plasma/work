# FileRank: C
"""Execution command and its workflow adapter."""

from app.registry import register
from app.commands.model import Command, Context
from scripts.execute import run_execution, run_stage


def execute(single, stage):
    ctx = Context().require_event("workflow_dispatch", fresh=True)
    scripts = ctx.resolve_execution()
    if single:
        if len(scripts) != 1:
            raise ValueError("Single execution requires exactly one script.")
        return run_execution(scripts)
    return run_stage(scripts, stage)


@register("execute")
class ExecuteCommand(Command):
    help = "Run validated execution stages"

    @staticmethod
    def configure(parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--single", action="store_true")
        mode.add_argument("--serial-stage", type=int, choices=(1, 2))

    @staticmethod
    def execute(args):
        return execute(args.single, args.serial_stage)
