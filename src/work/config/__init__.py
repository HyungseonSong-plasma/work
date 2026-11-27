# FileRank: C
"""Trusted, version-controlled registry configuration."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load_registry(name):
    if name not in {"commands", "executions", "workflows", "deletions", "tests", "actions_policy"}:
        raise ValueError("Unknown registry file.")
    path = ROOT / (name + ".toml")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Registry must be a regular file.")
    with path.open("rb") as stream:
        document = tomllib.load(stream)
    if set(document) != {name}:
        raise ValueError(f"Invalid {name} registry root.")
    return document[name]


def load_names(name):
    values = load_registry(name)
    if (not isinstance(values, list) or not values or
            any(not isinstance(value, str) or not value for value in values)):
        raise ValueError(f"Invalid {name} registry.")
    if len(values) != len(set(values)):
        raise ValueError(f"Duplicate {name} entry.")
    return tuple(values)


def require_deletion(target):
    entries = load_registry("deletions")
    if not isinstance(entries, dict):
        raise ValueError("Invalid deletion registry.")
    for entry in entries.values():
        if (not isinstance(entry, dict) or set(entry) != {"enabled", "permission"} or
                type(entry["enabled"]) is not bool or not isinstance(entry["permission"], str)):
            raise ValueError("Invalid deletion entry.")
    # Only explicitly implemented deletion targets can be enabled.
    if target not in {"branch", "actions"} or entries.get(target, {}).get("enabled") is not True:
        raise ValueError(f"Deletion target is disabled or unsupported: {target}")
