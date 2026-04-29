from datetime import date

import pytest

from world.balance_sheet import BalanceSheetProjector
from world.clock import Clock
from world.constraints import (
    ConstraintBook,
    ConstraintEvaluation,
    ConstraintEvaluator,
    ConstraintRecord,
    DuplicateConstraintError,
    UnknownConstraintError,
)
from world.contracts import ContractBook, ContractRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.ownership import OwnershipBook
from world.prices import PriceBook
from world.registry import RegisteredObject, Registry
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_world(
    *,
    registry: Registry | None = None,
    ledger: Ledger | None = None,
) -> tuple[
    OwnershipBook,
    ContractBook,
    PriceBook,
    Registry,
    BalanceSheetProjector,
]:
    ownership = OwnershipBook()
    contracts = ContractBook()
    prices = PriceBook()
    registry = registry if registry is not None else Registry()
    projector = BalanceSheetProjector(
        ownership=ownership,
        contracts=contracts,
        prices=prices,
        registry=registry,
        ledger=ledger,
    )
    return ownership, contracts, prices, registry, projector


def _loan(
    *,
    contract_id: str = "contract:loan_001",
    lender: str,
    borrower: str,
    principal: float,
    collateral: tuple[str, ...] = (),
) -> ContractRecord:
    return ContractRecord(
        contract_id=contract_id,
        contract_type="loan",
        parties=(lender, borrower),
        principal=principal,
        collateral_asset_ids=collateral,
        metadata={"lender_id": lender, "borrower_id": borrower},
    )


# ---------------------------------------------------------------------------
# ConstraintRecord / ConstraintBook
# ---------------------------------------------------------------------------


def test_add_and_retrieve_constraint():
    book = ConstraintBook()
    constraint = ConstraintRecord(
        constraint_id="constraint:lev_001",
        owner_id="agent:firm_x",
        constraint_type="max_leverage",
        threshold=0.7,
        comparison="<=",
    )
    book.add_constraint(constraint)
    assert book.get_constraint("constraint:lev_001") is constraint


def test_add_constraint_rejects_duplicates():
    book = ConstraintBook()
    constraint = ConstraintRecord(
        constraint_id="constraint:lev_001",
        owner_id="agent:firm_x",
        constraint_type="max_leverage",
        threshold=0.7,
        comparison="<=",
    )
    book.add_constraint(constraint)
    with pytest.raises(DuplicateConstraintError):
        book.add_constraint(constraint)


def test_get_constraint_raises_for_unknown_id():
    book = ConstraintBook()
    with pytest.raises(UnknownConstraintError):
        book.get_constraint("constraint:does_not_exist")


def test_list_by_owner_and_list_by_type():
    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:firm_lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:firm_cash",
            owner_id="agent:firm_x",
            constraint_type="min_cash_like_assets",
            threshold=10_000.0,
            comparison=">=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:bank_lev",
            owner_id="agent:bank_a",
            constraint_type="max_leverage",
            threshold=0.9,
            comparison="<=",
        )
    )

    firm_constraints = book.list_by_owner("agent:firm_x")
    leverage_constraints = book.list_by_type("max_leverage")

    assert {c.constraint_id for c in firm_constraints} == {
        "constraint:firm_lev",
        "constraint:firm_cash",
    }
    assert {c.constraint_id for c in leverage_constraints} == {
        "constraint:firm_lev",
        "constraint:bank_lev",
    }


def test_constraint_record_rejects_invalid_comparison():
    with pytest.raises(ValueError):
        ConstraintRecord(
            constraint_id="constraint:bad",
            owner_id="agent:x",
            constraint_type="max_leverage",
            threshold=1.0,
            comparison="not_a_comparison",
        )


def test_evaluation_rejects_invalid_status():
    with pytest.raises(ValueError):
        ConstraintEvaluation(
            constraint_id="constraint:x",
            owner_id="agent:x",
            as_of_date="2026-01-01",
            status="totally_fine",
            current_value=0.0,
            threshold=0.0,
        )


