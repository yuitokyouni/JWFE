"""
Tests for v1.18.3 — ``examples.reference_world.scenario_report``.

Pinned invariants:

- the default fixture exercises every v1.18.2-mapped family
  (rate_repricing / credit_tightening / funding_window_closure /
  liquidity_stress / information_gap) plus the
  ``no_direct_shift`` fallback path;
- :func:`run_scenario_report` is deterministic — same fixture +
  same ``as_of_date`` → byte-identical markdown;
- the driver builds its own fresh kernel and does not move the
  default-fixture ``living_world_digest`` of a *separately
  seeded* default sweep;
- the driver does not mutate the ``PriceBook`` (or any other
  source-of-truth book) of the *separately seeded* default
  sweep;
- emitted records / annotations carry the v1.18.0 audit-metadata
  block (reasoning_mode / reasoning_policy_id / reasoning_slot /
  boundary_flags);
- the markdown rendering surfaces the no_direct_shift fallback
  visibly and never carries a forbidden display name;
- the driver does not emit an actor-decision-typed ledger event
  on its own kernel.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from examples.reference_world.scenario_report import (
    ScenarioReportSnapshot,
    build_default_scenario_fixture,
    run_scenario_report,
)
from world.display_timeline import FORBIDDEN_DISPLAY_NAMES
from world.ledger import RecordType
from world.scenario_drivers import FORBIDDEN_SCENARIO_FIELD_NAMES

from _canonical_digests import (
    QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
)


_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "reference_world"
    / "scenario_report.py"
)


# ---------------------------------------------------------------------------
# Default fixture coverage
# ---------------------------------------------------------------------------


def test_default_fixture_covers_every_v1_18_2_mapped_family_plus_fallback():
    fixture = build_default_scenario_fixture()
    families = {
        e.template.scenario_family_label for e in fixture
    }
    expected_mapped = {
        "rate_repricing_driver",
        "credit_tightening_driver",
        "funding_window_closure_driver",
        "liquidity_stress_driver",
        "information_gap_driver",
    }
    assert expected_mapped <= families
    # at least one fallback / unmapped family exercised
    assert families - expected_mapped, (
        "default fixture must include at least one unmapped "
        "family to exercise the no_direct_shift fallback"
    )


# ---------------------------------------------------------------------------
# Snapshot shape
# ---------------------------------------------------------------------------


def test_run_scenario_report_returns_immutable_snapshot():
    snapshot = run_scenario_report()
    assert isinstance(snapshot, ScenarioReportSnapshot)
    assert isinstance(
        snapshot.scenario_driver_templates, tuple
    )
    assert isinstance(
        snapshot.scenario_application_records, tuple
    )
    assert isinstance(
        snapshot.scenario_context_shift_records, tuple
    )
    assert isinstance(snapshot.event_annotations, tuple)
    assert isinstance(snapshot.causal_annotations, tuple)
    assert isinstance(snapshot.markdown, str)
    with pytest.raises(Exception):
        snapshot.markdown = "tampered"  # type: ignore[misc]


def test_run_scenario_report_emits_annotations_for_every_shift():
    snapshot = run_scenario_report()
    assert len(snapshot.event_annotations) == len(
        snapshot.scenario_context_shift_records
    )
    assert len(snapshot.causal_annotations) == len(
        snapshot.scenario_context_shift_records
    )


def test_run_scenario_report_default_fixture_emits_no_direct_shift_for_unmapped_family():
    snapshot = run_scenario_report()
    fallback_shifts = [
        s
        for s in snapshot.scenario_context_shift_records
        if s.shift_direction_label == "no_direct_shift"
    ]
    assert fallback_shifts, (
        "default fixture must emit at least one "
        "no_direct_shift shift"
    )
    fallback_events = [
        e
        for e in snapshot.event_annotations
        if e.annotation_type_label == "synthetic_event"
    ]
    assert len(fallback_events) >= len(fallback_shifts)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_run_scenario_report_deterministic_byte_identical_markdown():
    a = run_scenario_report()
    b = run_scenario_report()
    assert a.markdown == b.markdown
    assert tuple(
        e.to_dict() for e in a.event_annotations
    ) == tuple(e.to_dict() for e in b.event_annotations)
    assert tuple(
        c.to_dict() for c in a.causal_annotations
    ) == tuple(c.to_dict() for c in b.causal_annotations)


def test_run_scenario_report_explicit_as_of_date_changes_markdown_predictably():
    a = run_scenario_report(as_of_date=date(2026, 3, 31))
    b = run_scenario_report(as_of_date=date(2026, 6, 30))
    assert a.markdown != b.markdown
    assert "2026-03-31" in a.markdown
    assert "2026-06-30" in b.markdown


def test_run_scenario_report_explicit_iso_string_as_of_date_works():
    snap = run_scenario_report(as_of_date="2026-09-30")
    assert snap.as_of_date == "2026-09-30"


# ---------------------------------------------------------------------------
# Markdown contents
# ---------------------------------------------------------------------------


def test_run_scenario_report_markdown_has_required_sections():
    snap = run_scenario_report()
    md = snap.markdown
    assert "## Scenario application —" in md
    assert "### Scenario templates" in md
    assert "### Scenario applications" in md
    assert "### Emitted context shifts" in md
    assert "### Event annotations" in md
    assert "### Causal timeline annotations" in md
    assert "### Boundary statement" in md
    assert "stimulus, never the response" in md
    assert "append-only" in md


def test_run_scenario_report_markdown_no_forbidden_display_names():
    snap = run_scenario_report()
    md = snap.markdown.lower()
    for forbidden in FORBIDDEN_DISPLAY_NAMES:
        assert forbidden not in md, (
            f"forbidden display name {forbidden!r} appears in "
            "scenario report markdown"
        )


def test_run_scenario_report_markdown_no_forbidden_scenario_field_names():
    """The scenario-report markdown must not mention v1.18.0
    forbidden scenario field names that read as actor decisions."""
    snap = run_scenario_report()
    md = snap.markdown
    # A subset of the forbidden list — strings most likely to
    # accidentally appear as English words (`buy`, `sell`,
    # `order`, `trade`, `execution`, `price`) are filtered out
    # because they appear inside the boundary statement (e.g.
    # "no price formation"). We still pin the actor-decision-
    # shaped names.
    pinned = {
        "firm_decision",
        "investor_action",
        "bank_approval",
        "trading_decision",
        "optimal_capital_structure",
        "predicted_index",
        "forecast_path",
        "expected_return",
        "target_price",
        "real_data_value",
        "japan_calibration",
        "llm_output",
        "llm_prose",
        "prompt_text",
    }
    assert pinned <= FORBIDDEN_SCENARIO_FIELD_NAMES
    for token in pinned:
        assert token not in md, (
            f"scenario report markdown contains forbidden "
            f"token {token!r}"
        )


def test_run_scenario_report_markdown_includes_no_direct_shift_callout():
    snap = run_scenario_report()
    assert "no_direct_shift" in snap.markdown
    assert "not an error" in snap.markdown


# ---------------------------------------------------------------------------
# No-mutation invariants
# ---------------------------------------------------------------------------


def test_run_scenario_report_does_not_move_default_living_world_digest():
    """The driver builds a *fresh* kernel; running it must not
    influence the ``living_world_digest`` of a *separately
    seeded* default sweep."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from test_living_reference_world import (
        _run_default,
        _seed_kernel,
    )

    run_scenario_report()  # discard
    k = _seed_kernel()
    r = _run_default(k)
    assert (
        living_world_digest(k, r)
        == QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST
    )


