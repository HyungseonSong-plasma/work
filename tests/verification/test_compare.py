# FileRank: C
"""Independent tests of the comparison gates (not part of app test)."""

import contextlib
import io
import unittest

from tests.verification.compare import compare_ids, compare_records, compare_semantic


class ComparisonContract(unittest.TestCase):
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