def test_constraint_book_snapshot_lists_all_sorted():
    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:b",
            owner_id="agent:x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:a",
            owner_id="agent:x",
            constraint_type="min_net_asset_value",
            threshold=0.0,
            comparison=">=",
        )
    )
    snap = book.snapshot()
    assert snap["count"] == 2
    assert [item["constraint_id"] for item in snap["constraints"]] == [
        "constraint:a",
        "constraint:b",
    ]


# ---------------------------------------------------------------------------
# ConstraintEvaluator: the 5 supported types
# ---------------------------------------------------------------------------


def test_max_leverage_ok():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=500.0)
    )

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )

    evaluator = ConstraintEvaluator(book=book, projector=projector)
    evaluations = evaluator.evaluate_owner("agent:firm_x", as_of_date="2026-01-02")

    assert len(evaluations) == 1
    assert evaluations[0].status == "ok"
    assert evaluations[0].current_value == 0.5


def test_max_leverage_warning():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    # 0.6 leverage is above warning_threshold (0.5) but below threshold (0.7)
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=600.0)
    )

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
            warning_threshold=0.5,
        )
    )

    evaluations = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")

    assert evaluations[0].status == "warning"
    assert evaluations[0].current_value == 0.6


def test_max_leverage_breached():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=800.0)
    )

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )

    evaluations = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")

    assert evaluations[0].status == "breached"
    assert evaluations[0].current_value == 0.8


def test_min_net_asset_value_breached():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 100)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=500.0)
    )

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:nav",
            owner_id="agent:firm_x",
            constraint_type="min_net_asset_value",
            threshold=0.0,
            comparison=">=",
        )
    )

    evaluations = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")

    assert evaluations[0].status == "breached"
    assert evaluations[0].current_value == -400.0


def test_min_cash_like_assets_with_registry():
    registry = Registry()
    registry.register(
        RegisteredObject(
            id="asset:cash_jpy", kind="asset", type="cash", space="market"
        )
    )
    ownership, contracts, prices, _, projector = _make_world(registry=registry)
    ownership.add_position("agent:firm_x", "asset:cash_jpy", 50_000)
    prices.set_price("asset:cash_jpy", 1.0, "2026-01-01", "system")

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:cash",
            owner_id="agent:firm_x",
            constraint_type="min_cash_like_assets",
            threshold=10_000.0,
            comparison=">=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:cash_breach",
            owner_id="agent:firm_x",
            constraint_type="min_cash_like_assets",
            threshold=100_000.0,
            comparison=">=",
        )
    )

    evaluations = {
        e.constraint_id: e
        for e in ConstraintEvaluator(book=book, projector=projector).evaluate_owner(
            "agent:firm_x", as_of_date="2026-01-02"
        )
    }
    assert evaluations["constraint:cash"].status == "ok"
    assert evaluations["constraint:cash_breach"].status == "breached"


def test_min_cash_like_assets_unknown_without_registry():
    ownership, contracts, prices, _, projector = _make_world(registry=Registry())
    ownership.add_position("agent:firm_x", "asset:cash", 50_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    # No "cash" type registration -> cash_like_assets is None.

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:cash",
            owner_id="agent:firm_x",
            constraint_type="min_cash_like_assets",
            threshold=10_000.0,
            comparison=">=",
        )
    )

    evaluation = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")[0]

    assert evaluation.status == "unknown"
    assert evaluation.current_value is None
    assert "cash_like_assets" in evaluation.message


