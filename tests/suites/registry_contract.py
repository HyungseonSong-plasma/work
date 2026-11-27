# FileRank: C
"""Tests of registry completeness and registration validation."""

from contextlib import contextmanager
from unittest.mock import Mock, patch

from work.libs.testing import TestSuite
from tests.fixtures import TestContext
from tests.wiring import SUITES, build_suite, register
from work.libs.testing import validate_method


@register("registry")
class RegistryContract(TestSuite):
    context_type = TestContext

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
        from tests.fixtures import ActionsTestContext
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
        from tests.fixtures import WorkflowTestContext
        before = dict(os.environ)
        ctx = WorkflowTestContext()
        with self.assertRaises(RuntimeError):
            with ctx.patched_environment(GITHUB_RUN_ATTEMPT="2"):
                self.assertEqual(os.environ["GITHUB_RUN_ATTEMPT"], "2")
                raise RuntimeError("test cleanup")
        self.assertEqual(dict(os.environ), before)

    def test_workflow_fixture_returns_independent_events(self):
        from tests.fixtures import WorkflowTestContext
        ctx = WorkflowTestContext()
        first = ctx.event("pr_merge.py")
        first["sender"]["id"] = 99
        self.assertEqual(ctx.event("pr_merge.py")["sender"]["id"], 1)

    def test_configuration_context_cleans_up_on_error(self):
        import config
        from tests.fixtures import ConfigurationTestContext
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
        from tests.fixtures import ActionsTestContext

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

    def test_static_grammar_bindings_preserve_identity(self):
        from work.libs import testing, _test_grammar
        for name in ("DECLARATION_CALLS", "EXPRESSION_NODES", "RUNNERS", "validate_method"):
            with self.subTest(binding=name):
                self.assertIs(getattr(testing, name), getattr(_test_grammar, name))

    def test_static_shape_does_not_replace_runtime_callback_validation(self):
        from work.libs.testing import TestSuite, validate_method
        from unittest.mock import Mock, patch

        callbacks = Mock()
        def check(ctx, unexpected):
            callbacks.check(ctx, unexpected)

        def act(ctx):
            callbacks.act(ctx)

        def arrange(ctx):
            callbacks.arrange(ctx)

        compact = "def check(ctx, unexpected):\n        pass\n"
        valid_act = "def act(ctx):\n        pass\n"
        valid_arrange = "def arrange(ctx):\n        pass\n"
        cases = (
            ("compact", compact + "    self.run_contract(check=check)",
             lambda: self.run_contract(check=check)),
            ("split", valid_act + "    def check(ctx):\n        pass\n    " +
             valid_arrange + "    self.run_contract(act, check, arrange=arrange)",
             lambda: self.run_contract(act, act, arrange=arrange)),
            ("cases", "cases = (('one',),)\n    " + compact +
             "    self.run_cases(cases, check)", lambda: self.run_cases((("one",),), check)),
            ("scenario", valid_act + "    " + compact + "    " +
             valid_arrange + "    steps = (('one', act),)\n    self.run_scenario(steps, check, arrange=arrange)",
             lambda: self.run_scenario((("one", act),), check, arrange=arrange)),
        )
        for name, body, run in cases:
            with self.subTest(form=name):
                self.assertIsNone(validate_method("def test_example(self):\n    " + body))
                with patch.object(TestSuite, "context_type", Mock()) as context:
                    with self.assertRaisesRegex(ValueError, "Invalid runner callback signature"):
                        run()
                    context.assert_not_called()
                self.assertEqual(callbacks.mock_calls, [])

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

    def test_runner_grammar_preserves_form_and_error_precedence(self):
        from work.libs.testing import RUNNERS

        self.assertEqual(RUNNERS, frozenset(("run_cases", "run_contract", "run_scenario")))
        compact = "def check(ctx):\n    pass\n"
        split = "def act(ctx):\n    pass\ndef check(ctx, result):\n    pass\n"
        scenario = "def first(ctx):\n    pass\ndef check(ctx):\n    pass\n"
        arrange = "def arrange(ctx):\n    pass\n"
        cases = "cases = (('one', 1),)\ndef check(ctx, value):\n    pass\n"
        valid = (
            cases + "self.run_cases(cases, check)",
            compact + "self.run_contract(check=check)",
            arrange + compact + "self.run_contract(check=check, arrange=arrange)",
            split + "self.run_contract(act, check, raises=ValueError)",
            arrange + split + "self.run_contract(act, check, arrange=arrange, raises=ValueError)",
            scenario + "steps = (('first', first),)\nself.run_scenario(steps, check)",
            arrange + scenario + "steps = (('first', first),)\nself.run_scenario(steps, check, arrange=arrange)",
        )

        def source(body):
            return "def test_example(self):\n" + "\n".join("    " + line for line in body.splitlines())

        for body in valid:
            with self.subTest(body=body):
                self.assertIsNone(validate_method(source(body)))
        invalid = (
            (compact + "self.run_contract(check=check, check=check)", "Invalid runner keywords."),
            (compact + "self.run_contract(check=check, **other)", "Invalid runner keywords."),
            (compact + "self.run_contract(check=check, raises=bad(), arrange=wrong)", "Expected exceptions require split contract form."),
            (split + "self.run_contract(act, check, raises=bad(), arrange=wrong)", "Invalid expected exception declaration."),
            (compact + "self.run_contract(check=check, arrange=wrong, other=1)", "Use the named arrange callback."),
            (cases + "self.run_cases(cases, check, arrange=wrong)", "Use self.run_cases(cases, check)."),
            (compact + "self.run_cases(cases, check)", "Use self.run_cases(cases, check)."),
            (scenario + "steps = ()\nself.run_scenario(steps, check, arrange=wrong)", "Scenario requires an explicit named step table."),
            (scenario + "steps = (('first', 1),)\nself.run_scenario(steps, check, arrange=wrong)", "Invalid step declaration."),
            (scenario + "steps = (('first', first),)\nself.run_scenario(steps, check, raises=ValueError)", "Missing, unused or unexpected runner callbacks."),
            (arrange + compact + "self.run_contract(check=check)", "Missing, unused or unexpected runner callbacks."),
            (compact + "self.run_contract(check=wrong, raises=bad())", "Use run_contract(act, check) or run_contract(check=check)."),
            ("bad = print('not executed')\n" + compact + "self.run_contract(check=check, raises=bad())", "Only data and callback declarations may precede the runner."),
        )
        for body, expected in invalid:
            with self.subTest(body=body):
                with self.assertRaises(ValueError) as error:
                    validate_method(source(body))
                self.assertEqual(str(error.exception), expected)

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

    def test_shared_registry_rejects_duplicate_before_validation(self):
        from work.libs.frame import Registry
        registry = Registry()
        validator = Mock()
        first = object()
        self.assertIs(registry.add("first", first, duplicate="duplicate", validate=validator), first)
        validator.assert_called_once_with(first)
        validator.reset_mock()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            registry.add("first", object(), duplicate="duplicate", validate=validator)
        validator.assert_not_called()
        self.assertIs(registry.resolve("first", unknown="unknown"), first)
        with self.assertRaisesRegex(ValueError, "unknown"):
            registry.resolve("missing", unknown="unknown")
        validator.side_effect = TypeError("invalid")
        with self.assertRaisesRegex(TypeError, "invalid"):
            registry.add("second", object(), duplicate="duplicate", validate=validator)
        self.assertEqual(list(registry), ["first"])
        with patch.dict(registry, {"temporary": object()}):
            self.assertEqual(list(registry), ["first", "temporary"])
        self.assertEqual(list(registry), ["first"])

    def test_shared_registry_selection_preserves_distinct_policies(self):
        from work.libs.frame import Registry, select_registered, validate_unique
        registry = Registry(first=1, second=2)
        self.assertEqual(list(select_registered(registry, ("second", "first"),
                                               unknown="unknown", complete=True).items()),
                         [("second", 2), ("first", 1)])
        self.assertEqual(select_registered(registry, ("second",), unknown="unknown"),
                         {"second": 2})
        for names, complete in ((("missing",), False), (("first",), True),
                                (("first", "second", "missing"), True)):
            with self.subTest(names=names, complete=complete):
                with self.assertRaisesRegex(ValueError, "unknown"):
                    select_registered(registry, names, unknown="unknown", complete=complete)
        validate_unique(("first", "second"), "duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_unique(("first", "first"), "duplicate")

    def test_shared_callback_validation_preserves_caller_errors(self):
        from work.libs.frame import validate_callback
        for callback in (None, lambda: None, lambda x, y: None):
            for error_type in (TypeError, ValueError):
                with self.subTest(callback=callback, error=error_type):
                    with self.assertRaisesRegex(error_type, "signature"):
                        validate_callback(callback, 1, error_type=error_type, message="signature")
        for callback in (lambda x: None, lambda *args: None, lambda x, y=1: None):
            validate_callback(callback, 1, error_type=ValueError, message="signature")

    def test_shared_override_validation_handles_class_and_instance_methods(self):
        from work.libs.frame import validate_overrides

        class Base:
            @classmethod
            def execute(cls):
                pass

            def run(self):
                pass

        class Inherited(Base):
            pass

        class Changed(Base):
            @classmethod
            def execute(cls):
                pass

            def run(self):
                pass

        for name, classmethods in (("execute", True), ("run", False)):
            validate_overrides(Inherited, Base, (name,), error_type=TypeError,
                               message="override {name}", classmethods=classmethods)
            with self.assertRaisesRegex(TypeError, "override " + name):
                validate_overrides(Changed, Base, (name,), error_type=TypeError,
                                   message="override {name}", classmethods=classmethods)

    def test_shared_frame_import_is_domain_independent(self):
        from tests.fixtures import import_probe
        result = import_probe(("work.libs.frame",),
                              ("app", "tests", "github", "config"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_frame_contract_rejects_invalid_declarations(self):
        from work.libs.frame import FrameContract
        for stages in ([], (), ("",), ("not a name",), ("prepare", 1)):
            with self.subTest(stages=stages):
                with self.assertRaises(TypeError):
                    FrameContract(stages)
        with self.assertRaisesRegex(ValueError, "Duplicate lifecycle stage"):
            FrameContract(("prepare", "prepare"))

    def test_frame_binding_requires_exact_callbacks_before_execution(self):
        from work.libs.frame import FrameContract
        contract = FrameContract(("prepare", "mutate"))
        prepare = Mock()
        for callbacks in ({"prepare": prepare}, {"prepare": prepare, "mutate": None},
                          {"prepare": prepare, "mutate": lambda: None},
                          {"prepare": prepare, "mutate": lambda ctx: ctx, "extra": prepare}):
            with self.subTest(callbacks=callbacks):
                with self.assertRaises(TypeError):
                    contract.bind(**callbacks)
        prepare.assert_not_called()

    def test_frame_order_is_contract_owned_and_threads_results(self):
        from work.libs.frame import FrameContract
        observed = Mock()
        prepare = Mock(side_effect=lambda ctx: ctx + 1)
        validate = Mock(side_effect=lambda ctx: ctx * 2)
        mutate = Mock(side_effect=lambda ctx: str(ctx))
        for name, callback in (("prepare", prepare), ("validate", validate), ("mutate", mutate)):
            observed.attach_mock(callback, name)
        frame = FrameContract(("prepare", "validate", "mutate")).bind(
            mutate=mutate, prepare=prepare, validate=validate)
        self.assertEqual(frame.execute(3), "8")
        from unittest.mock import call
        self.assertEqual(observed.mock_calls, [call.prepare(3), call.validate(4), call.mutate(8)])

    def test_frame_stops_at_every_failed_stage(self):
        from work.libs.frame import FrameContract
        names = ("prepare", "review", "validate", "mutate", "confirm")
        for failure in names:
            with self.subTest(failure=failure):
                callbacks = {name: Mock(side_effect=ValueError(name) if name == failure
                                        else lambda ctx: ctx) for name in names}
                frame = FrameContract(names).bind(**callbacks)
                marker = object()
                with self.assertRaisesRegex(ValueError, failure):
                    frame.execute(marker)
                for index, name in enumerate(names):
                    if index <= names.index(failure):
                        callbacks[name].assert_called_once_with(marker)
                    else:
                        callbacks[name].assert_not_called()

    def test_frame_binding_is_immutable_and_runner_cannot_be_overridden(self):
        from dataclasses import FrozenInstanceError
        from work.libs.frame import Frame, FrameContract
        contract = FrameContract(("prepare",))
        frame = contract.bind(prepare=lambda ctx: ctx)
        with self.assertRaises(FrozenInstanceError):
            contract.stages = ("mutate",)
        with self.assertRaises(FrozenInstanceError):
            frame.callbacks = ()
        with self.assertRaises(TypeError):
            class Bypass(Frame):
                def execute(self, context):
                    return None
        with self.assertRaises(TypeError):
            Frame(contract, ())

    def test_testing_library_import_is_domain_independent(self):
        from tests.fixtures import import_probe, ROOT
        result = import_probe(("work.libs.testing",),
                              ("app", "tests", "github", "config"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((ROOT / "tests" / "framework").exists())

    def test_suite_registry_isolated_and_default_context_is_generic(self):
        from work.libs.testing import SuiteRegistry
        first, second = SuiteRegistry(), SuiteRegistry()

        @first.register("one")
        class One(TestSuite):
            def test_one(self):
                def check(ctx):
                    pass
                self.run_contract(check=check)

        second.register("two")(One)
        self.assertEqual(list(first), ["one"])
        self.assertEqual(list(second), ["two"])
        self.assertEqual(first.build(("one",)).countTestCases(), 1)
        self.assert_rejected(first.build, ("two",))
        self.assert_rejected(second.build, ("one", "two"))
        contexts = []
        instance = One()
        instance.run_cases((("one",), ("two",)), lambda ctx: contexts.append(ctx))
        self.assertIsNot(contexts[0], contexts[1])
        contexts[0].marker = "changed"
        self.assertFalse(hasattr(contexts[1], "marker"))
        self.assertFalse(hasattr(contexts[0], "cli_help"))

    def test_suite_self_test_exemption_requires_exact_pair(self):
        from work.libs.testing import SuiteRegistry
        registry = SuiteRegistry()

        class Direct(TestSuite):
            def test_direct(self):
                self.assertTrue(True)

        class Other(Direct):
            pass

        registry.register("registry")(Direct)
        self.assert_rejected(registry.build, ("registry",))
        self.assert_rejected(registry.build, ("registry",), self_test=("other", Direct))
        self.assert_rejected(registry.build, ("registry",), self_test=("registry", Other))
        self.assertEqual(registry.build(("registry",), self_test=("registry", Direct)).countTestCases(), 1)
        self.assert_rejected(build_suite, names=("registry",), registered={"registry": Direct})
        self.assert_rejected(build_suite, names=("other",), registered={"other": RegistryContract})
        suite = build_suite(names=("registry",), registered={"registry": RegistryContract})
        self.assertGreater(suite.countTestCases(), 0)

    def test_suite_loader_coverage_remains_required_for_exempt_class(self):
        import unittest
        from work.libs.testing import SuiteRegistry

        class Direct(TestSuite):
            def test_first(self):
                pass

            def test_second(self):
                pass

        registry = SuiteRegistry()
        registry.register("registry")(Direct)
        loader = Mock()
        loader.loadTestsFromTestCase.return_value = unittest.TestSuite([Direct("test_first")])
        with self.assertRaisesRegex(ValueError, "Unexpected test loader coverage"):
            registry.build(("registry",), loader=loader, self_test=("registry", Direct))

    def test_shared_scope_preserves_exit_failures_and_exception_identity(self):
        for runner in ("contract", "scenario"):
            for failure in ("entry", "body", "exit", "suppression"):
                with self.subTest(runner=runner, failure=failure):
                    original = StopIteration("original")
                    cleanup = RuntimeError("cleanup")
                    scope = Mock()
                    from unittest.mock import MagicMock
                    manager = MagicMock()
                    manager.__enter__.side_effect = original if failure == "entry" else None
                    manager.__exit__.side_effect = cleanup if failure == "exit" else None
                    manager.__exit__.return_value = failure == "suppression"
                    scope.return_value = manager
                    act = Mock(side_effect=original if failure in ("body", "suppression") else None)
                    check = Mock()
                    expected = (cleanup if failure == "exit" else original)
                    def run():
                        if runner == "contract":
                            self.run_contract(act, check, arrange=scope)
                        else:
                            self.run_scenario((("step", act),), check, arrange=scope)
                    if failure == "suppression":
                        with self.assertRaisesRegex(AssertionError, runner.capitalize() + " scope suppressed a failure."):
                            run()
                    else:
                        with self.assertRaises(type(expected)) as caught:
                            run()
                        self.assertIs(caught.exception, expected)
                    scope.assert_called_once()
                    if failure == "entry":
                        manager.__exit__.assert_not_called()
                        act.assert_not_called()
                    else:
                        manager.__exit__.assert_called_once()
                        if failure in ("body", "suppression"):
                            self.assertIs(manager.__exit__.call_args.args[1], original)
                    if failure != "exit":
                        check.assert_not_called()
                    else:
                        check.assert_called_once()
