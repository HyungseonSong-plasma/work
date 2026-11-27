# FileRank: C
"""Standalone consumer contract for the installed framework; no GitHub operations."""

from pathlib import Path
import sys
import unittest

import work
from work.libs.frame import FrameContract
from work.libs.command import Command, CommandRegistry, local_plan
from work.libs.testing import TestSuite, SuiteRegistry


class LocalCommand(Command):
    help = "consumer fixture"
    plan = local_plan(lambda ctx, args: 17)


class LocalContract(TestSuite):
    def test_frame(self):
        def check(ctx):
            frame = FrameContract(("prepare", "action")).bind(
                prepare=lambda value: value + 2, action=lambda value: value * 3)
            self.assertEqual(frame.execute(4), 18)
        self.run_contract(check=check)

    def test_command_registry(self):
        def check(ctx):
            registry = CommandRegistry()
            registry.register("local")(LocalCommand)
            self.assertEqual(registry.configured(("local",))["local"].execute(None), 17)
        self.run_contract(check=check)


if __name__ == "__main__":
    assert Path(work.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
    registry = SuiteRegistry()
    registry.register("consumer")(LocalContract)
    suite = registry.build(("consumer",))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() and result.testsRun == 2 else 1)
