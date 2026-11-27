# FileRank: C
"""Test lifecycle, suite registry and static grammar bindings."""

import inspect
import unittest
from contextlib import nullcontext
from types import SimpleNamespace

from libs.frame import (Registry, select_registered, validate_callback,
                        validate_overrides, validate_unique)
from libs._test_grammar import (DECLARATION_CALLS, EXPRESSION_NODES, RUNNERS,
                               validate_method)


def _run_scoped(suite, arrange, kind, execute):
    """Own context creation and scope without changing exception propagation."""
    ctx = suite.context_type()
    completed = False
    with (nullcontext() if arrange is None else arrange(ctx)):
        execute(ctx)
        completed = True
    suite.assertTrue(completed, f"{kind} scope suppressed a failure.")


class TestSuite(unittest.TestCase):
    """Common lifecycle and assertions; concrete suites own test expectations."""

    context_type = SimpleNamespace

    def setUp(self):
        self.ctx = self.context_type()

    def assert_rejected(self, operation, *args, **kwargs):
        with self.assertRaises(ValueError):
            operation(*args, **kwargs)

    def run_cases(self, rows, check):
        """Run explicitly named rows independently, reporting failures via subTest."""
        try:
            rows = tuple(rows)
        except TypeError as error:
            raise ValueError("Expected named case rows.") from error
        self._validate_callbacks(check)
        if not rows or any(not isinstance(row, tuple) or not row or
                           not isinstance(row[0], str) or not row[0].strip() for row in rows):
            raise ValueError("Expected nonempty named case rows.")
        names = [row[0] for row in rows]
        validate_unique(names, "Duplicate case name.")
        for _, *values in rows:
            self._validate_arity(check, 1 + len(values))
        for name, *values in rows:
            with self.subTest(case=name):
                check(self.context_type(), *values)

    def run_contract(self, act=None, check=None, *, arrange=None, raises=None):
        """Run one action and its checks in a fresh, optionally scoped context.

        An expected exception applies only to act, never setup or check.
        Arrange, when supplied, returns a non-suppressing context manager.
        """
        # Compact form keeps a cohesive operation and its assertions in check(ctx).
        # Use split form when action/result or expected-exception handling is useful.
        if act is None:
            self._validate_callbacks(check, arrange=arrange)
            if raises is not None:
                raise ValueError("Expected exceptions require a separate action.")
            self._validate_arity(check, 1)
        else:
            self._validate_callbacks(act, check, arrange=arrange)
            self._validate_arity(act, 1)
            self._validate_arity(check, 2)
        if arrange is not None:
            self._validate_arity(arrange, 1)
        if raises is not None and (
                not isinstance(raises, type) or not issubclass(raises, Exception)):
            raise ValueError("Expected an exception class.")
        def execute(ctx):
            if act is None:
                check(ctx)
            else:
                if raises is None:
                    result = act(ctx)
                else:
                    with self.assertRaises(raises) as error:
                        act(ctx)
                    result = error.exception
                check(ctx, result)

        _run_scoped(self, arrange, "Contract", execute)

    def run_scenario(self, steps, check, *, arrange=None):
        """Run ordered named steps and final checks in one fresh context.

        Stop immediately on unexpected failure; annotate the failing step
        without swallowing it so that the surrounding scope is unwound.
        """
        self._validate_callbacks(check, arrange=arrange)
        self._validate_arity(check, 1)
        if arrange is not None:
            self._validate_arity(arrange, 1)
        try:
            steps = tuple(steps)
        except TypeError as error:
            raise ValueError("Expected named scenario steps.") from error
        if not steps or any(
                not isinstance(step, tuple) or len(step) != 2
                or not isinstance(step[0], str) or not step[0].strip()
                or not callable(step[1]) for step in steps):
            raise ValueError("Expected nonempty named callable steps.")
        names = [name for name, _ in steps]
        validate_unique(names, "Duplicate scenario step name.")
        for _, step in steps:
            self._validate_arity(step, 1)
        def execute(ctx):
            for name, step in steps:
                try:
                    step(ctx)
                except Exception as error:
                    error.add_note(f"Scenario step: {name}")
                    raise
            check(ctx)

        _run_scoped(self, arrange, "Scenario", execute)

    @staticmethod
    def _validate_callbacks(*callbacks, arrange=None):
        if not all(callable(callback) for callback in callbacks) or (
                arrange is not None and not callable(arrange)):
            raise ValueError("Expected callable runner callbacks.")

    @staticmethod
    def _validate_arity(callback, count):
        validate_callback(callback, count, error_type=ValueError,
                          message="Invalid runner callback signature.")


def validate_suite(case):
    """Check actual loaded methods and prohibit replacing framework lifecycle."""
    if not isinstance(case, type) or not issubclass(case, TestSuite):
        raise ValueError("Expected TestSuite implementation.")
    validate_overrides(case, TestSuite,
                       (*RUNNERS, "run", "__call__", "setUp", "tearDown", "_callSetUp",
                        "_callTestMethod", "_callTearDown", "_callCleanup", "doCleanups",
                        "_validate_callbacks", "_validate_arity"),
                       error_type=ValueError,
                       message=case.__name__ + ": framework lifecycle override: {name}")
    names = unittest.defaultTestLoader.getTestCaseNames(case)
    for name in names:
        try:
            validate_method(inspect.getsource(getattr(case, name)))
        except (OSError, TypeError, SyntaxError, ValueError) as error:
            raise ValueError(f"{case.__name__}.{name}: {error}") from error
    return tuple(names)


class SuiteRegistry(Registry):
    """Explicit registration and complete, ordered suite loading."""

    def register(self, name):
        def decorator(case):
            if not isinstance(name, str) or not name:
                raise ValueError("Invalid suite name.")

            def validate(value):
                if not isinstance(value, type) or not issubclass(value, TestSuite):
                    raise TypeError("Suite must extend TestSuite model.")

            return self.add(name, case, duplicate=f"Duplicate test suite: {name}",
                            validate=validate)
        return decorator

    def build(self, names, loader=None, registered=None, *, self_test=None):
        """Only an explicitly supplied exact (name, class) pair may bypass AST checks."""
        loader = unittest.defaultTestLoader if loader is None else loader
        names = tuple(names)
        registered = self if registered is None else registered
        if not names:
            raise ValueError("Missing or duplicate test suites.")
        validate_unique(names, "Missing or duplicate test suites.")
        selected = select_registered(registered, names,
                                     unknown="Test manifest and registered suites do not match.",
                                     complete=True)
        suite = unittest.TestSuite()
        for name, case in selected.items():
            framework_test = (self_test is not None and name == self_test[0]
                              and case is self_test[1])
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
