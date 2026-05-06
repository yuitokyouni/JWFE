"""
v1.24.1 — Manual annotation storage pin tests.

Pins ``world/manual_annotations.py`` per the v1.24.0 design
note (`docs/v1_24_manual_annotation_layer.md`):

- ``ManualAnnotationRecord`` validates required fields,
  rejects empty cited_record_ids, rejects auto / LLM
  source_kind, rejects non-human_authored reasoning_mode,
  rejects forbidden field names, rejects forbidden
  metadata keys, rejects forbidden ``note_text`` wording;
- ``ManualAnnotationBook`` provides add / get / list /
  list_by_scope / list_by_label / list_by_case_study /
  list_by_cited_record / snapshot;
- duplicate ``annotation_id`` is rejected and emits no
  extra ledger record;
- the storage layer does not mutate any pre-existing
  source-of-truth book and does not call
  ``apply_stress_program`` / ``apply_scenario_driver``;
- the ``WorldKernel.manual_annotations`` field is empty
  by default;
- every existing canonical ``living_world_digest`` value
  remains byte-identical with an empty manual-annotation
  book;
- the ledger payload contains no v1.24.0 forbidden token
  at any key.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.forbidden_tokens import (
    FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES,
)
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.manual_annotations import (
    ANNOTATION_LABELS,
    ANNOTATION_SCOPE_LABELS,
    DuplicateManualAnnotationError,
    MANUAL_ANNOTATION_REASONING_MODE,
    MANUAL_ANNOTATION_SOURCE_KIND,
    ManualAnnotationBook,
    ManualAnnotationRecord,
    REVIEWER_ROLE_LABELS,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State

from _canonical_digests import (
    MONTHLY_REFERENCE_LIVING_WORLD_DIGEST,
    QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
    SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST,
)


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------


def _bare_kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 4, 30)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _build_record(
    *,
    annotation_id: str = "manual_annotation:test:01",
    annotation_scope_label: str = "stress_readout",
    annotation_label: str = "same_review_frame",
    cited_record_ids: tuple[str, ...] = (
        "stress_field_readout:foo",
    ),
    reviewer_role_label: str = "reviewer",
    case_study_id: str | None = None,
    created_for_record_id: str | None = None,
    note_text: str | None = None,
    metadata: dict | None = None,
) -> ManualAnnotationRecord:
    return ManualAnnotationRecord(
        annotation_id=annotation_id,
        annotation_scope_label=annotation_scope_label,
        annotation_label=annotation_label,
        cited_record_ids=cited_record_ids,
        reviewer_role_label=reviewer_role_label,
        case_study_id=case_study_id,
        created_for_record_id=created_for_record_id,
        note_text=note_text,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Required fields validate.
# ---------------------------------------------------------------------------


def test_manual_annotation_record_validates_required_fields() -> None:
    """A valid record constructs cleanly; an empty
    ``annotation_id`` / scope / label / reviewer-role
    is rejected. Closed-set membership is enforced."""
    r = _build_record()
    assert r.annotation_id == "manual_annotation:test:01"
    assert r.annotation_scope_label == "stress_readout"
    assert r.annotation_label == "same_review_frame"
    assert r.source_kind == MANUAL_ANNOTATION_SOURCE_KIND
    assert r.reasoning_mode == (
        MANUAL_ANNOTATION_REASONING_MODE
    )
    # Required-string discipline.
    with pytest.raises(ValueError):
        _build_record(annotation_id="")
    # Closed-set membership.
    with pytest.raises(ValueError):
        _build_record(
            annotation_scope_label="not_a_real_scope"
        )
    with pytest.raises(ValueError):
        _build_record(
            annotation_label="not_a_real_label"
        )
    with pytest.raises(ValueError):
        _build_record(
            reviewer_role_label="not_a_real_role"
        )
    # Defaults.
    assert r.case_study_id is None
    assert r.created_for_record_id is None
    assert r.note_text is None
    assert r.status == "active"
    # Boundary flags must include every default.
    for flag in (
        "no_actor_decision",
        "no_llm_execution",
        "no_price_formation",
        "no_aggregate_stress_result",
        "no_interaction_inference",
        "human_authored_only",
        "no_auto_annotation",
        "no_causal_proof",
        "descriptive_only",
    ):
        assert r.boundary_flags[flag] is True


# ---------------------------------------------------------------------------
# 2. cited_record_ids must be non-empty.
# ---------------------------------------------------------------------------


def test_manual_annotation_rejects_empty_cited_record_ids() -> None:
    """``cited_record_ids`` is non-empty by binding."""
    with pytest.raises(ValueError):
        _build_record(cited_record_ids=())
    # And every entry must be a non-empty string.
    with pytest.raises(ValueError):
        _build_record(cited_record_ids=("",))


# ---------------------------------------------------------------------------
# 3. source_kind = "human" only.
# ---------------------------------------------------------------------------


def test_manual_annotation_rejects_auto_or_llm_source_kind() -> None:
    """``source_kind`` is the closed singleton ``"human"``.
    ``"auto"`` / ``"llm"`` / any other value raises."""
    for forbidden in ("auto", "llm", "automated", "robot"):
        with pytest.raises(ValueError):
            ManualAnnotationRecord(
                annotation_id="manual_annotation:test:auto",
                annotation_scope_label="stress_readout",
                annotation_label="same_review_frame",
                cited_record_ids=("foo:1",),
                source_kind=forbidden,
            )


# ---------------------------------------------------------------------------
# 4. reasoning_mode = "human_authored" only.
# ---------------------------------------------------------------------------


def test_manual_annotation_rejects_non_human_authored_reasoning_mode() -> None:
    """``reasoning_mode`` is the closed singleton
    ``"human_authored"``."""
    for forbidden in (
        "rule_based_fallback",
        "llm_assisted",
        "auto_inferred",
        "external_policy_slot",
    ):
        with pytest.raises(ValueError):
            ManualAnnotationRecord(
                annotation_id="manual_annotation:test:rm",
                annotation_scope_label="stress_readout",
                annotation_label="same_review_frame",
                cited_record_ids=("foo:1",),
                reasoning_mode=forbidden,
            )


# ---------------------------------------------------------------------------
# 5. Forbidden field names — guaranteed by the field-name
#    guard at construction.
# ---------------------------------------------------------------------------


def test_manual_annotation_rejects_forbidden_field_names() -> None:
    """The dataclass field set has zero overlap with the
    v1.24.0 canonical
    ``FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES`` composition."""
    from dataclasses import fields as dc_fields
    field_names = {
        f.name for f in dc_fields(ManualAnnotationRecord)
    }
    overlap = (
        field_names & FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES
    )
    assert overlap == set(), (
        "ManualAnnotationRecord fields overlap with v1.24.0 "
        f"forbidden set: {sorted(overlap)!r}"
    )
    # And the closed-set vocabularies do not contain any
    # forbidden token.
    assert (
        ANNOTATION_LABELS
        & FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES
    ) == set()
    assert (
        ANNOTATION_SCOPE_LABELS
        & FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES
    ) == set()
    assert (
        REVIEWER_ROLE_LABELS
        & FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES
    ) == set()


# ---------------------------------------------------------------------------
# 6. Forbidden metadata keys — rejected at construction.
# ---------------------------------------------------------------------------


def test_manual_annotation_rejects_forbidden_metadata_keys() -> None:
    """Every v1.24.0 forbidden token rejected as a metadata
    key. Spot-check several token classes."""
    for forbidden_key in (
        "amplify",
        "dampen",
        "offset",
        "coexist",
        "causal_effect",
        "impact_score",
        "risk_score",
        "forecast",
        "prediction",
        "recommendation",
        "expected_return",
        "target_price",
        "buy",
        "sell",
        "order",
        "trade",
        "execution",
        "investment_advice",
        "japan_calibration",
        "llm_output",
        "auto_annotation",
        "auto_inference",
        "automatic_review",
        "llm_annotation",
        "inferred_interaction",
        "causal_proof",
        "actor_decision",
        "aggregate_shift_direction",
        "composite_risk_label",
        "dominant_stress_label",
        "net_stress_direction",
    ):
        with pytest.raises(ValueError):
            _build_record(
                metadata={forbidden_key: "anything"},
            )


# ---------------------------------------------------------------------------
# 7. Forbidden ``note_text`` — whole-word scan rejects.
# ---------------------------------------------------------------------------


def test_manual_annotation_rejects_forbidden_note_text() -> None:
    """``note_text`` is descriptive only; whole-word scan
    rejects any v1.24.0 forbidden token (case-
    insensitive)."""
    for forbidden_phrase in (
        "this stress will amplify the next one",
        "expected to dampen demand next quarter",
        "I think this is a forecast of credit conditions",
        "buy signal under tightening regime",
        "investment advice: increase allocation",
        "auto_annotation captured this case",
        "LLM output suggests amplification",
        "causal_effect across both programs",
        "predicted_stress_effect was high",
    ):
        with pytest.raises(ValueError):
            _build_record(note_text=forbidden_phrase)


# ---------------------------------------------------------------------------
# 8. Add / get / list / snapshot.
# ---------------------------------------------------------------------------


def test_manual_annotation_book_add_get_list_snapshot() -> None:
    """Append-only book CRUD: add, get, list,
    list_by_scope, list_by_label, list_by_case_study,
    snapshot."""
    book = ManualAnnotationBook()
    a = _build_record(
        annotation_id="manual_annotation:test:a",
        annotation_label="same_review_frame",
        annotation_scope_label="stress_readout",
        case_study_id="attention_crowding_case_study:1",
    )
    b = _build_record(
        annotation_id="manual_annotation:test:b",
        annotation_label="citation_gap_note",
        annotation_scope_label="case_study",
        case_study_id="attention_crowding_case_study:1",
        cited_record_ids=("scenario_application:bar",),
    )
    c = _build_record(
        annotation_id="manual_annotation:test:c",
        annotation_label="same_review_frame",
        annotation_scope_label="case_study",
    )
    book.add_annotation(a)
    book.add_annotation(b)
    book.add_annotation(c)

    assert (
        book.get_annotation("manual_annotation:test:a")
        is a
    )
    assert len(book.list_annotations()) == 3
    # By scope. Compare by ``annotation_id`` (the records
    # contain dict fields and are not hashable).
    assert {
        r.annotation_id for r in book.list_by_scope("stress_readout")
    } == {a.annotation_id}
    assert {
        r.annotation_id for r in book.list_by_scope("case_study")
    } == {b.annotation_id, c.annotation_id}
    # By label.
    assert {
        r.annotation_id
        for r in book.list_by_label("same_review_frame")
    } == {a.annotation_id, c.annotation_id}
    assert {
        r.annotation_id
        for r in book.list_by_label("citation_gap_note")
    } == {b.annotation_id}
    # By case study.
    assert {
        r.annotation_id
        for r in book.list_by_case_study(
            "attention_crowding_case_study:1"
        )
    } == {a.annotation_id, b.annotation_id}
    # Snapshot.
    snap = book.snapshot()
    assert "manual_annotations" in snap
    assert len(snap["manual_annotations"]) == 3


# ---------------------------------------------------------------------------
# 9. List by cited record id.
# ---------------------------------------------------------------------------


def test_manual_annotation_list_by_cited_record() -> None:
    """``list_by_cited_record(id)`` returns every annotation
    that cites ``id``. Multi-citation membership is
    handled."""
    book = ManualAnnotationBook()
    a = _build_record(
        annotation_id="manual_annotation:test:a",
        cited_record_ids=("stress_field_readout:1",),
    )
    b = _build_record(
        annotation_id="manual_annotation:test:b",
        cited_record_ids=(
            "stress_field_readout:1",
            "scenario_application:1",
        ),
    )
    c = _build_record(
        annotation_id="manual_annotation:test:c",
        cited_record_ids=("scenario_application:2",),
    )
    book.add_annotation(a)
    book.add_annotation(b)
    book.add_annotation(c)
    assert {
        r.annotation_id
        for r in book.list_by_cited_record(
            "stress_field_readout:1"
        )
    } == {a.annotation_id, b.annotation_id}
    assert {
        r.annotation_id
        for r in book.list_by_cited_record(
            "scenario_application:2"
        )
    } == {c.annotation_id}
    assert (
        book.list_by_cited_record("nonexistent:1") == ()
    )


# ---------------------------------------------------------------------------
# 10. Duplicate add emits no extra ledger record.
# ---------------------------------------------------------------------------


def test_duplicate_annotation_emits_no_extra_ledger_record() -> None:
    """``DuplicateManualAnnotationError`` raised on second
    add of the same id; ledger length unchanged on the
    failed second add."""
    kernel = _bare_kernel()
    a = _build_record()
    kernel.manual_annotations.add_annotation(a)
    ledger_len_after_add = len(kernel.ledger.records)
    # Exactly one ledger record was emitted by the first
    # add.
    assert ledger_len_after_add >= 1
    last_record = kernel.ledger.records[-1]
    assert (
        last_record.event_type
        == RecordType.MANUAL_ANNOTATION_RECORDED.value
    )
    # Duplicate raises and emits no extra ledger record.
    with pytest.raises(DuplicateManualAnnotationError):
        kernel.manual_annotations.add_annotation(a)
    assert (
        len(kernel.ledger.records) == ledger_len_after_add
    )


# ---------------------------------------------------------------------------
# 11. No source-of-truth book mutation.
# ---------------------------------------------------------------------------


def test_annotation_storage_does_not_mutate_source_of_truth_books() -> None:
    """Adding an annotation must not mutate any other
    kernel book. Snapshot every relevant book pre / post
    and assert byte-identity (modulo the ledger and the
    manual-annotation book itself)."""
    kernel = _bare_kernel()
    snap_before = {
        "scenario_drivers": (
            kernel.scenario_drivers.snapshot()
        ),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_programs": (
            kernel.stress_programs.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "market_environments": (
            kernel.market_environments.snapshot()
        ),
        "ownership": kernel.ownership.snapshot(),
        "contracts": kernel.contracts.snapshot(),
        "prices": kernel.prices.snapshot(),
        "constraints": kernel.constraints.snapshot(),
        "institutions": kernel.institutions.snapshot(),
    }
    kernel.manual_annotations.add_annotation(_build_record())
    snap_after = {
        "scenario_drivers": (
            kernel.scenario_drivers.snapshot()
        ),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_programs": (
            kernel.stress_programs.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "market_environments": (
            kernel.market_environments.snapshot()
        ),
        "ownership": kernel.ownership.snapshot(),
        "contracts": kernel.contracts.snapshot(),
        "prices": kernel.prices.snapshot(),
        "constraints": kernel.constraints.snapshot(),
        "institutions": kernel.institutions.snapshot(),
    }
    assert snap_before == snap_after, (
        "manual annotation storage mutated a "
        "source-of-truth book"
    )


# ---------------------------------------------------------------------------
# 12. No call to apply_stress_program /
#     apply_scenario_driver. Verified by monkey-patching
#     both helpers to raise.
# ---------------------------------------------------------------------------


def test_annotation_storage_does_not_call_apply_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The storage layer must not invoke either apply
    helper. Monkey-patch both to raise; the add still
    succeeds."""
    import world.scenario_applications as sa_mod
    import world.stress_applications as sap_mod

    def _forbid(*args, **kwargs):
        raise AssertionError(
            "manual annotation storage called an apply "
            "helper — read-only discipline violated"
        )

    monkeypatch.setattr(
        sap_mod, "apply_stress_program", _forbid
    )
    monkeypatch.setattr(
        sa_mod, "apply_scenario_driver", _forbid
    )
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(_build_record())
    assert (
        len(
            kernel.manual_annotations.list_annotations()
        )
        == 1
    )


