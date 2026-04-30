from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


class RelationshipError(Exception):
    """Base class for relationship-capital layer errors."""


class DuplicateRelationshipError(RelationshipError):
    """Raised when a relationship_id is added twice."""


class UnknownRelationshipError(RelationshipError, KeyError):
    """Raised when a relationship_id is not found."""


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
class RelationshipRecord:
    """
    A non-contractual relationship between two world objects.

    A `RelationshipRecord` captures soft links — trust, reputation,
    historical support, advisory ties, main-bank-like ties, repeat
    counterparty effects — that contracts and ownership records cannot
    express. v1.5 stores them as data; it does not act on them.

    Field semantics
    ---------------
    - ``source_id`` and ``target_id`` are free-form WorldIDs. v1.5
      does not validate that they resolve to registered objects
      (same v0/v1 cross-reference rule).
    - ``relationship_type`` is a free-form string. Suggested labels:
      ``"main_bank"``, ``"advisory"``, ``"trust"``, ``"reputation"``,
      ``"historical_support"``, ``"information_access"``,
      ``"interlocking_directorate"``, ``"long_term_partnership"``.
      v1.5 enumerates none.
    - ``strength`` is a domain-specific numeric score. The book does
      not interpret its scale; consumers in later milestones may
      decide what "strong" or "weak" means for a given type.
    - ``direction`` is a free-form string. Suggested labels:
      ``"directed"`` (asymmetric, from source to target),
      ``"undirected"`` (symmetric), ``"reciprocal"`` (mutual but
      possibly with different strengths each way).
    - ``visibility`` is a free-form string. Suggested labels:
      ``"public"``, ``"private"``, ``"restricted"``, ``"inferred"``,
      ``"rumored"``. v1.5 stores the label but does not enforce
      visibility filtering — that is a consumer concern.
    - ``decay_rate`` is stored but **not automatically applied** in
      v1.5. A future milestone may introduce a decay engine; until
      then, callers that want decayed strength compute it themselves
      from ``strength``, ``decay_rate``, and the current date.
    - ``evidence_refs`` is a tuple of WorldIDs / record IDs that
      justify the relationship: signals, contracts, action records,
      valuations, observations, ledger record IDs. v1.5 does not
      validate them.
    """

    relationship_id: str
    source_id: str
    target_id: str
    relationship_type: str
    strength: float
    as_of_date: str
    direction: str = "directed"
    visibility: str = "public"
    decay_rate: float = 0.0
    confidence: float = 1.0
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.relationship_id:
            raise ValueError("relationship_id is required")
        if not self.source_id:
            raise ValueError("source_id is required")
        if not self.target_id:
            raise ValueError("target_id is required")
        if not self.relationship_type:
            raise ValueError("relationship_type is required")
        if not self.as_of_date:
            raise ValueError("as_of_date is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "as_of_date", _coerce_iso_date(self.as_of_date))
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def with_strength(
        self,
        new_strength: float,
        as_of_date: str | None = None,
    ) -> "RelationshipRecord":
        """Return a copy with an updated strength (and optionally as_of_date)."""
        return RelationshipRecord(
            relationship_id=self.relationship_id,
            source_id=self.source_id,
            target_id=self.target_id,
            relationship_type=self.relationship_type,
            strength=new_strength,
            as_of_date=as_of_date if as_of_date is not None else self.as_of_date,
            direction=self.direction,
            visibility=self.visibility,
            decay_rate=self.decay_rate,
            confidence=self.confidence,
            evidence_refs=self.evidence_refs,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship_id": self.relationship_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relationship_type": self.relationship_type,
            "strength": self.strength,
            "as_of_date": self.as_of_date,
            "direction": self.direction,
            "visibility": self.visibility,
            "decay_rate": self.decay_rate,
            "confidence": self.confidence,
            "evidence_refs": list(self.evidence_refs),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class RelationshipView:
    """
    Aggregated view of relationships between two specific world objects.

    A `RelationshipView` is a *projection*: rebuilt every time it is
    requested, never canonical state. It exists so that consumers
    (future v1.5+ behavior modules) can ask "what's the soft link
    between A and B?" without joining the relationship records
    themselves.

    The view's ``total_strength`` is the simple sum of strengths
    across the matched relationships. v1.5 does **not**:

    - apply ``decay_rate`` to the strengths before summing
    - normalize across types
    - weight by confidence
    - deduplicate across direction
    - filter by visibility (the caller decides what's visible to whom)

    These are interpretation concerns. v1.5 only sums what's there.
    """

    subject_id: str
    counterparty_id: str
    relationship_types: tuple[str, ...]
    total_strength: float
    visible_relationship_ids: tuple[str, ...]
    as_of_date: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "relationship_types", tuple(self.relationship_types))
        object.__setattr__(
            self, "visible_relationship_ids", tuple(self.visible_relationship_ids)
        )
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "counterparty_id": self.counterparty_id,
            "relationship_types": list(self.relationship_types),
            "total_strength": self.total_strength,
            "visible_relationship_ids": list(self.visible_relationship_ids),
            "as_of_date": self.as_of_date,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# RelationshipCapitalBook
# ---------------------------------------------------------------------------


@dataclass
class RelationshipCapitalBook:
    """
    Storage for non-contractual relationships.

    Like every other v0 / v1 book, this one is append-only at the id
    level (a relationship_id is unique once added), emits ledger
    records on mutation, and refuses to mutate any other source-of-
    truth book. The single exception to "append-only" is
    ``update_strength``, which replaces the record under a given
    relationship_id with a new one carrying the updated strength —
    matching the existing pattern from `ContractBook.update_status`.
    The audit trail of every strength change lives in the ledger.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _relationships: dict[str, RelationshipRecord] = field(default_factory=dict)
    _by_source: dict[str, list[str]] = field(default_factory=dict)
    _by_target: dict[str, list[str]] = field(default_factory=dict)
    _by_type: dict[str, list[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_relationship(
        self, record: RelationshipRecord
    ) -> RelationshipRecord:
        if record.relationship_id in self._relationships:
            raise DuplicateRelationshipError(
                f"Duplicate relationship_id: {record.relationship_id}"
            )
        self._relationships[record.relationship_id] = record
        self._by_source.setdefault(record.source_id, []).append(
            record.relationship_id
        )
        self._by_target.setdefault(record.target_id, []).append(
            record.relationship_id
        )
        self._by_type.setdefault(record.relationship_type, []).append(
            record.relationship_id
        )

        if self.ledger is not None:
            self.ledger.append(
                event_type="relationship_added",
                simulation_date=self._now(),
                object_id=record.relationship_id,
                source=record.source_id,
                target=record.target_id,
                payload={
                    "relationship_id": record.relationship_id,
                    "source_id": record.source_id,
                    "target_id": record.target_id,
                    "relationship_type": record.relationship_type,
                    "strength": record.strength,
                    "direction": record.direction,
                    "visibility": record.visibility,
                    "decay_rate": record.decay_rate,
                    "as_of_date": record.as_of_date,
                    "evidence_refs": list(record.evidence_refs),
                },
                space_id="relationships",
                visibility=record.visibility,
                confidence=record.confidence,
            )
        return record

    def get_relationship(self, relationship_id: str) -> RelationshipRecord:
        try:
            return self._relationships[relationship_id]
        except KeyError as exc:
            raise UnknownRelationshipError(
                f"Relationship not found: {relationship_id!r}"
            ) from exc

    def list_by_source(
        self, source_id: str
    ) -> tuple[RelationshipRecord, ...]:
        ids = self._by_source.get(source_id, [])
        return tuple(self._relationships[rid] for rid in ids)

    def list_by_target(
        self, target_id: str
    ) -> tuple[RelationshipRecord, ...]:
        ids = self._by_target.get(target_id, [])
        return tuple(self._relationships[rid] for rid in ids)

    def list_by_type(
        self, relationship_type: str
    ) -> tuple[RelationshipRecord, ...]:
        ids = self._by_type.get(relationship_type, [])
        return tuple(self._relationships[rid] for rid in ids)

    def list_between(
        self,
        source_id: str,
        target_id: str,
    ) -> tuple[RelationshipRecord, ...]:
        """
        Return relationships whose ``source_id`` and ``target_id``
        match the arguments exactly. The lookup is directional: to
        get both (A → B) and (B → A) relationships, call this twice.
        Filtering by direction (``"directed"`` vs ``"undirected"``)
        is the caller's choice.
        """
        ids = self._by_source.get(source_id, [])
        return tuple(
            self._relationships[rid]
            for rid in ids
            if self._relationships[rid].target_id == target_id
        )

    def update_strength(
        self,
        relationship_id: str,
        new_strength: float,
        as_of_date: date | str | None = None,
        reason: str | None = None,
    ) -> RelationshipRecord:
        """
        Replace the relationship's record with one carrying the new
        strength. The previous strength and the supplied reason are
        recorded to the ledger so the history is reconstructable
        without keeping every prior record live.
        """
        existing = self.get_relationship(relationship_id)
        previous_strength = existing.strength

        new_as_of: str | None
        if as_of_date is None:
            new_as_of = None  # keep existing
        else:
            new_as_of = _coerce_iso_date(as_of_date)

        updated = existing.with_strength(new_strength, as_of_date=new_as_of)
        self._relationships[relationship_id] = updated

        if self.ledger is not None:
            self.ledger.append(
                event_type="relationship_strength_updated",
                simulation_date=self._now(),
                object_id=relationship_id,
                source=existing.source_id,
                target=existing.target_id,
                payload={
                    "relationship_id": relationship_id,
                    "previous_strength": previous_strength,
                    "new_strength": new_strength,
                    "as_of_date": updated.as_of_date,
                    "reason": reason,
                },
                space_id="relationships",
                visibility=existing.visibility,
                confidence=existing.confidence,
            )
        return updated

    def all_relationships(self) -> tuple[RelationshipRecord, ...]:
        return tuple(self._relationships.values())

    # ------------------------------------------------------------------
    # Derived view
    # ------------------------------------------------------------------

    def build_relationship_view(
        self,
        subject_id: str,
        counterparty_id: str,
    ) -> RelationshipView:
        """
        Build a `RelationshipView` aggregating relationships from
        ``subject_id`` toward ``counterparty_id``.

        Direction handling:
        - All ``source=subject_id, target=counterparty_id`` records
          are included regardless of direction value.
        - Records in the reverse direction (``source=counterparty_id,
          target=subject_id``) are included **only** when their
          ``direction`` is ``"undirected"`` or ``"reciprocal"`` —
          those go both ways by definition. ``"directed"`` records
          in the reverse direction are not included; they describe
          the counterparty's view of the subject, not the subject's
          view of the counterparty.

        ``total_strength`` is the simple sum of strengths over the
        included records. v1.5 applies no decay, no normalization,
        no confidence weighting. ``as_of_date`` on the view is the
        kernel clock's current date when available, else an empty
        string.
        """
        forward = list(self.list_between(subject_id, counterparty_id))
        reverse = [
            rec
            for rec in self.list_between(counterparty_id, subject_id)
            if rec.direction in ("undirected", "reciprocal")
        ]
        included = forward + reverse

        types = tuple(sorted({rec.relationship_type for rec in included}))
        ids = tuple(sorted(rec.relationship_id for rec in included))
        total = sum(rec.strength for rec in included)

        as_of = ""
        if self.clock is not None and self.clock.current_date is not None:
            as_of = self.clock.current_date.isoformat()

        return RelationshipView(
            subject_id=subject_id,
            counterparty_id=counterparty_id,
            relationship_types=types,
            total_strength=total,
            visible_relationship_ids=ids,
            as_of_date=as_of,
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        relationships = sorted(
            (r.to_dict() for r in self._relationships.values()),
            key=lambda item: item["relationship_id"],
        )
        return {"count": len(relationships), "relationships": relationships}

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
