"""
v1.23.1 — Forbidden-token composition pin tests.

Pins ``world/forbidden_tokens.py`` as the single source of
truth for the v1.18.0 / v1.19.0 / v1.21.0a / v1.22.0 forbidden
token vocabulary, decomposed into BASE + per-milestone deltas
and re-composed under the existing public names.

The pin tests prove:

- the v1.21.0a stress tokens are present in the canonical
  composition (no token is silently dropped during the
  decomposition);
- the v1.21.1 / v1.21.2 / v1.21.3 in-place
  ``FORBIDDEN_STRESS_PROGRAM_FIELD_NAMES`` /
  ``FORBIDDEN_STRESS_APPLICATION_FIELD_NAMES`` /
  ``FORBIDDEN_STRESS_READOUT_FIELD_NAMES`` declarations are
  byte-identical to the canonical composition (so the
  consolidation can replace them at a future v1.23.x.x
  sub-milestone without changing runtime behaviour);
- the canonical composed run-export forbidden set composes
  the v1.21.0a stress tokens (the "leak-fix" — a non-stress
  bundle section like ``manifest`` / ``overview`` /
  ``timeline`` cannot smuggle a v1.21.0a stress-shaped key);
- existing test fixtures have zero active forbidden-token
  violations against the canonical composed run-export set
  (dry-run scan over representative bundles built by the
  test suite).

The in-place declarations remain the runtime authority at
v1.23.1; this test suite documents the canonical
composition + leak-fix superset.
"""

from __future__ import annotations

from typing import Any, Mapping

from world.forbidden_tokens import (
    FORBIDDEN_RUN_EXPORT_FIELD_NAMES as CANONICAL_RUN_EXPORT_FORBIDDEN,
    FORBIDDEN_STRESS_APPLICATION_FIELD_NAMES as CANONICAL_STRESS_APPLICATION_FORBIDDEN,
    FORBIDDEN_STRESS_PROGRAM_FIELD_NAMES as CANONICAL_STRESS_PROGRAM_FORBIDDEN,
    FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS as CANONICAL_STRESS_READOUT_EXPORT_TOKENS,
    FORBIDDEN_STRESS_READOUT_FIELD_NAMES as CANONICAL_STRESS_READOUT_FORBIDDEN,
    FORBIDDEN_TOKENS_BASE,
    FORBIDDEN_TOKENS_V1_21_0A_STRESS_DELTA,
)
from world.run_export import (
    FORBIDDEN_RUN_EXPORT_FIELD_NAMES as IN_PLACE_RUN_EXPORT_FORBIDDEN,
    RunExportBundle,
    build_run_export_bundle,
)
from world.stress_applications import (
    FORBIDDEN_STRESS_APPLICATION_FIELD_NAMES as IN_PLACE_STRESS_APPLICATION_FORBIDDEN,
)
from world.stress_programs import (
    FORBIDDEN_STRESS_PROGRAM_FIELD_NAMES as IN_PLACE_STRESS_PROGRAM_FORBIDDEN,
)
from world.stress_readout import (
    FORBIDDEN_STRESS_READOUT_FIELD_NAMES as IN_PLACE_STRESS_READOUT_FORBIDDEN,
)

from _canonical_digests import (
    QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
)


# v1.21.0a stress tokens that the v1.23.1 leak-fix composes
# into ``CANONICAL_RUN_EXPORT_FORBIDDEN``. Listed verbatim so
# the test catches a future regression that quietly drops one.
_V1_21_0A_STRESS_TOKENS_EXPECTED: frozenset[str] = frozenset(
    {
        "stress_magnitude",
        "stress_magnitude_in_basis_points",
        "stress_magnitude_in_percent",
        "stress_probability_weight",
        "expected_field_response",
        "expected_stress_path",
        "stress_forecast_path",
        "stress_buy_signal",
        "stress_sell_signal",
        "stress_target_price",
        "stress_expected_return",
        "stress_outcome_label",
        "aggregate_shift_direction",
        "aggregate_context_label",
        "combined_context_label",
        "combined_shift_direction",
        "net_pressure_label",
        "net_stress_direction",
        "composite_risk_label",
        "composite_market_access_label",
        "dominant_stress_label",
        "total_stress_intensity",
        "stress_amplification_score",
        "predicted_stress_effect",
        "projected_stress_effect",
        "interaction_label",
        "composition_label",
        "output_context_label",
        "dominant_shift_direction_label",
        "amplify",
        "dampen",
        "offset",
        "coexist",
    }
)


