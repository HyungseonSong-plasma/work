# FileRank: C
"""Common offline test-suite model and shared deterministic fixtures."""

import json
import unittest
from pathlib import Path

SHA = "a" * 40
PARAMS = json.dumps({"pr_number": 7, "expected_head_sha": SHA})
REPO = "example/work"
REF = "refs/heads/main"
ROOT = Path(__file__).resolve().parents[2]


def event(expression):
    return {
        "action": "created",
        "repository": {"full_name": REPO, "default_branch": "main", "owner": {"id": 1}},
        "comment": {"id": 12, "user": {"id": 1}, "author_association": "OWNER",
                    "body": "/execute " + json.dumps({
                        "execution": expression, "expected_head_sha": SHA})},
        "sender": {"id": 1},
        "issue": {"number": 7, "pull_request": {}},
    }


class TestSuite(unittest.TestCase):
    """Common contract-test helpers; all external operations are mocked."""

    def assert_rejected(self, operation, *args, **kwargs):
        with self.assertRaises(ValueError):
            operation(*args, **kwargs)
