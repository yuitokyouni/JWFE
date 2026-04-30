from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from spaces.base import BaseSpace
from spaces.investors.state import (
    DuplicateInvestorStateError,
    InvestorState,
    PortfolioExposure,
)
from world.balance_sheet import BalanceSheetProjector, BalanceSheetView
from world.clock import Clock
from world.constraints import ConstraintEvaluation, ConstraintEvaluator
from world.ledger import Ledger
from world.ownership import OwnershipBook, OwnershipRecord
from world.prices import PriceBook
from world.registry import Registry
from world.scheduler import Frequency
from world.signals import InformationSignal, SignalBook


@dataclass
class InvestorSpace(BaseSpace):
    """
    Investors Space — minimum internal state for investors.

    v0.10 scope:
        - hold a mapping of investor_id -> InvestorState (identity-level
          only)
        - read kernel-level projections (ownership, prices, balance
          sheets, constraints, signals) without mutating any source
          book
        - expose portfolio exposures derived from OwnershipBook ×
          PriceBook × Registry
        - log investor_state_added when an investor enters the space

    v0.10 explicitly does NOT implement:
        - trading decisions, order generation, or rebalancing
        - allocation logic, mandate enforcement, or strategy
        - price impact, liquidity, or market microstructure
        - performance attribution or benchmark comparison
        - investor-to-investor activist behavior
        - any mutation of OwnershipBook / ContractBook / PriceBook /
          ConstraintBook / SignalBook
        - any mutation of other spaces (CorporateSpace, BankSpace,
          ExchangeSpace, RealEstateSpace, etc.)

    Pattern note: this is the third domain space to follow the bind()
    template (after CorporateSpace §27 and BankSpace §28). The
    repetition is intentional. After v0.10 we have three concrete
    examples, which is the threshold for considering whether to
    extract a shared DomainSpace mixin in a later milestone.
    """

    space_id: str = "investors"
    frequencies: tuple[Frequency, ...] = (
        Frequency.DAILY,
        Frequency.MONTHLY,
    )
    registry: Registry | None = None
    ownership: OwnershipBook | None = None
    prices: PriceBook | None = None
    balance_sheets: BalanceSheetProjector | None = None
    constraint_evaluator: ConstraintEvaluator | None = None
    signals: SignalBook | None = None
    ledger: Ledger | None = None
    clock: Clock | None = None
    _investors: dict[str, InvestorState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lifecycle hook
    # ------------------------------------------------------------------

    def bind(self, kernel: Any) -> None:
        """
        Capture kernel references the space needs to read projections.

        Contract (see BaseSpace.bind for the full statement):
            - Idempotent: every assignment is gated on ``is None``, so a
              second call leaves the space in the same state as the first.
            - Fill-only: explicit refs supplied via the constructor are
              never overwritten.
            - Hot-swap / reload is out of scope.
        """
        if self.registry is None:
            self.registry = kernel.registry
        if self.ownership is None:
            self.ownership = kernel.ownership
        if self.prices is None:
            self.prices = kernel.prices
        if self.balance_sheets is None:
            self.balance_sheets = kernel.balance_sheets
        if self.constraint_evaluator is None:
            self.constraint_evaluator = kernel.constraint_evaluator
        if self.signals is None:
            self.signals = kernel.signals
        if self.ledger is None:
            self.ledger = kernel.ledger
        if self.clock is None:
            self.clock = kernel.clock

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
    # Read-only world projections
    # ------------------------------------------------------------------

    def get_balance_sheet_view(
        self,
        investor_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> BalanceSheetView | None:
        if self.balance_sheets is None:
            return None
        try:
            return self.balance_sheets.build_view(
                investor_id, as_of_date=as_of_date
            )
        except ValueError:
            return None

    def get_constraint_evaluations(
        self,
        investor_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> tuple[ConstraintEvaluation, ...]:
        if self.constraint_evaluator is None:
            return ()
        try:
            return self.constraint_evaluator.evaluate_owner(
                investor_id, as_of_date=as_of_date
            )
        except ValueError:
            return ()

    def get_visible_signals(
        self,
        observer_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> tuple[InformationSignal, ...]:
        """
        Return signals visible to ``observer_id``.

        In InvestorSpace the natural caller is querying "what does
        investor X see?", so ``observer_id`` is typically an investor
        id (e.g., ``"investor:gpf"``). The argument is named
        generically because the underlying check is
        :meth:`SignalBook.list_visible_to`, which is observer-agnostic.

        Returns an empty tuple if no SignalBook is bound.
        """
        if self.signals is None:
            return ()
        return self.signals.list_visible_to(observer_id, as_of_date=as_of_date)

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
