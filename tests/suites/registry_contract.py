# FileRank: C
"""Tests of registry completeness and registration validation."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

from tests.framework.model import TestSuite
from tests.framework.registry import SUITES, build_suite, register
from tests.framework.validation import validate_method


@register("registry")
class RegistryContract(TestSuite):
    def test_manifest_order_and_count(self):
        class First(TestSuite):
            def test_one(self):
                def check(ctx):
                    pass
                self.run_contract(check=check)

        class Second(TestSuite):
            def test_two(self):
                def check(ctx):
                    pass
                self.run_contract(check=check)

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

    def test_contract_runner_result_scope_and_fresh_context(self):
        observed = []
        active = []

        @contextmanager
        def arrange(ctx):
            observed.append(ctx)
            active.append(ctx)
            try:
                yield
            finally:
                active.pop()

        def act(ctx):
            self.assertEqual(active, [ctx])
            return "result"

        def check(ctx, result):
            self.assertEqual(active, [ctx])
            self.assertEqual(result, "result")

        for _ in range(2):
            self.run_contract(act, check, arrange=arrange)
            self.assertEqual(active, [])
        self.assertIsNot(observed[0], observed[1])

    def test_contract_runner_expected_exception_is_action_only(self):
        error = ValueError("expected")
        act = Mock(side_effect=error)
        check = Mock()
        self.run_contract(act, check, raises=ValueError)
        act.assert_called_once()
        check.assert_called_once_with(act.call_args.args[0], error)

        for effect, expected in ((None, AssertionError), (TypeError("wrong"), TypeError)):
            with self.subTest(effect=effect):
                check.reset_mock()
                with self.assertRaises(expected):
                    self.run_contract(Mock(side_effect=effect), check, raises=ValueError)
                check.assert_not_called()

        @contextmanager
        def arrange(ctx):
            raise ValueError("setup")
            yield

        act.reset_mock()
        with self.assertRaisesRegex(ValueError, "setup"):
            self.run_contract(act, check, arrange=arrange, raises=ValueError)
        act.assert_not_called()
        check.assert_not_called()

        with self.assertRaisesRegex(ValueError, "check"):
            self.run_contract(Mock(side_effect=error), Mock(side_effect=ValueError("check")),
                              raises=ValueError)

    def test_contract_runner_cleans_scope_on_failure(self):
        active = []

        @contextmanager
        def arrange(ctx):
            active.append(ctx)
            try:
                yield
            finally:
                active.pop()

        for fail_in in ("act", "check"):
            with self.subTest(fail_in=fail_in):
                act = Mock(side_effect=RuntimeError("act") if fail_in == "act" else None)
                check = Mock(side_effect=AssertionError("check") if fail_in == "check" else None)
                with self.assertRaises((RuntimeError, AssertionError)):
                    self.run_contract(act, check, arrange=arrange)
                self.assertEqual(active, [])
                if fail_in == "act":
                    check.assert_not_called()

    def test_scenario_runner_order_shared_context_and_cleanup(self):
        observed = []

        @contextmanager
        def arrange(ctx):
            observed.append(("arrange", ctx))
            ctx.state = []
            try:
                yield
            finally:
                observed.append(("cleanup", ctx))

        def first(ctx):
            observed.append(("first", ctx))
            ctx.state.append(1)

        def second(ctx):
            observed.append(("second", ctx))
            ctx.state.append(2)

        def check(ctx):
            observed.append(("check", ctx))
            self.assertEqual(ctx.state, [1, 2])

        self.run_scenario((("first", first), ("second", second)), check, arrange=arrange)
        self.assertEqual([name for name, _ in observed],
                         ["arrange", "first", "second", "check", "cleanup"])
        self.assertTrue(all(ctx is observed[0][1] for _, ctx in observed))

    def test_scenario_runner_stops_and_names_failed_step(self):
        for error in (AssertionError("failed"), RuntimeError("error")):
            with self.subTest(error=type(error).__name__):
                active = []

                @contextmanager
                def arrange(ctx):
                    active.append(ctx)
                    try:
                        yield
                    finally:
                        active.pop()

                first, later, check = Mock(side_effect=error), Mock(), Mock()
                with self.assertRaises(type(error)) as caught:
                    self.run_scenario((("broken", first), ("later", later)),
                                      check, arrange=arrange)
                self.assertIn("Scenario step: broken", caught.exception.__notes__)
                first.assert_called_once()
                later.assert_not_called()
                check.assert_not_called()
                self.assertEqual(active, [])

    def test_runner_invalid_declarations_precede_callbacks(self):
        act, check, arrange = Mock(), Mock(), Mock()
        for bad_steps in ((), (("", act),), ((" ", act),), (("x",),),
                          (("x", None),), (("x", act), ("x", act))):
            with self.subTest(steps=bad_steps):
                self.assert_rejected(self.run_scenario, bad_steps, check, arrange=arrange)
        self.assert_rejected(self.run_scenario, (("x", act),), None, arrange=arrange)
        self.assert_rejected(self.run_contract, False, check, arrange=arrange)
        self.assert_rejected(self.run_contract, act, None, arrange=arrange)
        self.assert_rejected(self.run_contract, act, check, arrange=arrange, raises="error")
        self.assert_rejected(self.run_contract, act, check, arrange=False)
        act.assert_not_called()
        check.assert_not_called()
        arrange.assert_not_called()

    def test_runner_scope_cannot_silently_suppress_failure(self):
        @contextmanager
        def arrange(ctx):
            try:
                yield
            except RuntimeError:
                pass

        act, check = Mock(side_effect=RuntimeError("unexpected")), Mock()
        with self.assertRaisesRegex(AssertionError, "suppressed"):
            self.run_contract(act, check, arrange=arrange)
        check.assert_not_called()
        with self.assertRaisesRegex(AssertionError, "suppressed"):
            self.run_scenario((("broken", act),), check, arrange=arrange)
        check.assert_not_called()

    def test_compact_contract_runner_scope_and_fresh_context(self):
        contexts, active = [], []

        @contextmanager
        def arrange(ctx):
            active.append(ctx)
            try:
                yield
            finally:
                active.pop()

        def check(ctx):
            contexts.append(ctx)
            self.assertEqual(active, [ctx])

        for _ in range(2):
            self.run_contract(check=check, arrange=arrange)
            self.assertEqual(active, [])
        self.assertIsNot(contexts[0], contexts[1])
        with self.assertRaises(ValueError):
            self.run_contract(check=check, raises=ValueError)

    def test_matrix_validates_all_rows_before_callback(self):
        check = Mock()
        for rows in (None, ((" ", 1),), (("valid", 1), ("bad", 2, 3))):
            with self.subTest(rows=rows):
                callback = check if rows is None or rows[0][0] == " " else lambda ctx, value: check(value)
                self.assert_rejected(self.run_cases, rows, callback)
        self.assert_rejected(self.run_cases, (("valid", 1),), None)
        check.assert_not_called()

    def test_structure_validation_accepts_three_runner_forms(self):
        bodies = (
            "cases = ((\"a\", 1),)\n    def check(ctx, value):\n        pass\n    self.run_cases(cases, check)",
            "def check(ctx):\n        pass\n    self.run_contract(check=check)",
            "def act(ctx):\n        return 1\n    def check(ctx, result):\n        pass\n    self.run_contract(act, check)",
            "def first(ctx):\n        pass\n    def check(ctx):\n        pass\n    steps = ((\"first\", first),)\n    self.run_scenario(steps, check)",
        )
        for body in bodies:
            with self.subTest(body=body):
                validate_method("def test_example(self):\n    " + body)

    def test_structure_validation_rejects_direct_or_multiple_execution(self):
        valid = "def check(ctx):\n        pass\n    self.run_contract(check=check)"
        bodies = (
            "self.assertTrue(True)",
            "self.assertTrue(True)\n    " + valid,
            valid + "\n    self.run_contract(check=check)",
            "if True:\n        self.run_contract(check=check)",
            "def check(ctx):\n        self.run_contract(check=check)\n    self.run_contract(check=check)",
            "def check(ctx):\n        self.ctx.api()\n    self.run_contract(check=check)",
            "value = operation()\n    " + valid,
            "def unused(ctx):\n        pass\n    " + valid,
            "def check(ctx):\n        pass\n    self.run_cases(((\"x\",),), check)",
            "def check(ctx):\n        pass\n    self.run_contract(check=check, raises=ValueError)",
        )
        for body in bodies:
            with self.subTest(body=body):
                self.assert_rejected(validate_method, "def test_example(self):\n    " + body)

    def test_registry_rejects_unstructured_or_overridden_suite(self):
        class Direct(TestSuite):
            def test_direct(self):
                self.assertTrue(True)

        class Override(TestSuite):
            def run_contract(self, *args, **kwargs):
                pass

            def test_contract(self):
                def check(ctx):
                    pass
                self.run_contract(check=check)

        for case in (Direct, Override):
            with self.subTest(case=case.__name__):
                self.assert_rejected(build_suite, names=["example"], registered={"example": case})
                self.assert_rejected(build_suite, names=["registry"], registered={"registry": case})
