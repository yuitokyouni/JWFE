from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.relationships import (
    DuplicateRelationshipError,
    RelationshipCapitalBook,
    RelationshipRecord,
    RelationshipView,
    UnknownRelationshipError,
)
from world.scheduler import Scheduler
from world.state import State


def _relationship(
    relationship_id: str = "relationship:001",
    *,
    source_id: str = "agent:firm_x",
    target_id: str = "agent:bank_a",
    relationship_type: str = "main_bank",
    strength: float = 0.7,
    as_of_date: str = "2026-01-01",
    direction: str = "directed",
    visibility: str = "public",
    decay_rate: float = 0.0,
    confidence: float = 1.0,
    evidence_refs: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> RelationshipRecord:
    return RelationshipRecord(
        relationship_id=relationship_id,
        source_id=source_id,
        target_id=target_id,
        relationship_type=relationship_type,
        strength=strength,
        as_of_date=as_of_date,
        direction=direction,
        visibility=visibility,
        decay_rate=decay_rate,
        confidence=confidence,
        evidence_refs=evidence_refs,
        metadata=metadata or {},
    )


def _book(with_ledger: bool = False) -> RelationshipCapitalBook:
    if with_ledger:
        return RelationshipCapitalBook(
            ledger=Ledger(),
            clock=Clock(current_date=date(2026, 1, 1)),
        )
    return RelationshipCapitalBook()


# ---------------------------------------------------------------------------
# RelationshipRecord dataclass
# ---------------------------------------------------------------------------


def test_relationship_record_carries_required_fields():
    r = _relationship()
    assert r.relationship_id == "relationship:001"
    assert r.source_id == "agent:firm_x"
    assert r.target_id == "agent:bank_a"
    assert r.relationship_type == "main_bank"
    assert r.strength == 0.7
    assert r.direction == "directed"
    assert r.visibility == "public"


def test_relationship_record_rejects_missing_required():
    with pytest.raises(ValueError):
        _relationship(relationship_id="")
    with pytest.raises(ValueError):
        _relationship(source_id="")
    with pytest.raises(ValueError):
        _relationship(target_id="")
    with pytest.raises(ValueError):
        _relationship(relationship_type="")
    with pytest.raises(ValueError):
        _relationship(as_of_date="")


def test_relationship_record_rejects_invalid_confidence():
    with pytest.raises(ValueError):
        _relationship(confidence=1.5)
    with pytest.raises(ValueError):
        _relationship(confidence=-0.1)


def test_relationship_record_is_immutable():
    r = _relationship()
    with pytest.raises(Exception):
        r.strength = 0.9  # type: ignore[misc]


def test_relationship_record_to_dict_is_serializable():
    r = _relationship(
        decay_rate=0.05,
        evidence_refs=("contract:loan_001", "signal:rating_a"),
    )
    payload = r.to_dict()
    assert payload["decay_rate"] == 0.05
    assert payload["evidence_refs"] == ["contract:loan_001", "signal:rating_a"]


def test_relationship_with_strength_returns_new_record():
    r = _relationship(strength=0.5, as_of_date="2026-01-01")
    updated = r.with_strength(0.8, as_of_date="2026-06-01")
    # Original unchanged.
    assert r.strength == 0.5
    assert r.as_of_date == "2026-01-01"
    # Updated copy reflects the change.
    assert updated.strength == 0.8
    assert updated.as_of_date == "2026-06-01"
    # Other fields preserved.
    assert updated.source_id == r.source_id
    assert updated.relationship_type == r.relationship_type


# ---------------------------------------------------------------------------
# RelationshipCapitalBook — CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_relationship():
    book = _book()
    r = _relationship()
    book.add_relationship(r)
    assert book.get_relationship("relationship:001") is r


def test_get_relationship_raises_for_unknown():
    book = _book()
    with pytest.raises(UnknownRelationshipError):
        book.get_relationship("relationship:nope")


def test_duplicate_relationship_id_rejected():
    book = _book()
    book.add_relationship(_relationship())
    with pytest.raises(DuplicateRelationshipError):
        book.add_relationship(_relationship())


def test_list_by_source_filters_correctly():
    book = _book()
    book.add_relationship(
        _relationship(relationship_id="r:1", source_id="agent:a", target_id="agent:x")
    )
    book.add_relationship(
        _relationship(relationship_id="r:2", source_id="agent:a", target_id="agent:y")
    )
    book.add_relationship(
        _relationship(relationship_id="r:3", source_id="agent:b", target_id="agent:x")
    )

    from_a = book.list_by_source("agent:a")
    from_b = book.list_by_source("agent:b")

    assert {r.relationship_id for r in from_a} == {"r:1", "r:2"}
    assert {r.relationship_id for r in from_b} == {"r:3"}


def test_list_by_target_filters_correctly():
    book = _book()
    book.add_relationship(
        _relationship(relationship_id="r:1", source_id="agent:a", target_id="agent:x")
    )
    book.add_relationship(
        _relationship(relationship_id="r:2", source_id="agent:b", target_id="agent:x")
    )
    book.add_relationship(
        _relationship(relationship_id="r:3", source_id="agent:a", target_id="agent:y")
    )

    to_x = book.list_by_target("agent:x")
    to_y = book.list_by_target("agent:y")

    assert {r.relationship_id for r in to_x} == {"r:1", "r:2"}
    assert {r.relationship_id for r in to_y} == {"r:3"}


def test_list_by_type_filters_correctly():
    book = _book()
    book.add_relationship(
        _relationship(relationship_id="r:1", relationship_type="main_bank")
    )
    book.add_relationship(
        _relationship(relationship_id="r:2", relationship_type="advisory")
    )
    book.add_relationship(
        _relationship(relationship_id="r:3", relationship_type="main_bank")
    )

    main_bank = book.list_by_type("main_bank")
    advisory = book.list_by_type("advisory")

    assert {r.relationship_id for r in main_bank} == {"r:1", "r:3"}
    assert {r.relationship_id for r in advisory} == {"r:2"}


def test_list_between_returns_directional_matches_only():
    book = _book()
    book.add_relationship(
        _relationship(
            relationship_id="r:forward",
            source_id="agent:a",
            target_id="agent:b",
        )
    )
    book.add_relationship(
        _relationship(
            relationship_id="r:reverse",
            source_id="agent:b",
            target_id="agent:a",
        )
    )

    forward = book.list_between("agent:a", "agent:b")
    reverse = book.list_between("agent:b", "agent:a")

    # list_between is directional: A→B returns the forward record only.
    assert {r.relationship_id for r in forward} == {"r:forward"}
    assert {r.relationship_id for r in reverse} == {"r:reverse"}


# ---------------------------------------------------------------------------
# update_strength
# ---------------------------------------------------------------------------


def test_update_strength_replaces_record_in_place():
    book = _book()
    book.add_relationship(_relationship(strength=0.5))

    updated = book.update_strength(
        "relationship:001",
        new_strength=0.9,
        as_of_date="2026-06-01",
        reason="reference_test_update",
    )
    assert updated.strength == 0.9
    assert updated.as_of_date == "2026-06-01"

    # Subsequent get returns the updated record.
    fetched = book.get_relationship("relationship:001")
    assert fetched.strength == 0.9


def test_update_strength_preserves_other_fields():
    book = _book()
    book.add_relationship(
        _relationship(
            relationship_type="main_bank",
            direction="directed",
            visibility="public",
            decay_rate=0.05,
            confidence=0.8,
            evidence_refs=("contract:loan_001",),
            metadata={"note": "reference"},
        )
    )

    updated = book.update_strength("relationship:001", new_strength=0.4)
    assert updated.relationship_type == "main_bank"
    assert updated.direction == "directed"
    assert updated.visibility == "public"
    assert updated.decay_rate == 0.05
    assert updated.confidence == 0.8
    assert updated.evidence_refs == ("contract:loan_001",)
    assert updated.metadata == {"note": "reference"}


def test_update_strength_keeps_as_of_date_when_not_provided():
    book = _book()
    book.add_relationship(_relationship(strength=0.5, as_of_date="2026-01-01"))
    updated = book.update_strength("relationship:001", new_strength=0.6)
    assert updated.as_of_date == "2026-01-01"


def test_update_strength_raises_for_unknown_relationship():
    book = _book()
    with pytest.raises(UnknownRelationshipError):
        book.update_strength("relationship:nope", new_strength=0.5)


def test_update_strength_records_to_ledger_with_reason():
    book = _book(with_ledger=True)
    book.add_relationship(_relationship(strength=0.5))
    book.update_strength(
        "relationship:001",
        new_strength=0.9,
        reason="reference_test_update",
    )

    records = book.ledger.filter(event_type="relationship_strength_updated")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "relationship:001"
    assert record.payload["previous_strength"] == 0.5
    assert record.payload["new_strength"] == 0.9
    assert record.payload["reason"] == "reference_test_update"


# ---------------------------------------------------------------------------
# Evidence refs and decay storage
# ---------------------------------------------------------------------------


def test_evidence_refs_preserved_on_add_and_get():
    book = _book()
    book.add_relationship(
        _relationship(
            evidence_refs=(
                "contract:loan_001",
                "signal:rating_a",
                "action:announcement_001",
                "valuation:underwriting_001",
            )
        )
    )
    fetched = book.get_relationship("relationship:001")
    assert fetched.evidence_refs == (
        "contract:loan_001",
        "signal:rating_a",
        "action:announcement_001",
        "valuation:underwriting_001",
    )


def test_decay_rate_stored_but_not_applied():
    """
    v1.5 stores decay_rate verbatim. It does NOT auto-decay strength
    when the record is read at a later date — that is a future
    milestone's concern.
    """
    book = _book()
    book.add_relationship(
        _relationship(
            strength=1.0,
            as_of_date="2026-01-01",
            decay_rate=0.99,  # would decay to ~0 if applied
        )
    )
    # Even after a long simulated gap, the stored strength is unchanged.
    fetched = book.get_relationship("relationship:001")
    assert fetched.strength == 1.0
    assert fetched.decay_rate == 0.99


# ---------------------------------------------------------------------------
# build_relationship_view
# ---------------------------------------------------------------------------


def test_build_relationship_view_aggregates_forward_strength():
    book = _book()
    book.add_relationship(
        _relationship(
            relationship_id="r:1",
            source_id="agent:firm_x",
            target_id="agent:bank_a",
            relationship_type="main_bank",
            strength=0.7,
        )
    )
    book.add_relationship(
        _relationship(
            relationship_id="r:2",
            source_id="agent:firm_x",
            target_id="agent:bank_a",
            relationship_type="advisory",
            strength=0.3,
        )
    )

    view = book.build_relationship_view("agent:firm_x", "agent:bank_a")
    assert isinstance(view, RelationshipView)
    assert view.subject_id == "agent:firm_x"
    assert view.counterparty_id == "agent:bank_a"
    assert abs(view.total_strength - 1.0) < 1e-9
    assert view.relationship_types == ("advisory", "main_bank")
    assert view.visible_relationship_ids == ("r:1", "r:2")


def test_build_relationship_view_includes_undirected_reverse_records():
    """
    Records in the reverse direction (counterparty → subject) are
    included when their direction is 'undirected' or 'reciprocal'.
    """
    book = _book()
    # Forward: A → B, directed.
    book.add_relationship(
        _relationship(
            relationship_id="r:forward",
            source_id="agent:a",
            target_id="agent:b",
            direction="directed",
            strength=0.4,
        )
    )
    # Reverse: B → A, undirected — should be included from A's view.
    book.add_relationship(
        _relationship(
            relationship_id="r:undirected",
            source_id="agent:b",
            target_id="agent:a",
            direction="undirected",
            strength=0.6,
        )
    )
    # Reverse: B → A, directed — should NOT be included from A's view.
    book.add_relationship(
        _relationship(
            relationship_id="r:reverse_directed",
            source_id="agent:b",
            target_id="agent:a",
            direction="directed",
            strength=0.5,
        )
    )

    view = book.build_relationship_view("agent:a", "agent:b")
    assert set(view.visible_relationship_ids) == {"r:forward", "r:undirected"}
    assert abs(view.total_strength - 1.0) < 1e-9


def test_build_relationship_view_returns_empty_for_no_relationships():
    book = _book()
    view = book.build_relationship_view("agent:nobody", "agent:nothing")
    assert view.total_strength == 0.0
    assert view.relationship_types == ()
    assert view.visible_relationship_ids == ()


def test_build_relationship_view_does_not_apply_decay():
    """v1.5 explicitly does not apply decay_rate when summing strength."""
    book = _book()
    book.add_relationship(
        _relationship(
            strength=1.0,
            decay_rate=0.99,
            as_of_date="2026-01-01",
        )
    )
    view = book.build_relationship_view("agent:firm_x", "agent:bank_a")
    assert view.total_strength == 1.0  # raw, no decay


def test_build_relationship_view_does_not_trigger_behavior():
    """
    Building a view is a pure read — no signal emission, no event
    publishing, no cross-space mutation.
    """
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )
    kernel.relationships.add_relationship(_relationship(strength=0.7))

    signals_before = kernel.signals.snapshot()

    kernel.relationships.build_relationship_view("agent:firm_x", "agent:bank_a")

    # No signals were emitted by the view.
    assert kernel.signals.snapshot() == signals_before


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_lists_relationships_sorted():
    book = _book()
    book.add_relationship(_relationship(relationship_id="r:b"))
    book.add_relationship(_relationship(relationship_id="r:a"))
    book.add_relationship(_relationship(relationship_id="r:c"))

    snap = book.snapshot()
    assert snap["count"] == 3
    assert [r["relationship_id"] for r in snap["relationships"]] == [
        "r:a",
        "r:b",
        "r:c",
    ]


