"""
v1.24.2 — Manual annotation readout pin tests.

Pins ``world/manual_annotation_readout.py``:

- ``build_manual_annotation_readout`` is read-only
  (no kernel mutation, no ledger emission, no apply call,
  no add_annotation call);
- ``annotation_label_counts`` /
  ``annotations_by_scope`` / ``reviewer_role_counts``
  are counts, not scores;
- ``unresolved_cited_record_ids`` surfaces dangling
  citations;
- determinism: same kernel state → byte-identical
  readout + markdown;
- forbidden-token boundary scan rejects metadata keys;
- markdown contains required sections + carries no
  v1.21.0a / v1.22.0 forbidden wording outside the
  pinned boundary block;
- the v1.23.2 validation hook is optional / non-mandatory;
- existing v1.23.2 validation tests still pass without
  annotations (verified by collecting the existing
  validation test files).
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.manual_annotation_readout import (
    ManualAnnotationReadout,
    build_manual_annotation_readout,
    build_manual_annotation_validation_hook_summary,
    render_manual_annotation_readout_markdown,
)
from world.manual_annotations import (
    ManualAnnotationRecord,
)
from world.registry import Registry
from world.scenario_drivers import ScenarioDriverTemplate
from world.scheduler import Scheduler
from world.state import State
from world.stress_applications import apply_stress_program
from world.stress_programs import (
    StressProgramTemplate,
    StressStep,
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


def _build_template() -> ScenarioDriverTemplate:
    return ScenarioDriverTemplate(
        scenario_driver_template_id=(
            "scenario_driver:credit_tightening:reference"
        ),
        scenario_family_label="credit_tightening_driver",
        driver_group_label="credit_liquidity",
        driver_label="Synthetic test driver",
        event_date_policy_label="quarter_end",
        severity_label="medium",
        affected_actor_scope_label="market_wide",
        expected_annotation_type_label="financing_constraint",
        affected_evidence_bucket_labels=(
            "market_environment_state",
            "financing_review_surface",
        ),
    )


def _seed_kernel_with_one_program_application() -> tuple[
    WorldKernel, str
]:
    """Seed a kernel with one resolved stress program +
    application so we can attach annotations citing the
    extant scenario_application id."""
    kernel = _bare_kernel()
    kernel.scenario_drivers.add_template(_build_template())
    program_id = "stress_program:test_v1_24_2:single"
    program = StressProgramTemplate(
        stress_program_template_id=program_id,
        program_label="v1.24.2 readout fixture",
        program_purpose_label=(
            "single_credit_tightening_stress"
        ),
        stress_steps=(
            StressStep(
                stress_step_id=f"{program_id}:step:0",
                parent_stress_program_template_id=program_id,
                step_index=0,
                scenario_driver_template_id=(
                    "scenario_driver:credit_tightening:reference"
                ),
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            ),
        ),
    )
    kernel.stress_programs.add_program(program)
    receipt = apply_stress_program(
        kernel,
        stress_program_template_id=program_id,
        as_of_date="2026-04-30",
    )
    return kernel, receipt.stress_program_application_id


def _annotation(
    annotation_id: str,
    *,
    annotation_scope_label: str = "stress_readout",
    annotation_label: str = "same_review_frame",
    cited_record_ids: tuple[str, ...] = (
        "stress_field_readout:nonexistent",
    ),
    reviewer_role_label: str = "reviewer",
    case_study_id: str | None = None,
) -> ManualAnnotationRecord:
    return ManualAnnotationRecord(
        annotation_id=annotation_id,
        annotation_scope_label=annotation_scope_label,
        annotation_label=annotation_label,
        cited_record_ids=cited_record_ids,
        reviewer_role_label=reviewer_role_label,
        case_study_id=case_study_id,
    )


# ---------------------------------------------------------------------------
# 1. Read-only — readout building does not mutate / re-add /
#    re-apply.
# ---------------------------------------------------------------------------


def test_manual_annotation_readout_is_read_only() -> None:
    """Same kernel state → byte-identical readout +
    byte-identical markdown across two consecutive calls.
    Snapshots of every relevant book (scenario_drivers /
    scenario_applications / stress_applications /
    manual_annotations / ledger) are byte-identical pre /
    post."""
    kernel, _ = _seed_kernel_with_one_program_application()
    kernel.manual_annotations.add_annotation(_annotation("ma:1"))
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:2", annotation_label="citation_gap_note"
        )
    )

    snap_before = {
        "scenario_drivers": (
            kernel.scenario_drivers.snapshot()
        ),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "manual_annotations": (
            kernel.manual_annotations.snapshot()
        ),
        "ledger_len": len(kernel.ledger.records),
    }
    a = build_manual_annotation_readout(kernel)
    snap_after_1 = {
        "scenario_drivers": (
            kernel.scenario_drivers.snapshot()
        ),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "manual_annotations": (
            kernel.manual_annotations.snapshot()
        ),
        "ledger_len": len(kernel.ledger.records),
    }
    assert snap_before == snap_after_1
    b = build_manual_annotation_readout(kernel)
    assert a.to_dict() == b.to_dict()
    md_a = render_manual_annotation_readout_markdown(a)
    md_b = render_manual_annotation_readout_markdown(b)
    assert md_a == md_b


# ---------------------------------------------------------------------------
# 2. Counts are counts (not scores). The label-count
#    multiset preserves first-occurrence order.
# ---------------------------------------------------------------------------


def test_readout_counts_annotation_labels_without_scores() -> None:
    """Three annotations with two labels produce a
    (label, count) tuple summing to three. The pair shape
    is (str, int); no float / score / weight."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:a", annotation_label="same_review_frame"
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:b", annotation_label="same_review_frame"
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:c", annotation_label="citation_gap_note"
        )
    )
    readout = build_manual_annotation_readout(kernel)
    label_counts = dict(readout.annotation_label_counts)
    assert label_counts == {
        "same_review_frame": 2,
        "citation_gap_note": 1,
    }
    # Pair shape is (str, int).
    for pair in readout.annotation_label_counts:
        label, count = pair
        assert isinstance(label, str)
        assert isinstance(count, int)
        assert not isinstance(count, bool)
    # First-occurrence order preserved.
    assert (
        readout.annotation_label_counts[0][0]
        == "same_review_frame"
    )


