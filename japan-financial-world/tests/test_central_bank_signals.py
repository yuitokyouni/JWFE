"""
Tests for v1.13.4 CentralBankOperationSignalRecord +
CollateralEligibilitySignalRecord + CentralBankSignalBook.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.central_bank_signals import (
    CentralBankOperationSignalRecord,
    CentralBankSignalBook,
    CollateralEligibilitySignalRecord,
    DuplicateCentralBankOperationSignalError,
    DuplicateCollateralEligibilitySignalError,
    UnknownCentralBankOperationSignalError,
    UnknownCollateralEligibilitySignalError,
)
from world.clock import Clock
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


def _operation(
    *,
    operation_signal_id: str = "central_bank_operation_signal:reference_a",
    authority_id: str = "monetary_authority:reference_alpha",
    as_of_date: str = "2026-03-31",
    operation_label: str = "open_market_operation",
    direction_label: str = "inject",
    horizon_label: str = "short_term",
    status: str = "active",
    visibility: str = "public",
    confidence: float = 0.5,
    source_settlement_account_ids: tuple[str, ...] = (),
    source_interbank_liquidity_state_ids: tuple[str, ...] = (),
    source_market_environment_state_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> CentralBankOperationSignalRecord:
    return CentralBankOperationSignalRecord(
        operation_signal_id=operation_signal_id,
        authority_id=authority_id,
        as_of_date=as_of_date,
        operation_label=operation_label,
        direction_label=direction_label,
        horizon_label=horizon_label,
        status=status,
        visibility=visibility,
        confidence=confidence,
        source_settlement_account_ids=source_settlement_account_ids,
        source_interbank_liquidity_state_ids=source_interbank_liquidity_state_ids,
        source_market_environment_state_ids=source_market_environment_state_ids,
        metadata=metadata or {},
    )


def _eligibility(
    *,
    eligibility_signal_id: str = "collateral_eligibility_signal:reference_a",
    authority_id: str = "monetary_authority:reference_alpha",
    collateral_class_label: str = "reference_government_paper",
    as_of_date: str = "2026-03-31",
    eligibility_label: str = "eligible",
    haircut_tier_label: str = "tier_low",
    status: str = "active",
    visibility: str = "public",
    confidence: float = 0.5,
    source_market_environment_state_ids: tuple[str, ...] = (),
    source_interbank_liquidity_state_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> CollateralEligibilitySignalRecord:
    return CollateralEligibilitySignalRecord(
        eligibility_signal_id=eligibility_signal_id,
        authority_id=authority_id,
        collateral_class_label=collateral_class_label,
        as_of_date=as_of_date,
        eligibility_label=eligibility_label,
        haircut_tier_label=haircut_tier_label,
        status=status,
        visibility=visibility,
        confidence=confidence,
        source_market_environment_state_ids=source_market_environment_state_ids,
        source_interbank_liquidity_state_ids=source_interbank_liquidity_state_ids,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Operation record validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"operation_signal_id": ""},
        {"authority_id": ""},
        {"as_of_date": ""},
        {"operation_label": ""},
        {"direction_label": ""},
        {"horizon_label": ""},
        {"status": ""},
        {"visibility": ""},
    ],
)
def test_operation_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _operation(**kwargs)


def test_operation_coerces_date():
    s = _operation(as_of_date=date(2026, 3, 31))
    assert s.as_of_date == "2026-03-31"


def test_operation_is_frozen():
    s = _operation()
    with pytest.raises(Exception):
        s.operation_signal_id = "tampered"  # type: ignore[misc]


def test_operation_to_dict_round_trips():
    s = _operation(
        source_settlement_account_ids=("settlement_account:a",),
        source_interbank_liquidity_state_ids=("interbank_liquidity_state:a",),
        source_market_environment_state_ids=("market_environment_state:a",),
        metadata={"note": "synthetic"},
    )
    out = s.to_dict()
    assert out["source_settlement_account_ids"] == ["settlement_account:a"]
    assert out["source_interbank_liquidity_state_ids"] == [
        "interbank_liquidity_state:a"
    ]
    assert out["source_market_environment_state_ids"] == [
        "market_environment_state:a"
    ]
    assert out["metadata"] == {"note": "synthetic"}


def test_operation_rejects_bool_confidence():
    with pytest.raises(ValueError):
        _operation(confidence=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_operation_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValueError):
        _operation(confidence=bad)


def test_operation_rejects_non_numeric_confidence():
    with pytest.raises(ValueError):
        _operation(confidence="0.5")  # type: ignore[arg-type]


def test_operation_rejects_empty_strings_in_source_tuples():
    with pytest.raises(ValueError):
        _operation(source_settlement_account_ids=("",))
    with pytest.raises(ValueError):
        _operation(source_interbank_liquidity_state_ids=("valid", ""))
    with pytest.raises(ValueError):
        _operation(source_market_environment_state_ids=("",))


# ---------------------------------------------------------------------------
# Eligibility record validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"eligibility_signal_id": ""},
        {"authority_id": ""},
        {"collateral_class_label": ""},
        {"as_of_date": ""},
        {"eligibility_label": ""},
        {"haircut_tier_label": ""},
        {"status": ""},
        {"visibility": ""},
    ],
)
def test_eligibility_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _eligibility(**kwargs)


def test_eligibility_coerces_date():
    s = _eligibility(as_of_date=date(2026, 3, 31))
    assert s.as_of_date == "2026-03-31"


def test_eligibility_is_frozen():
    s = _eligibility()
    with pytest.raises(Exception):
        s.eligibility_signal_id = "tampered"  # type: ignore[misc]


def test_eligibility_rejects_bool_confidence():
    with pytest.raises(ValueError):
        _eligibility(confidence=True)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [-0.01, 1.01])
def test_eligibility_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValueError):
        _eligibility(confidence=bad)


def test_eligibility_to_dict_round_trips():
    s = _eligibility(
        source_market_environment_state_ids=("market_environment_state:a",),
        source_interbank_liquidity_state_ids=("interbank_liquidity_state:a",),
        metadata={"note": "synthetic"},
    )
    out = s.to_dict()
    assert out["source_market_environment_state_ids"] == [
        "market_environment_state:a"
    ]
    assert out["source_interbank_liquidity_state_ids"] == [
        "interbank_liquidity_state:a"
    ]


# ---------------------------------------------------------------------------
# Recommended labels (pinned but not enforced)
# ---------------------------------------------------------------------------


_RECOMMENDED_OPERATION_LABELS = (
    "open_market_operation",
    "standing_facility",
    "policy_communication",
    "unknown",
)
_RECOMMENDED_DIRECTION_LABELS = ("inject", "withdraw", "neutral", "unknown")
_RECOMMENDED_HORIZON_LABELS = (
    "intraday", "short_term", "medium_term", "long_term", "unknown",
)
_RECOMMENDED_ELIGIBILITY_LABELS = (
    "eligible", "conditionally_eligible", "ineligible", "unknown",
)
_RECOMMENDED_HAIRCUT_TIERS = (
    "tier_low", "tier_medium", "tier_high", "tier_severe", "unknown",
)


@pytest.mark.parametrize("label", _RECOMMENDED_OPERATION_LABELS)
def test_recommended_operation_labels_accepted(label):
    s = _operation(operation_label=label)
    assert s.operation_label == label


@pytest.mark.parametrize("label", _RECOMMENDED_DIRECTION_LABELS)
def test_recommended_direction_labels_accepted(label):
    s = _operation(direction_label=label)
    assert s.direction_label == label


@pytest.mark.parametrize("label", _RECOMMENDED_HORIZON_LABELS)
def test_recommended_horizon_labels_accepted(label):
    s = _operation(horizon_label=label)
    assert s.horizon_label == label


@pytest.mark.parametrize("label", _RECOMMENDED_ELIGIBILITY_LABELS)
def test_recommended_eligibility_labels_accepted(label):
    s = _eligibility(eligibility_label=label)
    assert s.eligibility_label == label


@pytest.mark.parametrize("label", _RECOMMENDED_HAIRCUT_TIERS)
def test_recommended_haircut_tier_labels_accepted(label):
    s = _eligibility(haircut_tier_label=label)
    assert s.haircut_tier_label == label


# ---------------------------------------------------------------------------
# Anti-fields
# ---------------------------------------------------------------------------


_FORBIDDEN_FIELDS = {
    "amount",
    "currency_value",
    "fx_rate",
    "balance",
    "debit",
    "credit",
    "policy_rate",
    "interest",
    "order",
    "trade",
    "recommendation",
    "investment_advice",
    "forecast_value",
    "actual_value",
    "real_data_value",
    "behavior_probability",
    "haircut_percentage",
    "haircut_value",
    "operation_amount",
    "policy_stance_numeric",
    "margin_amount",
}


def test_operation_record_has_no_anti_fields():
    field_names = {
        f.name for f in dataclass_fields(CentralBankOperationSignalRecord)
    }
    leaked = field_names & _FORBIDDEN_FIELDS
    assert not leaked


def test_eligibility_record_has_no_anti_fields():
    field_names = {
        f.name for f in dataclass_fields(CollateralEligibilitySignalRecord)
    }
    leaked = field_names & _FORBIDDEN_FIELDS
    assert not leaked


# ---------------------------------------------------------------------------
# Book — operation CRUD
# ---------------------------------------------------------------------------


def test_book_add_and_get_operation():
    book = CentralBankSignalBook()
    s = _operation()
    book.add_operation(s)
    assert book.get_operation(s.operation_signal_id) is s


def test_book_get_unknown_operation_raises():
    book = CentralBankSignalBook()
    with pytest.raises(UnknownCentralBankOperationSignalError):
        book.get_operation("central_bank_operation_signal:missing")
    with pytest.raises(KeyError):
        book.get_operation("central_bank_operation_signal:missing")


def test_book_duplicate_operation_id_rejected():
    book = CentralBankSignalBook()
    book.add_operation(_operation())
    with pytest.raises(DuplicateCentralBankOperationSignalError):
        book.add_operation(_operation())


def test_book_list_operations_by_authority():
    book = CentralBankSignalBook()
    book.add_operation(
        _operation(
            operation_signal_id="central_bank_operation_signal:a",
            authority_id="monetary_authority:alpha",
        )
    )
    book.add_operation(
        _operation(
            operation_signal_id="central_bank_operation_signal:b",
            authority_id="monetary_authority:beta",
        )
    )
    assert (
        len(book.list_operations_by_authority("monetary_authority:alpha"))
        == 1
    )


def test_book_list_operations_by_label():
    book = CentralBankSignalBook()
    book.add_operation(
        _operation(
            operation_signal_id="central_bank_operation_signal:a",
            operation_label="open_market_operation",
        )
    )
    book.add_operation(
        _operation(
            operation_signal_id="central_bank_operation_signal:b",
            operation_label="standing_facility",
        )
    )
    assert len(book.list_operations_by_label("standing_facility")) == 1


# ---------------------------------------------------------------------------
# Book — eligibility CRUD
# ---------------------------------------------------------------------------


def test_book_add_and_get_eligibility():
    book = CentralBankSignalBook()
    s = _eligibility()
    book.add_eligibility(s)
    assert book.get_eligibility(s.eligibility_signal_id) is s


def test_book_get_unknown_eligibility_raises():
    book = CentralBankSignalBook()
    with pytest.raises(UnknownCollateralEligibilitySignalError):
        book.get_eligibility("collateral_eligibility_signal:missing")


def test_book_duplicate_eligibility_id_rejected():
    book = CentralBankSignalBook()
    book.add_eligibility(_eligibility())
    with pytest.raises(DuplicateCollateralEligibilitySignalError):
        book.add_eligibility(_eligibility())


def test_book_list_eligibilities_by_class():
    book = CentralBankSignalBook()
    book.add_eligibility(
        _eligibility(
            eligibility_signal_id="collateral_eligibility_signal:a",
            collateral_class_label="reference_government_paper",
        )
    )
    book.add_eligibility(
        _eligibility(
            eligibility_signal_id="collateral_eligibility_signal:b",
            collateral_class_label="reference_corporate_paper",
        )
    )
    assert (
        len(
            book.list_eligibilities_by_class("reference_corporate_paper")
        )
        == 1
    )


def test_book_list_eligibilities_by_label():
    book = CentralBankSignalBook()
    book.add_eligibility(
        _eligibility(
            eligibility_signal_id="collateral_eligibility_signal:a",
            eligibility_label="eligible",
        )
    )
    book.add_eligibility(
        _eligibility(
            eligibility_signal_id="collateral_eligibility_signal:b",
            eligibility_label="ineligible",
        )
    )
    assert len(book.list_eligibilities_by_label("ineligible")) == 1


def test_book_snapshot_is_deterministic_and_sorted():
    book = CentralBankSignalBook()
    book.add_operation(
        _operation(operation_signal_id="central_bank_operation_signal:b")
    )
    book.add_operation(
        _operation(operation_signal_id="central_bank_operation_signal:a")
    )
    book.add_eligibility(
        _eligibility(eligibility_signal_id="collateral_eligibility_signal:b")
    )
    book.add_eligibility(
        _eligibility(eligibility_signal_id="collateral_eligibility_signal:a")
    )
    snap = book.snapshot()
    assert snap["operation_count"] == 2
    assert [s["operation_signal_id"] for s in snap["operations"]] == [
        "central_bank_operation_signal:a",
        "central_bank_operation_signal:b",
    ]
    assert snap["eligibility_count"] == 2
    assert [
        s["eligibility_signal_id"] for s in snap["eligibilities"]
    ] == [
        "collateral_eligibility_signal:a",
        "collateral_eligibility_signal:b",
    ]


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_types_exist():
    assert (
        RecordType.CENTRAL_BANK_OPERATION_SIGNAL_RECORDED.value
        == "central_bank_operation_signal_recorded"
    )
    assert (
        RecordType.COLLATERAL_ELIGIBILITY_SIGNAL_RECORDED.value
        == "collateral_eligibility_signal_recorded"
    )


def test_add_operation_writes_one_ledger_record():
    ledger = Ledger()
    book = CentralBankSignalBook(ledger=ledger)
    book.add_operation(_operation())
    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert (
        rec.record_type
        is RecordType.CENTRAL_BANK_OPERATION_SIGNAL_RECORDED
    )
    assert rec.space_id == "central_bank_signals"


def test_add_eligibility_writes_one_ledger_record():
    ledger = Ledger()
    book = CentralBankSignalBook(ledger=ledger)
    book.add_eligibility(_eligibility())
    assert len(ledger.records) == 1
    rec = ledger.records[0]
    assert (
        rec.record_type
        is RecordType.COLLATERAL_ELIGIBILITY_SIGNAL_RECORDED
    )


def test_payloads_carry_no_anti_field_keys():
    ledger = Ledger()
    book = CentralBankSignalBook(ledger=ledger)
    book.add_operation(_operation())
    book.add_eligibility(_eligibility())
    for rec in ledger.records:
        leaked = set(rec.payload.keys()) & _FORBIDDEN_FIELDS
        assert not leaked


def test_book_without_ledger_does_not_raise():
    book = CentralBankSignalBook()
    book.add_operation(_operation())
    book.add_eligibility(_eligibility())


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_central_bank_signals_book():
    k = _kernel()
    assert isinstance(k.central_bank_signals, CentralBankSignalBook)
    assert k.central_bank_signals.ledger is k.ledger
    assert k.central_bank_signals.clock is k.clock


def test_kernel_simulation_date_uses_clock_for_operation():
    k = _kernel()
    k.central_bank_signals.add_operation(_operation())
    rec = k.ledger.records[-1]
    assert rec.simulation_date == "2026-03-31"


def test_kernel_simulation_date_uses_clock_for_eligibility():
    k = _kernel()
    k.central_bank_signals.add_eligibility(_eligibility())
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
        "attention_feedback": k.attention_feedback.snapshot(),
        "investor_intents": k.investor_intents.snapshot(),
        "market_environments": k.market_environments.snapshot(),
        "firm_financial_states": k.firm_financial_states.snapshot(),
    }
    k.central_bank_signals.add_operation(_operation())
    k.central_bank_signals.add_eligibility(_eligibility())
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
        / "central_bank_signals.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
