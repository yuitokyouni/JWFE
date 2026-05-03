"""
Tests for v1.15.3 AggregatedMarketInterestRecord +
AggregatedMarketInterestBook + ``build_aggregated_market_interest``.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.market_interest import (
    AggregatedMarketInterestBook,
    AggregatedMarketInterestRecord,
    CONCENTRATION_LABELS,
    DuplicateAggregatedMarketInterestError,
    LIQUIDITY_INTEREST_LABELS,
    NET_INTEREST_LABELS,
    STATUS_LABELS,
    UnknownAggregatedMarketInterestError,
    build_aggregated_market_interest,
)
from world.market_intents import InvestorMarketIntentRecord
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _record(
    *,
    aggregated_interest_id: str = (
        "aggregated_market_interest:venue:reference_exchange_a:"
        "security:reference_a:equity:line_1:2026-03-31"
    ),
    venue_id: str = "venue:reference_exchange_a",
    security_id: str = "security:reference_a:equity:line_1",
    as_of_date: str = "2026-03-31",
    increased_interest_count: int = 0,
    reduced_interest_count: int = 0,
    neutral_or_hold_review_count: int = 0,
    liquidity_watch_count: int = 0,
    risk_reduction_review_count: int = 0,
    engagement_linked_review_count: int = 0,
    total_intent_count: int = 0,
    net_interest_label: str = "insufficient_observations",
    liquidity_interest_label: str = "unknown",
    concentration_label: str = "insufficient_observations",
    status: str = "active",
    visibility: str = "internal_only",
    confidence: float = 0.5,
    source_market_intent_ids: tuple[str, ...] = (),
    source_market_environment_state_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> AggregatedMarketInterestRecord:
    return AggregatedMarketInterestRecord(
        aggregated_interest_id=aggregated_interest_id,
        venue_id=venue_id,
        security_id=security_id,
        as_of_date=as_of_date,
        increased_interest_count=increased_interest_count,
        reduced_interest_count=reduced_interest_count,
        neutral_or_hold_review_count=neutral_or_hold_review_count,
        liquidity_watch_count=liquidity_watch_count,
        risk_reduction_review_count=risk_reduction_review_count,
        engagement_linked_review_count=engagement_linked_review_count,
        total_intent_count=total_intent_count,
        net_interest_label=net_interest_label,
        liquidity_interest_label=liquidity_interest_label,
        concentration_label=concentration_label,
        status=status,
        visibility=visibility,
        confidence=confidence,
        source_market_intent_ids=source_market_intent_ids,
        source_market_environment_state_ids=source_market_environment_state_ids,
        metadata=metadata or {},
    )


def _intent(
    *,
    market_intent_id: str,
    investor_id: str = "investor:reference_a",
    security_id: str = "security:reference_a:equity:line_1",
    intent_direction_label: str = "increase_interest",
) -> InvestorMarketIntentRecord:
    return InvestorMarketIntentRecord(
        market_intent_id=market_intent_id,
        investor_id=investor_id,
        security_id=security_id,
        as_of_date="2026-03-31",
        intent_direction_label=intent_direction_label,
        intensity_label="moderate",
        horizon_label="near_term",
        status="active",
        visibility="internal_only",
        confidence=0.5,
    )


# ---------------------------------------------------------------------------
# Required-string validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"aggregated_interest_id": ""},
        {"venue_id": ""},
        {"security_id": ""},
        {"as_of_date": ""},
        {"visibility": ""},
    ],
)
def test_record_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _record(**kwargs)


def test_record_coerces_date_to_iso_string():
    r = _record(as_of_date=date(2026, 3, 31))
    assert r.as_of_date == "2026-03-31"


def test_record_is_frozen():
    r = _record()
    with pytest.raises(Exception):
        r.aggregated_interest_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Count fields — non-negative + bool rejection
# ---------------------------------------------------------------------------


_COUNT_FIELDS = (
    "increased_interest_count",
    "reduced_interest_count",
    "neutral_or_hold_review_count",
    "liquidity_watch_count",
    "risk_reduction_review_count",
    "engagement_linked_review_count",
    "total_intent_count",
)


@pytest.mark.parametrize("field_name", _COUNT_FIELDS)
def test_record_rejects_negative_count(field_name):
    with pytest.raises(ValueError):
        _record(**{field_name: -1})


@pytest.mark.parametrize("field_name", _COUNT_FIELDS)
def test_record_rejects_bool_count(field_name):
    with pytest.raises(ValueError):
        _record(**{field_name: True})


@pytest.mark.parametrize("field_name", _COUNT_FIELDS)
def test_record_rejects_non_int_count(field_name):
    with pytest.raises(ValueError):
        _record(**{field_name: 1.5})


# ---------------------------------------------------------------------------
# Confidence (bounded, bool-rejecting)
# ---------------------------------------------------------------------------


def test_record_rejects_bool_confidence():
    with pytest.raises(ValueError):
        _record(confidence=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_record_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValueError):
        _record(confidence=bad)


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_record_accepts_in_range_confidence(good):
    r = _record(confidence=good)
    assert r.confidence == float(good)


def test_record_rejects_non_numeric_confidence():
    with pytest.raises(ValueError):
        _record(confidence="0.5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Source-id tuple validation
# ---------------------------------------------------------------------------


def test_record_rejects_empty_strings_in_source_tuples():
    for kwarg in (
        "source_market_intent_ids",
        "source_market_environment_state_ids",
    ):
        with pytest.raises(ValueError):
            _record(**{kwarg: ("",)})


def test_record_to_dict_round_trips():
    r = _record(
        source_market_intent_ids=(
            "market_intent:investor_a:security_a:2026-03-31",
        ),
        source_market_environment_state_ids=(
            "market_environment_state:2026Q3",
        ),
        metadata={"note": "synthetic"},
    )
    out = r.to_dict()
    assert out["source_market_intent_ids"] == [
        "market_intent:investor_a:security_a:2026-03-31"
    ]
    assert out["source_market_environment_state_ids"] == [
        "market_environment_state:2026Q3"
    ]
    assert out["metadata"] == {"note": "synthetic"}


# ---------------------------------------------------------------------------
# Closed-set acceptance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(NET_INTEREST_LABELS))
def test_net_interest_labels_accepted(label):
    r = _record(net_interest_label=label)
    assert r.net_interest_label == label


@pytest.mark.parametrize("label", sorted(LIQUIDITY_INTEREST_LABELS))
def test_liquidity_interest_labels_accepted(label):
    r = _record(liquidity_interest_label=label)
    assert r.liquidity_interest_label == label


@pytest.mark.parametrize("label", sorted(CONCENTRATION_LABELS))
def test_concentration_labels_accepted(label):
    r = _record(concentration_label=label)
    assert r.concentration_label == label


@pytest.mark.parametrize("label", sorted(STATUS_LABELS))
def test_status_labels_accepted(label):
    r = _record(status=label)
    assert r.status == label


# ---------------------------------------------------------------------------
# Closed-set rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "net_interest_label",
        "liquidity_interest_label",
        "concentration_label",
        "status",
    ],
)
def test_label_field_rejects_out_of_set_value(field_name):
    with pytest.raises(ValueError):
        _record(**{field_name: "not_a_real_label"})


# ---------------------------------------------------------------------------
# Closed-set pinning
# ---------------------------------------------------------------------------


def test_pinned_net_interest_label_set_is_exact():
    assert NET_INTEREST_LABELS == frozenset(
        {
            "increased_interest",
            "reduced_interest",
            "balanced",
            "mixed",
            "insufficient_observations",
            "unknown",
        }
    )


def test_pinned_liquidity_interest_label_set_is_exact():
    assert LIQUIDITY_INTEREST_LABELS == frozenset(
        {
            "liquidity_attention_low",
            "liquidity_attention_moderate",
            "liquidity_attention_high",
            "unknown",
        }
    )


def test_pinned_concentration_label_set_is_exact():
    assert CONCENTRATION_LABELS == frozenset(
        {
            "dispersed",
            "moderately_concentrated",
            "concentrated",
            "insufficient_observations",
            "unknown",
        }
    )


def test_pinned_status_label_set_is_exact():
    assert STATUS_LABELS == frozenset(
        {
            "draft",
            "active",
            "stale",
            "superseded",
            "archived",
            "unknown",
        }
    )


# ---------------------------------------------------------------------------
# Anti-fields — must NOT appear on dataclass or ledger payload
# ---------------------------------------------------------------------------


_FORBIDDEN_FIELDS = {
    "buy",
    "sell",
    "order",
    "order_id",
    "trade",
    "trade_id",
    "execution",
    "executed",
    "bid",
    "ask",
    "quote",
    "clearing",
    "settlement",
    "price",
    "order_imbalance",
    "target_price",
    "expected_return",
    "recommendation",
    "investment_advice",
    "real_data_value",
    # plus the v1.14.x family standard set
    "amount",
    "loan_amount",
    "interest_rate",
    "coupon",
    "coupon_rate",
    "spread",
    "fee",
    "yield",
    "policy_rate",
    "interest",
    "tenor_years",
    "default_probability",
    "behavior_probability",
    "rating",
    "internal_rating",
    "pd",
    "lgd",
    "ead",
    "decision_outcome",
    "forecast_value",
    "actual_value",
    "underwriting",
    "syndication",
    "commitment",
    "allocation",
    "offering_price",
    "take_up_probability",
    "selected_option",
    "optimal_option",
    "approved",
    "target_weight",
    "overweight",
    "underweight",
}


def test_record_has_no_anti_fields():
    field_names = {
        f.name for f in dataclass_fields(AggregatedMarketInterestRecord)
    }
    leaked = field_names & _FORBIDDEN_FIELDS
    assert not leaked


# ---------------------------------------------------------------------------
# Book — CRUD
# ---------------------------------------------------------------------------


def test_book_add_and_get_record():
    book = AggregatedMarketInterestBook()
    r = _record()
    book.add_record(r)
    assert book.get_record(r.aggregated_interest_id) is r


def test_book_get_unknown_record_raises():
    book = AggregatedMarketInterestBook()
    with pytest.raises(UnknownAggregatedMarketInterestError):
        book.get_record("aggregated_market_interest:missing")
    with pytest.raises(KeyError):
        book.get_record("aggregated_market_interest:missing")


def test_book_duplicate_id_rejected():
    book = AggregatedMarketInterestBook()
    book.add_record(_record())
    with pytest.raises(DuplicateAggregatedMarketInterestError):
        book.add_record(_record())


def test_book_list_records_returns_all():
    book = AggregatedMarketInterestBook()
    book.add_record(_record(aggregated_interest_id="aggregated_market_interest:a"))
    book.add_record(_record(aggregated_interest_id="aggregated_market_interest:b"))
    assert len(book.list_records()) == 2


def test_book_list_by_venue():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a",
            venue_id="venue:p1",
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b",
            venue_id="venue:p2",
        )
    )
    out = book.list_by_venue("venue:p1")
    assert len(out) == 1


def test_book_list_by_security():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a",
            security_id="security:p1",
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b",
            security_id="security:p2",
        )
    )
    assert len(book.list_by_security("security:p2")) == 1


def test_book_list_by_date():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a",
            as_of_date="2026-03-31",
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b",
            as_of_date="2026-04-30",
        )
    )
    assert len(book.list_by_date("2026-04-30")) == 1


def test_book_list_by_net_interest():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a",
            net_interest_label="insufficient_observations",
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b",
            net_interest_label="balanced",
            total_intent_count=3,
            increased_interest_count=1,
            reduced_interest_count=1,
            neutral_or_hold_review_count=1,
        )
    )
    assert len(book.list_by_net_interest("balanced")) == 1


def test_book_list_by_liquidity_interest():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a",
            liquidity_interest_label="unknown",
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b",
            liquidity_interest_label="liquidity_attention_low",
            total_intent_count=2,
            neutral_or_hold_review_count=2,
        )
    )
    assert len(book.list_by_liquidity_interest("liquidity_attention_low")) == 1


def test_book_list_by_status():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a", status="active"
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b", status="superseded"
        )
    )
    assert len(book.list_by_status("superseded")) == 1


def test_book_list_by_source_market_intent():
    book = AggregatedMarketInterestBook()
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:a",
            source_market_intent_ids=("market_intent:n1",),
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:b",
            source_market_intent_ids=(
                "market_intent:n1",
                "market_intent:n2",
            ),
        )
    )
    book.add_record(
        _record(
            aggregated_interest_id="aggregated_market_interest:c",
            source_market_intent_ids=("market_intent:n3",),
        )
    )
    out = book.list_by_source_market_intent("market_intent:n1")
    assert {r.aggregated_interest_id for r in out} == {
        "aggregated_market_interest:a",
        "aggregated_market_interest:b",
    }


def test_book_snapshot_is_deterministic_and_sorted():
    book = AggregatedMarketInterestBook()
    book.add_record(_record(aggregated_interest_id="aggregated_market_interest:b"))
    book.add_record(_record(aggregated_interest_id="aggregated_market_interest:a"))
    snap = book.snapshot()
    assert snap["record_count"] == 2
    assert [r["aggregated_interest_id"] for r in snap["records"]] == [
        "aggregated_market_interest:a",
        "aggregated_market_interest:b",
    ]
    assert book.snapshot() == snap


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    assert (
        RecordType.AGGREGATED_MARKET_INTEREST_RECORDED.value
        == "aggregated_market_interest_recorded"
    )


def test_add_record_writes_exactly_one_ledger_record():
    ledger = Ledger()
    book = AggregatedMarketInterestBook(ledger=ledger)
    book.add_record(_record())
    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert rec.record_type is RecordType.AGGREGATED_MARKET_INTEREST_RECORDED
    assert rec.space_id == "aggregated_market_interest"


def test_duplicate_add_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = AggregatedMarketInterestBook(ledger=ledger)
    book.add_record(_record())
    with pytest.raises(DuplicateAggregatedMarketInterestError):
        book.add_record(_record())
    assert len(ledger.records) == 1


def test_ledger_record_routes_venue_to_security():
    """``source = venue_id``, ``target = security_id`` so the
    ledger graph reads as 'venue V aggregated market interest
    for security S'."""
    ledger = Ledger()
    book = AggregatedMarketInterestBook(ledger=ledger)
    book.add_record(_record())
    rec = ledger.records[0]
    assert rec.source == "venue:reference_exchange_a"
    assert rec.target == "security:reference_a:equity:line_1"