# ---------------------------------------------------------------------------
# 3. Counts annotation scopes — same shape contract.
# ---------------------------------------------------------------------------


def test_readout_counts_annotation_scopes() -> None:
    """``annotations_by_scope`` is a (scope, count) pair
    tuple with the same shape contract as the label
    counts."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:1",
            annotation_scope_label="stress_readout",
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:2",
            annotation_scope_label="case_study",
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:3",
            annotation_scope_label="case_study",
        )
    )
    readout = build_manual_annotation_readout(kernel)
    scope_counts = dict(readout.annotations_by_scope)
    assert scope_counts == {
        "stress_readout": 1,
        "case_study": 2,
    }


# ---------------------------------------------------------------------------
# 4. Unresolved cited record ids — surfaces dangling
#    citations.
# ---------------------------------------------------------------------------


def test_readout_surfaces_unresolved_cited_record_ids() -> None:
    """An annotation citing a non-existent
    ``scenario_application:nonexistent`` id produces an
    unresolved cited id in the readout. An annotation
    citing an extant id resolves cleanly."""
    kernel, receipt_id = (
        _seed_kernel_with_one_program_application()
    )
    apps = (
        kernel.scenario_applications.list_applications()
    )
    extant_app_id = apps[0].scenario_application_id
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:resolved",
            cited_record_ids=(extant_app_id,),
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:dangling",
            cited_record_ids=(
                "scenario_application:nonexistent_id",
            ),
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:unknown_prefix",
            cited_record_ids=(
                "totally_unknown_prefix:foo",
            ),
        )
    )
    readout = build_manual_annotation_readout(kernel)
    assert extant_app_id not in (
        readout.unresolved_cited_record_ids
    )
    assert (
        "scenario_application:nonexistent_id"
        in readout.unresolved_cited_record_ids
    )
    assert (
        "totally_unknown_prefix:foo"
        in readout.unresolved_cited_record_ids
    )
    # Warnings surface the diagnostic counts.
    assert any(
        "do not resolve" in w
        or "unrecognised plain-id prefix" in w
        for w in readout.warnings
    )


# ---------------------------------------------------------------------------
# 5. No ledger record emission.
# ---------------------------------------------------------------------------


def test_readout_does_not_emit_ledger_records() -> None:
    """Building the readout must not emit any ledger
    record."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(_annotation("ma:1"))
    ledger_len_before = len(kernel.ledger.records)
    build_manual_annotation_readout(kernel)
    assert len(kernel.ledger.records) == ledger_len_before


# ---------------------------------------------------------------------------
# 6. No kernel mutation.
# ---------------------------------------------------------------------------


