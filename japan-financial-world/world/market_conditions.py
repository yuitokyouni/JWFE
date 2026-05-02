"""
v1.11.0 MarketConditionRecord + MarketConditionBook.

Implements the capital-market context-signal layer named in
``docs/world_model.md`` §77 and in
``docs/v1_11_financial_market_surface_design.md`` (when that
document lands). The layer makes the living reference world
visibly *finance-aware* — interest-rate environment, credit-spread
environment, equity-valuation environment, funding window,
liquidity / volatility regime, issuance-market window — without
implementing price formation, trading, yield-curve calibration,
order matching, or any real market data.

- ``MarketConditionRecord`` — a single immutable, append-only
  record naming a *generic, jurisdiction-neutral* condition
  (direction + bounded synthetic strength + bounded synthetic
  confidence) for a synthetic market in a given period. The
  record is **context evidence**, not a price quote, not a yield,
  not a spread, and not a forecast.
- ``MarketConditionBook`` — append-only storage with read-only
  listings and a deterministic snapshot.

Scope discipline (v1.11.0)
==========================

A ``MarketConditionRecord`` is **context evidence** that later
milestones (firm pressure assessment, valuation refresh, bank
credit review, corporate strategic response candidates,
living-world reports) may *read* as one input among many. By
itself, a market-condition record:

- does **not** form any price, quote, yield, spread, or index
  level (no order matching, no microstructure, no clearing);
- does **not** trade, allocate, or recommend any security;
- does **not** originate, approve, reject, price, or mutate any
  loan / contract / covenant / ownership relation;
- does **not** mutate any firm financial statement;
- does **not** forecast any market level, return, or default
  probability;
- does **not** issue, allocate, or price any DCM / ECM offering;
- does **not** mutate any other source-of-truth book in the
  kernel (only the ``MarketConditionBook`` itself and the kernel
  ledger are written to).

The record fields are jurisdiction-neutral by construction. The
book refuses to validate any controlled-vocabulary field
(``market_id``, ``market_type``, ``condition_type``,
``direction``, ``time_horizon``, ``status``, ``visibility``)
against any specific country, regulator, exchange, named market
operator, or vendor benchmark — those calibrations live in v2
(Japan public-data) and beyond, not here.

Cross-references (``related_variable_ids``,
``related_signal_ids``, ``related_exposure_ids``) are recorded as
data and **not** validated for resolution against any other book,
per the v0/v1 cross-reference rule already used by every prior
v1.10 storage book.

The two numeric fields, ``strength`` and ``confidence``, are
**synthetic** quantities bounded in ``[0.0, 1.0]`` inclusive.
They are **never** calibrated yields, spreads, indices, levels,
or probabilities; they are illustrative ordering only, following
the v1 pattern set by ``world/exposures.py``,
``world/signals.py``, and ``world/industry.py``. Booleans are
rejected for both fields (since ``bool`` is a subtype of ``int``
in Python) so ``True`` / ``False`` cannot smuggle past the
bounded-numeric check.

v1.11.0 ships zero economic behavior: no order matching, no
trading, no clearing, no quote dissemination, no yield-curve
calibration, no real data ingestion, no Japan calibration, no
investment recommendation, no security recommendation, no DCM /
ECM execution, no loan origination, no lending decisions, no
covenant enforcement, no portfolio-allocation decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MarketConditionError(Exception):
    """Base class for market-condition-layer errors."""


class DuplicateMarketConditionError(MarketConditionError):
    """Raised when a condition_id is added twice."""


class UnknownMarketConditionError(MarketConditionError, KeyError):
    """Raised when a condition_id is not found."""


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
    value: Iterable[str], *, field_name: str
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
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketConditionRecord:
    """
    Immutable record of one generic capital-market condition.

    A condition record names a synthetic, jurisdiction-neutral
    *condition* of a market / sector / regime in a given period:
    a direction tag (``easing`` / ``tightening`` / ``widening`` /
    ``narrowing`` / ``supportive`` / ``restrictive`` / ``mixed`` /
    ``unknown``), a bounded synthetic strength in ``[0.0, 1.0]``,
    a horizon class, a bounded synthetic confidence in
    ``[0.0, 1.0]``, an illustrative condition-type tag, and a
    small lifecycle-status tag, plus plain-id cross-references to
    variables, signals, and exposures.

    It is **context evidence**, not a price, not a yield, not a
    spread, not a forecast, and not a real measurement.

    Field semantics
    ---------------
    - ``condition_id`` is the stable id; unique within a
      ``MarketConditionBook``. Conditions are append-only — a
      condition is never mutated in place; instead, a new
      condition is added (with a different ``condition_id``) when
      the market's stance changes (a previous record may carry
      ``status="superseded"`` for audit).
    - ``market_id`` names the synthetic market this condition
      applies to. Free-form, jurisdiction-neutral string (e.g.,
      ``"market:reference_rates_general"``).
    - ``market_type`` is a small free-form controlled-vocabulary
      tag describing the *kind* of market. Suggested generic,
      jurisdiction-neutral labels: ``"reference_rates"``,
      ``"credit_spreads"``, ``"equity_market"``,
      ``"funding_market"``, ``"issuance_market"``,
      ``"liquidity_market"``, ``"volatility_regime"``. v1.11.0
      stores the tag without enforcing membership in any specific
      list.
    - ``as_of_date`` is the required ISO ``YYYY-MM-DD`` date
      naming the period the condition is recorded against.
    - ``condition_type`` is a free-form controlled-vocabulary tag
      describing the *kind* of condition the record names.
      Suggested generic, jurisdiction-neutral labels:
      ``"rate_level"``, ``"spread_level"``,
      ``"valuation_environment"``, ``"funding_window"``,
      ``"liquidity_regime"``, ``"volatility_regime"``,
      ``"issuance_window"``. v1.11.0 stores the tag without
      enforcing membership in any specific list.
    - ``direction`` is a small free-form tag naming the
      direction class. Recommended jurisdiction-neutral labels:
      ``"easing"`` / ``"tightening"`` / ``"widening"`` /
      ``"narrowing"`` / ``"supportive"`` / ``"restrictive"`` /
      ``"mixed"`` / ``"unknown"``. v1.11.0 stores the tag without
      enforcing membership in any list.
    - ``strength`` is a synthetic, bounded numeric value in
      ``[0.0, 1.0]`` inclusive — illustrative magnitude ordering
      only, **never** a calibrated yield, spread, index level,
      probability, or any real-market measurement. Booleans are
      rejected.
    - ``time_horizon`` is a free-form label naming the horizon
      class. Recommended labels: ``"short_term"`` /
      ``"medium_term"`` / ``"long_term"`` / ``"structural"``.
    - ``confidence`` is a synthetic, bounded numeric value in
      ``[0.0, 1.0]`` inclusive — illustrative confidence ordering
      only, **never** a calibrated probability. Booleans are
      rejected.
    - ``status`` is a small free-form tag tracking the lifecycle
      of the record. Recommended jurisdiction-neutral labels:
      ``"draft"`` / ``"active"`` / ``"under_review"`` /
      ``"superseded"`` / ``"retired"`` / ``"withdrawn"``.
    - ``related_variable_ids``, ``related_signal_ids``,
      ``related_exposure_ids`` are tuples of plain-id
      cross-references; stored as data and not validated.
    - ``visibility`` is a free-form generic visibility tag
      (``"public"`` / ``"internal_only"`` / ``"restricted"``).
      Metadata only; not enforced as a runtime gate in v1.11.0.
    - ``metadata`` is free-form for provenance, parameters, and
      issuer notes. Must not carry real yields, real spreads,
      real index levels, real market-size values, real survey
      data, paid-data vendor identifiers, vendor consensus
      forecasts, expert-interview content, or any real-data
      payload; those remain restricted artifacts under
      ``docs/public_private_boundary.md`` and never appear in
      public FWE.

    Anti-fields
    -----------
    The record deliberately has **no** ``price``, ``market_price``,
    ``yield_value``, ``spread_bps``, ``index_level``,
    ``forecast_value``, ``expected_return``, ``recommendation``,
    ``target_price``, ``real_data_value``, or ``market_size``
    field. A public-FWE condition stores the synthetic
    direction / strength / confidence triple plus generic labels
    and IDs — never a calibrated number that could be confused
    with a real market quote, a real yield curve point, or a
    forecast.
    """

    condition_id: str
    market_id: str
    market_type: str
    as_of_date: str
    condition_type: str
    direction: str
    strength: float
    time_horizon: str
    confidence: float
    status: str
    visibility: str
    related_variable_ids: tuple[str, ...] = field(default_factory=tuple)
    related_signal_ids: tuple[str, ...] = field(default_factory=tuple)
    related_exposure_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "condition_id",
        "market_id",
        "market_type",
        "as_of_date",
        "condition_type",
        "direction",
        "time_horizon",
        "status",
        "visibility",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "related_variable_ids",
        "related_signal_ids",
        "related_exposure_ids",
    )

    def __post_init__(self) -> None:
        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, (str, date)) or (
                isinstance(value, str) and not value
            ):
                raise ValueError(f"{name} is required")

        # strength — synthetic magnitude in [0, 1].
        if (
            isinstance(self.strength, bool)
            or not isinstance(self.strength, (int, float))
        ):
            raise ValueError("strength must be a number")
        if not (0.0 <= float(self.strength) <= 1.0):
            raise ValueError(
                "strength must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated yield, "
                "spread, index level, or probability)"
            )
        object.__setattr__(self, "strength", float(self.strength))

        # confidence — synthetic [0, 1].
        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "confidence must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated "
                "probability)"
            )
        object.__setattr__(self, "confidence", float(self.confidence))

        object.__setattr__(
            self, "as_of_date", _coerce_iso_date(self.as_of_date)
        )

        for tuple_field_name in self.TUPLE_FIELDS:
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "market_id": self.market_id,
            "market_type": self.market_type,
            "as_of_date": self.as_of_date,
            "condition_type": self.condition_type,
            "direction": self.direction,
            "strength": self.strength,
            "time_horizon": self.time_horizon,
            "confidence": self.confidence,
            "status": self.status,
            "visibility": self.visibility,
            "related_variable_ids": list(self.related_variable_ids),
            "related_signal_ids": list(self.related_signal_ids),
            "related_exposure_ids": list(self.related_exposure_ids),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class MarketConditionBook:
    """
    Append-only storage for ``MarketConditionRecord`` instances.

    The book emits exactly one ledger record per ``add_condition``
    call (``RecordType.MARKET_CONDITION_ADDED``) and refuses to
    mutate any other source-of-truth book in the kernel. v1.11.0
    ships storage and read-only listings only — no automatic
    condition inference, no price formation, no yield-curve
    calibration, no order matching, no clearing, no economic
    behavior.

    Cross-references (``market_id``, ``related_variable_ids``,
    ``related_signal_ids``, ``related_exposure_ids``) are
    recorded as data and not validated against any other book,
    per the v0/v1 cross-reference rule.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _conditions: dict[str, MarketConditionRecord] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_condition(
        self, condition: MarketConditionRecord
    ) -> MarketConditionRecord:
        if condition.condition_id in self._conditions:
            raise DuplicateMarketConditionError(
                f"Duplicate condition_id: {condition.condition_id}"
            )
        self._conditions[condition.condition_id] = condition

        if self.ledger is not None:
            self.ledger.append(
                event_type="market_condition_added",
                simulation_date=self._now(),
                object_id=condition.condition_id,
                source=condition.market_id,
                payload={
                    "condition_id": condition.condition_id,
                    "market_id": condition.market_id,
                    "market_type": condition.market_type,
                    "as_of_date": condition.as_of_date,
                    "condition_type": condition.condition_type,
                    "direction": condition.direction,
                    "strength": condition.strength,
                    "time_horizon": condition.time_horizon,
                    "confidence": condition.confidence,
                    "status": condition.status,
                    "visibility": condition.visibility,
                    "related_variable_ids": list(
                        condition.related_variable_ids
                    ),
                    "related_signal_ids": list(
                        condition.related_signal_ids
                    ),
                    "related_exposure_ids": list(
                        condition.related_exposure_ids
                    ),
                },
                space_id="capital_markets",
                visibility=condition.visibility,
                confidence=condition.confidence,
            )
        return condition

    def get_condition(
        self, condition_id: str
    ) -> MarketConditionRecord:
        try:
            return self._conditions[condition_id]
        except KeyError as exc:
            raise UnknownMarketConditionError(
                f"Market condition not found: {condition_id!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    def list_conditions(
        self,
    ) -> tuple[MarketConditionRecord, ...]:
        return tuple(self._conditions.values())

    def list_by_market(
        self, market_id: str
    ) -> tuple[MarketConditionRecord, ...]:
        return tuple(
            c
            for c in self._conditions.values()
            if c.market_id == market_id
        )

    def list_by_market_type(
        self, market_type: str
    ) -> tuple[MarketConditionRecord, ...]:
        return tuple(
            c
            for c in self._conditions.values()
            if c.market_type == market_type
        )

    def list_by_condition_type(
        self, condition_type: str
    ) -> tuple[MarketConditionRecord, ...]:
        return tuple(
            c
            for c in self._conditions.values()
            if c.condition_type == condition_type
        )

    def list_by_direction(
        self, direction: str
    ) -> tuple[MarketConditionRecord, ...]:
        return tuple(
            c
            for c in self._conditions.values()
            if c.direction == direction
        )

    def list_by_status(
        self, status: str
    ) -> tuple[MarketConditionRecord, ...]:
        return tuple(
            c for c in self._conditions.values() if c.status == status
        )

    def list_by_date(
        self, as_of: date | str
    ) -> tuple[MarketConditionRecord, ...]:
        target = _coerce_iso_date(as_of)
        return tuple(
            c
            for c in self._conditions.values()
            if c.as_of_date == target
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        conditions = sorted(
            (c.to_dict() for c in self._conditions.values()),
            key=lambda item: item["condition_id"],
        )
        return {
            "condition_count": len(conditions),
            "conditions": conditions,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
