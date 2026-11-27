# FileRank: C
"""Offline cli contract tests."""

import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from app import cli
from app.commands import execute as execute_command
from app.registry import COMMANDS, register
from tests.fixture import ROOT
from tests.registry import register as register_suite


@register_suite("cli")
class CliContract(unittest.TestCase):
    def test_help_starts_real_module(self):
        result = subprocess.run([sys.executable, "-m", "app", "--help"],
                                cwd=ROOT, capture_output=True, text=True)
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

    def test_reject_unknown_task(self):
        with self.assertRaises(SystemExit) as error:
            cli.main(["task", "unregistered.py"])
        self.assertEqual(error.exception.code, 2)

    def test_registered_command_extends_cli_without_branch(self):
        with patch.dict(COMMANDS):
            @register("sample")
            class SampleCommand:
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
        result = subprocess.run([sys.executable, "-m", "app", "test", "--help"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
