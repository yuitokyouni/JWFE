"""
Tests for v1.8.13 investor / bank review routines.

Pins the v1.8.13 contract end-to-end:

- ``register_*_review_interaction`` and ``register_*_review_routine``
  are idempotent and produce the right self-loop topology
  (Investors→Investors, Banking→Banking) with the routine type
  locked into ``routine_types_that_may_use_this_channel``.
- ``run_investor_review`` and ``run_bank_review`` each create
  exactly one ``RoutineRunRecord`` (via the engine) and exactly
  one ``InformationSignal`` (the synthetic review note), with
  bidirectional run↔signal links wired through ``output_refs``
  / ``related_ids`` / ``metadata["routine_run_id"]``.
- The two ledger entries appear in order: ``routine_run_recorded``
  → ``signal_added``.
- Selected ``SelectedObservationSet`` ids flow through the engine
  into ``RoutineRunRecord.input_refs``; the signal payload's
  count summaries match the resolved input refs.
- Status is engine-default: ``"completed"`` when refs resolve,
  ``"degraded"`` when they don't (anti-scenario discipline).
- No economic mutation. The review routines do **not** touch
  ``valuations`` / ``prices`` / ``ownership`` / ``contracts`` /
  ``constraints`` / ``exposures`` / ``variables`` / ``attention``
  (beyond reading the supplied selection) / ``institutions`` /
  ``external_processes``.
- ``kernel.tick()`` and ``kernel.run(days=N)`` never fire the
  routines.
- Determinism: same kernel + same seed produces the same run id,
  same signal id, same payload counts.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from world.attention import SelectedObservationSet
from world.clock import Clock
from world.exposures import ExposureRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.reference_attention import (
    InvestorBankAttentionDemoResult,
    run_investor_bank_attention_demo,
)
from world.reference_reviews import (
    BANK_REVIEW_INTERACTION_ID,
    BANK_REVIEW_ROUTINE_TYPE,
    BANK_REVIEW_SIGNAL_TYPE,
    INVESTOR_REVIEW_INTERACTION_ID,
    INVESTOR_REVIEW_ROUTINE_TYPE,
    INVESTOR_REVIEW_SIGNAL_TYPE,
    ReviewRoutineResult,
    register_bank_review_interaction,
    register_bank_review_routine,
    register_investor_review_interaction,
    register_investor_review_routine,
    run_bank_review,
    run_investor_review,
)
from world.reference_routines import (
    register_corporate_quarterly_reporting_routine,
    register_corporate_reporting_interaction,
    run_corporate_quarterly_reporting,
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


def _seed_kernel(
    *,
    with_corporate_signal: bool = True,
    with_attention_demo: bool = True,
    register_review_routines: bool = True,
) -> WorldKernel:
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

    for exposure in _REFERENCE_EXPOSURES:
        k.exposures.add_exposure(exposure)

    if with_corporate_signal:
        register_corporate_reporting_interaction(k)
        register_corporate_quarterly_reporting_routine(k, firm_id=_FIRM)
        run_corporate_quarterly_reporting(k, firm_id=_FIRM, as_of_date=_AS_OF)

    if with_attention_demo:
        run_investor_bank_attention_demo(
            k,
            firm_id=_FIRM,
            investor_id=_INVESTOR,
            bank_id=_BANK,
            as_of_date=_AS_OF,
        )

    if register_review_routines:
        register_investor_review_interaction(k)
        register_investor_review_routine(k, investor_id=_INVESTOR)
        register_bank_review_interaction(k)
        register_bank_review_routine(k, bank_id=_BANK)

    return k


def _attention_demo(k: WorldKernel) -> InvestorBankAttentionDemoResult:
    """Re-derive the attention demo result so tests can grab the
    selection ids the seeded kernel produced."""
    # The demo helper is idempotent on profile registration and
    # raises on duplicate menu / selection — so we look up the
    # already-persisted selection ids by actor.
    inv_sel = k.attention.list_selections_by_actor(_INVESTOR)[0]
    bnk_sel = k.attention.list_selections_by_actor(_BANK)[0]
    return InvestorBankAttentionDemoResult(
        investor_profile_id=inv_sel.attention_profile_id,
        bank_profile_id=bnk_sel.attention_profile_id,
        investor_menu_id=inv_sel.menu_id,
        bank_menu_id=bnk_sel.menu_id,
        investor_selection_id=inv_sel.selection_id,
        bank_selection_id=bnk_sel.selection_id,
        investor_selected_refs=inv_sel.selected_refs,
        bank_selected_refs=bnk_sel.selected_refs,
        shared_refs=tuple(
            r for r in inv_sel.selected_refs if r in set(bnk_sel.selected_refs)
        ),
        investor_only_refs=tuple(
            r for r in inv_sel.selected_refs if r not in set(bnk_sel.selected_refs)
        ),
        bank_only_refs=tuple(
            r for r in bnk_sel.selected_refs if r not in set(inv_sel.selected_refs)
        ),
        as_of_date=inv_sel.as_of_date,
    )


# ---------------------------------------------------------------------------
# Interaction / routine registration
# ---------------------------------------------------------------------------


def test_investor_review_interaction_is_self_loop():
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    spec = register_investor_review_interaction(k)
    assert spec.interaction_id == INVESTOR_REVIEW_INTERACTION_ID
    assert spec.source_space_id == "investors"
    assert spec.target_space_id == "investors"
    assert spec.routine_types_that_may_use_this_channel == (
        INVESTOR_REVIEW_ROUTINE_TYPE,
    )


def test_bank_review_interaction_is_self_loop():
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    spec = register_bank_review_interaction(k)
    assert spec.source_space_id == "banking"
    assert spec.target_space_id == "banking"
    assert spec.routine_types_that_may_use_this_channel == (
        BANK_REVIEW_ROUTINE_TYPE,
    )


def test_register_investor_review_interaction_is_idempotent():
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    a = register_investor_review_interaction(k)
    b = register_investor_review_interaction(k)
    assert a.interaction_id == b.interaction_id
    assert (
        len(
            [
                i
                for i in k.interactions.list_interactions()
                if i.interaction_id == INVESTOR_REVIEW_INTERACTION_ID
            ]
        )
        == 1
    )


def test_register_bank_review_interaction_is_idempotent():
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    a = register_bank_review_interaction(k)
    b = register_bank_review_interaction(k)
    assert a.interaction_id == b.interaction_id
    assert (
        len(
            [
                i
                for i in k.interactions.list_interactions()
                if i.interaction_id == BANK_REVIEW_INTERACTION_ID
            ]
        )
        == 1
    )


def test_register_investor_review_routine_is_idempotent():
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    register_investor_review_interaction(k)
    a = register_investor_review_routine(k, investor_id=_INVESTOR)
    b = register_investor_review_routine(k, investor_id=_INVESTOR)
    assert a.routine_id == b.routine_id
    assert a.routine_type == INVESTOR_REVIEW_ROUTINE_TYPE
    assert a.owner_space_id == "investors"
    assert a.owner_id == _INVESTOR
    assert a.allowed_interaction_ids == (INVESTOR_REVIEW_INTERACTION_ID,)


def test_register_bank_review_routine_is_idempotent():
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    register_bank_review_interaction(k)
    a = register_bank_review_routine(k, bank_id=_BANK)
    b = register_bank_review_routine(k, bank_id=_BANK)
    assert a.routine_id == b.routine_id
    assert a.routine_type == BANK_REVIEW_ROUTINE_TYPE
    assert a.owner_space_id == "banking"
    assert a.allowed_interaction_ids == (BANK_REVIEW_INTERACTION_ID,)


@pytest.mark.parametrize(
    "fn,kwargs",
    [
        (register_investor_review_routine, {"investor_id": ""}),
        (register_bank_review_routine, {"bank_id": ""}),
    ],
)
def test_register_routine_rejects_empty_actor_id(fn, kwargs):
    k = _seed_kernel(with_attention_demo=False, register_review_routines=False)
    register_investor_review_interaction(k)
    register_bank_review_interaction(k)
    with pytest.raises(ValueError):
        fn(k, **kwargs)


# ---------------------------------------------------------------------------
# Run flow — happy path
# ---------------------------------------------------------------------------


def _run_default_investor(k: WorldKernel) -> ReviewRoutineResult:
    demo = _attention_demo(k)
    return run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(demo.investor_selection_id,),
        as_of_date=_AS_OF,
    )


def _run_default_bank(k: WorldKernel) -> ReviewRoutineResult:
    demo = _attention_demo(k)
    return run_bank_review(
        k,
        bank_id=_BANK,
        selected_observation_set_ids=(demo.bank_selection_id,),
        as_of_date=_AS_OF,
    )


def test_investor_review_creates_one_routine_run_record():
    k = _seed_kernel()
    result = _run_default_investor(k)
    assert isinstance(result, ReviewRoutineResult)
    runs = k.routines.list_runs_by_routine(result.routine_id)
    assert len(runs) == 1
    assert runs[0].run_id == result.run_id
    assert runs[0].routine_type == INVESTOR_REVIEW_ROUTINE_TYPE
    assert runs[0].owner_space_id == "investors"


def test_bank_review_creates_one_routine_run_record():
    k = _seed_kernel()
    result = _run_default_bank(k)
    runs = k.routines.list_runs_by_routine(result.routine_id)
    assert len(runs) == 1
    assert runs[0].routine_type == BANK_REVIEW_ROUTINE_TYPE
    assert runs[0].owner_space_id == "banking"


def test_investor_review_creates_one_review_signal():
    k = _seed_kernel()
    before_signals = len(k.signals.all_signals())
    result = _run_default_investor(k)
    after_signals = k.signals.all_signals()
    assert len(after_signals) - before_signals == 1
    assert result.signal.signal_type == INVESTOR_REVIEW_SIGNAL_TYPE
    assert result.signal.subject_id == _INVESTOR


def test_bank_review_creates_one_review_signal():
    k = _seed_kernel()
    before_signals = len(k.signals.all_signals())
    result = _run_default_bank(k)
    after_signals = k.signals.all_signals()
    assert len(after_signals) - before_signals == 1
    assert result.signal.signal_type == BANK_REVIEW_SIGNAL_TYPE
    assert result.signal.subject_id == _BANK


def test_signal_back_references_routine_run():
    k = _seed_kernel()
    result = _run_default_investor(k)
    assert result.signal.related_ids == (result.run_id,)
    assert result.signal.metadata["routine_run_id"] == result.run_id


def test_run_record_forward_references_signal():
    k = _seed_kernel()
    result = _run_default_investor(k)
    record = k.routines.get_run_record(result.run_id)
    assert result.signal.signal_id in record.output_refs


def test_run_consumes_selected_refs_from_attention_book():
    """The engine collects the SelectedObservationSet's selected_refs
    into RoutineRunRecord.input_refs; the helper must not strip them
    out."""
    k = _seed_kernel()
    demo = _attention_demo(k)
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(demo.investor_selection_id,),
        as_of_date=_AS_OF,
    )
    record = k.routines.get_run_record(result.run_id)
    for ref in demo.investor_selected_refs:
        assert ref in record.input_refs


def test_payload_counts_match_resolved_input_refs():
    k = _seed_kernel()
    demo = _attention_demo(k)
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(demo.investor_selection_id,),
        as_of_date=_AS_OF,
    )
    payload = result.signal.payload
    assert payload["selected_ref_count"] == len(result.result.input_refs)
    total = (
        payload["selected_signal_count"]
        + payload["selected_variable_observation_count"]
        + payload["selected_exposure_count"]
        + payload["selected_other_count"]
    )
    assert total == payload["selected_ref_count"]


def test_investor_and_bank_review_input_refs_can_differ():
    """Heterogeneous attention propagates: when the investor and the
    bank fed different SelectedObservationSets, the resulting
    input_refs differ on the two run records."""
    k = _seed_kernel()
    inv = _run_default_investor(k)
    bnk = _run_default_bank(k)
    assert (
        k.routines.get_run_record(inv.run_id).input_refs
        != k.routines.get_run_record(bnk.run_id).input_refs
    )


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------


def test_status_completed_when_selection_has_refs():
    k = _seed_kernel()
    result = _run_default_investor(k)
    assert result.status == "completed"
    assert result.signal.payload["status"] == "completed"


def test_status_degraded_when_no_selection_supplied():
    k = _seed_kernel(with_attention_demo=False)
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(),
        as_of_date=_AS_OF,
    )
    assert result.status == "degraded"
    assert result.signal.payload["selected_ref_count"] == 0


def test_status_degraded_when_selection_has_no_refs():
    """An empty SelectedObservationSet is still a legitimate input —
    but flows through to a degraded run, not a failure (anti-scenario)."""
    k = _seed_kernel(with_attention_demo=False)
    empty_selection = SelectedObservationSet(
        selection_id="selection:empty",
        actor_id=_INVESTOR,
        attention_profile_id="profile:investor:empty",
        menu_id="menu:investor:empty",
        selected_refs=(),
        selection_reason="profile_match",
        as_of_date=_AS_OF,
        status="empty",
    )
    # add_selection requires the attention profile to exist (the
    # AttentionBook emits a ledger record but does not validate
    # profile ids). add_selection itself does not check ref overlap.
    k.attention.add_selection(empty_selection)
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(empty_selection.selection_id,),
        as_of_date=_AS_OF,
    )
    assert result.status == "degraded"


# ---------------------------------------------------------------------------
# Date semantics
# ---------------------------------------------------------------------------


def test_as_of_date_defaults_to_clock():
    k = _seed_kernel()
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(),
    )
    assert result.as_of_date == _AS_OF


def test_explicit_as_of_date_overrides_clock():
    k = _seed_kernel()
    demo = _attention_demo(k)
    # Use a different date — the run_id is derived from the date so
    # the run will be distinct from any other run on the same kernel.
    explicit = "2026-06-30"
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(demo.investor_selection_id,),
        as_of_date=explicit,
    )
    assert result.as_of_date == explicit


# ---------------------------------------------------------------------------
# Ledger ordering
# ---------------------------------------------------------------------------


def test_investor_review_ledger_order_run_then_signal():
    k = _seed_kernel()
    demo = _attention_demo(k)
    before = len(k.ledger.records)
    result = run_investor_review(
        k,
        investor_id=_INVESTOR,
        selected_observation_set_ids=(demo.investor_selection_id,),
        as_of_date=_AS_OF,
    )
    new_records = k.ledger.records[before:]
    types_in_order = [r.event_type for r in new_records]
    assert types_in_order == ["routine_run_recorded", "signal_added"]
    assert new_records[0].object_id == result.run_id
    assert new_records[1].object_id == result.signal_id


def test_bank_review_ledger_order_run_then_signal():
    k = _seed_kernel()
    demo = _attention_demo(k)
    before = len(k.ledger.records)
    run_bank_review(
        k,
        bank_id=_BANK,
        selected_observation_set_ids=(demo.bank_selection_id,),
        as_of_date=_AS_OF,
    )
    new_records = k.ledger.records[before:]
    types_in_order = [r.event_type for r in new_records]
    assert types_in_order == ["routine_run_recorded", "signal_added"]


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def _run_for_determinism(k: WorldKernel) -> tuple[str, str, dict[str, Any]]:
    inv = _run_default_investor(k)
    return (inv.run_id, inv.signal_id, dict(inv.signal.payload))


def test_review_run_is_deterministic_across_fresh_kernels():
    a = _run_for_determinism(_seed_kernel())
    b = _run_for_determinism(_seed_kernel())
    assert a[0] == b[0]
    assert a[1] == b[1]
    assert a[2] == b[2]


# ---------------------------------------------------------------------------
# No-mutation guarantees
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
        # Attention book is *read* (the selections feed the engine)
        # but never mutated by the review routines themselves.
        "attention": k.attention.snapshot(),
    }


def test_investor_review_does_not_mutate_unrelated_books():
    k = _seed_kernel()
    before = _capture_state(k)
    _run_default_investor(k)
    after = _capture_state(k)
    assert before == after


def test_bank_review_does_not_mutate_unrelated_books():
    k = _seed_kernel()
    before = _capture_state(k)
    _run_default_bank(k)
    after = _capture_state(k)
    assert before == after


def test_review_routines_only_write_routine_book_and_signal_book():
    """Beyond the engine's run-record write and the helper's
    signal write, no other book grows."""
    k = _seed_kernel()
    before = {
        "interactions": len(k.interactions.list_interactions()),
        "routines": len(k.routines.list_routines()),
        "attention_profiles": len(k.attention.list_profiles()),
        "attention_menus": len(k.attention.list_menus_by_actor(_INVESTOR))
        + len(k.attention.list_menus_by_actor(_BANK)),
        "attention_selections": len(
            k.attention.list_selections_by_actor(_INVESTOR)
        )
        + len(k.attention.list_selections_by_actor(_BANK)),
        "exposures": len(k.exposures.list_exposures()),
        "variable_observations": len(
            k.variables.snapshot()["observations"]
        ),
    }
    _run_default_investor(k)
    _run_default_bank(k)
    after = {
        "interactions": len(k.interactions.list_interactions()),
        "routines": len(k.routines.list_routines()),
        "attention_profiles": len(k.attention.list_profiles()),
        "attention_menus": len(k.attention.list_menus_by_actor(_INVESTOR))
        + len(k.attention.list_menus_by_actor(_BANK)),
        "attention_selections": len(
            k.attention.list_selections_by_actor(_INVESTOR)
        )
        + len(k.attention.list_selections_by_actor(_BANK)),
        "exposures": len(k.exposures.list_exposures()),
        "variable_observations": len(
            k.variables.snapshot()["observations"]
        ),
    }
    assert before == after


# ---------------------------------------------------------------------------
# No auto-firing from tick / run
# ---------------------------------------------------------------------------


def test_kernel_tick_does_not_auto_fire_review_routines():
    k = _seed_kernel()
    inv_routine = f"routine:{INVESTOR_REVIEW_ROUTINE_TYPE}:{_INVESTOR}"
    bnk_routine = f"routine:{BANK_REVIEW_ROUTINE_TYPE}:{_BANK}"
    runs_inv_before = len(k.routines.list_runs_by_routine(inv_routine))
    runs_bnk_before = len(k.routines.list_runs_by_routine(bnk_routine))
    k.tick()
    assert len(k.routines.list_runs_by_routine(inv_routine)) == runs_inv_before
    assert len(k.routines.list_runs_by_routine(bnk_routine)) == runs_bnk_before


def test_kernel_run_does_not_auto_fire_review_routines():
    k = _seed_kernel()
    inv_routine = f"routine:{INVESTOR_REVIEW_ROUTINE_TYPE}:{_INVESTOR}"
    bnk_routine = f"routine:{BANK_REVIEW_ROUTINE_TYPE}:{_BANK}"
    runs_inv_before = len(k.routines.list_runs_by_routine(inv_routine))
    runs_bnk_before = len(k.routines.list_runs_by_routine(bnk_routine))
    k.run(days=5)
    assert len(k.routines.list_runs_by_routine(inv_routine)) == runs_inv_before
    assert len(k.routines.list_runs_by_routine(bnk_routine)) == runs_bnk_before


# ---------------------------------------------------------------------------
# Synthetic-only identifiers
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "nyse",
)


def test_review_signal_identifiers_are_synthetic():
    k = _seed_kernel()
    inv = _run_default_investor(k)
    bnk = _run_default_bank(k)

    def _walk(value: Any) -> list[str]:
        out: list[str] = []
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, dict):
            for v in value.values():
                out.extend(_walk(v))
        elif isinstance(value, (list, tuple, set, frozenset)):
            for v in value:
                out.extend(_walk(v))
        return out

    for s in (inv.signal, bnk.signal):
        strings = _walk(s.to_dict())
        joined = " ".join(strings).lower()
        for token in _FORBIDDEN_TOKENS:
            # Use word-boundary check by surrounding spaces / punct
            # — `tse` substring of `itself` must not trigger.
            for sep in (" ", ":", "/", "-", "_", "(", ")", ",", ".", "'", '"'):
                if f"{sep}{token}{sep}" in f" {joined} ":
                    pytest.fail(
                        f"forbidden token {token!r} appears in signal {s.signal_id}"
                    )


def test_module_constants_use_no_jurisdiction_specific_tokens():
    constants = (
        INVESTOR_REVIEW_ROUTINE_TYPE,
        BANK_REVIEW_ROUTINE_TYPE,
        INVESTOR_REVIEW_INTERACTION_ID,
        BANK_REVIEW_INTERACTION_ID,
        INVESTOR_REVIEW_SIGNAL_TYPE,
        BANK_REVIEW_SIGNAL_TYPE,
    )
    for c in constants:
        for token in _FORBIDDEN_TOKENS:
            assert token not in c.lower(), c
