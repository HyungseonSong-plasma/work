# FileRank: C
"""Explicit test-suite registry; never import modules named by configuration."""

import sys
import unittest

from tests.framework.validation import validate_suite

from config import load_names
from libs.frame import Registry, select_registered, validate_unique

SUITES = Registry()


def register(name):
    def decorator(case):
        if not isinstance(name, str) or not name:
            raise ValueError("Invalid suite name.")
        def validate(value):
            from tests.framework.model import TestSuite

            if not isinstance(value, type) or not issubclass(value, TestSuite):
                raise TypeError("Suite must extend TestSuite model.")

        return SUITES.add(name, case, duplicate=f"Duplicate test suite: {name}",
                          validate=validate)
    return decorator


def build_suite(loader=None, names=None, registered=None):
    """Require complete manifest coverage; never silently omit a suite."""
    loader = unittest.defaultTestLoader if loader is None else loader
    names = load_names("tests") if names is None else tuple(names)
    registered = SUITES if registered is None else registered
    if not names:
        raise ValueError("Missing or duplicate test suites.")
    validate_unique(names, "Missing or duplicate test suites.")
    selected = select_registered(registered, names,
                                 unknown="Test manifest and registered suites do not match.",
                                 complete=True)
    suite = unittest.TestSuite()
    for name, case in selected.items():
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
