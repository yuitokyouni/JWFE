"""
Tests for v1.22.1 — Stress Readout Export Section.

Pins the v1.22.0 design contract end-to-end:

- The new ``stress_readout`` payload section on
  :class:`world.run_export.RunExportBundle` is **omitted** from
  the JSON output when no v1.21 stress program has been applied
  to the kernel — this is the digest-preserving discipline that
  keeps every pre-v1.22 bundle byte-identical.
- When at least one
  :class:`world.stress_applications.StressProgramApplicationRecord`
  exists, the section serialises **descriptive-only** plain-id
  citations and per-step resolution counts (the 19 keys pinned
  by :data:`world.run_export.STRESS_READOUT_ENTRY_REQUIRED_KEYS`).
- No interaction inference. No aggregate / combined / net /
  dominant / composite output. No impact / outcome / risk_score
  / forecast / prediction / recommendation / expected_return /
  target_price / amplify / dampen / offset / coexist surfaced as
  keys or as string values.
- Partial application is preserved visibly:
  ``unresolved_step_count`` > 0 ⇒ ``is_partial`` is True,
  ``unresolved_step_ids`` lists the affected ids, and
  ``unresolved_reason_labels`` carries a closed-set reason
  parallel array.
- The export does **not** emit a ledger record, does **not**
  mutate any source-of-truth book, and does **not** change
  existing v1.21.last digests for no-stress fixtures.
- The browser bundle remains static JSON (parseable by
  :func:`json.loads`).
- v1.22.1 ships **no UI changes**: the static workbench HTML
  is byte-identical pre / post v1.22.1.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.run_export import (
    FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS,
    STRESS_READOUT_ENTRY_REQUIRED_KEYS,
    RunExportBundle,
    build_run_export_bundle,
    bundle_to_dict,
    bundle_to_json,
)
from world.scenario_drivers import ScenarioDriverTemplate
from world.scheduler import Scheduler
from world.state import State
from world.stress_applications import apply_stress_program
from world.stress_programs import (
    StressProgramTemplate,
    StressStep,
)
from world.stress_readout_export import (
    build_stress_readout_export_section,
    stress_field_readout_to_export_entry,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _bare_kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 4, 30)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _seed_happy_path_kernel(
    *,
    program_id: str = "stress_program:export_test:happy_path",
) -> tuple[WorldKernel, str]:
    kernel = _bare_kernel()
    kernel.scenario_drivers.add_template(
        ScenarioDriverTemplate(
            scenario_driver_template_id=(
                "scenario_driver:credit_tightening:reference"
            ),
            scenario_family_label="credit_tightening_driver",
            driver_group_label="credit_liquidity",
            driver_label="Synthetic test driver",
            event_date_policy_label="quarter_end",
            severity_label="medium",
            affected_actor_scope_label="market_wide",
            expected_annotation_type_label=(
                "financing_constraint"
            ),
            affected_evidence_bucket_labels=(
                "market_environment_state",
                "financing_review_surface",
            ),
        )
    )
    program = StressProgramTemplate(
        stress_program_template_id=program_id,
        program_label="Export test program",
        program_purpose_label=(
            "single_credit_tightening_stress"
        ),
        stress_steps=(
            StressStep(
                stress_step_id=f"{program_id}:step:0",
                parent_stress_program_template_id=program_id,
                step_index=0,
                scenario_driver_template_id=(
                    "scenario_driver:credit_tightening:reference"
                ),
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            ),
        ),
    )
    kernel.stress_programs.add_program(program)
    receipt = apply_stress_program(
        kernel,
        stress_program_template_id=program_id,
        as_of_date="2026-04-30",
    )
    return kernel, receipt.stress_program_application_id


def _seed_partial_kernel(
    *,
    program_id: str = "stress_program:export_test:partial",
) -> tuple[WorldKernel, str]:
    kernel = _bare_kernel()
    kernel.scenario_drivers.add_template(
        ScenarioDriverTemplate(
            scenario_driver_template_id=(
                "scenario_driver:credit_tightening:reference"
            ),
            scenario_family_label="credit_tightening_driver",
            driver_group_label="credit_liquidity",
            driver_label="Synthetic test driver",
            event_date_policy_label="quarter_end",
            severity_label="medium",
            affected_actor_scope_label="market_wide",
            expected_annotation_type_label=(
                "financing_constraint"
            ),
            affected_evidence_bucket_labels=(
                "market_environment_state",
                "financing_review_surface",
            ),
        )
    )
    program = StressProgramTemplate(
        stress_program_template_id=program_id,
        program_label="Partial export test program",
        program_purpose_label="multi_stress_demonstration",
        stress_steps=(
            StressStep(
                stress_step_id=f"{program_id}:step:0",
                parent_stress_program_template_id=program_id,
                step_index=0,
                scenario_driver_template_id=(
                    "scenario_driver:credit_tightening:reference"
                ),
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            ),
            StressStep(
                stress_step_id=f"{program_id}:step:1",
                parent_stress_program_template_id=program_id,
                step_index=1,
                # NOT registered → step is unresolved
                scenario_driver_template_id=(
                    "scenario_driver:nonexistent:reference"
                ),
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_05",
            ),
        ),
    )
    kernel.stress_programs.add_program(program)
    receipt = apply_stress_program(
        kernel,
        stress_program_template_id=program_id,
        as_of_date="2026-04-30",
    )
    return kernel, receipt.stress_program_application_id


def _make_minimal_bundle(
    *, stress_readout=None
) -> RunExportBundle:
    """Build a minimal bundle for export-shape assertions."""
    return build_run_export_bundle(
        bundle_id="run_bundle:test:v1_22_1",
        run_profile_label="quarterly_default",
        regime_label="constrained",
        selected_scenario_label="none_baseline",
        period_count=0,
        digest="x" * 64,
        stress_readout=stress_readout,
    )


# ---------------------------------------------------------------------------
# 1. test_export_bundle_omits_stress_readouts_when_absent
# ---------------------------------------------------------------------------


def test_export_bundle_omits_stress_readouts_when_absent():
    """When no stress readout exists, the JSON output must not
    contain the ``stress_readout`` key. This is the digest-
    preserving omission that keeps pre-v1.22 bundles byte-
    identical."""
    bundle = _make_minimal_bundle()
    d = bundle_to_dict(bundle)
    assert "stress_readout" not in d
    s = bundle_to_json(bundle)
    assert "stress_readout" not in s
    parsed = json.loads(s)
    assert "stress_readout" not in parsed
    # Bare kernel → empty section.
    kernel = _bare_kernel()
    assert build_stress_readout_export_section(kernel) == ()


# ---------------------------------------------------------------------------
# 2. test_existing_no_stress_bundle_digest_unchanged
# ---------------------------------------------------------------------------


_V1_21_LAST_QUARTERLY_DEFAULT_DIGEST: str = (
    "f93bdf3f4203c20d4a58e956160b0bb1004dcdecf"
    "0648a92cc961401b705897c"
)
_V1_21_LAST_MONTHLY_REFERENCE_DIGEST: str = (
    "75a91cfa35cbbc29d321ffab045eb07ce4d2ba77dc"
    "4514a009bb4e596c91879d"
)
_V1_21_LAST_SCENARIO_UNIVERSE_FIXTURE_DIGEST: str = (
    "5003fdfaa45d5b5212130b1158729c692616cf2a8d"
    "f9b425b226baef15566eb6"
)


def test_existing_no_stress_bundle_digest_unchanged():
    """The v1.21.last canonical living-world digests must remain
    byte-identical for the ``quarterly_default`` and
    ``monthly_reference`` test fixtures, and the v1.20.3
    ``scenario_monthly_reference_universe`` fixture digest.
    v1.22.1 adds an export-side section that is omitted when the
    kernel has no stress program — therefore the digests cannot
    move."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from test_living_reference_world import (  # type: ignore[import-not-found]
        _run_default,
        _run_monthly_reference,
        _seed_kernel as _canonical_seed_kernel,
    )
    from test_living_reference_world_performance_boundary import (  # type: ignore[import-not-found]
        _seed_v1_20_3_kernel,
    )
    from world.reference_living_world import (
        _DEFAULT_MONTHLY_PERIOD_DATES,
        _DEFAULT_SCENARIO_UNIVERSE_BANK_IDS,
        _DEFAULT_SCENARIO_UNIVERSE_FIRM_IDS,
        _DEFAULT_SCENARIO_UNIVERSE_INVESTOR_IDS,
        run_living_reference_world,
    )

    # quarterly_default
    k1 = _canonical_seed_kernel()
    r1 = _run_default(k1)
    assert (
        living_world_digest(k1, r1)
        == _V1_21_LAST_QUARTERLY_DEFAULT_DIGEST
    )

    # monthly_reference
    k2 = _canonical_seed_kernel()
    r2 = _run_monthly_reference(k2)
    assert (
        living_world_digest(k2, r2)
        == _V1_21_LAST_MONTHLY_REFERENCE_DIGEST
    )

    # scenario_monthly_reference_universe (v1.20.3 fixture)
    k3 = _seed_v1_20_3_kernel()
    r3 = run_living_reference_world(
        k3,
        firm_ids=_DEFAULT_SCENARIO_UNIVERSE_FIRM_IDS,
        investor_ids=_DEFAULT_SCENARIO_UNIVERSE_INVESTOR_IDS,
        bank_ids=_DEFAULT_SCENARIO_UNIVERSE_BANK_IDS,
        period_dates=_DEFAULT_MONTHLY_PERIOD_DATES,
        profile="scenario_monthly_reference_universe",
    )
    assert (
        living_world_digest(k3, r3)
        == _V1_21_LAST_SCENARIO_UNIVERSE_FIXTURE_DIGEST
    )

    # And the v1.22.1 export section is empty for all three:
    assert build_stress_readout_export_section(k1) == ()
    assert build_stress_readout_export_section(k2) == ()
    assert build_stress_readout_export_section(k3) == ()


