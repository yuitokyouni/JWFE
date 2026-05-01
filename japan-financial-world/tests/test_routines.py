"""
Tests for v1.8.4 RoutineBook + RoutineRunRecord.

Covers ``RoutineSpec`` + ``RoutineRunRecord`` field validation,
``RoutineBook`` CRUD + filter listings (routines and run records),
the ``routine_can_use_interaction`` predicate against an
``InteractionBook``, ledger emission of ``ROUTINE_ADDED`` and
``ROUTINE_RUN_RECORDED``, snapshot determinism, kernel wiring, and
the no-mutation guarantee against every other v0/v1 source-of-truth
book.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.interactions import InteractionBook, InteractionSpec
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.routines import (
    DuplicateRoutineError,
    DuplicateRoutineRunError,
    RoutineBook,
    RoutineRunRecord,
    RoutineSpec,
    UnknownRoutineError,
    UnknownRoutineRunError,
)
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    *,
    routine_id: str = "routine:corporate.quarterly_reporting:firm_a",
    routine_type: str = "corporate_quarterly_reporting",
    owner_space_id: str = "corporate",
    owner_id: str | None = "firm:reference_manufacturer_a",
    frequency: str = "QUARTERLY",
    phase_id: str | None = "post_close",
    enabled: bool = True,
    required_input_ref_types: tuple[str, ...] = ("FundamentalsRecord",),
    optional_input_ref_types: tuple[str, ...] = ("ExternalFactorObservation",),
    output_ref_types: tuple[str, ...] = (
        "ValuationRecord",
        "InformationSignal",
    ),
    allowed_interaction_ids: tuple[str, ...] = (
        "interaction:corporate.earnings_to_information",
    ),
    missing_input_policy: str = "degraded",
    metadata: dict | None = None,
) -> RoutineSpec:
    return RoutineSpec(
        routine_id=routine_id,
        routine_type=routine_type,
        owner_space_id=owner_space_id,
        owner_id=owner_id,
        frequency=frequency,
        phase_id=phase_id,
        enabled=enabled,
        required_input_ref_types=required_input_ref_types,
        optional_input_ref_types=optional_input_ref_types,
        output_ref_types=output_ref_types,
        allowed_interaction_ids=allowed_interaction_ids,
        missing_input_policy=missing_input_policy,
        metadata=metadata or {},
    )


def _run(
    *,
    run_id: str = "run:routine:corporate.quarterly_reporting:firm_a:2026-03-31",
    routine_id: str = "routine:corporate.quarterly_reporting:firm_a",
    routine_type: str = "corporate_quarterly_reporting",
    owner_space_id: str = "corporate",
    owner_id: str | None = "firm:reference_manufacturer_a",
    as_of_date: str = "2026-03-31",
    phase_id: str | None = "post_close",
    input_refs: tuple[str, ...] = ("fundamentals:firm_a:2026Q1",),
    output_refs: tuple[str, ...] = ("valuation:firm_a:2026Q1",),
    interaction_ids: tuple[str, ...] = (
        "interaction:corporate.earnings_to_information",
    ),
    parent_record_ids: tuple[str, ...] = (),
    status: str = "completed",
    metadata: dict | None = None,
) -> RoutineRunRecord:
    return RoutineRunRecord(
        run_id=run_id,
        routine_id=routine_id,
        routine_type=routine_type,
        owner_space_id=owner_space_id,
        owner_id=owner_id,
        as_of_date=as_of_date,
        phase_id=phase_id,
        input_refs=input_refs,
        output_refs=output_refs,
        interaction_ids=interaction_ids,
        parent_record_ids=parent_record_ids,
        status=status,
        metadata=metadata or {},
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
    enabled: bool = True,
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
        enabled=enabled,
    )


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# RoutineSpec validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"routine_id": ""},
        {"routine_type": ""},
        {"owner_space_id": ""},
        {"frequency": ""},
        {"missing_input_policy": ""},
        {"owner_id": ""},
        {"phase_id": ""},
    ],
)
def test_routine_spec_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _spec(**kwargs)


def test_routine_spec_rejects_non_bool_enabled():
    with pytest.raises(ValueError):
        _spec(enabled="yes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tuple_field",
    [
        "required_input_ref_types",
        "optional_input_ref_types",
        "output_ref_types",
        "allowed_interaction_ids",
    ],
)
def test_routine_spec_rejects_empty_strings_in_tuple_fields(tuple_field):
    bad = {tuple_field: ("valid", "")}
    with pytest.raises(ValueError):
        _spec(**bad)


def test_routine_spec_normalizes_tuple_fields_to_tuples():
    spec = _spec(
        required_input_ref_types=["FundamentalsRecord"],
        allowed_interaction_ids=["interaction:a", "interaction:b"],
    )
    assert isinstance(spec.required_input_ref_types, tuple)
    assert isinstance(spec.allowed_interaction_ids, tuple)


def test_routine_spec_is_frozen():
    spec = _spec()
    with pytest.raises(Exception):
        spec.routine_id = "tampered"  # type: ignore[misc]


def test_routine_spec_to_dict_round_trips_fields():
    spec = _spec()
    d = spec.to_dict()
    assert d["routine_id"] == spec.routine_id
    assert d["routine_type"] == spec.routine_type
    assert d["owner_space_id"] == spec.owner_space_id
    assert d["frequency"] == spec.frequency
    assert d["missing_input_policy"] == spec.missing_input_policy
    assert d["allowed_interaction_ids"] == list(spec.allowed_interaction_ids)


def test_routine_spec_default_missing_input_policy_is_degraded():
    """v1.8.1 anti-scenario default: routines should remain endogenous."""
    spec = RoutineSpec(
        routine_id="routine:x",
        routine_type="x",
        owner_space_id="corporate",
        frequency="DAILY",
    )
    assert spec.missing_input_policy == "degraded"


# ---------------------------------------------------------------------------
# RoutineRunRecord validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run_id": ""},
        {"routine_id": ""},
        {"routine_type": ""},
        {"owner_space_id": ""},
        {"as_of_date": ""},
        {"status": ""},
        {"owner_id": ""},
        {"phase_id": ""},
    ],
)
def test_run_record_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _run(**kwargs)


def test_run_record_coerces_date_to_iso_string():
    record = _run(as_of_date=date(2026, 3, 31))
    assert record.as_of_date == "2026-03-31"
    assert isinstance(record.as_of_date, str)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "input_refs",
        "output_refs",
        "interaction_ids",
        "parent_record_ids",
    ],
)
def test_run_record_rejects_empty_strings_in_tuple_fields(tuple_field):
    bad = {tuple_field: ("valid", "")}
    with pytest.raises(ValueError):
        _run(**bad)


def test_run_record_is_frozen():
    record = _run()
    with pytest.raises(Exception):
        record.run_id = "tampered"  # type: ignore[misc]


def test_run_record_to_dict_round_trips_fields():
    record = _run(parent_record_ids=("rec_abc", "rec_def"))
    d = record.to_dict()
    assert d["run_id"] == record.run_id
    assert d["routine_id"] == record.routine_id
    assert d["status"] == record.status
    assert d["parent_record_ids"] == ["rec_abc", "rec_def"]


# ---------------------------------------------------------------------------
# RoutineBook: routine CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_routine():
    book = RoutineBook()
    spec = _spec()
    book.add_routine(spec)
    assert book.get_routine(spec.routine_id) is spec


def test_get_routine_unknown_raises():
    book = RoutineBook()
    with pytest.raises(UnknownRoutineError):
        book.get_routine("routine:does_not_exist")


def test_duplicate_routine_id_rejected():
    book = RoutineBook()
    book.add_routine(_spec())
    with pytest.raises(DuplicateRoutineError):
        book.add_routine(_spec())


# ---------------------------------------------------------------------------
# RoutineBook: filter listings
# ---------------------------------------------------------------------------


def _seed_typical_routines(book: RoutineBook) -> None:
    book.add_routine(
        _spec(
            routine_id="routine:corp.quarterly:firm_a",
            routine_type="corporate_quarterly_reporting",
            owner_space_id="corporate",
            owner_id="firm:reference_manufacturer_a",
            frequency="QUARTERLY",
        )
    )
    book.add_routine(
        _spec(
            routine_id="routine:corp.quarterly:firm_b",
            routine_type="corporate_quarterly_reporting",
            owner_space_id="corporate",
            owner_id="firm:reference_manufacturer_b",
            frequency="QUARTERLY",
        )
    )
    book.add_routine(
        _spec(
            routine_id="routine:bank.review:bank_a",
            routine_type="bank_review",
            owner_space_id="banking",
            owner_id="bank:reference_bank_a",
            frequency="MONTHLY",
            allowed_interaction_ids=("interaction:bank.review_to_corporate",),
        )
    )
    book.add_routine(
        _spec(
            routine_id="routine:investor.review:fund_a",
            routine_type="investor_review",
            owner_space_id="investors",
            owner_id="investor:reference_pension_a",
            frequency="MONTHLY",
            allowed_interaction_ids=(),
        )
    )


def test_list_routines_returns_all_enabled():
    book = RoutineBook()
    _seed_typical_routines(book)
    assert len(book.list_routines()) == 4


def test_list_by_type():
    book = RoutineBook()
    _seed_typical_routines(book)
    quarterly = book.list_by_type("corporate_quarterly_reporting")
    assert {r.routine_id for r in quarterly} == {
        "routine:corp.quarterly:firm_a",
        "routine:corp.quarterly:firm_b",
    }
    assert book.list_by_type("does_not_exist") == ()


def test_list_by_owner_space():
    book = RoutineBook()
    _seed_typical_routines(book)
    corp = book.list_by_owner_space("corporate")
    assert len(corp) == 2
    bank = book.list_by_owner_space("banking")
    assert len(bank) == 1
    assert book.list_by_owner_space("real_estate") == ()


def test_list_by_frequency():
    book = RoutineBook()
    _seed_typical_routines(book)
    quarterly = book.list_by_frequency("QUARTERLY")
    assert len(quarterly) == 2
    monthly = book.list_by_frequency("MONTHLY")
    assert len(monthly) == 2


def test_list_for_interaction():
    book = RoutineBook()
    _seed_typical_routines(book)
    using = book.list_for_interaction(
        "interaction:corporate.earnings_to_information"
    )
    assert {r.routine_id for r in using} == {
        "routine:corp.quarterly:firm_a",
        "routine:corp.quarterly:firm_b",
    }
    assert book.list_for_interaction("interaction:unknown") == ()


# ---------------------------------------------------------------------------
# Disabled routines
# ---------------------------------------------------------------------------


def test_disabled_routines_excluded_by_default():
    book = RoutineBook()
    book.add_routine(_spec(routine_id="routine:enabled_one"))
    book.add_routine(_spec(routine_id="routine:disabled_one", enabled=False))
    listed = book.list_routines()
    assert {s.routine_id for s in listed} == {"routine:enabled_one"}


def test_disabled_routines_included_with_flag():
    book = RoutineBook()
    book.add_routine(_spec(routine_id="routine:enabled_one"))
    book.add_routine(_spec(routine_id="routine:disabled_one", enabled=False))
    listed = book.list_routines(include_disabled=True)
    assert {s.routine_id for s in listed} == {
        "routine:enabled_one",
        "routine:disabled_one",
    }


def test_disabled_excluded_from_filter_listings_too():
    book = RoutineBook()
    book.add_routine(
        _spec(routine_id="routine:a", routine_type="t", owner_space_id="s")
    )
    book.add_routine(
        _spec(
            routine_id="routine:b",
            routine_type="t",
            owner_space_id="s",
            enabled=False,
        )
    )
    assert {r.routine_id for r in book.list_by_type("t")} == {"routine:a"}
    assert {
        r.routine_id for r in book.list_by_type("t", include_disabled=True)
    } == {"routine:a", "routine:b"}


# ---------------------------------------------------------------------------
# RoutineBook: run record CRUD + listings
# ---------------------------------------------------------------------------


def test_add_and_get_run_record():
    book = RoutineBook()
    record = _run()
    book.add_run_record(record)
    assert book.get_run_record(record.run_id) is record


def test_get_run_record_unknown_raises():
    book = RoutineBook()
    with pytest.raises(UnknownRoutineRunError):
        book.get_run_record("run:does_not_exist")


def test_duplicate_run_id_rejected():
    book = RoutineBook()
    book.add_run_record(_run())
    with pytest.raises(DuplicateRoutineRunError):
        book.add_run_record(_run())


def test_list_runs_by_routine():
    book = RoutineBook()
    book.add_run_record(_run(run_id="run:a", routine_id="routine:x"))
    book.add_run_record(_run(run_id="run:b", routine_id="routine:x"))
    book.add_run_record(_run(run_id="run:c", routine_id="routine:y"))
    x_runs = book.list_runs_by_routine("routine:x")
    assert {r.run_id for r in x_runs} == {"run:a", "run:b"}
    assert book.list_runs_by_routine("routine:unknown") == ()


def test_list_runs_by_date_accepts_str_and_date():
    book = RoutineBook()
    book.add_run_record(_run(run_id="run:a", as_of_date="2026-03-31"))
    book.add_run_record(_run(run_id="run:b", as_of_date="2026-03-31"))
    book.add_run_record(_run(run_id="run:c", as_of_date="2026-06-30"))
    by_str = book.list_runs_by_date("2026-03-31")
    by_date = book.list_runs_by_date(date(2026, 3, 31))
    assert {r.run_id for r in by_str} == {"run:a", "run:b"}
    assert {r.run_id for r in by_date} == {"run:a", "run:b"}
    assert book.list_runs_by_date("2026-12-31") == ()


def test_list_runs_by_status():
    book = RoutineBook()
    book.add_run_record(_run(run_id="run:a", status="completed"))
    book.add_run_record(_run(run_id="run:b", status="degraded"))
    book.add_run_record(_run(run_id="run:c", status="failed"))
    book.add_run_record(_run(run_id="run:d", status="partial"))
    assert {r.run_id for r in book.list_runs_by_status("completed")} == {"run:a"}
    assert {r.run_id for r in book.list_runs_by_status("degraded")} == {"run:b"}
    assert {r.run_id for r in book.list_runs_by_status("failed")} == {"run:c"}
    assert {r.run_id for r in book.list_runs_by_status("partial")} == {"run:d"}
    assert book.list_runs_by_status("nonexistent") == ()


# ---------------------------------------------------------------------------
# Status vocabulary + missing_input_policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status",
    ["completed", "partial", "degraded", "failed"],
)
def test_run_record_accepts_recommended_status_vocabulary(status):
    """The recommended vocabulary must round-trip cleanly."""
    record = _run(status=status)
    assert record.status == status


def test_routine_spec_stores_missing_input_policy():
    """missing_input_policy is free-form but stored as-is."""
    spec_degraded = _spec(missing_input_policy="degraded")
    spec_strict = _spec(
        routine_id="routine:strict",
        missing_input_policy="strict",
    )
    spec_skip = _spec(
        routine_id="routine:skip",
        missing_input_policy="skip",
    )
    spec_custom = _spec(
        routine_id="routine:custom",
        missing_input_policy="custom_policy_label",
    )
    assert spec_degraded.missing_input_policy == "degraded"
    assert spec_strict.missing_input_policy == "strict"
    assert spec_skip.missing_input_policy == "skip"
    assert spec_custom.missing_input_policy == "custom_policy_label"


def test_run_record_preserves_parent_record_ids():
    record = _run(
        parent_record_ids=("rec_alpha", "rec_beta", "rec_gamma"),
    )
    assert record.parent_record_ids == ("rec_alpha", "rec_beta", "rec_gamma")


# ---------------------------------------------------------------------------
# routine_can_use_interaction predicate
# ---------------------------------------------------------------------------


def test_routine_can_use_interaction_positive_case():
    rb = RoutineBook()
    ib = InteractionBook()
    rb.add_routine(_spec())
    ib.add_interaction(_interaction())
    assert rb.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:corporate.earnings_to_information",
        ib,
    ) is True


def test_routine_can_use_interaction_false_when_routine_type_not_allowed():
    rb = RoutineBook()
    ib = InteractionBook()
    rb.add_routine(_spec(routine_type="bank_review"))
    ib.add_interaction(
        _interaction(
            routine_types_that_may_use_this_channel=(
                "corporate_quarterly_reporting",
            )
        )
    )
    # Routine declares the channel but interaction does not list bank_review.
    assert rb.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:corporate.earnings_to_information",
        ib,
    ) is False


def test_routine_can_use_interaction_false_when_not_in_allowed_interaction_ids():
    rb = RoutineBook()
    ib = InteractionBook()
    rb.add_routine(_spec(allowed_interaction_ids=("interaction:other",)))
    ib.add_interaction(_interaction())
    # Topology side allows it but routine did not declare the channel.
    assert rb.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:corporate.earnings_to_information",
        ib,
    ) is False


def test_routine_can_use_interaction_unknown_routine_raises():
    rb = RoutineBook()
    ib = InteractionBook()
    ib.add_interaction(_interaction())
    with pytest.raises(UnknownRoutineError):
        rb.routine_can_use_interaction(
            "routine:does_not_exist",
            "interaction:corporate.earnings_to_information",
            ib,
        )


def test_routine_can_use_interaction_unknown_interaction_returns_false():
    """
    Documented behavior: unknown interaction_id returns False rather
    than raising. The predicate must be safe to call against any
    pair of ids.
    """
    rb = RoutineBook()
    ib = InteractionBook()
    rb.add_routine(_spec(allowed_interaction_ids=("interaction:nowhere",)))
    assert rb.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:nowhere",
        ib,
    ) is False


def test_routine_can_use_interaction_empty_allowed_types_means_any():
    """v1.8.3 / v1.8.2 semantics: empty tuple = any routine type."""
    rb = RoutineBook()
    ib = InteractionBook()
    rb.add_routine(
        _spec(
            routine_type="some_brand_new_routine_type",
            allowed_interaction_ids=("interaction:open_channel",),
        )
    )
    ib.add_interaction(
        _interaction(
            interaction_id="interaction:open_channel",
            routine_types_that_may_use_this_channel=(),
        )
    )
    assert rb.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:open_channel",
        ib,
    ) is True


def test_routine_can_use_interaction_does_not_mutate_either_book():
    rb = RoutineBook()
    ib = InteractionBook()
    rb.add_routine(_spec())
    ib.add_interaction(_interaction())
    rb_snap = rb.snapshot()
    ib_snap = ib.snapshot()
    rb.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:corporate.earnings_to_information",
        ib,
    )
    assert rb.snapshot() == rb_snap
    assert ib.snapshot() == ib_snap


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_and_sorted():
    book = RoutineBook()
    _seed_typical_routines(book)
    book.add_run_record(_run(run_id="run:beta"))
    book.add_run_record(_run(run_id="run:alpha"))
    snap_a = book.snapshot()
    snap_b = book.snapshot()
    assert snap_a == snap_b
    routine_ids = [r["routine_id"] for r in snap_a["routines"]]
    run_ids = [r["run_id"] for r in snap_a["runs"]]
    assert routine_ids == sorted(routine_ids)
    assert run_ids == sorted(run_ids)


def test_snapshot_counts_disabled_separately():
    book = RoutineBook()
    book.add_routine(_spec(routine_id="routine:enabled", enabled=True))
    book.add_routine(_spec(routine_id="routine:disabled", enabled=False))
    snap = book.snapshot()
    assert snap["routine_count"] == 2
    assert snap["enabled_routine_count"] == 1
    assert snap["run_count"] == 0


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_types_exist():
    assert RecordType.ROUTINE_ADDED.value == "routine_added"
    assert RecordType.ROUTINE_RUN_RECORDED.value == "routine_run_recorded"


def test_add_routine_writes_ledger_record_when_present():
    ledger = Ledger()
    clock = Clock(current_date=date(2026, 1, 1))
    book = RoutineBook(ledger=ledger, clock=clock)
    spec = _spec()
    book.add_routine(spec)
    records = ledger.filter(event_type="routine_added")
    assert len(records) == 1
    rec = records[0]
    assert rec.object_id == spec.routine_id
    assert rec.payload["routine_type"] == spec.routine_type
    assert rec.payload["missing_input_policy"] == spec.missing_input_policy


def test_add_run_record_writes_ledger_record_when_present():
    ledger = Ledger()
    clock = Clock(current_date=date(2026, 1, 1))
    book = RoutineBook(ledger=ledger, clock=clock)
    record = _run(parent_record_ids=("rec_alpha",))
    book.add_run_record(record)
    records = ledger.filter(event_type="routine_run_recorded")
    assert len(records) == 1
    rec = records[0]
    assert rec.object_id == record.run_id
    # Use as_of_date as the simulation_date (not the clock).
    assert rec.simulation_date == record.as_of_date
    # parent_record_ids preserved on the ledger entry.
    assert "rec_alpha" in rec.parent_record_ids


def test_add_routine_without_ledger_does_not_raise():
    book = RoutineBook()
    book.add_routine(_spec())


def test_add_run_record_without_ledger_does_not_raise():
    book = RoutineBook()
    book.add_run_record(_run())


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_routines_book():
    kernel = _kernel()
    assert isinstance(kernel.routines, RoutineBook)
    assert kernel.routines.ledger is kernel.ledger
    assert kernel.routines.clock is kernel.clock


def test_kernel_add_routine_emits_to_kernel_ledger():
    kernel = _kernel()
    kernel.routines.add_routine(_spec())
    records = kernel.ledger.filter(event_type="routine_added")
    assert len(records) == 1


def test_kernel_routine_can_use_interaction_uses_interactions_book():
    """The predicate should compose cleanly with the kernel's
    InteractionBook field."""
    kernel = _kernel()
    kernel.routines.add_routine(_spec())
    kernel.interactions.add_interaction(_interaction())
    assert kernel.routines.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:corporate.earnings_to_information",
        kernel.interactions,
    ) is True


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def test_routine_book_does_not_mutate_other_kernel_books():
    """
    Adding routines and run records, building snapshots, and using
    the predicate must not mutate any other source-of-truth book.
    """
    kernel = _kernel()

    # Seed unrelated books with one entry each so snapshot equality
    # is meaningful.
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-01-01", "exchange")
    kernel.interactions.add_interaction(_interaction())

    ownership_before = kernel.ownership.snapshot()
    contracts_before = kernel.contracts.snapshot()
    prices_before = kernel.prices.snapshot()
    constraints_before = kernel.constraints.snapshot()
    signals_before = kernel.signals.snapshot()
    valuations_before = kernel.valuations.snapshot()
    institutions_before = kernel.institutions.snapshot()
    external_processes_before = kernel.external_processes.snapshot()
    relationships_before = kernel.relationships.snapshot()
    interactions_before = kernel.interactions.snapshot()

    kernel.routines.add_routine(_spec())
    kernel.routines.add_run_record(_run())
    kernel.routines.list_routines()
    kernel.routines.list_by_type("corporate_quarterly_reporting")
    kernel.routines.list_by_owner_space("corporate")
    kernel.routines.list_by_frequency("QUARTERLY")
    kernel.routines.list_for_interaction(
        "interaction:corporate.earnings_to_information"
    )
    kernel.routines.list_runs_by_routine(
        "routine:corporate.quarterly_reporting:firm_a"
    )
    kernel.routines.list_runs_by_date("2026-03-31")
    kernel.routines.list_runs_by_status("completed")
    kernel.routines.routine_can_use_interaction(
        "routine:corporate.quarterly_reporting:firm_a",
        "interaction:corporate.earnings_to_information",
        kernel.interactions,
    )
    kernel.routines.snapshot()

    assert kernel.ownership.snapshot() == ownership_before
    assert kernel.contracts.snapshot() == contracts_before
    assert kernel.prices.snapshot() == prices_before
    assert kernel.constraints.snapshot() == constraints_before
    assert kernel.signals.snapshot() == signals_before
    assert kernel.valuations.snapshot() == valuations_before
    assert kernel.institutions.snapshot() == institutions_before
    assert kernel.external_processes.snapshot() == external_processes_before
    assert kernel.relationships.snapshot() == relationships_before
    assert kernel.interactions.snapshot() == interactions_before