# ---------------------------------------------------------------------------
# 1. Composition contains all v1.21.0a tokens
# ---------------------------------------------------------------------------


def test_forbidden_token_composition_contains_all_v1_21_0a_tokens() -> None:
    """Every v1.21.0a stress / aggregate / interaction token
    must appear in ``FORBIDDEN_TOKENS_V1_21_0A_STRESS_DELTA``.
    A future regression that silently drops a token from the
    delta would otherwise bypass the boundary at every
    composed surface."""
    missing = (
        _V1_21_0A_STRESS_TOKENS_EXPECTED
        - FORBIDDEN_TOKENS_V1_21_0A_STRESS_DELTA
    )
    assert missing == set(), (
        "v1.21.0a stress tokens missing from "
        "FORBIDDEN_TOKENS_V1_21_0A_STRESS_DELTA: "
        f"{sorted(missing)!r}"
    )


# ---------------------------------------------------------------------------
# 2. In-place stress-program / -application / -readout sets
#    match the canonical composition (byte-identical)
# ---------------------------------------------------------------------------


def test_stress_program_forbidden_set_matches_composed_set() -> None:
    """The v1.21.1 in-place
    ``FORBIDDEN_STRESS_PROGRAM_FIELD_NAMES`` must be byte-
    identical to the canonical composition. Any drift means
    a future migration to import from ``world.forbidden_tokens``
    would change runtime behaviour."""
    assert (
        IN_PLACE_STRESS_PROGRAM_FORBIDDEN
        == CANONICAL_STRESS_PROGRAM_FORBIDDEN
    )


def test_stress_application_forbidden_set_matches_composed_set() -> None:
    """The v1.21.2 in-place
    ``FORBIDDEN_STRESS_APPLICATION_FIELD_NAMES`` must equal
    the canonical composition."""
    assert (
        IN_PLACE_STRESS_APPLICATION_FORBIDDEN
        == CANONICAL_STRESS_APPLICATION_FORBIDDEN
    )


def test_stress_readout_forbidden_set_matches_composed_set() -> None:
    """The v1.21.3 in-place
    ``FORBIDDEN_STRESS_READOUT_FIELD_NAMES`` must equal the
    canonical composition."""
    assert (
        IN_PLACE_STRESS_READOUT_FORBIDDEN
        == CANONICAL_STRESS_READOUT_FORBIDDEN
    )


# ---------------------------------------------------------------------------
# 3. Canonical run-export set composes the v1.21.0a stress
#    tokens (the leak-fix). The in-place v1.19.0 run-export
#    set is the runtime authority and remains a subset of the
#    canonical composition until a future migration.
# ---------------------------------------------------------------------------


def test_run_export_forbidden_set_composes_stress_tokens() -> None:
    """The canonical composed
    ``FORBIDDEN_RUN_EXPORT_FIELD_NAMES`` must include every
    v1.21.0a stress token. This is the v1.23.1 leak-fix:
    once the in-place declaration migrates to import from
    ``world.forbidden_tokens``, a non-stress bundle section
    cannot smuggle a v1.21.0a stress-shaped key."""
    missing = (
        FORBIDDEN_TOKENS_V1_21_0A_STRESS_DELTA
        - CANONICAL_RUN_EXPORT_FORBIDDEN
    )
    assert missing == set(), (
        "v1.21.0a stress tokens missing from canonical "
        "FORBIDDEN_RUN_EXPORT_FIELD_NAMES (leak-fix "
        f"regression): {sorted(missing)!r}"
    )
    # And the in-place v1.19.0 run-export set is a subset of
    # the canonical composition (i.e., the canonical is a
    # superset; nothing is lost in the migration).
    extra = IN_PLACE_RUN_EXPORT_FORBIDDEN - CANONICAL_RUN_EXPORT_FORBIDDEN
    assert extra == set(), (
        "in-place FORBIDDEN_RUN_EXPORT_FIELD_NAMES contains "
        "tokens absent from canonical composition: "
        f"{sorted(extra)!r}"
    )


