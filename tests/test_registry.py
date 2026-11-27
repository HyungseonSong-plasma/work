# FileRank: C
"""Single unittest discovery entry point for the JSON test manifest."""

import unittest

from tests import suites  # Register trusted TestCase classes.
from tests.registry import build_suite


def load_tests(loader, standard_tests, pattern):
    return build_suite(loader)


if __name__ == "__main__":
    unittest.main()
