"""
v1.24.2 — Manual annotation readout (read-only) + optional
validation hook.

Read-only multiset projection over a kernel's
:class:`world.manual_annotations.ManualAnnotationBook`. The
readout surfaces:

- the multiset of cited record ids (deduplicated, in
  insertion order);
- ``annotation_label_counts`` — a tuple of
  ``(label, count)`` pairs preserving the order the
  labels first appeared. **Counts are counts, not
  scores.**
- ``annotations_by_scope`` — a tuple of
  ``(scope_label, count)`` pairs preserving first-
  occurrence order;
- ``reviewer_role_counts`` — a tuple of
  ``(role_label, count)`` pairs preserving first-
  occurrence order;
- ``unresolved_cited_record_ids`` — the subset of cited
  record ids whose plain-id prefix matches one of the
  v1.24.0 supported prefixes (§5 of the design pin) but
  which does not resolve to an extant record in the
  corresponding kernel book. The Cat 3 citation-
  completeness pin extends to v1.24.2 verbatim;
- ``warnings`` — human-readable warning strings (e.g. a
  "stale stress_program_application id" warning);
- ``metadata`` — opaque, scanned for forbidden keys.

Read-only discipline (binding):

- Re-running the helper on the same kernel state
  produces a byte-identical readout. The v1.23.2 Cat 1
  determinism pin extends to v1.24.2 verbatim.
- The readout emits **no** ledger record; v1.24.2 ships
  no new :class:`world.ledger.RecordType`.
- The readout does **not** mutate any kernel book.
- The readout does **not** call
  :func:`world.stress_applications.apply_stress_program`,
  :func:`world.scenario_applications.apply_scenario_driver`,
  or :meth:`world.manual_annotations.ManualAnnotationBook.add_annotation`.
- No automatic interpretation. The readout never reduces
  multiple annotations into a "combined" annotation,
  never infers an interaction, never produces an
  outcome / impact / forecast / recommendation.
- ``note_text`` is intentionally **not** surfaced as
  source-of-truth — the readout exposes only the
  multiset shape of the book.

Optional v1.23.2 validation hook:

- :func:`build_manual_annotation_validation_hook_summary`
  returns a small dict with ``manual_annotation_count``
  and ``unresolved_annotation_citation_count``. The hook
  is **non-mandatory**: a kernel without an annotation
  book continues to satisfy the v1.23.2 Cat 1-4 pins
  exactly as before. The v1.23.2 test suite stays green
  without modification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Iterable, Mapping

from world.forbidden_tokens import (
    FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES,
)
from world.manual_annotations import (
    ANNOTATION_LABELS,
    ANNOTATION_SCOPE_LABELS,
    ManualAnnotationRecord,
    REVIEWER_ROLE_LABELS,
)

if TYPE_CHECKING:
    from world.kernel import WorldKernel


__all__ = (
    "ManualAnnotationReadout",
    "build_manual_annotation_readout",
    "build_manual_annotation_validation_hook_summary",
    "render_manual_annotation_readout_markdown",
)


# ---------------------------------------------------------------------------
# Boundary statement carried verbatim into every rendered
# markdown summary. Mirrors the v1.21.3 / v1.23.3 anti-claim
# block, scoped to the manual-annotation surface.
# ---------------------------------------------------------------------------


_BOUNDARY_STATEMENT_LINES: tuple[str, ...] = (
    "Read-only manual annotation readout. ",
    "Multiset projection only — no causality claim. ",
    "No magnitude. No probability. No aggregate / combined / ",
    "net / dominant / composite stress result. ",
    "No interaction inference (no `amplify` / `dampen` / ",
    "`offset` / `coexist` label). ",
    "No price formation. No trading. No order. No execution. ",
    "No clearing. No settlement. No financing execution. ",
    "No firm decision. No investor action. No bank approval ",
    "logic. No investment advice. No real data ingestion. ",
    "No real institutional identifiers. No Japan calibration. ",
    "No LLM execution. No LLM prose as source-of-truth. ",
    "Annotations are human-authored only; counts are counts, ",
    "never scores.",
)


# ---------------------------------------------------------------------------
# Citation-prefix → kernel-book resolver. Used by the
# unresolved-citation scan. Prefixes are stable per v1.24.0
# design §5; adding a new prefix requires a fresh design pin.
# ---------------------------------------------------------------------------


def _scenario_application_id_set(kernel: "WorldKernel") -> set[str]:
    return {
        a.scenario_application_id
        for a in kernel.scenario_applications.list_applications()
    }


def _scenario_context_shift_id_set(kernel: "WorldKernel") -> set[str]:
    return {
        s.scenario_context_shift_id
        for s in kernel.scenario_applications.list_context_shifts()
    }


def _stress_program_application_id_set(
    kernel: "WorldKernel",
) -> set[str]:
    return {
        a.stress_program_application_id
        for a in kernel.stress_applications.list_applications()
    }


def _stress_program_template_id_set(
    kernel: "WorldKernel",
) -> set[str]:
    return {
        p.stress_program_template_id
        for p in kernel.stress_programs.list_programs()
    }


def _stress_field_readout_id_resolves(
    kernel: "WorldKernel", cited_id: str
) -> bool:
    """A ``stress_field_readout:<stress_program_application_id>``
    citation resolves when the receipt id portion exists in
    the kernel's stress_applications book."""
    prefix = "stress_field_readout:"
    if not cited_id.startswith(prefix):
        return False
    receipt_id = cited_id[len(prefix):]
    return receipt_id in _stress_program_application_id_set(kernel)


