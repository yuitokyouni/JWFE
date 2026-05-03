"""
v1.15.2 InvestorMarketIntentRecord +
InvestorMarketIntentBook.

Append-only **label-based** synthetic record naming one
investor's market-facing interest / review posture toward a
listed security at a point in time.

This is **market interest**, **not trading**. The record is
**not** an order, **not** a trade, **not** a portfolio
allocation, **not** investment advice. It does not move a
price, an order book, a fill, an allocation, a target weight,
an overweight, an underweight, or any binding instruction.

Naming note. v1.15.0's design note proposed
``InvestorTradingIntentRecord``. v1.15.2 ships under
``InvestorMarketIntentRecord`` instead because the public FWE
substrate models *market interest* before trading. The
``intent_direction_label`` vocabulary is identical to the
v1.15 ``SAFE_INTENT_LABELS`` set carried on
``MarketVenueRecord.supported_intent_labels`` plus
``unknown``; the forbidden trading verbs (``buy`` / ``sell`` /
``order`` / ``target_weight`` / ``overweight`` /
``underweight`` / ``execution``) are rejected by closed-set
membership.

The record carries:

- four small closed-set labels:
    - ``intent_direction_label`` — review-posture direction
    - ``intensity_label``        — review-posture intensity
    - ``horizon_label``          — review-posture horizon
    - ``status``                 — lifecycle posture
- six plain-id evidence tuples:
    - ``evidence_investor_intent_ids``        (v1.12.1)
    - ``evidence_valuation_ids``              (v1.9.5 / v1.12.5)
    - ``evidence_market_environment_state_ids`` (v1.12.2)
    - ``evidence_firm_state_ids``             (v1.12.0)
    - ``evidence_security_ids``               (v1.15.1)
    - ``evidence_venue_ids``                  (v1.15.1)
  Cross-references are stored as data and not validated
  against any other book per the v0/v1 cross-reference rule.
- a synthetic ``confidence`` ordering in ``[0.0, 1.0]``.
- ``visibility``, ``metadata``.

The record carries **no** ``buy``, ``sell``, ``order``,
``order_id``, ``trade``, ``trade_id``, ``execution``,
``bid``, ``ask``, ``quote``, ``clearing``, ``settlement``,
``target_weight``, ``overweight``, ``underweight``,
``expected_return``, ``target_price``, ``recommendation``,
``investment_advice``, or ``real_data_value`` field. Tests
pin the absence on both the dataclass field set and the
ledger payload key set.

The book emits exactly one ledger record per ``add_intent``
call (``RecordType.INVESTOR_MARKET_INTENT_RECORDED``) and
refuses to mutate any other source-of-truth book in the
kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.ledger import Ledger
from world.securities import SAFE_INTENT_LABELS


# ---------------------------------------------------------------------------
# Closed-set label vocabularies
# ---------------------------------------------------------------------------


# v1.15 intent direction vocabulary. Builds on the
# ``SAFE_INTENT_LABELS`` set carried by the v1.15.1
# ``MarketVenueRecord.supported_intent_labels`` slot and adds
# ``unknown`` so a record can decline to commit to a direction
# without falling outside the closed set. The forbidden trading
# verbs (``buy`` / ``sell`` / ``order`` / ``target_weight`` /
# ``overweight`` / ``underweight`` / ``execution``) remain absent
# by construction.
INTENT_DIRECTION_LABELS: frozenset[str] = SAFE_INTENT_LABELS | {"unknown"}

INTENSITY_LABELS: frozenset[str] = frozenset(
    {
        "low",
        "moderate",
        "elevated",
        "high",
        "unknown",
    }
)

HORIZON_LABELS: frozenset[str] = frozenset(
    {
        "intraperiod",
        "near_term",
        "medium_term",
        "long_term",
        "unknown",
    }
)

STATUS_LABELS: frozenset[str] = frozenset(
    {
        "draft",
        "active",
        "stale",
        "superseded",
        "archived",
        "unknown",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InvestorMarketIntentError(Exception):
    """Base class for v1.15.2 investor-market-intent-layer errors."""


class DuplicateInvestorMarketIntentError(InvestorMarketIntentError):
    """Raised when a market_intent_id is added twice."""


class UnknownInvestorMarketIntentError(
    InvestorMarketIntentError, KeyError
):
    """Raised when a market_intent_id is not found."""


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


def _validate_label(
    value: str, allowed: frozenset[str], *, field_name: str
) -> None:
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {sorted(allowed)!r}; "
            f"got {value!r}"
        )


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InvestorMarketIntentRecord:
    """Immutable record naming one investor's market-facing
    interest / review posture toward a listed security at a point
    in time. Storage / audit object only — never an order, a
    trade, an allocation, a target weight, or a recommendation.

    Field semantics
    ---------------
    - ``market_intent_id`` is the stable id; unique within an
      ``InvestorMarketIntentBook``.
    - ``investor_id`` and ``security_id`` are plain-id
      cross-references; the book does not validate either
      against any other book per the v0/v1 cross-reference rule.
    - ``as_of_date`` is the required ISO date.
    - the four label fields take values from the closed sets
      defined as module-level frozensets.
    - ``confidence`` is a synthetic ``[0.0, 1.0]`` scalar.
      Booleans rejected. **Never** a calibrated probability of
      any external action.
    - ``visibility`` is a free-form generic visibility tag.
    - ``evidence_*_ids`` are tuples of plain-id cross-references.
    - ``metadata`` is free-form.
    """

    market_intent_id: str
    investor_id: str
    security_id: str
    as_of_date: str
    intent_direction_label: str
    intensity_label: str
    horizon_label: str
    status: str
    visibility: str
    confidence: float
    evidence_investor_intent_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_valuation_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_market_environment_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    evidence_firm_state_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_security_ids: tuple[str, ...] = field(default_factory=tuple)
    evidence_venue_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "market_intent_id",
        "investor_id",
        "security_id",
        "as_of_date",
        "intent_direction_label",
        "intensity_label",
        "horizon_label",
        "status",
        "visibility",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "evidence_investor_intent_ids",
        "evidence_valuation_ids",
        "evidence_market_environment_state_ids",
        "evidence_firm_state_ids",
        "evidence_security_ids",
        "evidence_venue_ids",
    )

    LABEL_FIELDS: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = (
        ("intent_direction_label", INTENT_DIRECTION_LABELS),
        ("intensity_label", INTENSITY_LABELS),
        ("horizon_label", HORIZON_LABELS),
        ("status", STATUS_LABELS),
    )

    def __post_init__(self) -> None:
        if isinstance(self.as_of_date, date):
            object.__setattr__(
                self, "as_of_date", _coerce_iso_date(self.as_of_date)
            )

        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required")

        for label_field, allowed in self.LABEL_FIELDS:
            _validate_label(
                getattr(self, label_field),
                allowed,
                field_name=label_field,
            )

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "confidence must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated "
                "probability of any external action)"
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
            "market_intent_id": self.market_intent_id,
            "investor_id": self.investor_id,
            "security_id": self.security_id,
            "as_of_date": self.as_of_date,
            "intent_direction_label": self.intent_direction_label,
            "intensity_label": self.intensity_label,
            "horizon_label": self.horizon_label,
            "status": self.status,
            "visibility": self.visibility,
            "confidence": self.confidence,
            "evidence_investor_intent_ids": list(
                self.evidence_investor_intent_ids
            ),
            "evidence_valuation_ids": list(self.evidence_valuation_ids),
            "evidence_market_environment_state_ids": list(
                self.evidence_market_environment_state_ids
            ),
            "evidence_firm_state_ids": list(self.evidence_firm_state_ids),
            "evidence_security_ids": list(self.evidence_security_ids),
            "evidence_venue_ids": list(self.evidence_venue_ids),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class InvestorMarketIntentBook:
    """Append-only storage for v1.15.2
    ``InvestorMarketIntentRecord`` instances. The book emits
    exactly one ledger record per ``add_intent`` call
    (``RecordType.INVESTOR_MARKET_INTENT_RECORDED``) and
    refuses to mutate any other source-of-truth book.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _intents: dict[str, InvestorMarketIntentRecord] = field(
        default_factory=dict
    )

    def add_intent(
        self, intent: InvestorMarketIntentRecord
    ) -> InvestorMarketIntentRecord:
        if intent.market_intent_id in self._intents:
            raise DuplicateInvestorMarketIntentError(
                f"Duplicate market_intent_id: {intent.market_intent_id}"
            )
        self._intents[intent.market_intent_id] = intent

        if self.ledger is not None:
            self.ledger.append(
                event_type="investor_market_intent_recorded",
                simulation_date=self._now(),
                object_id=intent.market_intent_id,
                source=intent.investor_id,
                target=intent.security_id,
                payload={
                    "market_intent_id": intent.market_intent_id,
                    "investor_id": intent.investor_id,
                    "security_id": intent.security_id,
                    "as_of_date": intent.as_of_date,
                    "intent_direction_label": intent.intent_direction_label,
                    "intensity_label": intent.intensity_label,
                    "horizon_label": intent.horizon_label,
                    "status": intent.status,
                    "visibility": intent.visibility,
                    "confidence": intent.confidence,
                    "evidence_investor_intent_ids": list(
                        intent.evidence_investor_intent_ids
                    ),
                    "evidence_valuation_ids": list(
                        intent.evidence_valuation_ids
                    ),
                    "evidence_market_environment_state_ids": list(
                        intent.evidence_market_environment_state_ids
                    ),
                    "evidence_firm_state_ids": list(
                        intent.evidence_firm_state_ids
                    ),
                    "evidence_security_ids": list(
                        intent.evidence_security_ids
                    ),
                    "evidence_venue_ids": list(intent.evidence_venue_ids),
                },
                space_id="investor_market_intents",
                visibility=intent.visibility,
                confidence=intent.confidence,
            )
        return intent

    def get_intent(
        self, market_intent_id: str
    ) -> InvestorMarketIntentRecord:
        try:
            return self._intents[market_intent_id]
        except KeyError as exc:
            raise UnknownInvestorMarketIntentError(
                f"Investor market intent not found: {market_intent_id!r}"
            ) from exc

    def list_intents(self) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(self._intents.values())

    def list_by_investor(
        self, investor_id: str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(
            i for i in self._intents.values() if i.investor_id == investor_id
        )

    def list_by_security(
        self, security_id: str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(
            i for i in self._intents.values() if i.security_id == security_id
        )

    def list_by_intent_direction(
        self, intent_direction_label: str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(
            i
            for i in self._intents.values()
            if i.intent_direction_label == intent_direction_label
        )

    def list_by_intensity(
        self, intensity_label: str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(
            i
            for i in self._intents.values()
            if i.intensity_label == intensity_label
        )

    def list_by_horizon(
        self, horizon_label: str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(
            i for i in self._intents.values() if i.horizon_label == horizon_label
        )

    def list_by_status(
        self, status: str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        return tuple(i for i in self._intents.values() if i.status == status)

    def list_by_date(
        self, as_of: date | str
    ) -> tuple[InvestorMarketIntentRecord, ...]:
        target = _coerce_iso_date(as_of)
        return tuple(
            i for i in self._intents.values() if i.as_of_date == target
        )

    def snapshot(self) -> dict[str, Any]:
        intents = sorted(
            (i.to_dict() for i in self._intents.values()),
            key=lambda item: item["market_intent_id"],
        )
        return {
            "intent_count": len(intents),
            "intents": intents,
        }

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
