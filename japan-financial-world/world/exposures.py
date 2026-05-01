"""
v1.8.10 Exposure / Dependency Layer.

Implements the kernel-level book that records *who depends on
which world variable*. ``ExposureRecord`` completes the
source / scope / **exposure** hook chain that the v1.8.8 hardening
(§50.1) named: ``ReferenceVariableSpec`` already declares the
source hook (which space publishes the variable) and the scope
hook (which spaces / sectors / subjects / asset classes the
variable is relevant to); v1.8.10 adds the missing piece by
naming, as data, **which subjects depend on which variable, in
what direction, with what synthetic dependency strength**.

Scope discipline (v1.8.10)
--------------------------

- The book stores ``ExposureRecord`` entries and offers filter /
  lookup APIs. It does **not** compute impacts, calibrate
  sensitivities, multiply variable values by magnitudes, adjust
  valuations, update DSCR / LTV / leverage, simulate transmission
  chains, or move any other book.
- ``ExposureRecord.magnitude`` is a **synthetic dependency
  strength**, not a calibrated sensitivity. Future v2 / v3
  calibration may attach real sensitivity numbers; v1.8.10 stores
  whatever the caller declares within ``[0.0, 1.0]``.
- ``direction`` is a free-form **label**, not an arithmetic sign.
  Suggested vocabulary: ``"positive"``, ``"negative"``,
  ``"mixed"``, ``"neutral"``, ``"nonlinear"``. The book does not
  do any sign math.
- Cross-references (``subject_id``, ``variable_id``,
  ``source_ref_ids``) are recorded as data and **not** validated
  against any other book, per the v0/v1 cross-reference rule.
- v1.8.10 ships zero economic behavior: no scenario engine, no
  stochastic processes, no commodity / power / technology
  dynamics, no policy reaction, no price formation, no trading,
  no lending decisions, no Japan calibration.

Where v1.8.10 sits in the responsibility chain
-----------------------------------------------

    ReferenceVariableSpec    — what variable EXISTS (v1.8.9)
    VariableObservation      — what value was OBSERVED and WHEN (v1.8.9)
    ExposureRecord           — who DEPENDS on it (v1.8.10)   <— this layer
    AttentionProfile         — who WATCHES it (v1.8.5)
    Routine                  — when it is REVIEWED (v1.8.4 / v1.8.6 / v1.8.7)

Each step is opt-in. A subject's exposure to a variable does **not**
auto-watch the variable, does **not** auto-fire a routine, does
**not** produce any economic effect. The exposure layer simply
lets future v1.8.11 menu builders and v1.8.12+ routines look up
"which variables matter to this subject, and how" as data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ExposureError(Exception):
    """Base class for exposure-layer errors."""


class DuplicateExposureError(ExposureError):
    """Raised when an exposure_id is added twice."""


class UnknownExposureError(ExposureError, KeyError):
    """Raised when an exposure_id is not found."""


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
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExposureRecord:
    """
    A declared dependency of one subject on one world variable.

    An ``ExposureRecord`` says "subject X depends on variable Y in
    direction D, with synthetic strength M, in metric form K." It
    is **data**, not a calculation. v1.8.10 does not multiply M by
    any observation of Y, does not derive an impact estimate, and
    does not feed any other book.

    Field semantics
    ---------------
    - ``exposure_id`` is the stable id; unique within an
      ``ExposureBook``.
    - ``subject_id`` is the WorldID (or free-form id) of the
      depending entity. May refer to a firm, bank, investor,
      asset, contract, sector, market, portfolio, etc.
      Cross-reference is data; not validated against the registry.
    - ``subject_type`` names the *kind* of subject (free-form
      string; suggested values: ``"firm"``, ``"bank"``,
      ``"investor"``, ``"asset"``, ``"contract"``, ``"sector"``,
      ``"market"``, ``"portfolio"``).
    - ``variable_id`` references a ``ReferenceVariableSpec`` in
      ``WorldVariableBook``. Cross-reference is data; not
      validated.
    - ``exposure_type`` names the *kind* of dependency (free-form
      string; suggested values: ``"input_cost"``,
      ``"funding_cost"``, ``"discount_rate"``, ``"collateral"``,
      ``"revenue"``, ``"translation"``, ``"productivity"``,
      ``"labor_displacement"``, ``"narrative"``).
    - ``metric`` names the *transmission target*: the named
      consequence the dependency expresses (free-form string;
      suggested: ``"packaging_margin_pressure"``,
      ``"debt_service_burden"``, ``"collateral_value"``,
      ``"portfolio_translation_exposure"``,
      ``"operating_cost_pressure"``,
      ``"labor_displacement_risk"``).
    - ``direction`` is a free-form **label**, not arithmetic.
      Suggested vocabulary: ``"positive"`` / ``"negative"`` /
      ``"mixed"`` / ``"neutral"`` / ``"nonlinear"``. The book
      does not do sign math; consumers in later milestones may
      interpret the label, but v1.8.10 stores it verbatim.
    - ``magnitude`` is a synthetic dependency strength in
      ``[0.0, 1.0]``. NOT a calibrated sensitivity. NOT an impact
      coefficient. v1.8.10 enforces the bounds; v2 / v3
      calibration may relax or replace this field.
    - ``unit`` is a free-form string describing the unit of the
      magnitude (e.g., ``"synthetic_strength"``,
      ``"input_cost_share"``, ``"revenue_share"``,
      ``"covariance_proxy"``).
    - ``confidence`` is a float in ``[0.0, 1.0]``.
    - ``effective_from`` and ``effective_to`` are optional ISO
      ``YYYY-MM-DD`` date strings naming a validity window.
      v1.8.10 supports ``list_active_as_of(...)`` filtering.
    - ``source_ref_ids`` is a tuple of free-form refs that
      *justify* the exposure (signal ids, document refs, expert
      pseudonyms, valuation methodology refs). Not validated.
    - ``metadata`` is free-form. Suggested keys:
      ``"transmission_chain"`` (list of intermediate variables),
      ``"notes"``, ``"calibration_status"`` (e.g.
      ``"synthetic"`` / ``"public_data_calibrated"`` /
      ``"proprietary"``).

    Cross-references stored as data; the record does not validate
    that ``subject_id`` resolves to a registered object, that
    ``variable_id`` exists in ``WorldVariableBook``, or that
    ``source_ref_ids`` resolve to anything. Per the v0 / v1
    cross-reference rule.
    """

    exposure_id: str
    subject_id: str
    subject_type: str
    variable_id: str
    exposure_type: str
    metric: str
    direction: str
    magnitude: float
    unit: str = "synthetic_strength"
    confidence: float = 1.0
    effective_from: str | None = None
    effective_to: str | None = None
    source_ref_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "exposure_id",
            "subject_id",
            "subject_type",
            "variable_id",
            "exposure_type",
            "metric",
            "direction",
            "unit",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required and must be a non-empty string")

        # Magnitude — synthetic dependency strength in [0, 1].
        if (
            isinstance(self.magnitude, bool)
            or not isinstance(self.magnitude, (int, float))
        ):
            raise ValueError("magnitude must be a number")
        if not (0.0 <= float(self.magnitude) <= 1.0):
            raise ValueError(
                "magnitude must be between 0 and 1 inclusive (synthetic "
                "dependency strength; not a calibrated sensitivity)"
            )
        object.__setattr__(self, "magnitude", float(self.magnitude))

        # Confidence — [0, 1].
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError("confidence must be between 0 and 1 inclusive")
        object.__setattr__(self, "confidence", float(self.confidence))

        # Optional date fields.
        for name in ("effective_from", "effective_to"):
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

        # Window sanity: if both bounds are present and effective_from
        # is strictly after effective_to, the record is malformed.
        if (
            self.effective_from is not None
            and self.effective_to is not None
            and self.effective_from > self.effective_to
        ):
            raise ValueError(
                f"effective_from {self.effective_from!r} cannot be later "
                f"than effective_to {self.effective_to!r}"
            )

        # Tuple normalization.
        normalized = _normalize_string_tuple(
            self.source_ref_ids, field_name="source_ref_ids"
        )
        object.__setattr__(self, "source_ref_ids", normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def is_active_as_of(self, as_of_date: date | str) -> bool:
        """Return True if this record's validity window contains
        ``as_of_date``. Open-ended bounds (``None``) are treated as
        ``-infinity`` / ``+infinity`` respectively."""
        target = _coerce_iso_date(as_of_date)
        if self.effective_from is not None and target < self.effective_from:
            return False
        if self.effective_to is not None and target > self.effective_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "exposure_id": self.exposure_id,
            "subject_id": self.subject_id,
            "subject_type": self.subject_type,
            "variable_id": self.variable_id,
            "exposure_type": self.exposure_type,
            "metric": self.metric,
            "direction": self.direction,
            "magnitude": self.magnitude,
            "unit": self.unit,
            "confidence": self.confidence,
            "effective_from": self.effective_from,
            "effective_to": self.effective_to,
            "source_ref_ids": list(self.source_ref_ids),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class ExposureBook:
    """
    Storage for ``ExposureRecord`` entries.

    The book is append-only, emits one ledger record on each insert,
    and refuses to mutate any other v0/v1 source-of-truth book.
    v1.8.10 ships storage and lookup only — no impact computation,
    no sensitivity calibration, no transmission simulation, no
    state mutation.

    Cross-references are recorded as data; the book does not
    validate ``subject_id`` against the registry or ``variable_id``
    against ``WorldVariableBook``.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _exposures: dict[str, ExposureRecord] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_exposure(self, record: ExposureRecord) -> ExposureRecord:
        if record.exposure_id in self._exposures:
            raise DuplicateExposureError(
                f"Duplicate exposure_id: {record.exposure_id}"
            )
        self._exposures[record.exposure_id] = record

        if self.ledger is not None:
            self.ledger.append(
                event_type="exposure_added",
                simulation_date=self._now(),
                object_id=record.exposure_id,
                source=record.subject_id,
                target=record.variable_id,
                payload={
                    "exposure_id": record.exposure_id,
                    "subject_id": record.subject_id,
                    "subject_type": record.subject_type,
                    "variable_id": record.variable_id,
                    "exposure_type": record.exposure_type,
                    "metric": record.metric,
                    "direction": record.direction,
                    "magnitude": record.magnitude,
                    "unit": record.unit,
                    "confidence": record.confidence,
                    "effective_from": record.effective_from,
                    "effective_to": record.effective_to,
                    "source_ref_ids": list(record.source_ref_ids),
                },
                space_id="exposures",
            )
        return record

    def get_exposure(self, exposure_id: str) -> ExposureRecord:
        try:
            return self._exposures[exposure_id]
        except KeyError as exc:
            raise UnknownExposureError(
                f"Exposure not found: {exposure_id!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Bulk listing
    # ------------------------------------------------------------------

    def list_exposures(self) -> tuple[ExposureRecord, ...]:
        return tuple(self._exposures.values())

    def list_by_subject(self, subject_id: str) -> tuple[ExposureRecord, ...]:
        return tuple(
            r for r in self._exposures.values() if r.subject_id == subject_id
        )

    def list_by_subject_type(
        self, subject_type: str
    ) -> tuple[ExposureRecord, ...]:
        return tuple(
            r
            for r in self._exposures.values()
            if r.subject_type == subject_type
        )

    def list_by_variable(self, variable_id: str) -> tuple[ExposureRecord, ...]:
        return tuple(
            r for r in self._exposures.values() if r.variable_id == variable_id
        )

    def list_by_exposure_type(
        self, exposure_type: str
    ) -> tuple[ExposureRecord, ...]:
        return tuple(
            r
            for r in self._exposures.values()
            if r.exposure_type == exposure_type
        )

    def list_by_metric(self, metric: str) -> tuple[ExposureRecord, ...]:
        return tuple(
            r for r in self._exposures.values() if r.metric == metric
        )

    def list_by_direction(self, direction: str) -> tuple[ExposureRecord, ...]:
        return tuple(
            r for r in self._exposures.values() if r.direction == direction
        )

    def list_active_as_of(
        self, as_of_date: date | str
    ) -> tuple[ExposureRecord, ...]:
        """
        Return exposures whose validity window contains
        ``as_of_date``. Open-ended bounds (``effective_from=None``
        / ``effective_to=None``) are treated as
        ``-infinity`` / ``+infinity`` respectively, so an exposure
        with both bounds ``None`` is always active.

        ISO ``YYYY-MM-DD`` strings sort lexicographically the same
        as chronologically.
        """
        target = _coerce_iso_date(as_of_date)
        return tuple(
            r
            for r in self._exposures.values()
            if r.is_active_as_of(target)
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        exposures = sorted(
            (r.to_dict() for r in self._exposures.values()),
            key=lambda item: item["exposure_id"],
        )
        return {
            "exposure_count": len(exposures),
            "exposures": exposures,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