def test_snapshot_returns_empty_structure_for_empty_book():
    snap = RelationshipCapitalBook().snapshot()
    assert snap == {"count": 0, "relationships": []}


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_add_relationship_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_relationship(
        _relationship(
            relationship_type="main_bank",
            visibility="public",
            evidence_refs=("contract:loan_001",),
        )
    )

    records = book.ledger.filter(event_type="relationship_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "relationship:001"
    assert record.source == "agent:firm_x"
    assert record.target == "agent:bank_a"
    assert record.payload["relationship_type"] == "main_bank"
    assert record.payload["strength"] == 0.7
    assert record.simulation_date == "2026-01-01"
    assert record.space_id == "relationships"


def test_add_does_not_record_when_no_ledger():
    book = RelationshipCapitalBook()
    book.add_relationship(_relationship())
    assert book.get_relationship("relationship:001") is not None


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def test_relationship_book_does_not_mutate_other_books():
    """
    Adding, updating, and querying relationships must not touch any
    other source-of-truth book. Relationship capital is a record-only
    layer in v1.5.
    """
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.ownership.add_position("agent:firm_x", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-01-01", "system")

    ownership_before = kernel.ownership.snapshot()
    contracts_before = kernel.contracts.snapshot()
    prices_before = kernel.prices.snapshot()
    constraints_before = kernel.constraints.snapshot()
    signals_before = kernel.signals.snapshot()
    valuations_before = kernel.valuations.snapshot()
    institutions_before = kernel.institutions.snapshot()
    external_before = kernel.external_processes.snapshot()

    # Run a full slate of v1.5 operations.
    kernel.relationships.add_relationship(_relationship())
    kernel.relationships.update_strength(
        "relationship:001", new_strength=0.9, reason="test"
    )
    kernel.relationships.list_by_source("agent:firm_x")
    kernel.relationships.list_by_target("agent:bank_a")
    kernel.relationships.list_by_type("main_bank")
    kernel.relationships.list_between("agent:firm_x", "agent:bank_a")
    kernel.relationships.build_relationship_view(
        "agent:firm_x", "agent:bank_a"
    )
    kernel.relationships.snapshot()

    # All other books are untouched.
    assert kernel.ownership.snapshot() == ownership_before
    assert kernel.contracts.snapshot() == contracts_before
    assert kernel.prices.snapshot() == prices_before
    assert kernel.constraints.snapshot() == constraints_before
    assert kernel.signals.snapshot() == signals_before
    assert kernel.valuations.snapshot() == valuations_before
    assert kernel.institutions.snapshot() == institutions_before
    assert kernel.external_processes.snapshot() == external_before


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_relationships_with_default_wiring():
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.relationships.add_relationship(_relationship())

    assert kernel.relationships.ledger is kernel.ledger
    assert kernel.relationships.clock is kernel.clock
    assert (
        len(kernel.ledger.filter(event_type="relationship_added")) == 1
    )
