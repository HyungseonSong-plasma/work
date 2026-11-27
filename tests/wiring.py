# FileRank: C
"""Project-owned suite manifest, explicit registry and narrow self-test exemption."""

import sys

from work.config import load_names
from work.libs.testing import SuiteRegistry

SUITES = SuiteRegistry()
register = SUITES.register


def build_suite(loader=None, names=None, registered=None):
    names = load_names("tests") if names is None else tuple(names)
    # Preserve the exact registered self-test identity, never a name-only exemption.
    module = sys.modules.get("tests.suites.registry_contract")
    case = getattr(module, "RegistryContract", None)
    self_test = ("registry", case) if case is not None else None
    return SUITES.build(names, loader, registered, self_test=self_test)
