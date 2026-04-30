from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from spaces.base import BaseSpace
from world.balance_sheet import BalanceSheetProjector, BalanceSheetView
from world.clock import Clock
from world.constraints import ConstraintEvaluation, ConstraintEvaluator
from world.ledger import Ledger
from world.registry import Registry
from world.signals import InformationSignal, SignalBook


@dataclass
class DomainSpace(BaseSpace):
    """
    Shared scaffolding for read-only domain spaces.

    The v0.8 / v0.9 / v0.10 milestones each introduced one domain
    space (Corporate, Bank, Investor) that followed the same pattern:
    capture a fixed set of kernel references via ``bind()``, then expose
    a small set of read-only accessors that delegate to those references.

    DomainSpace is the v0.10.1 extraction of the parts that were truly
    identical across all three. It owns:

        - Common kernel ref fields:
              registry, balance_sheets, constraint_evaluator,
              signals, ledger, clock
        - ``bind(kernel)`` that fills those refs only when ``None``
          (idempotent / fill-only / explicit refs win, per §27.4)
        - ``get_balance_sheet_view(agent_id, *, as_of_date)``
        - ``get_constraint_evaluations(agent_id, *, as_of_date)``
        - ``get_visible_signals(observer_id, *, as_of_date)``

    DomainSpace does NOT own (these stay in concrete spaces):

        - Domain-specific state records (FirmState / BankState /
          InvestorState) and their duplicate-error classes
        - ``add_*_state`` / ``get_*_state`` / ``list_*`` and snapshot
          semantics — each space's snapshot has a different shape
          (firms / banks / investors) and naming is informative
        - Domain-specific projections (LendingExposure /
          PortfolioExposure)
        - Additional kernel refs that only some spaces need
          (``contracts`` for BankSpace; ``ownership`` and ``prices``
          for InvestorSpace). Subclasses extend ``bind()`` by
          calling ``super().bind(kernel)`` and capturing the extras.

    Why not abstract more
    ---------------------
    Each domain has its own distinguishable vocabulary
    (firm / bank / investor) for the entity it represents. Centralizing
    state CRUD with generic names like ``add_state`` would make every
    call site read worse, not better, and would lose the type-level
    distinction between FirmState and BankState. The accessors that
    *are* centralized here genuinely take a generic ``agent_id``: from
    the kernel's perspective firms, banks, and investors are all
    agents, so a unified parameter name is honest, not lossy.
    """

    registry: Registry | None = None
    balance_sheets: BalanceSheetProjector | None = None
    constraint_evaluator: ConstraintEvaluator | None = None
    signals: SignalBook | None = None
    ledger: Ledger | None = None
    clock: Clock | None = None

    def bind(self, kernel: Any) -> None:
        """
        Capture the common kernel references this space reads from.

        Subclasses extend this by overriding bind() and calling
        ``super().bind(kernel)`` first, then capturing any
        domain-specific refs (e.g. ContractBook for BankSpace).

        Contract (per §27.4):
            - Idempotent: gates each assignment on ``is None``, so a
              second call is a no-op.
            - Fill-only: never overwrites a ref that is already set.
            - Explicit constructor refs win.
            - Hot-swap / reload is out of scope.
        """
        if self.registry is None:
            self.registry = kernel.registry
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
    # Read-only kernel-projection accessors
    # ------------------------------------------------------------------

    def get_balance_sheet_view(
        self,
        agent_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> BalanceSheetView | None:
        """
        Return the BalanceSheetView for ``agent_id``.

        ``agent_id`` is whatever WorldID identifies the entity from the
        balance sheet projector's point of view — a firm_id from
        CorporateSpace, a bank_id from BankSpace, an investor_id from
        InvestorSpace. The argument name is generic because the
        projector is.

        Returns ``None`` when the projector is unbound or when no
        ``as_of_date`` can be resolved (no clock and no explicit date).
        """
        if self.balance_sheets is None:
            return None
        try:
            return self.balance_sheets.build_view(agent_id, as_of_date=as_of_date)
        except ValueError:
            return None

    def get_constraint_evaluations(
        self,
        agent_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> tuple[ConstraintEvaluation, ...]:
        """
        Return constraint evaluations for ``agent_id``.

        Returns ``()`` when no evaluator is bound or no date can be
        resolved.
        """
        if self.constraint_evaluator is None:
            return ()
        try:
            return self.constraint_evaluator.evaluate_owner(
                agent_id, as_of_date=as_of_date
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

        ``observer_id`` follows :meth:`SignalBook.list_visible_to`:
        any agent or space id is valid. In a domain space the
        natural caller passes their own domain id (firm_id /
        bank_id / investor_id) but the signature is observer-agnostic.

        Returns ``()`` when no SignalBook is bound.
        """
        if self.signals is None:
            return ()
        return self.signals.list_visible_to(observer_id, as_of_date=as_of_date)
