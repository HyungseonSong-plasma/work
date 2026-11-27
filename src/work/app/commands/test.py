# FileRank: C
"""Run the configured offline test suite through the application CLI."""

import unittest
from pathlib import Path

from work.app.wiring import register
from work.libs.command import Command, local_plan


def action(ctx, args):
    # Only the reviewed source checkout owns the offline test suite.
    source = Path(__file__).resolve().parents[3]
    root = source.parent
    if (source.name != "src" or Path.cwd().resolve() != root
            or not (root / "tests" / "__init__.py").is_file()
            or not (root / "pyproject.toml").is_file()):
        raise ValueError("Repository tests require a trusted source checkout.")
    # Load test implementations only for this command, not workflow execution.
    from tests import suites
    from tests.wiring import build_suite

    result = unittest.TextTestRunner(verbosity=2).run(build_suite())
    return 0 if result.wasSuccessful() else 1


@register("test")
class TestCommand(Command):
    help = "Run registered offline regression tests"
    workflow_execution = ()
    plan = local_plan(action)
