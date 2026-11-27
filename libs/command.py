# FileRank: C
"""Domain-independent registered command plans and regulated CLI lifecycle."""

import argparse
from dataclasses import dataclass

from libs.frame import (FrameContract, Registry, select_registered,
                        validate_callback, validate_overrides, validate_unique)


@dataclass(frozen=True)
class CommandPlan:
    """Declarative execution contract; the runner owns its stage order."""

    prepare: object
    validate: object
    action: object
    report: object = None
    returns_status: bool = False

    def __post_init__(self):
        for callback, arity in ((self.prepare, 1), (self.validate, 2), (self.action, 2)):
            _validate_callback(callback, arity)
        if self.report is not None:
            _validate_callback(self.report, 2)
        if type(self.returns_status) is not bool:
            raise TypeError("Command status mode must be boolean.")


def _validate_callback(callback, arity):
    validate_callback(callback, arity, error_type=TypeError,
                      message="Invalid command lifecycle callback.")


def _identity(ctx, args):
    return ctx


class Command:
    """Registered implementations declare plans; they do not own the runner."""

    help = ""
    plan = None
    targets = ()

    @classmethod
    def bind(cls, subparsers, name):
        validate_command(cls)
        parser = subparsers.add_parser(name, help=cls.help)
        cls.configure(parser)
        if any(action.dest in ("command", "handler") for action in parser._actions):
            raise TypeError("Reserved command parser destination.")
        if any(name in parser._defaults for name in ("command", "handler")):
            raise TypeError("Reserved command parser default.")

    @staticmethod
    def configure(parser):
        pass

    @classmethod
    def execute(cls, args):
        validate_command(cls)
        if cls.targets:
            target = getattr(args, "target", None)
            if not isinstance(target, str) or target not in dict(cls.targets):
                raise ValueError("Unknown deletion target.")
            plan = dict(cls.targets)[target]
        else:
            plan = cls.plan
        return _COMMAND_FRAME.execute(_CommandRun(plan, args))


def validate_command(command):
    """Reject alternate registered execution entrypoints and malformed plans."""
    if not isinstance(command, type) or not issubclass(command, Command):
        raise TypeError("Command must extend Command model.")
    validate_overrides(command, Command, ("bind", "execute"), error_type=TypeError,
                       message="Command may not override framework {name}.", classmethods=True)
    _validate_callback(command.configure, 1)
    if not isinstance(command.help, str) or not command.help:
        raise TypeError("Command requires a help string.")
    targets = command.targets
    if not isinstance(targets, tuple):
        raise TypeError("Command targets must be an explicit tuple.")
    if targets:
        if command.plan is not None or any(
                not isinstance(row, tuple) or len(row) != 2
                or not isinstance(row[0], str) or not row[0]
                or type(row[1]) is not CommandPlan for row in targets):
            raise TypeError("Invalid targeted command plans.")
        names = [name for name, _ in targets]
        validate_unique(names, "Duplicate command target.", error_type=TypeError)
    elif type(command.plan) is not CommandPlan:
        raise TypeError("Command requires a lifecycle plan.")


def run_cli(prog, configured, argv=None, *, errors, handle_error):
    """Own parser binding and dispatch; handle only declared execution failures."""
    parser = argparse.ArgumentParser(prog=prog)
    subparsers = parser.add_subparsers(dest="command", required=True)
    registered = configured()
    for name, command in registered.items():
        command.bind(subparsers, name)
    args = parser.parse_args(argv)
    try:
        return registered[args.command].execute(args)
    except errors as error:
        return handle_error(args.command, error)


def local_plan(action):
    """Local commands do not require GitHub environment variables."""
    return CommandPlan(lambda args: None, _identity, action, returns_status=True)


@dataclass
class _CommandRun:
    """Per-invocation adapter; argument and report semantics stay in this library."""

    plan: CommandPlan
    args: object
    ctx: object = None
    result: object = None

    def prepare(self):
        self.ctx = self.plan.prepare(self.args)
        return self

    def validate(self):
        self.ctx = self.plan.validate(self.ctx, self.args)
        return self

    def action(self):
        self.result = self.plan.action(self.ctx, self.args)
        return self

    def report(self):
        if self.plan.report is not None:
            self.plan.report(self.ctx, self.result)
        return self.result if self.plan.returns_status else 0


_COMMAND_FRAME = FrameContract(("prepare", "validate", "action", "report")).bind(
    prepare=_CommandRun.prepare,
    validate=_CommandRun.validate,
    action=_CommandRun.action,
    report=_CommandRun.report,
)


class CommandRegistry(Registry):
    """Explicit command selection, independent of manifest and application loading."""

    def register(self, name):
        def decorator(command):
            if not isinstance(name, str) or not name or name.startswith("-"):
                raise ValueError("Invalid command name.")
            return self.add(name, command, duplicate=f"Duplicate command: {name}",
                            validate=validate_command)
        return decorator

    def configured(self, names):
        selected = select_registered(self, names, unknown="Unknown configured command.")
        for command in selected.values():
            validate_command(command)
        return selected
