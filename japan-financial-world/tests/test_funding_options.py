"""
Tests for v1.14.2 FundingOptionCandidate +
FundingOptionCandidateBook.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.clock import Clock
from world.funding_options import (
    ACCESSIBILITY_LABELS,
    DuplicateFundingOptionCandidateError,
    FundingOptionCandidate,
    FundingOptionCandidateBook,
    INSTRUMENT_CLASS_LABELS,
    MARKET_FIT_LABELS,
    MATURITY_BAND_LABELS,
    OPTION_TYPE_LABELS,
    SENIORITY_LABELS,
    URGENCY_FIT_LABELS,
    UnknownFundingOptionCandidateError,
)
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _candidate(
    *,
    funding_option_id: str = "funding_option:reference_a:bank_loan:2026-03-31",
    firm_id: str = "firm:reference_a",
    as_of_date: str = "2026-03-31",
    option_type_label: str = "bank_loan_candidate",
    instrument_class_label: str = "loan",
    maturity_band_label: str = "medium_term",
    seniority_label: str = "senior",
    accessibility_label: str = "accessible",
    urgency_fit_label: str = "near_term",
    market_fit_label: str = "supportive",
    status: str = "candidate",
    visibility: str = "internal_only",
    confidence: float = 0.5,
    source_need_ids: tuple[str, ...] = (),
    source_market_environment_state_ids: tuple[str, ...] = (),
    source_interbank_liquidity_state_ids: tuple[str, ...] = (),
    source_firm_state_ids: tuple[str, ...] = (),
    source_bank_credit_review_signal_ids: tuple[str, ...] = (),
    source_investor_intent_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> FundingOptionCandidate:
    return FundingOptionCandidate(
        funding_option_id=funding_option_id,
        firm_id=firm_id,
        as_of_date=as_of_date,
        option_type_label=option_type_label,
        instrument_class_label=instrument_class_label,
        maturity_band_label=maturity_band_label,
        seniority_label=seniority_label,
        accessibility_label=accessibility_label,
        urgency_fit_label=urgency_fit_label,
        market_fit_label=market_fit_label,
        status=status,
        visibility=visibility,
        confidence=confidence,
        source_need_ids=source_need_ids,
        source_market_environment_state_ids=source_market_environment_state_ids,
        source_interbank_liquidity_state_ids=source_interbank_liquidity_state_ids,
        source_firm_state_ids=source_firm_state_ids,
        source_bank_credit_review_signal_ids=source_bank_credit_review_signal_ids,
        source_investor_intent_ids=source_investor_intent_ids,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Required-string validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"funding_option_id": ""},
        {"firm_id": ""},
        {"as_of_date": ""},
        {"status": ""},
        {"visibility": ""},
    ],
)
def test_candidate_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _candidate(**kwargs)


def test_candidate_coerces_date_to_iso_string():
    c = _candidate(as_of_date=date(2026, 3, 31))
    assert c.as_of_date == "2026-03-31"


def test_candidate_is_frozen():
    c = _candidate()
    with pytest.raises(Exception):
        c.funding_option_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Confidence (bounded, bool-rejecting)
# ---------------------------------------------------------------------------


def test_candidate_rejects_bool_confidence():
    with pytest.raises(ValueError):
        _candidate(confidence=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_candidate_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValueError):
        _candidate(confidence=bad)


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_candidate_accepts_in_range_confidence(good):
    c = _candidate(confidence=good)
    assert c.confidence == float(good)


def test_candidate_rejects_non_numeric_confidence():
    with pytest.raises(ValueError):
        _candidate(confidence="0.5")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Source-id tuple validation
# ---------------------------------------------------------------------------


def test_candidate_rejects_empty_strings_in_source_tuples():
    for kwarg in (
        "source_need_ids",
        "source_market_environment_state_ids",
        "source_interbank_liquidity_state_ids",
        "source_firm_state_ids",
        "source_bank_credit_review_signal_ids",
        "source_investor_intent_ids",
    ):
        with pytest.raises(ValueError):
            _candidate(**{kwarg: ("",)})


def test_candidate_to_dict_round_trips():
    c = _candidate(
        source_need_ids=("corporate_financing_need:reference_a:2026-03-31",),
        source_market_environment_state_ids=("market_environment_state:Q3",),
        source_interbank_liquidity_state_ids=(
            "interbank_liquidity_state:bank_c:2026-03-31",
        ),
        source_firm_state_ids=("firm_financial_state:reference_a:2026-03-31",),
        source_bank_credit_review_signal_ids=(
            "bank_credit_review_signal:bank_c:reference_a:Q3",
        ),
        source_investor_intent_ids=(
            "investor_intent_signal:investor_a:reference_a:Q3",
        ),
        metadata={"note": "synthetic"},
    )
    out = c.to_dict()
    assert out["source_need_ids"] == [
        "corporate_financing_need:reference_a:2026-03-31"
    ]
    assert out["source_market_environment_state_ids"] == [
        "market_environment_state:Q3"
    ]
    assert out["source_interbank_liquidity_state_ids"] == [
        "interbank_liquidity_state:bank_c:2026-03-31"
    ]
    assert out["source_firm_state_ids"] == [
        "firm_financial_state:reference_a:2026-03-31"
    ]
    assert out["source_bank_credit_review_signal_ids"] == [
        "bank_credit_review_signal:bank_c:reference_a:Q3"
    ]
    assert out["source_investor_intent_ids"] == [
        "investor_intent_signal:investor_a:reference_a:Q3"
    ]
    assert out["metadata"] == {"note": "synthetic"}


# ---------------------------------------------------------------------------
# Closed-set label vocabularies — accept every listed value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("label", sorted(OPTION_TYPE_LABELS))
def test_option_type_labels_accepted(label):
    c = _candidate(option_type_label=label)
    assert c.option_type_label == label


@pytest.mark.parametrize("label", sorted(INSTRUMENT_CLASS_LABELS))
def test_instrument_class_labels_accepted(label):
    c = _candidate(instrument_class_label=label)
    assert c.instrument_class_label == label


@pytest.mark.parametrize("label", sorted(MATURITY_BAND_LABELS))
def test_maturity_band_labels_accepted(label):
    c = _candidate(maturity_band_label=label)
    assert c.maturity_band_label == label


@pytest.mark.parametrize("label", sorted(SENIORITY_LABELS))
def test_seniority_labels_accepted(label):
    c = _candidate(seniority_label=label)
    assert c.seniority_label == label


@pytest.mark.parametrize("label", sorted(ACCESSIBILITY_LABELS))
def test_accessibility_labels_accepted(label):
    c = _candidate(accessibility_label=label)
    assert c.accessibility_label == label


@pytest.mark.parametrize("label", sorted(URGENCY_FIT_LABELS))
def test_urgency_fit_labels_accepted(label):
    c = _candidate(urgency_fit_label=label)
    assert c.urgency_fit_label == label


@pytest.mark.parametrize("label", sorted(MARKET_FIT_LABELS))
def test_market_fit_labels_accepted(label):
    c = _candidate(market_fit_label=label)
    assert c.market_fit_label == label


# ---------------------------------------------------------------------------
# Closed-set label vocabularies — reject out-of-set values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name",
    [
        "option_type_label",
        "instrument_class_label",
        "maturity_band_label",
        "seniority_label",
        "accessibility_label",
        "urgency_fit_label",
        "market_fit_label",
    ],
)
def test_label_field_rejects_out_of_set_value(field_name):
    with pytest.raises(ValueError):
        _candidate(**{field_name: "not_a_real_label"})


def test_pinned_option_type_label_set_is_exact():
    assert OPTION_TYPE_LABELS == frozenset(
        {
            "bank_loan_candidate",
            "bond_issuance_candidate",
            "equity_issuance_candidate",
            "internal_cash_candidate",
            "asset_sale_candidate",
            "hybrid_security_candidate",
            "unknown",
        }
    )


def test_pinned_instrument_class_label_set_is_exact():
    assert INSTRUMENT_CLASS_LABELS == frozenset(
        {
            "loan",
            "bond",
            "equity",
            "internal_funding",
            "asset_disposal",
            "hybrid",
            "unknown",
        }
    )


def test_pinned_maturity_band_label_set_is_exact():
    assert MATURITY_BAND_LABELS == frozenset(
        {
            "short_term",
            "medium_term",
            "long_term",
            "perpetual_or_equity_like",
            "unknown",
        }
    )


def test_pinned_seniority_label_set_is_exact():
    assert SENIORITY_LABELS == frozenset(
        {
            "senior",
            "subordinated",
            "unsecured",
            "secured",
            "equity_like",
            "not_applicable",
            "unknown",
        }
    )


def test_pinned_accessibility_label_set_is_exact():
    assert ACCESSIBILITY_LABELS == frozenset(
        {
            "accessible",
            "selective",
            "constrained",
            "unavailable",
            "unknown",
        }
    )


def test_pinned_urgency_fit_label_set_is_exact():
    assert URGENCY_FIT_LABELS == frozenset(
        {
            "immediate",
            "near_term",
            "medium_term",
            "strategic",
            "unknown",
        }
    )


def test_pinned_market_fit_label_set_is_exact():
    assert MARKET_FIT_LABELS == frozenset(
        {
            "supportive",
            "mixed",
            "restrictive",
            "unknown",
        }
    )


# ---------------------------------------------------------------------------
# Anti-fields — must NOT appear on dataclass or ledger payload
# ---------------------------------------------------------------------------


_FORBIDDEN_FIELDS = {
    "rate",
    "spread",
    "fee",
    "coupon",
    "price",
    "offering_price",
    "allocation",
    "underwriting",
    "syndication",
    "commitment",
    "approval",
    "executed",
    "take_up_probability",
    "expected_return",
    "recommendation",
    "investment_advice",
    "real_data_value",
    # also pin fields the surrounding v1.14.x family forbids
    "amount",
    "loan_amount",
    "interest_rate",
    "coupon_rate",
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
    "order",
    "trade",
    "forecast_value",
    "actual_value",
}


def test_candidate_has_no_anti_fields():
    field_names = {
        f.name for f in dataclass_fields(FundingOptionCandidate)
    }
    leaked = field_names & _FORBIDDEN_FIELDS
    assert not leaked


# ---------------------------------------------------------------------------
# Book — CRUD
# ---------------------------------------------------------------------------


def test_book_add_and_get_candidate():
    book = FundingOptionCandidateBook()
    c = _candidate()
    book.add_candidate(c)
    assert book.get_candidate(c.funding_option_id) is c


def test_book_get_unknown_candidate_raises():
    book = FundingOptionCandidateBook()
    with pytest.raises(UnknownFundingOptionCandidateError):
        book.get_candidate("funding_option:missing")
    with pytest.raises(KeyError):
        book.get_candidate("funding_option:missing")


def test_book_duplicate_funding_option_id_rejected():
    book = FundingOptionCandidateBook()
    book.add_candidate(_candidate())
    with pytest.raises(DuplicateFundingOptionCandidateError):
        book.add_candidate(_candidate())


def test_book_list_candidates_returns_all():
    book = FundingOptionCandidateBook()
    book.add_candidate(_candidate(funding_option_id="funding_option:a"))
    book.add_candidate(_candidate(funding_option_id="funding_option:b"))
    assert len(book.list_candidates()) == 2


def test_book_list_by_firm():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(funding_option_id="funding_option:a", firm_id="firm:p1")
    )
    book.add_candidate(
        _candidate(funding_option_id="funding_option:b", firm_id="firm:p2")
    )
    out = book.list_by_firm("firm:p1")
    assert len(out) == 1
    assert out[0].firm_id == "firm:p1"


def test_book_list_by_option_type():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:a",
            option_type_label="bank_loan_candidate",
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:b",
            option_type_label="bond_issuance_candidate",
        )
    )
    assert len(book.list_by_option_type("bond_issuance_candidate")) == 1


def test_book_list_by_instrument_class():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:a",
            instrument_class_label="loan",
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:b",
            instrument_class_label="bond",
        )
    )
    assert len(book.list_by_instrument_class("bond")) == 1


def test_book_list_by_accessibility():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:a",
            accessibility_label="accessible",
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:b",
            accessibility_label="constrained",
        )
    )
    assert len(book.list_by_accessibility("constrained")) == 1


def test_book_list_by_status():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:a", status="candidate"
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:b", status="superseded"
        )
    )
    assert len(book.list_by_status("superseded")) == 1


def test_book_list_by_date():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:a",
            as_of_date="2026-03-31",
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:b",
            as_of_date="2026-04-30",
        )
    )
    assert len(book.list_by_date("2026-04-30")) == 1


def test_book_list_by_need():
    book = FundingOptionCandidateBook()
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:a",
            source_need_ids=("corporate_financing_need:n1",),
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:b",
            source_need_ids=(
                "corporate_financing_need:n1",
                "corporate_financing_need:n2",
            ),
        )
    )
    book.add_candidate(
        _candidate(
            funding_option_id="funding_option:c",
            source_need_ids=("corporate_financing_need:n3",),
        )
    )
    out = book.list_by_need("corporate_financing_need:n1")
    assert {c.funding_option_id for c in out} == {
        "funding_option:a",
        "funding_option:b",
    }
    assert (
        len(book.list_by_need("corporate_financing_need:never_referenced"))
        == 0
    )


def test_book_snapshot_is_deterministic_and_sorted():
    book = FundingOptionCandidateBook()
    book.add_candidate(_candidate(funding_option_id="funding_option:b"))
    book.add_candidate(_candidate(funding_option_id="funding_option:a"))
    snap = book.snapshot()
    assert snap["candidate_count"] == 2
    assert [c["funding_option_id"] for c in snap["candidates"]] == [
        "funding_option:a",
        "funding_option:b",
    ]
    # Repeated snapshots are byte-identical.
    assert book.snapshot() == snap


# ---------------------------------------------------------------------------
# Plain-id cross-references — accepted as data, not validated
# ---------------------------------------------------------------------------


def test_can_cite_corporate_financing_need_ids_as_plain_ids():
    book = FundingOptionCandidateBook()
    c = _candidate(
        source_need_ids=(
            "corporate_financing_need:reference_a:2026-03-31",
            "corporate_financing_need:reference_a:2026-04-30",
        ),
    )
    book.add_candidate(c)
    out = book.get_candidate(c.funding_option_id)
    assert out.source_need_ids == (
        "corporate_financing_need:reference_a:2026-03-31",
        "corporate_financing_need:reference_a:2026-04-30",
    )


def test_can_cite_market_environment_and_interbank_liquidity_ids_as_plain_ids():
    book = FundingOptionCandidateBook()
    c = _candidate(
        source_market_environment_state_ids=(
            "market_environment_state:2026Q3",
        ),
        source_interbank_liquidity_state_ids=(
            "interbank_liquidity_state:bank_c:2026-03-31",
        ),
    )
    book.add_candidate(c)
    out = book.get_candidate(c.funding_option_id)
    assert out.source_market_environment_state_ids == (
        "market_environment_state:2026Q3",
    )
    assert out.source_interbank_liquidity_state_ids == (
        "interbank_liquidity_state:bank_c:2026-03-31",
    )


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    assert (
        RecordType.FUNDING_OPTION_CANDIDATE_RECORDED.value
        == "funding_option_candidate_recorded"
    )


def test_add_candidate_writes_exactly_one_ledger_record():
    ledger = Ledger()
    book = FundingOptionCandidateBook(ledger=ledger)
    book.add_candidate(_candidate())
    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert rec.record_type is RecordType.FUNDING_OPTION_CANDIDATE_RECORDED
    assert rec.space_id == "funding_options"


def test_duplicate_add_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = FundingOptionCandidateBook(ledger=ledger)
    book.add_candidate(_candidate())
    with pytest.raises(DuplicateFundingOptionCandidateError):
        book.add_candidate(_candidate())
    assert len(ledger.records) == 1


def test_ledger_payload_contains_label_fields():
    ledger = Ledger()
    book = FundingOptionCandidateBook(ledger=ledger)
    book.add_candidate(_candidate())
    rec = ledger.records[0]
    assert rec.payload["option_type_label"] == "bank_loan_candidate"
    assert rec.payload["instrument_class_label"] == "loan"
    assert rec.payload["maturity_band_label"] == "medium_term"
    assert rec.payload["seniority_label"] == "senior"
    assert rec.payload["accessibility_label"] == "accessible"
    assert rec.payload["urgency_fit_label"] == "near_term"
    assert rec.payload["market_fit_label"] == "supportive"


def test_ledger_payload_carries_no_anti_field_keys():
    ledger = Ledger()
    book = FundingOptionCandidateBook(ledger=ledger)
    book.add_candidate(_candidate())
    rec = ledger.records[0]
    leaked = set(rec.payload.keys()) & _FORBIDDEN_FIELDS
    assert not leaked


def test_ledger_emits_no_forbidden_event_types():
    ledger = Ledger()
    book = FundingOptionCandidateBook(ledger=ledger)
    book.add_candidate(_candidate())
    types = {rec.record_type for rec in ledger.records}
    assert types == {RecordType.FUNDING_OPTION_CANDIDATE_RECORDED}


def test_book_without_ledger_does_not_raise():
    book = FundingOptionCandidateBook()
    book.add_candidate(_candidate())


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_funding_options_book():
    k = _kernel()
    assert isinstance(k.funding_options, FundingOptionCandidateBook)
    assert k.funding_options.ledger is k.ledger
    assert k.funding_options.clock is k.clock


def test_kernel_simulation_date_uses_clock_for_candidate():
    k = _kernel()
    k.funding_options.add_candidate(_candidate())
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
    }
    k.funding_options.add_candidate(_candidate())
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
        / "funding_options.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
