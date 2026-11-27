# FileRank: C
"""Offline cli contract tests."""

from unittest.mock import Mock, patch

from app import cli
from app.commands import execute as execute_command
from app.registry import COMMANDS, register, workflow_commands
from app.commands.model import Command
from tests.suites.model import TestSuite
from tests.registry import register as register_suite


@register_suite("cli")
class CliContract(TestSuite):
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
            with patch.object(execute_command, "execute", return_value=0) as call:
                self.assertEqual(cli.main(args), 0)
                call.assert_called_once_with(*expected)

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
        with patch.dict(COMMANDS):
            @register("sample")
            class SampleCommand(Command):
                help = "Test-only command"

                @staticmethod
                def configure(parser):
                    parser.add_argument("--value", type=int, required=True)

                @staticmethod
                def execute(args):
                    return args.value

            with patch("app.registry.load_names", return_value=("sample",)):
                self.assertEqual(cli.main(["sample", "--value", "4"]), 4)

    def test_duplicate_registration_rejected(self):
        original = COMMANDS["trigger"]
        with self.assertRaises(ValueError):
            register("trigger")(original)
        self.assertIs(COMMANDS["trigger"], original)

    def test_invalid_registration_rejected(self):
        with self.assertRaises(TypeError):
            register("invalid")(object)
        self.assertNotIn("invalid", COMMANDS)

    def test_test_command_exit_status(self):
        cases = (
            ("success", True, 0),
            ("failure", False, 1),
        )

        def check(ctx, successful, expected):
            with patch("tests.registry.build_suite") as build, \
                    patch("app.commands.test.unittest.TextTestRunner") as runner:
                result = Mock()
                result.wasSuccessful.return_value = successful
                runner.return_value.run.return_value = result
                self.assertEqual(cli.main(["test"]), expected)
                build.assert_called_once_with()
                runner.return_value.run.assert_called_once_with(build.return_value)

        self.run_cases(cases, check)

    def test_workflow_projection_exact(self):
        self.assertEqual(workflow_commands(), {
            "pr_merge.py": ("merge",),
            "branch_delete.py": ("delete", "branch"),
        })

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
            ("trigger", "trigger", trigger),
            ("merge", "merge", merge),
            ("test", "test", test),
        )

        def check(ctx, name, module):
            with patch.object(module, "execute", return_value=0) as run:
                self.assertEqual(cli.main([name]), 0)
                run.assert_called_once_with()

        self.run_cases(cases, check)

    def test_delete_command_delegates_to_module_execute(self):
        from app.commands import delete
        with patch.object(delete, "execute", return_value=0) as run:
            self.assertEqual(cli.main(["delete", "branch"]), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0].target, "branch")
