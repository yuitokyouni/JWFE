"""
Tests for v1.8.15 ledger trace report.

Pins the v1.8.15 contract end-to-end:

- ``build_endogenous_chain_report`` produces an immutable
  ``LedgerTraceReport`` whose record_count, ordered ids, and
  bucketed ids match the kernel ledger slice produced by the
  v1.8.14 chain.
- ``record_type_counts`` sums to ``record_count`` and is sorted
  for determinism.
- ``ordered_record_ids`` matches ``chain_result.created_record_ids``
  byte-identically when the ledger has not been touched.
- The investor / bank / shared / -only refs are carried through
  from the chain result verbatim.
- ``to_dict`` and ``render_endogenous_chain_markdown`` are
  deterministic across two fresh kernels seeded identically.
- The reporter is **read-only**: no kernel book grows, no ledger
  record is appended, no signal / menu / selection / run is
  added.
- Validation is permissive: a slice / chain mismatch produces a
  ``warnings`` entry but the report still builds. A partial
  chain (missing event type) does the same.
- The CLI prints both the operational trace and the Markdown
  report without crashing.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from datetime import date
from typing import Any

import pytest

from world.clock import Clock
from world.exposures import ExposureRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.ledger_trace_report import (
    LedgerTraceReport,
    build_endogenous_chain_report,
    render_endogenous_chain_markdown,
)
from world.reference_chain import (
    EndogenousChainResult,
    run_reference_endogenous_chain,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State
from world.variables import ReferenceVariableSpec, VariableObservation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FIRM = "firm:reference_manufacturer_a"
_INVESTOR = "investor:reference_pension_a"
_BANK = "bank:reference_megabank_a"
_AS_OF = "2026-04-30"


_REFERENCE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("variable:reference_fx_pair_a", "fx"),
    ("variable:reference_long_rate_10y", "rates"),
    ("variable:reference_land_index_a", "real_estate"),
)


_REFERENCE_EXPOSURES: tuple[ExposureRecord, ...] = (
    ExposureRecord(
        exposure_id="exposure:investor_a:fx",
        subject_id=_INVESTOR,
        subject_type="investor",
        variable_id="variable:reference_fx_pair_a",
        exposure_type="translation",
        metric="portfolio_translation_exposure",
        direction="mixed",
        magnitude=0.4,
    ),
    ExposureRecord(
        exposure_id="exposure:bank_a:funding",
        subject_id=_BANK,
        subject_type="bank",
        variable_id="variable:reference_long_rate_10y",
        exposure_type="funding_cost",
        metric="debt_service_burden",
        direction="positive",
        magnitude=0.5,
    ),
    ExposureRecord(
        exposure_id="exposure:bank_a:collateral",
        subject_id=_BANK,
        subject_type="bank",
        variable_id="variable:reference_land_index_a",
        exposure_type="collateral",
        metric="collateral_value",
        direction="positive",
        magnitude=0.4,
    ),
)


def _seed_kernel() -> WorldKernel:
    k = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 4, 30)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )
    for vid, vgroup in _REFERENCE_VARIABLES:
        k.variables.add_variable(
            ReferenceVariableSpec(
                variable_id=vid,
                variable_name=vid,
                variable_group=vgroup,
                variable_type="level",
                source_space_id="external",
                canonical_unit="index",
                frequency="QUARTERLY",
                observation_kind="released",
            )
        )
        k.variables.add_observation(
            VariableObservation(
                observation_id=f"obs:{vid}:2026Q1",
                variable_id=vid,
                as_of_date="2026-04-15",
                value=100.0,
                unit="index",
                vintage_id="2026Q1_initial",
            )
        )
    for record in _REFERENCE_EXPOSURES:
        k.exposures.add_exposure(record)
    return k


def _run_chain(k: WorldKernel) -> EndogenousChainResult:
    return run_reference_endogenous_chain(
        k,
        firm_id=_FIRM,
        investor_id=_INVESTOR,
        bank_id=_BANK,
        as_of_date=_AS_OF,
    )


def _seeded_chain() -> tuple[WorldKernel, EndogenousChainResult]:
    k = _seed_kernel()
    return k, _run_chain(k)


# ---------------------------------------------------------------------------
# Report shape
# ---------------------------------------------------------------------------


def test_build_returns_immutable_report():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    assert isinstance(report, LedgerTraceReport)
    with pytest.raises(Exception):
        report.report_id = "tampered"  # type: ignore[misc]


def test_record_count_matches_ledger_slice():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    expected = chain.ledger_record_count_after - chain.ledger_record_count_before
    assert report.record_count == expected
    assert report.start_record_index == chain.ledger_record_count_before
    assert report.end_record_index == chain.ledger_record_count_after


def test_ordered_record_ids_match_chain_created_record_ids():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    assert report.ordered_record_ids == chain.created_record_ids


def test_record_type_counts_sum_to_record_count():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    total = sum(count for _, count in report.record_type_counts)
    assert total == report.record_count


def test_record_type_counts_are_sorted_for_determinism():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    keys = [event_type for event_type, _ in report.record_type_counts]
    assert keys == sorted(keys)


def test_bucketed_ids_match_chain_ids():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    # Routine runs: corporate + investor review + bank review.
    assert chain.corporate_routine_run_id in report.routine_run_ids
    assert chain.investor_review_run_id in report.routine_run_ids
    assert chain.bank_review_run_id in report.routine_run_ids
    assert len(report.routine_run_ids) == 3
    # Signals.
    assert chain.corporate_signal_id in report.signal_ids
    assert chain.investor_review_signal_id in report.signal_ids
    assert chain.bank_review_signal_id in report.signal_ids
    assert len(report.signal_ids) == 3
    # Menus.
    assert chain.investor_menu_id in report.menu_ids
    assert chain.bank_menu_id in report.menu_ids
    assert len(report.menu_ids) == 2
    # Selections.
    assert chain.investor_selection_id in report.selection_ids
    assert chain.bank_selection_id in report.selection_ids
    assert len(report.selection_ids) == 2


def test_selection_refs_carried_through_verbatim():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    assert report.investor_selected_refs == chain.investor_selected_refs
    assert report.bank_selected_refs == chain.bank_selected_refs
    assert report.shared_selected_refs == chain.shared_selected_refs
    assert report.investor_only_refs == chain.investor_only_selected_refs
    assert report.bank_only_refs == chain.bank_only_selected_refs


def test_default_report_id_uses_chain_name_and_as_of_date():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    assert report.report_id == f"report:reference_endogenous_chain:{_AS_OF}"
    assert report.chain_name == "reference_endogenous_chain"


def test_explicit_report_id_and_chain_name_honored():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(
        k, chain, chain_name="custom_chain", report_id="report:custom_id"
    )
    assert report.report_id == "report:custom_id"
    assert report.chain_name == "custom_chain"


def test_metadata_includes_chain_audit_fields():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    md = report.metadata
    assert md["renderer"] == "v1.8.15"
    assert md["format_version"] == "1"
    assert md["chain_corporate_status"] == chain.corporate_status
    assert md["chain_investor_review_status"] == chain.investor_review_status
    assert md["chain_bank_review_status"] == chain.bank_review_status
    assert md["chain_as_of_date"] == chain.as_of_date
    assert md["chain_firm_id"] == chain.firm_id


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_to_dict_is_deterministic_across_fresh_kernels():
    a_kernel, a_chain = _seeded_chain()
    b_kernel, b_chain = _seeded_chain()
    a = build_endogenous_chain_report(a_kernel, a_chain).to_dict()
    b = build_endogenous_chain_report(b_kernel, b_chain).to_dict()
    assert a == b


def test_markdown_is_deterministic_across_fresh_kernels():
    a_kernel, a_chain = _seeded_chain()
    b_kernel, b_chain = _seeded_chain()
    a = render_endogenous_chain_markdown(
        build_endogenous_chain_report(a_kernel, a_chain)
    )
    b = render_endogenous_chain_markdown(
        build_endogenous_chain_report(b_kernel, b_chain)
    )
    assert a == b


def test_markdown_contains_expected_sections():
    k, chain = _seeded_chain()
    md = render_endogenous_chain_markdown(
        build_endogenous_chain_report(k, chain)
    )
    for heading in (
        "# reference_endogenous_chain",
        "## Records by event type",
        "## Routine runs",
        "## Signals",
        "## Attention",
        "## Selection overlap",
        "## Warnings",
    ):
        assert heading in md
    # Expected event-type counts appear (we know the canonical
    # chain produces these).
    assert "`routine_run_recorded`: 3" in md
    assert "`signal_added`: 3" in md
    assert "`observation_menu_created`: 2" in md
    assert "`observation_set_selected`: 2" in md


# ---------------------------------------------------------------------------
# Validation / warnings
# ---------------------------------------------------------------------------


def test_canonical_chain_produces_no_warnings():
    k, chain = _seeded_chain()
    report = build_endogenous_chain_report(k, chain)
    assert report.warnings == ()


def test_report_warns_when_ledger_grows_after_chain():
    """A record appended after the chain returns invalidates the
    chain's ``created_record_ids`` cross-check; the report should
    note this rather than crash."""
    k, chain = _seeded_chain()
    # Mutate chain's recorded end index forward to simulate someone
    # appending records and re-using a stale chain result. We don't
    # mutate the kernel itself; we mutate the result's view.
    object.__setattr__(
        chain, "ledger_record_count_after", chain.ledger_record_count_after + 5
    )
    report = build_endogenous_chain_report(k, chain)
    assert any(
        "ledger.records has length" in w or "slice truncated" in w
        for w in report.warnings
    )


def test_report_warns_when_chain_count_does_not_match_slice():
    """A chain result whose created_record_count diverges from the
    slice length triggers a warning but does not crash."""
    k, chain = _seeded_chain()
    object.__setattr__(
        chain, "created_record_ids", chain.created_record_ids[:-1]
    )
    report = build_endogenous_chain_report(k, chain)
    assert any(
        "ledger slice length" in w or "do not match" in w
        for w in report.warnings
    )


def test_report_rejects_kernel_none():
    _, chain = _seeded_chain()
    with pytest.raises(ValueError):
        build_endogenous_chain_report(None, chain)


def test_report_rejects_non_chain_result():
    k = _seed_kernel()
    with pytest.raises(TypeError):
        build_endogenous_chain_report(k, {"not": "a chain result"})


# ---------------------------------------------------------------------------
# Read-only guarantee
# ---------------------------------------------------------------------------


def _capture_state(k: WorldKernel) -> dict[str, Any]:
    return {
        "valuations": k.valuations.snapshot(),
        "prices": k.prices.snapshot(),
        "ownership": k.ownership.snapshot(),
        "contracts": k.contracts.snapshot(),
        "constraints": k.constraints.snapshot(),
        "exposures": k.exposures.snapshot(),
        "variables": k.variables.snapshot(),
        "institutions": k.institutions.snapshot(),
        "external_processes": k.external_processes.snapshot(),
        "relationships": k.relationships.snapshot(),
        "attention": k.attention.snapshot(),
        "routines": k.routines.snapshot(),
        "interactions": k.interactions.snapshot(),
        "ledger_length": len(k.ledger.records),
        "signals": len(k.signals.all_signals()),
    }


def test_build_does_not_mutate_kernel():
    k, chain = _seeded_chain()
    before = _capture_state(k)
    report = build_endogenous_chain_report(k, chain)
    render_endogenous_chain_markdown(report)
    report.to_dict()
    after = _capture_state(k)
    assert before == after


# ---------------------------------------------------------------------------
# Schema-level validation in __post_init__
# ---------------------------------------------------------------------------


def test_report_rejects_inconsistent_indices():
    with pytest.raises(ValueError):
        LedgerTraceReport(
            report_id="r:1",
            chain_name="c",
            start_record_index=5,
            end_record_index=3,
            record_count=0,
            record_type_counts=(),
            ordered_record_ids=(),
            ordered_record_types=(),
            routine_run_ids=(),
            signal_ids=(),
            menu_ids=(),
            selection_ids=(),
        )


def test_report_rejects_record_count_mismatch():
    with pytest.raises(ValueError):
        LedgerTraceReport(
            report_id="r:1",
            chain_name="c",
            start_record_index=0,
            end_record_index=5,
            record_count=10,
            record_type_counts=(),
            ordered_record_ids=("a",) * 10,
            ordered_record_types=("x",) * 10,
            routine_run_ids=(),
            signal_ids=(),
            menu_ids=(),
            selection_ids=(),
        )


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_smoke_prints_trace_and_markdown():
    from examples.reference_world import run_endogenous_chain as cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["--markdown"])
    out = buf.getvalue()
    assert "[corporate]" in out
    assert "[review]" in out
    assert "# reference_endogenous_chain" in out
    assert "## Records by event type" in out
    # Compact summary substrings.
    assert re.search(r"shared\s*=\s*1", out)


def test_cli_smoke_no_markdown_default():
    from examples.reference_world import run_endogenous_chain as cli

    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main([])
    out = buf.getvalue()
    assert "[corporate]" in out
    # Without --markdown, the report should not appear.
    assert "# reference_endogenous_chain" not in out
