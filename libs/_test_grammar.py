# FileRank: C
"""Static test declaration grammar; no runner or suite-loading dependency."""

import ast
import textwrap
from types import MappingProxyType
from typing import NamedTuple


# Structural regulation of ordinary test declarations.
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


def _scenario_callbacks(steps):
    """Validate named step rows and return their required callback names."""
    if not isinstance(steps, (ast.Tuple, ast.List)) or not steps.elts:
        raise ValueError("Scenario requires an explicit named step table.")
    used = set()
    for row in steps.elts:
        if (not isinstance(row, ast.Tuple) or len(row.elts) != 2
                or not isinstance(row.elts[0], ast.Constant)
                or not isinstance(row.elts[0].value, str)
                or not isinstance(row.elts[1], ast.Name)):
            raise ValueError("Invalid step declaration.")
        used.add(row.elts[1].id)
    return used


class _RunnerForm(NamedTuple):
    """One accepted static call form; runtime runner semantics are independent."""

    positional: tuple
    callbacks: tuple
    data: str = ""
    check_keyword: bool = False
    optional: tuple = ()
    data_callbacks: object = None


# Canonical static grammar. Form selection does not execute a test callback.
_RUNNER_RULES = MappingProxyType({
    "run_cases": ("Use self.run_cases(cases, check).", (
        _RunnerForm(("cases", "check"), ("check",), data="cases"),
    )),
    "run_contract": ("Use run_contract(act, check) or run_contract(check=check).", (
        _RunnerForm((), ("check",), check_keyword=True, optional=("arrange",)),
        _RunnerForm(("act", "check"), ("act", "check"), optional=("raises", "arrange")),
    )),
    "run_scenario": ("Use self.run_scenario(steps, check).", (
        _RunnerForm(("steps", "check"), ("check",), data="steps",
                    optional=("arrange",), data_callbacks=_scenario_callbacks),
    )),
})
RUNNERS = frozenset(_RUNNER_RULES)


def _validate_runner_call(call, callbacks, declarations):
    """Apply the declared form, then consume keywords and check callback ownership."""
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    if len(keywords) != len(call.keywords) or None in keywords:
        raise ValueError("Invalid runner keywords.")
    message, forms = _RUNNER_RULES[call.func.attr]
    for form in forms:
        if (len(call.args) == len(form.positional)
                and all(_name(node, name) for node, name in zip(call.args, form.positional))
                and (not form.check_keyword or _name(keywords.get("check"), "check"))):
            break
    else:
        raise ValueError(message)
    if (form.data and form.data not in declarations) or (not form.optional and keywords):
        raise ValueError(message)

    used = set(form.callbacks)
    if form.check_keyword:
        keywords.pop("check")
        if "raises" in keywords:
            raise ValueError("Expected exceptions require split contract form.")
    if form.data_callbacks is not None:
        used.update(form.data_callbacks(declarations[form.data]))
    if "raises" in form.optional and "raises" in keywords:
        if not _declaration(keywords.pop("raises")):
            raise ValueError("Invalid expected exception declaration.")
    if "arrange" in form.optional and "arrange" in keywords:
        if not _name(keywords.pop("arrange"), "arrange"):
            raise ValueError("Use the named arrange callback.")
        used.add("arrange")
    if keywords or set(callbacks) != used:
        raise ValueError("Missing, unused or unexpected runner callbacks.")


def validate_method(source):
    """Require one final runner call and only declarations before it."""
    body = _method_body(source)
    callbacks, declarations = _collect_declarations(body[:-1])
    _validate_runner_call(body[-1].value, callbacks, declarations)
