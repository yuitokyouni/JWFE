"""
Tests for v1.8.7 Corporate Quarterly Reporting Routine.

Covers the three helpers in ``world/reference_routines.py``
(``register_corporate_reporting_interaction``,
``register_corporate_quarterly_reporting_routine``,
``run_corporate_quarterly_reporting``) and the end-to-end flow:
one ``RoutineRunRecord`` + one ``InformationSignal`` per call,
linked by id, in the right ledger order, with no other book mutated.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.reference_routines import (
    CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE,
    CORPORATE_REPORTING_INTERACTION_ID,
    CORPORATE_REPORTING_SIGNAL_TYPE,
    CORPORATE_REPORTING_SOURCE_ID,
    CorporateReportingResult,
    register_corporate_quarterly_reporting_routine,
    register_corporate_reporting_interaction,
    run_corporate_quarterly_reporting,
)
from world.registry import Registry
from world.routine_engine import (
    RoutineExecutionIncompatibleInteractionError,
)
from world.scheduler import Scheduler
from world.state import State


_FIRM_ID = "firm:reference_manufacturer_a"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _kernel(*, current_date: date | None = date(2026, 3, 31)) -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=current_date),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _seeded_kernel(
    *, firm_id: str = _FIRM_ID, current_date: date | None = date(2026, 3, 31)
) -> WorldKernel:
    """Kernel with the v1.8.7 interaction + routine pre-registered."""
    kernel = _kernel(current_date=current_date)
    register_corporate_reporting_interaction(kernel)
    register_corporate_quarterly_reporting_routine(kernel, firm_id=firm_id)
    return kernel


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def test_register_interaction_is_self_loop_with_locked_routine_type():
    kernel = _kernel()
    spec = register_corporate_reporting_interaction(kernel)
    assert spec.interaction_id == CORPORATE_REPORTING_INTERACTION_ID
    assert spec.source_space_id == "corporate"
    assert spec.target_space_id == "corporate"
    assert spec.direction == "self_loop"
    assert spec.routine_types_that_may_use_this_channel == (
        CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE,
    )


def test_register_interaction_is_idempotent():
    kernel = _kernel()
    a = register_corporate_reporting_interaction(kernel)
    b = register_corporate_reporting_interaction(kernel)
    assert a.interaction_id == b.interaction_id
    # Only one InteractionSpec stored.
    assert len(kernel.interactions.list_interactions()) == 1


def test_register_routine_per_firm_with_correct_metadata():
    kernel = _kernel()
    spec = register_corporate_quarterly_reporting_routine(
        kernel, firm_id=_FIRM_ID
    )
    assert (
        spec.routine_type
        == CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE
    )
    assert spec.owner_space_id == "corporate"
    assert spec.owner_id == _FIRM_ID
    assert spec.frequency == "QUARTERLY"
    assert spec.phase_id == "post_close"
    assert spec.missing_input_policy == "degraded"
    assert (
        CORPORATE_REPORTING_INTERACTION_ID in spec.allowed_interaction_ids
    )


def test_register_routine_is_idempotent():
    kernel = _kernel()
    a = register_corporate_quarterly_reporting_routine(
        kernel, firm_id=_FIRM_ID
    )
    b = register_corporate_quarterly_reporting_routine(
        kernel, firm_id=_FIRM_ID
    )
    assert a.routine_id == b.routine_id
    assert len(kernel.routines.list_routines()) == 1


def test_register_routine_rejects_empty_firm_id():
    kernel = _kernel()
    with pytest.raises(ValueError):
        register_corporate_quarterly_reporting_routine(kernel, firm_id="")


# ---------------------------------------------------------------------------
# run_corporate_quarterly_reporting — happy path
# ---------------------------------------------------------------------------


def test_run_creates_one_routine_run_record():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    assert isinstance(result, CorporateReportingResult)
    runs = kernel.routines.list_runs_by_routine(result.routine_id)
    assert len(runs) == 1
    assert runs[0].run_id == result.run_id


def test_run_creates_one_reporting_signal():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    signal = kernel.signals.get_signal(result.signal_id)
    assert signal.signal_type == CORPORATE_REPORTING_SIGNAL_TYPE
    assert signal.subject_id == _FIRM_ID
    assert signal.source_id == CORPORATE_REPORTING_SOURCE_ID
    # Only one signal added.
    assert len(kernel.signals.all_signals()) == 1


def test_signal_back_references_routine_run():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    signal = kernel.signals.get_signal(result.signal_id)
    assert result.run_id in signal.related_ids
    assert signal.metadata["routine_run_id"] == result.run_id


def test_run_record_forward_references_signal():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    record = kernel.routines.get_run_record(result.run_id)
    assert result.signal_id in record.output_refs


def test_run_uses_compatible_corporate_self_loop_interaction():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    record = kernel.routines.get_run_record(result.run_id)
    assert record.interaction_ids == (CORPORATE_REPORTING_INTERACTION_ID,)
    interaction = kernel.interactions.get_interaction(
        CORPORATE_REPORTING_INTERACTION_ID
    )
    assert interaction.source_space_id == interaction.target_space_id


# ---------------------------------------------------------------------------
# Payload + status
# ---------------------------------------------------------------------------


def test_signal_payload_carries_synthetic_fields():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(
        kernel,
        firm_id=_FIRM_ID,
        revenue_index=120.0,
        margin_index=0.12,
        leverage_hint=1.5,
        liquidity_hint=2.0,
        confidence=0.9,
    )
    payload = kernel.signals.get_signal(result.signal_id).payload
    assert payload["firm_id"] == _FIRM_ID
    assert payload["revenue_index"] == 120.0
    assert payload["margin_index"] == 0.12
    assert payload["leverage_hint"] == 1.5
    assert payload["liquidity_hint"] == 2.0
    assert payload["confidence"] == 0.9
    assert payload["statement"] == "synthetic quarterly reporting signal"
    assert payload["reporting_period"] == "2026-03-31"


def test_default_status_is_completed_when_inputs_present():
    """Default explicit_input_refs=(firm_id,) → resolved input_refs
    non-empty → "completed"."""
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    assert result.status == "completed"


def test_status_is_degraded_when_no_inputs_supplied():
    """Explicit empty input_refs preserves the v1.8.1 anti-scenario
    discipline: a run with no inputs is *degraded*, not *failed*."""
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(
        kernel, firm_id=_FIRM_ID, explicit_input_refs=()
    )
    assert result.status == "degraded"


# ---------------------------------------------------------------------------
# Date semantics
# ---------------------------------------------------------------------------


def test_as_of_date_defaults_to_clock():
    kernel = _seeded_kernel(current_date=date(2026, 6, 30))
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    assert result.as_of_date == "2026-06-30"


def test_explicit_as_of_date_overrides_clock():
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(
        kernel, firm_id=_FIRM_ID, as_of_date="2026-12-31"
    )
    assert result.as_of_date == "2026-12-31"


def test_helper_rejects_empty_firm_id():
    kernel = _seeded_kernel()
    with pytest.raises(ValueError):
        run_corporate_quarterly_reporting(kernel, firm_id="")


# (The "missing date without clock" path is covered by the v1.8.6
# RoutineEngine tests; ``Clock`` requires a current_date at
# construction, so a kernel-level missing-date scenario cannot be
# manufactured at the helper layer.)


# ---------------------------------------------------------------------------
# Incompatible interaction fails loudly
# ---------------------------------------------------------------------------


def test_run_fails_loudly_when_interaction_not_registered():
    """If only the routine is registered (without the corresponding
    interaction), the engine's compatibility check rejects the
    request."""
    kernel = _kernel()
    register_corporate_quarterly_reporting_routine(kernel, firm_id=_FIRM_ID)
    # interaction NOT registered
    with pytest.raises(RoutineExecutionIncompatibleInteractionError):
        run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)


def test_run_fails_loudly_when_routine_not_registered():
    """The routine spec must exist before the helper runs."""
    kernel = _kernel()
    register_corporate_reporting_interaction(kernel)
    # routine NOT registered
    with pytest.raises(Exception):
        # The engine raises RoutineExecutionValidationError when the
        # routine is unknown.
        run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)


# ---------------------------------------------------------------------------
# Ledger ordering
# ---------------------------------------------------------------------------


def test_ledger_contains_routine_run_recorded_before_signal_added():
    kernel = _seeded_kernel()
    before = len(kernel.ledger.records)
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    new_records = kernel.ledger.records[before:]
    # Engine writes routine_run_recorded; helper then adds the signal
    # (signal_added). Two new records, in this order.
    types_in_order = [r.event_type for r in new_records]
    assert types_in_order == ["routine_run_recorded", "signal_added"]
    # Both records reference the same run_id / signal_id.
    assert new_records[0].object_id == result.run_id
    assert new_records[1].object_id == result.signal_id


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def test_run_does_not_mutate_unrelated_kernel_books():
    """
    The v1.8.7 routine writes only to RoutineBook (one run record)
    and SignalBook (one signal). Every other v0/v1 source-of-truth
    book stays byte-identical.
    """
    kernel = _seeded_kernel()

    # Seed unrelated books with one entry each so snapshot equality
    # is meaningful.
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-03-31", "exchange")

    snaps_before = {
        "ownership": kernel.ownership.snapshot(),
        "contracts": kernel.contracts.snapshot(),
        "prices": kernel.prices.snapshot(),
        "constraints": kernel.constraints.snapshot(),
        "valuations": kernel.valuations.snapshot(),
        "institutions": kernel.institutions.snapshot(),
        "external_processes": kernel.external_processes.snapshot(),
        "relationships": kernel.relationships.snapshot(),
    }

    run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)

    assert kernel.ownership.snapshot() == snaps_before["ownership"]
    assert kernel.contracts.snapshot() == snaps_before["contracts"]
    assert kernel.prices.snapshot() == snaps_before["prices"]
    assert kernel.constraints.snapshot() == snaps_before["constraints"]
    assert kernel.valuations.snapshot() == snaps_before["valuations"]
    assert kernel.institutions.snapshot() == snaps_before["institutions"]
    assert (
        kernel.external_processes.snapshot()
        == snaps_before["external_processes"]
    )
    assert kernel.relationships.snapshot() == snaps_before["relationships"]


def test_kernel_tick_does_not_auto_run_routine():
    """v1.8.6 plumbing rule inherited: tick() must not auto-execute
    the v1.8.7 routine."""
    kernel = _seeded_kernel()
    kernel.tick()
    # No run records, no signals.
    routine_id = (
        f"routine:{CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE}:{_FIRM_ID}"
    )
    assert kernel.routines.list_runs_by_routine(routine_id) == ()
    assert kernel.signals.all_signals() == ()


def test_kernel_run_does_not_auto_run_routine():
    kernel = _seeded_kernel()
    kernel.run(days=5)
    routine_id = (
        f"routine:{CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE}:{_FIRM_ID}"
    )
    assert kernel.routines.list_runs_by_routine(routine_id) == ()
    assert kernel.signals.all_signals() == ()


# ---------------------------------------------------------------------------
# Synthetic-only identifiers
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS: tuple[str, ...] = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
)


def test_signal_payload_uses_only_synthetic_identifiers():
    """The signal must not embed any forbidden Japan-specific token."""
    kernel = _seeded_kernel()
    result = run_corporate_quarterly_reporting(kernel, firm_id=_FIRM_ID)
    signal = kernel.signals.get_signal(result.signal_id)

    def _walk(value):
        if isinstance(value, str):
            lowered = value.lower()
            for token in _FORBIDDEN_TOKENS:
                assert token not in lowered, (
                    f"forbidden token {token!r} in {value!r}"
                )
        elif isinstance(value, dict):
            for v in value.values():
                _walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                _walk(v)

    _walk(signal.signal_id)
    _walk(signal.source_id)
    _walk(dict(signal.payload))
    _walk(dict(signal.metadata))


def test_constants_are_synthetic_only():
    for value in (
        CORPORATE_REPORTING_INTERACTION_ID,
        CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE,
        CORPORATE_REPORTING_SIGNAL_TYPE,
        CORPORATE_REPORTING_SOURCE_ID,
    ):
        lowered = value.lower()
        for token in _FORBIDDEN_TOKENS:
            assert token not in lowered, (
                f"forbidden token {token!r} in module constant {value!r}"
            )


# ---------------------------------------------------------------------------
# Multiple firms / multiple periods
# ---------------------------------------------------------------------------


def test_multiple_firms_each_get_their_own_routine():
    """Different firms produce separate routine specs and run records."""
    kernel = _kernel()
    register_corporate_reporting_interaction(kernel)
    register_corporate_quarterly_reporting_routine(
        kernel, firm_id="firm:reference_manufacturer_a"
    )
    register_corporate_quarterly_reporting_routine(
        kernel, firm_id="firm:reference_manufacturer_b"
    )
    res_a = run_corporate_quarterly_reporting(
        kernel, firm_id="firm:reference_manufacturer_a"
    )
    res_b = run_corporate_quarterly_reporting(
        kernel, firm_id="firm:reference_manufacturer_b"
    )
    assert res_a.routine_id != res_b.routine_id
    assert res_a.signal_id != res_b.signal_id
    # Two run records, two signals.
    assert len(kernel.signals.all_signals()) == 2


def test_same_firm_different_periods_produce_distinct_records():
    kernel = _seeded_kernel()
    res_q1 = run_corporate_quarterly_reporting(
        kernel, firm_id=_FIRM_ID, as_of_date="2026-03-31"
    )
    res_q2 = run_corporate_quarterly_reporting(
        kernel, firm_id=_FIRM_ID, as_of_date="2026-06-30"
    )
    assert res_q1.run_id != res_q2.run_id
    assert res_q1.signal_id != res_q2.signal_id
    # Same routine spec; two run records.
    routine_id = (
        f"routine:{CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE}:{_FIRM_ID}"
    )
    assert len(kernel.routines.list_runs_by_routine(routine_id)) == 2
