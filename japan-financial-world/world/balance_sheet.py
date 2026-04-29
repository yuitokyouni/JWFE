from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Mapping

from world.clock import Clock
from world.contracts import ContractBook
from world.ledger import Ledger
from world.ownership import OwnershipBook
from world.prices import PriceBook
from world.registry import Registry


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


@dataclass(frozen=True)
class BalanceSheetView:
    """
    Read-only projection of an agent's financial position.

    A BalanceSheetView is a derived snapshot. It is always rebuilt from
    OwnershipBook + ContractBook + PriceBook. It is never the canonical
    store of any value. Mutating a view has no effect on the underlying
    books.

    Convention for borrower / lender identification:
        Contracts opt into balance-sheet treatment by setting
        metadata["borrower_id"] and metadata["lender_id"]. Contracts
        without these keys are not classified as liability or financial
        asset and contribute nothing to the view.

    v0.5 simplifications (intentional):
        - Asset value uses position.quantity * latest_price.
        - Loan principal is treated as an undiscounted face-value
          liability (borrower) or financial asset (lender). No present
          value, no amortization, no accrued interest.
        - Collateral_value is the sum of latest prices of
          collateral_asset_ids. Collateral quantities are not modeled.
        - Missing prices do not crash; affected ids are recorded in
          metadata["missing_prices"].
        - Status filtering is not applied; settled or defaulted
          contracts are still included. Pre-filter contracts upstream
          if you need different behavior.
    """

    agent_id: str
    as_of_date: str
    asset_value: float
    liabilities: float
    net_asset_value: float
    cash_like_assets: float | None = None
    debt_principal: float | None = None
    collateral_value: float | None = None
    asset_breakdown: Mapping[str, float] = field(default_factory=dict)
    liability_breakdown: Mapping[str, float] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "as_of_date": self.as_of_date,
            "asset_value": self.asset_value,
            "liabilities": self.liabilities,
            "net_asset_value": self.net_asset_value,
            "cash_like_assets": self.cash_like_assets,
            "debt_principal": self.debt_principal,
            "collateral_value": self.collateral_value,
            "asset_breakdown": dict(self.asset_breakdown),
            "liability_breakdown": dict(self.liability_breakdown),
            "metadata": dict(self.metadata),
        }


@dataclass
class BalanceSheetProjector:
    """
    Read-only projector that derives BalanceSheetViews from the network
    layer (OwnershipBook + ContractBook + PriceBook).

    The projector holds no derived state of its own. Each call to
    build_view() recomputes the view from current book contents.

    The projector MUST NOT mutate ownership, contracts, or prices.
    """

    ownership: OwnershipBook
    contracts: ContractBook
    prices: PriceBook
    registry: Registry | None = None
    clock: Clock | None = None
    ledger: Ledger | None = None

    def build_view(
        self,
        agent_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> BalanceSheetView:
        as_of = self._resolve_as_of(as_of_date)

        asset_breakdown: dict[str, float] = {}
        liability_breakdown: dict[str, float] = {}
        missing_prices: set[str] = set()

        cash_like_total = 0.0
        cash_like_seen = False
        debt_principal_total = 0.0
        collateral_total = 0.0
        collateral_seen = False

        # ----- Asset side: holdings from the ownership book -----
        for position in self.ownership.get_positions(agent_id):
            latest = self.prices.get_latest_price(position.asset_id)
            if latest is None:
                missing_prices.add(position.asset_id)
                continue

            value = float(position.quantity) * float(latest.price)
            asset_breakdown[position.asset_id] = (
                asset_breakdown.get(position.asset_id, 0.0) + value
            )

            if self.registry is not None and position.asset_id in self.registry:
                obj = self.registry.get(position.asset_id)
                if getattr(obj, "type", None) == "cash":
                    cash_like_total += value
                    cash_like_seen = True

        # ----- Asset and liability side: contracts the agent is party to -----
        for contract in self.contracts.list_by_party(agent_id):
            borrower = contract.metadata.get("borrower_id")
            lender = contract.metadata.get("lender_id")

            if contract.principal is not None and agent_id == borrower:
                principal = float(contract.principal)
                liability_breakdown[contract.contract_id] = (
                    liability_breakdown.get(contract.contract_id, 0.0) + principal
                )
                debt_principal_total += principal

                for collateral_id in contract.collateral_asset_ids:
                    collateral_seen = True
                    latest = self.prices.get_latest_price(collateral_id)
                    if latest is None:
                        missing_prices.add(collateral_id)
                        continue
                    collateral_total += float(latest.price)

            if contract.principal is not None and agent_id == lender:
                principal = float(contract.principal)
                asset_breakdown[contract.contract_id] = (
                    asset_breakdown.get(contract.contract_id, 0.0) + principal
                )

        asset_value = sum(asset_breakdown.values())
        liabilities = sum(liability_breakdown.values())
        net_asset_value = asset_value - liabilities

        metadata: dict[str, Any] = {}
        if missing_prices:
            metadata["missing_prices"] = sorted(missing_prices)

        return BalanceSheetView(
            agent_id=agent_id,
            as_of_date=as_of,
            asset_value=asset_value,
            liabilities=liabilities,
            net_asset_value=net_asset_value,
            cash_like_assets=cash_like_total if cash_like_seen else None,
            debt_principal=debt_principal_total if liability_breakdown else None,
            collateral_value=collateral_total if collateral_seen else None,
            asset_breakdown=asset_breakdown,
            liability_breakdown=liability_breakdown,
            metadata=metadata,
        )

    def build_views(
        self,
        agent_ids: Iterable[str],
        *,
        as_of_date: date | str | None = None,
    ) -> tuple[BalanceSheetView, ...]:
        return tuple(
            self.build_view(agent_id, as_of_date=as_of_date) for agent_id in agent_ids
        )

    def snapshot(
        self,
        *,
        as_of_date: date | str | None = None,
    ) -> dict[str, Any]:
        as_of = self._resolve_as_of(as_of_date)
        agent_ids = self._discover_agents()
        views = self.build_views(agent_ids, as_of_date=as_of)

        if self.ledger is not None:
            for view in views:
                self.ledger.append(
                    event_type="balance_sheet_view_created",
                    simulation_date=as_of,
                    object_id=view.agent_id,
                    agent_id=view.agent_id,
                    payload={
                        "agent_id": view.agent_id,
                        "asset_value": view.asset_value,
                        "liabilities": view.liabilities,
                        "net_asset_value": view.net_asset_value,
                    },
                    space_id="balance_sheet",
                )

        return {
            "as_of_date": as_of,
            "count": len(views),
            "views": [view.to_dict() for view in views],
        }

    def _resolve_as_of(self, as_of_date: date | str | None) -> str:
        if as_of_date is not None:
            return _coerce_iso_date(as_of_date)
        if self.clock is not None and self.clock.current_date is not None:
            return self.clock.current_date.isoformat()
        raise ValueError(
            "as_of_date is required when the projector has no clock reference"
        )

    def _discover_agents(self) -> tuple[str, ...]:
        agents: set[str] = set()
        for record in self.ownership.all_positions():
            agents.add(record.owner_id)
        for contract in self.contracts.all_contracts():
            for party in contract.parties:
                agents.add(party)
        return tuple(sorted(agents))
