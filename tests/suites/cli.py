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
    def test_help_starts_real_module(self):
        result = self.ctx.cli_help()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("trigger", result.stdout)
        self.assertIn("test", result.stdout)

    def test_cli_single(self):
        with patch.object(execute_command, "execute", return_value=0) as call:
            self.assertEqual(cli.main(["execute", "--single"]), 0)
            call.assert_called_once_with(True, None)

    def test_cli_serial(self):
        with patch.object(execute_command, "execute", return_value=0) as call:
            self.assertEqual(cli.main(["execute", "--serial-stage", "2"]), 0)
            call.assert_called_once_with(False, 2)

    def test_removed_task_command(self):
        with self.assertRaises(SystemExit) as error:
            cli.main(["task", "pr_merge.py"])
        self.assertEqual(error.exception.code, 2)

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

    def test_unknown_command_rejected(self):
        with self.assertRaises(SystemExit) as error:
            cli.main(["unregistered"])
        self.assertEqual(error.exception.code, 2)


    def test_test_command_exit_status(self):
        for successful, expected in ((True, 0), (False, 1)):
            with self.subTest(successful=successful):
                with patch("tests.registry.build_suite") as build, \
                        patch("app.commands.test.unittest.TextTestRunner") as runner:
                    result = Mock()
                    result.wasSuccessful.return_value = successful
                    runner.return_value.run.return_value = result
                    self.assertEqual(cli.main(["test"]), expected)
                    build.assert_called_once_with()
                    runner.return_value.run.assert_called_once_with(build.return_value)

    def test_test_command_help(self):
        result = self.ctx.cli_help("test")
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_workflow_projection_exact(self):
        self.assertEqual(workflow_commands(), {
            "pr_merge.py": ("merge",),
            "branch_delete.py": ("delete", "branch"),
        })

    def test_workflow_projection_rejects_missing_or_duplicate(self):
        with patch.object(COMMANDS["merge"], "workflow_execution", ()):
            self.assert_rejected(workflow_commands)
        with patch.object(COMMANDS["delete"], "workflow_execution", ("pr_merge.py",)):
            self.assert_rejected(workflow_commands)
        with patch.object(COMMANDS["test"], "workflow_execution", ("test.py",)):
            self.assert_rejected(workflow_commands)


    def test_no_argument_commands_delegate_to_module_execute(self):
        from app.commands import trigger, merge, test
        for name, module in (("trigger", trigger), ("merge", merge), ("test", test)):
            with self.subTest(command=name):
                with patch.object(module, "execute", return_value=0) as run:
                    self.assertEqual(cli.main([name]), 0)
                    run.assert_called_once_with()

    def test_delete_command_delegates_to_module_execute(self):
        from app.commands import delete
        with patch.object(delete, "execute", return_value=0) as run:
            self.assertEqual(cli.main(["delete", "branch"]), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0].target, "branch")