def _attention_crowding_case_study_id_resolves(
    kernel: "WorldKernel", cited_id: str
) -> bool:
    """A ``attention_crowding_case_study:<stress_program_application_id>``
    citation resolves when the receipt id portion exists in
    the kernel's stress_applications book — the v1.23.3
    case-study helper's case_study_id format."""
    prefix = "attention_crowding_case_study:"
    if not cited_id.startswith(prefix):
        return False
    receipt_id = cited_id[len(prefix):]
    return receipt_id in _stress_program_application_id_set(kernel)


def _classify_citation_resolution(
    kernel: "WorldKernel", cited_id: str
) -> str:
    """Return a short closed-set classification of a
    citation:

    - ``"resolved"`` — the cited id matches an extant
      record in the corresponding book;
    - ``"unresolved"`` — the cited id matches one of the
      v1.24.0 supported prefixes but does not resolve;
    - ``"unknown_prefix"`` — the cited id does not match
      any v1.24.0 supported prefix; treated as
      unresolved for diagnostic purposes but reported
      separately so a reviewer can spot a typo.
    """
    if cited_id.startswith("scenario_application:"):
        return (
            "resolved"
            if cited_id in _scenario_application_id_set(kernel)
            else "unresolved"
        )
    if cited_id.startswith("scenario_context_shift:"):
        return (
            "resolved"
            if cited_id
            in _scenario_context_shift_id_set(kernel)
            else "unresolved"
        )
    if cited_id.startswith("stress_program_application:"):
        return (
            "resolved"
            if cited_id
            in _stress_program_application_id_set(kernel)
            else "unresolved"
        )
    if cited_id.startswith("stress_program_template:"):
        return (
            "resolved"
            if cited_id
            in _stress_program_template_id_set(kernel)
            else "unresolved"
        )
    if cited_id.startswith("stress_field_readout:"):
        return (
            "resolved"
            if _stress_field_readout_id_resolves(
                kernel, cited_id
            )
            else "unresolved"
        )
    if cited_id.startswith("attention_crowding_case_study:"):
        return (
            "resolved"
            if _attention_crowding_case_study_id_resolves(
                kernel, cited_id
            )
            else "unresolved"
        )
    if cited_id.startswith("validation_report:"):
        # v1.23.2 reserved plain-id format; no runtime
        # record exists at v1.23.last. Treat as
        # "unresolved" — the reviewer's annotation
        # references a future record type.
        return "unresolved"
    return "unknown_prefix"


# ---------------------------------------------------------------------------
# Validation helpers (mirror the v1.21.x / v1.23.x discipline)
# ---------------------------------------------------------------------------


def _validate_required_string(
    value: Any, *, field_name: str
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _validate_string_tuple(
    value: Iterable[str], *, field_name: str
) -> tuple[str, ...]:
    normalized = tuple(value)
    for entry in normalized:
        if not isinstance(entry, str) or not entry:
            raise ValueError(
                f"{field_name} entries must be non-empty "
                f"strings; got {entry!r}"
            )
    return normalized


def _validate_count_pair_tuple(
    value: Iterable[tuple[str, int]],
    *,
    field_name: str,
) -> tuple[tuple[str, int], ...]:
    """Normalise a tuple of (label, count) pairs. Labels
    must be non-empty strings; counts non-negative ints."""
    normalised = tuple(value)
    for entry in normalised:
        if (
            not isinstance(entry, tuple)
            or len(entry) != 2
        ):
            raise ValueError(
                f"{field_name} entries must be (str, int) "
                f"tuples; got {entry!r}"
            )
        label, count = entry
        if not isinstance(label, str) or not label:
            raise ValueError(
                f"{field_name} label must be non-empty "
                f"string; got {label!r}"
            )
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
        ):
            raise ValueError(
                f"{field_name} count must be int (not "
                f"bool); got {type(count).__name__}"
            )
        if count < 0:
            raise ValueError(
                f"{field_name} count must be >= 0; got "
                f"{count}"
            )
    return normalised


