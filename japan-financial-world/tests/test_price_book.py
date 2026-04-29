from datetime import date

import pytest

from world.clock import Clock
from world.ledger import Ledger
from world.prices import PriceBook, PriceRecord


def _book(with_ledger: bool = False) -> PriceBook:
    if with_ledger:
        return PriceBook(ledger=Ledger(), clock=Clock(current_date=date(2026, 1, 1)))
    return PriceBook()


def test_set_price_records_observation():
    book = _book()
    record = book.set_price(
        asset_id="asset:aapl",
        price=150.0,
        simulation_date="2026-01-01",
        source="exchange",
    )

    assert record.asset_id == "asset:aapl"
    assert record.price == 150.0
    assert record.simulation_date == "2026-01-01"
    assert record.source == "exchange"


def test_set_price_accepts_date_objects():
    book = _book()
    record = book.set_price(
        asset_id="asset:aapl",
        price=150.0,
        simulation_date=date(2026, 1, 1),
        source="exchange",
    )
    assert record.simulation_date == "2026-01-01"


def test_get_latest_price_returns_most_recent_observation():
    book = _book()
    book.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    book.set_price("asset:aapl", 155.0, "2026-01-02", "exchange")
    book.set_price("asset:aapl", 152.0, "2026-01-03", "exchange")

    latest = book.get_latest_price("asset:aapl")
    assert latest is not None
    assert latest.price == 152.0
    assert latest.simulation_date == "2026-01-03"


def test_get_latest_price_returns_none_for_unknown_asset():
    book = _book()
    assert book.get_latest_price("asset:unknown") is None


def test_get_price_history_is_chronological():
    book = _book()
    book.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    book.set_price("asset:aapl", 155.0, "2026-01-02", "exchange")
    book.set_price("asset:aapl", 152.0, "2026-01-03", "exchange")

    history = book.get_price_history("asset:aapl")
    assert [record.price for record in history] == [150.0, 155.0, 152.0]
    assert [record.simulation_date for record in history] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]


def test_get_price_history_returns_empty_for_unknown_asset():
    book = _book()
    assert book.get_price_history("asset:unknown") == ()


def test_history_is_per_asset():
    book = _book()
    book.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    book.set_price("asset:msft", 380.0, "2026-01-01", "exchange")
    book.set_price("asset:aapl", 152.0, "2026-01-02", "exchange")

    assert len(book.get_price_history("asset:aapl")) == 2
    assert len(book.get_price_history("asset:msft")) == 1


def test_price_record_rejects_missing_source():
    with pytest.raises(ValueError):
        PriceRecord(
            asset_id="asset:aapl",
            price=150.0,
            simulation_date="2026-01-01",
            source="",
        )


def test_price_record_rejects_missing_asset_id():
    with pytest.raises(ValueError):
        PriceRecord(
            asset_id="",
            price=150.0,
            simulation_date="2026-01-01",
            source="exchange",
        )


def test_snapshot_returns_latest_and_history_lengths():
    book = _book()
    book.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    book.set_price("asset:aapl", 155.0, "2026-01-02", "exchange")
    book.set_price("asset:msft", 380.0, "2026-01-01", "exchange")

    snap = book.snapshot()

    assert snap["count"] == 2
    assert snap["latest_prices"]["asset:aapl"]["price"] == 155.0
    assert snap["latest_prices"]["asset:msft"]["price"] == 380.0
    assert snap["history_lengths"] == {"asset:aapl": 2, "asset:msft": 1}


def test_set_price_records_to_ledger():
    book = _book(with_ledger=True)
    book.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    book.set_price("asset:aapl", 155.0, "2026-01-02", "exchange")

    records = book.ledger.filter(event_type="price_updated")
    assert len(records) == 2
    assert records[0].object_id == "asset:aapl"
    assert records[0].source == "exchange"
    assert records[0].payload["price"] == 150.0
    assert records[0].payload["history_length"] == 1
    assert records[1].payload["price"] == 155.0
    assert records[1].payload["history_length"] == 2