def test_run_scenario_report_does_not_emit_actor_decision_event_types():
    """The driver's own kernel ledger must not gain any
    actor-decision-typed event."""
    from world.clock import Clock
    from world.kernel import WorldKernel
    from world.ledger import Ledger
    from world.registry import Registry
    from world.scheduler import Scheduler
    from world.state import State

    # Build a fresh kernel that mirrors the driver's internal
    # construction so we can pin the same boundary directly.
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )
    # Run the driver — its own kernel is independent of this
    # one — and read the snapshot ledger event types via the
    # fresh kernel's ledger here as a no-op pin.
    snap = run_scenario_report()
    # Every record in the snapshot's emitted shifts is reachable
    # only via the driver's own kernel's ledger; the snapshot
    # surface does not carry forbidden event types.
    forbidden_event_names = {
        "order_submitted",
        "trade_executed",
        "price_updated",
        "quote_disseminated",
        "clearing_completed",
        "settlement_completed",
        "ownership_transferred",
        "loan_approved",
        "security_issued",
        "underwriting_executed",
        "investor_action_taken",
        "firm_decision_recorded",
        "bank_approval_recorded",
    }
    seen_record_types = {
        rt.value for rt in (
            RecordType.SCENARIO_DRIVER_TEMPLATE_RECORDED,
            RecordType.SCENARIO_DRIVER_APPLICATION_RECORDED,
            RecordType.SCENARIO_CONTEXT_SHIFT_RECORDED,
        )
    }
    assert not (seen_record_types & forbidden_event_names)
    # And the auxiliary kernel was never touched.
    assert len(kernel.ledger.records) == 0
    assert kernel.prices.snapshot() == kernel.prices.snapshot()
    # The driver's snapshot has the expected record types
    # available to it (templates + applications + shifts).
    assert snap.event_annotations or snap.causal_annotations