# ---------------------------------------------------------------------------
# 13. Empty by default on the kernel.
# ---------------------------------------------------------------------------


def test_world_kernel_manual_annotations_empty_by_default() -> None:
    """A fresh kernel has an empty
    ``manual_annotations`` book + zero ledger records of
    type ``MANUAL_ANNOTATION_RECORDED``."""
    kernel = _bare_kernel()
    assert (
        kernel.manual_annotations.list_annotations() == ()
    )
    types = {
        r.event_type for r in kernel.ledger.records
    }
    assert (
        RecordType.MANUAL_ANNOTATION_RECORDED.value
        not in types
    )


# ---------------------------------------------------------------------------
# 14. Existing canonical digests unchanged with empty
#     manual-annotation book.
# ---------------------------------------------------------------------------


def test_existing_digests_unchanged_with_empty_annotation_book() -> None:
    """Every v1.21.last canonical
    ``living_world_digest`` value remains byte-identical
    when the kernel carries an empty
    ``ManualAnnotationBook``. The empty-by-default rule
    guarantees this; the explicit assertion catches a
    regression that accidentally fires the
    ``MANUAL_ANNOTATION_RECORDED`` event from kernel
    construction."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from test_living_reference_world import (
        _run_default,
        _run_monthly_reference,
        _seed_kernel,
    )

    # quarterly_default
    k_q = _seed_kernel()
    r_q = _run_default(k_q)
    assert (
        k_q.manual_annotations.list_annotations() == ()
    )
    assert (
        living_world_digest(k_q, r_q)
        == QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST
    )

    # monthly_reference
    k_m = _seed_kernel()
    r_m = _run_monthly_reference(k_m)
    assert (
        k_m.manual_annotations.list_annotations() == ()
    )
    assert (
        living_world_digest(k_m, r_m)
        == MONTHLY_REFERENCE_LIVING_WORLD_DIGEST
    )


def test_existing_scenario_universe_digest_unchanged_with_empty_annotation_book() -> None:
    """The v1.20.3 ``scenario_monthly_reference_universe``
    test-fixture digest must stay byte-identical at
    v1.24.1 when no annotation is explicitly added."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from test_living_reference_world_performance_boundary import (
        _run_v1_20_3,
        _seed_v1_20_3_kernel,
    )

    k = _seed_v1_20_3_kernel()
    r = _run_v1_20_3(k)
    assert k.manual_annotations.list_annotations() == ()
    assert (
        living_world_digest(k, r)
        == SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST
    )


# ---------------------------------------------------------------------------
# 15. Ledger payload has no forbidden keys.
# ---------------------------------------------------------------------------


def test_manual_annotation_ledger_payload_has_no_forbidden_keys() -> None:
    """The ``MANUAL_ANNOTATION_RECORDED`` ledger payload
    must not contain any v1.24.0 forbidden token at any
    key."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(
        _build_record(
            metadata={"reviewer_note_index": 1},
        )
    )
    last = kernel.ledger.records[-1]
    assert (
        last.event_type
        == RecordType.MANUAL_ANNOTATION_RECORDED.value
    )
    payload = last.payload
    # Ledger wraps payloads in MappingProxyType for
    # immutability; treat it as a generic Mapping.
    from typing import Mapping as _Mapping
    assert isinstance(payload, _Mapping)
    for key in payload.keys():
        assert (
            key not in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES
        ), (
            f"ledger payload key {key!r} is in the "
            "v1.24.0 forbidden set"
        )
    # And the boundary_flags inside the payload also
    # avoid forbidden keys.
    bf = payload.get("boundary_flags", {})
    for key in bf.keys():
        assert (
            key not in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES
        )
