from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spaces.domain import DomainSpace
from spaces.investors.state import (
    DuplicateInvestorStateError,
    InvestorState,
    PortfolioExposure,
)
from world.ownership import OwnershipBook, OwnershipRecord
from world.prices import PriceBook
from world.scheduler import Frequency


@dataclass
class InvestorSpace(DomainSpace):
    """
    Investors Space — minimum internal state for investors.

    v0.10 scope:
        - hold a mapping of investor_id -> InvestorState (identity-level
          only)
        - read kernel-level projections via DomainSpace accessors
        - expose portfolio exposures derived from OwnershipBook ×
          PriceBook × Registry
        - log investor_state_added when an investor enters the space

    v0.10 explicitly does NOT implement:
        - trading decisions, order generation, or rebalancing
        - allocation logic, mandate enforcement, or strategy
        - price impact, liquidity, or market microstructure
        - performance attribution or benchmark comparison
        - investor-to-investor activist behavior
        - any mutation of source books or other spaces

    Beyond the common refs supplied by :class:`DomainSpace`,
    InvestorSpace captures :attr:`ownership` and :attr:`prices` so it
    can build :class:`PortfolioExposure` views.
    """

    space_id: str = "investors"
    frequencies: tuple[Frequency, ...] = (
        Frequency.DAILY,
        Frequency.MONTHLY,
    )
    ownership: OwnershipBook | None = None
    prices: PriceBook | None = None
    _investors: dict[str, InvestorState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lifecycle hook — extends DomainSpace.bind() with investor-specific refs
    # ------------------------------------------------------------------

    def bind(self, kernel: Any) -> None:
        """Extend DomainSpace.bind() to also capture ownership/prices."""
        super().bind(kernel)
        if self.ownership is None:
            self.ownership = kernel.ownership
        if self.prices is None:
            self.prices = kernel.prices

    # ------------------------------------------------------------------
    # Investor state CRUD
    # ------------------------------------------------------------------

    def add_investor_state(self, investor_state: InvestorState) -> InvestorState:
        if investor_state.investor_id in self._investors:
            raise DuplicateInvestorStateError(
                f"Duplicate investor_id: {investor_state.investor_id}"
            )
        self._investors[investor_state.investor_id] = investor_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="investor_state_added",
                simulation_date=simulation_date,
                object_id=investor_state.investor_id,
                agent_id=investor_state.investor_id,
                payload={
                    "investor_id": investor_state.investor_id,
                    "investor_type": investor_state.investor_type,
                    "tier": investor_state.tier,
                    "status": investor_state.status,
                },
                space_id=self.space_id,
            )
        return investor_state

    def get_investor_state(self, investor_id: str) -> InvestorState | None:
        return self._investors.get(investor_id)

    def list_investors(self) -> tuple[InvestorState, ...]:
        """
        Return all registered investors in insertion order.

        Matches v0.8 / v0.9: insertion order is preserved as a stable
        contract for audit-style reads. Use :meth:`snapshot` for a
        deterministic id-keyed ordering.
        """
        return tuple(self._investors.values())

    # ------------------------------------------------------------------
    # Ownership-derived views
    # ------------------------------------------------------------------

    def list_portfolio_positions(
        self,
        investor_id: str,
    ) -> tuple[OwnershipRecord, ...]:
        """
        Return raw OwnershipBook positions held by the investor.

        This is the un-priced, un-classified view: each position is the
        underlying ``OwnershipRecord``. Use :meth:`list_portfolio_exposures`
        if you also want valuation and asset typing.
        """
        if self.ownership is None:
            return ()
        return self.ownership.get_positions(investor_id)

    def list_portfolio_exposures(
        self,
        investor_id: str,
    ) -> tuple[PortfolioExposure, ...]:
        """
        Return positions enriched with latest price and asset type.

        For each ownership position:
            - ``latest_price`` comes from PriceBook's most recent
              observation, or ``None`` if no price has been recorded.
            - ``market_value`` is ``quantity * latest_price`` when
              both are present; ``None`` otherwise.
            - ``asset_type`` comes from Registry when the asset is
              registered; ``None`` otherwise.
            - Missing-data flags (``missing_price``, ``missing_asset_type``)
              are recorded in ``metadata`` so callers can detect gaps
              without re-querying the books.

        Missing data does not crash. v0.10 deliberately does **not**
        infer strategy or intent from holdings — a position is just a
        position.
        """
        if self.ownership is None:
            return ()

        positions = self.ownership.get_positions(investor_id)
        exposures: list[PortfolioExposure] = []

        for position in positions:
            latest_price: float | None = None
            if self.prices is not None:
                latest = self.prices.get_latest_price(position.asset_id)
                if latest is not None:
                    latest_price = latest.price

            market_value: float | None = None
            if latest_price is not None:
                market_value = float(position.quantity) * float(latest_price)

            asset_type: str | None = None
            if self.registry is not None and position.asset_id in self.registry:
                obj = self.registry.get(position.asset_id)
                asset_type = getattr(obj, "type", None)

            metadata: dict[str, Any] = {}
            if latest_price is None:
                metadata["missing_price"] = True
            if asset_type is None:
                metadata["missing_asset_type"] = True

            exposures.append(
                PortfolioExposure(
                    investor_id=investor_id,
                    asset_id=position.asset_id,
                    quantity=float(position.quantity),
                    latest_price=latest_price,
                    market_value=market_value,
                    asset_type=asset_type,
                    metadata=metadata,
                )
            )

        return tuple(exposures)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """
        Return a deterministic, JSON-friendly view of the space.

        Investors are sorted by ``investor_id`` so the output is stable
        across runs regardless of insertion order. Use
        :meth:`list_investors` if insertion order matters.
        """
        investors = sorted(
            (investor.to_dict() for investor in self._investors.values()),
            key=lambda item: item["investor_id"],
        )
        return {
            "space_id": self.space_id,
            "count": len(investors),
            "investors": investors,
        }