def test_ledger_payload_contains_count_and_label_fields():
    ledger = Ledger()
    book = AggregatedMarketInterestBook(ledger=ledger)
    book.add_record(
        _record(
            increased_interest_count=2,
            reduced_interest_count=1,
            neutral_or_hold_review_count=0,
            total_intent_count=3,
            net_interest_label="increased_interest",
        )
    )
    rec = ledger.records[0]
    assert rec.payload["increased_interest_count"] == 2
    assert rec.payload["reduced_interest_count"] == 1
    assert rec.payload["total_intent_count"] == 3
    assert rec.payload["net_interest_label"] == "increased_interest"


def test_ledger_payload_carries_no_anti_field_keys():
    ledger = Ledger()
    book = AggregatedMarketInterestBook(ledger=ledger)
    book.add_record(_record())
    rec = ledger.records[0]
    leaked = set(rec.payload.keys()) & _FORBIDDEN_FIELDS
    assert not leaked


def test_ledger_emits_no_forbidden_event_types():
    ledger = Ledger()
    book = AggregatedMarketInterestBook(ledger=ledger)
    book.add_record(_record())
    types = {rec.record_type for rec in ledger.records}
    assert types == {RecordType.AGGREGATED_MARKET_INTEREST_RECORDED}


def test_book_without_ledger_does_not_raise():
    book = AggregatedMarketInterestBook()
    book.add_record(_record())


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_aggregated_market_interest_book():
    k = _kernel()
    assert isinstance(k.aggregated_market_interest, AggregatedMarketInterestBook)
    assert k.aggregated_market_interest.ledger is k.ledger
    assert k.aggregated_market_interest.clock is k.clock


