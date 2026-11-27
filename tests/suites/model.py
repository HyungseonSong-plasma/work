# FileRank: C
"""Common offline test-suite model and independent deterministic fixtures."""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

SHA = "a" * 40
PARAMS = json.dumps({"pr_number": 7, "expected_head_sha": SHA})
REPO = "example/work"
REF = "refs/heads/main"
ROOT = Path(__file__).resolve().parents[2]


class TestContext:
    """Fresh per-test context; no production policy or registry-derived expectations."""

    def cli_help(self, *args):
        return subprocess.run([sys.executable, "-m", "app", *args, "--help"],
                              cwd=ROOT, capture_output=True, text=True)

    def process(self, returncode=0):
        return Mock(return_value=SimpleNamespace(returncode=returncode))


class WorkflowTestContext(TestContext):
    """Independent workflow event and environment fixtures."""

    def environment(self, **changes):
        env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ATTEMPT": "1",
               "GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF,
               "EXECUTION_INPUTS": PARAMS, "GITHUB_SERVER_URL": "https://github.com"}
        env.update(changes)
        return env

    def patched_environment(self, **changes):
        return patch.dict(os.environ, self.environment(**changes), clear=True)

    def event(self, expression):
        return {
            "action": "created",
            "repository": {"full_name": REPO, "default_branch": "main", "owner": {"id": 1}},
            "comment": {"id": 12, "user": {"id": 1}, "author_association": "OWNER",
                        "body": "/execute " + json.dumps({
                            "execution": expression, "expected_head_sha": SHA})},
            "sender": {"id": 1},
            "issue": {"number": 7, "pull_request": {}},
        }


class ActionsTestContext(WorkflowTestContext):
    """Independent Actions metadata, mock transport and approval fixtures."""

    def __init__(self):
        self.repo = {"id": 1, "default_branch": "main"}
        self.run_data = {"id": 12, "repository": {"id": 1, "full_name": REPO},
                         "head_sha": SHA, "run_attempt": 1, "status": "completed",
                         "path": ".github/workflows/disposable.yml"}
        self.api = Mock(side_effect=self._response)
        self.remove = Mock()

    def _response(self, method, endpoint):
        return deepcopy(self.repo if endpoint == f"repos/{REPO}" else self.run_data)

    @property
    def parameters(self):
        return dict(api=self.api, remove=self.remove, repository=REPO,
                    run_ref=REF, run_id=12, expected_head_sha=SHA,
                    expected_run_attempt=1, current_run_id=13)

    @staticmethod
    def target(run_id=12):
        return {"run_id": run_id, "expected_head_sha": SHA, "expected_run_attempt": 1}

    @property
    def batch_parameters(self):
        return dict(api=self.api, remove=self.remove, repository=REPO,
                    run_ref=REF, current_run_id=13)

    def approval_event(self, bot=False):
        sender = {"id": 41898282, "login": "github-actions[bot]"} if bot else {"id": 1}
        return {"repository": {"full_name": REPO, "default_branch": "main",
                               "owner": {"id": 1}}, "sender": sender}

    @property
    def workflow_ref(self):
        return f"{REPO}/.github/workflows/actions_delete.yml@{REF}"

    def validate_context(self, event, repository, ref, actor_id, workflow_ref,
                         request_id="", source_pr="", inputs=None, api=None):
        # The production context is the system under test, never the source of fixtures.
        from app.commands.model import ActionsContext

        inputs = ({"run_id": "12", "expected_head_sha": SHA,
                   "expected_run_attempt": "1"} if inputs is None else inputs)
        args = SimpleNamespace(
            runs=inputs.get("runs", ""),
            run_id=int(inputs["run_id"]) if "run_id" in inputs else None,
            expected_head_sha=inputs.get("expected_head_sha"),
            expected_run_attempt=int(inputs["expected_run_attempt"])
            if "expected_run_attempt" in inputs else None,
            request_id=request_id, source_pr=source_pr)
        env = self.environment(GITHUB_REPOSITORY=repository, GITHUB_REF=ref,
                               GITHUB_ACTOR_ID=actor_id, GITHUB_WORKFLOW_REF=workflow_ref,
                               GITHUB_RUN_ID="13")
        env["GITHUB_API_URL"] = "https://api.github.com"
        ctx = ActionsContext(args, env=env, api=Mock() if api is None else api)
        with patch.object(ctx, "read_event", return_value=event):
            return ctx.validate()


class ConfigurationTestContext(TestContext):
    """Temporary configuration root; patches and files are always restored."""

    @contextmanager
    def registry_root(self, files=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in (files or {}).items():
                (root / name).write_text(content, encoding="utf-8")
            with patch("config.ROOT", root):
                yield root


class TestSuite(unittest.TestCase):
    """Common lifecycle and assertions; concrete suites own test expectations."""

    context_type = TestContext

    def setUp(self):
        self.ctx = self.context_type()

    def assert_rejected(self, operation, *args, **kwargs):
        with self.assertRaises(ValueError):
            operation(*args, **kwargs)

    def run_cases(self, rows, check):
        """Run explicitly named rows independently, reporting failures via subTest."""
        rows = tuple(rows)
        if not rows or any(not isinstance(row, tuple) or not row or
                           not isinstance(row[0], str) or not row[0] for row in rows):
            raise ValueError("Expected nonempty named case rows.")
        names = [row[0] for row in rows]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate case name.")
        for name, *values in rows:
            with self.subTest(case=name):
                check(self.context_type(), *values)
