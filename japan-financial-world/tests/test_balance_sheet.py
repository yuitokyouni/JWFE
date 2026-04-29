from datetime import date

import pytest

from world.balance_sheet import BalanceSheetProjector, BalanceSheetView
from world.clock import Clock
from world.contracts import ContractBook, ContractRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.ownership import OwnershipBook
from world.prices import PriceBook
from world.registry import RegisteredObject, Registry
from world.scheduler import Scheduler
from world.state import State


def _projector(
    *,
    ownership: OwnershipBook | None = None,
    contracts: ContractBook | None = None,
    prices: PriceBook | None = None,
    registry: Registry | None = None,
    ledger: Ledger | None = None,
) -> BalanceSheetProjector:
    return BalanceSheetProjector(
        ownership=ownership or OwnershipBook(),
        contracts=contracts or ContractBook(),
        prices=prices or PriceBook(),
        registry=registry,
        ledger=ledger,
    )


def _loan(
    *,
    contract_id: str = "contract:loan_001",
    lender: str,
    borrower: str,
    principal: float,
    collateral: tuple[str, ...] = (),
    status: str = "active",
) -> ContractRecord:
    return ContractRecord(
        contract_id=contract_id,
        contract_type="loan",
        parties=(lender, borrower),
        principal=principal,
        collateral_asset_ids=collateral,
        status=status,
        metadata={"lender_id": lender, "borrower_id": borrower},
    )


def test_asset_value_uses_quantity_times_latest_price():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:aapl", 100)
    prices = PriceBook()
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")

    view = _projector(ownership=ownership, prices=prices).build_view(
        "agent:alice", as_of_date="2026-01-02"
    )

    assert view.asset_value == 15_000.0
    assert view.asset_breakdown == {"asset:aapl": 15_000.0}
    assert view.liabilities == 0.0
    assert view.net_asset_value == 15_000.0


def test_latest_price_supersedes_older_observations():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:aapl", 100)
    prices = PriceBook()
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    prices.set_price("asset:aapl", 175.0, "2026-01-05", "exchange")

    view = _projector(ownership=ownership, prices=prices).build_view(
        "agent:alice", as_of_date="2026-01-06"
    )

    assert view.asset_value == 17_500.0


def test_missing_price_does_not_crash_and_records_warning():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:no_price", 100)
    ownership.add_position("agent:alice", "asset:has_price", 50)
    prices = PriceBook()
    prices.set_price("asset:has_price", 10.0, "2026-01-01", "exchange")

    view = _projector(ownership=ownership, prices=prices).build_view(
        "agent:alice", as_of_date="2026-01-02"
    )

    assert view.asset_value == 500.0
    assert "asset:no_price" not in view.asset_breakdown
    assert view.metadata["missing_prices"] == ["asset:no_price"]


def test_borrower_principal_counts_as_liability():
    contracts = ContractBook()
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=1_000_000.0)
    )

    view = _projector(contracts=contracts).build_view(
        "agent:firm_x", as_of_date="2026-01-02"
    )

    assert view.liabilities == 1_000_000.0
    assert view.debt_principal == 1_000_000.0
    assert view.liability_breakdown == {"contract:loan_001": 1_000_000.0}
    assert view.net_asset_value == -1_000_000.0


def test_lender_principal_counts_as_financial_asset():
    contracts = ContractBook()
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=1_000_000.0)
    )

    view = _projector(contracts=contracts).build_view(
        "agent:bank_a", as_of_date="2026-01-02"
    )

    assert view.asset_value == 1_000_000.0
    assert view.asset_breakdown == {"contract:loan_001": 1_000_000.0}
    assert view.liabilities == 0.0
    assert view.net_asset_value == 1_000_000.0


def test_collateral_value_uses_latest_prices_of_collateral_assets():
    contracts = ContractBook()
    contracts.add_contract(
        _loan(
            lender="agent:bank_a",
            borrower="agent:firm_x",
            principal=500_000.0,
            collateral=("asset:property_a", "asset:property_b"),
        )
    )
    prices = PriceBook()
    prices.set_price("asset:property_a", 300_000.0, "2026-01-01", "appraisal")
    prices.set_price("asset:property_b", 400_000.0, "2026-01-01", "appraisal")

    view = _projector(contracts=contracts, prices=prices).build_view(
        "agent:firm_x", as_of_date="2026-01-02"
    )

    assert view.collateral_value == 700_000.0


def test_collateral_value_only_attaches_to_borrower_view():
    contracts = ContractBook()
    contracts.add_contract(
        _loan(
            lender="agent:bank_a",
            borrower="agent:firm_x",
            principal=500_000.0,
            collateral=("asset:property_a",),
        )
    )
    prices = PriceBook()
    prices.set_price("asset:property_a", 300_000.0, "2026-01-01", "appraisal")

    bank_view = _projector(contracts=contracts, prices=prices).build_view(
        "agent:bank_a", as_of_date="2026-01-02"
    )
    firm_view = _projector(contracts=contracts, prices=prices).build_view(
        "agent:firm_x", as_of_date="2026-01-02"
    )

    assert bank_view.collateral_value is None
    assert firm_view.collateral_value == 300_000.0


def test_missing_collateral_price_recorded_in_metadata():
    contracts = ContractBook()
    contracts.add_contract(
        _loan(
            lender="agent:bank_a",
            borrower="agent:firm_x",
            principal=500_000.0,
            collateral=("asset:no_price_collateral",),
        )
    )
    prices = PriceBook()  # no price for the collateral

    view = _projector(contracts=contracts, prices=prices).build_view(
        "agent:firm_x", as_of_date="2026-01-02"
    )

    assert view.metadata["missing_prices"] == ["asset:no_price_collateral"]
    assert view.collateral_value == 0.0  # no priced collateral, but the field is set