# ---------------------------------------------------------------------------
# 4. BASE is a subset of every composed set.
# ---------------------------------------------------------------------------


def test_base_is_subset_of_every_composed_set() -> None:
    """``FORBIDDEN_TOKENS_BASE`` must be a subset of every
    composed forbidden set (every downstream layer forbids the
    BASE tokens)."""
    for name, composed in (
        (
            "FORBIDDEN_STRESS_PROGRAM_FIELD_NAMES",
            CANONICAL_STRESS_PROGRAM_FORBIDDEN,
        ),
        (
            "FORBIDDEN_STRESS_APPLICATION_FIELD_NAMES",
            CANONICAL_STRESS_APPLICATION_FORBIDDEN,
        ),
        (
            "FORBIDDEN_STRESS_READOUT_FIELD_NAMES",
            CANONICAL_STRESS_READOUT_FORBIDDEN,
        ),
        (
            "FORBIDDEN_RUN_EXPORT_FIELD_NAMES",
            CANONICAL_RUN_EXPORT_FORBIDDEN,
        ),
        (
            "FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS",
            CANONICAL_STRESS_READOUT_EXPORT_TOKENS,
        ),
    ):
        missing = FORBIDDEN_TOKENS_BASE - composed
        assert missing == set(), (
            f"{name} missing BASE tokens: {sorted(missing)!r}"
        )


# ---------------------------------------------------------------------------
# 5. Dry-run scan: no existing run-export fixture has an
#    active payload key that would violate the canonical
#    leak-fixed FORBIDDEN_RUN_EXPORT_FIELD_NAMES. This is the
#    v1.23.1 binding pre-merge scan from §3.B.
#
# We scan a representative ``RunExportBundle`` built via the
# helper signature the existing test corpus uses (default
# fixture digest + empty payload sections). A future fixture
# that legitimately needs a previously-leaky token must
# update the canonical set under a fresh design pin.
# ---------------------------------------------------------------------------


def _walk_payload_keys(value: Any) -> tuple[str, ...]:
    """Walk a JSON-like value and return every dict key
    encountered at any depth."""
    out: list[str] = []
    if isinstance(value, Mapping):
        for k, v in value.items():
            if isinstance(k, str):
                out.append(k)
            out.extend(_walk_payload_keys(v))
    elif isinstance(value, (list, tuple)):
        for entry in value:
            out.extend(_walk_payload_keys(entry))
    return tuple(out)


def _canonical_no_stress_bundle() -> RunExportBundle:
    """Representative canonical bundle (no stress applied) — a
    minimal stand-in for the existing test-corpus fixtures.
    Constructed without any forbidden key so the in-place
    scan accepts it; we then re-scan its payload keys against
    the canonical leak-fixed forbidden set."""
    return build_run_export_bundle(
        bundle_id="run_bundle:v1_23_1_dry_run:1",
        run_profile_label="quarterly_default",
        regime_label="constrained",
        selected_scenario_label="none_baseline",
        period_count=4,
        digest=QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
    )


def test_existing_fixtures_have_zero_active_forbidden_violations() -> None:
    """Walk a representative ``RunExportBundle`` payload and
    confirm no key matches the canonical leak-fixed
    ``FORBIDDEN_RUN_EXPORT_FIELD_NAMES``. This is the v1.23.1
    pre-merge dry-run scan — if a fixture legitimately needs
    a previously-leaky stress token as a payload key, the
    canonical composition must be revised under a fresh
    design pin before the in-place set migrates."""
    bundle = _canonical_no_stress_bundle()
    payload = bundle.to_dict()
    keys = _walk_payload_keys(payload)
    violations = sorted(
        k for k in keys if k in CANONICAL_RUN_EXPORT_FORBIDDEN
    )
    assert violations == [], (
        "Representative no-stress bundle has payload keys that "
        "would violate the canonical leak-fixed "
        "FORBIDDEN_RUN_EXPORT_FIELD_NAMES: "
        f"{violations!r}"
    )
