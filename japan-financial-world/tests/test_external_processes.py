from datetime import date

import pytest

from world.clock import Clock
from world.external_processes import (
    DuplicateObservationError,
    DuplicateProcessError,
    DuplicateScenarioPathError,
    ExternalFactorObservation,
    ExternalFactorProcess,
    ExternalProcessBook,
    ExternalScenarioPath,
    ExternalScenarioPoint,
    UnknownObservationError,
    UnknownProcessError,
    UnknownScenarioPathError,
)
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


def _process(
    process_id: str = "process:reference_fx_constant",
    *,
    factor_id: str = "factor:reference_usd_jpy",
    factor_type: str = "fx_rate",
    process_type: str = "constant",
    unit: str = "usd_per_jpy",
    base_value: float | None = 0.007,
    status: str = "active",
    metadata: dict | None = None,
) -> ExternalFactorProcess:
    return ExternalFactorProcess(
        process_id=process_id,
        factor_id=factor_id,
        factor_type=factor_type,
        process_type=process_type,
        unit=unit,
        base_value=base_value,
        status=status,
        metadata=metadata or {},
    )


def _observation(
    observation_id: str = "observation:001",
    *,
    factor_id: str = "factor:reference_usd_jpy",
    as_of_date: str = "2026-01-01",
    value: float = 0.007,
    unit: str = "usd_per_jpy",
    source_id: str = "system",
    phase_id: str | None = None,
    process_id: str | None = None,
    confidence: float = 1.0,
    related_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> ExternalFactorObservation:
    return ExternalFactorObservation(
        observation_id=observation_id,
        factor_id=factor_id,
        as_of_date=as_of_date,
        value=value,
        unit=unit,
        source_id=source_id,
        phase_id=phase_id,
        process_id=process_id,
        confidence=confidence,
        related_ids=related_ids,
        metadata=metadata or {},
    )


def _point(
    *,
    factor_id: str = "factor:reference_usd_jpy",
    as_of_date: str = "2026-01-01",
    value: float = 0.007,
    unit: str = "usd_per_jpy",
    phase_id: str | None = None,
    metadata: dict | None = None,
) -> ExternalScenarioPoint:
    return ExternalScenarioPoint(
        factor_id=factor_id,
        as_of_date=as_of_date,
        value=value,
        unit=unit,
        phase_id=phase_id,
        metadata=metadata or {},
    )


def _path(
    path_id: str = "path:reference_fx_q1",
    *,
    factor_id: str = "factor:reference_usd_jpy",
    points: tuple[ExternalScenarioPoint, ...] | None = None,
    source_id: str = "reference_scenario_designer",
    metadata: dict | None = None,
) -> ExternalScenarioPath:
    if points is None:
        points = (
            _point(as_of_date="2026-01-01", value=0.0070),
            _point(as_of_date="2026-02-01", value=0.0072),
            _point(as_of_date="2026-03-01", value=0.0068),
        )
    return ExternalScenarioPath(
        path_id=path_id,
        factor_id=factor_id,
        points=points,
        source_id=source_id,
        metadata=metadata or {},
    )


def _book(with_ledger: bool = False) -> ExternalProcessBook:
    if with_ledger:
        return ExternalProcessBook(
            ledger=Ledger(),
            clock=Clock(current_date=date(2026, 1, 1)),
        )
    return ExternalProcessBook()


# ---------------------------------------------------------------------------
# ExternalFactorProcess dataclass
# ---------------------------------------------------------------------------


def test_external_factor_process_carries_required_fields():
    p = _process()
    assert p.process_id == "process:reference_fx_constant"
    assert p.factor_id == "factor:reference_usd_jpy"
    assert p.process_type == "constant"
    assert p.base_value == 0.007


def test_external_factor_process_rejects_missing_required():
    with pytest.raises(ValueError):
        _process(process_id="")
    with pytest.raises(ValueError):
        _process(factor_id="")
    with pytest.raises(ValueError):
        _process(process_type="")


def test_external_factor_process_allows_none_base_value():
    """Non-constant processes (e.g., random_walk) may not have a base_value."""
    p = _process(process_type="random_walk", base_value=None)
    assert p.base_value is None


def test_external_factor_process_is_immutable():
    p = _process()
    with pytest.raises(Exception):
        p.base_value = 0.01  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExternalFactorObservation dataclass
# ---------------------------------------------------------------------------


def test_external_factor_observation_carries_required_fields():
    o = _observation()
    assert o.observation_id == "observation:001"
    assert o.value == 0.007
    assert o.confidence == 1.0
    assert o.phase_id is None
    assert o.process_id is None


def test_external_factor_observation_rejects_missing_required():
    with pytest.raises(ValueError):
        _observation(observation_id="")
    with pytest.raises(ValueError):
        _observation(factor_id="")
    with pytest.raises(ValueError):
        _observation(as_of_date="")
    with pytest.raises(ValueError):
        _observation(source_id="")


def test_external_factor_observation_rejects_invalid_confidence():
    with pytest.raises(ValueError):
        _observation(confidence=1.5)
    with pytest.raises(ValueError):
        _observation(confidence=-0.1)


def test_external_factor_observation_is_immutable():
    o = _observation()
    with pytest.raises(Exception):
        o.value = 0.01  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ExternalScenarioPoint / ExternalScenarioPath dataclasses
# ---------------------------------------------------------------------------


def test_scenario_point_carries_fields():
    p = _point()
    assert p.factor_id == "factor:reference_usd_jpy"
    assert p.as_of_date == "2026-01-01"


def test_scenario_path_validates_point_factor_match():
    """Every scenario point must share the path's factor_id."""
    with pytest.raises(ValueError):
        ExternalScenarioPath(
            path_id="path:bad",
            factor_id="factor:a",
            points=(
                _point(factor_id="factor:a"),
                _point(factor_id="factor:b"),  # wrong factor
            ),
            source_id="any",
        )


def test_scenario_path_find_point_matches_date_and_phase():
    path = _path(
        points=(
            _point(as_of_date="2026-01-01", value=1.0, phase_id=None),
            _point(as_of_date="2026-01-01", value=2.0, phase_id="opening_auction"),
            _point(as_of_date="2026-02-01", value=3.0, phase_id=None),
        )
    )
    assert path.find_point("2026-01-01", None).value == 1.0
    assert path.find_point("2026-01-01", "opening_auction").value == 2.0
    assert path.find_point("2026-02-01").value == 3.0
    assert path.find_point("2026-03-01") is None
    assert path.find_point("2026-01-01", "closing_auction") is None


# ---------------------------------------------------------------------------
# ExternalProcessBook — process CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_process():
    book = _book()
    p = _process()
    book.add_process(p)
    assert book.get_process("process:reference_fx_constant") is p


def test_get_process_raises_for_unknown():
    book = _book()
    with pytest.raises(UnknownProcessError):
        book.get_process("process:nope")


def test_duplicate_process_id_rejected():
    book = _book()
    book.add_process(_process())
    with pytest.raises(DuplicateProcessError):
        book.add_process(_process())


def test_list_processes_by_factor_filters_correctly():
    book = _book()
    book.add_process(_process(process_id="process:a", factor_id="factor:fx"))
    book.add_process(_process(process_id="process:b", factor_id="factor:fx"))
    book.add_process(_process(process_id="process:c", factor_id="factor:oil"))

    fx = book.list_processes_by_factor("factor:fx")
    oil = book.list_processes_by_factor("factor:oil")
    none = book.list_processes_by_factor("factor:unknown")

    assert {p.process_id for p in fx} == {"process:a", "process:b"}
    assert {p.process_id for p in oil} == {"process:c"}
    assert none == ()


def test_list_processes_by_type_filters_correctly():
    book = _book()
    book.add_process(_process(process_id="process:a", process_type="constant"))
    book.add_process(_process(process_id="process:b", process_type="constant"))
    book.add_process(
        _process(process_id="process:c", process_type="random_walk", base_value=None)
    )

    constants = book.list_processes_by_type("constant")
    rw = book.list_processes_by_type("random_walk")

    assert {p.process_id for p in constants} == {"process:a", "process:b"}
    assert {p.process_id for p in rw} == {"process:c"}


# ---------------------------------------------------------------------------
# ExternalProcessBook — observation CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_observation():
    book = _book()
    o = _observation()
    book.add_observation(o)
    assert book.get_observation("observation:001") is o


def test_get_observation_raises_for_unknown():
    book = _book()
    with pytest.raises(UnknownObservationError):
        book.get_observation("observation:nope")


def test_duplicate_observation_id_rejected():
    book = _book()
    book.add_observation(_observation())
    with pytest.raises(DuplicateObservationError):
        book.add_observation(_observation())


def test_list_observations_by_factor_filters_correctly():
    book = _book()
    book.add_observation(_observation(observation_id="obs:1", factor_id="factor:fx"))
    book.add_observation(_observation(observation_id="obs:2", factor_id="factor:fx"))
    book.add_observation(
        _observation(observation_id="obs:3", factor_id="factor:oil", value=80.0)
    )

    fx = book.list_observations_by_factor("factor:fx")
    oil = book.list_observations_by_factor("factor:oil")

    assert {o.observation_id for o in fx} == {"obs:1", "obs:2"}
    assert {o.observation_id for o in oil} == {"obs:3"}


def test_latest_observation_picks_highest_as_of_date():
    book = _book()
    book.add_observation(
        _observation(
            observation_id="obs:earlier",
            factor_id="factor:fx",
            as_of_date="2026-01-01",
            value=1.0,
        )
    )
    book.add_observation(
        _observation(
            observation_id="obs:later",
            factor_id="factor:fx",
            as_of_date="2026-06-01",
            value=2.0,
        )
    )
    book.add_observation(
        _observation(
            observation_id="obs:other",
            factor_id="factor:oil",
            as_of_date="2027-01-01",
            value=99.0,
        )
    )

    latest = book.latest_observation("factor:fx")
    assert latest is not None
    assert latest.observation_id == "obs:later"
    assert latest.value == 2.0


def test_latest_observation_returns_none_for_unknown_factor():
    book = _book()
    book.add_observation(_observation(factor_id="factor:fx"))
    assert book.latest_observation("factor:unknown") is None


# ---------------------------------------------------------------------------
# ExternalProcessBook — scenario path CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_scenario_path():
    book = _book()
    path = _path()
    book.add_scenario_path(path)
    assert book.get_scenario_path("path:reference_fx_q1") is path


def test_get_scenario_path_raises_for_unknown():
    book = _book()
    with pytest.raises(UnknownScenarioPathError):
        book.get_scenario_path("path:nope")


def test_duplicate_scenario_path_rejected():
    book = _book()
    book.add_scenario_path(_path())
    with pytest.raises(DuplicateScenarioPathError):
        book.add_scenario_path(_path())


def test_get_scenario_point_by_date():
    book = _book()
    book.add_scenario_path(_path())
    point = book.get_scenario_point("path:reference_fx_q1", "2026-02-01")
    assert point is not None
    assert point.value == 0.0072


def test_get_scenario_point_returns_none_for_missing_date():
    book = _book()
    book.add_scenario_path(_path())
    assert book.get_scenario_point("path:reference_fx_q1", "2027-01-01") is None


def test_get_scenario_point_raises_for_unknown_path():
    book = _book()
    with pytest.raises(UnknownScenarioPathError):
        book.get_scenario_point("path:nope", "2026-01-01")


# ---------------------------------------------------------------------------
# Helpers — minimal generation
# ---------------------------------------------------------------------------


def test_create_constant_observation_uses_process_base_value():
    book = _book()
    book.add_process(_process(base_value=0.007))

    obs = book.create_constant_observation(
        "process:reference_fx_constant", "2026-01-15"
    )
    assert obs.value == 0.007
    assert obs.factor_id == "factor:reference_usd_jpy"
    assert obs.process_id == "process:reference_fx_constant"
    assert obs.as_of_date == "2026-01-15"
    assert obs.unit == "usd_per_jpy"


def test_create_constant_observation_id_is_deterministic():
    book = _book()
    book.add_process(_process())

    obs = book.create_constant_observation(
        "process:reference_fx_constant", "2026-01-15", phase_id="opening_auction"
    )
    assert (
        obs.observation_id
        == "observation:process:reference_fx_constant:2026-01-15:opening_auction"
    )


def test_create_constant_observation_rejects_non_constant_process():
    book = _book()
    book.add_process(
        _process(process_type="random_walk", base_value=None)
    )
    with pytest.raises(ValueError, match="constant"):
        book.create_constant_observation(
            "process:reference_fx_constant", "2026-01-15"
        )


def test_create_constant_observation_rejects_missing_base_value():
    book = _book()
    book.add_process(_process(base_value=None))
    with pytest.raises(ValueError, match="base_value"):
        book.create_constant_observation(
            "process:reference_fx_constant", "2026-01-15"
        )


def test_create_constant_observation_double_call_rejects_as_duplicate():
    book = _book()
    book.add_process(_process())
    book.create_constant_observation(
        "process:reference_fx_constant", "2026-01-15"
    )
    with pytest.raises(DuplicateObservationError):
        book.create_constant_observation(
            "process:reference_fx_constant", "2026-01-15"
        )


def test_create_observation_from_path_replays_point():
    book = _book()
    book.add_scenario_path(_path())

    obs = book.create_observation_from_path(
        "path:reference_fx_q1", "2026-02-01"
    )
    assert obs is not None
    assert obs.value == 0.0072
    assert obs.factor_id == "factor:reference_usd_jpy"
    assert obs.source_id == "reference_scenario_designer"  # from path
    assert obs.related_ids == ("path:reference_fx_q1",)
    assert obs.metadata["source_path_id"] == "path:reference_fx_q1"


def test_create_observation_from_path_returns_none_for_missing_date():
    book = _book()
    book.add_scenario_path(_path())

    result = book.create_observation_from_path(
        "path:reference_fx_q1", "2027-01-01"
    )
    assert result is None
    # No observation was written for the missing point.
    assert book.list_observations_by_factor("factor:reference_usd_jpy") == ()


def test_create_observation_from_path_raises_for_unknown_path():
    book = _book()
    with pytest.raises(UnknownScenarioPathError):
        book.create_observation_from_path("path:nope", "2026-01-01")


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_lists_all_categories_sorted():
    book = _book()
    book.add_process(_process(process_id="process:b"))
    book.add_process(
        _process(process_id="process:a", factor_id="factor:other")
    )
    book.add_observation(_observation(observation_id="obs:b"))
    book.add_observation(_observation(observation_id="obs:a"))
    book.add_scenario_path(_path(path_id="path:b"))
    book.add_scenario_path(_path(path_id="path:a"))

    snap = book.snapshot()
    assert snap["process_count"] == 2
    assert snap["observation_count"] == 2
    assert snap["scenario_path_count"] == 2
    assert [p["process_id"] for p in snap["processes"]] == [
        "process:a",
        "process:b",
    ]
    assert [o["observation_id"] for o in snap["observations"]] == [
        "obs:a",
        "obs:b",
    ]
    assert [p["path_id"] for p in snap["scenario_paths"]] == [
        "path:a",
        "path:b",
    ]


def test_snapshot_returns_empty_structure_for_empty_book():
    snap = ExternalProcessBook().snapshot()
    assert snap == {
        "process_count": 0,
        "observation_count": 0,
        "scenario_path_count": 0,
        "processes": [],
        "observations": [],
        "scenario_paths": [],
    }


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_add_process_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_process(_process())

    records = book.ledger.filter(event_type="external_process_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "process:reference_fx_constant"
    assert record.target == "factor:reference_usd_jpy"
    assert record.payload["process_type"] == "constant"
    assert record.simulation_date == "2026-01-01"
    assert record.space_id == "external_processes"


def test_add_observation_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_observation(_observation(value=0.0075, source_id="reference_feed"))

    records = book.ledger.filter(event_type="external_observation_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "observation:001"
    assert record.target == "factor:reference_usd_jpy"
    assert record.source == "reference_feed"
    assert record.payload["value"] == 0.0075


def test_add_scenario_path_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_scenario_path(_path())

    records = book.ledger.filter(event_type="external_scenario_path_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "path:reference_fx_q1"
    assert record.target == "factor:reference_usd_jpy"
    assert record.payload["point_count"] == 3


def test_add_does_not_record_when_no_ledger():
    book = ExternalProcessBook()
    book.add_process(_process())
    book.add_observation(_observation())
    book.add_scenario_path(_path())
    # Nothing crashes; ledger is None.
    assert book.get_process("process:reference_fx_constant") is not None


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def test_external_process_book_does_not_mutate_other_books():
    """
    The external-process layer must not touch any other source-of-
    truth book. Per the v1.4 design rule, observations are recorded
    here; their downstream effect on PriceBook, SignalBook, etc. is a
    later-milestone concern.
    """
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.ownership.add_position("agent:alice", "asset:x", 100)
    kernel.prices.set_price("asset:x", 50.0, "2026-01-01", "exchange")

    ownership_before = kernel.ownership.snapshot()
    contracts_before = kernel.contracts.snapshot()
    prices_before = kernel.prices.snapshot()
    constraints_before = kernel.constraints.snapshot()
    signals_before = kernel.signals.snapshot()
    valuations_before = kernel.valuations.snapshot()
    institutions_before = kernel.institutions.snapshot()

    # Run a full slate of v1.4 operations.
    kernel.external_processes.add_process(_process())
    kernel.external_processes.create_constant_observation(
        "process:reference_fx_constant", "2026-01-15"
    )
    kernel.external_processes.add_scenario_path(_path())
    kernel.external_processes.create_observation_from_path(
        "path:reference_fx_q1", "2026-02-01"
    )
    kernel.external_processes.snapshot()

    # All other books are untouched.
    assert kernel.ownership.snapshot() == ownership_before
    assert kernel.contracts.snapshot() == contracts_before
    assert kernel.prices.snapshot() == prices_before
    assert kernel.constraints.snapshot() == constraints_before
    assert kernel.signals.snapshot() == signals_before
    assert kernel.valuations.snapshot() == valuations_before
    assert kernel.institutions.snapshot() == institutions_before


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_external_processes_with_default_wiring():
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.external_processes.add_process(_process())

    assert kernel.external_processes.ledger is kernel.ledger
    assert kernel.external_processes.clock is kernel.clock
    assert (
        len(kernel.ledger.filter(event_type="external_process_added")) == 1
    )
