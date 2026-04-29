from datetime import date

import pytest

from world.clock import Clock
from world.contracts import (
    ContractBook,
    ContractRecord,
    DuplicateContractError,
    UnknownContractError,
)
from world.ledger import Ledger


def _book(with_ledger: bool = False) -> ContractBook:
    if with_ledger:
        return ContractBook(ledger=Ledger(), clock=Clock(current_date=date(2026, 1, 1)))
    return ContractBook()


def _loan(
    contract_id: str = "contract:loan_001",
    *,
    parties: tuple[str, ...] = ("agent:bank_a", "agent:firm_x"),
    contract_type: str = "loan",
    principal: float | None = 1_000_000.0,
    rate: float | None = 0.025,
    maturity_date: str | None = "2031-01-01",
    collateral: tuple[str, ...] = (),
    status: str = "active",
) -> ContractRecord:
    return ContractRecord(
        contract_id=contract_id,
        contract_type=contract_type,
        parties=parties,
        principal=principal,
        rate=rate,
        maturity_date=maturity_date,
        collateral_asset_ids=collateral,
        status=status,
    )


def test_add_contract_stores_record():
    book = _book()
    contract = book.add_contract(_loan())
    assert contract.contract_id == "contract:loan_001"
    assert book.get_contract("contract:loan_001") is contract


def test_add_contract_rejects_duplicates():
    book = _book()
    book.add_contract(_loan())
    with pytest.raises(DuplicateContractError):
        book.add_contract(_loan())


def test_get_contract_raises_for_unknown_id():
    book = _book()
    with pytest.raises(UnknownContractError):
        book.get_contract("contract:does_not_exist")


def test_list_by_party_filters_correctly():
    book = _book()
    book.add_contract(_loan(contract_id="contract:loan_001", parties=("agent:bank_a", "agent:firm_x")))
    book.add_contract(_loan(contract_id="contract:loan_002", parties=("agent:bank_a", "agent:firm_y")))
    book.add_contract(_loan(contract_id="contract:lease_001", parties=("agent:firm_x", "agent:landlord_z"), contract_type="lease"))

    bank_contracts = book.list_by_party("agent:bank_a")
    firm_x_contracts = book.list_by_party("agent:firm_x")

    assert {c.contract_id for c in bank_contracts} == {
        "contract:loan_001",
        "contract:loan_002",
    }
    assert {c.contract_id for c in firm_x_contracts} == {
        "contract:loan_001",
        "contract:lease_001",
    }


def test_list_by_type_filters_correctly():
    book = _book()
    book.add_contract(_loan(contract_id="contract:loan_001"))
    book.add_contract(_loan(contract_id="contract:loan_002"))
    book.add_contract(_loan(contract_id="contract:bond_001", contract_type="bond"))

    loans = book.list_by_type("loan")
    bonds = book.list_by_type("bond")

    assert {c.contract_id for c in loans} == {"contract:loan_001", "contract:loan_002"}
    assert {c.contract_id for c in bonds} == {"contract:bond_001"}


def test_update_status_replaces_record():
    book = _book()
    book.add_contract(_loan(status="active"))

    updated = book.update_status("contract:loan_001", "settled")
    assert updated.status == "settled"
    assert book.get_contract("contract:loan_001").status == "settled"


def test_update_status_raises_for_unknown_contract():
    book = _book()
    with pytest.raises(UnknownContractError):
        book.update_status("contract:does_not_exist", "settled")


def test_collateral_and_maturity_are_preserved_through_status_change():
    book = _book()
    book.add_contract(
        _loan(
            collateral=("asset:property_001", "asset:property_002"),
            maturity_date="2031-01-01",
        )
    )
    updated = book.update_status("contract:loan_001", "defaulted")

    assert updated.collateral_asset_ids == ("asset:property_001", "asset:property_002")
    assert updated.maturity_date == "2031-01-01"


def test_contract_record_rejects_empty_parties():
    with pytest.raises(ValueError):
        ContractRecord(
            contract_id="contract:bad",
            contract_type="loan",
            parties=(),
        )


def test_contract_record_accepts_date_for_maturity():
    contract = ContractRecord(
        contract_id="contract:loan_dt",
        contract_type="loan",
        parties=("agent:a", "agent:b"),
        maturity_date=date(2031, 1, 1),
    )
    assert contract.maturity_date == "2031-01-01"


def test_snapshot_lists_all_contracts_sorted():
    book = _book()
    book.add_contract(_loan(contract_id="contract:loan_002"))
    book.add_contract(_loan(contract_id="contract:loan_001"))

    snap = book.snapshot()
    assert snap["count"] == 2
    ids = [item["contract_id"] for item in snap["contracts"]]
    assert ids == ["contract:loan_001", "contract:loan_002"]


def test_add_contract_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_contract(_loan(collateral=("asset:property_001",)))

    records = book.ledger.filter(event_type="contract_created")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "contract:loan_001"
    assert record.payload["contract_type"] == "loan"
    # Ledger payloads are frozen, so list-typed values come back as tuples.
    assert tuple(record.payload["parties"]) == ("agent:bank_a", "agent:firm_x")
    assert tuple(record.payload["collateral_asset_ids"]) == ("asset:property_001",)


def test_update_status_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_contract(_loan())
    book.update_status("contract:loan_001", "settled")

    records = book.ledger.filter(event_type="contract_status_updated")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "contract:loan_001"
    assert record.payload["previous_status"] == "active"
    assert record.payload["new_status"] == "settled"
