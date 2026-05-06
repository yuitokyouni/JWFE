"""
Tests for v1.19.3 ``InformationReleaseCalendar`` storage —
``world.information_release`` module.

Pinned invariants:

- closed-set vocabularies (``RELEASE_CADENCE_LABELS``,
  ``INDICATOR_FAMILY_LABELS``, ``RELEASE_IMPORTANCE_LABELS``,
  ``JURISDICTION_SCOPE_LABELS``, ``ARRIVAL_STATUS_LABELS``,
  ``REASONING_MODE_LABELS``, ``REASONING_SLOT_LABELS``,
  ``STATUS_LABELS``, ``VISIBILITY_LABELS``);
- v1.19.3 hard naming boundary
  (``FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES``) disjoint from
  every closed-set vocabulary; dataclass field names disjoint;
  payload keys disjoint at every depth (calendar / scheduled
  release / arrival, plus boundary_flags + metadata);
- frozen dataclasses with strict construction-time validation;
- ``scheduled_period_index`` rejects ``bool`` (which is a
  subclass of ``int``);
- duplicate id rejected; duplicate emits no extra ledger
  record;
- unknown id raises;
- every list / filter method returns the right subset;
- snapshot determinism;
- ledger emits exactly one record per ``add_*`` call (covers
  the three new ``RecordType`` values);
- kernel wiring (``WorldKernel.information_releases``);
- adding records does not mutate ``PriceBook`` or any other
  source-of-truth book;
- empty book does not move the default-fixture
  ``living_world_digest``;
- arrivals carry the v1.19.0 default boundary-flag set,
  ``reasoning_mode = "rule_based_fallback"``, and
  ``reasoning_slot = "future_llm_compatible"``;
- module-text scan for forbidden actor-decision tokens and
  Japan-real-data tokens;
- jurisdiction-neutral identifier scan over module + test
  text.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

from world.clock import Clock
from world.information_release import (
    ARRIVAL_STATUS_LABELS,
    DEFAULT_BOUNDARY_FLAGS,
    DEFAULT_REASONING_MODE,
    DEFAULT_REASONING_POLICY_ID,
    DEFAULT_REASONING_SLOT,
    DuplicateInformationArrivalError,
    DuplicateInformationReleaseCalendarError,
    DuplicateScheduledIndicatorReleaseError,
    FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES,
    INDICATOR_FAMILY_LABELS,
    InformationArrivalRecord,
    InformationReleaseBook,
    InformationReleaseCalendar,
    JURISDICTION_SCOPE_LABELS,
    REASONING_MODE_LABELS,
    REASONING_SLOT_LABELS,
    RELEASE_CADENCE_LABELS,
    RELEASE_IMPORTANCE_LABELS,
    STATUS_LABELS,
    ScheduledIndicatorRelease,
    UnknownInformationArrivalError,
    UnknownInformationReleaseCalendarError,
    UnknownScheduledIndicatorReleaseError,
    VISIBILITY_LABELS,
)
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State

from _canonical_digests import (
    QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
)


_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "world"
    / "information_release.py"
)


# ---------------------------------------------------------------------------
# Closed-set vocabularies
# ---------------------------------------------------------------------------


def test_release_cadence_labels_closed_set():
    assert RELEASE_CADENCE_LABELS == frozenset(
        {
            "monthly",
            "quarterly",
            "meeting_based",
            "weekly",
            "daily_operational",
            "ad_hoc",
            "display_only",
            "unknown",
        }
    )


def test_indicator_family_labels_closed_set():
    assert INDICATOR_FAMILY_LABELS == frozenset(
        {
            "central_bank_policy",
            "inflation",
            "labor_market",
            "production_supply",
            "consumption_demand",
            "capex_investment",
            "gdp_national_accounts",
            "market_liquidity",
            "fiscal_policy",
            "sector_specific",
            "information_gap",
            "unknown",
        }
    )


def test_release_importance_labels_closed_set():
    assert RELEASE_IMPORTANCE_LABELS == frozenset(
        {
            "routine",
            "high_attention",
            "regime_relevant",
            "stress_relevant",
            "unknown",
        }
    )


def test_jurisdiction_scope_labels_closed_set():
    assert JURISDICTION_SCOPE_LABELS == frozenset(
        {
            "jurisdiction_neutral",
            "generic_developed_market",
            "generic_emerging_market",
            "unknown",
        }
    )


def test_arrival_status_labels_closed_set():
    assert ARRIVAL_STATUS_LABELS == frozenset(
        {
            "arrived",
            "delayed",
            "missing",
            "not_scheduled",
            "unknown",
        }
    )


def test_reasoning_mode_labels_closed_set():
    assert REASONING_MODE_LABELS == frozenset(
        {
            "rule_based_fallback",
            "future_llm_compatible",
            "external_policy_slot",
            "unknown",
        }
    )


def test_reasoning_slot_labels_closed_set():
    assert REASONING_SLOT_LABELS == frozenset(
        {
            "future_llm_compatible",
            "rule_based_only",
            "not_applicable",
            "unknown",
        }
    )


def test_status_labels_closed_set():
    assert STATUS_LABELS == frozenset(
        {"draft", "active", "stale", "superseded", "archived", "unknown"}
    )


def test_visibility_labels_closed_set():
    assert VISIBILITY_LABELS == frozenset(
        {"internal_only", "shared_internal", "external_audit"}
    )


# ---------------------------------------------------------------------------
# Forbidden field-name boundary
# ---------------------------------------------------------------------------


def test_forbidden_field_names_includes_v1_18_0_pinned_set():
    pinned_v1_18_0 = {
        "firm_decision",
        "investor_action",
        "bank_approval",
        "trading_decision",
        "optimal_capital_structure",
        "buy",
        "sell",
        "order",
        "trade",
        "execution",
        "price",
        "market_price",
        "predicted_index",
        "forecast_path",
        "expected_return",
        "target_price",
        "recommendation",
        "investment_advice",
        "real_data_value",
        "japan_calibration",
        "llm_output",
        "llm_prose",
        "prompt_text",
    }
    assert pinned_v1_18_0 <= FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES


def test_forbidden_field_names_includes_v1_19_3_japan_real_data_tokens():
    pinned_v1_19_3 = {
        "real_indicator_value",
        "cpi_value",
        "gdp_value",
        "policy_rate",
        "real_release_date",
        "boj",
        "fomc",
        "ecb",
    }
    assert pinned_v1_19_3 <= FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES


def test_forbidden_field_names_disjoint_from_every_closed_set():
    for vocab in (
        RELEASE_CADENCE_LABELS,
        INDICATOR_FAMILY_LABELS,
        RELEASE_IMPORTANCE_LABELS,
        JURISDICTION_SCOPE_LABELS,
        ARRIVAL_STATUS_LABELS,
        REASONING_MODE_LABELS,
        REASONING_SLOT_LABELS,
        STATUS_LABELS,
        VISIBILITY_LABELS,
    ):
        assert not (FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES & vocab)


def test_dataclass_field_names_disjoint_from_forbidden():
    for cls in (
        InformationReleaseCalendar,
        ScheduledIndicatorRelease,
        InformationArrivalRecord,
    ):
        fields = set(cls.__dataclass_fields__.keys())
        assert not (fields & FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES), (
            f"{cls.__name__} field names overlap with forbidden set"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _calendar(
    *,
    calendar_id: str = "calendar:reference_monthly_synthetic",
    calendar_label: str = "Reference monthly synthetic calendar",
    jurisdiction_scope_label: str = "jurisdiction_neutral",
    release_cadence_labels: tuple[str, ...] = (
        "monthly",
        "quarterly",
        "meeting_based",
    ),
    indicator_family_labels: tuple[str, ...] = (
        "inflation",
        "labor_market",
    ),
    status: str = "active",
    visibility: str = "internal_only",
    metadata: dict | None = None,
) -> InformationReleaseCalendar:
    return InformationReleaseCalendar(
        calendar_id=calendar_id,
        calendar_label=calendar_label,
        jurisdiction_scope_label=jurisdiction_scope_label,
        release_cadence_labels=release_cadence_labels,
        indicator_family_labels=indicator_family_labels,
        status=status,
        visibility=visibility,
        metadata=metadata or {},
    )


def _scheduled(
    *,
    scheduled_release_id: str = (
        "scheduled_release:calendar:reference_monthly_synthetic:"
        "inflation:period_01"
    ),
    calendar_id: str = "calendar:reference_monthly_synthetic",
    indicator_family_label: str = "inflation",
    release_cadence_label: str = "monthly",
    release_importance_label: str = "regime_relevant",
    scheduled_month_label: str = "period_01",
    scheduled_period_index: int = 0,
    expected_attention_surface_labels: tuple[str, ...] = (
        "market_environment",
    ),
    status: str = "active",
    visibility: str = "internal_only",
    metadata: dict | None = None,
) -> ScheduledIndicatorRelease:
    return ScheduledIndicatorRelease(
        scheduled_release_id=scheduled_release_id,
        calendar_id=calendar_id,
        indicator_family_label=indicator_family_label,
        release_cadence_label=release_cadence_label,
        release_importance_label=release_importance_label,
        scheduled_month_label=scheduled_month_label,
        scheduled_period_index=scheduled_period_index,
        expected_attention_surface_labels=(
            expected_attention_surface_labels
        ),
        status=status,
        visibility=visibility,
        metadata=metadata or {},
    )


def _arrival(
    *,
    information_arrival_id: str = "arrival:test:1:2026-01-31",
    calendar_id: str = "calendar:reference_monthly_synthetic",
    scheduled_release_id: str = (
        "scheduled_release:calendar:reference_monthly_synthetic:"
        "inflation:period_01"
    ),
    as_of_date: str = "2026-01-31",
    indicator_family_label: str = "inflation",
    release_cadence_label: str = "monthly",
    release_importance_label: str = "regime_relevant",
    arrival_status_label: str = "arrived",
    affected_context_surface_labels: tuple[str, ...] = (
        "market_environment",
    ),
    expected_attention_surface_labels: tuple[str, ...] = (
        "market_environment",
    ),
    reasoning_mode: str | None = None,
    reasoning_slot: str | None = None,
    boundary_flags: dict | None = None,
    status: str = "active",
    visibility: str = "internal_only",
    metadata: dict | None = None,
) -> InformationArrivalRecord:
    kwargs = dict(
        information_arrival_id=information_arrival_id,
        calendar_id=calendar_id,
        scheduled_release_id=scheduled_release_id,
        as_of_date=as_of_date,
        indicator_family_label=indicator_family_label,
        release_cadence_label=release_cadence_label,
        release_importance_label=release_importance_label,
        arrival_status_label=arrival_status_label,
        affected_context_surface_labels=affected_context_surface_labels,
        expected_attention_surface_labels=expected_attention_surface_labels,
        status=status,
        visibility=visibility,
        metadata=metadata or {},
    )
    if reasoning_mode is not None:
        kwargs["reasoning_mode"] = reasoning_mode
    if reasoning_slot is not None:
        kwargs["reasoning_slot"] = reasoning_slot
    if boundary_flags is not None:
        kwargs["boundary_flags"] = boundary_flags
    return InformationArrivalRecord(**kwargs)


def _bare_kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# Calendar field validation
# ---------------------------------------------------------------------------


def test_calendar_accepts_minimal_required_fields():
    c = _calendar()
    assert c.calendar_id == "calendar:reference_monthly_synthetic"
    assert c.jurisdiction_scope_label == "jurisdiction_neutral"
    assert c.status == "active"
    assert c.visibility == "internal_only"


def test_calendar_rejects_empty_calendar_id():
    with pytest.raises(ValueError):
        _calendar(calendar_id="")


def test_calendar_rejects_unknown_jurisdiction_scope_label():
    with pytest.raises(ValueError):
        _calendar(jurisdiction_scope_label="custom_jurisdiction")


def test_calendar_rejects_unknown_cadence_in_labels_tuple():
    with pytest.raises(ValueError):
        _calendar(release_cadence_labels=("monthly", "rogue_cadence"))


def test_calendar_rejects_unknown_indicator_family_in_labels_tuple():
    with pytest.raises(ValueError):
        _calendar(indicator_family_labels=("inflation", "rogue_family"))


def test_calendar_rejects_unknown_status():
    with pytest.raises(ValueError):
        _calendar(status="committed")


def test_calendar_rejects_unknown_visibility():
    with pytest.raises(ValueError):
        _calendar(visibility="public_marketing")


def test_calendar_rejects_metadata_with_forbidden_key():
    with pytest.raises(ValueError):
        _calendar(metadata={"price": 1.0})


def test_calendar_rejects_metadata_with_japan_real_data_key():
    with pytest.raises(ValueError):
        _calendar(metadata={"cpi_value": 1.0})


def test_calendar_rejects_non_mapping_metadata():
    with pytest.raises(TypeError):
        _calendar(metadata=["not a mapping"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ScheduledIndicatorRelease field validation
# ---------------------------------------------------------------------------


def test_scheduled_release_accepts_minimal_required_fields():
    r = _scheduled()
    assert r.scheduled_period_index == 0
    assert r.release_importance_label == "regime_relevant"


def test_scheduled_release_rejects_empty_scheduled_release_id():
    with pytest.raises(ValueError):
        _scheduled(scheduled_release_id="")


def test_scheduled_release_rejects_unknown_indicator_family_label():
    with pytest.raises(ValueError):
        _scheduled(indicator_family_label="rogue_family")


def test_scheduled_release_rejects_unknown_cadence_label():
    with pytest.raises(ValueError):
        _scheduled(release_cadence_label="continuous")


def test_scheduled_release_rejects_unknown_importance_label():
    with pytest.raises(ValueError):
        _scheduled(release_importance_label="critical")


def test_scheduled_release_rejects_negative_period_index():
    with pytest.raises(ValueError):
        _scheduled(scheduled_period_index=-1)


def test_scheduled_release_rejects_bool_period_index():
    """``bool`` is a subclass of ``int`` in Python; the dataclass
    must reject it explicitly to keep the audit shape honest."""
    with pytest.raises(TypeError):
        _scheduled(scheduled_period_index=True)  # type: ignore[arg-type]


def test_scheduled_release_rejects_non_int_period_index():
    with pytest.raises(TypeError):
        _scheduled(scheduled_period_index="0")  # type: ignore[arg-type]


def test_scheduled_release_rejects_empty_attention_surface_label():
    with pytest.raises(ValueError):
        _scheduled(
            expected_attention_surface_labels=("market_environment", "")
        )


def test_scheduled_release_rejects_metadata_with_forbidden_key():
    with pytest.raises(ValueError):
        _scheduled(metadata={"target_price": 1.0})


def test_scheduled_release_rejects_metadata_with_real_release_date_key():
    with pytest.raises(ValueError):
        _scheduled(metadata={"real_release_date": "2026-01-31"})


# ---------------------------------------------------------------------------
# InformationArrivalRecord field validation
# ---------------------------------------------------------------------------


def test_arrival_accepts_minimal_required_fields():
    a = _arrival()
    assert a.arrival_status_label == "arrived"
    assert a.reasoning_mode == "rule_based_fallback"
    assert a.reasoning_slot == "future_llm_compatible"
    assert a.reasoning_policy_id == DEFAULT_REASONING_POLICY_ID


def test_arrival_default_boundary_flags_are_v1_19_0_set():
    a = _arrival()
    assert dict(a.boundary_flags) == dict(DEFAULT_BOUNDARY_FLAGS)
    assert a.boundary_flags["synthetic_only"] is True
    assert a.boundary_flags["no_price_formation"] is True
    assert a.boundary_flags["no_trading"] is True
    assert a.boundary_flags["no_investment_advice"] is True
    assert a.boundary_flags["no_real_data"] is True
    assert a.boundary_flags["no_japan_calibration"] is True
    assert a.boundary_flags["no_llm_execution"] is True
    assert a.boundary_flags["display_or_export_only"] is True


def test_arrival_rejects_empty_information_arrival_id():
    with pytest.raises(ValueError):
        _arrival(information_arrival_id="")


def test_arrival_rejects_unknown_arrival_status_label():
    with pytest.raises(ValueError):
        _arrival(arrival_status_label="processing")


def test_arrival_rejects_unknown_reasoning_mode():
    with pytest.raises(ValueError):
        _arrival(reasoning_mode="learned_model_v3")


def test_arrival_rejects_unknown_reasoning_slot():
    with pytest.raises(ValueError):
        _arrival(reasoning_slot="custom_slot")


def test_arrival_rejects_metadata_with_forbidden_key():
    with pytest.raises(ValueError):
        _arrival(metadata={"target_price": 1.0})


def test_arrival_rejects_boundary_flags_with_forbidden_key():
    flags = dict(DEFAULT_BOUNDARY_FLAGS)
    flags["price"] = True
    with pytest.raises(ValueError):
        _arrival(boundary_flags=flags)


def test_arrival_rejects_non_bool_boundary_flag_value():
    flags = dict(DEFAULT_BOUNDARY_FLAGS)
    flags["custom"] = "yes"  # not a bool
    with pytest.raises(ValueError):
        _arrival(boundary_flags=flags)


def test_arrival_rejects_non_mapping_boundary_flags():
    with pytest.raises(TypeError):
        _arrival(boundary_flags=["not", "a", "mapping"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Default reasoning_mode / reasoning_slot
# ---------------------------------------------------------------------------


def test_default_reasoning_mode_is_rule_based_fallback():
    """v1.19.3 binding default; pinned by the module-level
    constant and reflected in every freshly-constructed
    arrival record."""
    assert DEFAULT_REASONING_MODE == "rule_based_fallback"
    assert DEFAULT_REASONING_SLOT == "future_llm_compatible"
    a = _arrival()
    assert a.reasoning_mode == "rule_based_fallback"
    assert a.reasoning_slot == "future_llm_compatible"


# ---------------------------------------------------------------------------
# Immutability + to_dict round-trip
# ---------------------------------------------------------------------------


def test_calendar_record_is_immutable():
    c = _calendar()
    with pytest.raises(Exception):
        c.calendar_id = "other"  # type: ignore[misc]


def test_scheduled_release_record_is_immutable():
    r = _scheduled()
    with pytest.raises(Exception):
        r.scheduled_release_id = "other"  # type: ignore[misc]


def test_arrival_record_is_immutable():
    a = _arrival()
    with pytest.raises(Exception):
        a.information_arrival_id = "other"  # type: ignore[misc]


def test_calendar_to_dict_round_trip_byte_identical():
    a = _calendar()
    b = _calendar()
    assert a.to_dict() == b.to_dict()


def test_scheduled_release_to_dict_round_trip_byte_identical():
    a = _scheduled()
    b = _scheduled()
    assert a.to_dict() == b.to_dict()


def test_arrival_to_dict_round_trip_byte_identical():
    a = _arrival()
    b = _arrival()
    assert a.to_dict() == b.to_dict()


def test_to_dict_keys_disjoint_from_forbidden():
    for record, label in (
        (_calendar(), "calendar"),
        (_scheduled(), "scheduled"),
        (_arrival(), "arrival"),
    ):
        payload = record.to_dict()
        assert not (
            set(payload.keys()) & FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES
        ), f"{label} payload keys overlap forbidden set"
        metadata_keys = set(payload["metadata"].keys())
        assert not (
            metadata_keys & FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES
        ), f"{label} metadata keys overlap forbidden set"


def test_arrival_to_dict_boundary_flag_keys_disjoint_from_forbidden():
    payload = _arrival().to_dict()
    bf_keys = set(payload["boundary_flags"].keys())
    assert not (bf_keys & FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES)


# ---------------------------------------------------------------------------
# InformationReleaseBook — add / get / list / duplicate / unknown
# ---------------------------------------------------------------------------


def test_book_add_get_list_calendar():
    book = InformationReleaseBook()
    c = _calendar()
    book.add_calendar(c)
    assert book.get_calendar(c.calendar_id) is c
    assert book.list_calendars() == (c,)


def test_book_add_get_list_scheduled_release():
    book = InformationReleaseBook()
    book.add_calendar(_calendar())
    r = _scheduled()
    book.add_scheduled_release(r)
    assert book.get_scheduled_release(r.scheduled_release_id) is r
    assert book.list_scheduled_releases() == (r,)


def test_book_add_get_list_arrival():
    book = InformationReleaseBook()
    book.add_calendar(_calendar())
    book.add_scheduled_release(_scheduled())
    a = _arrival()
    book.add_arrival(a)
    assert book.get_arrival(a.information_arrival_id) is a
    assert book.list_arrivals() == (a,)


def test_book_duplicate_calendar_id_raises():
    book = InformationReleaseBook()
    book.add_calendar(_calendar())
    with pytest.raises(DuplicateInformationReleaseCalendarError):
        book.add_calendar(_calendar())


def test_book_duplicate_scheduled_release_id_raises():
    book = InformationReleaseBook()
    book.add_scheduled_release(_scheduled())
    with pytest.raises(DuplicateScheduledIndicatorReleaseError):
        book.add_scheduled_release(_scheduled())


def test_book_duplicate_arrival_id_raises():
    book = InformationReleaseBook()
    book.add_arrival(_arrival())
    with pytest.raises(DuplicateInformationArrivalError):
        book.add_arrival(_arrival())


def test_book_unknown_calendar_id_raises():
    book = InformationReleaseBook()
    with pytest.raises(UnknownInformationReleaseCalendarError):
        book.get_calendar("missing")


def test_book_unknown_scheduled_release_id_raises():
    book = InformationReleaseBook()
    with pytest.raises(UnknownScheduledIndicatorReleaseError):
        book.get_scheduled_release("missing")


def test_book_unknown_arrival_id_raises():
    book = InformationReleaseBook()
    with pytest.raises(UnknownInformationArrivalError):
        book.get_arrival("missing")


def test_book_list_releases_by_calendar():
    book = InformationReleaseBook()
    a = _scheduled(
        scheduled_release_id="scheduled_release:cal_a:1",
        calendar_id="cal_a",
    )
    b = _scheduled(
        scheduled_release_id="scheduled_release:cal_b:1",
        calendar_id="cal_b",
    )
    book.add_scheduled_release(a)
    book.add_scheduled_release(b)
    assert book.list_releases_by_calendar("cal_a") == (a,)
    assert book.list_releases_by_calendar("cal_b") == (b,)
    assert book.list_releases_by_calendar("missing") == ()


def test_book_list_releases_by_indicator_family():
    book = InformationReleaseBook()
    a = _scheduled(
        scheduled_release_id="scheduled_release:1",
        indicator_family_label="inflation",
    )
    b = _scheduled(
        scheduled_release_id="scheduled_release:2",
        indicator_family_label="labor_market",
    )
    book.add_scheduled_release(a)
    book.add_scheduled_release(b)
    assert book.list_releases_by_indicator_family("inflation") == (a,)
    assert book.list_releases_by_indicator_family("labor_market") == (b,)


def test_book_list_releases_by_cadence():
    book = InformationReleaseBook()
    a = _scheduled(
        scheduled_release_id="scheduled_release:m",
        release_cadence_label="monthly",
    )
    b = _scheduled(
        scheduled_release_id="scheduled_release:q",
        release_cadence_label="quarterly",
    )
    book.add_scheduled_release(a)
    book.add_scheduled_release(b)
    assert book.list_releases_by_cadence("monthly") == (a,)
    assert book.list_releases_by_cadence("quarterly") == (b,)


def test_book_list_releases_by_importance():
    book = InformationReleaseBook()
    a = _scheduled(
        scheduled_release_id="scheduled_release:hi",
        release_importance_label="high_attention",
    )
    b = _scheduled(
        scheduled_release_id="scheduled_release:routine",
        release_importance_label="routine",
    )
    book.add_scheduled_release(a)
    book.add_scheduled_release(b)
    assert book.list_releases_by_importance("high_attention") == (a,)
    assert book.list_releases_by_importance("routine") == (b,)


def test_book_list_arrivals_by_calendar():
    book = InformationReleaseBook()
    a = _arrival(
        information_arrival_id="arrival:1",
        calendar_id="cal_a",
    )
    b = _arrival(
        information_arrival_id="arrival:2",
        calendar_id="cal_b",
    )
    book.add_arrival(a)
    book.add_arrival(b)
    assert book.list_arrivals_by_calendar("cal_a") == (a,)
    assert book.list_arrivals_by_calendar("cal_b") == (b,)


def test_book_list_arrivals_by_indicator_family():
    book = InformationReleaseBook()
    a = _arrival(
        information_arrival_id="arrival:1",
        indicator_family_label="inflation",
    )
    b = _arrival(
        information_arrival_id="arrival:2",
        indicator_family_label="labor_market",
    )
    book.add_arrival(a)
    book.add_arrival(b)
    assert book.list_arrivals_by_indicator_family("inflation") == (a,)
    assert book.list_arrivals_by_indicator_family("labor_market") == (b,)


def test_book_list_arrivals_by_date():
    book = InformationReleaseBook()
    a = _arrival(
        information_arrival_id="arrival:jan",
        as_of_date="2026-01-31",
    )
    b = _arrival(
        information_arrival_id="arrival:feb",
        as_of_date="2026-02-28",
    )
    book.add_arrival(a)
    book.add_arrival(b)
    assert book.list_arrivals_by_date("2026-01-31") == (a,)
    assert book.list_arrivals_by_date("2026-02-28") == (b,)


def test_book_list_arrivals_by_importance():
    book = InformationReleaseBook()
    a = _arrival(
        information_arrival_id="arrival:hi",
        release_importance_label="regime_relevant",
    )
    b = _arrival(
        information_arrival_id="arrival:routine",
        release_importance_label="routine",
    )
    book.add_arrival(a)
    book.add_arrival(b)
    assert book.list_arrivals_by_importance("regime_relevant") == (a,)
    assert book.list_arrivals_by_importance("routine") == (b,)


def test_book_snapshot_deterministic():
    book = InformationReleaseBook()
    book.add_calendar(_calendar())
    book.add_scheduled_release(_scheduled())
    book.add_arrival(_arrival())
    snap_a = book.snapshot()
    snap_b = book.snapshot()
    assert snap_a == snap_b
    assert "calendars" in snap_a
    assert "scheduled_releases" in snap_a
    assert "arrivals" in snap_a
    assert len(snap_a["calendars"]) == 1
    assert len(snap_a["scheduled_releases"]) == 1
    assert len(snap_a["arrivals"]) == 1


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_ledger_emits_one_record_per_add_calendar():
    kernel = _bare_kernel()
    before = len(kernel.ledger.records)
    kernel.information_releases.add_calendar(_calendar())
    after = len(kernel.ledger.records)
    assert after - before == 1
    record = kernel.ledger.records[-1]
    assert record.record_type == RecordType.INFORMATION_RELEASE_CALENDAR_RECORDED


def test_ledger_emits_one_record_per_add_scheduled_release():
    kernel = _bare_kernel()
    kernel.information_releases.add_calendar(_calendar())
    before = len(kernel.ledger.records)
    kernel.information_releases.add_scheduled_release(_scheduled())
    after = len(kernel.ledger.records)
    assert after - before == 1
    record = kernel.ledger.records[-1]
    assert record.record_type == RecordType.SCHEDULED_INDICATOR_RELEASE_RECORDED


def test_ledger_emits_one_record_per_add_arrival():
    kernel = _bare_kernel()
    kernel.information_releases.add_calendar(_calendar())
    kernel.information_releases.add_scheduled_release(_scheduled())
    before = len(kernel.ledger.records)
    kernel.information_releases.add_arrival(_arrival())
    after = len(kernel.ledger.records)
    assert after - before == 1
    record = kernel.ledger.records[-1]
    assert record.record_type == RecordType.INFORMATION_ARRIVAL_RECORDED


def test_three_new_record_types_reachable():
    """v1.19.3 adds three new ``RecordType`` values; each one
    must be reachable via the corresponding ``add_*`` call."""
    kernel = _bare_kernel()
    kernel.information_releases.add_calendar(_calendar())
    kernel.information_releases.add_scheduled_release(_scheduled())
    kernel.information_releases.add_arrival(_arrival())
    seen = {rec.record_type for rec in kernel.ledger.records}
    assert RecordType.INFORMATION_RELEASE_CALENDAR_RECORDED in seen
    assert RecordType.SCHEDULED_INDICATOR_RELEASE_RECORDED in seen
    assert RecordType.INFORMATION_ARRIVAL_RECORDED in seen


def test_duplicate_calendar_emits_no_extra_ledger_record():
    kernel = _bare_kernel()
    kernel.information_releases.add_calendar(_calendar())
    count_after_first = len(kernel.ledger.records)
    with pytest.raises(DuplicateInformationReleaseCalendarError):
        kernel.information_releases.add_calendar(_calendar())
    assert len(kernel.ledger.records) == count_after_first


def test_duplicate_scheduled_release_emits_no_extra_ledger_record():
    kernel = _bare_kernel()
    kernel.information_releases.add_scheduled_release(_scheduled())
    count_after_first = len(kernel.ledger.records)
    with pytest.raises(DuplicateScheduledIndicatorReleaseError):
        kernel.information_releases.add_scheduled_release(_scheduled())
    assert len(kernel.ledger.records) == count_after_first


def test_duplicate_arrival_emits_no_extra_ledger_record():
    kernel = _bare_kernel()
    kernel.information_releases.add_arrival(_arrival())
    count_after_first = len(kernel.ledger.records)
    with pytest.raises(DuplicateInformationArrivalError):
        kernel.information_releases.add_arrival(_arrival())
    assert len(kernel.ledger.records) == count_after_first


def test_ledger_payload_keys_disjoint_from_forbidden():
    kernel = _bare_kernel()
    kernel.information_releases.add_calendar(_calendar())
    kernel.information_releases.add_scheduled_release(_scheduled())
    kernel.information_releases.add_arrival(_arrival())
    for record in kernel.ledger.records[-3:]:
        assert not (
            set(record.payload.keys())
            & FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES
        )


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_wires_information_releases_book():
    kernel = _bare_kernel()
    assert isinstance(
        kernel.information_releases, InformationReleaseBook
    )
    assert kernel.information_releases.ledger is kernel.ledger
    assert kernel.information_releases.list_calendars() == ()
    assert kernel.information_releases.list_scheduled_releases() == ()
    assert kernel.information_releases.list_arrivals() == ()


# ---------------------------------------------------------------------------
# No-mutation invariants
# ---------------------------------------------------------------------------


def test_add_calendar_does_not_mutate_pricebook():
    kernel = _bare_kernel()
    snap_before = kernel.prices.snapshot()
    kernel.information_releases.add_calendar(_calendar())
    snap_after = kernel.prices.snapshot()
    assert snap_before == snap_after


def test_add_arrival_does_not_mutate_pricebook():
    kernel = _bare_kernel()
    snap_before = kernel.prices.snapshot()
    kernel.information_releases.add_arrival(_arrival())
    snap_after = kernel.prices.snapshot()
    assert snap_before == snap_after


def test_add_arrival_does_not_mutate_other_source_of_truth_books():
    kernel = _bare_kernel()
    snaps_before = {
        "ownership": kernel.ownership.snapshot(),
        "contracts": kernel.contracts.snapshot(),
        "constraints": kernel.constraints.snapshot(),
        "valuations": kernel.valuations.snapshot(),
        "institutions": kernel.institutions.snapshot(),
        "external_processes": kernel.external_processes.snapshot(),
        "relationships": kernel.relationships.snapshot(),
    }
    kernel.information_releases.add_calendar(_calendar())
    kernel.information_releases.add_scheduled_release(_scheduled())
    kernel.information_releases.add_arrival(_arrival())
    assert kernel.ownership.snapshot() == snaps_before["ownership"]
    assert kernel.contracts.snapshot() == snaps_before["contracts"]
    assert kernel.constraints.snapshot() == snaps_before["constraints"]
    assert kernel.valuations.snapshot() == snaps_before["valuations"]
    assert kernel.institutions.snapshot() == snaps_before["institutions"]
    assert (
        kernel.external_processes.snapshot()
        == snaps_before["external_processes"]
    )
    assert kernel.relationships.snapshot() == snaps_before["relationships"]


def test_empty_information_releases_does_not_move_default_living_world_digest():
    """Wiring an empty :class:`InformationReleaseBook` into
    :class:`WorldKernel` must leave the default-fixture
    ``living_world_digest`` byte-identical to v1.19.1."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from test_living_reference_world import _run_default, _seed_kernel

    k = _seed_kernel()
    r = _run_default(k)
    assert (
        living_world_digest(k, r)
        == QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST
    )


