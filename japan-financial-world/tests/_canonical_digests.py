"""
v1.23.1 — Canonical living-world digest constants.

Single source of truth for the four canonical
``living_world_digest`` / CLI-bundle digest pins that the test
suite asserts against. Importing from this module is the
discipline; pasting the hex literal into a test file is a
regression — a typo at any single site silently breaks
regression detection at that site.

The constants are byte-identical to the values pinned across
the v1.18.last / v1.19.last / v1.20.last / v1.21.last /
v1.22.last digests; v1.23.1 introduces no new digest. A
future digest update lands in a separate v1.23.x.x sub-
milestone under a fresh design pin.

Pin tests live in
``tests/test_canonical_digests_module.py``.
"""

from __future__ import annotations


# v1.18.last / v1.19.last / v1.20.last / v1.21.last /
# v1.22.last canonical default-fixture digest. This is the
# ``quarterly_default`` (no-scenario, no-stress) profile
# digest. ≥ 17 sites in the test corpus pinned to this hex.
QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST: str = (
    "f93bdf3f4203c20d4a58e956160b0bb1004dcdecf"
    "0648a92cc961401b705897c"
)


# v1.19.3 ``monthly_reference`` profile digest (12 monthly
# periods, no stress). Unchanged from v1.19.last across the
# entire v1.20 / v1.21 / v1.22 sequence.
MONTHLY_REFERENCE_LIVING_WORLD_DIGEST: str = (
    "75a91cfa35cbbc29d321ffab045eb07ce4d2ba77dc"
    "4514a009bb4e596c91879d"
)


# v1.20.3 ``scenario_monthly_reference_universe`` test-fixture
# digest under the default regime (no ``--regime`` flag).
SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST: str = (
    "5003fdfaa45d5b5212130b1158729c692616cf2a8d"
    "f9b425b226baef15566eb6"
)


# v1.20.4 CLI bundle digest under
# ``--regime constrained --scenario credit_tightening_driver``.
V1_20_4_CLI_BUNDLE_DIGEST: str = (
    "ec37715b8b5532841311bbf14d087cf4dcca731a9d"
    "c5de3b2868f32700731aaf"
)


__all__ = [
    "QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST",
    "MONTHLY_REFERENCE_LIVING_WORLD_DIGEST",
    "SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST",
    "V1_20_4_CLI_BUNDLE_DIGEST",
]
