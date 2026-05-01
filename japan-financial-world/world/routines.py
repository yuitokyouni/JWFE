"""
v1.8.4 RoutineBook + RoutineRunRecord.

Implements the kernel-level book that stores **scheduled
endogenous routine specifications** and **auditable run records**,
per the v1.8.1 Endogenous Reference Dynamics design
(``docs/v1_endogenous_reference_dynamics_design.md``).

Scope discipline (v1.8.4):

- ``RoutineBook`` stores ``RoutineSpec`` and ``RoutineRunRecord``
  entries. It does **not** schedule, fire, execute, or otherwise
  *run* any routine. The Routine Engine that performs execution
  is a later milestone.
- ``AttentionProfile``, ``ObservationMenu``, and
  ``SelectedObservationSet`` (the v1.8.2 attention layer) are
  also later milestones; v1.8.4 ships only routine identity +
  audit storage.
- No concrete routines (corporate quarterly reporting, valuation
  refresh, bank review, investor review, etc.) are implemented.
- Cross-references (``allowed_interaction_ids`` on a spec,
  ``input_refs`` / ``output_refs`` / ``interaction_ids`` /
  ``parent_record_ids`` on a run record) are recorded as data and
  **not** validated for resolution against any other book, per
  the v0/v1 cross-reference rule.
- v1.8.4 ships zero economic behavior: no price formation, no
  trading, no lending decisions, no corporate actions, no policy
  reaction functions, no Japan calibration.

The book offers one helper that *reads* the v1.8.3
``InteractionBook`` to answer "may this routine use this
interaction channel?" — a predicate, not a mutator. See
``routine_can_use_interaction``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, TYPE_CHECKING

from world.clock import Clock
from world.ledger import Ledger

if TYPE_CHECKING:
    from world.interactions import InteractionBook


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RoutineError(Exception):
    """Base class for routine-layer errors."""


class DuplicateRoutineError(RoutineError):
    """Raised when a routine_id is added twice."""


class DuplicateRoutineRunError(RoutineError):
    """Raised when a run_id is added twice."""


class UnknownRoutineError(RoutineError, KeyError):
    """Raised when a routine_id is not found."""


class UnknownRoutineRunError(RoutineError, KeyError):
    """Raised when a run_id is not found."""


# ---------------------------------------------------------------------------
# Date coercion (mirrors world/relationships._coerce_iso_date)
# ---------------------------------------------------------------------------


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


def _normalize_string_tuple(
    value, *, field_name: str
) -> tuple[str, ...]:
    normalized = tuple(value)
    for entry in normalized:
        if not isinstance(entry, str) or not entry:
            raise ValueError(
                f"{field_name} entries must be non-empty strings; "
                f"got {entry!r}"
            )
    return normalized


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutineSpec:
    """
    Static declaration of a scheduled endogenous routine.

    Field semantics
    ---------------
    - ``routine_id`` is the stable id; unique within a
      ``RoutineBook``.
    - ``routine_type`` names the *category* of routine, drawn from
      a controlled vocabulary the project will grow milestone by
      milestone (v1.8.5+: ``"corporate_quarterly_reporting"`` etc.).
      Free-form string in v1.8.4; the book does not enumerate.
    - ``owner_space_id`` is the v0/v1 space id that owns the
      routine's side effects. Required.
    - ``owner_id`` optionally scopes the routine to one specific
      world object within the owner space (e.g., one firm filing
      its own quarterly report). ``None`` means "any owner within
      the owner space."
    - ``frequency`` is a free-form label naming the cadence (e.g.,
      ``"DAILY"``, ``"MONTHLY"``, ``"QUARTERLY"``, ``"YEARLY"``,
      or any custom label). v1.8.4 does **not** schedule tasks
      from the routine layer; the field is informational. The
      v0 ``Frequency`` enum is the recommended vocabulary, but
      the book does not enforce it.
    - ``phase_id`` is an optional intraday phase label (v1.2).
    - ``enabled`` (default ``True``) is a flag mirroring v1.8.3's
      ``InteractionSpec.enabled``. Disabled routines remain in the
      book but are excluded from list views unless
      ``include_disabled=True``.
    - ``required_input_ref_types`` and ``optional_input_ref_types``
      name record-type strings the routine *should* / *may* read
      to produce its output. Matches v1.8.3 ``InteractionSpec``.
    - ``output_ref_types`` names record-type strings the routine
      *produces*.
    - ``allowed_interaction_ids`` names ``InteractionSpec``
      ``interaction_id``s this routine may publish on. The v1.8.3
      ``InteractionSpec.routine_types_that_may_use_this_channel``
      provides the topology-side authorization; this field
      provides the routine-side declaration. Both must agree for
      ``routine_can_use_interaction`` to return ``True`` —
      see that function's docstring.
    - ``missing_input_policy`` is a free-form label naming what
      the engine should do when a declared optional input is
      missing at run time. Suggested vocabulary: ``"degraded"``
      (the v1.8.1 anti-scenario default — the run still produces
      output, status will be ``"degraded"``), ``"strict"`` (the
      run fails), ``"skip"`` (the run is suppressed). v1.8.4
      stores the label only; the engine that interprets it ships
      in a later milestone.
    - ``metadata`` is free-form for provenance, parameters, and
      owner notes.

    Cross-references are stored as data; the book does not
    validate ``owner_space_id`` against the registry, nor
    ``allowed_interaction_ids`` against any ``InteractionBook``.
    """

    routine_id: str
    routine_type: str
    owner_space_id: str
    frequency: str
    owner_id: str | None = None
    phase_id: str | None = None
    enabled: bool = True
    required_input_ref_types: tuple[str, ...] = field(default_factory=tuple)
    optional_input_ref_types: tuple[str, ...] = field(default_factory=tuple)
    output_ref_types: tuple[str, ...] = field(default_factory=tuple)
    allowed_interaction_ids: tuple[str, ...] = field(default_factory=tuple)
    missing_input_policy: str = "degraded"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.routine_id, str) or not self.routine_id:
            raise ValueError("routine_id is required")
        if not isinstance(self.routine_type, str) or not self.routine_type:
            raise ValueError("routine_type is required")
        if not isinstance(self.owner_space_id, str) or not self.owner_space_id:
            raise ValueError("owner_space_id is required")
        if not isinstance(self.frequency, str) or not self.frequency:
            raise ValueError("frequency is required")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if self.owner_id is not None and not (
            isinstance(self.owner_id, str) and self.owner_id
        ):
            raise ValueError(
                "owner_id must be a non-empty string or None"
            )
        if self.phase_id is not None and not (
            isinstance(self.phase_id, str) and self.phase_id
        ):
            raise ValueError(
                "phase_id must be a non-empty string or None"
            )
        if (
            not isinstance(self.missing_input_policy, str)
            or not self.missing_input_policy
        ):
            raise ValueError("missing_input_policy is required")

        for tuple_field_name in (
            "required_input_ref_types",
            "optional_input_ref_types",
            "output_ref_types",
            "allowed_interaction_ids",
        ):
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "routine_id": self.routine_id,
            "routine_type": self.routine_type,
            "owner_space_id": self.owner_space_id,
            "owner_id": self.owner_id,
            "frequency": self.frequency,
            "phase_id": self.phase_id,
            "enabled": self.enabled,
            "required_input_ref_types": list(self.required_input_ref_types),
            "optional_input_ref_types": list(self.optional_input_ref_types),
            "output_ref_types": list(self.output_ref_types),
            "allowed_interaction_ids": list(self.allowed_interaction_ids),
            "missing_input_policy": self.missing_input_policy,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RoutineRunRecord:
    """
    Per-execution audit record for a routine run.

    The record is **denormalized**: it carries ``routine_type`` and
    ``owner_space_id`` alongside ``routine_id`` so the audit trail
    is self-contained and remains interpretable even if the spec is
    later disabled or re-described in metadata.

    ``status`` is a free-form string; the project's recommended
    vocabulary is ``"completed"`` / ``"partial"`` / ``"degraded"`` /
    ``"failed"``. ``"degraded"`` is the v1.8.1 anti-scenario
    default for the case "the routine ran with one or more declared
    optional inputs missing but still produced its endogenous
    output." A run that becomes silent solely because its optional
    inputs were missing has slipped back into scenario-driven mode
    and should be ``"failed"``, not ``"completed"``.

    Field semantics
    ---------------
    - ``run_id`` is the stable id; unique within a ``RoutineBook``.
    - ``routine_id`` references the spec the run executed.
    - ``routine_type`` and ``owner_space_id`` are denormalized
      copies of the spec's fields at run time.
    - ``owner_id`` is the actor scope (matches the spec's
      ``owner_id``; may be ``None``).
    - ``as_of_date`` is ISO ``YYYY-MM-DD``.
    - ``phase_id`` is optional intraday phase.
    - ``input_refs`` are the ids of records the run actually read
      (a strict subset of what the spec declared, plus any
      additional context the engine chose to read).
    - ``output_refs`` are the ids of records the run produced.
    - ``interaction_ids`` are the ``InteractionSpec``
      ``interaction_id``s the run actually used to publish (a
      subset of the spec's ``allowed_interaction_ids``, possibly
      empty).
    - ``parent_record_ids`` are ledger record ids that link this
      run back to causally-prior records (the v1 ledger
      convention).
    - ``status`` is the free-form outcome label.
    - ``metadata`` is free-form.
    """

    run_id: str
    routine_id: str
    routine_type: str
    owner_space_id: str
    as_of_date: str
    status: str
    owner_id: str | None = None
    phase_id: str | None = None
    input_refs: tuple[str, ...] = field(default_factory=tuple)
    output_refs: tuple[str, ...] = field(default_factory=tuple)
    interaction_ids: tuple[str, ...] = field(default_factory=tuple)
    parent_record_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError("run_id is required")
        if not isinstance(self.routine_id, str) or not self.routine_id:
            raise ValueError("routine_id is required")
        if not isinstance(self.routine_type, str) or not self.routine_type:
            raise ValueError("routine_type is required")
        if not isinstance(self.owner_space_id, str) or not self.owner_space_id:
            raise ValueError("owner_space_id is required")
        if not isinstance(self.as_of_date, (str, date)) or (
            isinstance(self.as_of_date, str) and not self.as_of_date
        ):
            raise ValueError("as_of_date is required")
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("status is required")
        if self.owner_id is not None and not (
            isinstance(self.owner_id, str) and self.owner_id
        ):
            raise ValueError(
                "owner_id must be a non-empty string or None"
            )
        if self.phase_id is not None and not (
            isinstance(self.phase_id, str) and self.phase_id
        ):
            raise ValueError(
                "phase_id must be a non-empty string or None"
            )

        object.__setattr__(self, "as_of_date", _coerce_iso_date(self.as_of_date))

        for tuple_field_name in (
            "input_refs",
            "output_refs",
            "interaction_ids",
            "parent_record_ids",
        ):
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "routine_id": self.routine_id,
            "routine_type": self.routine_type,
            "owner_space_id": self.owner_space_id,
            "owner_id": self.owner_id,
            "as_of_date": self.as_of_date,
            "phase_id": self.phase_id,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "interaction_ids": list(self.interaction_ids),
            "parent_record_ids": list(self.parent_record_ids),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class RoutineBook:
    """
    Storage for ``RoutineSpec`` and ``RoutineRunRecord`` entries.

    The book is append-only, emits ledger records on each insert,
    and refuses to mutate any other source-of-truth book. v1.8.4
    ships storage and audit only — no execution, no scheduling, no
    economic behavior. The Routine Engine that fires routines on
    schedule is a later milestone.

    Cross-references on records (``allowed_interaction_ids`` on a
    spec; ``input_refs`` / ``output_refs`` / ``interaction_ids`` /
    ``parent_record_ids`` on a run record) are recorded as data and
    **not** validated against any other book, per v0 / v1.

    The one helper that touches another book is
    :meth:`routine_can_use_interaction`, which is a pure predicate
    over ``RoutineBook`` + ``InteractionBook`` — it reads both,
    mutates neither.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _routines: dict[str, RoutineSpec] = field(default_factory=dict)
    _runs: dict[str, RoutineRunRecord] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Routine CRUD
    # ------------------------------------------------------------------

    def add_routine(self, spec: RoutineSpec) -> RoutineSpec:
        if spec.routine_id in self._routines:
            raise DuplicateRoutineError(
                f"Duplicate routine_id: {spec.routine_id}"
            )
        self._routines[spec.routine_id] = spec

        if self.ledger is not None:
            self.ledger.append(
                event_type="routine_added",
                simulation_date=self._now(),
                object_id=spec.routine_id,
                source=spec.owner_space_id,
                target=spec.owner_id,
                payload={
                    "routine_id": spec.routine_id,
                    "routine_type": spec.routine_type,
                    "owner_space_id": spec.owner_space_id,
                    "owner_id": spec.owner_id,
                    "frequency": spec.frequency,
                    "phase_id": spec.phase_id,
                    "enabled": spec.enabled,
                    "missing_input_policy": spec.missing_input_policy,
                    "required_input_ref_types": list(
                        spec.required_input_ref_types
                    ),
                    "optional_input_ref_types": list(
                        spec.optional_input_ref_types
                    ),
                    "output_ref_types": list(spec.output_ref_types),
                    "allowed_interaction_ids": list(
                        spec.allowed_interaction_ids
                    ),
                },
                space_id="routines",
            )
        return spec

    def get_routine(self, routine_id: str) -> RoutineSpec:
        try:
            return self._routines[routine_id]
        except KeyError as exc:
            raise UnknownRoutineError(
                f"Routine not found: {routine_id!r}"
            ) from exc

    def list_routines(
        self, *, include_disabled: bool = False
    ) -> tuple[RoutineSpec, ...]:
        return tuple(
            self._filter(self._routines.values(), include_disabled)
        )

    def list_by_type(
        self, routine_type: str, *, include_disabled: bool = False
    ) -> tuple[RoutineSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._routines.values()
                    if spec.routine_type == routine_type
                ),
                include_disabled,
            )
        )

    def list_by_owner_space(
        self, owner_space_id: str, *, include_disabled: bool = False
    ) -> tuple[RoutineSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._routines.values()
                    if spec.owner_space_id == owner_space_id
                ),
                include_disabled,
            )
        )

    def list_by_frequency(
        self, frequency: str, *, include_disabled: bool = False
    ) -> tuple[RoutineSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._routines.values()
                    if spec.frequency == frequency
                ),
                include_disabled,
            )
        )

    def list_for_interaction(
        self, interaction_id: str, *, include_disabled: bool = False
    ) -> tuple[RoutineSpec, ...]:
        """
        Return every routine that lists ``interaction_id`` in its
        ``allowed_interaction_ids``. Does *not* check the
        topology-side authorization (use
        :meth:`routine_can_use_interaction` for the full predicate).
        """
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._routines.values()
                    if interaction_id in spec.allowed_interaction_ids
                ),
                include_disabled,
            )
        )

    # ------------------------------------------------------------------
    # Run record CRUD
    # ------------------------------------------------------------------

    def add_run_record(self, record: RoutineRunRecord) -> RoutineRunRecord:
        if record.run_id in self._runs:
            raise DuplicateRoutineRunError(
                f"Duplicate run_id: {record.run_id}"
            )
        self._runs[record.run_id] = record

        if self.ledger is not None:
            self.ledger.append(
                event_type="routine_run_recorded",
                simulation_date=record.as_of_date,
                object_id=record.run_id,
                source=record.owner_space_id,
                target=record.owner_id,
                payload={
                    "run_id": record.run_id,
                    "routine_id": record.routine_id,
                    "routine_type": record.routine_type,
                    "owner_space_id": record.owner_space_id,
                    "owner_id": record.owner_id,
                    "as_of_date": record.as_of_date,
                    "phase_id": record.phase_id,
                    "status": record.status,
                    "input_refs": list(record.input_refs),
                    "output_refs": list(record.output_refs),
                    "interaction_ids": list(record.interaction_ids),
                },
                parent_record_ids=record.parent_record_ids,
                space_id="routines",
            )
        return record

    def get_run_record(self, run_id: str) -> RoutineRunRecord:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise UnknownRoutineRunError(
                f"Routine run not found: {run_id!r}"
            ) from exc

    def list_runs_by_routine(
        self, routine_id: str
    ) -> tuple[RoutineRunRecord, ...]:
        return tuple(
            record
            for record in self._runs.values()
            if record.routine_id == routine_id
        )

    def list_runs_by_date(
        self, as_of_date: date | str
    ) -> tuple[RoutineRunRecord, ...]:
        target = _coerce_iso_date(as_of_date)
        return tuple(
            record
            for record in self._runs.values()
            if record.as_of_date == target
        )

    def list_runs_by_status(
        self, status: str
    ) -> tuple[RoutineRunRecord, ...]:
        return tuple(
            record
            for record in self._runs.values()
            if record.status == status
        )

    # ------------------------------------------------------------------
    # Compatibility helper
    # ------------------------------------------------------------------

    def routine_can_use_interaction(
        self,
        routine_id: str,
        interaction_id: str,
        interactions_book: "InteractionBook",
    ) -> bool:
        """
        Pure predicate: ``True`` iff the routine and the interaction
        agree that the routine may publish on the channel.

        Both sides must agree:

        - The routine declares the channel by listing
          ``interaction_id`` in its
          ``RoutineSpec.allowed_interaction_ids``.
        - The interaction admits the routine type either by
          listing ``RoutineSpec.routine_type`` in its
          ``InteractionSpec.routine_types_that_may_use_this_channel``
          *or* by leaving that tuple empty (the v1.8.3 "any
          routine type" semantics, mirrored here for consistency
          with ``InteractionBook.list_for_routine_type``).

        Behavior on missing inputs:

        - Unknown ``routine_id`` raises ``UnknownRoutineError``
          (the routine half is local to this book, and the caller
          should know its own routine ids).
        - Unknown ``interaction_id`` returns ``False`` (the
          interaction half is in another book; predicates should
          not raise on a closed-world miss). This keeps the
          predicate safe to call against any pair of ids without
          crash, which matters for downstream attention / engine
          milestones that may probe the topology speculatively.

        The function reads both books and mutates neither.
        """
        spec = self.get_routine(routine_id)

        if interaction_id not in spec.allowed_interaction_ids:
            return False

        try:
            interaction = interactions_book.get_interaction(interaction_id)
        except Exception:  # noqa: BLE001 - InteractionBook may raise its own KeyError subclass
            return False

        allowed_types = (
            interaction.routine_types_that_may_use_this_channel
        )
        if not allowed_types:
            # v1.8.3 / v1.8.2 semantics: empty tuple = any routine type.
            return True
        return spec.routine_type in allowed_types

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        routines = sorted(
            (spec.to_dict() for spec in self._routines.values()),
            key=lambda item: item["routine_id"],
        )
        runs = sorted(
            (record.to_dict() for record in self._runs.values()),
            key=lambda item: item["run_id"],
        )
        return {
            "routine_count": len(routines),
            "enabled_routine_count": sum(
                1 for spec in self._routines.values() if spec.enabled
            ),
            "run_count": len(runs),
            "routines": routines,
            "runs": runs,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _filter(specs, include_disabled: bool):
        for spec in specs:
            if include_disabled or spec.enabled:
                yield spec

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
