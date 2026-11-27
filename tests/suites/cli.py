# FileRank: C
"""Offline cli contract tests."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import cli
from app.commands import execute as execute_command
from app.wiring import COMMANDS, register, workflow_commands
from libs.command import Command, CommandPlan, local_plan
from libs.testing import TestSuite
from tests.fixtures import TestContext
from tests.wiring import register as register_suite


@register_suite("cli")
class CliContract(TestSuite):
    context_type = TestContext

    def test_cli_help(self):
        cases = (
            ("root", (), ("trigger", "test")),
            ("test", ("test",), ()),
        )

        def check(ctx, args, expected):
            result = ctx.cli_help(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            for token in expected:
                self.assertIn(token, result.stdout)

        self.run_cases(cases, check)

    def test_cli_execution_modes(self):
        cases = (
            ("single", ["execute", "--single"], (True, None)),
            ("serial_stage_2", ["execute", "--serial-stage", "2"], (False, 2)),
        )

        def check(ctx, args, expected):
            command = execute_command.ExecuteCommand
            prepared = object()
            validated = object()
            prepare, validate, action = Mock(return_value=prepared), Mock(return_value=validated), Mock(return_value=0)
            plan = replace(command.plan, prepare=prepare, validate=validate, action=action)
            with patch.object(command, "plan", plan):
                self.assertEqual(cli.main(args), 0)
            prepare.assert_called_once()
            parsed = prepare.call_args.args[0]
            self.assertEqual((parsed.single, parsed.serial_stage), expected)
            validate.assert_called_once_with(prepared, parsed)
            action.assert_called_once_with(validated, parsed)

        self.run_cases(cases, check)

    def test_cli_rejects_unknown_commands(self):
        cases = (
            ("removed_task", ["task", "pr_merge.py"]),
            ("unregistered", ["unregistered"]),
        )

        def check(ctx, args):
            with self.assertRaises(SystemExit) as error:
                cli.main(args)
            self.assertEqual(error.exception.code, 2)

        self.run_cases(cases, check)

    def test_registered_command_extends_cli_without_branch(self):
        def check(ctx):
            with patch.dict(COMMANDS):
                @register("sample")
                class SampleCommand(Command):
                    help = "Test-only command"

                    @staticmethod
                    def configure(parser):
                        parser.add_argument("--value", type=int, required=True)

                    plan = local_plan(lambda ctx, args: args.value)

                with patch("app.wiring.load_names", return_value=("sample",)):
                    self.assertEqual(cli.main(["sample", "--value", "4"]), 4)

        self.run_contract(check=check)

    def test_duplicate_registration_rejected(self):
        def remember(ctx):
            ctx.original = COMMANDS["trigger"]

        def reject_duplicate(ctx):
            self.assert_rejected(register("trigger"), ctx.original)

        def check(ctx):
            self.assertIs(COMMANDS["trigger"], ctx.original)

        steps = (("remember", remember), ("reject_duplicate", reject_duplicate))
        self.run_scenario(steps, check)

    def test_invalid_registration_rejected(self):
        def check(ctx):
            with self.assertRaises(TypeError):
                register("invalid")(object)
            self.assertNotIn("invalid", COMMANDS)

        self.run_contract(check=check)

    def test_test_command_exit_status(self):
        cases = (
            ("success", True, 0),
            ("failure", False, 1),
        )

        def check(ctx, successful, expected):
            with patch("tests.wiring.build_suite") as build, \
                    patch("app.commands.test.unittest.TextTestRunner") as runner:
                result = Mock()
                result.wasSuccessful.return_value = successful
                runner.return_value.run.return_value = result
                self.assertEqual(cli.main(["test"]), expected)
                build.assert_called_once_with()
                runner.return_value.run.assert_called_once_with(build.return_value)

        self.run_cases(cases, check)

    def test_workflow_projection_exact(self):
        def check(ctx):
            self.assertEqual(workflow_commands(), {
                "pr_merge.py": ("merge",),
                "branch_delete.py": ("delete", "branch"),
            })

        self.run_contract(check=check)

    def test_workflow_projection_rejects_invalid_bindings(self):
        cases = (
            ("missing", "merge", ()),
            ("duplicate", "delete", ("pr_merge.py",)),
            ("unknown", "test", ("test.py",)),
        )

        def check(ctx, command, binding):
            with patch.object(COMMANDS[command], "workflow_execution", binding):
                self.assert_rejected(workflow_commands)

        self.run_cases(cases, check)

    def test_no_argument_commands_delegate_to_module_execute(self):
        from app.commands import trigger, merge, test
        cases = (
            ("trigger", "trigger", trigger.TriggerCommand),
            ("merge", "merge", merge.MergeCommand),
            ("test", "test", test.TestCommand),
        )

        def check(ctx, name, command):
            prepared, validated = object(), object()
            prepare = Mock(return_value=prepared)
            validate = Mock(return_value=validated)
            action = Mock(return_value=0)
            report = Mock() if command.plan.report is not None else None
            plan = replace(command.plan, prepare=prepare, validate=validate,
                           action=action, report=report)
            with patch.object(command, "plan", plan):
                self.assertEqual(cli.main([name]), 0)
            prepare.assert_called_once()
            args = prepare.call_args.args[0]
            self.assertEqual(vars(args), {"command": name})
            validate.assert_called_once_with(prepared, args)
            action.assert_called_once_with(validated, args)
            if report is not None:
                report.assert_called_once_with(validated, 0)

        self.run_cases(cases, check)

    def test_delete_command_delegates_to_module_execute(self):
        def check(ctx):
            from app.commands.delete import DeleteCommand
            prepared, validated = object(), object()
            prepare, validate, action, report = (
                Mock(return_value=prepared), Mock(return_value=validated),
                Mock(return_value="Deleted"), Mock())
            branch = replace(dict(DeleteCommand.targets)["branch"], prepare=prepare,
                             validate=validate, action=action, report=report)
            other = Mock()
            actions = replace(dict(DeleteCommand.targets)["actions"], action=other)
            with patch.object(DeleteCommand, "targets", (("branch", branch), ("actions", actions))):
                self.assertEqual(cli.main(["delete", "branch"]), 0)
            prepare.assert_called_once()
            args = prepare.call_args.args[0]
            self.assertEqual(args.target, "branch")
            validate.assert_called_once_with(prepared, args)
            action.assert_called_once_with(validated, args)
            report.assert_called_once_with(validated, "Deleted")
            other.assert_not_called()

        self.run_contract(check=check)

    def test_command_lifecycle_order_and_failure(self):
        cases = (("success", None), ("prepare", "prepare"),
                 ("validate", "validate"), ("action", "action"), ("report", "report"))

        def check(ctx, failure):
            calls = []
            prepared, validated = object(), object()

            def stage(name, result):
                def callback(*args):
                    calls.append(name)
                    if name == failure:
                        raise ValueError(name)
                    return result
                return callback

            class Sample(Command):
                help = "Lifecycle probe"
                plan = CommandPlan(stage("prepare", prepared), stage("validate", validated),
                                   stage("action", 7), stage("report", None),
                                   returns_status=True)

            args = SimpleNamespace()
            order = ["prepare", "validate", "action", "report"]
            if failure is None:
                self.assertEqual(Sample.execute(args), 7)
                self.assertEqual(calls, order)
            else:
                with self.assertRaisesRegex(ValueError, failure):
                    Sample.execute(args)
                self.assertEqual(calls, order[:order.index(failure) + 1])

        self.run_cases(cases, check)

    def test_command_registration_rejects_lifecycle_overrides(self):
        cases = (("execute", "execute"), ("bind", "bind"),
                 ("missing_plan", "plan"), ("duplicate_targets", "targets"))

        def check(ctx, attribute):
            plan = local_plan(lambda ctx, args: 0)
            values = {"execute": staticmethod(lambda args: 0),
                      "bind": classmethod(lambda cls, parser, name: None),
                      "plan": None, "targets": (("x", plan), ("x", plan))}
            attrs = {"help": "Invalid", "plan": plan}
            if attribute == "targets":
                attrs["plan"] = None
            attrs[attribute] = values[attribute]
            invalid = type("InvalidCommand", (Command,), attrs)
            with patch.dict(COMMANDS):
                with self.assertRaises(TypeError):
                    register("invalid")(invalid)
                self.assertNotIn("invalid", COMMANDS)

        self.run_cases(cases, check)

    def test_command_parser_cannot_override_dispatch(self):
        def check(ctx):
            action = Mock(return_value=0)
            alternate = Mock(return_value=0)

            class Sample(Command):
                help = "Invalid parser"
                plan = local_plan(action)

                @staticmethod
                def configure(parser):
                    parser.set_defaults(handler=alternate)

            with patch.dict(COMMANDS):
                register("sample")(Sample)
                with patch("app.wiring.load_names", return_value=("sample",)):
                    with self.assertRaises(TypeError):
                        cli.main(["sample"])
            action.assert_not_called()
            alternate.assert_not_called()

        self.run_contract(check=check)

    def test_command_library_import_is_domain_independent(self):
        def check(ctx):
            from tests.fixtures import import_probe
            result = import_probe(("libs.command",),
                                  ("app", "tests", "github", "config"))
            self.assertEqual(result.returncode, 0, result.stderr)

        self.run_contract(check=check)

    def test_command_registry_isolation_and_manifest_order(self):
        def check(ctx):
            from libs.command import CommandRegistry
            first, second = CommandRegistry(), CommandRegistry()

            @first.register("alpha")
            class Alpha(Command):
                help = "Alpha"
                plan = local_plan(lambda ctx, args: 1)

            @first.register("beta")
            class Beta(Command):
                help = "Beta"
                plan = local_plan(lambda ctx, args: 2)

            second.register("alpha")(Beta)
            self.assertEqual(list(first.configured(("beta", "alpha")).items()),
                             [("beta", Beta), ("alpha", Alpha)])
            self.assertEqual(first.configured(("alpha",)), {"alpha": Alpha})
            self.assertEqual(second.configured(("alpha",)), {"alpha": Beta})
            self.assert_rejected(second.configured, ("beta",))
            self.assert_rejected(first.register("alpha"), object)
            self.assertEqual(first["alpha"], Alpha)

        self.run_contract(check=check)

    def test_command_fixed_frame_preserves_context_report_and_status(self):
        cases = (("status_report", True, True), ("zero_report", False, True),
                 ("status_no_report", True, False), ("zero_no_report", False, False))

        def check(ctx, returns_status, has_report):
            from libs import command as framework
            from libs.frame import Frame
            from unittest.mock import call
            args, prepared, validated, result = (object(), object(), object(), object())
            prepare = Mock(return_value=prepared)
            validate = Mock(return_value=validated)
            action = Mock(return_value=result)
            report = Mock()
            trace = Mock()
            for name, callback in (("prepare", prepare), ("validate", validate),
                                   ("action", action), ("report", report)):
                trace.attach_mock(callback, name)

            class Sample(Command):
                help = "Frame contract"
                plan = CommandPlan(prepare, validate, action,
                                   report if has_report else None, returns_status)

            self.assertIs(type(framework._COMMAND_FRAME), Frame)
            self.assertEqual(framework._COMMAND_FRAME.contract.stages,
                             ("prepare", "validate", "action", "report"))
            with patch.object(framework, "_COMMAND_FRAME", wraps=framework._COMMAND_FRAME) as frame:
                self.assertIs(Sample.execute(args), result if returns_status else 0)
                frame.execute.assert_called_once()
            expected = [call.prepare(args), call.validate(prepared, args),
                        call.action(validated, args)]
            if has_report:
                expected.append(call.report(validated, result))
            self.assertEqual(trace.mock_calls, expected)

        self.run_cases(cases, check)