def test_add_arrival_does_not_create_actor_decision_event():
    kernel = _bare_kernel()
    kernel.information_releases.add_calendar(_calendar())
    kernel.information_releases.add_scheduled_release(_scheduled())
    kernel.information_releases.add_arrival(_arrival())
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
    }
    seen = {rec.record_type.value for rec in kernel.ledger.records}
    assert not (seen & forbidden_event_names)


# ---------------------------------------------------------------------------
# Module-text scans
# ---------------------------------------------------------------------------


def test_module_text_does_not_carry_actor_decision_or_real_data_phrases():
    """Module text must not assert actor decisions or carry
    Japan-real-data tokens as bare identifiers. The forbidden
    field names live inside the
    ``FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES`` literal at
    module scope (the closed-set definition itself); strip that
    literal first. The v1.19.0 boundary-flag set legitimately
    contains compound names like ``no_japan_calibration`` /
    ``no_llm_execution`` / ``no_real_data`` — those are
    boundary-flag *identifiers*, not the bare forbidden
    token, so we scan for word-boundary matches only."""
    text = _MODULE_PATH.read_text(encoding="utf-8")
    open_marker = (
        "FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES: "
        "frozenset[str] = frozenset("
    )
    open_idx = text.find(open_marker)
    close_idx = text.find(")", open_idx) if open_idx >= 0 else -1
    if open_idx >= 0 and close_idx > open_idx:
        text = text[:open_idx] + text[close_idx:]
    forbidden_phrases = (
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
        # v1.19.3 Japan-real-data tokens
        "real_indicator_value",
        "cpi_value",
        "gdp_value",
        "policy_rate",
        "real_release_date",
    )
    for phrase in forbidden_phrases:
        # word-boundary match — ``no_japan_calibration`` (a
        # boundary-flag identifier carried verbatim from
        # v1.19.0) does NOT match ``\bjapan_calibration\b``.
        pattern = rf"\b{re.escape(phrase)}\b"
        assert re.search(pattern, text) is None, (
            f"forbidden phrase {phrase!r} appears as a bare "
            "identifier in information_release.py outside the "
            "closed-set literal"
        )


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
    "nasdaq",
)