def test_kernel_simulation_date_uses_clock_for_record():
    k = _kernel()
    k.aggregated_market_interest.add_record(_record())
    rec = k.ledger.records[-1]
    assert rec.simulation_date == "2026-03-31"


# ---------------------------------------------------------------------------
# No-mutation invariant
# ---------------------------------------------------------------------------


def test_book_does_not_mutate_other_kernel_books():
    k = _kernel()
    snaps_before = {
        "ownership": k.ownership.snapshot(),
        "contracts": k.contracts.snapshot(),
        "prices": k.prices.snapshot(),
        "constraints": k.constraints.snapshot(),
        "signals": k.signals.snapshot(),
        "valuations": k.valuations.snapshot(),
        "settlement_accounts": k.settlement_accounts.snapshot(),
        "settlement_payments": k.settlement_payments.snapshot(),
        "interbank_liquidity": k.interbank_liquidity.snapshot(),
        "central_bank_signals": k.central_bank_signals.snapshot(),
        "attention_feedback": k.attention_feedback.snapshot(),
        "investor_intents": k.investor_intents.snapshot(),
        "market_environments": k.market_environments.snapshot(),
        "firm_financial_states": k.firm_financial_states.snapshot(),
        "corporate_financing_needs": k.corporate_financing_needs.snapshot(),
        "funding_options": k.funding_options.snapshot(),
        "capital_structure_reviews": k.capital_structure_reviews.snapshot(),
        "financing_paths": k.financing_paths.snapshot(),
        "security_market": k.security_market.snapshot(),
        "investor_market_intents": k.investor_market_intents.snapshot(),
    }
    k.aggregated_market_interest.add_record(_record())
    for name, before in snaps_before.items():
        assert getattr(k, name).snapshot() == before, name


