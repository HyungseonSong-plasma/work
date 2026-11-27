# FileRank: C
"""Independent test lifecycle, structural validation and suite registry."""

import ast
import inspect
import textwrap
import unittest
from contextlib import nullcontext
from types import SimpleNamespace

from libs.frame import (Registry, select_registered, validate_callback,
                        validate_overrides, validate_unique)


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


# Structural regulation of ordinary test declarations.
RUNNERS = frozenset(("run_cases", "run_contract", "run_scenario"))
DECLARATION_CALLS = frozenset(("dict", "tuple", "range", "json.dumps"))
EXPRESSION_NODES = (ast.Constant, ast.Name, ast.Load, ast.Tuple, ast.List,
                    ast.Dict, ast.Set, ast.Attribute, ast.Call, ast.keyword,
                    ast.BinOp, ast.Add, ast.Mult, ast.UnaryOp, ast.USub, ast.UAdd)


def _name(node, expected):
    return isinstance(node, ast.Name) and node.id == expected


def _runner(node):
    return (isinstance(node, ast.Attribute) and _name(node.value, "self")
            and node.attr in RUNNERS)


def _declaration(node):
    """Allow data declarations, not arbitrary actions or assertions."""
    for part in ast.walk(node):
        if not isinstance(part, EXPRESSION_NODES):
            return False
        if isinstance(part, ast.Name) and part.id == "self":
            return False
        if isinstance(part, ast.Call):
            if ast.unparse(part.func) not in DECLARATION_CALLS:
                return False
    return True


def _method_body(source):
    """Validate the test envelope before inspecting individual declarations."""
    tree = ast.parse(textwrap.dedent(source))
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        raise ValueError("Expected one test method.")
    method = tree.body[0]
    if (method.decorator_list or len(method.args.args) != 1
            or method.args.args[0].arg != "self" or method.args.posonlyargs
            or method.args.kwonlyargs or method.args.vararg or method.args.kwarg
            or method.args.defaults):
        raise ValueError("Ordinary test requires undecorated test(self).")
    body = method.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body = body[1:]
    if (not body or not isinstance(body[-1], ast.Expr)
            or not isinstance(body[-1].value, ast.Call)
            or not _runner(body[-1].value.func)):
        raise ValueError("Test must end with one framework runner call.")
    if sum(_runner(node) for node in ast.walk(method)) != 1:
        raise ValueError("Exactly one runner reference is required.")
    if any(isinstance(node, ast.Attribute) and _name(node.value, "self")
           and node.attr == "ctx" for node in ast.walk(method)):
        raise ValueError("Use the runner-owned callback context.")
    return body


def _collect_declarations(nodes):
    """Collect named callbacks and data declarations; reject executable statements."""
    callbacks, declarations = {}, {}
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.FunctionDef):
            if (node.name in callbacks or node.name in declarations
                    or not node.args.args or node.args.args[0].arg != "ctx"
                    or node.args.defaults or node.args.kw_defaults
                    or node.args.posonlyargs or node.args.kwonlyargs
                    or node.args.vararg or node.args.kwarg or node.returns
                    or any(arg.annotation for arg in node.args.args)
                    or (node.decorator_list and
                        not (node.name == "arrange" and len(node.decorator_list) == 1
                             and _name(node.decorator_list[0], "contextmanager")))):
                raise ValueError("Invalid callback declaration.")
            callbacks[node.name] = node
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name) and _declaration(node.value)):
            name = node.targets[0].id
            if name in declarations or name in callbacks or name == "self":
                raise ValueError("Duplicate or invalid data declaration.")
            declarations[name] = node.value
        else:
            raise ValueError("Only data and callback declarations may precede the runner.")

    return callbacks, declarations


def _validate_runner_call(call, callbacks, declarations):
    """Check runner-specific argument grammar and exact callback ownership."""
    runner = call.func.attr
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if len(keywords) != len(call.keywords) or None in keywords:
        raise ValueError("Invalid runner keywords.")
    used = {"check"}
    if runner == "run_cases":
        _validate_cases_call(call, keywords, declarations)
    elif runner == "run_contract":
        _validate_contract_call(call, keywords, used)
    else:
        _validate_scenario_call(call, declarations, used)
    if "arrange" in keywords and runner != "run_cases":
        if not _name(keywords.pop("arrange"), "arrange"):
            raise ValueError("Use the named arrange callback.")
        used.add("arrange")
    if keywords or set(callbacks) != used:
        raise ValueError("Missing, unused or unexpected runner callbacks.")


def _validate_cases_call(call, keywords, declarations):
    if (len(call.args) != 2 or not _name(call.args[0], "cases")
            or not _name(call.args[1], "check") or keywords
            or "cases" not in declarations):
        raise ValueError("Use self.run_cases(cases, check).")


def _validate_contract_call(call, keywords, used):
    if not call.args and _name(keywords.get("check"), "check"):
        keywords.pop("check")
        if "raises" in keywords:
            raise ValueError("Expected exceptions require split contract form.")
    elif (len(call.args) == 2 and _name(call.args[0], "act")
          and _name(call.args[1], "check")):
        used.add("act")
    else:
        raise ValueError("Use run_contract(act, check) or run_contract(check=check).")
    if "raises" in keywords and not _declaration(keywords.pop("raises")):
        raise ValueError("Invalid expected exception declaration.")


def _validate_scenario_call(call, declarations, used):
    if (len(call.args) != 2 or not _name(call.args[0], "steps")
            or not _name(call.args[1], "check") or "steps" not in declarations):
        raise ValueError("Use self.run_scenario(steps, check).")
    steps = declarations["steps"]
    if not isinstance(steps, (ast.Tuple, ast.List)) or not steps.elts:
        raise ValueError("Scenario requires an explicit named step table.")
    for row in steps.elts:
        if (not isinstance(row, ast.Tuple) or len(row.elts) != 2
                or not isinstance(row.elts[0], ast.Constant)
                or not isinstance(row.elts[0].value, str)
                or not isinstance(row.elts[1], ast.Name)):
            raise ValueError("Invalid step declaration.")
        used.add(row.elts[1].id)


def validate_method(source):
    """Require one final runner call and only declarations before it."""
    body = _method_body(source)
    callbacks, declarations = _collect_declarations(body[:-1])
    _validate_runner_call(body[-1].value, callbacks, declarations)


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