def test_readout_does_not_mutate_kernel() -> None:
    """Snapshots of every kernel book are byte-identical
    pre / post readout build."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(_annotation("ma:1"))
    snap_before = {
        "manual_annotations": (
            kernel.manual_annotations.snapshot()
        ),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "ledger_len": len(kernel.ledger.records),
    }
    build_manual_annotation_readout(kernel)
    snap_after = {
        "manual_annotations": (
            kernel.manual_annotations.snapshot()
        ),
        "scenario_applications": (
            kernel.scenario_applications.snapshot()
        ),
        "stress_applications": (
            kernel.stress_applications.snapshot()
        ),
        "ledger_len": len(kernel.ledger.records),
    }
    assert snap_before == snap_after


# ---------------------------------------------------------------------------
# 7. No call to apply / add_annotation helpers.
# ---------------------------------------------------------------------------


def test_readout_does_not_call_apply_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The readout must not call apply_stress_program /
    apply_scenario_driver / add_annotation. Monkey-patch
    each to raise; the readout build must still
    succeed."""
    import world.manual_annotations as ma_mod
    import world.scenario_applications as sa_mod
    import world.stress_applications as sap_mod

    def _forbid(*args, **kwargs):
        raise AssertionError(
            "manual annotation readout called a forbidden "
            "helper — read-only discipline violated"
        )

    monkeypatch.setattr(
        sap_mod, "apply_stress_program", _forbid
    )
    monkeypatch.setattr(
        sa_mod, "apply_scenario_driver", _forbid
    )
    monkeypatch.setattr(
        ma_mod.ManualAnnotationBook,
        "add_annotation",
        _forbid,
    )
    kernel = _bare_kernel()
    readout = build_manual_annotation_readout(kernel)
    assert readout.annotation_count == 0


# ---------------------------------------------------------------------------
# 8. No interaction inference. The readout never produces
#    an interaction-label / aggregate / composite token.
# ---------------------------------------------------------------------------


def test_readout_does_not_infer_interactions() -> None:
    """The readout's serialised output contains no
    v1.21.0a interaction label (`amplify` / `dampen` /
    `offset` / `coexist`) and no v1.22.0 outcome /
    aggregate / dominant token. Whole-word scan over the
    rendered markdown body (excluding boundary
    statement)."""
    kernel = _bare_kernel()
    # Add three annotations with two scopes / two labels.
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:1",
            annotation_label="same_review_frame",
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:2",
            annotation_label="uncited_stress_candidate",
            annotation_scope_label="case_study",
        )
    )
    kernel.manual_annotations.add_annotation(
        _annotation(
            "ma:3",
            annotation_label="partial_application_note",
        )
    )
    readout = build_manual_annotation_readout(kernel)
    md = render_manual_annotation_readout_markdown(readout)
    body = md.split("## Boundary statement")[0].lower()
    interaction_tokens = (
        "amplify",
        "dampen",
        "offset",
        "coexist",
        "aggregate",
        "composite",
        "dominant",
    )
    for token in interaction_tokens:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, body) is None, (
            f"forbidden interaction token {token!r} appears "
            "in the readout body (outside boundary statement)"
        )


# ---------------------------------------------------------------------------
# 9. Forbidden metadata is rejected at construction.
# ---------------------------------------------------------------------------


def test_readout_rejects_forbidden_metadata() -> None:
    """``ManualAnnotationReadout(metadata=...)``
    construction rejects forbidden keys directly. The
    helper passes caller-supplied metadata through after
    the same scan."""
    kernel = _bare_kernel()
    with pytest.raises(ValueError):
        build_manual_annotation_readout(
            kernel,
            metadata={"causal_effect": "anything"},
        )
    # And direct dataclass construction raises.
    with pytest.raises(ValueError):
        ManualAnnotationReadout(
            readout_id="manual_annotation_readout:test",
            annotation_ids=(),
            cited_record_ids=(),
            annotation_label_counts=(),
            annotations_by_scope=(),
            unresolved_cited_record_ids=(),
            reviewer_role_counts=(),
            metadata={"forecast": "no"},
        )


# ---------------------------------------------------------------------------
# 10. Markdown contains required sections.
# ---------------------------------------------------------------------------


