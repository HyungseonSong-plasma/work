# FileRank: C
"""Trusted, version-controlled registry configuration."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def load_registry(name):
    if name not in {"commands", "executions", "workflows", "deletions"}:
        raise ValueError("Unknown registry file.")
    path = ROOT / (name + ".json")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Registry must be a regular file.")
    with path.open(encoding="utf-8") as stream:
        return json.load(stream, object_pairs_hook=_unique_object)


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
    # Only branch deletion has an implemented and authorized handler.
    if target not in {"branch"} or entries.get(target, {}).get("enabled") is not True:
        raise ValueError(f"Deletion target is disabled or unsupported: {target}")
