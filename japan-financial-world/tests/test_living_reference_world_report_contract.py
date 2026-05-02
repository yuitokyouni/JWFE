"""
v1.9.1-prep — Living World Trace Report contract test.

This file does not test the v1.9.1 reporter (which has not been
implemented). It pins the v1.9.0 result schema invariants the
future reporter will rely on, so a refactor or accidental schema
change fails here before it can break the v1.9.1 reporter.

Every assertion below corresponds to an item in
``docs/v1_9_living_world_report_contract.md``.

If a v1.9.x change has to break one of these invariants, the right
process is:

1. update the contract doc;
2. update this test;
3. update the v1.9.1 reporter (if shipped) to match.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date

from world.clock import Clock
from world.exposures import ExposureRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.reference_living_world import (
    LivingReferencePeriodSummary,
    LivingReferenceWorldResult,
    run_living_reference_world,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State
from world.variables import ReferenceVariableSpec, VariableObservation


# ---------------------------------------------------------------------------
# Required-field contract
# ---------------------------------------------------------------------------


_REQUIRED_RESULT_FIELDS: frozenset[str] = frozenset(
    {
        "run_id",
        "period_count",
        "firm_ids",
        "investor_ids",
        "bank_ids",
        "created_record_ids",
        "per_period_summaries",
        "ledger_record_count_before",
        "ledger_record_count_after",
        "metadata",
    }
)


_REQUIRED_PERIOD_FIELDS: frozenset[str] = frozenset(
    {
        "period_id",
        "as_of_date",
        "corporate_signal_ids",
        "investor_menu_ids",
        "bank_menu_ids",
        "investor_selection_ids",
        "bank_selection_ids",
        "investor_review_signal_ids",
        "bank_review_signal_ids",
        "record_count_created",
        "metadata",
    }
)


def test_living_reference_world_result_is_a_dataclass():
    assert is_dataclass(LivingReferenceWorldResult)


def test_living_reference_period_summary_is_a_dataclass():
    assert is_dataclass(LivingReferencePeriodSummary)


def test_living_reference_world_result_has_every_required_field():
    actual = {f.name for f in fields(LivingReferenceWorldResult)}
    missing = _REQUIRED_RESULT_FIELDS - actual
    assert missing == set(), f"LivingReferenceWorldResult missing: {missing}"


def test_living_reference_period_summary_has_every_required_field():
    actual = {f.name for f in fields(LivingReferencePeriodSummary)}
    missing = _REQUIRED_PERIOD_FIELDS - actual
    assert missing == set(), f"LivingReferencePeriodSummary missing: {missing}"


# ---------------------------------------------------------------------------
# End-to-end contract: every report-critical invariant
# ---------------------------------------------------------------------------


_FIRMS: tuple[str, ...] = (
    "firm:reference_manufacturer_a",
    "firm:reference_retailer_b",
    "firm:reference_utility_c",
)

_INVESTORS: tuple[str, ...] = (
    "investor:reference_pension_a",
    "investor:reference_growth_fund_a",
)

_BANKS: tuple[str, ...] = (
    "bank:reference_megabank_a",
    "bank:reference_regional_b",
)


def _seed_kernel() -> WorldKernel:
    k = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    variables: tuple[tuple[str, str], ...] = (
        ("variable:reference_fx_pair_a", "fx"),
        ("variable:reference_long_rate_10y", "rates"),
        ("variable:reference_credit_spread_a", "credit"),
        ("variable:reference_land_index_a", "real_estate"),
        ("variable:reference_electricity_price_a", "energy_power"),
        ("variable:reference_cpi_yoy", "inflation"),
    )
    obs_dates = (
        "2026-01-15",
        "2026-04-15",
        "2026-07-15",
        "2026-10-15",
    )
    for vid, vgroup in variables:
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
        for q in obs_dates:
            k.variables.add_observation(
                VariableObservation(
                    observation_id=f"obs:{vid}:{q}",
                    variable_id=vid,
                    as_of_date=q,
                    value=100.0,
                    unit="index",
                    vintage_id=f"{q}_initial",
                )
            )

    for inv in _INVESTORS:
        k.exposures.add_exposure(
            ExposureRecord(
                exposure_id=f"exposure:{inv}:fx",
                subject_id=inv,
                subject_type="investor",
                variable_id="variable:reference_fx_pair_a",
                exposure_type="translation",
                metric="portfolio_translation_exposure",
                direction="mixed",
                magnitude=0.4,
            )
        )
        k.exposures.add_exposure(
            ExposureRecord(
                exposure_id=f"exposure:{inv}:rates",
                subject_id=inv,
                subject_type="investor",
                variable_id="variable:reference_long_rate_10y",
                exposure_type="discount_rate",
                metric="valuation_discount_rate",
                direction="negative",
                magnitude=0.3,
            )
        )
    for bnk in _BANKS:
        k.exposures.add_exposure(
            ExposureRecord(
                exposure_id=f"exposure:{bnk}:funding",
                subject_id=bnk,
                subject_type="bank",
                variable_id="variable:reference_long_rate_10y",
                exposure_type="funding_cost",
                metric="debt_service_burden",
                direction="positive",
                magnitude=0.5,
            )
        )
        k.exposures.add_exposure(
            ExposureRecord(
                exposure_id=f"exposure:{bnk}:collateral",
                subject_id=bnk,
                subject_type="bank",
                variable_id="variable:reference_land_index_a",
                exposure_type="collateral",
                metric="collateral_value",
                direction="positive",
                magnitude=0.4,
            )
        )

    return k


def _run() -> tuple[WorldKernel, LivingReferenceWorldResult]:
    k = _seed_kernel()
    r = run_living_reference_world(
        k,
        firm_ids=_FIRMS,
        investor_ids=_INVESTORS,
        bank_ids=_BANKS,
    )
    return k, r


# ---------------------------------------------------------------------------
# Ledger slice cross-check (the v1.8.15-style invariant the reporter
# will assert at render time as a warning candidate).
# ---------------------------------------------------------------------------


def test_created_record_ids_match_ledger_slice():
    k, r = _run()
    actual = tuple(
        rec.object_id
        for rec in k.ledger.records[
            r.ledger_record_count_before : r.ledger_record_count_after
        ]
    )
    assert actual == r.created_record_ids


def test_per_period_record_counts_plus_infra_sum_to_total_slice_length():
    """v1.9.0 does idempotent infra registration (interactions,
    per-firm corporate routines, per-actor profiles + review
    routines) **before** the period loop. Those writes form an
    "infra prelude" between
    ``result.ledger_record_count_before`` and
    ``per_period_summaries[0].metadata["ledger_record_count_before"]``.

    The contract: per-period sums + infra-prelude = total chain
    delta. The v1.9.1 reporter must surface the prelude in the
    Setup summary section. See
    ``docs/v1_9_living_world_report_contract.md``.
    """
    _, r = _run()
    per_period_total = sum(
        ps.record_count_created for ps in r.per_period_summaries
    )
    chain_total = r.ledger_record_count_after - r.ledger_record_count_before
    infra_count = (
        r.per_period_summaries[0].metadata["ledger_record_count_before"]
        - r.ledger_record_count_before
    )
    assert per_period_total + infra_count == chain_total
    assert chain_total == r.created_record_count
    # The prelude must be non-negative; on the canonical fixture
    # it is strictly positive (interactions + routines + profiles).
    assert infra_count >= 0


def test_per_period_metadata_carries_chronological_ledger_indices():
    """Each period summary's metadata must expose the per-period
    ledger slice so the v1.9.1 reporter can re-walk one period's
    records without re-walking the entire run. The first period's
    ``ledger_record_count_before`` may sit *after* the run's
    ``ledger_record_count_before`` because of the infra prelude;
    from period 1 onward the chronology is contiguous."""
    _, r = _run()
    period_one_before = r.per_period_summaries[0].metadata[
        "ledger_record_count_before"
    ]
    assert period_one_before >= r.ledger_record_count_before

    prev_after = period_one_before
    for ps in r.per_period_summaries:
        before = ps.metadata["ledger_record_count_before"]
        after = ps.metadata["ledger_record_count_after"]
        assert before == prev_after
        assert after - before == ps.record_count_created
        prev_after = after
    assert prev_after == r.ledger_record_count_after


# ---------------------------------------------------------------------------
# Selection refs are reachable for the set-difference computation
# the v1.9.1 reporter will perform.
# ---------------------------------------------------------------------------


def test_investor_selection_refs_resolvable_for_set_difference():
    k, r = _run()
    for ps in r.per_period_summaries:
        for sel_id in ps.investor_selection_ids:
            sel = k.attention.get_selection(sel_id)
            # Selected refs is a tuple of strings — exactly what a
            # set-difference computation needs.
            assert isinstance(sel.selected_refs, tuple)
            for ref in sel.selected_refs:
                assert isinstance(ref, str) and ref


def test_bank_selection_refs_resolvable_for_set_difference():
    k, r = _run()
    for ps in r.per_period_summaries:
        for sel_id in ps.bank_selection_ids:
            sel = k.attention.get_selection(sel_id)
            assert isinstance(sel.selected_refs, tuple)
            for ref in sel.selected_refs:
                assert isinstance(ref, str) and ref


def test_pairwise_set_difference_is_computable():
    """Spot-check that for one (investor, bank) pair in one period,
    the pairwise set-difference computation the v1.9.1 reporter
    will perform actually resolves to non-empty data on the
    canonical fixture."""
    k, r = _run()
    ps = r.per_period_summaries[0]
    inv_sel = k.attention.get_selection(ps.investor_selection_ids[0])
    bnk_sel = k.attention.get_selection(ps.bank_selection_ids[0])
    inv_set = set(inv_sel.selected_refs)
    bnk_set = set(bnk_sel.selected_refs)
    shared = inv_set & bnk_set
    investor_only = inv_set - bnk_set
    bank_only = bnk_set - inv_set
    # On the canonical seed, both actors share the corporate
    # signals (default profiles watch corporate_quarterly_report),
    # and each has at least one ref the other does not.
    assert shared, "expected non-empty shared refs on canonical seed"
    assert investor_only, "expected non-empty investor_only refs"
    assert bank_only, "expected non-empty bank_only refs"


# ---------------------------------------------------------------------------
# Determinism — the report-critical fields are byte-equal across
# fresh kernels seeded identically.
# ---------------------------------------------------------------------------


def _report_critical_view(r: LivingReferenceWorldResult) -> dict:
    return {
        "run_id": r.run_id,
        "period_count": r.period_count,
        "firm_ids": r.firm_ids,
        "investor_ids": r.investor_ids,
        "bank_ids": r.bank_ids,
        "ledger_record_count_before": r.ledger_record_count_before,
        "ledger_record_count_after": r.ledger_record_count_after,
        "created_record_ids": r.created_record_ids,
        "per_period_summaries": tuple(
            (
                ps.period_id,
                ps.as_of_date,
                ps.corporate_signal_ids,
                ps.investor_menu_ids,
                ps.bank_menu_ids,
                ps.investor_selection_ids,
                ps.bank_selection_ids,
                ps.investor_review_signal_ids,
                ps.bank_review_signal_ids,
                ps.record_count_created,
            )
            for ps in r.per_period_summaries
        ),
    }


def test_report_critical_fields_are_deterministic_across_fresh_kernels():
    _, a = _run()
    _, b = _run()
    assert _report_critical_view(a) == _report_critical_view(b)


# ---------------------------------------------------------------------------
# No-mutation: the report-critical reads do not touch any kernel book.
# This pins the v1.9.1 input policy ("read-only") on the input side.
# ---------------------------------------------------------------------------


def test_reading_report_critical_data_does_not_mutate_kernel():
    k, r = _run()
    snap_before = {
        "ledger_length": len(k.ledger.records),
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
        "signal_count": len(k.signals.all_signals()),
    }

    # Walk every report-critical read path the v1.9.1 reporter will
    # exercise.
    _ = r.created_record_ids
    _ = r.ledger_record_count_before, r.ledger_record_count_after
    for ps in r.per_period_summaries:
        for sel_id in ps.investor_selection_ids + ps.bank_selection_ids:
            _ = k.attention.get_selection(sel_id).selected_refs
        for rid in ps.investor_review_run_ids + ps.bank_review_run_ids + ps.corporate_run_ids:
            _ = k.routines.get_run_record(rid)
        for sid in (
            ps.corporate_signal_ids
            + ps.investor_review_signal_ids
            + ps.bank_review_signal_ids
        ):
            _ = k.signals.get_signal(sid)
        for mid in ps.investor_menu_ids + ps.bank_menu_ids:
            _ = k.attention.get_menu(mid)
    for record in k.ledger.records[
        r.ledger_record_count_before : r.ledger_record_count_after
    ]:
        _ = record.event_type, record.object_id

    snap_after = {
        "ledger_length": len(k.ledger.records),
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
        "signal_count": len(k.signals.all_signals()),
    }
    assert snap_before == snap_after
