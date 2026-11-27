# FileRank: C
"""Run the configured offline test suite through the application CLI."""

import unittest

from app.registry import register


@register("test")
class TestCommand:
    help = "Run registered offline regression tests"

    @staticmethod
    def configure(parser):
        pass

    @staticmethod
    def execute(args):
        # Load test implementations only for this command, not workflow execution.
        from tests import suites
        from tests.registry import build_suite

        result = unittest.TextTestRunner(verbosity=2).run(build_suite())
        return 0 if result.wasSuccessful() else 1
