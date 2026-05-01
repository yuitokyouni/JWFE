"""
v1.8.6 Routine Engine plumbing.

A thin execution service that turns a ``RoutineExecutionRequest`` plus
selected observation records into an auditable
``RoutineRunRecord`` (stored via ``RoutineBook.add_run_record``).

Scope discipline (v1.8.6):

- The engine is **plumbing, not behavior**. It validates the request,
  collects input refs, and writes one ``RoutineRunRecord``. It does
  **not** call user-defined callbacks, generate signals, valuations,
  prices, contracts, ownership changes, or any economic action.
- It does **not** schedule routines, fire them automatically, or
  hook into ``kernel.tick()`` / ``kernel.run()``. Execution is
  caller-initiated through ``execute_request``.
- It does **not** build attention menus, decide selections, or
  consume external observations as triggers — selections come in
  pre-built (per v1.8.5), and the v1.8.1 anti-scenario discipline
  cascades through the engine's status semantics (a request with no
  inputs is recorded as ``"degraded"``, not ``"failed"``).
- Concrete routines (corporate quarterly reporting, investor
  review, bank review, etc.) are out of scope. They land starting
  v1.8.7 on top of this plumbing.

The engine reads from ``RoutineBook``, ``InteractionBook``, and
``AttentionBook``. The only book it writes to is ``RoutineBook``,
through the existing ``add_run_record`` ledger emission path. No
v0 / v1 record shape, book API, scheduler extension, or ledger
record type is altered.

Cross-references on the request (``interaction_ids``,
``selected_observation_set_ids``, ``explicit_input_refs``,
``output_refs``) are validated for existence where the engine
must (interactions and selections are looked up); other ids are
recorded as data and not resolved against any other book, per the
v0 / v1 cross-reference rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from world.attention import (
    AttentionBook,
    UnknownSelectedObservationSetError,
)
from world.clock import Clock
from world.interactions import InteractionBook
from world.routines import (
    RoutineBook,
    RoutineRunRecord,
    UnknownRoutineError,
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RoutineExecutionError(Exception):
    """Base class for routine-execution errors."""


class RoutineExecutionValidationError(RoutineExecutionError):
    """Raised when a request fails structural validation."""


class RoutineExecutionMissingDateError(RoutineExecutionError):
    """Raised when a request has no as_of_date and no clock is wired."""


class RoutineExecutionIncompatibleInteractionError(RoutineExecutionError):
    """Raised when a requested interaction is unknown or not allowed."""


class RoutineExecutionUnknownSelectionError(RoutineExecutionError):
    """Raised when a requested selected_observation_set_id is unknown."""


# ---------------------------------------------------------------------------
# Helpers
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


def _dedupe_preserve_order(values) -> tuple[str, ...]:
    """Return values with first-occurrence order preserved and
    duplicates removed. Deterministic."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return tuple(out)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoutineExecutionRequest:
    """
    Caller-supplied input to ``RoutineEngine.execute_request``.

    Field semantics
    ---------------
    - ``request_id`` is the stable id of the request; useful for
      idempotency in caller-side bookkeeping. The engine does not
      enforce uniqueness across requests because requests are not
      stored — the resulting ``RoutineRunRecord`` is.
    - ``routine_id`` references the ``RoutineSpec`` to execute. The
      spec must exist in the engine's ``RoutineBook``.
    - ``as_of_date`` is optional. If absent, the engine uses
      ``clock.current_date``; if no clock is wired,
      ``RoutineExecutionMissingDateError`` is raised.
    - ``phase_id`` is the optional intraday phase (v1.2).
    - ``interaction_ids`` lists ``InteractionSpec`` ids the request
      claims to use. Each must satisfy
      ``RoutineBook.routine_can_use_interaction``; unknown ids fail
      execution with the same error as not-allowed ids.
    - ``selected_observation_set_ids`` lists
      ``SelectedObservationSet`` ids whose ``selected_refs`` will be
      collected as inputs. Each must exist in the engine's
      ``AttentionBook``.
    - ``explicit_input_refs`` lists additional input record ids the
      caller wants attached, beyond what the selections supply.
    - ``output_refs`` lists record ids the caller has *already*
      created (or names them in advance) to pass through to the
      ``RoutineRunRecord.output_refs`` audit field. The engine
      does not create them.
    - ``status`` is an optional override. If absent, the engine
      computes the status from the input shape: ``"completed"``
      when the resolved input_refs are non-empty;
      ``"degraded"`` when they are empty (the v1.8.1 anti-scenario
      default — the routine ran with no inputs but the run is
      still a valid recorded event).
    - ``metadata`` is free-form. Two reserved keys are honored if
      present: ``parent_record_ids`` (a sequence of ledger
      record ids) flows to ``RoutineRunRecord.parent_record_ids``;
      every other key flows through to the run record's
      ``metadata`` unchanged. The engine also sets
      ``selected_observation_set_ids`` in the resulting run
      record's metadata.
    """

    request_id: str
    routine_id: str
    as_of_date: str | None = None
    phase_id: str | None = None
    interaction_ids: tuple[str, ...] = field(default_factory=tuple)
    selected_observation_set_ids: tuple[str, ...] = field(default_factory=tuple)
    explicit_input_refs: tuple[str, ...] = field(default_factory=tuple)
    output_refs: tuple[str, ...] = field(default_factory=tuple)
    status: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id:
            raise ValueError("request_id is required")
        if not isinstance(self.routine_id, str) or not self.routine_id:
            raise ValueError("routine_id is required")
        if self.as_of_date is not None and not (
            isinstance(self.as_of_date, str) and self.as_of_date
        ):
            raise ValueError(
                "as_of_date must be a non-empty ISO YYYY-MM-DD string or None"
            )
        if self.phase_id is not None and not (
            isinstance(self.phase_id, str) and self.phase_id
        ):
            raise ValueError(
                "phase_id must be a non-empty string or None"
            )
        if self.status is not None and not (
            isinstance(self.status, str) and self.status
        ):
            raise ValueError(
                "status must be a non-empty string or None"
            )

        for tuple_field_name in (
            "interaction_ids",
            "selected_observation_set_ids",
            "explicit_input_refs",
            "output_refs",
        ):
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "routine_id": self.routine_id,
            "as_of_date": self.as_of_date,
            "phase_id": self.phase_id,
            "interaction_ids": list(self.interaction_ids),
            "selected_observation_set_ids": list(
                self.selected_observation_set_ids
            ),
            "explicit_input_refs": list(self.explicit_input_refs),
            "output_refs": list(self.output_refs),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RoutineExecutionResult:
    """
    Engine output. Mirrors the resulting ``RoutineRunRecord`` plus
    the ``request_id`` for caller-side correlation. Returned by
    ``RoutineEngine.execute_request``.

    Two runs of the engine with the same request and the same
    underlying book state produce equal results, because the engine
    is deterministic: it does not consult any wall-clock value other
    than what the kernel's ``Clock`` exposes, and it does not
    introduce randomness.
    """

    request_id: str
    run_id: str
    routine_id: str
    routine_type: str
    owner_space_id: str
    as_of_date: str
    status: str
    phase_id: str | None = None
    input_refs: tuple[str, ...] = field(default_factory=tuple)
    output_refs: tuple[str, ...] = field(default_factory=tuple)
    interaction_ids: tuple[str, ...] = field(default_factory=tuple)
    selected_observation_set_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Engine-built results always pass validated tuples; this
        # post-init exists so callers that hand-craft
        # ``RoutineExecutionResult`` instances (rare; mostly tests)
        # are held to the same standards.
        for tuple_field_name in (
            "input_refs",
            "output_refs",
            "interaction_ids",
            "selected_observation_set_ids",
        ):
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)
        object.__setattr__(self, "metadata", dict(self.metadata))


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class RoutineEngine:
    """
    Thin execution service. Constructed with the kernel-level
    ``RoutineBook``, ``InteractionBook``, ``AttentionBook``, and
    optionally a ``Clock``. The engine reads from all three books
    and writes only to ``RoutineBook`` through its existing
    ``add_run_record`` ledger emission path.

    The engine is intentionally stateless beyond its references to
    those books. It can be reconstructed at any time from the same
    arguments without losing information.
    """

    routines: RoutineBook
    interactions: InteractionBook
    attention: AttentionBook
    clock: Clock | None = None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_request(
        self, request: RoutineExecutionRequest
    ) -> dict[str, Any]:
        """
        Run every validation check that ``execute_request`` would,
        without writing a run record. Returns a small summary dict
        suitable for caller-side previews / dry-runs::

            {
              "request_id": ...,
              "routine_id": ...,
              "routine_type": ...,
              "owner_space_id": ...,
              "as_of_date": ...,           # resolved from request or clock
              "interaction_ids": (...),
              "selected_observation_set_ids": (...),
              "selected_refs_count": int,
              "explicit_input_refs_count": int,
              "resolved_input_refs_count": int,
              "default_status": "completed" | "degraded",
            }

        Raises the same controlled errors as ``execute_request`` so
        callers that want to surface validation failures cleanly can
        call this method first.
        """
        spec = self._resolve_routine(request)
        as_of_date = self._resolve_as_of_date(request)
        self._validate_interactions(request, spec)
        selected_refs = self.collect_selected_refs(
            request.selected_observation_set_ids
        )
        resolved = _dedupe_preserve_order(
            list(request.explicit_input_refs) + list(selected_refs)
        )
        default_status = self._default_status(resolved)
        return {
            "request_id": request.request_id,
            "routine_id": request.routine_id,
            "routine_type": spec.routine_type,
            "owner_space_id": spec.owner_space_id,
            "as_of_date": as_of_date,
            "interaction_ids": tuple(request.interaction_ids),
            "selected_observation_set_ids": tuple(
                request.selected_observation_set_ids
            ),
            "selected_refs_count": len(selected_refs),
            "explicit_input_refs_count": len(request.explicit_input_refs),
            "resolved_input_refs_count": len(resolved),
            "default_status": default_status,
        }

    # ------------------------------------------------------------------
    # Selected-ref collection
    # ------------------------------------------------------------------

    def collect_selected_refs(
        self, selected_observation_set_ids
    ) -> tuple[str, ...]:
        """
        Walk ``selected_observation_set_ids``, look each up in
        ``AttentionBook``, and concatenate their ``selected_refs``.

        Order is preserved across selections (declaration order of
        the input list, then declaration order within each
        ``SelectedObservationSet.selected_refs``). Duplicates are
        **not** deduped here — that happens once at the resolved-
        input-refs layer, after the explicit_input_refs are joined,
        so that a duplicate appearing in both the explicit list and
        a selection is still removed deterministically.

        Raises ``RoutineExecutionUnknownSelectionError`` if any
        selection id is missing.
        """
        out: list[str] = []
        for sel_id in selected_observation_set_ids:
            try:
                selection = self.attention.get_selection(sel_id)
            except UnknownSelectedObservationSetError as exc:
                raise RoutineExecutionUnknownSelectionError(
                    f"Unknown selected_observation_set_id: {sel_id!r}"
                ) from exc
            out.extend(selection.selected_refs)
        return tuple(out)

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def execute_request(
        self, request: RoutineExecutionRequest
    ) -> RoutineExecutionResult:
        """
        Validate the request, build a ``RoutineRunRecord``, write it
        through ``RoutineBook.add_run_record`` (which emits the
        ``ROUTINE_RUN_RECORDED`` ledger entry), and return a
        ``RoutineExecutionResult`` mirroring the run.

        Idempotency is the caller's responsibility — the engine does
        **not** check whether a run with this ``run_id`` already
        exists; if the caller passes a duplicate, ``RoutineBook``
        raises ``DuplicateRoutineRunError``.

        The ``run_id`` is derived from the ``request_id`` by
        prepending ``"run:"`` so a run can be cross-referenced back
        to its request without storing the request itself. Callers
        that want explicit control may supply
        ``request.metadata["run_id"]`` to override.
        """
        spec = self._resolve_routine(request)
        as_of_date = self._resolve_as_of_date(request)
        self._validate_interactions(request, spec)
        selected_refs = self.collect_selected_refs(
            request.selected_observation_set_ids
        )

        resolved_input_refs = _dedupe_preserve_order(
            list(request.explicit_input_refs) + list(selected_refs)
        )

        if request.status is not None:
            status = request.status
        else:
            status = self._default_status(resolved_input_refs)

        # Pull reserved metadata keys out so they do not collide
        # with engine-set fields on the run record.
        metadata = dict(request.metadata)
        parent_record_ids = tuple(
            metadata.pop("parent_record_ids", ())
        )
        run_id = metadata.pop(
            "run_id", f"run:{request.request_id}"
        )
        if not isinstance(run_id, str) or not run_id:
            raise RoutineExecutionValidationError(
                f"run_id must be a non-empty string; got {run_id!r}"
            )

        # Engine-set audit field: the selections that fed this run.
        metadata["selected_observation_set_ids"] = list(
            request.selected_observation_set_ids
        )

        record = RoutineRunRecord(
            run_id=run_id,
            routine_id=spec.routine_id,
            routine_type=spec.routine_type,
            owner_space_id=spec.owner_space_id,
            owner_id=spec.owner_id,
            as_of_date=as_of_date,
            phase_id=request.phase_id,
            input_refs=resolved_input_refs,
            output_refs=tuple(request.output_refs),
            interaction_ids=tuple(request.interaction_ids),
            parent_record_ids=parent_record_ids,
            status=status,
            metadata=metadata,
        )

        self.routines.add_run_record(record)

        return RoutineExecutionResult(
            request_id=request.request_id,
            run_id=record.run_id,
            routine_id=record.routine_id,
            routine_type=record.routine_type,
            owner_space_id=record.owner_space_id,
            as_of_date=record.as_of_date,
            phase_id=record.phase_id,
            input_refs=record.input_refs,
            output_refs=record.output_refs,
            interaction_ids=record.interaction_ids,
            selected_observation_set_ids=tuple(
                request.selected_observation_set_ids
            ),
            status=record.status,
            metadata=record.metadata,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_routine(self, request: RoutineExecutionRequest):
        try:
            spec = self.routines.get_routine(request.routine_id)
        except UnknownRoutineError as exc:
            raise RoutineExecutionValidationError(
                f"Unknown routine_id: {request.routine_id!r}"
            ) from exc
        if not spec.enabled:
            raise RoutineExecutionValidationError(
                f"Routine {request.routine_id!r} is disabled; "
                "v1.8.6 rejects execution requests against disabled "
                "routines. Re-enable the spec or run a different routine."
            )
        return spec

    def _resolve_as_of_date(self, request: RoutineExecutionRequest) -> str:
        if request.as_of_date is not None:
            return _coerce_iso_date(request.as_of_date)
        if self.clock is not None and self.clock.current_date is not None:
            return self.clock.current_date.isoformat()
        raise RoutineExecutionMissingDateError(
            "Request has no as_of_date and no clock is wired; "
            "supply request.as_of_date or initialize the engine with a clock."
        )

    def _validate_interactions(
        self, request: RoutineExecutionRequest, spec
    ) -> None:
        for interaction_id in request.interaction_ids:
            ok = self.routines.routine_can_use_interaction(
                spec.routine_id, interaction_id, self.interactions
            )
            if not ok:
                raise RoutineExecutionIncompatibleInteractionError(
                    f"Interaction {interaction_id!r} is unknown or not "
                    f"permitted for routine {spec.routine_id!r} "
                    f"(routine_type={spec.routine_type!r}). Both sides must "
                    "agree: the routine must list the interaction in its "
                    "allowed_interaction_ids AND the interaction's "
                    "routine_types_that_may_use_this_channel must admit "
                    "this routine_type (or be empty for the 'any routine "
                    "type' semantics)."
                )

    @staticmethod
    def _default_status(resolved_input_refs: tuple[str, ...]) -> str:
        # v1.8.1 anti-scenario discipline: a run with no inputs is
        # ``"degraded"``, not ``"failed"``.
        return "completed" if resolved_input_refs else "degraded"
