"""
Tests for v1.13.1 SettlementAccountRecord + SettlementAccountBook.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.settlement_accounts import (
    DuplicateSettlementAccountError,
    SettlementAccountBook,
    SettlementAccountRecord,
    UnknownSettlementAccountError,
)
from world.state import State


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _account(
    *,
    account_id: str = "settlement_account:reference_megabank_a:reserve",
    owner_institution_id: str = "bank:reference_megabank_a",
    owner_type: str = "participant_bank",
    account_type: str = "reserve_account",
    currency_label: str = "reference_currency_a",
    settlement_system_id: str = "settlement_system:reference_generic_substrate",
    status: str = "active",
    visibility: str = "internal_only",
    opened_date: str = "2026-01-01",
    closed_date: str | None = None,
    metadata: dict | None = None,
) -> SettlementAccountRecord:
    return SettlementAccountRecord(
        account_id=account_id,
        owner_institution_id=owner_institution_id,
        owner_type=owner_type,
        account_type=account_type,
        currency_label=currency_label,
        settlement_system_id=settlement_system_id,
        status=status,
        visibility=visibility,
        opened_date=opened_date,
        closed_date=closed_date,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"account_id": ""},
        {"owner_institution_id": ""},
        {"owner_type": ""},
        {"account_type": ""},
        {"currency_label": ""},
        {"settlement_system_id": ""},
        {"status": ""},
        {"visibility": ""},
        {"opened_date": ""},
    ],
)
def test_account_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _account(**kwargs)


def test_account_coerces_dates_to_iso_strings():
    a = _account(
        opened_date=date(2026, 1, 1),
        closed_date=date(2026, 6, 30),
    )
    assert a.opened_date == "2026-01-01"
    assert a.closed_date == "2026-06-30"


def test_account_rejects_closed_date_before_opened_date():
    with pytest.raises(ValueError):
        _account(opened_date="2026-06-30", closed_date="2026-01-01")


def test_account_closed_date_optional():
    a = _account(closed_date=None)
    assert a.closed_date is None


def test_account_is_frozen():
    a = _account()
    with pytest.raises(Exception):
        a.account_id = "tampered"  # type: ignore[misc]


def test_account_to_dict_round_trips():
    a = _account(metadata={"note": "synthetic"})
    out = a.to_dict()
    assert out["account_id"] == a.account_id
    assert out["metadata"] == {"note": "synthetic"}


# ---------------------------------------------------------------------------
# Anti-fields — no balance / accounting / payment field
# ---------------------------------------------------------------------------


def test_account_has_no_balance_or_accounting_field():
    field_names = {f.name for f in dataclass_fields(SettlementAccountRecord)}
    forbidden = {
        "balance",
        "available_credit",
        "pending_settlement_amount",
        "interest_accrued",
        "debit_limit",
        "credit_line",
        "cash_balance",
        "reserve_balance",
        "required_reserve",
        "policy_rate",
        "order",
        "trade",
        "recommendation",
        "investment_advice",
        "forecast_value",
        "actual_value",
        "real_data_value",
        "behavior_probability",
    }
    leaked = field_names & forbidden
    assert not leaked


# ---------------------------------------------------------------------------
# Book CRUD + listings
# ---------------------------------------------------------------------------


def test_book_add_and_get_account():
    book = SettlementAccountBook()
    a = _account()
    book.add_account(a)
    assert book.get_account(a.account_id) is a


def test_book_get_unknown_raises():
    book = SettlementAccountBook()
    with pytest.raises(UnknownSettlementAccountError):
        book.get_account("settlement_account:missing")
    with pytest.raises(KeyError):
        book.get_account("settlement_account:missing")


def test_book_duplicate_account_id_rejected():
    book = SettlementAccountBook()
    book.add_account(_account())
    with pytest.raises(DuplicateSettlementAccountError):
        book.add_account(_account())


def test_book_list_accounts_in_insertion_order():
    book = SettlementAccountBook()
    a = _account(account_id="settlement_account:a")
    b = _account(account_id="settlement_account:b")
    book.add_account(a)
    book.add_account(b)
    assert book.list_accounts() == (a, b)


def test_book_list_by_owner_filters_exactly():
    book = SettlementAccountBook()
    book.add_account(
        _account(account_id="settlement_account:a", owner_institution_id="bank:a")
    )
    book.add_account(
        _account(account_id="settlement_account:b", owner_institution_id="bank:b")
    )
    out = book.list_by_owner("bank:a")
    assert len(out) == 1
    assert out[0].owner_institution_id == "bank:a"


def test_book_list_by_account_type_filters_exactly():
    book = SettlementAccountBook()
    book.add_account(
        _account(
            account_id="settlement_account:a", account_type="reserve_account"
        )
    )
    book.add_account(
        _account(
            account_id="settlement_account:b",
            account_type="settlement_account",
        )
    )
    out = book.list_by_account_type("reserve_account")
    assert len(out) == 1


def test_book_list_by_status_filters_exactly():
    book = SettlementAccountBook()
    book.add_account(
        _account(account_id="settlement_account:a", status="active")
    )
    book.add_account(
        _account(account_id="settlement_account:b", status="frozen")
    )
    out = book.list_by_status("frozen")
    assert len(out) == 1


def test_book_list_active_as_of():
    book = SettlementAccountBook()
    book.add_account(
        _account(
            account_id="settlement_account:a",
            opened_date="2026-01-01",
            closed_date="2026-06-30",
        )
    )
    book.add_account(
        _account(
            account_id="settlement_account:b",
            opened_date="2026-04-01",
            status="active",
        )
    )
    book.add_account(
        _account(
            account_id="settlement_account:c",
            opened_date="2026-01-01",
            status="closed",
        )
    )
    out = book.list_active_as_of("2026-04-01")
    out_ids = {a.account_id for a in out}
    assert out_ids == {"settlement_account:a", "settlement_account:b"}


def test_book_snapshot_is_deterministic_and_sorted():
    book = SettlementAccountBook()
    book.add_account(_account(account_id="settlement_account:b"))
    book.add_account(_account(account_id="settlement_account:a"))
    snap = book.snapshot()
    assert snap["account_count"] == 2
    assert [a["account_id"] for a in snap["accounts"]] == [
        "settlement_account:a",
        "settlement_account:b",
    ]


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    assert (
        RecordType.SETTLEMENT_ACCOUNT_REGISTERED.value
        == "settlement_account_registered"
    )


def test_add_account_writes_one_ledger_record():
    ledger = Ledger()
    book = SettlementAccountBook(ledger=ledger)
    book.add_account(_account())
    assert len(ledger.records) == 1
    assert (
        ledger.records[0].record_type is RecordType.SETTLEMENT_ACCOUNT_REGISTERED
    )


def test_payload_carries_no_balance_or_accounting_keys():
    ledger = Ledger()
    book = SettlementAccountBook(ledger=ledger)
    book.add_account(_account())
    payload = ledger.records[0].payload
    forbidden = {
        "balance",
        "available_credit",
        "pending_settlement_amount",
        "interest_accrued",
        "debit_limit",
        "credit_line",
        "cash_balance",
        "reserve_balance",
        "required_reserve",
        "policy_rate",
    }
    leaked = set(payload.keys()) & forbidden
    assert not leaked


def test_book_without_ledger_does_not_raise():
    book = SettlementAccountBook()
    book.add_account(_account())


def test_duplicate_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = SettlementAccountBook(ledger=ledger)
    book.add_account(_account())
    with pytest.raises(DuplicateSettlementAccountError):
        book.add_account(_account())
    assert len(ledger.records) == 1


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_settlement_accounts_book():
    k = _kernel()
    assert isinstance(k.settlement_accounts, SettlementAccountBook)
    assert k.settlement_accounts.ledger is k.ledger
    assert k.settlement_accounts.clock is k.clock


def test_kernel_simulation_date_uses_clock():
    k = _kernel()
    k.settlement_accounts.add_account(_account())
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
        "institutions": k.institutions.snapshot(),
        "external_processes": k.external_processes.snapshot(),
        "relationships": k.relationships.snapshot(),
        "interactions": k.interactions.snapshot(),
        "routines": k.routines.snapshot(),
        "attention": k.attention.snapshot(),
        "variables": k.variables.snapshot(),
        "exposures": k.exposures.snapshot(),
        "stewardship": k.stewardship.snapshot(),
        "engagement": k.engagement.snapshot(),
        "escalations": k.escalations.snapshot(),
        "strategic_responses": k.strategic_responses.snapshot(),
        "industry_conditions": k.industry_conditions.snapshot(),
        "market_conditions": k.market_conditions.snapshot(),
        "capital_market_readouts": k.capital_market_readouts.snapshot(),
        "market_environments": k.market_environments.snapshot(),
        "firm_financial_states": k.firm_financial_states.snapshot(),
        "investor_intents": k.investor_intents.snapshot(),
        "attention_feedback": k.attention_feedback.snapshot(),
    }
    k.settlement_accounts.add_account(_account())
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
        / "settlement_accounts.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