# ---------------------------------------------------------------------------
# 3. test_export_bundle_includes_stress_readouts_when_present
# ---------------------------------------------------------------------------


def test_export_bundle_includes_stress_readouts_when_present():
    """When a stress program has been applied, the export section
    is present, has length 1 (v1.21.0a cardinality), and
    surfaces in the JSON output."""
    kernel, _ = _seed_happy_path_kernel()
    section = build_stress_readout_export_section(kernel)
    assert isinstance(section, tuple)
    assert len(section) == 1
    assert isinstance(section[0], dict)

    bundle = _make_minimal_bundle(stress_readout=section)
    d = bundle.to_dict()
    assert "stress_readout" in d
    assert isinstance(d["stress_readout"], list)
    assert len(d["stress_readout"]) == 1

    s = bundle_to_json(bundle)
    parsed = json.loads(s)
    assert "stress_readout" in parsed
    assert isinstance(parsed["stress_readout"], list)
    assert len(parsed["stress_readout"]) == 1


# ---------------------------------------------------------------------------
# 4. test_stress_readout_export_uses_descriptive_keys_only
# ---------------------------------------------------------------------------


def test_stress_readout_export_uses_descriptive_keys_only():
    """The 19 descriptive-only keys pinned by v1.22.0 §3.4 are
    the **only** keys allowed in an entry. No extras."""
    assert len(STRESS_READOUT_ENTRY_REQUIRED_KEYS) == 19
    expected = {
        "stress_program_application_id",
        "stress_program_template_id",
        "as_of_date",
        "total_step_count",
        "resolved_step_count",
        "unresolved_step_count",
        "active_step_ids",
        "unresolved_step_ids",
        "unresolved_reason_labels",
        "is_partial",
        "scenario_driver_template_ids",
        "scenario_application_ids",
        "scenario_context_shift_ids",
        "context_surface_labels",
        "shift_direction_labels",
        "scenario_family_labels",
        "source_context_record_ids",
        "downstream_citation_ids",
        "warnings",
    }
    assert STRESS_READOUT_ENTRY_REQUIRED_KEYS == expected

    kernel, _ = _seed_happy_path_kernel()
    section = build_stress_readout_export_section(kernel)
    assert len(section) == 1
    entry_keys = set(section[0].keys())
    assert entry_keys == expected


