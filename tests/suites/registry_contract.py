# FileRank: C
"""Tests of registry completeness and registration validation."""

from unittest.mock import patch

from tests.framework.model import TestSuite
from tests.framework.registry import SUITES, build_suite, register


@register("registry")
class RegistryContract(TestSuite):
    def test_manifest_order_and_count(self):
        class First(TestSuite):
            def test_one(self):
                pass

        class Second(TestSuite):
            def test_two(self):
                pass

        suite = build_suite(names=["second", "first"],
                            registered={"first": First, "second": Second})
        self.assertEqual(suite.countTestCases(), 2)
        self.assertEqual([case.__class__ for case in suite],
                         [Second, First])

    def test_missing_unknown_and_duplicate_suites_rejected(self):
        cases = (
            ("empty_manifest", []),
            ("unknown", ["unknown"]),
            ("duplicate", ["cli", "cli"]),
            ("extra_unknown", ["cli", "unknown"]),
        )

        def check(ctx, names):
            self.assert_rejected(build_suite, names=names, registered={"cli": RegistryContract})

        self.run_cases(cases, check)

    def test_duplicate_registration_rejected(self):
        with self.assertRaises(ValueError):
            register("registry")(RegistryContract)

    def test_invalid_registration_rejected(self):
        with patch.dict(SUITES):
            with self.assertRaises(TypeError):
                register("invalid")(object)
            self.assertNotIn("invalid", SUITES)

    def test_empty_suite_rejected(self):
        class Empty(TestSuite):
            pass

        with self.assertRaises(ValueError):
            build_suite(names=["empty"], registered={"empty": Empty})

    def test_context_is_fresh_per_test_case(self):
        from tests.framework.model import ActionsTestContext
        class FixtureCase(TestSuite):
            context_type = ActionsTestContext

        first, second = FixtureCase(), FixtureCase()
        first.setUp()
        second.setUp()
        first.ctx.run_data["status"] = "changed"
        first.ctx.remove("example")
        self.assertEqual(second.ctx.run_data["status"], "completed")
        second.ctx.remove.assert_not_called()

    def test_workflow_fixture_environment_restores_on_error(self):
        import os
        from tests.framework.model import WorkflowTestContext
        before = dict(os.environ)
        ctx = WorkflowTestContext()
        with self.assertRaises(RuntimeError):
            with ctx.patched_environment(GITHUB_RUN_ATTEMPT="2"):
                self.assertEqual(os.environ["GITHUB_RUN_ATTEMPT"], "2")
                raise RuntimeError("test cleanup")
        self.assertEqual(dict(os.environ), before)

    def test_workflow_fixture_returns_independent_events(self):
        from tests.framework.model import WorkflowTestContext
        ctx = WorkflowTestContext()
        first = ctx.event("pr_merge.py")
        first["sender"]["id"] = 99
        self.assertEqual(ctx.event("pr_merge.py")["sender"]["id"], 1)

    def test_configuration_context_cleans_up_on_error(self):
        import config
        from tests.framework.model import ConfigurationTestContext
        original = config.ROOT
        with self.assertRaises(RuntimeError):
            with ConfigurationTestContext().registry_root() as root:
                self.assertEqual(config.ROOT, root)
                raise RuntimeError("test cleanup")
        self.assertEqual(config.ROOT, original)
        self.assertFalse(root.exists())

    def test_case_matrix_rejects_empty_invalid_or_duplicate_names(self):
        check = self.ctx.process()
        for rows in ((), ((),), (("", 1),), ((1, 2),),
                     (("same", 1), ("same", 2))):
            with self.subTest(rows=rows):
                self.assert_rejected(self.run_cases, rows, check)
        check.assert_not_called()

    def test_case_matrix_isolates_rows_and_reports_named_failures(self):
        import unittest
        from tests.framework.model import ActionsTestContext

        observed = []

        class MatrixFixture(TestSuite):
            context_type = ActionsTestContext

            def test_matrix(self):
                def check(ctx, fail):
                    observed.append(ctx)
                    self.assertEqual(ctx.run_data["status"], "completed")
                    ctx.run_data["status"] = "changed"
                    ctx.remove("example")
                    if fail:
                        self.fail("intentional row failure")

                self.run_cases((("first", True), ("second", False)), check)

        result = unittest.TestResult()
        MatrixFixture("test_matrix").run(result)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.errors), 0)
        self.assertIn("case='first'", str(result.failures[0][0]))
        self.assertEqual(len(observed), 2)
        self.assertIsNot(observed[0], observed[1])
        self.assertIsNot(observed[0].remove, observed[1].remove)
