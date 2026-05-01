"""
v1.8.11 ObservationMenuBuilder.

A read-only join service that builds per-actor ``ObservationMenu``
records from visible signals, visible world-variable observations,
and active exposures. The builder implements the v1.8.8 hardening's
**gate 1 (visibility) + gate 2 (availability)** of the four-gate
rule:

    gate 1: visibility    — visible_from_date / as_of_date filter
    gate 2: availability  — through this builder, exposures join
                            variable observations to the actor
    gate 3: selection     — SelectedObservationSet (v1.8.5;
                            NOT automated by this builder)
    gate 4: consumption   — RoutineEngine + RoutineRunRecord
                            (v1.8.6; NOT triggered by this builder)

Scope discipline (v1.8.11):

- The builder is **availability plumbing**, not attention selection.
  It builds menus from existing books; it does not pick which
  observations the actor "actually" cares about — that is gate 3
  (`SelectedObservationSet`) and remains caller-driven.
- The builder does not execute routines, generate signals,
  compute impacts, calibrate sensitivities, multiply variable
  values by exposure magnitudes, adjust valuations, or move any
  other book.
- The builder writes exactly one `ObservationMenu` per
  `build_menu(...)` call, via `AttentionBook.add_menu` (which
  emits the existing `OBSERVATION_MENU_CREATED` ledger entry).
  No other ledger writes are performed.
- `preview_menu(...)` builds the same result but does **not**
  write — useful for caller-side dry-runs without ledger churn.

Variable / exposure join semantics (the v1.8.8 hardening's
exposure hook in action):

- The actor's exposures define which variables matter to them.
- For each relevant variable, only observations with
  `visibility_date <= as_of_date` are surfaced.
- If the actor has zero exposures, the menu's
  `available_variable_observation_ids` is empty by default —
  the builder does **not** dump every world variable on every
  actor.

Cross-references (`actor_id`, `variable_id`, `interaction_id`)
are recorded as data and **not** validated against the registry,
per the v0/v1 cross-reference rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping, TYPE_CHECKING

from world.attention import (
    AttentionBook,
    ObservationMenu,
)
from world.clock import Clock
from world.exposures import ExposureBook
from world.signals import SignalBook
from world.variables import WorldVariableBook

if TYPE_CHECKING:
    from world.interactions import InteractionBook


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ObservationMenuBuilderError(Exception):
    """Base class for observation-menu-builder errors."""


class ObservationMenuBuildMissingDateError(ObservationMenuBuilderError):
    """Raised when no as_of_date is supplied and no clock is wired."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


