"""
Tests for v1.11.0 MarketConditionRecord + MarketConditionBook.

Covers field validation (including bounded synthetic numeric
fields ``strength`` and ``confidence`` and explicit bool rejection
matching the v1 ``world/exposures.py`` style), immutability,
``add_condition`` deduplication, unknown lookup, every list /
filter method, deterministic snapshots, ledger emission with the
new ``RecordType.MARKET_CONDITION_ADDED``, kernel wiring of the
new ``MarketConditionBook``, the no-mutation guarantee against
every other v0/v1 source-of-truth book in the kernel, the v1.11.0
scope discipline (no price formation, no yield-curve calibration,
no order matching, no clearing, no real-data ingestion, no
action-class ledger record on ``add_condition``), an explicit
anti-fields assertion that no ``price`` / ``market_price`` /
``yield_value`` / ``spread_bps`` / ``index_level`` /
``forecast_value`` / ``expected_return`` / ``recommendation`` /
``target_price`` / ``real_data_value`` / ``market_size`` field
exists on the record or in the ledger payload, and a
jurisdiction-neutral identifier scan over both the new module and
the test file.

Identifier and tag strings used in this test suite are
jurisdiction-neutral and synthetic; no Japan-specific institution
name, regulator, exchange, vendor benchmark, code, or threshold
appears anywhere in the test body.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.market_conditions import (
    DuplicateMarketConditionError,
    MarketConditionBook,
    MarketConditionRecord,
    UnknownMarketConditionError,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _condition(
    *,
    condition_id: str = (
        "market_condition:reference_rates_general:2026-03-31"
    ),
    market_id: str = "market:reference_rates_general",
    market_type: str = "reference_rates",
    as_of_date: str = "2026-03-31",
    condition_type: str = "rate_level",
    direction: str = "supportive",
    strength: float = 0.5,
    time_horizon: str = "medium_term",
    confidence: float = 0.5,
    status: str = "active",
    visibility: str = "internal_only",
    related_variable_ids: tuple[str, ...] = (),
    related_signal_ids: tuple[str, ...] = (),
    related_exposure_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> MarketConditionRecord:
    return MarketConditionRecord(
        condition_id=condition_id,
        market_id=market_id,
        market_type=market_type,
        as_of_date=as_of_date,
        condition_type=condition_type,
        direction=direction,
        strength=strength,
        time_horizon=time_horizon,
        confidence=confidence,
        status=status,
        visibility=visibility,
        related_variable_ids=related_variable_ids,
        related_signal_ids=related_signal_ids,
        related_exposure_ids=related_exposure_ids,
        metadata=metadata or {},
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
# Record — field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"condition_id": ""},
        {"market_id": ""},
        {"market_type": ""},
        {"as_of_date": ""},
        {"condition_type": ""},
        {"direction": ""},
        {"time_horizon": ""},
        {"status": ""},
        {"visibility": ""},
    ],
)
def test_condition_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _condition(**kwargs)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "related_variable_ids",
        "related_signal_ids",
        "related_exposure_ids",
    ],
)
def test_condition_rejects_empty_strings_in_tuple_fields(tuple_field):
    bad = {tuple_field: ("valid", "")}
    with pytest.raises(ValueError):
        _condition(**bad)


def test_condition_coerces_as_of_date_to_iso_string():
    c = _condition(as_of_date=date(2026, 3, 31))
    assert c.as_of_date == "2026-03-31"


def test_condition_rejects_non_date_as_of_date():
    with pytest.raises((TypeError, ValueError)):
        _condition(as_of_date=12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Bounded numeric fields — strength + confidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-0.01, 1.01, -1.0, 1.5, 100.0])
def test_strength_rejects_out_of_range(value):
    with pytest.raises(ValueError):
        _condition(strength=value)


@pytest.mark.parametrize("value", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_strength_accepts_in_range(value):
    c = _condition(strength=value)
    assert c.strength == float(value)


def test_strength_rejects_bool_true():
    with pytest.raises(ValueError):
        _condition(strength=True)  # type: ignore[arg-type]


def test_strength_rejects_bool_false():
    with pytest.raises(ValueError):
        _condition(strength=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["0.5", None, [0.5], {"x": 0.5}])
def test_strength_rejects_non_numeric(value):
    with pytest.raises((TypeError, ValueError)):
        _condition(strength=value)  # type: ignore[arg-type]


def test_strength_int_is_accepted_and_coerced_to_float():
    c = _condition(strength=1)
    assert isinstance(c.strength, float)
    assert c.strength == 1.0


@pytest.mark.parametrize("value", [-0.01, 1.01, -1.0, 1.5, 100.0])
def test_confidence_rejects_out_of_range(value):
    with pytest.raises(ValueError):
        _condition(confidence=value)


@pytest.mark.parametrize("value", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_confidence_accepts_in_range(value):
    c = _condition(confidence=value)
    assert c.confidence == float(value)


def test_confidence_rejects_bool_true():
    with pytest.raises(ValueError):
        _condition(confidence=True)  # type: ignore[arg-type]


def test_confidence_rejects_bool_false():
    with pytest.raises(ValueError):
        _condition(confidence=False)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["0.5", None, [0.5], {"x": 0.5}])
def test_confidence_rejects_non_numeric(value):
    with pytest.raises((TypeError, ValueError)):
        _condition(confidence=value)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Immutability & round-trip
# ---------------------------------------------------------------------------


def test_condition_is_frozen():
    c = _condition()
    with pytest.raises(Exception):
        c.condition_id = "tampered"  # type: ignore[misc]


def test_condition_to_dict_round_trips_fields():
    c = _condition(
        related_variable_ids=("variable:reference_var_a",),
        related_signal_ids=("signal:reference_signal_a",),
        related_exposure_ids=("exposure:reference_exposure_a",),
        metadata={"note": "synthetic"},
    )
    out = c.to_dict()
    assert out["condition_id"] == c.condition_id
    assert out["market_id"] == c.market_id
    assert out["market_type"] == c.market_type
    assert out["as_of_date"] == c.as_of_date
    assert out["condition_type"] == c.condition_type
    assert out["direction"] == c.direction
    assert out["strength"] == c.strength
    assert out["time_horizon"] == c.time_horizon
    assert out["confidence"] == c.confidence
    assert out["status"] == c.status
    assert out["visibility"] == c.visibility
    assert out["related_variable_ids"] == ["variable:reference_var_a"]
    assert out["related_signal_ids"] == ["signal:reference_signal_a"]
    assert out["related_exposure_ids"] == ["exposure:reference_exposure_a"]
    assert out["metadata"] == {"note": "synthetic"}


def test_condition_metadata_is_independent_copy():
    src = {"note": "synthetic"}
    c = _condition(metadata=src)
    src["note"] = "tampered"
    assert c.metadata["note"] == "synthetic"


# ---------------------------------------------------------------------------
# Anti-fields — no price / yield / spread / index / forecast / recommendation
# ---------------------------------------------------------------------------


def test_condition_record_has_no_price_or_forecast_field():
    """
    v1.11.0 market-condition record must store the synthetic
    direction / strength / confidence triple plus generic labels —
    never a price quote, yield, spread, index level, forecast,
    expected return, recommendation, target price, real-data
    value, or market size. The v1.11.0 anti-fields list is the
    binding contract this test pins.
    """
    field_names = {
        f.name for f in dataclass_fields(MarketConditionRecord)
    }
    forbidden = {
        "price",
        "market_price",
        "yield_value",
        "spread_bps",
        "index_level",
        "forecast_value",
        "expected_return",
        "recommendation",
        "target_price",
        "real_data_value",
        "market_size",
    }
    leaked = field_names & forbidden
    assert not leaked, (
        f"v1.11.0 market condition must not carry price / yield / "
        f"spread / index / forecast / recommendation fields; "
        f"found: {sorted(leaked)}"
    )


# ---------------------------------------------------------------------------
# Book — add / get / dedup / unknown
# ---------------------------------------------------------------------------


def test_add_and_get_condition():
    book = MarketConditionBook()
    c = _condition()
    book.add_condition(c)
    assert book.get_condition(c.condition_id) is c


def test_get_condition_unknown_raises():
    book = MarketConditionBook()
    with pytest.raises(UnknownMarketConditionError):
        book.get_condition("does-not-exist")


def test_unknown_market_condition_error_is_keyerror():
    err = UnknownMarketConditionError("missing")
    assert isinstance(err, KeyError)


def test_duplicate_condition_id_rejected():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:dup"))
    with pytest.raises(DuplicateMarketConditionError):
        book.add_condition(_condition(condition_id="mc:dup"))


def test_add_condition_returns_record():
    book = MarketConditionBook()
    c = _condition()
    returned = book.add_condition(c)
    assert returned is c


# ---------------------------------------------------------------------------
# Listings & filters
# ---------------------------------------------------------------------------


def test_list_conditions_in_insertion_order():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:a"))
    book.add_condition(_condition(condition_id="mc:b"))
    book.add_condition(_condition(condition_id="mc:c"))
    listed = book.list_conditions()
    assert tuple(c.condition_id for c in listed) == (
        "mc:a", "mc:b", "mc:c",
    )


def test_list_conditions_empty_book():
    assert MarketConditionBook().list_conditions() == ()


def test_list_by_market():
    book = MarketConditionBook()
    book.add_condition(
        _condition(condition_id="mc:rates_q1", market_id="market:reference_rates_general")
    )
    book.add_condition(
        _condition(
            condition_id="mc:credit_q1",
            market_id="market:reference_credit_spreads_general",
            market_type="credit_spreads",
            condition_type="spread_level",
        )
    )
    book.add_condition(
        _condition(condition_id="mc:rates_q2", market_id="market:reference_rates_general")
    )
    matched = book.list_by_market("market:reference_rates_general")
    assert tuple(c.condition_id for c in matched) == (
        "mc:rates_q1", "mc:rates_q2",
    )


def test_list_by_market_no_match():
    book = MarketConditionBook()
    book.add_condition(_condition(market_id="market:reference_rates_general"))
    assert book.list_by_market("market:reference_other") == ()


def test_list_by_market_type():
    book = MarketConditionBook()
    book.add_condition(
        _condition(condition_id="mc:r", market_type="reference_rates")
    )
    book.add_condition(
        _condition(condition_id="mc:c", market_type="credit_spreads")
    )
    book.add_condition(
        _condition(condition_id="mc:r2", market_type="reference_rates")
    )
    rates = book.list_by_market_type("reference_rates")
    assert tuple(c.condition_id for c in rates) == ("mc:r", "mc:r2")


def test_list_by_condition_type():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:rl", condition_type="rate_level"))
    book.add_condition(
        _condition(condition_id="mc:fw", condition_type="funding_window")
    )
    matched = book.list_by_condition_type("funding_window")
    assert tuple(c.condition_id for c in matched) == ("mc:fw",)


def test_list_by_direction():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:eas", direction="easing"))
    book.add_condition(
        _condition(condition_id="mc:tig", direction="tightening")
    )
    book.add_condition(_condition(condition_id="mc:wid", direction="widening"))
    book.add_condition(_condition(condition_id="mc:nar", direction="narrowing"))
    book.add_condition(
        _condition(condition_id="mc:sup", direction="supportive")
    )
    book.add_condition(
        _condition(condition_id="mc:res", direction="restrictive")
    )
    book.add_condition(_condition(condition_id="mc:mix", direction="mixed"))
    book.add_condition(_condition(condition_id="mc:unk", direction="unknown"))
    for direction, expected_id in [
        ("easing", "mc:eas"),
        ("tightening", "mc:tig"),
        ("widening", "mc:wid"),
        ("narrowing", "mc:nar"),
        ("supportive", "mc:sup"),
        ("restrictive", "mc:res"),
        ("mixed", "mc:mix"),
        ("unknown", "mc:unk"),
    ]:
        assert tuple(
            c.condition_id for c in book.list_by_direction(direction)
        ) == (expected_id,)


def test_list_by_status():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:draft", status="draft"))
    book.add_condition(_condition(condition_id="mc:active", status="active"))
    book.add_condition(_condition(condition_id="mc:retired", status="retired"))
    assert tuple(
        c.condition_id for c in book.list_by_status("active")
    ) == ("mc:active",)


def test_list_by_date_filters_exactly():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:mar", as_of_date="2026-03-31"))
    book.add_condition(_condition(condition_id="mc:jun", as_of_date="2026-06-30"))
    book.add_condition(_condition(condition_id="mc:mar2", as_of_date="2026-03-31"))
    mar = book.list_by_date("2026-03-31")
    jun = book.list_by_date("2026-06-30")
    miss = book.list_by_date("2026-07-31")
    assert tuple(c.condition_id for c in mar) == ("mc:mar", "mc:mar2")
    assert tuple(c.condition_id for c in jun) == ("mc:jun",)
    assert miss == ()


def test_list_by_date_accepts_date_object():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:mar", as_of_date="2026-03-31"))
    matched = book.list_by_date(date(2026, 3, 31))
    assert tuple(c.condition_id for c in matched) == ("mc:mar",)


# ---------------------------------------------------------------------------
# Plain-id cross-references — no validation against any other book
# ---------------------------------------------------------------------------


def test_condition_can_reference_unresolved_variable_signal_exposure_ids():
    book = MarketConditionBook()
    c = _condition(
        related_variable_ids=("variable:not-in-variable-book",),
        related_signal_ids=("signal:not-in-signal-book",),
        related_exposure_ids=("exposure:not-in-exposure-book",),
    )
    book.add_condition(c)
    assert book.get_condition(c.condition_id) is c


def test_condition_id_can_be_referenced_from_corporate_response_candidate():
    """
    A v1.10.3 ``CorporateStrategicResponseCandidate`` cites a v1.11.0
    market-condition id via its **type-correct slot**
    ``trigger_market_condition_ids`` (added in v1.11.0) — *not*
    via ``trigger_signal_ids`` and *not* via
    ``trigger_industry_condition_ids``. The dedicated slot keeps
    ``signal_id`` / ``industry_condition_id`` /
    ``market_condition_id`` distinguishable in ledger replay,
    lineage reconstruction, and report generation without
    requiring payload introspection.
    """
    from world.strategic_response import (
        CorporateStrategicResponseCandidate,
        StrategicResponseCandidateBook,
    )

    book = MarketConditionBook()
    c = _condition(condition_id="mc:cited")
    book.add_condition(c)

    response_book = StrategicResponseCandidateBook()
    response_book.add_candidate(
        CorporateStrategicResponseCandidate(
            response_candidate_id="resp:cites_market_cond",
            company_id="firm:reference_manufacturer_a",
            as_of_date="2026-04-01",
            response_type="capital_allocation_review",
            status="draft",
            priority="medium",
            horizon="medium_term",
            expected_effect_label=(
                "expected_efficiency_improvement_candidate"
            ),
            constraint_label="subject_to_board_review",
            visibility="internal_only",
            trigger_market_condition_ids=("mc:cited",),
        )
    )
    listed = response_book.list_candidates()
    assert listed[0].trigger_market_condition_ids == ("mc:cited",)
    # Type-correct slot must keep market-condition ids out of both
    # the signal slot and the industry-condition slot.
    assert listed[0].trigger_signal_ids == ()
    assert listed[0].trigger_industry_condition_ids == ()
    assert response_book.list_by_market_condition("mc:cited") == (
        listed[0],
    )


# ---------------------------------------------------------------------------
# Snapshot determinism
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_and_sorted():
    book = MarketConditionBook()
    book.add_condition(_condition(condition_id="mc:z"))
    book.add_condition(_condition(condition_id="mc:a"))
    book.add_condition(_condition(condition_id="mc:m"))

    snap1 = book.snapshot()
    snap2 = book.snapshot()
    assert snap1 == snap2
    assert snap1["condition_count"] == 3
    assert [c["condition_id"] for c in snap1["conditions"]] == [
        "mc:a", "mc:m", "mc:z",
    ]


def test_snapshot_empty_book():
    snap = MarketConditionBook().snapshot()
    assert snap == {"condition_count": 0, "conditions": []}


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    assert (
        RecordType("market_condition_added")
        is RecordType.MARKET_CONDITION_ADDED
    )
    assert RecordType.MARKET_CONDITION_ADDED.value == "market_condition_added"


def test_add_condition_writes_exactly_one_ledger_record():
    ledger = Ledger()
    book = MarketConditionBook(ledger=ledger)
    book.add_condition(_condition(condition_id="mc:emit"))
    records = ledger.filter(event_type="market_condition_added")
    assert len(records) == 1
    record = records[0]
    assert record.record_type is RecordType.MARKET_CONDITION_ADDED
    assert record.object_id == "mc:emit"
    assert record.source == "market:reference_rates_general"
    assert record.space_id == "capital_markets"
    assert record.visibility == "internal_only"
    assert record.confidence == 0.5


def test_add_condition_payload_carries_full_field_set():
    ledger = Ledger()
    book = MarketConditionBook(ledger=ledger)
    book.add_condition(
        _condition(
            condition_id="mc:payload",
            related_variable_ids=("variable:reference_var_a",),
            related_signal_ids=("signal:reference_signal_a",),
            related_exposure_ids=("exposure:reference_exposure_a",),
        )
    )
    payload = ledger.filter(event_type="market_condition_added")[-1].payload
    assert payload["condition_id"] == "mc:payload"
    assert payload["market_id"] == "market:reference_rates_general"
    assert payload["market_type"] == "reference_rates"
    assert payload["as_of_date"] == "2026-03-31"
    assert payload["condition_type"] == "rate_level"
    assert payload["direction"] == "supportive"
    assert payload["strength"] == 0.5
    assert payload["time_horizon"] == "medium_term"
    assert payload["confidence"] == 0.5
    assert payload["status"] == "active"
    assert payload["visibility"] == "internal_only"
    assert tuple(payload["related_variable_ids"]) == (
        "variable:reference_var_a",
    )
    assert tuple(payload["related_signal_ids"]) == (
        "signal:reference_signal_a",
    )
    assert tuple(payload["related_exposure_ids"]) == (
        "exposure:reference_exposure_a",
    )


def test_add_condition_payload_carries_no_price_or_forecast_keys():
    ledger = Ledger()
    book = MarketConditionBook(ledger=ledger)
    book.add_condition(_condition(condition_id="mc:audit"))
    payload_keys = set(
        ledger.filter(event_type="market_condition_added")[-1].payload.keys()
    )
    forbidden = {
        "price",
        "market_price",
        "yield_value",
        "spread_bps",
        "index_level",
        "forecast_value",
        "expected_return",
        "recommendation",
        "target_price",
        "real_data_value",
        "market_size",
    }
    leaked = payload_keys & forbidden
    assert not leaked, (
        f"v1.11.0 market condition payload must not carry price / "
        f"yield / spread / index / forecast / recommendation keys; "
        f"found: {sorted(leaked)}"
    )


def test_add_condition_without_ledger_does_not_raise():
    book = MarketConditionBook()
    book.add_condition(_condition())


def test_duplicate_add_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = MarketConditionBook(ledger=ledger)
    book.add_condition(_condition(condition_id="mc:once"))
    with pytest.raises(DuplicateMarketConditionError):
        book.add_condition(_condition(condition_id="mc:once"))
    assert len(ledger.filter(event_type="market_condition_added")) == 1


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_market_conditions_book():
    kernel = _kernel()
    assert isinstance(kernel.market_conditions, MarketConditionBook)
    assert kernel.market_conditions.ledger is kernel.ledger
    assert kernel.market_conditions.clock is kernel.clock


def test_kernel_add_condition_emits_to_kernel_ledger():
    kernel = _kernel()
    kernel.market_conditions.add_condition(_condition())
    records = kernel.ledger.filter(event_type="market_condition_added")
    assert len(records) == 1


def test_kernel_market_condition_simulation_date_uses_clock():
    kernel = _kernel()
    kernel.market_conditions.add_condition(
        _condition(condition_id="mc:wired")
    )
    records = kernel.ledger.filter(event_type="market_condition_added")
    assert records[-1].simulation_date == "2026-01-01"


# ---------------------------------------------------------------------------
# No-mutation guarantee against every other source-of-truth book
# ---------------------------------------------------------------------------


def test_market_conditions_book_does_not_mutate_other_kernel_books():
    kernel = _kernel()
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-01-01", "exchange")

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
        "exposures": kernel.exposures.snapshot(),
        "stewardship": kernel.stewardship.snapshot(),
        "engagement": kernel.engagement.snapshot(),
        "escalations": kernel.escalations.snapshot(),
        "strategic_responses": kernel.strategic_responses.snapshot(),
        "industry_conditions": kernel.industry_conditions.snapshot(),
    }

    kernel.market_conditions.add_condition(
        _condition(
            condition_id="mc:k:a",
            related_variable_ids=("variable:reference_var_a",),
            related_signal_ids=("signal:reference_signal_a",),
            related_exposure_ids=("exposure:reference_exposure_a",),
        )
    )
    kernel.market_conditions.add_condition(
        _condition(
            condition_id="mc:k:b",
            market_id="market:reference_credit_spreads_general",
            market_type="credit_spreads",
            condition_type="spread_level",
            direction="widening",
            strength=0.3,
            confidence=0.7,
            status="under_review",
            visibility="public",
            as_of_date="2026-04-15",
        )
    )
    kernel.market_conditions.list_conditions()
    kernel.market_conditions.list_by_market("market:reference_rates_general")
    kernel.market_conditions.list_by_market_type("reference_rates")
    kernel.market_conditions.list_by_condition_type("rate_level")
    kernel.market_conditions.list_by_direction("supportive")
    kernel.market_conditions.list_by_status("active")
    kernel.market_conditions.list_by_date("2026-03-31")
    kernel.market_conditions.snapshot()

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
    assert kernel.exposures.snapshot() == snaps_before["exposures"]
    assert kernel.stewardship.snapshot() == snaps_before["stewardship"]
    assert kernel.engagement.snapshot() == snaps_before["engagement"]
    assert kernel.escalations.snapshot() == snaps_before["escalations"]
    assert (
        kernel.strategic_responses.snapshot()
        == snaps_before["strategic_responses"]
    )
    assert (
        kernel.industry_conditions.snapshot()
        == snaps_before["industry_conditions"]
    )


# ---------------------------------------------------------------------------
# No-action invariant
# ---------------------------------------------------------------------------


def test_market_conditions_emits_only_market_condition_added_records():
    ledger = Ledger()
    book = MarketConditionBook(ledger=ledger)
    book.add_condition(_condition(condition_id="mc:audit"))
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert record.record_type is RecordType.MARKET_CONDITION_ADDED


def test_market_conditions_does_not_emit_action_or_price_records():
    """
    v1.11.0 add_condition must not emit any action-class or
    price-formation-class record. The forbidden record-type set
    covers every v1.x action-shaped record plus every record we
    would associate with order matching, clearing, price formation,
    or covenant enforcement.
    """
    forbidden_event_types = {
        "order_submitted",
        "price_updated",
        "contract_created",
        "contract_status_updated",
        "contract_covenant_breached",
        "ownership_position_added",
        "ownership_transferred",
        "institution_action_recorded",
        "valuation_added",
        "valuation_compared",
        "firm_state_added",
    }
    ledger = Ledger()
    book = MarketConditionBook(ledger=ledger)
    book.add_condition(_condition(condition_id="mc:no_action"))
    seen = {r.event_type for r in ledger.records}
    assert seen.isdisjoint(forbidden_event_types), (
        f"v1.11.0 add_condition must not emit any action / "
        f"price-formation / firm-state record; saw forbidden "
        f"event types: {sorted(seen & forbidden_event_types)}"
    )


# ---------------------------------------------------------------------------
# Jurisdiction-neutral identifier scan
#
# This test reads its own source file and confirms that every test
# string is jurisdiction-neutral. The forbidden token list mirrors
# ``world/experiment.py::_FORBIDDEN_TOKENS``; this duplication is
# intentional so that the test fails locally even when the
# experiment-config scan does not run.
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
)


def test_test_file_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    text = Path(__file__).read_text(encoding="utf-8").lower()
    table_start = text.find("_forbidden_tokens = (")
    table_end = text.find(")", table_start) + 1
    if table_start != -1 and table_end > 0:
        text = text[:table_start] + text[table_end:]

    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"jurisdiction-specific token {token!r} appeared in test file"
        )


def test_market_conditions_module_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parent.parent
        / "world"
        / "market_conditions.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"jurisdiction-specific token {token!r} appeared in "
            f"world/market_conditions.py"
        )
