"""
Tests for v1.8.9 WorldVariableBook.

Covers `ReferenceVariableSpec` and `VariableObservation` field
validation, the book's CRUD + filter listings, the visibility
semantics that prevent look-ahead bias, the deterministic
``latest_observation`` tiebreaker, ledger emission of the two new
RecordType members, snapshot determinism, kernel wiring, and the
no-mutation guarantee against every other v0/v1 source-of-truth
book.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State
from world.variables import (
    DuplicateVariableError,
    DuplicateVariableObservationError,
    ReferenceVariableSpec,
    UnknownVariableError,
    UnknownVariableObservationError,
    VariableObservation,
    WorldVariableBook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    *,
    variable_id: str = "variable:cpi_yoy",
    variable_name: str = "CPI Year-over-Year",
    variable_group: str = "inflation",
    variable_type: str = "rate",
    source_space_id: str = "external",
    source_id: str | None = None,
    canonical_unit: str = "percent",
    frequency: str = "QUARTERLY",
    observation_kind: str = "released",
    default_visibility: str = "public",
    observability_scope: str = "global",
    related_space_ids: tuple[str, ...] = ("corporate", "banking"),
    related_subject_ids: tuple[str, ...] = (),
    related_sector_ids: tuple[str, ...] = (),
    related_asset_class_ids: tuple[str, ...] = (),
    typical_consumer_space_ids: tuple[str, ...] = ("investors", "banking"),
    expected_release_lag_days: int | None = 30,
    metadata: dict | None = None,
) -> ReferenceVariableSpec:
    return ReferenceVariableSpec(
        variable_id=variable_id,
        variable_name=variable_name,
        variable_group=variable_group,
        variable_type=variable_type,
        source_space_id=source_space_id,
        source_id=source_id,
        canonical_unit=canonical_unit,
        frequency=frequency,
        observation_kind=observation_kind,
        default_visibility=default_visibility,
        observability_scope=observability_scope,
        related_space_ids=related_space_ids,
        related_subject_ids=related_subject_ids,
        related_sector_ids=related_sector_ids,
        related_asset_class_ids=related_asset_class_ids,
        typical_consumer_space_ids=typical_consumer_space_ids,
        expected_release_lag_days=expected_release_lag_days,
        metadata=metadata or {},
    )


def _obs(
    *,
    observation_id: str = "obs:cpi_yoy:2026Q1_initial",
    variable_id: str = "variable:cpi_yoy",
    as_of_date: str = "2026-04-15",
    value=2.3,
    unit: str = "percent",
    observation_period_start: str | None = "2026-01-01",
    observation_period_end: str | None = "2026-03-31",
    release_date: str | None = None,
    visible_from_date: str | None = None,
    vintage_id: str | None = "2026Q1_initial",
    revision_of: str | None = None,
    observed_by_space_id: str | None = "information",
    published_by_source_id: str | None = "source:reference_macro_publisher",
    carried_by_interaction_id: str | None = None,
    confidence: float = 1.0,
    metadata: dict | None = None,
) -> VariableObservation:
    return VariableObservation(
        observation_id=observation_id,
        variable_id=variable_id,
        as_of_date=as_of_date,
        value=value,
        unit=unit,
        observation_period_start=observation_period_start,
        observation_period_end=observation_period_end,
        release_date=release_date,
        visible_from_date=visible_from_date,
        vintage_id=vintage_id,
        revision_of=revision_of,
        observed_by_space_id=observed_by_space_id,
        published_by_source_id=published_by_source_id,
        carried_by_interaction_id=carried_by_interaction_id,
        confidence=confidence,
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
# ReferenceVariableSpec validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"variable_id": ""},
        {"variable_name": ""},
        {"variable_group": ""},
        {"variable_type": ""},
        {"source_space_id": ""},
        {"canonical_unit": ""},
        {"frequency": ""},
        {"observation_kind": ""},
        {"default_visibility": ""},
        {"observability_scope": ""},
        {"source_id": ""},
    ],
)
def test_spec_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _spec(**kwargs)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "related_space_ids",
        "related_subject_ids",
        "related_sector_ids",
        "related_asset_class_ids",
        "typical_consumer_space_ids",
    ],
)
def test_spec_rejects_empty_strings_in_tuple_fields(tuple_field):
    with pytest.raises(ValueError):
        _spec(**{tuple_field: ("valid", "")})


def test_spec_normalizes_tuples_deterministically():
    spec = _spec(
        related_space_ids=["corporate", "banking", "real_estate"],
    )
    assert isinstance(spec.related_space_ids, tuple)
    assert spec.related_space_ids == ("corporate", "banking", "real_estate")


def test_spec_expected_release_lag_days_accepts_int_or_none():
    _spec(expected_release_lag_days=30)
    _spec(expected_release_lag_days=0)
    _spec(expected_release_lag_days=None)


def test_spec_expected_release_lag_days_rejects_non_int():
    with pytest.raises(ValueError):
        _spec(expected_release_lag_days="30")  # type: ignore[arg-type]


def test_spec_expected_release_lag_days_rejects_bool():
    """bool is a subclass of int; should not slip through."""
    with pytest.raises(ValueError):
        _spec(expected_release_lag_days=True)  # type: ignore[arg-type]


def test_spec_is_frozen():
    spec = _spec()
    with pytest.raises(Exception):
        spec.variable_id = "tampered"  # type: ignore[misc]


def test_spec_to_dict_round_trips_fields():
    spec = _spec(
        related_space_ids=("corporate",),
        typical_consumer_space_ids=("investors",),
    )
    d = spec.to_dict()
    assert d["variable_id"] == spec.variable_id
    assert d["related_space_ids"] == ["corporate"]
    assert d["typical_consumer_space_ids"] == ["investors"]


# ---------------------------------------------------------------------------
# VariableObservation validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"observation_id": ""},
        {"variable_id": ""},
        {"as_of_date": ""},
        {"unit": ""},
        {"observation_period_start": ""},
        {"observation_period_end": ""},
        {"release_date": ""},
        {"visible_from_date": ""},
        {"vintage_id": ""},
        {"revision_of": ""},
        {"observed_by_space_id": ""},
        {"published_by_source_id": ""},
        {"carried_by_interaction_id": ""},
    ],
)
def test_observation_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _obs(**kwargs)


def test_observation_coerces_date_to_iso_string():
    o = _obs(as_of_date=date(2026, 4, 15))
    assert o.as_of_date == "2026-04-15"


def test_observation_coerces_optional_dates_to_iso_strings():
    o = _obs(
        observation_period_start=date(2026, 1, 1),
        observation_period_end=date(2026, 3, 31),
        release_date=date(2026, 4, 15),
        visible_from_date=date(2026, 4, 16),
    )
    assert o.observation_period_start == "2026-01-01"
    assert o.observation_period_end == "2026-03-31"
    assert o.release_date == "2026-04-15"
    assert o.visible_from_date == "2026-04-16"


def test_observation_accepts_numeric_value_int_and_float():
    _obs(value=42)
    _obs(value=3.14)


def test_observation_accepts_string_value():
    _obs(value="qualitative_high")


def test_observation_accepts_none_value():
    _obs(value=None)


@pytest.mark.parametrize("conf", [-0.1, 1.1, 2.0, -1.0])
def test_observation_rejects_confidence_out_of_bounds(conf):
    with pytest.raises(ValueError):
        _obs(confidence=conf)


def test_observation_confidence_bounds_inclusive():
    _obs(confidence=0.0)
    _obs(confidence=1.0)


def test_observation_rejects_non_numeric_confidence():
    with pytest.raises(ValueError):
        _obs(confidence="high")  # type: ignore[arg-type]


def test_observation_rejects_bool_confidence():
    """bool is a subclass of int; should not slip through."""
    with pytest.raises(ValueError):
        _obs(confidence=True)  # type: ignore[arg-type]


def test_observation_visibility_date_uses_visible_from_date_when_present():
    o = _obs(visible_from_date="2026-04-16")
    assert o.visibility_date == "2026-04-16"


def test_observation_visibility_date_falls_back_to_as_of_date():
    o = _obs(visible_from_date=None)
    assert o.visibility_date == o.as_of_date == "2026-04-15"


def test_observation_is_frozen():
    o = _obs()
    with pytest.raises(Exception):
        o.observation_id = "tampered"  # type: ignore[misc]


def test_observation_to_dict_round_trips_fields():
    o = _obs(vintage_id="2026Q1_initial", revision_of=None)
    d = o.to_dict()
    assert d["observation_id"] == o.observation_id
    assert d["variable_id"] == o.variable_id
    assert d["vintage_id"] == "2026Q1_initial"
    assert d["revision_of"] is None


# ---------------------------------------------------------------------------
# Variable CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_variable():
    book = WorldVariableBook()
    spec = _spec()
    book.add_variable(spec)
    assert book.get_variable(spec.variable_id) is spec


def test_get_variable_unknown_raises():
    book = WorldVariableBook()
    with pytest.raises(UnknownVariableError):
        book.get_variable("variable:does_not_exist")


def test_duplicate_variable_id_rejected():
    book = WorldVariableBook()
    book.add_variable(_spec())
    with pytest.raises(DuplicateVariableError):
        book.add_variable(_spec())


# ---------------------------------------------------------------------------
# Variable filter listings
# ---------------------------------------------------------------------------


def _seed_typical_variables(book: WorldVariableBook) -> None:
    book.add_variable(_spec())  # variable:cpi_yoy, inflation, source=external
    book.add_variable(
        _spec(
            variable_id="variable:gdp_growth",
            variable_name="GDP Growth",
            variable_group="real_activity",
            variable_type="rate",
            source_space_id="external",
            related_space_ids=("corporate",),
            typical_consumer_space_ids=("investors",),
        )
    )
    book.add_variable(
        _spec(
            variable_id="variable:policy_rate",
            variable_name="Policy Rate",
            variable_group="rates",
            variable_type="rate",
            source_space_id="policy",
            related_space_ids=("banking", "investors"),
            typical_consumer_space_ids=("banking", "investors"),
            observation_kind="continuous",
        )
    )
    book.add_variable(
        _spec(
            variable_id="variable:oil_price_reference",
            variable_name="Reference Oil Price",
            variable_group="material",
            variable_type="level",
            source_space_id="external",
            related_space_ids=("corporate",),
            typical_consumer_space_ids=("corporate", "information"),
        )
    )


def test_list_variables_by_group():
    book = WorldVariableBook()
    _seed_typical_variables(book)
    inflation = book.list_variables_by_group("inflation")
    assert {s.variable_id for s in inflation} == {"variable:cpi_yoy"}
    rates = book.list_variables_by_group("rates")
    assert {s.variable_id for s in rates} == {"variable:policy_rate"}
    assert book.list_variables_by_group("nonexistent_group") == ()


def test_list_variables_by_source_space():
    book = WorldVariableBook()
    _seed_typical_variables(book)
    external = book.list_variables_by_source_space("external")
    assert {s.variable_id for s in external} == {
        "variable:cpi_yoy",
        "variable:gdp_growth",
        "variable:oil_price_reference",
    }
    policy = book.list_variables_by_source_space("policy")
    assert {s.variable_id for s in policy} == {"variable:policy_rate"}


def test_list_variables_by_related_space():
    book = WorldVariableBook()
    _seed_typical_variables(book)
    banking = book.list_variables_by_related_space("banking")
    assert {s.variable_id for s in banking} == {
        "variable:cpi_yoy",
        "variable:policy_rate",
    }
    real_estate = book.list_variables_by_related_space("real_estate")
    assert real_estate == ()


def test_list_variables_by_consumer_space():
    book = WorldVariableBook()
    _seed_typical_variables(book)
    investors = book.list_variables_by_consumer_space("investors")
    assert {s.variable_id for s in investors} == {
        "variable:cpi_yoy",
        "variable:gdp_growth",
        "variable:policy_rate",
    }
    corporate = book.list_variables_by_consumer_space("corporate")
    assert {s.variable_id for s in corporate} == {
        "variable:oil_price_reference",
    }


# ---------------------------------------------------------------------------
# Observation CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_observation():
    book = WorldVariableBook()
    obs = _obs()
    book.add_observation(obs)
    assert book.get_observation(obs.observation_id) is obs


def test_get_observation_unknown_raises():
    book = WorldVariableBook()
    with pytest.raises(UnknownVariableObservationError):
        book.get_observation("obs:does_not_exist")


def test_duplicate_observation_id_rejected():
    book = WorldVariableBook()
    book.add_observation(_obs())
    with pytest.raises(DuplicateVariableObservationError):
        book.add_observation(_obs())


def test_observation_does_not_require_variable_to_be_registered():
    """Cross-reference rule: variable_id is data, not validated."""
    book = WorldVariableBook()
    book.add_observation(_obs(variable_id="variable:floating_id"))


# ---------------------------------------------------------------------------
# Observation filter listings
# ---------------------------------------------------------------------------


def _seed_typical_observations(book: WorldVariableBook) -> None:
    book.add_variable(_spec())
    book.add_observation(
        _obs(
            observation_id="obs:cpi:2026Q1_initial",
            as_of_date="2026-04-15",
            vintage_id="2026Q1_initial",
            value=2.3,
        )
    )
    book.add_observation(
        _obs(
            observation_id="obs:cpi:2026Q1_revision",
            as_of_date="2026-05-20",
            vintage_id="2026Q1_revision",
            revision_of="obs:cpi:2026Q1_initial",
            value=2.4,
        )
    )
    book.add_observation(
        _obs(
            observation_id="obs:cpi:2026Q2_initial",
            as_of_date="2026-07-15",
            observation_period_start="2026-04-01",
            observation_period_end="2026-06-30",
            vintage_id="2026Q2_initial",
            value=2.5,
        )
    )


def test_list_observations_no_filter_returns_all():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    assert len(book.list_observations()) == 3


def test_list_observations_by_variable():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    cpi = book.list_observations_by_variable("variable:cpi_yoy")
    assert len(cpi) == 3
    assert book.list_observations_by_variable("variable:unknown") == ()


def test_list_observations_function_with_variable_id_arg():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    via_arg = book.list_observations("variable:cpi_yoy")
    via_method = book.list_observations_by_variable("variable:cpi_yoy")
    assert via_arg == via_method


def test_list_observations_by_as_of_date():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    on_initial = book.list_observations_by_as_of_date("2026-04-15")
    assert {o.observation_id for o in on_initial} == {
        "obs:cpi:2026Q1_initial"
    }
    assert book.list_observations_by_as_of_date("2099-01-01") == ()


def test_list_observations_by_as_of_date_accepts_date_object():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    on_initial = book.list_observations_by_as_of_date(date(2026, 4, 15))
    assert {o.observation_id for o in on_initial} == {
        "obs:cpi:2026Q1_initial"
    }


# ---------------------------------------------------------------------------
# Visibility filtering — the v1.8.8 hardening's gate-1
# ---------------------------------------------------------------------------


def test_visible_observations_filter_by_visibility_date():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    # Only the initial release is visible by 2026-04-30.
    visible = book.list_observations_visible_as_of("2026-04-30")
    assert {o.observation_id for o in visible} == {"obs:cpi:2026Q1_initial"}


def test_visible_observations_includes_all_when_far_future():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    visible = book.list_observations_visible_as_of("2099-01-01")
    assert len(visible) == 3


def test_visible_observations_empty_when_before_any_release():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    assert book.list_observations_visible_as_of("2025-12-31") == ()


def test_visible_from_date_overrides_as_of_date_for_visibility():
    """
    visible_from_date wins over as_of_date when present. An
    observation with as_of_date=2026-04-15 and
    visible_from_date=2026-05-01 is NOT visible on 2026-04-30
    even though as_of_date is past.
    """
    book = WorldVariableBook()
    book.add_variable(_spec())
    book.add_observation(
        _obs(
            observation_id="obs:embargoed",
            as_of_date="2026-04-15",
            visible_from_date="2026-05-01",
        )
    )
    assert book.list_observations_visible_as_of("2026-04-30") == ()
    assert len(book.list_observations_visible_as_of("2026-05-01")) == 1


def test_visible_from_date_can_make_observation_visible_earlier():
    """
    visible_from_date wins both directions: an observation with
    as_of_date=2026-04-15 and visible_from_date=2026-04-01 is
    visible on 2026-04-10 because the operational visibility date
    is the earlier one.
    """
    book = WorldVariableBook()
    book.add_variable(_spec())
    book.add_observation(
        _obs(
            observation_id="obs:early_visible",
            as_of_date="2026-04-15",
            visible_from_date="2026-04-01",
        )
    )
    visible = book.list_observations_visible_as_of("2026-04-10")
    assert {o.observation_id for o in visible} == {"obs:early_visible"}


# ---------------------------------------------------------------------------
# latest_observation
# ---------------------------------------------------------------------------


def test_latest_observation_no_date_returns_overall_latest():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    latest = book.latest_observation("variable:cpi_yoy")
    assert latest is not None
    assert latest.observation_id == "obs:cpi:2026Q2_initial"


def test_latest_observation_respects_as_of_date():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    latest = book.latest_observation("variable:cpi_yoy", "2026-04-30")
    assert latest is not None
    assert latest.observation_id == "obs:cpi:2026Q1_initial"


def test_latest_observation_returns_revision_when_visible():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    latest = book.latest_observation("variable:cpi_yoy", "2026-06-01")
    assert latest is not None
    assert latest.observation_id == "obs:cpi:2026Q1_revision"


def test_latest_observation_returns_none_when_nothing_visible():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    assert book.latest_observation("variable:cpi_yoy", "2025-12-31") is None


def test_latest_observation_returns_none_for_unknown_variable():
    book = WorldVariableBook()
    assert book.latest_observation("variable:does_not_exist") is None


def test_latest_observation_deterministic_tiebreaker():
    """
    Same visibility_date, same as_of_date -> tiebreaker on
    observation_id (lexicographic descending).
    """
    book = WorldVariableBook()
    book.add_variable(_spec())
    book.add_observation(
        _obs(
            observation_id="obs:aaa",
            as_of_date="2026-04-15",
            value=1.0,
        )
    )
    book.add_observation(
        _obs(
            observation_id="obs:zzz",
            as_of_date="2026-04-15",
            value=2.0,
        )
    )
    book.add_observation(
        _obs(
            observation_id="obs:mmm",
            as_of_date="2026-04-15",
            value=3.0,
        )
    )
    latest = book.latest_observation("variable:cpi_yoy")
    assert latest is not None
    # zzz wins because lexicographic descending.
    assert latest.observation_id == "obs:zzz"


def test_latest_observation_is_repeatable():
    """Two calls return identical results from the same book state."""
    book = WorldVariableBook()
    _seed_typical_observations(book)
    a = book.latest_observation("variable:cpi_yoy", "2026-06-01")
    b = book.latest_observation("variable:cpi_yoy", "2026-06-01")
    assert a is b


# ---------------------------------------------------------------------------
# Channel filter
# ---------------------------------------------------------------------------


def test_list_observations_carried_by_interaction():
    book = WorldVariableBook()
    book.add_variable(_spec())
    book.add_observation(
        _obs(
            observation_id="obs:via_channel_a",
            carried_by_interaction_id="interaction:external.commodity_feed",
        )
    )
    book.add_observation(
        _obs(
            observation_id="obs:via_channel_b",
            as_of_date="2026-04-16",
            carried_by_interaction_id="interaction:external.commodity_feed",
        )
    )
    book.add_observation(
        _obs(
            observation_id="obs:no_channel",
            as_of_date="2026-04-17",
            carried_by_interaction_id=None,
        )
    )
    via = book.list_observations_carried_by_interaction(
        "interaction:external.commodity_feed"
    )
    assert {o.observation_id for o in via} == {
        "obs:via_channel_a",
        "obs:via_channel_b",
    }
    assert (
        book.list_observations_carried_by_interaction(
            "interaction:does_not_exist"
        )
        == ()
    )


# ---------------------------------------------------------------------------
# Vintage / revision storage
# ---------------------------------------------------------------------------


def test_vintage_and_revision_stored_and_retrievable():
    book = WorldVariableBook()
    _seed_typical_observations(book)
    initial = book.get_observation("obs:cpi:2026Q1_initial")
    revision = book.get_observation("obs:cpi:2026Q1_revision")
    assert initial.vintage_id == "2026Q1_initial"
    assert initial.revision_of is None
    assert revision.vintage_id == "2026Q1_revision"
    assert revision.revision_of == "obs:cpi:2026Q1_initial"


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_and_sorted():
    book = WorldVariableBook()
    _seed_typical_variables(book)
    book.add_observation(_obs(observation_id="obs:beta"))
    book.add_observation(_obs(observation_id="obs:alpha", as_of_date="2026-04-16"))
    snap_a = book.snapshot()
    snap_b = book.snapshot()
    assert snap_a == snap_b
    var_ids = [v["variable_id"] for v in snap_a["variables"]]
    obs_ids = [o["observation_id"] for o in snap_a["observations"]]
    assert var_ids == sorted(var_ids)
    assert obs_ids == sorted(obs_ids)


def test_snapshot_counts():
    book = WorldVariableBook()
    book.add_variable(_spec())
    book.add_observation(_obs())
    snap = book.snapshot()
    assert snap["variable_count"] == 1
    assert snap["observation_count"] == 1


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_types_exist():
    assert RecordType.VARIABLE_ADDED.value == "variable_added"
    assert (
        RecordType.VARIABLE_OBSERVATION_ADDED.value
        == "variable_observation_added"
    )


def test_add_variable_writes_ledger_record_when_present():
    ledger = Ledger()
    clock = Clock(current_date=date(2026, 3, 31))
    book = WorldVariableBook(ledger=ledger, clock=clock)
    book.add_variable(_spec())
    records = ledger.filter(event_type="variable_added")
    assert len(records) == 1
    rec = records[0]
    assert rec.object_id == "variable:cpi_yoy"
    assert rec.payload["variable_group"] == "inflation"
    assert rec.payload["source_space_id"] == "external"


def test_add_observation_writes_ledger_record_when_present():
    ledger = Ledger()
    clock = Clock(current_date=date(2026, 3, 31))
    book = WorldVariableBook(ledger=ledger, clock=clock)
    book.add_variable(_spec())
    obs = _obs(carried_by_interaction_id="interaction:external.feed")
    book.add_observation(obs)
    records = ledger.filter(event_type="variable_observation_added")
    assert len(records) == 1
    rec = records[0]
    assert rec.object_id == obs.observation_id
    assert rec.target == obs.variable_id
    # simulation_date is the observation's as_of_date.
    assert rec.simulation_date == obs.as_of_date
    # carried_by_interaction_id flows to ledger correlation_id.
    assert rec.correlation_id == "interaction:external.feed"


def test_add_methods_without_ledger_do_not_raise():
    book = WorldVariableBook()
    book.add_variable(_spec())
    book.add_observation(_obs())


# ---------------------------------------------------------------------------
# Kernel wiring + no-mutation
# ---------------------------------------------------------------------------


def test_kernel_exposes_variables_book():
    kernel = _kernel()
    assert isinstance(kernel.variables, WorldVariableBook)
    assert kernel.variables.ledger is kernel.ledger
    assert kernel.variables.clock is kernel.clock


def test_kernel_add_variable_emits_to_kernel_ledger():
    kernel = _kernel()
    kernel.variables.add_variable(_spec())
    records = kernel.ledger.filter(event_type="variable_added")
    assert len(records) == 1


def test_world_variable_book_does_not_mutate_other_books():
    """
    Adding variables, adding observations, exercising every read
    API, and building snapshots must not mutate any other v0/v1
    source-of-truth book.
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
    }

    _seed_typical_variables(kernel.variables)
    # Note: _seed_typical_variables already added variable:cpi_yoy, so
    # only seed observations directly (avoid the duplicate-variable
    # add inside _seed_typical_observations).
    kernel.variables.add_observation(
        _obs(observation_id="obs:cpi:initial", as_of_date="2026-04-15")
    )
    kernel.variables.add_observation(
        _obs(
            observation_id="obs:cpi:revision",
            as_of_date="2026-05-20",
            revision_of="obs:cpi:initial",
        )
    )

    kernel.variables.list_variables()
    kernel.variables.list_variables_by_group("inflation")
    kernel.variables.list_variables_by_source_space("external")
    kernel.variables.list_variables_by_related_space("banking")
    kernel.variables.list_variables_by_consumer_space("investors")
    kernel.variables.list_observations()
    kernel.variables.list_observations_by_variable("variable:cpi_yoy")
    kernel.variables.list_observations_by_as_of_date("2026-04-15")
    kernel.variables.list_observations_visible_as_of("2026-06-01")
    kernel.variables.list_observations_carried_by_interaction(
        "interaction:does_not_exist"
    )
    kernel.variables.latest_observation("variable:cpi_yoy", "2026-06-01")
    kernel.variables.snapshot()

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


def test_kernel_tick_does_not_auto_mutate_variables():
    """tick() and run() must not write variables or observations
    on their own — there is no scheduler integration in v1.8.9."""
    kernel = _kernel()
    kernel.variables.add_variable(_spec())
    snap_before = kernel.variables.snapshot()
    kernel.tick()
    kernel.run(days=3)
    assert kernel.variables.snapshot() == snap_before