# ---------------------------------------------------------------------------
# 5. test_stress_readout_export_rejects_or_omits_forbidden_keys
# ---------------------------------------------------------------------------


def test_stress_readout_export_rejects_or_omits_forbidden_keys():
    """An entry with a forbidden key must be rejected at
    construction time (extra-key whitelist failure)."""
    base_kernel, _ = _seed_happy_path_kernel()
    section = build_stress_readout_export_section(base_kernel)
    assert len(section) == 1
    entry = dict(section[0])
    for forbidden in (
        "impact",
        "outcome",
        "risk_score",
        "amplification",
        "dampening",
        "offset_effect",
        "dominant_stress",
        "net_pressure",
        "composite_risk",
        "forecast",
        "expected_response",
        "prediction",
        "recommendation",
        "expected_return",
        "target_price",
        "buy",
        "sell",
        "order",
        "trade",
        "execution",
        "real_data",
        "japan_calibration",
        "llm_output",
        "aggregate",
        "combined",
        "net",
        "dominant",
        "composite",
        "amplify",
        "dampen",
        "offset",
        "coexist",
    ):
        smuggled = dict(entry)
        smuggled[forbidden] = "x"
        with pytest.raises(ValueError):
            _make_minimal_bundle(stress_readout=[smuggled])

    # Also: every forbidden token from the user's brief is in
    # the runtime forbidden set.
    expected_forbidden = {
        "impact",
        "outcome",
        "risk_score",
        "amplification",
        "dampening",
        "offset_effect",
        "dominant_stress",
        "net_pressure",
        "composite_risk",
        "forecast",
        "expected_response",
        "prediction",
        "recommendation",
        "expected_return",
        "target_price",
        "buy",
        "sell",
        "order",
        "trade",
        "execution",
        "real_data",
        "japan_calibration",
        "llm_output",
        "aggregate",
        "combined",
        "net",
        "dominant",
        "composite",
        "amplify",
        "dampen",
        "offset",
        "coexist",
    }
    assert (
        expected_forbidden
        <= FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS
    )


