"""
v1.15.3 AggregatedMarketInterestRecord +
AggregatedMarketInterestBook +
``build_aggregated_market_interest`` helper.

Append-only **label-based** synthetic record summarising one
venue's set of cited :class:`InvestorMarketIntentRecord`
instances for one security at one date.

This is **market interest aggregation**, **not** an order
book, **not** order imbalance, **not** price formation, **not**
trade execution, **not** quote dissemination, **not** clearing,
**not** settlement. The record is a count + label readout
over non-binding investor review postures; it never carries an
order, a trade, a quote, a price, or a recommendation.

The record carries:

- seven non-negative integer **counts** that bucket the cited
  market intents by ``intent_direction_label``:
    - ``increased_interest_count``        (``increase_interest``)
    - ``reduced_interest_count``          (``reduce_interest``)
    - ``neutral_or_hold_review_count``    (``hold_review`` +
      ``rebalance_review`` + ``unknown``)
    - ``liquidity_watch_count``           (``liquidity_watch``)
    - ``risk_reduction_review_count``     (``risk_reduction_review``)
    - ``engagement_linked_review_count``  (``engagement_linked_review``)
    - ``total_intent_count`` — sum of the six bucket counts
- three small closed-set summary labels:
    - ``net_interest_label``       — net direction
    - ``liquidity_interest_label`` — liquidity-attention level
    - ``concentration_label``      — bucket dispersion
- one closed-set lifecycle label: ``status``
- a synthetic ``confidence`` ordering in ``[0.0, 1.0]``
- two plain-id source tuples:
    - ``source_market_intent_ids`` (the per-investor records this
      aggregation read; a v1.15.2 cross-reference)
    - ``source_market_environment_state_ids`` (v1.12.2)
- ``visibility``, ``metadata``.

Cross-references are stored as data and not validated against
any other book per the v0/v1 cross-reference rule.

The record carries **no** ``buy``, ``sell``, ``order``,
``order_id``, ``trade``, ``trade_id``, ``execution``, ``bid``,
``ask``, ``quote``, ``clearing``, ``settlement``, ``price``,
``order_imbalance``, ``target_price``, ``expected_return``,
``recommendation``, ``investment_advice``, or
``real_data_value`` field. Tests pin the absence on both the
dataclass field set and the ledger payload key set.

The book emits exactly one ledger record per ``add_record``
call (``RecordType.AGGREGATED_MARKET_INTEREST_RECORDED``) with
``source = venue_id`` and ``target = security_id`` so the
ledger graph reads as 'venue V aggregated market interest for
security S'. The book mutates no other source-of-truth book.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Closed-set label vocabularies
# ---------------------------------------------------------------------------


NET_INTEREST_LABELS: frozenset[str] = frozenset(
    {
        "increased_interest",
        "reduced_interest",
        "balanced",
        "mixed",
        "insufficient_observations",
        "unknown",
    }
)

LIQUIDITY_INTEREST_LABELS: frozenset[str] = frozenset(
    {
        "liquidity_attention_low",
        "liquidity_attention_moderate",
        "liquidity_attention_high",
        "unknown",
    }
)

CONCENTRATION_LABELS: frozenset[str] = frozenset(
    {
        "dispersed",
        "moderately_concentrated",
        "concentrated",
        "insufficient_observations",
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


class AggregatedMarketInterestError(Exception):
    """Base class for v1.15.3 aggregated-market-interest errors."""


class DuplicateAggregatedMarketInterestError(AggregatedMarketInterestError):
    """Raised when an aggregated_interest_id is added twice."""


class UnknownAggregatedMarketInterestError(
    AggregatedMarketInterestError, KeyError
):
    """Raised when an aggregated_interest_id is not found."""


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


def _validate_count(value: Any, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be a non-negative int")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative; got {value!r}")


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AggregatedMarketInterestRecord:
    """Immutable record summarising one venue's aggregation of
    investor market intents for one security at one date.

    Field semantics
    ---------------
    - ``aggregated_interest_id`` is the stable id; unique within
      an ``AggregatedMarketInterestBook``.
    - ``venue_id`` and ``security_id`` are plain-id cross-
      references; the book does not validate either against any
      other book per the v0/v1 cross-reference rule.
    - ``as_of_date`` is the required ISO date.
    - the seven count fields are non-negative integers; booleans
      are rejected.
    - the four label fields take values from the closed sets
      defined as module-level frozensets.
    - ``confidence`` is a synthetic ``[0.0, 1.0]`` scalar
      (booleans rejected) — never a calibrated probability of
      any external action.
    - ``visibility`` is a free-form generic visibility tag.
    - ``source_*_ids`` are tuples of plain-id cross-references.
    - ``metadata`` is free-form.
    """

    aggregated_interest_id: str
    venue_id: str
    security_id: str
    as_of_date: str
    increased_interest_count: int
    reduced_interest_count: int
    neutral_or_hold_review_count: int
    liquidity_watch_count: int
    risk_reduction_review_count: int
    engagement_linked_review_count: int
    total_intent_count: int
    net_interest_label: str
    liquidity_interest_label: str
    concentration_label: str
    status: str
    visibility: str
    confidence: float
    source_market_intent_ids: tuple[str, ...] = field(default_factory=tuple)
    source_market_environment_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "aggregated_interest_id",
        "venue_id",
        "security_id",
        "as_of_date",
        "net_interest_label",
        "liquidity_interest_label",
        "concentration_label",
        "status",
        "visibility",
    )

    COUNT_FIELDS: ClassVar[tuple[str, ...]] = (
        "increased_interest_count",
        "reduced_interest_count",
        "neutral_or_hold_review_count",
        "liquidity_watch_count",
        "risk_reduction_review_count",
        "engagement_linked_review_count",
        "total_intent_count",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "source_market_intent_ids",
        "source_market_environment_state_ids",
    )

    LABEL_FIELDS: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = (
        ("net_interest_label", NET_INTEREST_LABELS),
        ("liquidity_interest_label", LIQUIDITY_INTEREST_LABELS),
        ("concentration_label", CONCENTRATION_LABELS),
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

        for name in self.COUNT_FIELDS:
            _validate_count(getattr(self, name), field_name=name)

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
            "aggregated_interest_id": self.aggregated_interest_id,
            "venue_id": self.venue_id,
            "security_id": self.security_id,
            "as_of_date": self.as_of_date,
            "increased_interest_count": self.increased_interest_count,
            "reduced_interest_count": self.reduced_interest_count,
            "neutral_or_hold_review_count": self.neutral_or_hold_review_count,
            "liquidity_watch_count": self.liquidity_watch_count,
            "risk_reduction_review_count": self.risk_reduction_review_count,
            "engagement_linked_review_count": (
                self.engagement_linked_review_count
            ),
            "total_intent_count": self.total_intent_count,
            "net_interest_label": self.net_interest_label,
            "liquidity_interest_label": self.liquidity_interest_label,
            "concentration_label": self.concentration_label,
            "status": self.status,
            "visibility": self.visibility,
            "confidence": self.confidence,
            "source_market_intent_ids": list(self.source_market_intent_ids),
            "source_market_environment_state_ids": list(
                self.source_market_environment_state_ids
            ),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class AggregatedMarketInterestBook:
    """Append-only storage for v1.15.3
    ``AggregatedMarketInterestRecord`` instances. The book emits
    exactly one ledger record per ``add_record`` call
    (``RecordType.AGGREGATED_MARKET_INTEREST_RECORDED``) with
    ``source = venue_id`` and ``target = security_id``; the book
    mutates no other source-of-truth book.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _records: dict[str, AggregatedMarketInterestRecord] = field(
        default_factory=dict
    )

    def add_record(
        self, record: AggregatedMarketInterestRecord
    ) -> AggregatedMarketInterestRecord:
        if record.aggregated_interest_id in self._records:
            raise DuplicateAggregatedMarketInterestError(
                f"Duplicate aggregated_interest_id: "
                f"{record.aggregated_interest_id}"
            )
        self._records[record.aggregated_interest_id] = record

        if self.ledger is not None:
            self.ledger.append(
                event_type="aggregated_market_interest_recorded",
                simulation_date=self._now(),
                object_id=record.aggregated_interest_id,
                source=record.venue_id,
                target=record.security_id,
                payload={
                    "aggregated_interest_id": record.aggregated_interest_id,
                    "venue_id": record.venue_id,
                    "security_id": record.security_id,
                    "as_of_date": record.as_of_date,
                    "increased_interest_count": (
                        record.increased_interest_count
                    ),
                    "reduced_interest_count": record.reduced_interest_count,
                    "neutral_or_hold_review_count": (
                        record.neutral_or_hold_review_count
                    ),
                    "liquidity_watch_count": record.liquidity_watch_count,
                    "risk_reduction_review_count": (
                        record.risk_reduction_review_count
                    ),
                    "engagement_linked_review_count": (
                        record.engagement_linked_review_count
                    ),
                    "total_intent_count": record.total_intent_count,
                    "net_interest_label": record.net_interest_label,
                    "liquidity_interest_label": (
                        record.liquidity_interest_label
                    ),
                    "concentration_label": record.concentration_label,
                    "status": record.status,
                    "visibility": record.visibility,
                    "confidence": record.confidence,
                    "source_market_intent_ids": list(
                        record.source_market_intent_ids
                    ),
                    "source_market_environment_state_ids": list(
                        record.source_market_environment_state_ids
                    ),
                },
                space_id="aggregated_market_interest",
                visibility=record.visibility,
                confidence=record.confidence,
            )
        return record

    def get_record(
        self, aggregated_interest_id: str
    ) -> AggregatedMarketInterestRecord:
        try:
            return self._records[aggregated_interest_id]
        except KeyError as exc:
            raise UnknownAggregatedMarketInterestError(
                f"Aggregated market interest record not found: "
                f"{aggregated_interest_id!r}"
            ) from exc

    def list_records(self) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(self._records.values())

    def list_by_venue(
        self, venue_id: str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(
            r for r in self._records.values() if r.venue_id == venue_id
        )

    def list_by_security(
        self, security_id: str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(
            r for r in self._records.values() if r.security_id == security_id
        )

    def list_by_date(
        self, as_of: date | str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        target = _coerce_iso_date(as_of)
        return tuple(
            r for r in self._records.values() if r.as_of_date == target
        )

    def list_by_net_interest(
        self, net_interest_label: str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(
            r
            for r in self._records.values()
            if r.net_interest_label == net_interest_label
        )

    def list_by_liquidity_interest(
        self, liquidity_interest_label: str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(
            r
            for r in self._records.values()
            if r.liquidity_interest_label == liquidity_interest_label
        )

    def list_by_status(
        self, status: str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(r for r in self._records.values() if r.status == status)

    def list_by_source_market_intent(
        self, market_intent_id: str
    ) -> tuple[AggregatedMarketInterestRecord, ...]:
        return tuple(
            r
            for r in self._records.values()
            if market_intent_id in r.source_market_intent_ids
        )

    def snapshot(self) -> dict[str, Any]:
        records = sorted(
            (r.to_dict() for r in self._records.values()),
            key=lambda item: item["aggregated_interest_id"],
        )
        return {
            "record_count": len(records),
            "records": records,
        }

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()


# ---------------------------------------------------------------------------
# Deterministic builder
#
# The helper resolves only the explicitly cited ids by calling
# ``kernel.investor_market_intents.get_intent(id)``. It never
# scans the book globally (no ``list_*`` calls). Any cited id
# that fails to resolve is recorded in metadata under
# ``unresolved_market_intent_count`` and skipped during
# bucket / label derivation. Any resolved intent whose
# ``security_id`` does not match the helper's ``security_id`` is
# ignored and recorded in metadata under
# ``mismatched_security_id_count`` (the design choice — keep the
# count surface clean by recording the mismatch in metadata
# rather than introducing a separate count field).
# ---------------------------------------------------------------------------


# Mapping from intent direction labels to count field names. The
# ``rebalance_review`` and ``unknown`` labels fall into the
# ``neutral_or_hold_review_count`` bucket per the v1.15.3
# helper-rule documentation.
_DIRECTION_TO_COUNT_FIELD: Mapping[str, str] = {
    "increase_interest": "increased_interest_count",
    "reduce_interest": "reduced_interest_count",
    "hold_review": "neutral_or_hold_review_count",
    "rebalance_review": "neutral_or_hold_review_count",
    "liquidity_watch": "liquidity_watch_count",
    "risk_reduction_review": "risk_reduction_review_count",
    "engagement_linked_review": "engagement_linked_review_count",
    "unknown": "neutral_or_hold_review_count",
}


def _derive_net_interest_label(
    *,
    total: int,
    increased: int,
    reduced: int,
    neutral: int,
) -> str:
    """Deterministic v1.15.3 ``net_interest_label`` rule.

    - ``total == 0`` → ``insufficient_observations``
    - ``increased > reduced`` and ``increased >= neutral`` →
      ``increased_interest``
    - ``reduced > increased`` and ``reduced >= neutral`` →
      ``reduced_interest``
    - both ``increased`` and ``reduced`` non-zero and within 1 of
      each other → ``mixed``
    - otherwise → ``balanced``
    """
    if total == 0:
        return "insufficient_observations"
    if increased > reduced and increased >= neutral:
        return "increased_interest"
    if reduced > increased and reduced >= neutral:
        return "reduced_interest"
    if increased > 0 and reduced > 0 and abs(increased - reduced) <= 1:
        return "mixed"
    return "balanced"


def _derive_liquidity_interest_label(
    *,
    total: int,
    liquidity_watch_count: int,
) -> str:
    """Deterministic v1.15.3 ``liquidity_interest_label`` rule.

    - ``total == 0`` → ``unknown``
    - ``liquidity_watch_count == 0`` → ``liquidity_attention_low``
    - liquidity ratio ``< 0.5`` → ``liquidity_attention_moderate``
    - otherwise → ``liquidity_attention_high``
    """
    if total == 0:
        return "unknown"
    if liquidity_watch_count == 0:
        return "liquidity_attention_low"
    if liquidity_watch_count * 2 < total:
        return "liquidity_attention_moderate"
    return "liquidity_attention_high"


def _derive_concentration_label(
    *,
    total: int,
    counts: Mapping[str, int],
) -> str:
    """Deterministic v1.15.3 ``concentration_label`` rule.

    - ``total < 2`` → ``insufficient_observations``
    - exactly one bucket has any non-zero count → ``concentrated``
    - 2 or 3 buckets have non-zero counts → ``moderately_concentrated``
    - 4+ buckets have non-zero counts → ``dispersed``

    ``counts`` is the mapping of count-field names to values
    excluding ``total_intent_count``.
    """
    if total < 2:
        return "insufficient_observations"
    occupied_buckets = sum(1 for v in counts.values() if v > 0)
    if occupied_buckets <= 1:
        return "concentrated"
    if occupied_buckets <= 3:
        return "moderately_concentrated"
    return "dispersed"


def build_aggregated_market_interest(
    kernel: Any,
    *,
    venue_id: str,
    security_id: str,
    as_of_date: date | str,
    source_market_intent_ids: Iterable[str] = (),
    source_market_environment_state_ids: Iterable[str] = (),
    aggregated_interest_id: str | None = None,
    confidence: float = 0.5,
    status: str = "active",
    visibility: str = "internal_only",
    metadata: Mapping[str, Any] | None = None,
) -> AggregatedMarketInterestRecord:
    """Synthesise one ``AggregatedMarketInterestRecord`` from a
    set of cited ``InvestorMarketIntentRecord`` ids and add it
    to ``kernel.aggregated_market_interest``.

    The helper is a deterministic pure-count synthesiser:

    - Reads only the cited ids via
      ``kernel.investor_market_intents.get_intent``. Never calls
      ``list_intents`` or any other globally-scanning method.
    - Counts only intents whose ``security_id`` matches the
      helper's ``security_id``. Mismatched intents are ignored
      and the count is recorded in metadata under
      ``mismatched_security_id_count``.
    - Unresolved ids are ignored and the count is recorded in
      metadata under ``unresolved_market_intent_count``.
    - Bucket mapping per the module docstring: every cited
      ``intent_direction_label`` falls into exactly one count
      bucket.
    - Derives ``net_interest_label`` /
      ``liquidity_interest_label`` / ``concentration_label`` via
      the small deterministic rules in
      :func:`_derive_net_interest_label`,
      :func:`_derive_liquidity_interest_label`, and
      :func:`_derive_concentration_label`.
    - Sets ``status = "active"`` by default at synthesis time.

    The helper does **not** infer orders, trades, prices,
    quotes, or order imbalance.
    """

    intent_ids_t = tuple(source_market_intent_ids)
    mes_ids_t = tuple(source_market_environment_state_ids)

    counts: dict[str, int] = {
        "increased_interest_count": 0,
        "reduced_interest_count": 0,
        "neutral_or_hold_review_count": 0,
        "liquidity_watch_count": 0,
        "risk_reduction_review_count": 0,
        "engagement_linked_review_count": 0,
    }
    mismatched_security_id_count = 0
    unresolved_market_intent_count = 0

    book = getattr(kernel, "investor_market_intents", None)
    for iid in intent_ids_t:
        if book is None:
            unresolved_market_intent_count += 1
            continue
        try:
            intent = book.get_intent(iid)
        except Exception:
            unresolved_market_intent_count += 1
            continue
        if intent.security_id != security_id:
            mismatched_security_id_count += 1
            continue
        bucket_field = _DIRECTION_TO_COUNT_FIELD.get(
            intent.intent_direction_label,
            "neutral_or_hold_review_count",
        )
        counts[bucket_field] += 1

    total = sum(counts.values())

    net_interest = _derive_net_interest_label(
        total=total,
        increased=counts["increased_interest_count"],
        reduced=counts["reduced_interest_count"],
        neutral=counts["neutral_or_hold_review_count"],
    )
    liquidity_interest = _derive_liquidity_interest_label(
        total=total,
        liquidity_watch_count=counts["liquidity_watch_count"],
    )
    concentration = _derive_concentration_label(
        total=total,
        counts=counts,
    )

    final_metadata: dict[str, Any] = dict(metadata) if metadata else {}
    final_metadata["mismatched_security_id_count"] = (
        mismatched_security_id_count
    )
    final_metadata["unresolved_market_intent_count"] = (
        unresolved_market_intent_count
    )

    if aggregated_interest_id is None:
        as_iso = _coerce_iso_date(as_of_date)
        aggregated_interest_id = (
            f"aggregated_market_interest:{venue_id}:{security_id}:{as_iso}"
        )

    record = AggregatedMarketInterestRecord(
        aggregated_interest_id=aggregated_interest_id,
        venue_id=venue_id,
        security_id=security_id,
        as_of_date=as_of_date,
        increased_interest_count=counts["increased_interest_count"],
        reduced_interest_count=counts["reduced_interest_count"],
        neutral_or_hold_review_count=counts["neutral_or_hold_review_count"],
        liquidity_watch_count=counts["liquidity_watch_count"],
        risk_reduction_review_count=counts["risk_reduction_review_count"],
        engagement_linked_review_count=counts["engagement_linked_review_count"],
        total_intent_count=total,
        net_interest_label=net_interest,
        liquidity_interest_label=liquidity_interest,
        concentration_label=concentration,
        status=status,
        visibility=visibility,
        confidence=confidence,
        source_market_intent_ids=intent_ids_t,
        source_market_environment_state_ids=mes_ids_t,
        metadata=final_metadata,
    )
    return kernel.aggregated_market_interest.add_record(record)
