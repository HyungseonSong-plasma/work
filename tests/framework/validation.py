# FileRank: C
"""Structural policy for registered ordinary tests, not a security sandbox."""

import ast
import inspect
import textwrap
import unittest

from tests.framework.model import TestSuite
from libs.frame import validate_overrides


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


def validate_method(source):
    """Require one final runner call and only declarations before it."""
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
    callbacks, declarations = {}, {}
    for node in body[:-1]:
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

    call = body[-1].value
    runner = call.func.attr
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if len(keywords) != len(call.keywords) or None in keywords:
        raise ValueError("Invalid runner keywords.")
    used = {"check"}
    if runner == "run_cases":
        if (len(call.args) != 2 or not _name(call.args[0], "cases")
                or not _name(call.args[1], "check") or keywords
                or "cases" not in declarations):
            raise ValueError("Use self.run_cases(cases, check).")
    elif runner == "run_contract":
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
    else:
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
    if "arrange" in keywords and runner != "run_cases":
        if not _name(keywords.pop("arrange"), "arrange"):
            raise ValueError("Use the named arrange callback.")
        used.add("arrange")
    if keywords or set(callbacks) != used:
        raise ValueError("Missing, unused or unexpected runner callbacks.")


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