# ---------------------------------------------------------------------------
# 6. test_stress_readout_export_preserves_partial_application_fields
# ---------------------------------------------------------------------------


def test_stress_readout_export_preserves_partial_application_fields():
    """Partial application MUST surface visibly in the export
    section. ``is_partial`` is True, ``unresolved_step_count`` is
    > 0, ``unresolved_step_ids`` lists the affected ids, and
    ``unresolved_reason_labels`` carries a parallel closed-set
    reason label."""
    kernel, _ = _seed_partial_kernel()
    section = build_stress_readout_export_section(kernel)
    assert len(section) == 1
    entry = section[0]

    assert entry["is_partial"] is True
    assert entry["unresolved_step_count"] >= 1
    assert (
        len(entry["unresolved_step_ids"])
        == entry["unresolved_step_count"]
    )
    assert (
        len(entry["unresolved_reason_labels"])
        == entry["unresolved_step_count"]
    )
    # Reason vocabulary is closed (template_missing or
    # unknown_failure).
    for label in entry["unresolved_reason_labels"]:
        assert label in ("template_missing", "unknown_failure")
    # warnings list carries at least one entry on partial path.
    assert len(entry["warnings"]) >= 1
    # And the partial-application surface is preserved end-to-
    # end in the bundle.
    bundle = _make_minimal_bundle(stress_readout=section)
    parsed = json.loads(bundle_to_json(bundle))
    assert parsed["stress_readout"][0]["is_partial"] is True
    assert (
        parsed["stress_readout"][0]["unresolved_step_count"]
        == entry["unresolved_step_count"]
    )


# ---------------------------------------------------------------------------
# 7. test_stress_readout_export_preserves_order
# ---------------------------------------------------------------------------


def test_stress_readout_export_preserves_order():
    """Same kernel state → byte-identical export section. List-
    typed fields preserve emission order verbatim."""
    kernel_a, _ = _seed_happy_path_kernel()
    kernel_b, _ = _seed_happy_path_kernel()
    section_a = build_stress_readout_export_section(kernel_a)
    section_b = build_stress_readout_export_section(kernel_b)
    assert section_a == section_b

    # The three multiset arrays preserve parallel ordering.
    entry = section_a[0]
    n = len(entry["scenario_context_shift_ids"])
    assert len(entry["context_surface_labels"]) == n
    assert len(entry["shift_direction_labels"]) == n
    assert len(entry["scenario_family_labels"]) == n

    # Two consecutive bundle_to_json calls produce byte-
    # identical JSON.
    bundle = _make_minimal_bundle(stress_readout=section_a)
    s1 = bundle_to_json(bundle)
    s2 = bundle_to_json(bundle)
    assert s1 == s2


