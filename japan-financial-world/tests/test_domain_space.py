"""
Contract tests for the DomainSpace abstraction (v0.10.1).

These tests pin down the behavior the three concrete domain spaces
inherit from DomainSpace. They do not duplicate every per-space
integration test — those still cover the inherited code paths from
each subclass's perspective. This file exists so that future domain
spaces (RealEstate, Exchange, Information, Policy, External) can be
implemented against a known contract rather than a pattern read from
sibling code.
"""

from datetime import date

from spaces.domain import DomainSpace
from world.balance_sheet import BalanceSheetProjector
from world.clock import Clock
from world.constraints import ConstraintBook, ConstraintEvaluator
from world.contracts import ContractBook
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.ownership import OwnershipBook
from world.prices import PriceBook
from world.registry import Registry
from world.scheduler import Scheduler
from world.signals import SignalBook
from world.state import State


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# DomainSpace can be instantiated directly (no domain state required)
# ---------------------------------------------------------------------------


def test_domain_space_starts_with_no_refs_set():
    space = DomainSpace()
    assert space.registry is None
    assert space.balance_sheets is None
    assert space.constraint_evaluator is None
    assert space.signals is None
    assert space.ledger is None
    assert space.clock is None


# ---------------------------------------------------------------------------
# bind() contract: idempotent, fill-only, explicit refs win
# ---------------------------------------------------------------------------


def test_bind_captures_all_common_kernel_refs():
    kernel = _kernel()
    space = DomainSpace()

    space.bind(kernel)

    assert space.registry is kernel.registry
    assert space.balance_sheets is kernel.balance_sheets
    assert space.constraint_evaluator is kernel.constraint_evaluator
    assert space.signals is kernel.signals
    assert space.ledger is kernel.ledger
    assert space.clock is kernel.clock


def test_bind_is_fill_only_for_each_ref():
    kernel = _kernel()
    custom_ledger = Ledger()
    custom_signals = SignalBook()

    space = DomainSpace(ledger=custom_ledger, signals=custom_signals)
    space.bind(kernel)

    # Explicit refs win.
    assert space.ledger is custom_ledger
    assert space.signals is custom_signals
    # Unset refs are filled in.
    assert space.registry is kernel.registry
    assert space.balance_sheets is kernel.balance_sheets
    assert space.constraint_evaluator is kernel.constraint_evaluator
    assert space.clock is kernel.clock


def test_bind_is_idempotent():
    kernel = _kernel()
    space = DomainSpace()

    space.bind(kernel)
    snapshot_after_first = (
        space.registry,
        space.balance_sheets,
        space.constraint_evaluator,
        space.signals,
        space.ledger,
        space.clock,
    )

    space.bind(kernel)

    assert (
        space.registry,
        space.balance_sheets,
        space.constraint_evaluator,
        space.signals,
        space.ledger,
        space.clock,
    ) == snapshot_after_first


# ---------------------------------------------------------------------------
# Read-only accessors return safe defaults when refs are unbound
# ---------------------------------------------------------------------------


def test_get_balance_sheet_view_returns_none_when_unbound():
    assert DomainSpace().get_balance_sheet_view("agent:any") is None


def test_get_constraint_evaluations_returns_empty_when_unbound():
    assert DomainSpace().get_constraint_evaluations("agent:any") == ()


def test_get_visible_signals_returns_empty_when_unbound():
    assert DomainSpace().get_visible_signals("agent:any") == ()


def test_get_balance_sheet_view_returns_none_when_no_date_resolvable():
    """
    BalanceSheetProjector raises ValueError if it cannot resolve an
    as_of_date. DomainSpace converts that into a None return so callers
    don't need to handle the exception path.
    """
    # Build a projector with no clock and pass no as_of_date.
    space = DomainSpace(
        balance_sheets=BalanceSheetProjector(
            ownership=OwnershipBook(),
            contracts=ContractBook(),
            prices=PriceBook(),
        )
    )
    assert space.get_balance_sheet_view("agent:any") is None


def test_get_constraint_evaluations_returns_empty_when_no_date_resolvable():
    book = ConstraintBook()
    space = DomainSpace(
        constraint_evaluator=ConstraintEvaluator(
            book=book,
            projector=BalanceSheetProjector(
                ownership=OwnershipBook(),
                contracts=ContractBook(),
                prices=PriceBook(),
            ),
        )
    )
    assert space.get_constraint_evaluations("agent:any") == ()


# ---------------------------------------------------------------------------
# Wiring through register_space (DomainSpace.bind is invoked by kernel)
# ---------------------------------------------------------------------------


def test_register_space_invokes_domain_space_bind():
    kernel = _kernel()
    space = DomainSpace()

    kernel.register_space(space)

    assert space.registry is kernel.registry
    assert space.balance_sheets is kernel.balance_sheets
    assert space.constraint_evaluator is kernel.constraint_evaluator
    assert space.signals is kernel.signals
    assert space.ledger is kernel.ledger
    assert space.clock is kernel.clock
