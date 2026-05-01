"""
v1.8.9 WorldVariableBook — storage for reference variable specs and
observations.

Implements the v1.8.8 design's storage layer: a kernel-level book
that stores ``ReferenceVariableSpec`` records (what variables exist)
and ``VariableObservation`` records (what value was observed and
when), with explicit anchoring to spaces, channels, and future
exposure / dependency records.

Naming choice
-------------

The book is named **`WorldVariableBook`**, not `IndicatorBook`.
"World variable" matches the v1.8.8 design's conceptual
classification — a reference variable is a *world-context / field /
substrate variable*, not specifically a macro indicator. Energy
variables, technology indices, and qualitative narratives are
first-class members of the layer; "indicator" would narrow to
macroeconomic context only and obscure the AI / electricity / labor
groups. The class name is `WorldVariableBook`; the module is
`world/variables.py`.

Scope discipline (v1.8.9)
-------------------------

- The book stores ``ReferenceVariableSpec`` and ``VariableObservation``
  records and offers filter / lookup APIs. It does **not** calculate
  GDP, forecast CPI, set rates, simulate commodity / power /
  technology dynamics, execute policy reactions, move prices,
  trigger trades, or perform Japan calibration.
- A variable observation does **not** auto-trigger any routine. The
  v1.8.8 four-gate rule (visibility / availability / selection /
  consumption) governs when an observation matters — and three of
  the four gates live outside this book.
- Cross-references (``variable_id`` on observations,
  ``revision_of`` between observations, ``carried_by_interaction_id``,
  etc.) are recorded as data and **not** validated against any
  other book. The v0/v1 cross-reference rule holds.

The book offers **visibility-aware** read APIs
(``list_observations_visible_as_of``, ``latest_observation``) so
callers can avoid look-ahead bias by construction. The visibility
filter is the v1.8.8 hardening's gate 1; gates 2-4 (availability,
selection, consumption) live in v1.8.10 / v1.8.11 / v1.8.6+ layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class VariableError(Exception):
    """Base class for world-variable layer errors."""


class DuplicateVariableError(VariableError):
    """Raised when a variable_id is added twice."""


class DuplicateVariableObservationError(VariableError):
    """Raised when an observation_id is added twice."""


class UnknownVariableError(VariableError, KeyError):
    """Raised when a variable_id is not found."""


class UnknownVariableObservationError(VariableError, KeyError):
    """Raised when an observation_id is not found."""


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


# ---------------------------------------------------------------------------
# ReferenceVariableSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceVariableSpec:
    """
    Static declaration of one observable world-context variable.

    A ``ReferenceVariable`` is **not** an Agent, **not** a Space,
    **not** a Scenario, **not** a Shock, and **not** a `PriceBook`
    replacement. It is a *world-context / field / substrate variable*
    that may be observed by agents through routines and interaction
    channels. See ``v1_reference_variable_layer_design.md``.

    Three required hooks (v1.8.8 hardening):

    1. **Source hook** — ``source_space_id`` (required) and
       ``source_id`` (optional). Names *who publishes / observes*
       the variable.
    2. **Scope hook** — ``related_space_ids``,
       ``related_subject_ids``, ``related_sector_ids``,
       ``related_asset_class_ids``, ``observability_scope``,
       ``typical_consumer_space_ids``. Names *what the variable is
       relevant to*.
    3. **Exposure hook** — lives in v1.8.10 ``ExposureRecord``.
       The spec names which scope the exposure layer is expected to
       resolve against; the exposure layer itself is a later
       milestone.

    Field semantics
    ---------------
    - ``variable_id`` and ``variable_name`` are required strings.
    - ``variable_group`` and ``variable_type`` are free-form strings
      (controlled-label-like; v1.8.9 does not enum-lock the
      vocabulary). Suggested values for ``variable_group`` are the
      13 groups in the design doc; suggested values for
      ``variable_type`` include ``"level"``, ``"rate"``,
      ``"index"``, ``"spread"``, ``"ratio"``, ``"log_change"``,
      ``"qualitative_score"``.
    - ``source_space_id`` is required; the publishing / observing
      space.
    - ``source_id`` is optional; a named source within
      ``source_space_id``.
    - ``related_*`` tuples are deterministically normalized
      (declaration order preserved; each entry must be a non-empty
      string).
    - ``canonical_unit`` is a free-form unit string.
    - ``frequency`` is a free-form label; the v0 ``Frequency`` enum
      values are recommended (``"DAILY"`` / ``"MONTHLY"`` /
      ``"QUARTERLY"`` / ``"YEARLY"``) plus ``"CONTINUOUS"`` and
      ``"IRREGULAR"``.
    - ``observation_kind`` is a free-form label; suggested values:
      ``"released"``, ``"continuous"``, ``"estimate"``,
      ``"expectations_proxy"``, ``"qualitative"``.
    - ``default_visibility`` mirrors the ``SignalBook`` vocabulary
      (``"public"`` / ``"restricted"`` / ``"private"``).
    - ``observability_scope`` controls who may observe the variable
      (``"global"`` / ``"jurisdictional"`` / ``"private"``); v1.8.9
      stores it, v1.8.11 will enforce in the menu builder.
    - ``typical_consumer_space_ids`` is a tuple of spaces typically
      expected to consume the variable. Used by v1.8.11+ for default
      menu suggestions.
    - ``expected_release_lag_days`` is the typical lag between the
      period a variable describes and its release date. ``None`` for
      continuous / live variables.
    - ``metadata`` is free-form for provenance, parameters, and
      owner notes.

    Cross-references are recorded as data; the spec does not
    validate ``source_space_id`` / related ids / typical-consumer
    ids against the registry, per the v0/v1 cross-reference rule.
    """

    variable_id: str
    variable_name: str
    variable_group: str
    variable_type: str
    source_space_id: str
    canonical_unit: str
    frequency: str
    observation_kind: str
    default_visibility: str = "public"
    observability_scope: str = "global"
    source_id: str | None = None
    related_space_ids: tuple[str, ...] = field(default_factory=tuple)
    related_subject_ids: tuple[str, ...] = field(default_factory=tuple)
    related_sector_ids: tuple[str, ...] = field(default_factory=tuple)
    related_asset_class_ids: tuple[str, ...] = field(default_factory=tuple)
    typical_consumer_space_ids: tuple[str, ...] = field(default_factory=tuple)
    expected_release_lag_days: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "variable_id",
            "variable_name",
            "variable_group",
            "variable_type",
            "source_space_id",
            "canonical_unit",
            "frequency",
            "observation_kind",
            "default_visibility",
            "observability_scope",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required and must be a non-empty string")

        if self.source_id is not None and not (
            isinstance(self.source_id, str) and self.source_id
        ):
            raise ValueError("source_id must be a non-empty string or None")

        if self.expected_release_lag_days is not None:
            if (
                isinstance(self.expected_release_lag_days, bool)
                or not isinstance(self.expected_release_lag_days, int)
            ):
                raise ValueError(
                    "expected_release_lag_days must be int or None"
                )

        for tuple_field_name in (
            "related_space_ids",
            "related_subject_ids",
            "related_sector_ids",
            "related_asset_class_ids",
            "typical_consumer_space_ids",
        ):
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable_id": self.variable_id,
            "variable_name": self.variable_name,
            "variable_group": self.variable_group,
            "variable_type": self.variable_type,
            "source_space_id": self.source_space_id,
            "source_id": self.source_id,
            "canonical_unit": self.canonical_unit,
            "frequency": self.frequency,
            "observation_kind": self.observation_kind,
            "default_visibility": self.default_visibility,
            "observability_scope": self.observability_scope,
            "related_space_ids": list(self.related_space_ids),
            "related_subject_ids": list(self.related_subject_ids),
            "related_sector_ids": list(self.related_sector_ids),
            "related_asset_class_ids": list(self.related_asset_class_ids),
            "typical_consumer_space_ids": list(self.typical_consumer_space_ids),
            "expected_release_lag_days": self.expected_release_lag_days,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# VariableObservation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VariableObservation:
    """
    One released or recorded data point on a reference variable.

    Time fields and look-ahead-bias prevention
    -------------------------------------------

    - ``as_of_date`` (required): the canonical timestamp the
      observation carries — typically the release date for
      released variables and the quote date for continuous ones.
    - ``observation_period_start`` / ``observation_period_end``
      (optional): the period the observation *describes*. For GDP
      Q1 2026, the period spans 2026-01-01 to 2026-03-31.
    - ``release_date`` (optional): the official release date when
      different from ``as_of_date`` (e.g., embargo / leak edge
      cases). When both ``visible_from_date`` and
      ``release_date`` are absent, ``as_of_date`` is the visibility
      timestamp.
    - ``visible_from_date`` (optional): the **operational visibility
      timestamp** — the date this observation became visible to
      agents in the simulated world. When provided, this field
      wins over ``as_of_date`` for visibility filtering. v1.8.11
      menu builder uses ``visible_from_date if present else
      as_of_date`` to gate look-ahead.
    - ``vintage_id`` (optional): a label naming this vintage
      (e.g., ``"2026Q1_initial"`` / ``"2026Q1_first_revision"``).
    - ``revision_of`` (optional): when this observation revises a
      prior one, the prior ``observation_id``. Forms a linked-list
      of revisions. v1.8.9 stores the link; revision *resolution*
      (e.g., "give me the latest non-superseded vintage of
      variable X for period Y") is a later milestone.

    Anchoring fields (v1.8.8 hardening)
    -----------------------------------

    - ``observed_by_space_id`` (optional): the space that recorded
      the observation. Often equals the spec's
      ``source_space_id``; may differ.
    - ``published_by_source_id`` (optional): named publisher within
      the recording space.
    - ``carried_by_interaction_id`` (optional): the
      ``InteractionSpec.interaction_id`` of the channel through
      which the observation reached its consumers. Null when the
      observation was simply stored without a channel record.

    Other fields
    ------------

    - ``value``: ``int | float | str | None``. Numeric values
      should be accepted for the typical macro / FX / commodity /
      index variables; string values support qualitative scores.
      v1.8.9 does not constrain the type beyond "passes through
      to_dict cleanly."
    - ``unit``: the unit at observation time. Often equals
      ``spec.canonical_unit``; may differ when a release is in
      nominal terms while the spec is real, or vice versa.
    - ``confidence``: float in [0.0, 1.0].
    - ``metadata``: free-form. Suggested keys:
      ``"data_quality"``, ``"survey_response_count"``.
    """

    observation_id: str
    variable_id: str
    as_of_date: str
    value: Any
    unit: str
    observation_period_start: str | None = None
    observation_period_end: str | None = None
    release_date: str | None = None
    visible_from_date: str | None = None
    vintage_id: str | None = None
    revision_of: str | None = None
    observed_by_space_id: str | None = None
    published_by_source_id: str | None = None
    carried_by_interaction_id: str | None = None
    confidence: float = 1.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("observation_id", "variable_id", "unit"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required and must be a non-empty string")

        if not isinstance(self.as_of_date, (str, date)) or (
            isinstance(self.as_of_date, str) and not self.as_of_date
        ):
            raise ValueError("as_of_date is required")
        object.__setattr__(self, "as_of_date", _coerce_iso_date(self.as_of_date))

        for name in (
            "observation_period_start",
            "observation_period_end",
            "release_date",
            "visible_from_date",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            if isinstance(value, date):
                object.__setattr__(self, name, value.isoformat())
            elif isinstance(value, str):
                if not value:
                    raise ValueError(
                        f"{name} must be a non-empty ISO date string or None"
                    )
            else:
                raise ValueError(
                    f"{name} must be a date / ISO string / None"
                )

        for name in (
            "vintage_id",
            "revision_of",
            "observed_by_space_id",
            "published_by_source_id",
            "carried_by_interaction_id",
        ):
            value = getattr(self, name)
            if value is not None and not (isinstance(value, str) and value):
                raise ValueError(
                    f"{name} must be a non-empty string or None"
                )

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("confidence must be between 0 and 1 inclusive")
        object.__setattr__(self, "confidence", float(self.confidence))

        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def visibility_date(self) -> str:
        """
        Operational visibility date used by the book's filter APIs.

        When ``visible_from_date`` is present, it wins; otherwise
        ``as_of_date`` is used. ``release_date`` is *not* used for
        visibility; it is reference metadata for "official release
        moment differs from when this became visible to agents."
        """
        return (
            self.visible_from_date
            if self.visible_from_date is not None
            else self.as_of_date
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "variable_id": self.variable_id,
            "as_of_date": self.as_of_date,
            "observation_period_start": self.observation_period_start,
            "observation_period_end": self.observation_period_end,
            "release_date": self.release_date,
            "visible_from_date": self.visible_from_date,
            "vintage_id": self.vintage_id,
            "revision_of": self.revision_of,
            "value": self.value,
            "unit": self.unit,
            "observed_by_space_id": self.observed_by_space_id,
            "published_by_source_id": self.published_by_source_id,
            "carried_by_interaction_id": self.carried_by_interaction_id,
            "confidence": self.confidence,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class WorldVariableBook:
    """
    Storage for ``ReferenceVariableSpec`` and ``VariableObservation``
    records.

    Append-only: ``add_variable`` and ``add_observation`` reject
    duplicates and emit one ledger record each. The book reads from
    its own internal stores only; it does not mutate any other v0/v1
    source-of-truth book.

    Cross-references are stored as data, not validated. Look-ahead
    filtering is handled by ``list_observations_visible_as_of`` and
    ``latest_observation``; callers that bypass these helpers and
    iterate raw records are responsible for applying the same gate.
    """

    ledger: Any | None = None
    clock: Any | None = None
    _variables: dict[str, ReferenceVariableSpec] = field(default_factory=dict)
    _observations: dict[str, VariableObservation] = field(default_factory=dict)
    _observations_by_variable: dict[str, list[str]] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # Variable CRUD
    # ------------------------------------------------------------------

    def add_variable(self, spec: ReferenceVariableSpec) -> ReferenceVariableSpec:
        if spec.variable_id in self._variables:
            raise DuplicateVariableError(
                f"Duplicate variable_id: {spec.variable_id}"
            )
        self._variables[spec.variable_id] = spec

        if self.ledger is not None:
            self.ledger.append(
                event_type="variable_added",
                simulation_date=self._now(),
                object_id=spec.variable_id,
                source=spec.source_space_id,
                payload={
                    "variable_id": spec.variable_id,
                    "variable_name": spec.variable_name,
                    "variable_group": spec.variable_group,
                    "variable_type": spec.variable_type,
                    "source_space_id": spec.source_space_id,
                    "source_id": spec.source_id,
                    "canonical_unit": spec.canonical_unit,
                    "frequency": spec.frequency,
                    "observation_kind": spec.observation_kind,
                    "default_visibility": spec.default_visibility,
                    "observability_scope": spec.observability_scope,
                    "expected_release_lag_days": spec.expected_release_lag_days,
                    "related_space_ids": list(spec.related_space_ids),
                    "related_subject_ids": list(spec.related_subject_ids),
                    "related_sector_ids": list(spec.related_sector_ids),
                    "related_asset_class_ids": list(spec.related_asset_class_ids),
                    "typical_consumer_space_ids": list(
                        spec.typical_consumer_space_ids
                    ),
                },
                space_id="variables",
                visibility=spec.default_visibility,
            )
        return spec

    def get_variable(self, variable_id: str) -> ReferenceVariableSpec:
        try:
            return self._variables[variable_id]
        except KeyError as exc:
            raise UnknownVariableError(
                f"Variable not found: {variable_id!r}"
            ) from exc

    def list_variables(self) -> tuple[ReferenceVariableSpec, ...]:
        return tuple(self._variables.values())

    def list_variables_by_group(
        self, variable_group: str
    ) -> tuple[ReferenceVariableSpec, ...]:
        return tuple(
            spec
            for spec in self._variables.values()
            if spec.variable_group == variable_group
        )

    def list_variables_by_source_space(
        self, source_space_id: str
    ) -> tuple[ReferenceVariableSpec, ...]:
        return tuple(
            spec
            for spec in self._variables.values()
            if spec.source_space_id == source_space_id
        )

    def list_variables_by_related_space(
        self, space_id: str
    ) -> tuple[ReferenceVariableSpec, ...]:
        return tuple(
            spec
            for spec in self._variables.values()
            if space_id in spec.related_space_ids
        )

    def list_variables_by_consumer_space(
        self, space_id: str
    ) -> tuple[ReferenceVariableSpec, ...]:
        return tuple(
            spec
            for spec in self._variables.values()
            if space_id in spec.typical_consumer_space_ids
        )

    # ------------------------------------------------------------------
    # Observation CRUD
    # ------------------------------------------------------------------

    def add_observation(
        self, observation: VariableObservation
    ) -> VariableObservation:
        if observation.observation_id in self._observations:
            raise DuplicateVariableObservationError(
                f"Duplicate observation_id: {observation.observation_id}"
            )
        self._observations[observation.observation_id] = observation
        self._observations_by_variable.setdefault(
            observation.variable_id, []
        ).append(observation.observation_id)

        if self.ledger is not None:
            self.ledger.append(
                event_type="variable_observation_added",
                simulation_date=observation.as_of_date,
                object_id=observation.observation_id,
                target=observation.variable_id,
                source=observation.observed_by_space_id,
                payload={
                    "observation_id": observation.observation_id,
                    "variable_id": observation.variable_id,
                    "as_of_date": observation.as_of_date,
                    "observation_period_start": observation.observation_period_start,
                    "observation_period_end": observation.observation_period_end,
                    "release_date": observation.release_date,
                    "visible_from_date": observation.visible_from_date,
                    "vintage_id": observation.vintage_id,
                    "revision_of": observation.revision_of,
                    "value": observation.value,
                    "unit": observation.unit,
                    "observed_by_space_id": observation.observed_by_space_id,
                    "published_by_source_id": observation.published_by_source_id,
                    "carried_by_interaction_id": observation.carried_by_interaction_id,
                    "confidence": observation.confidence,
                },
                space_id="variables",
                correlation_id=observation.carried_by_interaction_id,
            )
        return observation

    def get_observation(self, observation_id: str) -> VariableObservation:
        try:
            return self._observations[observation_id]
        except KeyError as exc:
            raise UnknownVariableObservationError(
                f"Observation not found: {observation_id!r}"
            ) from exc

    def list_observations(
        self, variable_id: str | None = None
    ) -> tuple[VariableObservation, ...]:
        if variable_id is None:
            return tuple(self._observations.values())
        return self.list_observations_by_variable(variable_id)

    def list_observations_by_variable(
        self, variable_id: str
    ) -> tuple[VariableObservation, ...]:
        ids = self._observations_by_variable.get(variable_id, [])
        return tuple(self._observations[oid] for oid in ids)

    def list_observations_by_as_of_date(
        self, as_of_date: date | str
    ) -> tuple[VariableObservation, ...]:
        target = _coerce_iso_date(as_of_date)
        return tuple(
            obs
            for obs in self._observations.values()
            if obs.as_of_date == target
        )

    def list_observations_visible_as_of(
        self, as_of_date: date | str
    ) -> tuple[VariableObservation, ...]:
        """
        Return observations whose ``visibility_date`` (which is
        ``visible_from_date if present else as_of_date``) is
        ``<= as_of_date``.

        This is the v1.8.8 hardening's gate-1 visibility filter. ISO
        ``YYYY-MM-DD`` strings sort lexicographically the same as
        chronologically, so direct string comparison is correct.
        """
        target = _coerce_iso_date(as_of_date)
        return tuple(
            obs
            for obs in self._observations.values()
            if obs.visibility_date <= target
        )

    def list_observations_carried_by_interaction(
        self, interaction_id: str
    ) -> tuple[VariableObservation, ...]:
        return tuple(
            obs
            for obs in self._observations.values()
            if obs.carried_by_interaction_id == interaction_id
        )

    def latest_observation(
        self,
        variable_id: str,
        as_of_date: date | str | None = None,
    ) -> VariableObservation | None:
        """
        Return the latest visible observation of ``variable_id``.

        If ``as_of_date`` is provided, only observations with
        ``visibility_date <= as_of_date`` are considered. If no
        observations are visible, returns ``None``.

        The "latest" tiebreaker is **deterministic**:

            (visibility_date desc, as_of_date desc, observation_id desc)

        — same visibility date wins on as_of_date; same as_of_date
        wins on observation_id (lexicographic). Two repeated calls
        with the same book state always return the same record.
        """
        candidates = list(self.list_observations_by_variable(variable_id))
        if as_of_date is not None:
            target = _coerce_iso_date(as_of_date)
            candidates = [
                obs for obs in candidates if obs.visibility_date <= target
            ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda obs: (
                obs.visibility_date,
                obs.as_of_date,
                obs.observation_id,
            ),
            reverse=True,
        )
        return candidates[0]

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        variables = sorted(
            (spec.to_dict() for spec in self._variables.values()),
            key=lambda item: item["variable_id"],
        )
        observations = sorted(
            (obs.to_dict() for obs in self._observations.values()),
            key=lambda item: item["observation_id"],
        )
        return {
            "variable_count": len(variables),
            "observation_count": len(observations),
            "variables": variables,
            "observations": observations,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
