# FileRank: C
"""Tests of registry completeness and registration validation."""

import unittest
from unittest.mock import patch

from tests.suites.model import TestSuite
from tests.registry import SUITES, build_suite, register


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
        registered = {"cli": RegistryContract}
        for names in ([], ["unknown"], ["cli", "cli"], ["cli", "unknown"]):
            with self.subTest(names=names):
                with self.assertRaises(ValueError):
                    build_suite(names=names, registered=registered)

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