def _validate_request_field(value, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required and must be a non-empty string")
    return value


def _normalize_optional_string(
    value, *, field_name: str
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string or None")
    return value


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ObservationMenuBuildRequest:
    """
    Caller-supplied input to ``ObservationMenuBuilder.build_menu``
    (and ``preview_menu``).

    Field semantics
    ---------------
    - ``request_id`` is the stable id of the request. Used to
      derive the resulting ``menu_id`` (default
      ``"menu:" + request_id`` for a build, ``"menu:preview:" +
      request_id`` for a preview). Caller may override via
      ``metadata["menu_id"]``.
    - ``actor_id`` is the actor whose menu is being built.
    - ``as_of_date`` is optional. If absent, the builder uses
      ``clock.current_date``; if no clock is wired,
      ``ObservationMenuBuildMissingDateError`` is raised.
    - ``phase_id`` is the optional intraday phase (v1.2).
    - ``include_signals`` / ``include_variables`` /
      ``include_exposures`` are boolean toggles. v1.8.11's default
      is "include everything" (``True`` for all three) so callers
      that want a maximal menu need not specify each flag.
      Setting a flag to ``False`` skips the corresponding
      collection step; the menu will have empty fields for
      skipped sources.
    - ``metadata`` is free-form. Two reserved keys are honored if
      present: ``menu_id`` (overrides the default derived id) and
      ``status`` (overrides the auto-derived status label).
    """

    request_id: str
    actor_id: str
    as_of_date: str | None = None
    phase_id: str | None = None
    include_signals: bool = True
    include_variables: bool = True
    include_exposures: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_request_field(self.request_id, field_name="request_id")
        _validate_request_field(self.actor_id, field_name="actor_id")
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
        for name in ("include_signals", "include_variables", "include_exposures"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} must be a bool")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "actor_id": self.actor_id,
            "as_of_date": self.as_of_date,
            "phase_id": self.phase_id,
            "include_signals": self.include_signals,
            "include_variables": self.include_variables,
            "include_exposures": self.include_exposures,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ObservationMenuBuildResult:
    """
    Builder output. Mirrors the shape of the resulting
    ``ObservationMenu`` plus the ``request_id`` and a derived
    ``status`` label so callers can correlate without re-fetching
    the menu from the book.

    Status vocabulary (v1.8.11):

    - ``"completed"`` — at least one available ref exists across
      the menu.
    - ``"empty"`` — zero candidates across all sources.
    - ``"partial"`` — caller-supplied or future-builder-supplied.
      v1.8.11 does not auto-derive this label; the schema
      reserves it.
    - ``"degraded"`` — caller-supplied. v1.8.11 does not
      auto-derive.

    The label is descriptive; no economic meaning is implied.
    """

    request_id: str
    menu_id: str
    actor_id: str
    as_of_date: str
    status: str
    phase_id: str | None = None
    available_signal_ids: tuple[str, ...] = field(default_factory=tuple)
    available_variable_observation_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    available_exposure_ids: tuple[str, ...] = field(default_factory=tuple)
    available_interaction_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalize tuples deterministically and reject empty entries
        # so a result handed to a downstream consumer is always
        # well-shaped.
        for tuple_field_name in (
            "available_signal_ids",
            "available_variable_observation_ids",
            "available_exposure_ids",
            "available_interaction_ids",
        ):
            value = tuple(getattr(self, tuple_field_name))
            for entry in value:
                if not isinstance(entry, str) or not entry:
                    raise ValueError(
                        f"{tuple_field_name} entries must be non-empty strings"
                    )
            object.__setattr__(self, tuple_field_name, value)
        object.__setattr__(self, "metadata", dict(self.metadata))


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


@dataclass
class ObservationMenuBuilder:
    """
    Read-only join service. Reads from ``AttentionBook``,
    ``SignalBook``, ``WorldVariableBook``, ``ExposureBook``, and
    optionally ``InteractionBook``. Writes one ``ObservationMenu``
    per ``build_menu(...)`` call via the existing
    ``AttentionBook.add_menu`` ledger path.

    The builder is stateless beyond its references to the books
    and clock; it can be reconstructed at any time from the same
    arguments without losing information.
    """

    attention: AttentionBook
    signals: SignalBook
    variables: WorldVariableBook
    exposures: ExposureBook
    interactions: "InteractionBook | None" = None
    clock: Clock | None = None

    # ------------------------------------------------------------------
    # Public collectors (read-only; callable on their own for dry-runs)
    # ------------------------------------------------------------------

    def collect_visible_signals(
        self, actor_id: str, as_of_date: date | str
    ) -> tuple[str, ...]:
        """Return the ids of signals visible to the actor as of the
        given date."""
        target = _coerce_iso_date(as_of_date)
        signals = self.signals.list_visible_to(actor_id, as_of_date=target)
        return tuple(s.signal_id for s in signals)

    def collect_active_exposures(
        self, actor_id: str, as_of_date: date | str
    ) -> tuple[str, ...]:
        """Return the ids of the actor's active exposures as of the
        given date."""
        target = _coerce_iso_date(as_of_date)
        actor_exposures = self.exposures.list_by_subject(actor_id)
        return tuple(
            r.exposure_id
            for r in actor_exposures
            if r.is_active_as_of(target)
        )

    def collect_visible_variable_observations(
        self, actor_id: str, as_of_date: date | str
    ) -> tuple[str, ...]:
        """
        Return the ids of variable observations relevant to the
        actor *via the actor's active exposures*, filtered by
        visibility (gate 1).

        If the actor has no active exposures, the result is
        empty — the builder does **not** dump every world variable
        on every actor.
        """
        target = _coerce_iso_date(as_of_date)
        # Step 1: which variables matter to this actor.
        actor_exposures = self.exposures.list_by_subject(actor_id)
        relevant_variable_ids = {
            r.variable_id
            for r in actor_exposures
            if r.is_active_as_of(target)
        }
        if not relevant_variable_ids:
            return ()

        # Step 2: collect visible observations on those variables.
        visible = self.variables.list_observations_visible_as_of(target)
        return tuple(
            o.observation_id
            for o in visible
            if o.variable_id in relevant_variable_ids
        )

    # ------------------------------------------------------------------
    # build / preview
    # ------------------------------------------------------------------

    def build_menu(
        self, request: ObservationMenuBuildRequest
    ) -> ObservationMenuBuildResult:
        """
        Build the menu, persist it via ``AttentionBook.add_menu``
        (which emits the existing ``OBSERVATION_MENU_CREATED``
        ledger entry), and return a result mirroring the menu
        plus the caller's ``request_id``.

        Idempotency is the caller's responsibility: the builder
        does not check whether a menu with this id already exists;
        if the caller passes a duplicate, ``AttentionBook`` raises
        ``DuplicateObservationMenuError``.
        """
        return self._build(request, persist=True)

    def preview_menu(
        self, request: ObservationMenuBuildRequest
    ) -> ObservationMenuBuildResult:
        """
        Compute the menu without writing it to ``AttentionBook``
        and without emitting any ledger record. The result's
        ``menu_id`` is prefixed with ``"menu:preview:"`` to make
        the non-persistent shape obvious to callers.
        """
        return self._build(request, persist=False)

    # ------------------------------------------------------------------
    # Internal flow
    # ------------------------------------------------------------------

    def _build(
        self,
        request: ObservationMenuBuildRequest,
        *,
        persist: bool,
    ) -> ObservationMenuBuildResult:
        as_of_date = self._resolve_as_of_date(request)

        # Collectors run independently. Each collection is wrapped
        # in a try/except so a failure in one source does not abort
        # the build; the failed source contributes an empty list,
        # and metadata records the failure so callers can flag it.
        # v1.8.11's default is "everything succeeds" — these branches
        # exist to keep the schema faithful under unusual conditions.
        signal_ids: tuple[str, ...] = ()
        variable_observation_ids: tuple[str, ...] = ()
        exposure_ids: tuple[str, ...] = ()
        failures: list[str] = []

        if request.include_signals:
            try:
                signal_ids = self.collect_visible_signals(
                    request.actor_id, as_of_date
                )
            except Exception:  # noqa: BLE001 - best-effort isolation
                failures.append("signals")

        if request.include_exposures:
            try:
                exposure_ids = self.collect_active_exposures(
                    request.actor_id, as_of_date
                )
            except Exception:  # noqa: BLE001
                failures.append("exposures")

        if request.include_variables:
            try:
                variable_observation_ids = (
                    self.collect_visible_variable_observations(
                        request.actor_id, as_of_date
                    )
                )
            except Exception:  # noqa: BLE001
                failures.append("variable_observations")

        # Available interaction ids: the union of
        # carried_by_interaction_id values across the surfaced
        # variable observations + the "interaction_id" key in any
        # surfaced signal's metadata (a project convention used by
        # the v1.8.7 corporate reporting routine and similar).
        interaction_ids = self._collect_interaction_ids(
            signal_ids, variable_observation_ids
        )

        # Build the request-level metadata that flows into the
        # menu's metadata. Reserve menu_id and status overrides via
        # request.metadata as the v1.8.6 RoutineEngine does.
        request_metadata = dict(request.metadata)
        menu_id_override = request_metadata.pop("menu_id", None)
        status_override = request_metadata.pop("status", None)
        if status_override is not None and not (
            isinstance(status_override, str) and status_override
        ):
            raise ValueError(
                "metadata['status'] must be a non-empty string"
            )
        if menu_id_override is not None and not (
            isinstance(menu_id_override, str) and menu_id_override
        ):
            raise ValueError(
                "metadata['menu_id'] must be a non-empty string"
            )

        if menu_id_override is not None:
            menu_id = menu_id_override
        elif persist:
            menu_id = f"menu:{request.request_id}"
        else:
            menu_id = f"menu:preview:{request.request_id}"

        # Compute default status: any candidate -> completed; none -> empty.
        any_candidates = bool(
            signal_ids
            or variable_observation_ids
            or exposure_ids
            or interaction_ids
        )
        status = (
            status_override
            if status_override is not None
            else ("completed" if any_candidates else "empty")
        )

        # Augment menu metadata with builder-level audit fields so a
        # consumer reading the persisted menu can reconstruct the
        # build context.
        menu_metadata = dict(request_metadata)
        menu_metadata["build_request_id"] = request.request_id
        menu_metadata["build_status"] = status
        if failures:
            menu_metadata["build_failed_sources"] = list(failures)

        if persist:
            menu = ObservationMenu(
                menu_id=menu_id,
                actor_id=request.actor_id,
                as_of_date=as_of_date,
                phase_id=request.phase_id,
                available_signal_ids=signal_ids,
                available_interaction_ids=interaction_ids,
                available_variable_observation_ids=variable_observation_ids,
                available_exposure_ids=exposure_ids,
                metadata=menu_metadata,
            )
            self.attention.add_menu(menu)

        return ObservationMenuBuildResult(
            request_id=request.request_id,
            menu_id=menu_id,
            actor_id=request.actor_id,
            as_of_date=as_of_date,
            phase_id=request.phase_id,
            available_signal_ids=signal_ids,
            available_variable_observation_ids=variable_observation_ids,
            available_exposure_ids=exposure_ids,
            available_interaction_ids=interaction_ids,
            status=status,
            metadata=menu_metadata,
        )

    def _resolve_as_of_date(
        self, request: ObservationMenuBuildRequest
    ) -> str:
        if request.as_of_date is not None:
            return _coerce_iso_date(request.as_of_date)
        if self.clock is not None and self.clock.current_date is not None:
            return self.clock.current_date.isoformat()
        raise ObservationMenuBuildMissingDateError(
            "Request has no as_of_date and no clock is wired; "
            "supply request.as_of_date or initialize the builder with a clock."
        )

    def _collect_interaction_ids(
        self,
        signal_ids: tuple[str, ...],
        variable_observation_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """
        Union of ``carried_by_interaction_id`` values from the
        surfaced variable observations + the ``interaction_id``
        key (when present) in the surfaced signals' metadata.

        v1.8.11 does **not** verify that each interaction id
        actually exists in ``InteractionBook``. The id is a
        forward-pointing data reference; v1.8.12+ consumers may
        validate it explicitly when they need to.
        """
        seen: set[str] = set()
        out: list[str] = []

        for obs_id in variable_observation_ids:
            try:
                obs = self.variables.get_observation(obs_id)
            except Exception:  # noqa: BLE001
                continue
            interaction_id = obs.carried_by_interaction_id
            if interaction_id and interaction_id not in seen:
                seen.add(interaction_id)
                out.append(interaction_id)

        for signal_id in signal_ids:
            try:
                signal = self.signals.get_signal(signal_id)
            except Exception:  # noqa: BLE001
                continue
            interaction_id = signal.metadata.get("interaction_id")
            if (
                isinstance(interaction_id, str)
                and interaction_id
                and interaction_id not in seen
            ):
                seen.add(interaction_id)
                out.append(interaction_id)

        return tuple(out)