def _scan_for_forbidden_keys(
    mapping: Mapping[str, Any], *, field_name: str
) -> None:
    for key in mapping.keys():
        if not isinstance(key, str):
            continue
        if key in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES:
            raise ValueError(
                f"{field_name} contains forbidden key "
                f"{key!r} (v1.24.0 manual-annotation "
                "boundary)"
            )


# ---------------------------------------------------------------------------
# ManualAnnotationReadout
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualAnnotationReadout:
    """Immutable, read-only multiset projection over a
    kernel's :class:`ManualAnnotationBook`.

    Every field is one of: a plain-id string, a tuple of
    plain-id strings preserved in insertion order, a tuple
    of (label, count) pairs preserved in first-occurrence
    order, a tuple of human-readable warning strings, or
    an opaque metadata mapping scanned for forbidden keys.

    No field is a reduction. No field carries a magnitude,
    a probability, a forecast, a recommendation, or a
    composition / interaction label.
    """

    readout_id: str
    annotation_ids: tuple[str, ...]
    cited_record_ids: tuple[str, ...]
    annotation_label_counts: tuple[tuple[str, int], ...]
    annotations_by_scope: tuple[tuple[str, int], ...]
    unresolved_cited_record_ids: tuple[str, ...]
    reviewer_role_counts: tuple[tuple[str, int], ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "readout_id",
    )

    def __post_init__(self) -> None:
        for fname in self.__dataclass_fields__.keys():
            if fname in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES:
                raise ValueError(
                    f"dataclass field {fname!r} is in the "
                    "v1.24.0 forbidden field-name set"
                )
        for name in self.REQUIRED_STRING_FIELDS:
            _validate_required_string(
                getattr(self, name), field_name=name
            )
        for name in (
            "annotation_ids",
            "cited_record_ids",
            "unresolved_cited_record_ids",
        ):
            object.__setattr__(
                self,
                name,
                _validate_string_tuple(
                    getattr(self, name), field_name=name
                ),
            )
        for name in (
            "annotation_label_counts",
            "annotations_by_scope",
            "reviewer_role_counts",
        ):
            object.__setattr__(
                self,
                name,
                _validate_count_pair_tuple(
                    getattr(self, name), field_name=name
                ),
            )
        warnings = tuple(self.warnings)
        for entry in warnings:
            if not isinstance(entry, str) or not entry:
                raise ValueError(
                    "warnings entries must be non-empty "
                    "strings"
                )
        object.__setattr__(self, "warnings", warnings)
        metadata_dict = dict(self.metadata)
        _scan_for_forbidden_keys(
            metadata_dict, field_name="metadata"
        )
        object.__setattr__(self, "metadata", metadata_dict)

    @property
    def annotation_count(self) -> int:
        return len(self.annotation_ids)

    @property
    def cited_record_count(self) -> int:
        return len(self.cited_record_ids)

    @property
    def unresolved_cited_record_count(self) -> int:
        return len(self.unresolved_cited_record_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "readout_id": self.readout_id,
            "annotation_ids": list(self.annotation_ids),
            "cited_record_ids": list(self.cited_record_ids),
            "annotation_label_counts": [
                list(p) for p in self.annotation_label_counts
            ],
            "annotations_by_scope": [
                list(p) for p in self.annotations_by_scope
            ],
            "unresolved_cited_record_ids": list(
                self.unresolved_cited_record_ids
            ),
            "reviewer_role_counts": [
                list(p) for p in self.reviewer_role_counts
            ],
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# build_manual_annotation_readout — read-only helper
# ---------------------------------------------------------------------------


def _ordered_count_pairs(
    items: Iterable[str],
) -> tuple[tuple[str, int], ...]:
    """Build a (label, count) pair tuple preserving the
    order of first occurrence. Used by every v1.24.2
    multiset count surface."""
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return tuple(counts.items())


def _ordered_unique(
    items: Iterable[str],
) -> tuple[str, ...]:
    """De-duplicate a stream of strings preserving the
    order of first occurrence."""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return tuple(out)


def _filter_annotations(
    annotations: tuple[ManualAnnotationRecord, ...],
    *,
    annotation_ids: tuple[str, ...],
    case_study_id: str | None,
) -> tuple[ManualAnnotationRecord, ...]:
    selected = annotations
    if annotation_ids:
        wanted = set(annotation_ids)
        selected = tuple(
            a for a in selected if a.annotation_id in wanted
        )
    if case_study_id is not None:
        selected = tuple(
            a
            for a in selected
            if a.case_study_id == case_study_id
        )
    return selected


def build_manual_annotation_readout(
    kernel: "WorldKernel",
    *,
    annotation_ids: Iterable[str] = (),
    case_study_id: str | None = None,
    readout_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ManualAnnotationReadout:
    """Build a deterministic read-only readout over the
    kernel's :class:`ManualAnnotationBook`.

    Read-only discipline (binding):

    - Does NOT call
      :func:`world.stress_applications.apply_stress_program`,
      :func:`world.scenario_applications.apply_scenario_driver`,
      or
      :meth:`world.manual_annotations.ManualAnnotationBook.add_annotation`.
    - Does NOT mutate any kernel book.
    - Does NOT emit a ledger record (v1.24.2 ships no new
      :class:`world.ledger.RecordType`).

    Same kernel state + same arguments → byte-identical
    readout.
    """
    book = getattr(kernel, "manual_annotations", None)
    if book is None:
        all_annotations: tuple[ManualAnnotationRecord, ...] = ()
    else:
        all_annotations = book.list_annotations()

    selected = _filter_annotations(
        all_annotations,
        annotation_ids=tuple(annotation_ids),
        case_study_id=case_study_id,
    )

    annotation_id_list = tuple(
        a.annotation_id for a in selected
    )
    cited_id_list = _ordered_unique(
        cid for a in selected for cid in a.cited_record_ids
    )

    label_counts = _ordered_count_pairs(
        a.annotation_label for a in selected
    )
    scope_counts = _ordered_count_pairs(
        a.annotation_scope_label for a in selected
    )
    role_counts = _ordered_count_pairs(
        a.reviewer_role_label for a in selected
    )

    unresolved: list[str] = []
    unknown_prefix: list[str] = []
    for cid in cited_id_list:
        cls = _classify_citation_resolution(kernel, cid)
        if cls == "unresolved":
            unresolved.append(cid)
        elif cls == "unknown_prefix":
            unknown_prefix.append(cid)

    warnings: list[str] = []
    if unresolved:
        warnings.append(
            f"{len(unresolved)} cited record id(s) do not "
            "resolve to an extant kernel record"
        )
    if unknown_prefix:
        warnings.append(
            f"{len(unknown_prefix)} cited record id(s) "
            "carry an unrecognised plain-id prefix"
        )

    if readout_id is None:
        if case_study_id:
            readout_id = (
                f"manual_annotation_readout:{case_study_id}"
            )
        else:
            readout_id = "manual_annotation_readout:default"

    caller_metadata = dict(metadata or {})
    _scan_for_forbidden_keys(
        caller_metadata, field_name="metadata"
    )

    # unresolved_cited_record_ids = unresolved + unknown
    # prefix in original order. The reviewer cares about
    # "did my citation resolve?"; the closed-set
    # diagnostic distinction is preserved in warnings.
    unresolved_cited = tuple(
        cid
        for cid in cited_id_list
        if cid in unresolved or cid in unknown_prefix
    )

    return ManualAnnotationReadout(
        readout_id=readout_id,
        annotation_ids=annotation_id_list,
        cited_record_ids=cited_id_list,
        annotation_label_counts=label_counts,
        annotations_by_scope=scope_counts,
        unresolved_cited_record_ids=unresolved_cited,
        reviewer_role_counts=role_counts,
        warnings=tuple(warnings),
        metadata=caller_metadata,
    )


# ---------------------------------------------------------------------------
# render_manual_annotation_readout_markdown
# ---------------------------------------------------------------------------


def render_manual_annotation_readout_markdown(
    readout: ManualAnnotationReadout,
) -> str:
    """Deterministic markdown rendering of a
    :class:`ManualAnnotationReadout`. Same readout → same
    bytes.

    The renderer emits 8 sections in this order:

    1. ``## Manual annotation readout`` — readout id +
       annotation count.
    2. ``## Annotation labels`` — closed-set label
       multiset count list.
    3. ``## Annotation scopes`` — closed-set scope
       multiset count list.
    4. ``## Cited records`` — plain-id list of cited
       records in insertion order.
    5. ``## Unresolved citations`` — plain-id list of
       unresolved cited records.
    6. ``## Reviewer roles`` — closed-set reviewer-role
       multiset count list.
    7. ``## Warnings`` — human-readable warning list.
    8. ``## Boundary statement`` — pinned anti-claim
       block.

    The renderer emits no ``impact`` / ``outcome`` /
    ``risk score`` / ``forecast`` / ``prediction`` /
    ``recommendation`` / ``causal effect`` / ``amplification`` /
    ``dampening`` / ``offset effect`` / ``dominant`` /
    ``net`` / ``composite`` text outside the boundary
    statement section. Pinned by
    ``test_markdown_has_no_forbidden_wording``.
    """
    if not isinstance(readout, ManualAnnotationReadout):
        raise TypeError(
            "readout must be a ManualAnnotationReadout; "
            f"got {type(readout).__name__}"
        )

    out: list[str] = []
    out.append(
        f"# Manual annotation readout — {readout.readout_id}"
    )
    out.append("")

    # 1. Header / counts.
    out.append("## Manual annotation readout")
    out.append("")
    out.append(
        f"- **Readout id**: `{readout.readout_id}`"
    )
    out.append(
        f"- **Annotation count**: "
        f"{readout.annotation_count}"
    )
    out.append(
        f"- **Cited record count**: "
        f"{readout.cited_record_count}"
    )
    out.append(
        f"- **Unresolved cited record count**: "
        f"{readout.unresolved_cited_record_count}"
    )
    out.append("")

    # 2. Annotation labels.
    out.append("## Annotation labels")
    out.append("")
    if not readout.annotation_label_counts:
        out.append("- (none)")
    else:
        for label, count in readout.annotation_label_counts:
            out.append(
                f"- `{label}`: {count}"
            )
    out.append("")

    # 3. Annotation scopes.
    out.append("## Annotation scopes")
    out.append("")
    if not readout.annotations_by_scope:
        out.append("- (none)")
    else:
        for scope, count in readout.annotations_by_scope:
            out.append(
                f"- `{scope}`: {count}"
            )
    out.append("")

    # 4. Cited records.
    out.append("## Cited records")
    out.append("")
    if not readout.cited_record_ids:
        out.append("- (none)")
    else:
        for cid in readout.cited_record_ids:
            out.append(f"- `{cid}`")
    out.append("")

    # 5. Unresolved citations.
    out.append("## Unresolved citations")
    out.append("")
    if not readout.unresolved_cited_record_ids:
        out.append("- (none)")
    else:
        for cid in readout.unresolved_cited_record_ids:
            out.append(f"- `{cid}`")
    out.append("")

    # 6. Reviewer roles.
    out.append("## Reviewer roles")
    out.append("")
    if not readout.reviewer_role_counts:
        out.append("- (none)")
    else:
        for role, count in readout.reviewer_role_counts:
            out.append(
                f"- `{role}`: {count}"
            )
    out.append("")

    # 7. Warnings.
    out.append("## Warnings")
    out.append("")
    if not readout.warnings:
        out.append("- (none)")
    else:
        for w in readout.warnings:
            out.append(f"- {w}")
    out.append("")

    # 8. Boundary statement.
    out.append("## Boundary statement")
    out.append("")
    out.append("".join(_BOUNDARY_STATEMENT_LINES))
    out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------------------
# v1.23.2 validation hook (optional / non-mandatory)
# ---------------------------------------------------------------------------


def build_manual_annotation_validation_hook_summary(
    kernel: "WorldKernel",
) -> dict[str, int]:
    """Optional validation-hook summary that the v1.23.2
    validation report (or a v1.23.3 case-study report)
    can call when a manual-annotation book is present.

    Returns a small dict with two keys:

    - ``manual_annotation_count`` — total number of
      annotations in the kernel's book.
    - ``unresolved_annotation_citation_count`` — total
      number of unresolved cited record ids across all
      annotations.

    The hook is **non-mandatory**: a kernel without an
    annotation book returns ``{"manual_annotation_count":
    0, "unresolved_annotation_citation_count": 0}``. The
    hook never modifies the v1.23.2 validation report
    shape; it returns a separate dict the caller can
    embed under a non-required key.

    Read-only / no ledger emission / no kernel mutation.
    """
    readout = build_manual_annotation_readout(kernel)
    return {
        "manual_annotation_count": readout.annotation_count,
        "unresolved_annotation_citation_count": (
            readout.unresolved_cited_record_count
        ),
    }


# Re-export the closed-set vocabularies in case a downstream
# consumer wants to whitelist against them.
__all__ = (
    "ANNOTATION_LABELS",
    "ANNOTATION_SCOPE_LABELS",
    "ManualAnnotationReadout",
    "REVIEWER_ROLE_LABELS",
    "build_manual_annotation_readout",
    "build_manual_annotation_validation_hook_summary",
    "render_manual_annotation_readout_markdown",
)
