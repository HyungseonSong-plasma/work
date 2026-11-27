# FileRank: C
"""Independent tests of the comparison gates (not part of app test)."""

import contextlib
from copy import deepcopy
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.verification.compare import compare_ids, compare_records, compare_semantic, compare_migration_records
from tests.verification._snapshot_imports import namespace, library, layout


class ComparisonContract(unittest.TestCase):
    def test_snapshot_namespace_is_unambiguous(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                namespace(root)
            old = root / "libs"
            old.mkdir()
            with self.assertRaises(ValueError):
                namespace(root)
            (old / "__init__.py").touch()
            self.assertEqual(namespace(root), "libs")
            new = root / "work" / "libs"
            new.mkdir(parents=True)
            (new / "__init__.py").touch()
            (new.parent / "__init__.py").touch()
            with self.assertRaises(ValueError):
                namespace(root)
            (old / "__init__.py").unlink()
            old.rmdir()
            self.assertEqual(namespace(root), "work.libs")
            source = root / "src" / "work"
            source.parent.mkdir()
            new.parent.rename(source)
            self.assertEqual(layout(root), "src")
            self.assertEqual(namespace(root), "work.libs")
            (source / "__init__.py").unlink()
            with self.assertRaises(ValueError):
                namespace(root)
        with self.assertRaises(ValueError):
            library("arbitrary")

    def test_ids_allow_only_additions_without_reordering(self):
        with contextlib.redirect_stdout(io.StringIO()):
            compare_ids(["a", "b"], ["x", "a", "b", "y"])
        for new in (["b", "a"], ["a"], ["a", "a", "b"]):
            with self.subTest(new=new), self.assertRaises(ValueError):
                compare_ids(["a", "b"], new)

    def test_records_reject_missing_or_changed_evidence(self):
        old = {f"fixture:{i}": i for i in range(1697)}
        with contextlib.redirect_stdout(io.StringIO()):
            compare_records(old, dict(old))
            for new in ({}, dict(old, **{"fixture:1": -1})):
                with self.assertRaises(ValueError):
                    compare_records(old, new)

    def test_migration_accepts_only_exact_deltas(self):
        cli = ("cli:help:", "cli:help:trigger", "cli:help:execute",
               "cli:help:merge", "cli:help:delete", "cli:help:test",
               "cli:invalid:", "cli:invalid:unknown", "cli:invalid:execute",
               "cli:invalid:delete/unknown", "cli:invalid:execute/--serial-stage/3")
        sequences = ("execution_sequence:success", "execution_sequence:positive_failure",
                     "execution_sequence:negative_failure", "execution_sequence:first_stage",
                     "execution_sequence:second_stage")
        old = {f"fixture:{i}": i for i in range(1681)}
        for key in cli:
            old[key] = {"stdout": "usage: python3 -m app", "stderr": "", "exit": 0}
        for key in sequences:
            old[key] = {"trace": [["run", [["-m", "app", "merge"], True, False], {}]],
                        "value": 0}
        new = deepcopy(old)
        for key in cli:
            new[key]["stdout"] = "usage: python -m work"
        for key in sequences:
            new[key]["trace"][0][1][0] = ["-E", "-s", "-m", "work", "merge"]
        with contextlib.redirect_stdout(io.StringIO()):
            compare_migration_records(old, new)
            for kind in ("unrelated", "missing", "wrong_cli", "wrong_argv",
                         "wrong_cwd", "wrong_exit", "missing_delta"):
                bad = deepcopy(new)
                if kind == "unrelated":
                    bad["fixture:0"] = -1
                elif kind == "missing":
                    del bad["fixture:0"]
                elif kind == "wrong_cli":
                    bad[cli[0]]["stdout"] = "usage: other"
                elif kind == "wrong_argv":
                    bad[sequences[0]]["trace"][0][1][0][-1] = "delete"
                elif kind == "wrong_cwd":
                    bad[sequences[0]]["trace"][0][1][1] = False
                elif kind == "wrong_exit":
                    bad[cli[0]]["exit"] = 1
                else:
                    bad[cli[0]] = old[cli[0]]
                with self.subTest(kind=kind), self.assertRaises(ValueError):
                    compare_migration_records(old, bad)
            bad_old = deepcopy(old)
            bad_old[sequences[0]]["trace"][0][1][1] = False
            with self.assertRaises(ValueError):
                compare_migration_records(bad_old, new)

    def test_semantic_rejects_missing_duplicate_or_changed_evidence(self):
        rows = [f"Q1_{i} accepted" for i in range(18)] + [f"Q2_{i} accepted" for i in range(11)]
        with contextlib.redirect_stdout(io.StringIO()):
            compare_semantic(rows, list(rows))
            for other in (rows[:-1], [rows[0]] * 29, rows[:-1] + ["Q2_10 rejected"]):
                with self.assertRaises(ValueError):
                    compare_semantic(rows, other)
            with self.assertRaises(ValueError):
                compare_semantic(rows[:-1], rows[:-1])


if __name__ == "__main__":
    unittest.main()
