from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spaces.corporate.state import DuplicateFirmStateError, FirmState
from spaces.domain import DomainSpace
from world.scheduler import Frequency


@dataclass
class CorporateSpace(DomainSpace):
    """
    Corporate Space — minimum internal state for firms.

    v0.8 scope:
        - hold a mapping of firm_id -> FirmState (identity-level only)
        - read kernel-level projections (balance sheets, constraints,
          signals) via accessors inherited from DomainSpace
        - log firm_state_added when a firm enters the space

    v0.8 explicitly does NOT implement:
        - revenue / profit / earnings logic
        - asset sale or borrowing decisions
        - bank credit reactions, investor reactions, market clearing
        - any mutation of OwnershipBook / ContractBook / PriceBook /
          ConstraintBook / SignalBook
        - any mutation of other spaces (BankSpace, InvestorSpace, etc.)

    The kernel-projection accessors (``get_balance_sheet_view``,
    ``get_constraint_evaluations``, ``get_visible_signals``) live on
    :class:`DomainSpace`. CorporateSpace requires no extra kernel refs
    beyond those, so it inherits ``bind()`` unchanged. See §30 for the
    v0.10.1 extraction rationale.
    """

    space_id: str = "corporate"
    frequencies: tuple[Frequency, ...] = (
        Frequency.MONTHLY,
        Frequency.QUARTERLY,
        Frequency.YEARLY,
    )
    _firms: dict[str, FirmState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Firm state CRUD
    # ------------------------------------------------------------------

    def add_firm_state(self, firm_state: FirmState) -> FirmState:
        if firm_state.firm_id in self._firms:
            raise DuplicateFirmStateError(
                f"Duplicate firm_id: {firm_state.firm_id}"
            )
        self._firms[firm_state.firm_id] = firm_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="firm_state_added",
                simulation_date=simulation_date,
                object_id=firm_state.firm_id,
                agent_id=firm_state.firm_id,
                payload={
                    "firm_id": firm_state.firm_id,
                    "sector": firm_state.sector,
                    "tier": firm_state.tier,
                    "status": firm_state.status,
                },
                space_id=self.space_id,
            )
        return firm_state

    def get_firm_state(self, firm_id: str) -> FirmState | None:
        return self._firms.get(firm_id)

    def list_firms(self) -> tuple[FirmState, ...]:
        """
        Return all registered firms in insertion order.

        v0.8 documents this as a stable invariant: ``list_firms()``
        preserves the order in which ``add_firm_state`` was called. This
        is useful for audit-style reads where "added Nth" is meaningful.
        Callers that want a deterministic, content-keyed ordering should
        use :meth:`snapshot`, which sorts by ``firm_id``.
        """
        return tuple(self._firms.values())

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """
        Return a deterministic, JSON-friendly view of the space.

        Firms are sorted by ``firm_id`` so the output is stable across
        runs regardless of insertion order. Use :meth:`list_firms` if
        insertion order matters.
        """
        firms = sorted(
            (firm.to_dict() for firm in self._firms.values()),
            key=lambda item: item["firm_id"],
        )
        return {
            "space_id": self.space_id,
            "count": len(firms),
            "firms": firms,
        }