def test_module_jurisdiction_neutral_scan():
    text = _MODULE_PATH.read_text(encoding="utf-8").lower()
    # Strip the forbidden-field-names literal so the v1.19.3
    # Japan-token boundary identifiers in that literal do not
    # falsely trip this check.
    open_marker = (
        "forbidden_information_release_field_names: "
        "frozenset[str] = frozenset("
    )
    open_idx = text.find(open_marker)
    close_idx = text.find(")", open_idx) if open_idx >= 0 else -1
    if open_idx >= 0 and close_idx > open_idx:
        text = text[:open_idx] + text[close_idx:]
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"forbidden token {token!r} appears in "
            "information_release.py"
        )


def test_test_file_jurisdiction_neutral_scan():
    text = Path(__file__).read_text(encoding="utf-8").lower()
    # Strip the ``_FORBIDDEN_TOKENS`` table — its contents are
    # this very test's reference set.
    table_start = text.find("_forbidden_tokens = (")
    table_end = text.find(")", table_start) + 1
    if table_start != -1 and table_end > 0:
        text = text[:table_start] + text[table_end:]
    # Strip the ``pinned_v1_19_3`` literal where the v1.19.3
    # forbidden Japan-token names are listed for the
    # ``test_forbidden_field_names_includes_v1_19_3_japan_real_data_tokens``
    # check.
    pinned_start = text.find("pinned_v1_19_3 = {")
    if pinned_start != -1:
        pinned_end = text.find("}", pinned_start) + 1
        if pinned_end > 0:
            text = text[:pinned_start] + text[pinned_end:]
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"forbidden token {token!r} appears in "
            "test_information_release.py"
        )
