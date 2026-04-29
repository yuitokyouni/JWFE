import pytest

from world.ledger import Ledger, RecordType
from world.state import StateAccessError, StateLayer, StateStore


def test_investor_cannot_read_true_state():
    state = StateStore()

    state.set_state(
        StateLayer.TRUE,
        "firm:sample_001",
        {"cash": 100, "debt": 300},
        source="firm:sample_001",
        simulation_date="2026-01-01",
    )

    with pytest.raises(StateAccessError):
        state.read_state(
            StateLayer.TRUE,
            "firm:sample_001",
            requester_role="investor",
            requester_id="investor:fund_a",
        )

    assert state.read_state(
        StateLayer.TRUE,
        "firm:sample_001",
        requester_role="system",
    ) == {"cash": 100, "debt": 300}


def test_published_and_market_state_are_readable_by_investor():
    state = StateStore()

    state.set_state(
        StateLayer.PUBLISHED,
        "firm:sample_001",
        {"reported_revenue": 1000},
        source="firm:sample_001",
        simulation_date="2026-01-01",
    )

    state.set_state(
        StateLayer.MARKET,
        "firm:sample_001",
        {"price": 1200, "spread_bps": 80},
        source="market:equity",
        simulation_date="2026-01-01",
    )

    assert state.read_state(
        StateLayer.PUBLISHED,
        "firm:sample_001",
        requester_role="investor",
        requester_id="investor:fund_a",
    )["reported_revenue"] == 1000

    assert state.read_state(
        StateLayer.MARKET,
        "firm:sample_001",
        requester_role="investor",
        requester_id="investor:fund_a",
    )["price"] == 1200


def test_perceived_state_is_owner_scoped():
    state = StateStore()

    state.set_state(
        StateLayer.PERCEIVED,
        "firm:sample_001",
        {"credit_view": "weakening"},
        source="investor:fund_a",
        owner_id="investor:fund_a",
        simulation_date="2026-01-01",
    )

    own_view = state.read_state(
        StateLayer.PERCEIVED,
        "firm:sample_001",
        requester_role="investor",
        requester_id="investor:fund_a",
    )

    assert own_view["credit_view"] == "weakening"

    with pytest.raises(StateAccessError):
        state.read_state(
            StateLayer.PERCEIVED,
            "firm:sample_001",
            requester_role="investor",
            requester_id="investor:fund_b",
        )


def test_snapshot_creation_records_to_ledger():
    ledger = Ledger()
    state = StateStore()

    state.set_state(
        StateLayer.MARKET,
        "firm:sample_001",
        {"price": 1000},
        source="market:equity",
        simulation_date="2026-01-01",
    )

    snapshot = state.create_snapshot(
        simulation_date="2026-01-01",
        source="state",
        ledger=ledger,
        metadata={"reason": "daily_close"},
    )

    assert snapshot.snapshot_id.startswith("snapshot_")
    assert snapshot.state_hash.startswith("sha256:")

    records = ledger.query(record_type=RecordType.STATE_SNAPSHOT_CREATED)
    assert len(records) == 1
    assert records[0].object_id == snapshot.snapshot_id
    assert records[0].payload["state_hash"] == snapshot.state_hash


def test_restore_snapshot():
    state = StateStore()

    state.set_state(
        StateLayer.MARKET,
        "firm:sample_001",
        {"price": 1000},
        source="market:equity",
        simulation_date="2026-01-01",
    )

    snapshot = state.create_snapshot(simulation_date="2026-01-01")

    state.set_state(
        StateLayer.MARKET,
        "firm:sample_001",
        {"price": 700},
        source="market:equity",
        simulation_date="2026-01-02",
    )

    assert state.read_state(
        StateLayer.MARKET,
        "firm:sample_001",
        requester_role="system",
    )["price"] == 700

    state.restore_snapshot(snapshot)

    assert state.read_state(
        StateLayer.MARKET,
        "firm:sample_001",
        requester_role="system",
    )["price"] == 1000