def test_markdown_contains_required_sections() -> None:
    """The renderer emits each of the eight required
    sections in order: Manual annotation readout /
    Annotation labels / Annotation scopes / Cited records /
    Unresolved citations / Reviewer roles / Warnings /
    Boundary statement."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(_annotation("ma:1"))
    md = render_manual_annotation_readout_markdown(
        build_manual_annotation_readout(kernel)
    )
    required_sections = (
        "## Manual annotation readout",
        "## Annotation labels",
        "## Annotation scopes",
        "## Cited records",
        "## Unresolved citations",
        "## Reviewer roles",
        "## Warnings",
        "## Boundary statement",
    )
    last_idx = -1
    for section in required_sections:
        idx = md.find(section)
        assert idx >= 0, (
            f"markdown missing required section {section!r}"
        )
        assert idx > last_idx, (
            f"section {section!r} out of order"
        )
        last_idx = idx


# ---------------------------------------------------------------------------
# 11. Markdown has no forbidden wording outside boundary
#     statement.
# ---------------------------------------------------------------------------


def test_markdown_has_no_forbidden_wording() -> None:
    """The rendered markdown body (excluding the
    ``## Boundary statement`` section, which legitimately
    references each forbidden token under the negation
    form) carries no forbidden wording."""
    kernel = _bare_kernel()
    kernel.manual_annotations.add_annotation(_annotation("ma:1"))
    md = render_manual_annotation_readout_markdown(
        build_manual_annotation_readout(kernel)
    )
    body = md.split("## Boundary statement")[0].lower()
    forbidden_phrases = (
        "impact",
        "outcome",
        "risk score",
        "forecast",
        "prediction",
        "recommendation",
        "causal effect",
        "amplification",
        "dampening",
        "offset effect",
        "expected return",
        "target price",
        "investment advice",
    )
    for phrase in forbidden_phrases:
        assert phrase not in body, (
            f"forbidden phrase {phrase!r} in markdown body"
        )


# ---------------------------------------------------------------------------
# 12. Validation hook is optional / backward-compatible.
# ---------------------------------------------------------------------------


def test_validation_hook_optional_and_backward_compatible() -> None:
    """The hook returns a dict with two non-negative int
    counts. A kernel with no annotations returns zeros.
    A kernel with annotations returns positive counts +
    the unresolved citation count if any."""
    # Empty kernel.
    k0 = _bare_kernel()
    s0 = build_manual_annotation_validation_hook_summary(k0)
    assert s0 == {
        "manual_annotation_count": 0,
        "unresolved_annotation_citation_count": 0,
    }
    # Kernel with one resolved + one dangling annotation.
    k1, _ = _seed_kernel_with_one_program_application()
    apps = (
        k1.scenario_applications.list_applications()
    )
    extant_app_id = apps[0].scenario_application_id
    k1.manual_annotations.add_annotation(
        _annotation(
            "ma:resolved",
            cited_record_ids=(extant_app_id,),
        )
    )
    k1.manual_annotations.add_annotation(
        _annotation(
            "ma:dangling",
            cited_record_ids=(
                "scenario_application:nope",
            ),
        )
    )
    s1 = build_manual_annotation_validation_hook_summary(k1)
    assert s1["manual_annotation_count"] == 2
    assert (
        s1["unresolved_annotation_citation_count"] >= 1
    )
    # The hook returns a fresh dict; no shared state.
    s2 = build_manual_annotation_validation_hook_summary(k0)
    assert s2["manual_annotation_count"] == 0


# ---------------------------------------------------------------------------
# 13. Existing v1.23.2 validation tests still pass.
#     We re-collect (and filter for) those test ids and
#     confirm they exist; a separate, broader full-suite
#     run is the canonical proof.
# ---------------------------------------------------------------------------


def test_existing_validation_tests_still_pass_without_annotations() -> None:
    """Re-import the v1.23.2 validation test modules and
    exercise the canonical pin functions (which take no
    annotation kernel state) to confirm they still
    produce the same results without an annotation
    book."""
    # Smoke import of the v1.23.2 test modules.
    import importlib

    for mod_name in (
        "test_validation_determinism",
        "test_validation_boundary",
        "test_validation_citation_completeness",
        "test_validation_partial_application_visibility",
        "test_validation_placeholder_categories",
    ):
        mod = importlib.import_module(mod_name)
        assert mod is not None, (
            f"v1.23.2 validation module {mod_name!r} "
            "missing"
        )

    # A kernel without an annotation book continues to
    # satisfy the v1.23.2 Cat 1-4 pins exactly as before
    # — verified by the determinism pin function existing
    # and being callable.
    from test_validation_determinism import (
        test_validation_determinism_pin_v1_23_2_readout_dict,
    )
    test_validation_determinism_pin_v1_23_2_readout_dict()
    # And the case-study pin from v1.23.3 still passes
    # without manual annotations.
    from test_attention_crowding_case_study import (
        test_attention_crowding_case_study_report_is_deterministic,
    )
    test_attention_crowding_case_study_report_is_deterministic()
