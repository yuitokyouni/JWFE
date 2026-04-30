from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spaces.banking.state import (
    BankState,
    DuplicateBankStateError,
    LendingExposure,
)
from spaces.domain import DomainSpace
from world.contracts import ContractBook, ContractRecord
from world.scheduler import Frequency


@dataclass
class BankSpace(DomainSpace):
    """
    Banking Space — minimum internal state for banks.

    v0.9 scope:
        - hold a mapping of bank_id -> BankState (identity-level only)
        - read kernel-level projections via DomainSpace accessors
        - expose lending exposures derived from ContractBook by
          filtering on ``metadata["lender_id"] == bank_id``
        - log bank_state_added when a bank enters the space

    v0.9 explicitly does NOT implement:
        - lending decisions, credit underwriting, or origination logic
        - credit tightening, spread updates, or rate adjustments
        - default detection or non-performing classification
        - collateral haircut or LTV breach reactions
        - any mutation of source books or other spaces

    Beyond the common refs supplied by :class:`DomainSpace`, BankSpace
    captures :attr:`contracts` so it can derive
    :class:`LendingExposure` views.
    """

    space_id: str = "banking"
    frequencies: tuple[Frequency, ...] = (
        Frequency.DAILY,
        Frequency.QUARTERLY,
    )
    contracts: ContractBook | None = None
    _banks: dict[str, BankState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lifecycle hook — extends DomainSpace.bind() with bank-specific refs
    # ------------------------------------------------------------------

    def bind(self, kernel: Any) -> None:
        """Extend DomainSpace.bind() to also capture ``contracts``."""
        super().bind(kernel)
        if self.contracts is None:
            self.contracts = kernel.contracts

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