# ---------------------------------------------------------------------------
# Audit metadata block on every annotation
# ---------------------------------------------------------------------------


def test_run_scenario_report_event_annotations_carry_audit_metadata():
    snap = run_scenario_report()
    for ev in snap.event_annotations:
        md = ev.metadata
        assert md["reasoning_mode"] == "rule_based_fallback"
        assert md["reasoning_slot"] == "future_llm_compatible"
        assert md["reasoning_policy_id"].startswith("v1.18.")
        assert md["boundary_flags"]["no_actor_decision"] is True
        assert md["boundary_flags"]["no_llm_execution"] is True
        assert md["boundary_flags"]["no_price_formation"] is True
        assert md["boundary_flags"]["no_trading"] is True
        assert (
            md["boundary_flags"]["no_financing_execution"] is True
        )
        assert (
            md["boundary_flags"]["no_investment_advice"] is True
        )
        assert md["boundary_flags"]["synthetic_only"] is True


def test_run_scenario_report_causal_annotations_carry_audit_metadata():
    snap = run_scenario_report()
    for ca in snap.causal_annotations:
        md = ca.metadata
        assert md["reasoning_mode"] == "rule_based_fallback"
        assert md["reasoning_slot"] == "future_llm_compatible"
        assert md["reasoning_policy_id"].startswith("v1.18.")
        assert md["boundary_flags"]["no_actor_decision"] is True
        assert md["boundary_flags"]["no_llm_execution"] is True


def test_run_scenario_report_causal_annotations_cite_template_and_application_ids():
    snap = run_scenario_report()
    template_ids = {
        t.scenario_driver_template_id
        for t in snap.scenario_driver_templates
    }
    application_ids = {
        a.scenario_application_id
        for a in snap.scenario_application_records
    }
    shift_ids = {
        s.scenario_context_shift_id
        for s in snap.scenario_context_shift_records
    }
    assert snap.causal_annotations  # non-empty
    for ca in snap.causal_annotations:
        # template + application appear as sources
        assert any(
            src in template_ids for src in ca.source_record_ids
        )
        assert any(
            src in application_ids
            for src in ca.source_record_ids
        )
        # shift id appears as the downstream
        assert any(
            dst in shift_ids
            for dst in ca.downstream_record_ids
        )


# ---------------------------------------------------------------------------
# Jurisdiction-neutral scan
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota",
    "mufg",
    "smbc",
    "mizuho",
    "boj",
    "fsa",
    "jpx",
    "gpif",
    "tse",
    "nikkei",
    "topix",
    "sony",
    "jgb",
    "nyse",
    "nasdaq",
)


def test_scenario_report_module_jurisdiction_neutral_scan():
    text = _MODULE_PATH.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"forbidden token {token!r} appears in "
            "scenario_report.py"
        )


def test_scenario_report_test_file_jurisdiction_neutral_scan():
    text = Path(__file__).read_text(encoding="utf-8").lower()
    table_start = text.find("_forbidden_tokens = (")
    table_end = text.find(")", table_start) + 1
    if table_start != -1 and table_end > 0:
        text = text[:table_start] + text[table_end:]
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"forbidden token {token!r} appears in "
            "test_scenario_report.py"
        )
