"""
Tests for v1.15.2 InvestorMarketIntentRecord +
InvestorMarketIntentBook.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.market_intents import (
    DuplicateInvestorMarketIntentError,
    HORIZON_LABELS,
    INTENSITY_LABELS,
    INTENT_DIRECTION_LABELS,
    InvestorMarketIntentBook,
    InvestorMarketIntentRecord,
    STATUS_LABELS,
    UnknownInvestorMarketIntentError,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.securities import SAFE_INTENT_LABELS
from world.state import State


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _intent(
    *,
    market_intent_id: str = (
        "market_intent:investor_a:security_a:2026-03-31"
    ),
    investor_id: str = "investor:reference_a",
    security_id: str = "security:reference_a:equity:line_1",
    as_of_date: str = "2026-03-31",
    intent_direction_label: str = "increase_interest",
    intensity_label: str = "moderate",
    horizon_label: str = "near_term",
    status: str = "active",
    visibility: str = "internal_only",
    confidence: float = 0.5,
    evidence_investor_intent_ids: tuple[str, ...] = (),
    evidence_valuation_ids: tuple[str, ...] = (),
    evidence_market_environment_state_ids: tuple[str, ...] = (),
    evidence_firm_state_ids: tuple[str, ...] = (),
    evidence_security_ids: tuple[str, ...] = (),
    evidence_venue_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> InvestorMarketIntentRecord:
    return InvestorMarketIntentRecord(
        market_intent_id=market_intent_id,
        investor_id=investor_id,
        security_id=security_id,
        as_of_date=as_of_date,
        intent_direction_label=intent_direction_label,
        intensity_label=intensity_label,
        horizon_label=horizon_label,
        status=status,
        visibility=visibility,
        confidence=confidence,
        evidence_investor_intent_ids=evidence_investor_intent_ids,
        evidence_valuation_ids=evidence_valuation_ids,
        evidence_market_environment_state_ids=evidence_market_environment_state_ids,
        evidence_firm_state_ids=evidence_firm_state_ids,
        evidence_security_ids=evidence_security_ids,
        evidence_venue_ids=evidence_venue_ids,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Required-string validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"market_intent_id": ""},
        {"investor_id": ""},
        {"security_id": ""},
        {"as_of_date": ""},
        {"visibility": ""},
    ],
)
def test_intent_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _intent(**kwargs)


def test_intent_coerces_date_to_iso_string():
    i = _intent(as_of_date=date(2026, 3, 31))
    assert i.as_of_date == "2026-03-31"


def test_intent_is_frozen():
    i = _intent()
    with pytest.raises(Exception):
        i.market_intent_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Confidence (bounded, bool-rejecting)
# ---------------------------------------------------------------------------


def test_intent_rejects_bool_confidence():
    with pytest.raises(ValueError):
        _intent(confidence=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_intent_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValueError):
        _intent(confidence=bad)


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_intent_accepts_in_range_confidence(good):
    i = _intent(confidence=good)
    assert i.confidence == float(good)


def test_intent_rejects_non_numeric_confidence():
    with pytest.raises(ValueError):
        _intent(confidence="0.5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Evidence-id tuple validation
# ---------------------------------------------------------------------------


def test_intent_rejects_empty_strings_in_evidence_tuples():
    for kwarg in (
        "evidence_investor_intent_ids",
        "evidence_valuation_ids",
        "evidence_market_environment_state_ids",
        "evidence_firm_state_ids",
        "evidence_security_ids",
        "evidence_venue_ids",
    ):
        with pytest.raises(ValueError):
            _intent(**{kwarg: ("",)})


def test_intent_to_dict_round_trips():
    i = _intent(
        evidence_investor_intent_ids=(
            "investor_intent_signal:investor_a:firm_a:2026Q3",
        ),
        evidence_valuation_ids=(
            "valuation:reference_lite:investor_a:firm_a:2026-03-31",
        ),
        evidence_market_environment_state_ids=(
            "market_environment_state:2026Q3",
        ),
        evidence_firm_state_ids=(
            "firm_financial_state:firm_a:2026Q3",
        ),
        evidence_security_ids=(
            "security:reference_a:equity:line_1",
        ),
        evidence_venue_ids=("venue:reference_exchange_a",),
        metadata={"note": "synthetic"},
    )
    out = i.to_dict()
    assert out["evidence_investor_intent_ids"] == [
        "investor_intent_signal:investor_a:firm_a:2026Q3"
    ]
    assert out["evidence_valuation_ids"] == [
        "valuation:reference_lite:investor_a:firm_a:2026-03-31"
    ]
    assert out["evidence_market_environment_state_ids"] == [
        "market_environment_state:2026Q3"
    ]
    assert out["evidence_firm_state_ids"] == [
        "firm_financial_state:firm_a:2026Q3"
    ]
    assert out["evidence_security_ids"] == [
        "security:reference_a:equity:line_1"
    ]
    assert out["evidence_venue_ids"] == ["venue:reference_exchange_a"]
    assert out["metadata"] == {"note": "synthetic"}


# ---------------------------------------------------------------------------
# Closed-set acceptance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(INTENT_DIRECTION_LABELS))
def test_intent_direction_labels_accepted(label):
    i = _intent(intent_direction_label=label)
    assert i.intent_direction_label == label


@pytest.mark.parametrize("label", sorted(INTENSITY_LABELS))
def test_intensity_labels_accepted(label):
    i = _intent(intensity_label=label)
    assert i.intensity_label == label


@pytest.mark.parametrize("label", sorted(HORIZON_LABELS))
def test_horizon_labels_accepted(label):
    i = _intent(horizon_label=label)
    assert i.horizon_label == label


@pytest.mark.parametrize("label", sorted(STATUS_LABELS))
def test_status_labels_accepted(label):
    i = _intent(status=label)
    assert i.status == label


# ---------------------------------------------------------------------------
# Closed-set rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "intent_direction_label",
        "intensity_label",
        "horizon_label",
        "status",
    ],
)
def test_label_field_rejects_out_of_set_value(field_name):
    with pytest.raises(ValueError):
        _intent(**{field_name: "not_a_real_label"})


# ---------------------------------------------------------------------------
# Forbidden trading verbs — rejected by closed-set membership
# ---------------------------------------------------------------------------


_FORBIDDEN_INTENT_VERBS = (
    "buy",
    "sell",
    "order",
    "target_weight",
    "overweight",
    "underweight",
    "execution",
)


@pytest.mark.parametrize("forbidden", _FORBIDDEN_INTENT_VERBS)
def test_intent_direction_rejects_forbidden_trading_verb(forbidden):
    """v1.15.2 explicitly rejects every forbidden trading verb on
    ``intent_direction_label``. The vocabulary models *market
    interest*, never *order instruction*."""
    with pytest.raises(ValueError):
        _intent(intent_direction_label=forbidden)


# ---------------------------------------------------------------------------
# Vocabulary-set pinning
# ---------------------------------------------------------------------------


def test_intent_direction_set_extends_safe_intent_labels_with_unknown():
    """The v1.15.2 ``intent_direction_label`` vocabulary is the
    v1.15.1 ``SAFE_INTENT_LABELS`` set plus ``unknown``. This
    pin is intentional — it keeps the venue's
    ``supported_intent_labels`` and the per-investor record's
    ``intent_direction_label`` aligned (with ``unknown`` allowed
    only on the per-record direction)."""
    assert INTENT_DIRECTION_LABELS == SAFE_INTENT_LABELS | {"unknown"}


def test_pinned_intent_direction_label_set_is_exact():
    assert INTENT_DIRECTION_LABELS == frozenset(
        {
            "increase_interest",
            "reduce_interest",
            "hold_review",
            "liquidity_watch",
            "rebalance_review",
            "risk_reduction_review",
            "engagement_linked_review",
            "unknown",
        }
    )


def test_pinned_intensity_label_set_is_exact():
    assert INTENSITY_LABELS == frozenset(
        {"low", "moderate", "elevated", "high", "unknown"}
    )


def test_pinned_horizon_label_set_is_exact():
    assert HORIZON_LABELS == frozenset(
        {
            "intraperiod",
            "near_term",
            "medium_term",
            "long_term",
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
    "target_weight",
    "overweight",
    "underweight",
    "expected_return",
    "target_price",
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
    "price",
}


def test_intent_record_has_no_anti_fields():
    field_names = {f.name for f in dataclass_fields(InvestorMarketIntentRecord)}
    leaked = field_names & _FORBIDDEN_FIELDS
    assert not leaked


# ---------------------------------------------------------------------------
# Book — CRUD
# ---------------------------------------------------------------------------


def test_book_add_and_get_intent():
    book = InvestorMarketIntentBook()
    i = _intent()
    book.add_intent(i)
    assert book.get_intent(i.market_intent_id) is i


def test_book_get_unknown_intent_raises():
    book = InvestorMarketIntentBook()
    with pytest.raises(UnknownInvestorMarketIntentError):
        book.get_intent("market_intent:missing")
    with pytest.raises(KeyError):
        book.get_intent("market_intent:missing")


def test_book_duplicate_market_intent_id_rejected():
    book = InvestorMarketIntentBook()
    book.add_intent(_intent())
    with pytest.raises(DuplicateInvestorMarketIntentError):
        book.add_intent(_intent())


def test_book_list_intents_returns_all():
    book = InvestorMarketIntentBook()
    book.add_intent(_intent(market_intent_id="market_intent:a"))
    book.add_intent(_intent(market_intent_id="market_intent:b"))
    assert len(book.list_intents()) == 2


def test_book_list_by_investor():
    book = InvestorMarketIntentBook()
    book.add_intent(
        _intent(
            market_intent_id="market_intent:a", investor_id="investor:p1"
        )
    )
    book.add_intent(
        _intent(
            market_intent_id="market_intent:b", investor_id="investor:p2"
        )
    )
    out = book.list_by_investor("investor:p1")
    assert len(out) == 1
    assert out[0].investor_id == "investor:p1"


def test_book_list_by_security():
    book = InvestorMarketIntentBook()
    book.add_intent(
        _intent(
            market_intent_id="market_intent:a", security_id="security:a"
        )
    )
    book.add_intent(
        _intent(
            market_intent_id="market_intent:b", security_id="security:b"
        )
    )
    assert len(book.list_by_security("security:b")) == 1


def test_book_list_by_intent_direction():
    book = InvestorMarketIntentBook()
    book.add_intent(
        _intent(
            market_intent_id="market_intent:a",
            intent_direction_label="increase_interest",
        )
    )
    book.add_intent(
        _intent(
            market_intent_id="market_intent:b",
            intent_direction_label="reduce_interest",
        )
    )
    assert len(book.list_by_intent_direction("reduce_interest")) == 1


def test_book_list_by_intensity():
    book = InvestorMarketIntentBook()
    book.add_intent(
        _intent(market_intent_id="market_intent:a", intensity_label="low")
    )
    book.add_intent(
        _intent(market_intent_id="market_intent:b", intensity_label="high")
    )
    assert len(book.list_by_intensity("high")) == 1


def test_book_list_by_horizon():
    book = InvestorMarketIntentBook()
    book.add_intent(
        _intent(market_intent_id="market_intent:a", horizon_label="near_term")
    )
    book.add_intent(
        _intent(
            market_intent_id="market_intent:b", horizon_label="long_term"
        )
    )
    assert len(book.list_by_horizon("long_term")) == 1


def test_book_list_by_status():
    book = InvestorMarketIntentBook()
    book.add_intent(_intent(market_intent_id="market_intent:a", status="active"))
    book.add_intent(
        _intent(market_intent_id="market_intent:b", status="superseded")
    )
    assert len(book.list_by_status("superseded")) == 1


def test_book_list_by_date():
    book = InvestorMarketIntentBook()
    book.add_intent(
        _intent(
            market_intent_id="market_intent:a", as_of_date="2026-03-31"
        )
    )
    book.add_intent(
        _intent(
            market_intent_id="market_intent:b", as_of_date="2026-04-30"
        )
    )
    assert len(book.list_by_date("2026-04-30")) == 1


def test_book_snapshot_is_deterministic_and_sorted():
    book = InvestorMarketIntentBook()
    book.add_intent(_intent(market_intent_id="market_intent:b"))
    book.add_intent(_intent(market_intent_id="market_intent:a"))
    snap = book.snapshot()
    assert snap["intent_count"] == 2
    assert [i["market_intent_id"] for i in snap["intents"]] == [
        "market_intent:a",
        "market_intent:b",
    ]
    assert book.snapshot() == snap


# ---------------------------------------------------------------------------
# Plain-id cross-references — accepted as data, not validated
# ---------------------------------------------------------------------------


def test_can_cite_listed_security_id_as_plain_id():
    book = InvestorMarketIntentBook()
    i = _intent(
        evidence_security_ids=(
            "security:reference_a:equity:line_1",
            "security:reference_a:corporate_bond:line_1",
        ),
    )
    book.add_intent(i)
    out = book.get_intent(i.market_intent_id)
    assert out.evidence_security_ids == (
        "security:reference_a:equity:line_1",
        "security:reference_a:corporate_bond:line_1",
    )


def test_can_cite_market_venue_id_as_plain_id():
    book = InvestorMarketIntentBook()
    i = _intent(
        evidence_venue_ids=(
            "venue:reference_exchange_a",
            "venue:reference_otc_network_a",
        ),
    )
    book.add_intent(i)
    out = book.get_intent(i.market_intent_id)
    assert out.evidence_venue_ids == (
        "venue:reference_exchange_a",
        "venue:reference_otc_network_a",
    )


def test_can_cite_investor_intent_valuation_and_environment_ids_as_plain_ids():
    book = InvestorMarketIntentBook()
    i = _intent(
        evidence_investor_intent_ids=(
            "investor_intent_signal:investor_a:firm_a:2026Q3",
        ),
        evidence_valuation_ids=(
            "valuation:reference_lite:investor_a:firm_a:2026-03-31",
        ),
        evidence_market_environment_state_ids=(
            "market_environment_state:2026Q3",
        ),
    )
    book.add_intent(i)
    out = book.get_intent(i.market_intent_id)
    assert out.evidence_investor_intent_ids == (
        "investor_intent_signal:investor_a:firm_a:2026Q3",
    )
    assert out.evidence_valuation_ids == (
        "valuation:reference_lite:investor_a:firm_a:2026-03-31",
    )
    assert out.evidence_market_environment_state_ids == (
        "market_environment_state:2026Q3",
    )


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    assert (
        RecordType.INVESTOR_MARKET_INTENT_RECORDED.value
        == "investor_market_intent_recorded"
    )


def test_add_intent_writes_exactly_one_ledger_record():
    ledger = Ledger()
    book = InvestorMarketIntentBook(ledger=ledger)
    book.add_intent(_intent())
    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert rec.record_type is RecordType.INVESTOR_MARKET_INTENT_RECORDED
    assert rec.space_id == "investor_market_intents"


def test_duplicate_add_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = InvestorMarketIntentBook(ledger=ledger)
    book.add_intent(_intent())
    with pytest.raises(DuplicateInvestorMarketIntentError):
        book.add_intent(_intent())
    assert len(ledger.records) == 1


def test_ledger_payload_contains_label_fields():
    ledger = Ledger()
    book = InvestorMarketIntentBook(ledger=ledger)
    book.add_intent(_intent())
    rec = ledger.records[0]
    assert rec.payload["intent_direction_label"] == "increase_interest"
    assert rec.payload["intensity_label"] == "moderate"
    assert rec.payload["horizon_label"] == "near_term"
    assert rec.payload["status"] == "active"


def test_ledger_payload_carries_no_anti_field_keys():
    ledger = Ledger()
    book = InvestorMarketIntentBook(ledger=ledger)
    book.add_intent(_intent())
    rec = ledger.records[0]
    leaked = set(rec.payload.keys()) & _FORBIDDEN_FIELDS
    assert not leaked


def test_ledger_emits_no_forbidden_event_types():
    ledger = Ledger()
    book = InvestorMarketIntentBook(ledger=ledger)
    book.add_intent(_intent())
    types = {rec.record_type for rec in ledger.records}
    assert types == {RecordType.INVESTOR_MARKET_INTENT_RECORDED}


def test_book_without_ledger_does_not_raise():
    book = InvestorMarketIntentBook()
    book.add_intent(_intent())


def test_ledger_record_routes_investor_to_security():
    """The ``source`` field carries the investor id; the
    ``target`` field carries the security id. This makes the
    ledger graph readable as 'investor X expressed market intent
    toward security Y'."""
    ledger = Ledger()
    book = InvestorMarketIntentBook(ledger=ledger)
    book.add_intent(_intent())
    rec = ledger.records[0]
    assert rec.source == "investor:reference_a"
    assert rec.target == "security:reference_a:equity:line_1"


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_investor_market_intents_book():
    k = _kernel()
    assert isinstance(k.investor_market_intents, InvestorMarketIntentBook)
    assert k.investor_market_intents.ledger is k.ledger
    assert k.investor_market_intents.clock is k.clock


def test_kernel_simulation_date_uses_clock_for_intent():
    k = _kernel()
    k.investor_market_intents.add_intent(_intent())
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
    }
    k.investor_market_intents.add_intent(_intent())
    for name, before in snaps_before.items():
        assert getattr(k, name).snapshot() == before, name


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
        / "market_intents.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
