"""
Tests for v1.8.10 ExposureBook.

Covers ``ExposureRecord`` field validation, ``ExposureBook`` CRUD +
filter listings, the validity-window filter (`list_active_as_of`),
ledger emission of `EXPOSURE_ADDED`, snapshot determinism, kernel
wiring, and the no-mutation guarantee against every other v0/v1
source-of-truth book.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.exposures import (
    DuplicateExposureError,
    ExposureBook,
    ExposureRecord,
    UnknownExposureError,
)
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _record(
    *,
    exposure_id: str = "exposure:firm_a:packaging:cost",
    subject_id: str = "firm:reference_food_processor_a",
    subject_type: str = "firm",
    variable_id: str = "variable:petrochemical_input_cost",
    exposure_type: str = "input_cost",
    metric: str = "packaging_margin_pressure",
    direction: str = "positive",
    magnitude: float = 0.45,
    unit: str = "input_cost_share",
    confidence: float = 0.7,
    effective_from: str | None = None,
    effective_to: str | None = None,
    source_ref_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> ExposureRecord:
    return ExposureRecord(
        exposure_id=exposure_id,
        subject_id=subject_id,
        subject_type=subject_type,
        variable_id=variable_id,
        exposure_type=exposure_type,
        metric=metric,
        direction=direction,
        magnitude=magnitude,
        unit=unit,
        confidence=confidence,
        effective_from=effective_from,
        effective_to=effective_to,
        source_ref_ids=source_ref_ids,
        metadata=metadata or {},
    )


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# ExposureRecord field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exposure_id": ""},
        {"subject_id": ""},
        {"subject_type": ""},
        {"variable_id": ""},
        {"exposure_type": ""},
        {"metric": ""},
        {"direction": ""},
        {"unit": ""},
        {"effective_from": ""},
        {"effective_to": ""},
    ],
)
def test_record_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _record(**kwargs)


def test_record_rejects_empty_strings_in_source_ref_ids():
    with pytest.raises(ValueError):
        _record(source_ref_ids=("valid", ""))


@pytest.mark.parametrize("magnitude", [-0.01, 1.01, 2.0, -1.0])
def test_record_rejects_magnitude_out_of_bounds(magnitude):
    with pytest.raises(ValueError):
        _record(magnitude=magnitude)


def test_record_magnitude_bounds_inclusive():
    _record(magnitude=0.0)
    _record(magnitude=1.0)


def test_record_rejects_non_numeric_magnitude():
    with pytest.raises(ValueError):
        _record(magnitude="high")  # type: ignore[arg-type]


def test_record_rejects_bool_magnitude():
    """bool is a subclass of int; should not slip through."""
    with pytest.raises(ValueError):
        _record(magnitude=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("conf", [-0.1, 1.1, 2.0, -1.0])
def test_record_rejects_confidence_out_of_bounds(conf):
    with pytest.raises(ValueError):
        _record(confidence=conf)


def test_record_confidence_bounds_inclusive():
    _record(confidence=0.0)
    _record(confidence=1.0)


def test_record_rejects_bool_confidence():
    with pytest.raises(ValueError):
        _record(confidence=True)  # type: ignore[arg-type]


def test_record_coerces_date_objects_to_iso_strings():
    r = _record(
        effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31)
    )
    assert r.effective_from == "2026-01-01"
    assert r.effective_to == "2026-12-31"


def test_record_rejects_inverted_validity_window():
    with pytest.raises(ValueError):
        _record(effective_from="2026-12-31", effective_to="2026-01-01")


def test_record_normalizes_source_ref_ids_to_tuple():
    r = _record(source_ref_ids=["signal:a", "doc:b"])
    assert isinstance(r.source_ref_ids, tuple)
    assert r.source_ref_ids == ("signal:a", "doc:b")


def test_record_is_frozen():
    r = _record()
    with pytest.raises(Exception):
        r.exposure_id = "tampered"  # type: ignore[misc]


def test_record_to_dict_round_trips_fields():
    r = _record(
        effective_from="2026-01-01",
        effective_to="2026-12-31",
        source_ref_ids=("signal:a",),
        metadata={"transmission_chain": ["a", "b"]},
    )
    d = r.to_dict()
    assert d["exposure_id"] == r.exposure_id
    assert d["subject_id"] == r.subject_id
    assert d["variable_id"] == r.variable_id
    assert d["magnitude"] == r.magnitude
    assert d["effective_from"] == "2026-01-01"
    assert d["source_ref_ids"] == ["signal:a"]
    assert d["metadata"] == {"transmission_chain": ["a", "b"]}


# ---------------------------------------------------------------------------
# is_active_as_of property method
# ---------------------------------------------------------------------------


def test_is_active_as_of_inside_window():
    r = _record(effective_from="2026-01-01", effective_to="2026-12-31")
    assert r.is_active_as_of("2026-06-15") is True


def test_is_active_as_of_before_window():
    r = _record(effective_from="2026-01-01", effective_to="2026-12-31")
    assert r.is_active_as_of("2025-12-31") is False


def test_is_active_as_of_after_window():
    r = _record(effective_from="2026-01-01", effective_to="2026-12-31")
    assert r.is_active_as_of("2027-01-01") is False


def test_is_active_as_of_inclusive_at_bounds():
    r = _record(effective_from="2026-01-01", effective_to="2026-12-31")
    assert r.is_active_as_of("2026-01-01") is True
    assert r.is_active_as_of("2026-12-31") is True


def test_is_active_as_of_open_ended_lower_bound():
    """effective_from=None means -infinity → always active up to upper."""
    r = _record(effective_from=None, effective_to="2026-12-31")
    assert r.is_active_as_of("1900-01-01") is True
    assert r.is_active_as_of("2099-01-01") is False


def test_is_active_as_of_open_ended_upper_bound():
    """effective_to=None means +infinity → always active from lower."""
    r = _record(effective_from="2026-01-01", effective_to=None)
    assert r.is_active_as_of("2099-01-01") is True
    assert r.is_active_as_of("2025-12-31") is False


def test_is_active_as_of_both_bounds_open():
    """Both None → record is always active."""
    r = _record(effective_from=None, effective_to=None)
    assert r.is_active_as_of("1900-01-01") is True
    assert r.is_active_as_of("2099-12-31") is True


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_exposure():
    book = ExposureBook()
    r = _record()
    book.add_exposure(r)
    assert book.get_exposure(r.exposure_id) is r


def test_get_unknown_raises():
    book = ExposureBook()
    with pytest.raises(UnknownExposureError):
        book.get_exposure("exposure:does_not_exist")


def test_duplicate_exposure_id_rejected():
    book = ExposureBook()
    book.add_exposure(_record())
    with pytest.raises(DuplicateExposureError):
        book.add_exposure(_record())


def test_book_does_not_validate_variable_id_against_other_books():
    """Cross-reference rule: variable_id is data, not validated."""
    book = ExposureBook()
    book.add_exposure(
        _record(
            exposure_id="exposure:freestanding",
            variable_id="variable:never_registered_anywhere",
        )
    )


# ---------------------------------------------------------------------------
# Filter listings
# ---------------------------------------------------------------------------


def _seed_typical_exposures(book: ExposureBook) -> None:
    """A small but realistic set of exposures covering the
    examples called out in the v1.8.10 spec."""
    book.add_exposure(
        _record(
            exposure_id="exposure:food_processor_a:packaging",
            subject_id="firm:reference_food_processor_a",
            subject_type="firm",
            variable_id="variable:petrochemical_input_cost",
            exposure_type="input_cost",
            metric="packaging_margin_pressure",
            direction="positive",
            magnitude=0.45,
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:property_op_a:debt_service",
            subject_id="firm:reference_property_operator_a",
            subject_type="firm",
            variable_id="variable:policy_rate",
            exposure_type="funding_cost",
            metric="debt_service_burden",
            direction="positive",
            magnitude=0.7,
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:bank_a:collateral",
            subject_id="bank:reference_bank_a",
            subject_type="bank",
            variable_id="variable:land_price_index_reference",
            exposure_type="collateral",
            metric="collateral_value",
            direction="positive",
            magnitude=0.6,
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:macro_fund_a:translation",
            subject_id="investor:reference_macro_fund_a",
            subject_type="investor",
            variable_id="variable:usd_jpy",
            exposure_type="translation",
            metric="portfolio_translation_exposure",
            direction="mixed",
            magnitude=0.4,
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:elec_manufacturer_a:energy",
            subject_id="firm:reference_electric_manufacturer_a",
            subject_type="firm",
            variable_id="variable:electricity_price_index",
            exposure_type="input_cost",
            metric="operating_cost_pressure",
            direction="positive",
            magnitude=0.55,
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:labor_sector_a:ai_displacement",
            subject_id="sector:reference_labor_sector_a",
            subject_type="sector",
            variable_id="variable:automation_adoption_index",
            exposure_type="labor_displacement",
            metric="labor_displacement_risk",
            direction="negative",
            magnitude=0.3,
        )
    )


def test_list_exposures_returns_all():
    book = ExposureBook()
    _seed_typical_exposures(book)
    assert len(book.list_exposures()) == 6


def test_list_by_subject():
    book = ExposureBook()
    _seed_typical_exposures(book)
    food = book.list_by_subject("firm:reference_food_processor_a")
    assert {r.exposure_id for r in food} == {
        "exposure:food_processor_a:packaging"
    }
    assert book.list_by_subject("firm:does_not_exist") == ()


def test_list_by_subject_type():
    book = ExposureBook()
    _seed_typical_exposures(book)
    firms = book.list_by_subject_type("firm")
    assert len(firms) == 3
    assert {r.subject_type for r in firms} == {"firm"}
    banks = book.list_by_subject_type("bank")
    assert len(banks) == 1
    sectors = book.list_by_subject_type("sector")
    assert len(sectors) == 1


def test_list_by_variable():
    book = ExposureBook()
    _seed_typical_exposures(book)
    rate = book.list_by_variable("variable:policy_rate")
    assert {r.exposure_id for r in rate} == {
        "exposure:property_op_a:debt_service"
    }
    assert book.list_by_variable("variable:never_registered") == ()


def test_list_by_exposure_type():
    book = ExposureBook()
    _seed_typical_exposures(book)
    input_cost = book.list_by_exposure_type("input_cost")
    assert len(input_cost) == 2
    assert {r.metric for r in input_cost} == {
        "packaging_margin_pressure",
        "operating_cost_pressure",
    }
    funding = book.list_by_exposure_type("funding_cost")
    assert len(funding) == 1


def test_list_by_metric():
    book = ExposureBook()
    _seed_typical_exposures(book)
    pressure = book.list_by_metric("packaging_margin_pressure")
    assert len(pressure) == 1
    assert book.list_by_metric("nonexistent_metric") == ()


def test_list_by_direction():
    book = ExposureBook()
    _seed_typical_exposures(book)
    positive = book.list_by_direction("positive")
    assert len(positive) == 4
    mixed = book.list_by_direction("mixed")
    assert len(mixed) == 1
    negative = book.list_by_direction("negative")
    assert len(negative) == 1


# ---------------------------------------------------------------------------
# list_active_as_of
# ---------------------------------------------------------------------------


def test_list_active_as_of_filters_by_window():
    book = ExposureBook()
    book.add_exposure(
        _record(
            exposure_id="exposure:past",
            effective_from="2025-01-01",
            effective_to="2025-12-31",
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:current",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
        )
    )
    book.add_exposure(
        _record(
            exposure_id="exposure:future",
            effective_from="2027-01-01",
            effective_to="2027-12-31",
        )
    )
    active = book.list_active_as_of("2026-06-15")
    assert {r.exposure_id for r in active} == {"exposure:current"}


def test_list_active_as_of_includes_open_ended_records():
    book = ExposureBook()
    book.add_exposure(
        _record(
            exposure_id="exposure:always_open",
            effective_from=None,
            effective_to=None,
        )
    )
    assert len(book.list_active_as_of("1900-01-01")) == 1
    assert len(book.list_active_as_of("2099-12-31")) == 1


def test_list_active_as_of_accepts_date_object():
    book = ExposureBook()
    book.add_exposure(
        _record(
            exposure_id="exposure:current",
            effective_from="2026-01-01",
            effective_to="2026-12-31",
        )
    )
    assert (
        len(book.list_active_as_of(date(2026, 6, 15))) == 1
    )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_and_sorted():
    book = ExposureBook()
    book.add_exposure(_record(exposure_id="exposure:beta"))
    book.add_exposure(_record(exposure_id="exposure:alpha"))
    book.add_exposure(_record(exposure_id="exposure:gamma"))
    a = book.snapshot()
    b = book.snapshot()
    assert a == b
    ids = [r["exposure_id"] for r in a["exposures"]]
    assert ids == sorted(ids)
    assert a["exposure_count"] == 3


def test_snapshot_round_trips_record_fields():
    book = ExposureBook()
    book.add_exposure(_record())
    snap = book.snapshot()
    assert snap["exposure_count"] == 1
    rec = snap["exposures"][0]
    assert rec["exposure_id"] == "exposure:firm_a:packaging:cost"
    assert rec["magnitude"] == 0.45


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    assert RecordType.EXPOSURE_ADDED.value == "exposure_added"


def test_add_exposure_writes_ledger_record_when_present():
    ledger = Ledger()
    clock = Clock(current_date=date(2026, 3, 31))
    book = ExposureBook(ledger=ledger, clock=clock)
    r = _record()
    book.add_exposure(r)
    records = ledger.filter(event_type="exposure_added")
    assert len(records) == 1
    rec = records[0]
    assert rec.object_id == r.exposure_id
    assert rec.source == r.subject_id
    assert rec.target == r.variable_id
    assert rec.payload["direction"] == "positive"
    assert rec.payload["magnitude"] == 0.45


def test_add_exposure_without_ledger_does_not_raise():
    book = ExposureBook()
    book.add_exposure(_record())


# ---------------------------------------------------------------------------
# Kernel wiring + no-mutation guarantee
# ---------------------------------------------------------------------------


def test_kernel_exposes_exposures_book():
    kernel = _kernel()
    assert isinstance(kernel.exposures, ExposureBook)
    assert kernel.exposures.ledger is kernel.ledger
    assert kernel.exposures.clock is kernel.clock


def test_kernel_add_exposure_emits_to_kernel_ledger():
    kernel = _kernel()
    kernel.exposures.add_exposure(_record())
    records = kernel.ledger.filter(event_type="exposure_added")
    assert len(records) == 1


def test_exposure_book_does_not_mutate_other_kernel_books():
    """
    Adding exposures and exercising every read API must not mutate
    any other v0/v1 source-of-truth book.
    """
    kernel = _kernel()

    # Seed unrelated books with one entry each so snapshot equality
    # is meaningful.
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-03-31", "exchange")

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
        "routines": kernel.routines.snapshot(),
        "attention": kernel.attention.snapshot(),
        "variables": kernel.variables.snapshot(),
    }

    _seed_typical_exposures(kernel.exposures)

    kernel.exposures.list_exposures()
    kernel.exposures.list_by_subject("firm:reference_food_processor_a")
    kernel.exposures.list_by_subject_type("firm")
    kernel.exposures.list_by_variable("variable:policy_rate")
    kernel.exposures.list_by_exposure_type("input_cost")
    kernel.exposures.list_by_metric("packaging_margin_pressure")
    kernel.exposures.list_by_direction("positive")
    kernel.exposures.list_active_as_of("2026-06-01")
    kernel.exposures.snapshot()

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
    assert kernel.routines.snapshot() == snaps_before["routines"]
    assert kernel.attention.snapshot() == snaps_before["attention"]
    assert kernel.variables.snapshot() == snaps_before["variables"]


def test_kernel_tick_does_not_auto_create_exposures():
    """tick() / run() must not write exposures on their own — there
    is no scheduler integration in v1.8.10."""
    kernel = _kernel()
    kernel.exposures.add_exposure(_record())
    snap_before = kernel.exposures.snapshot()
    kernel.tick()
    kernel.run(days=3)
    assert kernel.exposures.snapshot() == snap_before
