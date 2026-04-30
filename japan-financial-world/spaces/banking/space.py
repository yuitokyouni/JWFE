from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from spaces.banking.state import (
    BankState,
    DuplicateBankStateError,
    LendingExposure,
)
from spaces.base import BaseSpace
from world.balance_sheet import BalanceSheetProjector, BalanceSheetView
from world.clock import Clock
from world.constraints import ConstraintEvaluation, ConstraintEvaluator
from world.contracts import ContractBook, ContractRecord
from world.ledger import Ledger
from world.registry import Registry
from world.scheduler import Frequency
from world.signals import InformationSignal, SignalBook


@dataclass
class BankSpace(BaseSpace):
    """
    Banking Space — minimum internal state for banks.

    v0.9 scope:
        - hold a mapping of bank_id -> BankState (identity-level only)
        - read kernel-level projections (contracts, balance sheets,
          constraints, signals) without mutating any source book
        - expose lending exposures derived from ContractBook by
          filtering on metadata["lender_id"] == bank_id
        - log bank_state_added when a bank enters the space

    v0.9 explicitly does NOT implement:
        - lending decisions, credit underwriting, or origination logic
        - credit tightening, spread updates, or rate adjustments
        - default detection or non-performing classification
        - collateral haircut or LTV breach reactions
        - any mutation of OwnershipBook / ContractBook / PriceBook /
          ConstraintBook / SignalBook
        - any mutation of other spaces (CorporateSpace, InvestorSpace,
          ExchangeSpace, RealEstateSpace, etc.)

    Pattern note: BankSpace mirrors CorporateSpace from §27. The same
    bind() contract applies. The only structural difference is that
    BankSpace also captures `kernel.contracts` so it can derive
    LendingExposure views.
    """

    space_id: str = "banking"
    frequencies: tuple[Frequency, ...] = (
        Frequency.DAILY,
        Frequency.QUARTERLY,
    )
    registry: Registry | None = None
    contracts: ContractBook | None = None
    balance_sheets: BalanceSheetProjector | None = None
    constraint_evaluator: ConstraintEvaluator | None = None
    signals: SignalBook | None = None
    ledger: Ledger | None = None
    clock: Clock | None = None
    _banks: dict[str, BankState] = field(default_factory=dict)

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
        if self.contracts is None:
            self.contracts = kernel.contracts
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
    # Bank state CRUD
    # ------------------------------------------------------------------

    def add_bank_state(self, bank_state: BankState) -> BankState:
        if bank_state.bank_id in self._banks:
            raise DuplicateBankStateError(
                f"Duplicate bank_id: {bank_state.bank_id}"
            )
        self._banks[bank_state.bank_id] = bank_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="bank_state_added",
                simulation_date=simulation_date,
                object_id=bank_state.bank_id,
                agent_id=bank_state.bank_id,
                payload={
                    "bank_id": bank_state.bank_id,
                    "bank_type": bank_state.bank_type,
                    "tier": bank_state.tier,
                    "status": bank_state.status,
                },
                space_id=self.space_id,
            )
        return bank_state

    def get_bank_state(self, bank_id: str) -> BankState | None:
        return self._banks.get(bank_id)

    def list_banks(self) -> tuple[BankState, ...]:
        """
        Return all registered banks in insertion order.

        Matches the v0.8 list_firms invariant: insertion order is
        preserved as a stable contract for audit-style reads. Use
        :meth:`snapshot` for a deterministic id-keyed ordering.
        """
        return tuple(self._banks.values())

    # ------------------------------------------------------------------
    # Read-only world projections
    # ------------------------------------------------------------------

    def get_balance_sheet_view(
        self,
        bank_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> BalanceSheetView | None:
        if self.balance_sheets is None:
            return None
        try:
            return self.balance_sheets.build_view(bank_id, as_of_date=as_of_date)
        except ValueError:
            return None

    def get_constraint_evaluations(
        self,
        bank_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> tuple[ConstraintEvaluation, ...]:
        if self.constraint_evaluator is None:
            return ()
        try:
            return self.constraint_evaluator.evaluate_owner(
                bank_id, as_of_date=as_of_date
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

        In BankSpace the natural caller is querying "what does
        bank X see?", so ``observer_id`` is typically a bank id (e.g.,
        ``"bank:mufg"``). The argument is named generically because the
        underlying check is :meth:`SignalBook.list_visible_to`, which
        is observer-agnostic — any agent or space id is valid.

        Returns an empty tuple if no SignalBook is bound.
        """
        if self.signals is None:
            return ()
        return self.signals.list_visible_to(observer_id, as_of_date=as_of_date)

    # ------------------------------------------------------------------
    # Contract-derived views
    # ------------------------------------------------------------------

    def list_contracts_for_bank(
        self,
        bank_id: str,
    ) -> tuple[ContractRecord, ...]:
        """
        Return every contract where the bank appears in ``parties``.

        This is the broad query — it includes contracts where the bank
        is borrower, lender, counterparty, or any other role. v0.9 does
        not interpret roles here; for lender-side filtering use
        :meth:`list_lending_exposures`.
        """
        if self.contracts is None:
            return ()
        return self.contracts.list_by_party(bank_id)

    def list_lending_exposures(
        self,
        bank_id: str,
    ) -> tuple[LendingExposure, ...]:
        """
        Return contracts where the bank is the explicit lender.

        A contract qualifies iff ``metadata["lender_id"] == bank_id``.
        v0.9 deliberately does **not** infer roles from the order of
        ``parties`` — opt-in role tagging via metadata is the only
        source of truth.

        ``borrower_id`` is taken from ``metadata.get("borrower_id")``
        and may be ``None`` if the contract did not declare one. No
        credit-quality classification (performing / impaired / etc.) is
        applied. Callers that care about that should consult signals
        or future domain-specific layers.
        """
        if self.contracts is None:
            return ()

        candidates = self.contracts.list_by_party(bank_id)
        exposures: list[LendingExposure] = []
        for contract in candidates:
            if contract.metadata.get("lender_id") != bank_id:
                continue
            exposures.append(
                LendingExposure(
                    contract_id=contract.contract_id,
                    lender_id=bank_id,
                    borrower_id=contract.metadata.get("borrower_id"),
                    principal=contract.principal,
                    contract_type=contract.contract_type,
                    status=contract.status,
                    collateral_asset_ids=contract.collateral_asset_ids,
                )
            )
        return tuple(exposures)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """
        Return a deterministic, JSON-friendly view of the space.

        Banks are sorted by ``bank_id`` so the output is stable across
        runs regardless of insertion order. Use :meth:`list_banks` if
        insertion order matters.
        """
        banks = sorted(
            (bank.to_dict() for bank in self._banks.values()),
            key=lambda item: item["bank_id"],
        )
        return {
            "space_id": self.space_id,
            "count": len(banks),
            "banks": banks,
        }