# ---------------------------------------------------------------------------
# Builder — bucket mapping per direction label
# ---------------------------------------------------------------------------


def _seed_intents(
    k: WorldKernel,
    pairs: list[tuple[str, str]],
    *,
    security_id: str = "security:reference_a:equity:line_1",
) -> list[str]:
    """Seed the kernel with one InvestorMarketIntentRecord per
    (intent_id_suffix, intent_direction_label) pair. Returns the
    list of intent ids."""
    ids = []
    for suffix, direction in pairs:
        iid = f"market_intent:{suffix}"
        k.investor_market_intents.add_intent(
            _intent(
                market_intent_id=iid,
                investor_id=f"investor:{suffix}",
                security_id=security_id,
                intent_direction_label=direction,
            )
        )
        ids.append(iid)
    return ids


def test_builder_increase_interest_maps_to_increased_count():
    k = _kernel()
    ids = _seed_intents(k, [("a", "increase_interest")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.increased_interest_count == 1
    assert r.total_intent_count == 1


def test_builder_reduce_interest_maps_to_reduced_count():
    k = _kernel()
    ids = _seed_intents(k, [("a", "reduce_interest")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.reduced_interest_count == 1


def test_builder_hold_review_maps_to_neutral_count():
    k = _kernel()
    ids = _seed_intents(k, [("a", "hold_review")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.neutral_or_hold_review_count == 1


def test_builder_rebalance_review_maps_to_neutral_count():
    """Per v1.15.3 helper-rule docs: rebalance_review folds into
    the neutral_or_hold_review_count bucket."""
    k = _kernel()
    ids = _seed_intents(k, [("a", "rebalance_review")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.neutral_or_hold_review_count == 1


def test_builder_unknown_direction_maps_to_neutral_count():
    """Per v1.15.3 helper-rule docs: unknown direction folds into
    the neutral_or_hold_review_count bucket."""
    k = _kernel()
    ids = _seed_intents(k, [("a", "unknown")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.neutral_or_hold_review_count == 1


def test_builder_liquidity_watch_maps_to_liquidity_count():
    k = _kernel()
    ids = _seed_intents(k, [("a", "liquidity_watch")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.liquidity_watch_count == 1


def test_builder_risk_reduction_review_maps_to_risk_count():
    k = _kernel()
    ids = _seed_intents(k, [("a", "risk_reduction_review")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.risk_reduction_review_count == 1


def test_builder_engagement_linked_review_maps_to_engagement_count():
    k = _kernel()
    ids = _seed_intents(k, [("a", "engagement_linked_review")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.engagement_linked_review_count == 1


def test_builder_total_equals_sum_of_buckets():
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "reduce_interest"),
            ("c", "hold_review"),
            ("d", "liquidity_watch"),
            ("e", "risk_reduction_review"),
            ("f", "engagement_linked_review"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.total_intent_count == 6
    assert (
        r.increased_interest_count
        + r.reduced_interest_count
        + r.neutral_or_hold_review_count
        + r.liquidity_watch_count
        + r.risk_reduction_review_count
        + r.engagement_linked_review_count
        == r.total_intent_count
    )


# ---------------------------------------------------------------------------
# Builder — net_interest_label rules
# ---------------------------------------------------------------------------


def test_builder_no_intents_yields_insufficient_observations():
    k = _kernel()
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=(),
    )
    assert r.total_intent_count == 0
    assert r.net_interest_label == "insufficient_observations"
    assert r.concentration_label == "insufficient_observations"
    assert r.liquidity_interest_label == "unknown"


def test_builder_increased_interest_rule_dominates_neutral():
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "increase_interest"),
            ("c", "increase_interest"),
            ("d", "hold_review"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.net_interest_label == "increased_interest"


def test_builder_reduced_interest_rule_dominates_neutral():
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "reduce_interest"),
            ("b", "reduce_interest"),
            ("c", "reduce_interest"),
            ("d", "hold_review"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.net_interest_label == "reduced_interest"


def test_builder_mixed_rule_when_increased_and_reduced_close():
    """Both increase and reduce non-zero, equal counts, neutral
    bucket present too — mixed."""
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "reduce_interest"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.net_interest_label == "mixed"


def test_builder_balanced_rule_when_neutral_dominates():
    """When neutral is the largest bucket and increase/reduce are
    both zero, the result is balanced."""
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "hold_review"),
            ("b", "hold_review"),
            ("c", "hold_review"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.net_interest_label == "balanced"


# ---------------------------------------------------------------------------
# Builder — liquidity_interest_label rules
# ---------------------------------------------------------------------------


def test_builder_liquidity_low_when_no_liquidity_watch():
    k = _kernel()
    ids = _seed_intents(k, [("a", "increase_interest")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.liquidity_interest_label == "liquidity_attention_low"


def test_builder_liquidity_moderate_when_under_half():
    """1 liquidity_watch out of 4 intents → moderate."""
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "increase_interest"),
            ("c", "increase_interest"),
            ("d", "liquidity_watch"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.liquidity_interest_label == "liquidity_attention_moderate"


def test_builder_liquidity_high_when_dominates():
    """3 liquidity_watch out of 3 intents → high."""
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "liquidity_watch"),
            ("b", "liquidity_watch"),
            ("c", "liquidity_watch"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.liquidity_interest_label == "liquidity_attention_high"


# ---------------------------------------------------------------------------
# Builder — concentration_label rules
# ---------------------------------------------------------------------------


def test_builder_concentration_insufficient_for_total_lt_2():
    k = _kernel()
    ids = _seed_intents(k, [("a", "increase_interest")])
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.concentration_label == "insufficient_observations"


def test_builder_concentration_concentrated_for_single_bucket():
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "increase_interest"),
            ("c", "increase_interest"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.concentration_label == "concentrated"


def test_builder_concentration_moderately_for_two_or_three_buckets():
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "reduce_interest"),
            ("c", "hold_review"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.concentration_label == "moderately_concentrated"


def test_builder_concentration_dispersed_for_four_or_more_buckets():
    k = _kernel()
    ids = _seed_intents(
        k,
        [
            ("a", "increase_interest"),
            ("b", "reduce_interest"),
            ("c", "hold_review"),
            ("d", "liquidity_watch"),
        ],
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=tuple(ids),
    )
    assert r.concentration_label == "dispersed"


# ---------------------------------------------------------------------------
# Builder — mismatched / unresolved / no-global-scan
# ---------------------------------------------------------------------------


def test_builder_ignores_mismatched_security_id_and_records_count_in_metadata():
    """Intents whose security_id does not match the helper's
    security_id are ignored; metadata records the mismatch
    count."""
    k = _kernel()
    # Two intents on the target security plus one on a different
    # security.
    k.investor_market_intents.add_intent(
        _intent(
            market_intent_id="market_intent:on_target_a",
            security_id="security:target",
            intent_direction_label="increase_interest",
        )
    )
    k.investor_market_intents.add_intent(
        _intent(
            market_intent_id="market_intent:on_target_b",
            security_id="security:target",
            intent_direction_label="reduce_interest",
        )
    )
    k.investor_market_intents.add_intent(
        _intent(
            market_intent_id="market_intent:on_other",
            security_id="security:other",
            intent_direction_label="increase_interest",
        )
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:target",
        as_of_date="2026-03-31",
        source_market_intent_ids=(
            "market_intent:on_target_a",
            "market_intent:on_target_b",
            "market_intent:on_other",
        ),
    )
    assert r.total_intent_count == 2
    assert r.increased_interest_count == 1
    assert r.reduced_interest_count == 1
    assert r.metadata["mismatched_security_id_count"] == 1
    assert r.metadata["unresolved_market_intent_count"] == 0


def test_builder_ignores_unresolved_ids_and_records_count_in_metadata():
    k = _kernel()
    k.investor_market_intents.add_intent(
        _intent(
            market_intent_id="market_intent:resolved",
            security_id="security:target",
            intent_direction_label="increase_interest",
        )
    )
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:target",
        as_of_date="2026-03-31",
        source_market_intent_ids=(
            "market_intent:resolved",
            "market_intent:does_not_exist",
        ),
    )
    assert r.total_intent_count == 1
    assert r.metadata["mismatched_security_id_count"] == 0
    assert r.metadata["unresolved_market_intent_count"] == 1


def test_builder_does_not_scan_intents_globally():
    """The helper must read only the cited ids — never iterate
    the full intents book. We monkey-patch every list_* on the
    intents book to raise; if the helper calls any of them, the
    test fails."""
    k = _kernel()
    k.investor_market_intents.add_intent(
        _intent(
            market_intent_id="market_intent:cited",
            security_id="security:target",
            intent_direction_label="increase_interest",
        )
    )

    def _boom(*_a, **_kw):  # pragma: no cover - must not fire
        raise AssertionError(
            "helper performed a global scan via list_* / snapshot — forbidden"
        )

    book = k.investor_market_intents
    for method_name in dir(book):
        if method_name.startswith("list_") or method_name == "snapshot":
            setattr(book, method_name, _boom)

    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:target",
        as_of_date="2026-03-31",
        source_market_intent_ids=("market_intent:cited",),
    )
    assert r.total_intent_count == 1
    assert r.increased_interest_count == 1


def test_builder_default_id_is_deterministic():
    k = _kernel()
    r = build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=(),
    )
    assert r.aggregated_interest_id == (
        "aggregated_market_interest:venue:reference_exchange_a:"
        "security:reference_a:equity:line_1:2026-03-31"
    )


def test_builder_writes_one_ledger_record():
    k = _kernel()
    build_aggregated_market_interest(
        k,
        venue_id="venue:reference_exchange_a",
        security_id="security:reference_a:equity:line_1",
        as_of_date="2026-03-31",
        source_market_intent_ids=(),
    )
    matched = [
        rec
        for rec in k.ledger.records
        if rec.record_type
        is RecordType.AGGREGATED_MARKET_INTEREST_RECORDED
    ]
    assert len(matched) == 1


def test_builder_is_deterministic_across_fresh_kernels():
    """Same cited-intent content + same args → same labels and
    counts across two fresh kernels."""

    def build(kernel: WorldKernel) -> AggregatedMarketInterestRecord:
        kernel.investor_market_intents.add_intent(
            _intent(
                market_intent_id="market_intent:a",
                security_id="security:target",
                intent_direction_label="increase_interest",
            )
        )
        kernel.investor_market_intents.add_intent(
            _intent(
                market_intent_id="market_intent:b",
                security_id="security:target",
                intent_direction_label="reduce_interest",
            )
        )
        return build_aggregated_market_interest(
            kernel,
            venue_id="venue:reference_exchange_a",
            security_id="security:target",
            as_of_date="2026-03-31",
            source_market_intent_ids=(
                "market_intent:a",
                "market_intent:b",
            ),
        )

    k1 = _kernel()
    k2 = _kernel()
    r1 = build(k1)
    r2 = build(k2)
    assert r1.to_dict() == r2.to_dict()


# ---------------------------------------------------------------------------
# Jurisdiction-neutral identifier scan
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
    "target2", "fedwire", "chaps", "bojnet",
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
        assert re.search(pattern, text) is None, token


def test_module_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parent.parent
        / "world"
        / "market_interest.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
