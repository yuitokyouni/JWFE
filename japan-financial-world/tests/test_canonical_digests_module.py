"""
v1.23.1 — Canonical digest module pin tests.

Pins ``tests/_canonical_digests.py`` as the single source of
truth for the four canonical living-world / CLI-bundle digests.

The module exports:

- ``QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST``
- ``MONTHLY_REFERENCE_LIVING_WORLD_DIGEST``
- ``SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST``
- ``V1_20_4_CLI_BUNDLE_DIGEST``

Tests:

- ``test_canonical_digests_module_exports_expected_values`` —
  the four constants exist and match the v1.18.last /
  v1.19.last / v1.20.last / v1.21.last byte-pinned values.
- ``test_no_duplicate_canonical_digest_literals_outside_canonical_module``
  — no test file outside ``tests/_canonical_digests.py`` and
  ``tests/test_canonical_digests_module.py`` (this file)
  pastes any of these four hex literals as a string. The
  exception list contains exactly these two files.

These tests are additive: they prove the v1.23.1 migration
landed without changing digest values.
"""

from __future__ import annotations

from pathlib import Path

from _canonical_digests import (
    MONTHLY_REFERENCE_LIVING_WORLD_DIGEST,
    QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
    SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST,
    V1_20_4_CLI_BUNDLE_DIGEST,
)


_TESTS_DIR = Path(__file__).resolve().parent


# v1.18.last / v1.19.last / v1.20.last / v1.21.last byte-pinned
# values (re-asserted here as bare hex literals so a change to
# ``_canonical_digests.py`` is caught by this pin test).
_EXPECTED_QUARTERLY_DEFAULT: str = (
    "f93bdf3f4203c20d4a58e956160b0bb1004dcdecf"
    "0648a92cc961401b705897c"
)
_EXPECTED_MONTHLY_REFERENCE: str = (
    "75a91cfa35cbbc29d321ffab045eb07ce4d2ba77dc"
    "4514a009bb4e596c91879d"
)
_EXPECTED_SCENARIO_MONTHLY_REFERENCE_UNIVERSE: str = (
    "5003fdfaa45d5b5212130b1158729c692616cf2a8d"
    "f9b425b226baef15566eb6"
)
_EXPECTED_V1_20_4_CLI_BUNDLE: str = (
    "ec37715b8b5532841311bbf14d087cf4dcca731a9d"
    "c5de3b2868f32700731aaf"
)


_CANONICAL_DIGEST_VALUES: tuple[str, ...] = (
    _EXPECTED_QUARTERLY_DEFAULT,
    _EXPECTED_MONTHLY_REFERENCE,
    _EXPECTED_SCENARIO_MONTHLY_REFERENCE_UNIVERSE,
    _EXPECTED_V1_20_4_CLI_BUNDLE,
)


# Tests that legitimately re-assert the four hex literals as
# part of pinning the canonical module itself. Any other test
# file pasting these literals is a regression and must be
# migrated to import from ``tests/_canonical_digests.py``.
_ALLOWED_LITERAL_FILES: frozenset[str] = frozenset(
    {
        "_canonical_digests.py",
        "test_canonical_digests_module.py",
    }
)


def test_canonical_digests_module_exports_expected_values() -> None:
    """The four constants exist and equal the v1.18.last /
    v1.19.last / v1.20.last / v1.21.last byte-pinned values."""
    assert (
        QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST
        == _EXPECTED_QUARTERLY_DEFAULT
    )
    assert (
        MONTHLY_REFERENCE_LIVING_WORLD_DIGEST
        == _EXPECTED_MONTHLY_REFERENCE
    )
    assert (
        SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST
        == _EXPECTED_SCENARIO_MONTHLY_REFERENCE_UNIVERSE
    )
    assert (
        V1_20_4_CLI_BUNDLE_DIGEST
        == _EXPECTED_V1_20_4_CLI_BUNDLE
    )
    # length = 64 (sha-256 hex)
    for value in (
        QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
        MONTHLY_REFERENCE_LIVING_WORLD_DIGEST,
        SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST,
        V1_20_4_CLI_BUNDLE_DIGEST,
    ):
        assert isinstance(value, str)
        assert len(value) == 64
        int(value, 16)  # parses as hex


def test_no_duplicate_canonical_digest_literals_outside_canonical_module() -> None:
    """Every test file (other than the canonical module itself
    and this pin test) must import the canonical constants from
    ``_canonical_digests`` rather than pasting the hex literal.
    A typo in any single site silently breaks regression
    detection at that site; this test catches such drift.

    Scans for both the full 64-char hex literal and its two
    32-char halves (the design pin commonly splits the literal
    across two adjacent string-concatenation lines, which a
    naive ``substring in text`` scan misses)."""
    offenders: list[tuple[str, str]] = []
    for path in sorted(_TESTS_DIR.glob("*.py")):
        if path.name in _ALLOWED_LITERAL_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for value in _CANONICAL_DIGEST_VALUES:
            # Scan full literal + first / second half (catches
            # split-across-two-lines form).
            patterns = (value, value[:32], value[32:])
            for pattern in patterns:
                if pattern in text:
                    offenders.append((path.name, pattern))
                    break
    assert offenders == [], (
        "Hard-coded canonical digest literal(s) found outside "
        "tests/_canonical_digests.py — migrate to "
        "``from _canonical_digests import <CONSTANT>``: "
        f"{offenders}"
    )