# ---------------------------------------------------------------------------
# 8. test_stress_readout_export_does_not_emit_ledger_records
# ---------------------------------------------------------------------------


def test_stress_readout_export_does_not_emit_ledger_records():
    """Building the export section must NOT append any ledger
    record. The v1.22.1 surface is read-only by construction."""
    kernel, _ = _seed_happy_path_kernel()
    before = len(kernel.ledger.records)
    section = build_stress_readout_export_section(kernel)
    assert len(section) == 1
    after = len(kernel.ledger.records)
    assert before == after
    # Project a readout to an entry directly — also emits no
    # ledger record.
    from world.stress_readout import build_stress_field_readout

    receipt_id = section[0]["stress_program_application_id"]
    readout = build_stress_field_readout(
        kernel,
        stress_program_application_id=receipt_id,
    )
    after_project = len(kernel.ledger.records)
    assert after == after_project
    entry = stress_field_readout_to_export_entry(readout)
    after_entry = len(kernel.ledger.records)
    assert after == after_entry
    assert isinstance(entry, dict)


# ---------------------------------------------------------------------------
# 9. test_stress_readout_export_does_not_mutate_source_of_truth_books
# ---------------------------------------------------------------------------


def test_stress_readout_export_does_not_mutate_source_of_truth_books():
    """Building the section must NOT mutate any kernel book.
    Snapshots of every relevant book are byte-identical pre /
    post the call."""
    kernel, _ = _seed_happy_path_kernel()
    before = {
        "scenario_drivers": kernel.scenario_drivers.snapshot(),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_programs": (
            kernel.stress_programs.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "ledger_records": list(kernel.ledger.records),
    }
    _ = build_stress_readout_export_section(kernel)
    # Twice — running again must still leave snapshots intact.
    _ = build_stress_readout_export_section(kernel)
    after = {
        "scenario_drivers": kernel.scenario_drivers.snapshot(),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_programs": (
            kernel.stress_programs.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "ledger_records": list(kernel.ledger.records),
    }
    assert before == after


# ---------------------------------------------------------------------------
# 10. test_browser_bundle_remains_static_json_only
# ---------------------------------------------------------------------------


def test_browser_bundle_remains_static_json_only():
    """The bundle JSON is parseable static JSON. No embedded
    JavaScript, no embedded HTML, no callable references."""
    kernel, _ = _seed_happy_path_kernel()
    section = build_stress_readout_export_section(kernel)
    bundle = _make_minimal_bundle(stress_readout=section)
    text = bundle_to_json(bundle)
    # Round-trips cleanly through json.loads (static JSON only).
    parsed = json.loads(text)
    assert isinstance(parsed, dict)
    # No script / fetch / xhr tokens snuck into the JSON text.
    lower = text.lower()
    for forbidden in (
        "<script",
        "</script",
        "fetch(",
        "xmlhttprequest",
        "eval(",
        "new function(",
    ):
        assert forbidden not in lower

    # The bundle is valid JSON whether or not the section is
    # present (sanity).
    bundle_empty = _make_minimal_bundle()
    parsed_empty = json.loads(bundle_to_json(bundle_empty))
    assert "stress_readout" not in parsed_empty


# ---------------------------------------------------------------------------
# 11. test_no_ui_files_changed_in_v1_22_1
# ---------------------------------------------------------------------------


# v1.20.5 / v1.21.last UI mockup digest is pinned at the file
# byte level. v1.22.1 must NOT touch
# ``examples/ui/fwe_workbench_mockup.html`` (UI changes are
# v1.22.2 territory).
_UI_MOCKUP_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "ui"
    / "fwe_workbench_mockup.html"
)


