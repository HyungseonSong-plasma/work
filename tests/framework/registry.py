# FileRank: C
"""Explicit test-suite registry; never import modules named by configuration."""

import sys
import unittest

from tests.framework.validation import validate_suite

from config import load_names

SUITES = {}


def register(name):
    def decorator(case):
        if not isinstance(name, str) or not name:
            raise ValueError("Invalid suite name.")
        if name in SUITES:
            raise ValueError(f"Duplicate test suite: {name}")
        from tests.framework.model import TestSuite

        if not isinstance(case, type) or not issubclass(case, TestSuite):
            raise TypeError("Suite must extend TestSuite model.")
        SUITES[name] = case
        return case
    return decorator


def build_suite(loader=None, names=None, registered=None):
    """Require complete manifest coverage; never silently omit a suite."""
    loader = unittest.defaultTestLoader if loader is None else loader
    names = load_names("tests") if names is None else tuple(names)
    registered = SUITES if registered is None else registered
    if not names or len(names) != len(set(names)):
        raise ValueError("Missing or duplicate test suites.")
    if set(names) != set(registered):
        raise ValueError("Test manifest and registered suites do not match.")
    suite = unittest.TestSuite()
    for name in names:
        case = registered[name]
        # One explicitly identified framework self-test class, not a module-wide bypass.
        module = sys.modules.get("tests.suites.registry_contract")
        framework_test = (name == "registry" and module is not None
                          and case is getattr(module, "RegistryContract", None))
        expected = (tuple(unittest.defaultTestLoader.getTestCaseNames(case))
                    if framework_test else validate_suite(case))
        cases = loader.loadTestsFromTestCase(case)
        loaded = tuple(test._testMethodName for test in cases if type(test) is case)
        if loaded != expected or len(loaded) != cases.countTestCases():
            raise ValueError(f"Unexpected test loader coverage: {name}")
        if not cases.countTestCases():
            raise ValueError(f"Empty registered suite: {name}")
        suite.addTests(cases)
    return suite
