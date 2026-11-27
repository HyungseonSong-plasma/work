# FileRank: C
"""Shared framework mechanics; domain policies belong to their callers."""

from dataclasses import dataclass
from inspect import signature


class Registry(dict):
    """Ordered explicit registration with validation before insertion."""

    def add(self, key, value, *, duplicate, validate=None):
        if key in self:
            raise ValueError(duplicate)
        if validate is not None:
            validate(value)
        self[key] = value
        return value

    def resolve(self, key, *, unknown):
        if key not in self:
            raise ValueError(unknown)
        return self[key]


def validate_unique(values, message, *, error_type=ValueError):
    """Require unique hashable values without sorting or normalization."""
    if len(values) != len(set(values)):
        raise error_type(message)


def select_registered(registry, names, *, unknown, complete=False):
    """Select in manifest order; completeness is a caller-owned policy."""
    if complete:
        if set(names) != set(registry):
            raise ValueError(unknown)
    elif any(name not in registry for name in names):
        raise ValueError(unknown)
    return {name: registry[name] for name in names}


def validate_callback(callback, count, *, error_type, message):
    """Require a callable that accepts the specified positional invocation."""
    try:
        if not callable(callback):
            raise TypeError("Not callable.")
        signature(callback).bind(*([None] * count))
    except (TypeError, ValueError) as error:
        raise error_type(message) from error


def validate_overrides(implementation, base, names, *, error_type, message,
                       classmethods=False):
    """Reject replacement of explicitly reserved framework methods."""
    for name in names:
        actual = getattr(implementation, name)
        expected = getattr(base, name)
        if classmethods:
            actual = getattr(actual, "__func__", None)
            expected = expected.__func__
        if actual is not expected:
            raise error_type(message.format(name=name))


@dataclass(frozen=True)
class FrameContract:
    """Trusted ordered stage declaration, independent of domain policy."""

    stages: tuple

    def __post_init__(self):
        if (type(self.stages) is not tuple or not self.stages
                or any(type(name) is not str or not name.isidentifier()
                       for name in self.stages)):
            raise TypeError("Expected a nonempty tuple of stage names.")
        validate_unique(self.stages, "Duplicate lifecycle stage.")

    def bind(self, **callbacks):
        """Bind exactly the declared callbacks, never their caller-supplied order."""
        if set(callbacks) != set(self.stages):
            raise TypeError("Lifecycle callbacks must match the declared stages.")
        return Frame(self, tuple(callbacks[name] for name in self.stages))


@dataclass(frozen=True)
class Frame:
    """A bound lifecycle; each callback accepts the prior stage's result."""

    contract: FrameContract
    callbacks: tuple

    def __init_subclass__(cls, **kwargs):
        raise TypeError("Frame execution is framework-owned; use composition.")

    def __post_init__(self):
        if (type(self.contract) is not FrameContract or type(self.callbacks) is not tuple
                or len(self.callbacks) != len(self.contract.stages)):
            raise TypeError("Invalid bound lifecycle.")
        for name, callback in zip(self.contract.stages, self.callbacks):
            validate_callback(callback, 1, error_type=TypeError,
                              message=f"Invalid lifecycle callback: {name}.")

    def execute(self, context):
        """Execute once in declared order; propagate failure before later stages."""
        for callback in self.callbacks:
            context = callback(context)
        return context