def test_no_ui_files_changed_in_v1_22_1():
    """v1.22.1 must add no UI changes. The static workbench
    HTML must contain neither a v1.22 active-stresses strip
    nor any v1.22-specific marker. The selectors v1.22.2 will
    add (data-section / data-active-stresses-cell) must be
    **absent** at v1.22.1."""
    assert _UI_MOCKUP_PATH.exists()
    text = _UI_MOCKUP_PATH.read_text(encoding="utf-8")
    # v1.22.2 selectors and wording must be absent at v1.22.1.
    assert 'data-section="active-stresses"' not in text
    assert "data-active-stresses-cell" not in text
    assert "Active stresses" not in text
    assert "Read-only stress readout" not in text
    assert "Multiset projection" not in text


# ---------------------------------------------------------------------------
# 12. test_no_interaction_inference_strings_in_export
# ---------------------------------------------------------------------------


def test_no_interaction_inference_strings_in_export():
    """The exported JSON must not contain the deferred v1.21.0a
    interaction-label tokens as literal string values
    (``amplify`` / ``dampen`` / ``offset`` / ``coexist``) and
    must not contain composition-reduction tokens
    (``aggregate`` / ``combined`` / ``net`` / ``dominant`` /
    ``composite``)."""
    # Happy-path bundle.
    kernel_h, _ = _seed_happy_path_kernel()
    section_h = build_stress_readout_export_section(kernel_h)
    bundle_h = _make_minimal_bundle(stress_readout=section_h)
    parsed_h = json.loads(bundle_to_json(bundle_h))

    # Partial-application bundle.
    kernel_p, _ = _seed_partial_kernel()
    section_p = build_stress_readout_export_section(kernel_p)
    bundle_p = _make_minimal_bundle(stress_readout=section_p)
    parsed_p = json.loads(bundle_to_json(bundle_p))

    forbidden_value_tokens = (
        "amplify",
        "dampen",
        "offset",
        "coexist",
        "aggregate",
        "combined",
        "net",
        "dominant",
        "composite",
    )
    for parsed in (parsed_h, parsed_p):
        for entry in parsed.get("stress_readout", []):
            for k, v in entry.items():
                if isinstance(v, str):
                    for tok in forbidden_value_tokens:
                        assert v.lower() != tok.lower(), (
                            f"{k!r} = {v!r} equals forbidden "
                            f"interaction-/composition-token "
                            f"{tok!r}"
                        )
                elif isinstance(v, list):
                    for item in v:
                        if not isinstance(item, str):
                            continue
                        for tok in forbidden_value_tokens:
                            assert (
                                item.lower() != tok.lower()
                            ), (
                                f"{k!r} contains forbidden "
                                f"interaction-/composition-"
                                f"token {tok!r}"
                            )


# ---------------------------------------------------------------------------
# 13. test_no_price_forecast_recommendation_strings_in_export
# ---------------------------------------------------------------------------


def test_no_price_forecast_recommendation_strings_in_export():
    """The exported JSON must not contain the v1.18.0 / v1.19.0
    price / forecast / advice / outcome / impact / risk-score
    tokens as literal string values. The v1.22.1 export carries
    only descriptive plain-id citations and closed-set labels;
    no outcome / forecast / recommendation language is emitted
    by construction."""
    kernel, _ = _seed_happy_path_kernel()
    section = build_stress_readout_export_section(kernel)
    bundle = _make_minimal_bundle(stress_readout=section)
    parsed = json.loads(bundle_to_json(bundle))
    forbidden_value_tokens = (
        "impact",
        "outcome",
        "risk_score",
        "amplification",
        "dampening",
        "offset_effect",
        "dominant_stress",
        "net_pressure",
        "composite_risk",
        "forecast",
        "expected_response",
        "prediction",
        "recommendation",
        "expected_return",
        "target_price",
        "real_data",
        "japan_calibration",
        "llm_output",
    )
    for entry in parsed.get("stress_readout", []):
        for k, v in entry.items():
            if isinstance(v, str):
                for tok in forbidden_value_tokens:
                    assert v.lower() != tok.lower(), (
                        f"{k!r} = {v!r} equals forbidden token "
                        f"{tok!r}"
                    )
            elif isinstance(v, list):
                for item in v:
                    if not isinstance(item, str):
                        continue
                    for tok in forbidden_value_tokens:
                        assert item.lower() != tok.lower(), (
                            f"{k!r} contains forbidden token "
                            f"{tok!r}"
                        )