def test_min_collateral_coverage_ok_and_breached():
    ownership, contracts, prices, _, projector = _make_world()
    contracts.add_contract(
        _loan(
            contract_id="contract:loan_001",
            lender="agent:bank_a",
            borrower="agent:firm_x",
            principal=500_000.0,
            collateral=("asset:property_a", "asset:property_b"),
        )
    )
    prices.set_price("asset:property_a", 400_000.0, "2026-01-01", "appraisal")
    prices.set_price("asset:property_b", 300_000.0, "2026-01-01", "appraisal")
    # collateral_value = 700_000; debt_principal = 500_000; coverage = 1.4

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:cov_ok",
            owner_id="agent:firm_x",
            constraint_type="min_collateral_coverage",
            threshold=1.2,
            comparison=">=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:cov_breach",
            owner_id="agent:firm_x",
            constraint_type="min_collateral_coverage",
            threshold=2.0,
            comparison=">=",
        )
    )

    evaluations = {
        e.constraint_id: e
        for e in ConstraintEvaluator(book=book, projector=projector).evaluate_owner(
            "agent:firm_x", as_of_date="2026-01-02"
        )
    }
    assert evaluations["constraint:cov_ok"].status == "ok"
    assert abs(evaluations["constraint:cov_ok"].current_value - 1.4) < 1e-9
    assert evaluations["constraint:cov_breach"].status == "breached"


def test_max_single_asset_concentration_ok_and_breached():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:aapl", 100)  # value 15_000
    ownership.add_position("agent:firm_x", "asset:msft", 50)  # value 20_000
    ownership.add_position("agent:firm_x", "asset:cash", 5_000)  # value 5_000
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    prices.set_price("asset:msft", 400.0, "2026-01-01", "exchange")
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    # total = 40_000; max = 20_000 (msft); concentration = 0.5

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:conc_ok",
            owner_id="agent:firm_x",
            constraint_type="max_single_asset_concentration",
            threshold=0.6,
            comparison="<=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:conc_breach",
            owner_id="agent:firm_x",
            constraint_type="max_single_asset_concentration",
            threshold=0.4,
            comparison="<=",
        )
    )

    evaluations = {
        e.constraint_id: e
        for e in ConstraintEvaluator(book=book, projector=projector).evaluate_owner(
            "agent:firm_x", as_of_date="2026-01-02"
        )
    }
    assert evaluations["constraint:conc_ok"].status == "ok"
    assert abs(evaluations["constraint:conc_ok"].current_value - 0.5) < 1e-9
    assert evaluations["constraint:conc_breach"].status == "breached"


def test_max_single_asset_concentration_with_target_ids_filter():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:aapl", 100)  # 15_000
    ownership.add_position("agent:firm_x", "asset:msft", 50)  # 20_000
    prices.set_price("asset:aapl", 150.0, "2026-01-01", "exchange")
    prices.set_price("asset:msft", 400.0, "2026-01-01", "exchange")

    book = ConstraintBook()
    # Restrict the concentration check to AAPL only.
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:conc_aapl",
            owner_id="agent:firm_x",
            constraint_type="max_single_asset_concentration",
            threshold=0.5,
            comparison="<=",
            target_ids=("asset:aapl",),
        )
    )

    evaluation = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")[0]

    assert evaluation.status == "ok"
    # 15_000 / 35_000 = 0.4286
    assert abs(evaluation.current_value - 15_000 / 35_000) < 1e-9


# ---------------------------------------------------------------------------
# Unknown / missing-data paths
# ---------------------------------------------------------------------------


def test_max_leverage_unknown_when_no_assets():
    ownership, contracts, prices, _, projector = _make_world()
    # No positions, no prices -> asset_value=0 -> leverage undefined.
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=500.0)
    )

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )

    evaluation = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")[0]

    assert evaluation.status == "unknown"
    assert evaluation.current_value is None
    assert evaluation.metadata["reason"]


def test_unsupported_constraint_type_returns_unknown():
    _, _, _, _, projector = _make_world()
    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:weird",
            owner_id="agent:firm_x",
            constraint_type="some_future_type",
            threshold=0.0,
            comparison="<=",
        )
    )

    evaluation = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_owner("agent:firm_x", as_of_date="2026-01-02")[0]

    assert evaluation.status == "unknown"
    assert evaluation.metadata["reason"] == "unsupported_constraint_type"


