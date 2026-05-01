"""
Tests for v1.8.6 Routine Engine plumbing.

Covers ``RoutineExecutionRequest`` field validation,
``RoutineExecutionResult`` shape, the engine's ``execute_request``
end-to-end flow (date defaulting, selected-ref collection,
deterministic dedup, default status semantics, interaction
compatibility, attention compatibility), the read-only
``validate_request`` and ``collect_selected_refs`` helpers, kernel
wiring (the engine is exposed as ``kernel.routine_engine`` and is
NOT fired by ``tick()`` / ``run()``), and the no-mutation guarantee
against every other v0/v1 source-of-truth book.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.attention import (
    AttentionBook,
    AttentionProfile,
    ObservationMenu,
    SelectedObservationSet,
)
from world.clock import Clock
from world.interactions import InteractionBook, InteractionSpec
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.routine_engine import (
    RoutineEngine,
    RoutineExecutionError,
    RoutineExecutionIncompatibleInteractionError,
    RoutineExecutionMissingDateError,
    RoutineExecutionRequest,
    RoutineExecutionResult,
    RoutineExecutionUnknownSelectionError,
    RoutineExecutionValidationError,
)
from world.routines import RoutineBook, RoutineSpec
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    *,
    routine_id: str = "routine:r1",
    routine_type: str = "corporate_quarterly_reporting",
    owner_space_id: str = "corporate",
    owner_id: str | None = "firm:reference_manufacturer_a",
    frequency: str = "QUARTERLY",
    enabled: bool = True,
    allowed_interaction_ids: tuple[str, ...] = (
        "interaction:corporate.earnings_to_information",
    ),
) -> RoutineSpec:
    return RoutineSpec(
        routine_id=routine_id,
        routine_type=routine_type,
        owner_space_id=owner_space_id,
        owner_id=owner_id,
        frequency=frequency,
        enabled=enabled,
        allowed_interaction_ids=allowed_interaction_ids,
    )


def _interaction(
    *,
    interaction_id: str = "interaction:corporate.earnings_to_information",
    source_space_id: str = "corporate",
    target_space_id: str = "information",
    interaction_type: str = "earnings_disclosure",
    channel_type: str = "scheduled_filing",
    routine_types_that_may_use_this_channel: tuple[str, ...] = (
        "corporate_quarterly_reporting",
    ),
) -> InteractionSpec:
    return InteractionSpec(
        interaction_id=interaction_id,
        source_space_id=source_space_id,
        target_space_id=target_space_id,
        interaction_type=interaction_type,
        channel_type=channel_type,
        routine_types_that_may_use_this_channel=(
            routine_types_that_may_use_this_channel
        ),
        output_ref_types=("InformationSignal",),
    )


def _profile(
    *, profile_id: str = "profile:firm_a:reporting"
) -> AttentionProfile:
    return AttentionProfile(
        profile_id=profile_id,
        actor_id="firm:reference_manufacturer_a",
        actor_type="firm",
        update_frequency="QUARTERLY",
        watched_signal_types=("earnings_disclosure",),
    )


def _menu(
    *,
    menu_id: str = "menu:firm_a:2026-03-31",
    actor_id: str = "firm:reference_manufacturer_a",
    as_of_date: str = "2026-03-31",
) -> ObservationMenu:
    return ObservationMenu(
        menu_id=menu_id,
        actor_id=actor_id,
        as_of_date=as_of_date,
        available_signal_ids=("signal:earnings:firm_a:2026Q1",),
    )


def _selection(
    *,
    selection_id: str = "selection:1",
    attention_profile_id: str = "profile:firm_a:reporting",
    menu_id: str = "menu:firm_a:2026-03-31",
    selected_refs: tuple[str, ...] = (
        "signal:earnings:firm_a:2026Q1",
        "valuation:firm_a:2026Q1",
    ),
    status: str = "completed",
) -> SelectedObservationSet:
    return SelectedObservationSet(
        selection_id=selection_id,
        actor_id="firm:reference_manufacturer_a",
        attention_profile_id=attention_profile_id,
        menu_id=menu_id,
        selected_refs=selected_refs,
        selection_reason="profile_match",
        as_of_date="2026-03-31",
        status=status,
    )


def _engine_with_seeded_books(
    *,
    with_clock: bool = True,
    with_interaction: bool = True,
    with_selection: bool = True,
    with_routine: bool = True,
):
    rb = RoutineBook()
    ib = InteractionBook()
    ab = AttentionBook()
    if with_routine:
        rb.add_routine(_spec())
    if with_interaction:
        ib.add_interaction(_interaction())
    if with_selection:
        ab.add_profile(_profile())
        ab.add_menu(_menu())
        ab.add_selection(_selection())
    clk = Clock(current_date=date(2026, 3, 31)) if with_clock else None
    return RoutineEngine(routines=rb, interactions=ib, attention=ab, clock=clk)


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# RoutineExecutionRequest validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_id": ""},
        {"routine_id": ""},
        {"as_of_date": ""},
        {"phase_id": ""},
        {"status": ""},
    ],
)
def test_request_rejects_empty_required_strings(kwargs):
    base = {"request_id": "req:1", "routine_id": "routine:r1"}
    base.update(kwargs)
    with pytest.raises(ValueError):
        RoutineExecutionRequest(**base)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "interaction_ids",
        "selected_observation_set_ids",
        "explicit_input_refs",
        "output_refs",
    ],
)
def test_request_rejects_empty_strings_in_tuple_fields(tuple_field):
    with pytest.raises(ValueError):
        RoutineExecutionRequest(
            request_id="req:1",
            routine_id="routine:r1",
            **{tuple_field: ("valid", "")},
        )


def test_request_is_frozen():
    req = RoutineExecutionRequest(request_id="req:1", routine_id="routine:r1")
    with pytest.raises(Exception):
        req.request_id = "tampered"  # type: ignore[misc]


def test_request_to_dict_round_trips_fields():
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        as_of_date="2026-03-31",
        interaction_ids=("i:1",),
        selected_observation_set_ids=("s:1",),
    )
    d = req.to_dict()
    assert d["request_id"] == req.request_id
    assert d["routine_id"] == req.routine_id
    assert d["interaction_ids"] == ["i:1"]


# ---------------------------------------------------------------------------
# execute_request: happy path
# ---------------------------------------------------------------------------


def test_execute_request_creates_routine_run_record():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    result = engine.execute_request(req)
    assert isinstance(result, RoutineExecutionResult)
    # One run record landed in the book.
    runs = engine.routines.list_runs_by_routine("routine:r1")
    assert len(runs) == 1
    stored = runs[0]
    assert stored.run_id == result.run_id
    assert stored.routine_type == "corporate_quarterly_reporting"
    assert stored.owner_space_id == "corporate"


def test_result_mirrors_stored_run_record():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:42",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
        explicit_input_refs=("signal:explicit_extra",),
    )
    result = engine.execute_request(req)
    stored = engine.routines.get_run_record(result.run_id)
    assert result.run_id == stored.run_id
    assert result.routine_id == stored.routine_id
    assert result.routine_type == stored.routine_type
    assert result.owner_space_id == stored.owner_space_id
    assert result.as_of_date == stored.as_of_date
    assert result.input_refs == stored.input_refs
    assert result.output_refs == stored.output_refs
    assert result.interaction_ids == stored.interaction_ids
    assert result.status == stored.status


def test_run_id_default_format_links_back_to_request():
    """
    Default run_id is "run:" + request_id, so callers can correlate
    runs and requests without storing the request itself.
    """
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:correlate_me",
        routine_id="routine:r1",
    )
    result = engine.execute_request(req)
    assert result.run_id == "run:req:correlate_me"


def test_run_id_metadata_override_honored():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        metadata={"run_id": "run:custom_id"},
    )
    result = engine.execute_request(req)
    assert result.run_id == "run:custom_id"


# ---------------------------------------------------------------------------
# Date semantics
# ---------------------------------------------------------------------------


def test_request_as_of_date_overrides_clock():
    engine = _engine_with_seeded_books()  # clock at 2026-03-31
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        as_of_date="2026-06-30",
    )
    result = engine.execute_request(req)
    assert result.as_of_date == "2026-06-30"


def test_date_defaults_to_clock_when_request_omits_it():
    engine = _engine_with_seeded_books()  # clock at 2026-03-31
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
    )
    result = engine.execute_request(req)
    assert result.as_of_date == "2026-03-31"


def test_missing_date_without_clock_raises_controlled_error():
    engine = _engine_with_seeded_books(with_clock=False)
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
    )
    with pytest.raises(RoutineExecutionMissingDateError):
        engine.execute_request(req)


# ---------------------------------------------------------------------------
# Selected-ref collection + dedup
# ---------------------------------------------------------------------------


def test_collect_selected_refs_concatenates_in_input_order():
    engine = _engine_with_seeded_books()
    engine.attention.add_selection(
        _selection(
            selection_id="selection:2",
            selected_refs=("signal:from_two:a", "signal:from_two:b"),
        )
    )
    refs = engine.collect_selected_refs(("selection:1", "selection:2"))
    # selection:1 has 2 refs, selection:2 has 2 refs; preserved order.
    assert refs == (
        "signal:earnings:firm_a:2026Q1",
        "valuation:firm_a:2026Q1",
        "signal:from_two:a",
        "signal:from_two:b",
    )


def test_collect_selected_refs_unknown_id_raises_controlled_error():
    engine = _engine_with_seeded_books()
    with pytest.raises(RoutineExecutionUnknownSelectionError):
        engine.collect_selected_refs(("selection:does_not_exist",))


def test_explicit_and_selected_refs_combine_deterministically():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
        explicit_input_refs=("explicit:a", "explicit:b"),
    )
    result = engine.execute_request(req)
    # Explicit first, then selected, in declaration order.
    assert result.input_refs == (
        "explicit:a",
        "explicit:b",
        "signal:earnings:firm_a:2026Q1",
        "valuation:firm_a:2026Q1",
    )


def test_duplicate_refs_are_deduped_with_first_occurrence_order():
    """
    v1.8.6 documented behavior: input_refs are deduped on
    first-occurrence order. A ref that appears in both
    explicit_input_refs and a selection is recorded once.
    """
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
        explicit_input_refs=(
            "signal:earnings:firm_a:2026Q1",  # also in the selection
            "explicit:unique",
        ),
    )
    result = engine.execute_request(req)
    # First occurrence wins (explicit), so the order is preserved
    # and the dup from the selection is dropped.
    assert result.input_refs == (
        "signal:earnings:firm_a:2026Q1",
        "explicit:unique",
        "valuation:firm_a:2026Q1",
    )


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------


def test_status_defaults_to_completed_when_inputs_present():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    result = engine.execute_request(req)
    assert result.status == "completed"


def test_status_defaults_to_degraded_when_no_inputs():
    """
    v1.8.1 anti-scenario discipline: a run with no inputs is
    "degraded", not "failed". The run still happened.
    """
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
    )
    result = engine.execute_request(req)
    assert result.status == "degraded"


@pytest.mark.parametrize(
    "explicit",
    ["completed", "partial", "degraded", "failed", "custom_status"],
)
def test_explicit_status_is_preserved(explicit):
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        status=explicit,
    )
    result = engine.execute_request(req)
    assert result.status == explicit


# ---------------------------------------------------------------------------
# Interaction compatibility
# ---------------------------------------------------------------------------


def test_compatible_interaction_passes():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
    )
    result = engine.execute_request(req)
    assert result.interaction_ids == (
        "interaction:corporate.earnings_to_information",
    )


def test_interaction_not_in_routine_allowed_list_raises():
    rb = RoutineBook()
    ib = InteractionBook()
    ab = AttentionBook()
    rb.add_routine(_spec(allowed_interaction_ids=("interaction:something_else",)))
    ib.add_interaction(_interaction())
    engine = RoutineEngine(routines=rb, interactions=ib, attention=ab)
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        as_of_date="2026-03-31",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
    )
    with pytest.raises(RoutineExecutionIncompatibleInteractionError):
        engine.execute_request(req)


def test_interaction_not_admitting_routine_type_raises():
    rb = RoutineBook()
    ib = InteractionBook()
    ab = AttentionBook()
    rb.add_routine(_spec(routine_type="bank_review"))
    ib.add_interaction(
        _interaction(
            routine_types_that_may_use_this_channel=(
                "corporate_quarterly_reporting",
            )
        )
    )
    engine = RoutineEngine(routines=rb, interactions=ib, attention=ab)
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        as_of_date="2026-03-31",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
    )
    with pytest.raises(RoutineExecutionIncompatibleInteractionError):
        engine.execute_request(req)


def test_unknown_interaction_id_fails_execution():
    """
    Even though routine_can_use_interaction returns False for
    unknown interaction_ids (a predicate-safety choice in v1.8.4),
    the engine treats unknown interactions as a fatal validation
    error so the failure is loud.
    """
    engine = _engine_with_seeded_books()
    # Make the routine list an interaction that doesn't exist in
    # the book.
    rb = RoutineBook()
    rb.add_routine(_spec(allowed_interaction_ids=("interaction:unknown",)))
    ib = InteractionBook()
    ab = AttentionBook()
    engine = RoutineEngine(
        routines=rb, interactions=ib, attention=ab,
        clock=Clock(current_date=date(2026, 3, 31)),
    )
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=("interaction:unknown",),
    )
    with pytest.raises(RoutineExecutionIncompatibleInteractionError):
        engine.execute_request(req)


# ---------------------------------------------------------------------------
# Attention compatibility
# ---------------------------------------------------------------------------


def test_unknown_selected_observation_set_raises_controlled_error():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        selected_observation_set_ids=("selection:does_not_exist",),
    )
    with pytest.raises(RoutineExecutionUnknownSelectionError):
        engine.execute_request(req)


def test_engine_does_not_enforce_subset_of_menu():
    """
    v1.8.5 deliberately did NOT enforce that
    SelectedObservationSet.selected_refs is a subset of the menu's
    available_*_ids. The engine inherits this: it consumes
    selections as records, not as economically-validated inputs.
    """
    engine = _engine_with_seeded_books()
    # Add a selection whose refs are not on its menu.
    engine.attention.add_selection(
        _selection(
            selection_id="selection:not_on_menu",
            selected_refs=("signal:appears_only_here",),
        )
    )
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        selected_observation_set_ids=("selection:not_on_menu",),
    )
    # Should succeed.
    result = engine.execute_request(req)
    assert "signal:appears_only_here" in result.input_refs


# ---------------------------------------------------------------------------
# Disabled routine + unknown routine
# ---------------------------------------------------------------------------


def test_unknown_routine_raises_validation_error():
    engine = _engine_with_seeded_books(with_routine=False)
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:does_not_exist",
    )
    with pytest.raises(RoutineExecutionValidationError):
        engine.execute_request(req)


def test_disabled_routine_rejected():
    rb = RoutineBook()
    ib = InteractionBook()
    ab = AttentionBook()
    rb.add_routine(_spec(enabled=False))
    engine = RoutineEngine(
        routines=rb, interactions=ib, attention=ab,
        clock=Clock(current_date=date(2026, 3, 31)),
    )
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
    )
    with pytest.raises(RoutineExecutionValidationError) as exc:
        engine.execute_request(req)
    assert "disabled" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# parent_record_ids from metadata
# ---------------------------------------------------------------------------


def test_parent_record_ids_from_metadata_flow_to_run_record():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        metadata={"parent_record_ids": ("rec_alpha", "rec_beta")},
    )
    result = engine.execute_request(req)
    stored = engine.routines.get_run_record(result.run_id)
    assert stored.parent_record_ids == ("rec_alpha", "rec_beta")
    # parent_record_ids should not also appear in metadata.
    assert "parent_record_ids" not in stored.metadata


def test_no_parents_invented_when_caller_does_not_supply():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
    )
    result = engine.execute_request(req)
    stored = engine.routines.get_run_record(result.run_id)
    assert stored.parent_record_ids == ()


# ---------------------------------------------------------------------------
# selected_observation_set_ids in metadata
# ---------------------------------------------------------------------------


def test_selected_observation_set_ids_stored_in_run_record_metadata():
    """
    RoutineRunRecord has no dedicated selected_observation_set_ids
    field; the engine stores them under
    metadata["selected_observation_set_ids"].
    """
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        selected_observation_set_ids=("selection:1",),
    )
    result = engine.execute_request(req)
    stored = engine.routines.get_run_record(result.run_id)
    assert stored.metadata["selected_observation_set_ids"] == ["selection:1"]
    # The result's metadata mirrors it.
    assert result.metadata["selected_observation_set_ids"] == ["selection:1"]


# ---------------------------------------------------------------------------
# validate_request
# ---------------------------------------------------------------------------


def test_validate_request_returns_summary_dict():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
        explicit_input_refs=("explicit:a",),
    )
    summary = engine.validate_request(req)
    assert summary["routine_id"] == "routine:r1"
    assert summary["routine_type"] == "corporate_quarterly_reporting"
    assert summary["owner_space_id"] == "corporate"
    assert summary["as_of_date"] == "2026-03-31"
    assert summary["selected_refs_count"] == 2
    assert summary["explicit_input_refs_count"] == 1
    assert summary["resolved_input_refs_count"] == 3
    assert summary["default_status"] == "completed"


def test_validate_request_does_not_create_run_record():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    engine.validate_request(req)
    assert engine.routines.list_runs_by_routine("routine:r1") == ()


def test_validate_request_raises_same_errors_as_execute():
    engine = _engine_with_seeded_books()
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=("interaction:unknown",),
    )
    with pytest.raises(RoutineExecutionIncompatibleInteractionError):
        engine.validate_request(req)


# ---------------------------------------------------------------------------
# Ledger emission via existing path
# ---------------------------------------------------------------------------


def test_routine_book_ledger_emits_routine_run_recorded():
    """The engine writes via RoutineBook.add_run_record, which
    already emits ROUTINE_RUN_RECORDED. The engine adds no other
    ledger writes."""
    kernel = _kernel()
    kernel.routines.add_routine(_spec())
    kernel.interactions.add_interaction(_interaction())
    kernel.attention.add_profile(_profile())
    kernel.attention.add_menu(_menu())
    kernel.attention.add_selection(_selection())

    before = len(kernel.ledger.records)
    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    kernel.routine_engine.execute_request(req)
    after = len(kernel.ledger.records)
    # Exactly one new ledger record (the routine_run_recorded).
    assert after - before == 1
    new_records = kernel.ledger.records[before:]
    assert new_records[0].event_type == "routine_run_recorded"


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_routine_engine():
    kernel = _kernel()
    assert isinstance(kernel.routine_engine, RoutineEngine)
    assert kernel.routine_engine.routines is kernel.routines
    assert kernel.routine_engine.interactions is kernel.interactions
    assert kernel.routine_engine.attention is kernel.attention
    assert kernel.routine_engine.clock is kernel.clock


def test_kernel_tick_does_not_execute_routines_automatically():
    """
    v1.8.6 plumbing rule: the engine must NOT hook into tick() /
    run(). Execution is caller-initiated only.
    """
    kernel = _kernel()
    kernel.routines.add_routine(_spec())
    kernel.interactions.add_interaction(_interaction())
    kernel.tick()
    # No routine run records should appear.
    assert kernel.routines.list_runs_by_routine("routine:r1") == ()


def test_kernel_run_does_not_execute_routines_automatically():
    kernel = _kernel()
    kernel.routines.add_routine(_spec())
    kernel.interactions.add_interaction(_interaction())
    kernel.run(days=5)
    assert kernel.routines.list_runs_by_routine("routine:r1") == ()


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def test_engine_does_not_mutate_other_kernel_books():
    """
    Executing a request reads from RoutineBook, InteractionBook,
    AttentionBook; writes one record to RoutineBook (which emits
    one ledger entry through its existing path); and touches
    nothing else.
    """
    kernel = _kernel()

    # Seed unrelated books with one entry each so snapshot equality
    # is meaningful.
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-03-31", "exchange")

    kernel.routines.add_routine(_spec())
    kernel.interactions.add_interaction(_interaction())
    kernel.attention.add_profile(_profile())
    kernel.attention.add_menu(_menu())
    kernel.attention.add_selection(_selection())

    snaps_before = {
        "ownership": kernel.ownership.snapshot(),
        "contracts": kernel.contracts.snapshot(),
        "prices": kernel.prices.snapshot(),
        "constraints": kernel.constraints.snapshot(),
        "signals": kernel.signals.snapshot(),
        "valuations": kernel.valuations.snapshot(),
        "institutions": kernel.institutions.snapshot(),
        "external_processes": kernel.external_processes.snapshot(),
        "relationships": kernel.relationships.snapshot(),
        "interactions": kernel.interactions.snapshot(),
        "attention": kernel.attention.snapshot(),
    }

    req = RoutineExecutionRequest(
        request_id="req:1",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    kernel.routine_engine.execute_request(req)

    assert kernel.ownership.snapshot() == snaps_before["ownership"]
    assert kernel.contracts.snapshot() == snaps_before["contracts"]
    assert kernel.prices.snapshot() == snaps_before["prices"]
    assert kernel.constraints.snapshot() == snaps_before["constraints"]
    assert kernel.signals.snapshot() == snaps_before["signals"]
    assert kernel.valuations.snapshot() == snaps_before["valuations"]
    assert kernel.institutions.snapshot() == snaps_before["institutions"]
    assert (
        kernel.external_processes.snapshot()
        == snaps_before["external_processes"]
    )
    assert kernel.relationships.snapshot() == snaps_before["relationships"]
    assert kernel.interactions.snapshot() == snaps_before["interactions"]
    assert kernel.attention.snapshot() == snaps_before["attention"]


def test_engine_writes_exactly_one_run_record_per_request():
    """The engine produces one RoutineRunRecord per execute_request
    call. Two requests against the same routine produce two
    distinct records."""
    engine = _engine_with_seeded_books()
    req_a = RoutineExecutionRequest(
        request_id="req:a",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    req_b = RoutineExecutionRequest(
        request_id="req:b",
        routine_id="routine:r1",
        interaction_ids=(
            "interaction:corporate.earnings_to_information",
        ),
        selected_observation_set_ids=("selection:1",),
    )
    engine.execute_request(req_a)
    engine.execute_request(req_b)
    runs = engine.routines.list_runs_by_routine("routine:r1")
    assert len(runs) == 2
    assert {r.run_id for r in runs} == {"run:req:a", "run:req:b"}


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_specific_errors_are_routine_execution_error_subclasses():
    assert issubclass(
        RoutineExecutionValidationError, RoutineExecutionError
    )
    assert issubclass(
        RoutineExecutionMissingDateError, RoutineExecutionError
    )
    assert issubclass(
        RoutineExecutionIncompatibleInteractionError, RoutineExecutionError
    )
    assert issubclass(
        RoutineExecutionUnknownSelectionError, RoutineExecutionError
    )
