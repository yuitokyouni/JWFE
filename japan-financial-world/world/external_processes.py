from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


class ExternalProcessError(Exception):
    """Base class for external-process layer errors."""


class DuplicateProcessError(ExternalProcessError):
    """Raised when a process_id is added twice."""


class DuplicateObservationError(ExternalProcessError):
    """Raised when an observation_id is added twice."""


class DuplicateScenarioPathError(ExternalProcessError):
    """Raised when a scenario path_id is added twice."""


class UnknownProcessError(ExternalProcessError, KeyError):
    """Raised when a process_id is not found."""


class UnknownObservationError(ExternalProcessError, KeyError):
    """Raised when an observation_id is not found."""


class UnknownScenarioPathError(ExternalProcessError, KeyError):
    """Raised when a scenario path_id is not found."""


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExternalFactorProcess:
    """
    Process definition for an external factor.

    A process describes *how the factor is expected to evolve over
    time* — but v1.4 does not actually evolve anything stochastically
    beyond the two minimal helpers (constant + scenario path replay).
    A process record is the slot a future v2 / v3 calibration would
    populate with concrete parameters; v1.4 stores the slot's identity
    and the bookkeeping around it.

    process_type is a free-form string. Suggested labels:
    ``"constant"``, ``"manual"``, ``"scenario_path"``,
    ``"historical_replay"``, ``"random_walk"``, ``"mean_reverting"``,
    ``"regime_switching"``. v1.4 only ships generation logic for
    ``"constant"`` (via ``base_value``) and ``"scenario_path"`` (via
    a paired scenario path). Other process types are storable but
    inert — their generation belongs to later milestones.
    """

    process_id: str
    factor_id: str
    factor_type: str = "unspecified"
    process_type: str = "constant"
    unit: str = "unspecified"
    base_value: float | None = None
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.process_id:
            raise ValueError("process_id is required")
        if not self.factor_id:
            raise ValueError("factor_id is required")
        if not self.process_type:
            raise ValueError("process_type is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "process_id": self.process_id,
            "factor_id": self.factor_id,
            "factor_type": self.factor_type,
            "process_type": self.process_type,
            "unit": self.unit,
            "base_value": self.base_value,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExternalFactorObservation:
    """
    A recorded observation of an external factor.

    An observation is *what the world saw at a moment in time* — not
    what any domestic agent thought about it. Observations are append-
    only and, like prices, never overwritten. v1.4 stores observations
    but does not propagate them: domestic agents that read external
    factors do so explicitly through ``ExternalProcessBook.latest_observation``
    or by querying observations directly.

    ``process_id`` is optional because not every observation comes from
    a registered process — a manually entered "we saw X" observation is
    valid. When present, it points back to the process that produced
    the observation (e.g., a constant-process helper or a scenario-path
    helper).
    """

    observation_id: str
    factor_id: str
    as_of_date: str
    value: float
    unit: str
    source_id: str
    phase_id: str | None = None
    process_id: str | None = None
    confidence: float = 1.0
    related_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("observation_id is required")
        if not self.factor_id:
            raise ValueError("factor_id is required")
        if not self.as_of_date:
            raise ValueError("as_of_date is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "as_of_date", _coerce_iso_date(self.as_of_date))
        object.__setattr__(self, "related_ids", tuple(self.related_ids))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "factor_id": self.factor_id,
            "as_of_date": self.as_of_date,
            "value": self.value,
            "unit": self.unit,
            "source_id": self.source_id,
            "phase_id": self.phase_id,
            "process_id": self.process_id,
            "confidence": self.confidence,
            "related_ids": list(self.related_ids),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExternalScenarioPoint:
    """
    A single declared point in a scenario path.

    Scenario points are the building blocks of deterministic replay:
    a path is a tuple of points, and the v1.4 helper
    ``create_observation_from_path`` looks up a point by
    ``(as_of_date, phase_id)`` to create a corresponding observation.

    ``factor_id`` on the point must match the parent path's
    ``factor_id`` (the path validates this on construction).
    """

    factor_id: str
    as_of_date: str
    value: float
    unit: str
    phase_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.factor_id:
            raise ValueError("factor_id is required")
        if not self.as_of_date:
            raise ValueError("as_of_date is required")
        object.__setattr__(self, "as_of_date", _coerce_iso_date(self.as_of_date))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_id": self.factor_id,
            "as_of_date": self.as_of_date,
            "value": self.value,
            "unit": self.unit,
            "phase_id": self.phase_id,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ExternalScenarioPath:
    """
    A deterministic sequence of scenario points for one factor.

    A scenario path lets the world replay a known external trajectory
    without computing it: the points are stored verbatim, and the
    helper ``create_observation_from_path`` looks them up by date and
    phase. This is the v1.4 mechanism for "we want this factor to
    follow exactly this path" tests and reference cases. v2 / v3 may
    populate paths from real Japan public or proprietary data; v1.4
    stores any caller-provided sequence without interpreting its
    origin.

    All points must share the path's ``factor_id``. Points are not
    required to be sorted; the lookup is a linear scan keyed on
    ``(as_of_date, phase_id)``.
    """

    path_id: str
    factor_id: str
    points: tuple[ExternalScenarioPoint, ...]
    source_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.path_id:
            raise ValueError("path_id is required")
        if not self.factor_id:
            raise ValueError("factor_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        points = tuple(self.points)
        for point in points:
            if point.factor_id != self.factor_id:
                raise ValueError(
                    f"scenario point factor_id {point.factor_id!r} does not "
                    f"match path factor_id {self.factor_id!r}"
                )
        object.__setattr__(self, "points", points)
        object.__setattr__(self, "metadata", dict(self.metadata))

    def find_point(
        self,
        as_of_date: date | str,
        phase_id: str | None = None,
    ) -> ExternalScenarioPoint | None:
        """
        Return the point matching ``(as_of_date, phase_id)``, or
        ``None`` if no point matches. ``phase_id=None`` matches a
        point whose ``phase_id`` is also ``None``; mismatched phases
        do not match.
        """
        target = _coerce_iso_date(as_of_date)
        for point in self.points:
            if point.as_of_date == target and point.phase_id == phase_id:
                return point
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_id": self.path_id,
            "factor_id": self.factor_id,
            "source_id": self.source_id,
            "points": [point.to_dict() for point in self.points],
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# ExternalProcessBook
# ---------------------------------------------------------------------------


@dataclass
class ExternalProcessBook:
    """
    Storage for external factor processes, observations, and scenario
    paths.

    The book is append-only, emits ledger records on mutation, and
    refuses to mutate any other source-of-truth book. v1.4 ships
    minimal generation logic — ``create_constant_observation`` and
    ``create_observation_from_path`` — and explicitly does **not**
    implement random walks, mean reversion, regime switching, or any
    other stochastic process. Those belong to later milestones.

    Cross-references (``factor_id`` on processes / observations,
    ``process_id`` on observations) are recorded as data and **not**
    validated for resolution. ExternalSpace's ``ExternalFactorState``
    is the natural place to register factors, but v1.4 does not
    require it; the cross-reference rule from v0 / v1 holds.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _processes: dict[str, ExternalFactorProcess] = field(default_factory=dict)
    _processes_by_factor: dict[str, list[str]] = field(default_factory=dict)
    _observations: dict[str, ExternalFactorObservation] = field(default_factory=dict)
    _observations_by_factor: dict[str, list[str]] = field(default_factory=dict)
    _scenario_paths: dict[str, ExternalScenarioPath] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Process CRUD
    # ------------------------------------------------------------------

    def add_process(self, process: ExternalFactorProcess) -> ExternalFactorProcess:
        if process.process_id in self._processes:
            raise DuplicateProcessError(
                f"Duplicate process_id: {process.process_id}"
            )
        self._processes[process.process_id] = process
        self._processes_by_factor.setdefault(process.factor_id, []).append(
            process.process_id
        )

        if self.ledger is not None:
            self.ledger.append(
                event_type="external_process_added",
                simulation_date=self._now(),
                object_id=process.process_id,
                target=process.factor_id,
                payload={
                    "process_id": process.process_id,
                    "factor_id": process.factor_id,
                    "factor_type": process.factor_type,
                    "process_type": process.process_type,
                    "unit": process.unit,
                    "base_value": process.base_value,
                    "status": process.status,
                },
                space_id="external_processes",
            )
        return process

    def get_process(self, process_id: str) -> ExternalFactorProcess:
        try:
            return self._processes[process_id]
        except KeyError as exc:
            raise UnknownProcessError(
                f"Process not found: {process_id!r}"
            ) from exc

    def list_processes_by_factor(
        self, factor_id: str
    ) -> tuple[ExternalFactorProcess, ...]:
        ids = self._processes_by_factor.get(factor_id, [])
        return tuple(self._processes[pid] for pid in ids)

    def list_processes_by_type(
        self, process_type: str
    ) -> tuple[ExternalFactorProcess, ...]:
        return tuple(
            p
            for p in self._processes.values()
            if p.process_type == process_type
        )

    def all_processes(self) -> tuple[ExternalFactorProcess, ...]:
        return tuple(self._processes.values())

    # ------------------------------------------------------------------
    # Observation CRUD
    # ------------------------------------------------------------------

    def add_observation(
        self, observation: ExternalFactorObservation
    ) -> ExternalFactorObservation:
        if observation.observation_id in self._observations:
            raise DuplicateObservationError(
                f"Duplicate observation_id: {observation.observation_id}"
            )
        self._observations[observation.observation_id] = observation
        self._observations_by_factor.setdefault(
            observation.factor_id, []
        ).append(observation.observation_id)

        if self.ledger is not None:
            self.ledger.append(
                event_type="external_observation_added",
                simulation_date=observation.as_of_date,
                object_id=observation.observation_id,
                target=observation.factor_id,
                source=observation.source_id,
                payload={
                    "observation_id": observation.observation_id,
                    "factor_id": observation.factor_id,
                    "as_of_date": observation.as_of_date,
                    "phase_id": observation.phase_id,
                    "value": observation.value,
                    "unit": observation.unit,
                    "source_id": observation.source_id,
                    "process_id": observation.process_id,
                    "related_ids": list(observation.related_ids),
                },
                space_id="external_processes",
                confidence=observation.confidence,
            )
        return observation

    def get_observation(
        self, observation_id: str
    ) -> ExternalFactorObservation:
        try:
            return self._observations[observation_id]
        except KeyError as exc:
            raise UnknownObservationError(
                f"Observation not found: {observation_id!r}"
            ) from exc

    def list_observations_by_factor(
        self, factor_id: str
    ) -> tuple[ExternalFactorObservation, ...]:
        ids = self._observations_by_factor.get(factor_id, [])
        return tuple(self._observations[oid] for oid in ids)

    def latest_observation(
        self, factor_id: str
    ) -> ExternalFactorObservation | None:
        """
        Return the observation for ``factor_id`` with the highest
        ``as_of_date``. ISO date strings compare lexicographically,
        so this is a date-correct max. Ties (same date) break to the
        most recently added observation.
        """
        ids = self._observations_by_factor.get(factor_id, [])
        if not ids:
            return None
        candidates = [self._observations[oid] for oid in ids]
        latest = candidates[0]
        for obs in candidates[1:]:
            if obs.as_of_date >= latest.as_of_date:
                latest = obs
        return latest

    def all_observations(self) -> tuple[ExternalFactorObservation, ...]:
        return tuple(self._observations.values())

    # ------------------------------------------------------------------
    # Scenario path CRUD
    # ------------------------------------------------------------------

    def add_scenario_path(
        self, path: ExternalScenarioPath
    ) -> ExternalScenarioPath:
        if path.path_id in self._scenario_paths:
            raise DuplicateScenarioPathError(
                f"Duplicate path_id: {path.path_id}"
            )
        self._scenario_paths[path.path_id] = path

        if self.ledger is not None:
            self.ledger.append(
                event_type="external_scenario_path_added",
                simulation_date=self._now(),
                object_id=path.path_id,
                target=path.factor_id,
                source=path.source_id,
                payload={
                    "path_id": path.path_id,
                    "factor_id": path.factor_id,
                    "source_id": path.source_id,
                    "point_count": len(path.points),
                },
                space_id="external_processes",
            )
        return path

    def get_scenario_path(self, path_id: str) -> ExternalScenarioPath:
        try:
            return self._scenario_paths[path_id]
        except KeyError as exc:
            raise UnknownScenarioPathError(
                f"Scenario path not found: {path_id!r}"
            ) from exc

    def get_scenario_point(
        self,
        path_id: str,
        as_of_date: date | str,
        phase_id: str | None = None,
    ) -> ExternalScenarioPoint | None:
        """
        Look up a scenario point on a path by ``(as_of_date, phase_id)``.

        Raises ``UnknownScenarioPathError`` if the path itself does
        not exist. Returns ``None`` if no point matches the date and
        phase.
        """
        path = self.get_scenario_path(path_id)
        return path.find_point(as_of_date, phase_id)

    def all_scenario_paths(self) -> tuple[ExternalScenarioPath, ...]:
        return tuple(self._scenario_paths.values())

    # ------------------------------------------------------------------
    # Helpers — minimal generation
    # ------------------------------------------------------------------

    def create_constant_observation(
        self,
        process_id: str,
        as_of_date: date | str,
        phase_id: str | None = None,
        *,
        source_id: str = "system",
        confidence: float = 1.0,
    ) -> ExternalFactorObservation:
        """
        Build and store an observation from a constant-typed process.

        The process must have ``process_type == "constant"`` and a
        non-None ``base_value``. The observation is given a
        deterministic id derived from process / date / phase so
        repeated calls with the same arguments are detected as
        duplicates.
        """
        process = self.get_process(process_id)
        if process.process_type != "constant":
            raise ValueError(
                f"process {process_id!r} has process_type "
                f"{process.process_type!r}, expected 'constant'"
            )
        if process.base_value is None:
            raise ValueError(
                f"process {process_id!r} has no base_value; cannot "
                f"create a constant observation"
            )

        as_of = _coerce_iso_date(as_of_date)
        phase_token = phase_id if phase_id is not None else "no_phase"
        observation_id = f"observation:{process_id}:{as_of}:{phase_token}"

        observation = ExternalFactorObservation(
            observation_id=observation_id,
            factor_id=process.factor_id,
            as_of_date=as_of,
            phase_id=phase_id,
            value=process.base_value,
            unit=process.unit,
            source_id=source_id,
            process_id=process_id,
            confidence=confidence,
        )
        return self.add_observation(observation)

    def create_observation_from_path(
        self,
        path_id: str,
        as_of_date: date | str,
        phase_id: str | None = None,
        *,
        source_id: str | None = None,
        confidence: float = 1.0,
    ) -> ExternalFactorObservation | None:
        """
        Build and store an observation from a scenario path point.

        Looks up the point matching ``(as_of_date, phase_id)`` on the
        path. If no point matches, returns ``None`` without writing
        to the book or the ledger. ``source_id`` defaults to the
        path's declared ``source_id``.

        Raises ``UnknownScenarioPathError`` if the path itself does
        not exist.
        """
        path = self.get_scenario_path(path_id)
        point = path.find_point(as_of_date, phase_id)
        if point is None:
            return None

        as_of = _coerce_iso_date(as_of_date)
        phase_token = phase_id if phase_id is not None else "no_phase"
        observation_id = f"observation:from_path:{path_id}:{as_of}:{phase_token}"

        observation = ExternalFactorObservation(
            observation_id=observation_id,
            factor_id=point.factor_id,
            as_of_date=point.as_of_date,
            phase_id=point.phase_id,
            value=point.value,
            unit=point.unit,
            source_id=source_id or path.source_id,
            process_id=None,
            confidence=confidence,
            related_ids=(path_id,),
            metadata={"source_path_id": path_id},
        )
        return self.add_observation(observation)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        processes = sorted(
            (p.to_dict() for p in self._processes.values()),
            key=lambda item: item["process_id"],
        )
        observations = sorted(
            (o.to_dict() for o in self._observations.values()),
            key=lambda item: item["observation_id"],
        )
        scenario_paths = sorted(
            (p.to_dict() for p in self._scenario_paths.values()),
            key=lambda item: item["path_id"],
        )
        return {
            "process_count": len(processes),
            "observation_count": len(observations),
            "scenario_path_count": len(scenario_paths),
            "processes": processes,
            "observations": observations,
            "scenario_paths": scenario_paths,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
