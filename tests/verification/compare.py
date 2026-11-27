# FileRank: C
"""Compare two explicitly trusted, clean post-Q1/Q2 repository snapshots."""

import argparse
from collections import Counter
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

if __package__:
    from ._snapshot_imports import layout
else:
    from _snapshot_imports import layout


HERE = Path(__file__).resolve().parent
RECORD_COUNT = 1697
SEMANTIC_COUNT = 29
TIMEOUT = 120


def run(command, root, env):
    result = subprocess.run(command, cwd=root, env=env, text=True,
                            capture_output=True, timeout=TIMEOUT)
    if result.returncode:
        raise ValueError(f"{command[0]} exited {result.returncode} in {root}:\n"
                         f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}")
    return result.stdout


def verify_snapshot(root, sha, env):
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Expected full lowercase snapshot commit SHA.")
    if Path(run(["git", "rev-parse", "--show-toplevel"], root, env).strip()).resolve() != root:
        raise ValueError(f"Not a repository root: {root}")
    if run(["git", "rev-parse", "HEAD"], root, env).strip() != sha:
        raise ValueError(f"Snapshot SHA mismatch: {root}")
    if run(["git", "status", "--porcelain", "--untracked-files=all"], root, env):
        raise ValueError(f"Snapshot must be clean: {root}")


def child_environment(root, home):
    # Do not propagate tokens, agent sockets, PYTHONPATH or ambient Git config.
    # This reduces accidental credential use; it is not a sandbox.
    return {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
            "LC_ALL": "C.UTF-8", "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))) if layout(root) == "src" else str(root), "PYTHONHASHSEED": "0",
            "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0"}


def observe(label, root, sha, home):
    env = child_environment(root, home)
    verify_snapshot(root, sha, env)
    python = [sys.executable, "-B"]
    run(python + ["-m", "work" if layout(root) == "src" else "app", "test"], root, env)
    ids = run(python + ["-c",
        'from tests import suites; from tests.wiring import build_suite; '
        'print("\\n".join(t.id() for t in build_suite()))'], root, env).splitlines()
    records = json.loads(run(python + [str(HERE / "probe.py")], root, env))
    semantic = run(python + [str(HERE / "semantic_probe.py")], root, env).splitlines()
    verify_snapshot(root, sha, env)
    print(f"{label}: {sha}, {len(ids)} test IDs (suite passed)", flush=True)
    return ids, records, semantic


def compare_ids(old, new):
    if not old or len(old) != len(set(old)) or len(new) != len(set(new)):
        raise ValueError("Missing or duplicate test IDs.")
    original = set(old)
    if [name for name in new if name in original] != old:
        raise ValueError("Original test IDs or relative order changed.")
    print(f"Original test IDs and order retained: {len(old)}; new: {len(new)-len(old)}")


def compare_records(old, new):
    if not isinstance(old, dict) or not isinstance(new, dict):
        raise ValueError("Expected named differential records.")
    if len(old) != RECORD_COUNT or old.keys() != new.keys():
        raise ValueError(f"Unexpected differential record coverage: {len(old)} / {len(new)}")
    differences = [name for name in old if old[name] != new[name]]
    print("Category counts:", dict(sorted(Counter(name.split(":")[0] for name in old).items())))
    print(f"Comparisons: {len(old)}; matches: {len(old)-len(differences)}; differences: {len(differences)}")
    if differences:
        for name in differences:
            print("DIFFERENCE", name, repr(old[name]), repr(new[name]))
        raise ValueError("Differential comparison failed.")


# D4 changes only the command's displayed program name and the reviewed child argv.
_CLI_KEYS = frozenset("cli:help:" + value for value in ("", "trigger", "execute", "merge", "delete", "test")) | frozenset(
    "cli:invalid:" + value for value in ("", "unknown", "execute", "delete/unknown", "execute/--serial-stage/3"))
_SEQUENCE_KEYS = frozenset("execution_sequence:" + value for value in
                           ("success", "positive_failure", "negative_failure", "first_stage", "second_stage"))


def compare_migration_records(old, new):
    """Check exact D4 deltas, then run the original strict equality gate."""
    if old.keys() != new.keys():
        raise ValueError("Unexpected migration observation coverage.")
    expected = deepcopy(old)
    for key in _CLI_KEYS:
        row = expected[key]
        if not any("python3 -m app" in row[field] for field in ("stdout", "stderr")):
            raise ValueError("Missing old CLI program name: " + key)
        for field in ("stdout", "stderr"):
            row[field] = row[field].replace("python3 -m app", "python -m work")
    for key in _SEQUENCE_KEYS:
        calls = expected[key]["trace"]
        if not calls:
            raise ValueError("Missing old subprocess trace: " + key)
        for call in calls:
            name, (argv, cwd_ok, check), kwargs = call
            if name != "run" or argv[:2] != ["-m", "app"] or cwd_ok is not True or check is not False or kwargs:
                raise ValueError("Unexpected old subprocess contract: " + key)
            call[1][0] = ["-E", "-s", "-m", "work", *argv[2:]]
    changed = {key for key in old if old[key] != new[key]}
    if changed != _CLI_KEYS | _SEQUENCE_KEYS:
        raise ValueError(f"Unexpected migration delta keys: {sorted(changed ^ (_CLI_KEYS | _SEQUENCE_KEYS))}")
    compare_records(expected, new)
    print(f"D4 exact intentional deltas: {len(changed)}; unchanged: {len(old)-len(changed)}")


def compare_semantic(old, new):
    def names(rows):
        return [line.split(" ", 1)[0] for line in rows if line.startswith(("Q1_", "Q2_"))]
    labels = names(old)
    if (len(labels) != SEMANTIC_COUNT or len(set(labels)) != SEMANTIC_COUNT
            or sum(name.startswith("Q1_") for name in labels) != 18
            or sum(name.startswith("Q2_") for name in labels) != 11):
        raise ValueError("Unexpected semantic observation coverage.")
    if old != new:
        raise ValueError("Semantic outcomes or observations changed.")
    print(f"Q1/Q2 semantic observations: {len(labels)}/{SEMANTIC_COUNT} matched")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-sha", required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    args = parser.parse_args(argv)
    baseline, candidate = args.baseline.resolve(), args.candidate.resolve()
    try:
        if not baseline.is_dir() or not candidate.is_dir() or baseline == candidate:
            raise ValueError("Provide two distinct existing repository roots.")
        with tempfile.TemporaryDirectory(prefix="work-verify-") as temp:
            home = Path(temp)
            # Validate both before executing either snapshot.
            verify_snapshot(baseline, args.baseline_sha, child_environment(baseline, home))
            verify_snapshot(candidate, args.candidate_sha, child_environment(candidate, home))
            first = observe("baseline", baseline, args.baseline_sha, home)
            second = observe("candidate", candidate, args.candidate_sha, home)
        compare_ids(first[0], second[0])
        if layout(baseline) != "src" and layout(candidate) == "src":
            compare_migration_records(first[1], second[1])
        else:
            compare_records(first[1], second[1])
        compare_semantic(first[2], second[2])
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"Verification failed: {error}", file=sys.stderr)
        return 1
    print("Verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