def test_net_asset_value_is_assets_minus_liabilities():
    ownership = OwnershipBook()
    ownership.add_position("agent:firm_x", "asset:cash_jpy", 50_000)
    prices = PriceBook()
    prices.set_price("asset:cash_jpy", 1.0, "2026-01-01", "system")

    contracts = ContractBook()
    contracts.add_contract(
        _loan(
            lender="agent:bank_a",
            borrower="agent:firm_x",
            principal=30_000.0,
        )
    )

    view = _projector(
        ownership=ownership, contracts=contracts, prices=prices
    ).build_view("agent:firm_x", as_of_date="2026-01-02")

    assert view.asset_value == 50_000.0
    assert view.liabilities == 30_000.0
    assert view.net_asset_value == 20_000.0


def test_cash_like_assets_detected_via_registry():
    ownership = OwnershipBook()
    ownership.add_position("agent:firm_x", "asset:cash_jpy", 50_000)
    ownership.add_position("agent:firm_x", "asset:aapl", 100)
    prices = PriceBook()
    prices.set_price("asset:cash_jpy", 1.0, "2026-01-01", "system")
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")

    registry = Registry()
    registry.register(
        RegisteredObject(
            id="asset:cash_jpy", kind="asset", type="cash", space="market"
        )
    )
    registry.register(
        RegisteredObject(
            id="asset:aapl", kind="asset", type="equity", space="market"
        )
    )

    view = _projector(
        ownership=ownership, prices=prices, registry=registry
    ).build_view("agent:firm_x", as_of_date="2026-01-02")

    assert view.cash_like_assets == 50_000.0
    assert view.asset_value == 50_000.0 + 15_000.0


def test_cash_like_assets_is_none_when_no_registry_provided():
    ownership = OwnershipBook()
    ownership.add_position("agent:firm_x", "asset:cash_jpy", 50_000)
    prices = PriceBook()
    prices.set_price("asset:cash_jpy", 1.0, "2026-01-01", "system")

    view = _projector(ownership=ownership, prices=prices).build_view(
        "agent:firm_x", as_of_date="2026-01-02"
    )

    assert view.cash_like_assets is None


def test_contracts_without_role_metadata_are_ignored_in_balance_sheet():
    contracts = ContractBook()
    contracts.add_contract(
        ContractRecord(
            contract_id="contract:no_role",
            contract_type="loan",
            parties=("agent:bank_a", "agent:firm_x"),
            principal=1_000_000.0,
            # no metadata roles -> not classified
        )
    )

    view = _projector(contracts=contracts).build_view(
        "agent:firm_x", as_of_date="2026-01-02"
    )

    assert view.liabilities == 0.0
    assert view.asset_value == 0.0


def test_build_views_returns_one_per_agent_in_order():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:aapl", 10)
    ownership.add_position("agent:bob", "asset:aapl", 20)
    prices = PriceBook()
    prices.set_price("asset:aapl", 100.0, "2026-01-01", "exchange")

    views = _projector(ownership=ownership, prices=prices).build_views(
        ["agent:alice", "agent:bob"], as_of_date="2026-01-02"
    )

    assert [v.agent_id for v in views] == ["agent:alice", "agent:bob"]
    assert views[0].asset_value == 1_000.0
    assert views[1].asset_value == 2_000.0


def test_snapshot_includes_all_agents_from_ownership_and_contracts():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:aapl", 100)
    contracts = ContractBook()
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=1_000.0)
    )
    prices = PriceBook()
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")

    snap = _projector(
        ownership=ownership, contracts=contracts, prices=prices
    ).snapshot(as_of_date="2026-01-02")

    agent_ids = {view["agent_id"] for view in snap["views"]}
    assert agent_ids == {"agent:alice", "agent:bank_a", "agent:firm_x"}
    assert snap["count"] == 3
    assert snap["as_of_date"] == "2026-01-02"


def test_snapshot_records_balance_sheet_view_created_in_ledger():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:aapl", 100)
    prices = PriceBook()
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    ledger = Ledger()

    projector = _projector(ownership=ownership, prices=prices, ledger=ledger)
    projector.snapshot(as_of_date="2026-01-02")

    records = ledger.filter(event_type="balance_sheet_view_created")
    assert len(records) == 1
    assert records[0].agent_id == "agent:alice"
    assert records[0].payload["asset_value"] == 15_000.0


def test_build_view_does_not_mutate_source_books():
    ownership = OwnershipBook()
    ownership.add_position("agent:alice", "asset:aapl", 100)
    contracts = ContractBook()
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=1_000.0)
    )
    prices = PriceBook()
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")

    ownership_before = ownership.snapshot()
    contracts_before = contracts.snapshot()
    prices_before = prices.snapshot()

    projector = _projector(ownership=ownership, contracts=contracts, prices=prices)
    projector.build_view("agent:alice", as_of_date="2026-01-02")
    projector.build_view("agent:firm_x", as_of_date="2026-01-02")
    projector.build_view("agent:bank_a", as_of_date="2026-01-02")

    assert ownership.snapshot() == ownership_before
    assert contracts.snapshot() == contracts_before
    assert prices.snapshot() == prices_before


def test_build_view_requires_a_date():
    projector = _projector()  # no clock
    with pytest.raises(ValueError):
        projector.build_view("agent:alice")


def test_kernel_exposes_balance_sheets_wired_to_books():
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.ownership.add_position("agent:alice", "asset:aapl", 100)
    kernel.prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")

    view = kernel.balance_sheets.build_view("agent:alice")

    # When no as_of_date is provided, it falls back to the kernel's clock.
    assert view.as_of_date == "2026-01-01"
    assert view.asset_value == 15_000.0
    assert isinstance(view, BalanceSheetView)