# ---------------------------------------------------------------------------
# Aggregation, snapshot, ledger, no-mutation
# ---------------------------------------------------------------------------


def test_evaluate_all_covers_every_owner_with_constraints():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    ownership.add_position("agent:firm_y", "asset:cash", 500)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:firm_x_nav",
            owner_id="agent:firm_x",
            constraint_type="min_net_asset_value",
            threshold=0.0,
            comparison=">=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:firm_y_nav",
            owner_id="agent:firm_y",
            constraint_type="min_net_asset_value",
            threshold=0.0,
            comparison=">=",
        )
    )

    evaluations = ConstraintEvaluator(
        book=book, projector=projector
    ).evaluate_all(as_of_date="2026-01-02")

    owner_ids = {e.owner_id for e in evaluations}
    assert owner_ids == {"agent:firm_x", "agent:firm_y"}


def test_evaluator_snapshot_returns_serializable_evaluations():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:nav",
            owner_id="agent:firm_x",
            constraint_type="min_net_asset_value",
            threshold=0.0,
            comparison=">=",
        )
    )

    snap = ConstraintEvaluator(book=book, projector=projector).snapshot(
        as_of_date="2026-01-02"
    )
    assert snap["count"] == 1
    assert snap["evaluations"][0]["status"] == "ok"
    assert snap["evaluations"][0]["constraint_id"] == "constraint:nav"


def test_constraint_added_and_evaluated_are_recorded_to_ledger():
    ledger = Ledger()
    ownership, contracts, prices, _, projector = _make_world(ledger=ledger)
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")

    book = ConstraintBook(ledger=ledger, clock=Clock(current_date=date(2026, 1, 1)))
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:nav",
            owner_id="agent:firm_x",
            constraint_type="min_net_asset_value",
            threshold=0.0,
            comparison=">=",
        )
    )

    evaluator = ConstraintEvaluator(book=book, projector=projector, ledger=ledger)
    evaluator.evaluate_owner("agent:firm_x", as_of_date="2026-01-02")

    added = ledger.filter(event_type="constraint_added")
    evaluated = ledger.filter(event_type="constraint_evaluated")
    assert len(added) == 2
    assert len(evaluated) == 2
    assert {r.payload["status"] for r in evaluated} == {"ok"}


def test_evaluator_does_not_mutate_source_books():
    ownership, contracts, prices, _, projector = _make_world()
    ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=500.0)
    )

    book = ConstraintBook()
    book.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )

    ownership_before = ownership.snapshot()
    contracts_before = contracts.snapshot()
    prices_before = prices.snapshot()
    constraints_before = book.snapshot()

    evaluator = ConstraintEvaluator(book=book, projector=projector)
    evaluator.evaluate_owner("agent:firm_x", as_of_date="2026-01-02")
    evaluator.evaluate_all(as_of_date="2026-01-03")

    assert ownership.snapshot() == ownership_before
    assert contracts.snapshot() == contracts_before
    assert prices.snapshot() == prices_before
    assert book.snapshot() == constraints_before


def test_kernel_exposes_constraints_and_evaluator():
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.ownership.add_position("agent:firm_x", "asset:cash", 1_000)
    kernel.prices.set_price("asset:cash", 1.0, "2026-01-01", "system")
    kernel.contracts.add_contract(
        _loan(lender="agent:bank_a", borrower="agent:firm_x", principal=500.0)
    )
    kernel.constraints.add_constraint(
        ConstraintRecord(
            constraint_id="constraint:lev",
            owner_id="agent:firm_x",
            constraint_type="max_leverage",
            threshold=0.7,
            comparison="<=",
        )
    )

    evaluations = kernel.constraint_evaluator.evaluate_all()
    assert len(evaluations) == 1
    assert evaluations[0].status == "ok"
    assert evaluations[0].current_value == 0.5
    # Default as_of_date comes from kernel.clock.
    assert evaluations[0].as_of_date == "2026-01-01"
