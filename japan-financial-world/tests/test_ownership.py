from datetime import date

import pytest

from world.clock import Clock
from world.ledger import Ledger
from world.ownership import (
    InsufficientQuantityError,
    OwnershipBook,
    UnknownPositionError,
)


def _book(with_ledger: bool = False) -> OwnershipBook:
    if with_ledger:
        return OwnershipBook(ledger=Ledger(), clock=Clock(current_date=date(2026, 1, 1)))
    return OwnershipBook()


def test_add_position_creates_record():
    book = _book()
    record = book.add_position("agent:alice", "asset:aapl", 100, acquisition_price=150.0)

    assert record.owner_id == "agent:alice"
    assert record.asset_id == "asset:aapl"
    assert record.quantity == 100
    assert record.acquisition_price == 150.0


def test_add_position_aggregates_existing_position():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100, acquisition_price=150.0)
    record = book.add_position("agent:alice", "asset:aapl", 50, acquisition_price=200.0)

    # Quantities accumulate; the latest acquisition_price wins.
    assert record.quantity == 150
    assert record.acquisition_price == 200.0


def test_add_position_rejects_zero_or_negative_quantity():
    book = _book()
    with pytest.raises(ValueError):
        book.add_position("agent:alice", "asset:aapl", 0)
    with pytest.raises(ValueError):
        book.add_position("agent:alice", "asset:aapl", -10)


def test_get_positions_returns_all_assets_for_owner():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100)
    book.add_position("agent:alice", "asset:msft", 200)
    book.add_position("agent:bob", "asset:aapl", 50)

    positions = book.get_positions("agent:alice")
    asset_ids = {position.asset_id for position in positions}

    assert asset_ids == {"asset:aapl", "asset:msft"}


def test_get_owners_returns_all_owners_of_asset():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100)
    book.add_position("agent:bob", "asset:aapl", 50)
    book.add_position("agent:carol", "asset:msft", 25)

    owners = book.get_owners("asset:aapl")
    owner_ids = {position.owner_id for position in owners}

    assert owner_ids == {"agent:alice", "agent:bob"}


def test_transfer_moves_quantity_between_owners():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100)

    from_record, to_record = book.transfer(
        "asset:aapl", "agent:alice", "agent:bob", 30
    )

    assert from_record is not None
    assert from_record.quantity == 70
    assert to_record.quantity == 30


def test_transfer_clears_position_when_quantity_reaches_zero():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100)

    from_record, to_record = book.transfer(
        "asset:aapl", "agent:alice", "agent:bob", 100
    )

    assert from_record is None
    assert to_record.quantity == 100
    assert book.get_position("agent:alice", "asset:aapl") is None


def test_transfer_rejects_insufficient_quantity():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 50)

    with pytest.raises(InsufficientQuantityError):
        book.transfer("asset:aapl", "agent:alice", "agent:bob", 100)


def test_transfer_rejects_unknown_position():
    book = _book()
    with pytest.raises(UnknownPositionError):
        book.transfer("asset:aapl", "agent:ghost", "agent:bob", 10)


def test_transfer_rejects_self_transfer():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100)
    with pytest.raises(ValueError):
        book.transfer("asset:aapl", "agent:alice", "agent:alice", 10)


def test_transfer_aggregates_into_existing_destination_position():
    book = _book()
    book.add_position("agent:alice", "asset:aapl", 100)
    book.add_position("agent:bob", "asset:aapl", 25)

    _, to_record = book.transfer("asset:aapl", "agent:alice", "agent:bob", 30)
    assert to_record.quantity == 55


def test_snapshot_lists_all_positions_sorted():
    book = _book()
    book.add_position("agent:bob", "asset:msft", 200)
    book.add_position("agent:alice", "asset:aapl", 100)

    snap = book.snapshot()
    assert snap["count"] == 2
    keys = [(item["owner_id"], item["asset_id"]) for item in snap["positions"]]
    assert keys == [("agent:alice", "asset:aapl"), ("agent:bob", "asset:msft")]


def test_add_position_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_position("agent:alice", "asset:aapl", 100, acquisition_price=150.0)

    records = book.ledger.filter(event_type="ownership_position_added")
    assert len(records) == 1
    assert records[0].object_id == "asset:aapl"
    assert records[0].agent_id == "agent:alice"
    assert records[0].payload["delta_quantity"] == 100
    assert records[0].payload["new_quantity"] == 100
    assert records[0].simulation_date == "2026-01-01"


def test_transfer_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_position("agent:alice", "asset:aapl", 100)
    book.transfer("asset:aapl", "agent:alice", "agent:bob", 30)

    transfer_records = book.ledger.filter(event_type="ownership_transferred")
    assert len(transfer_records) == 1
    record = transfer_records[0]
    assert record.source == "agent:alice"
    assert record.target == "agent:bob"
    assert record.payload["quantity"] == 30
    assert record.payload["from_remaining"] == 70
    assert record.payload["to_total"] == 30
