"""
v1.24.1 — Manual annotation interaction layer storage.

Storage-only foundation for the v1.24 Manual Annotation
Layer (per [`docs/v1_24_manual_annotation_layer.md`](../docs/v1_24_manual_annotation_layer.md)).
v1.24.1 ships one immutable frozen dataclass
(:class:`ManualAnnotationRecord`), one append-only
:class:`ManualAnnotationBook`, and the v1.24.0 closed-set
vocabularies — and nothing else. Read-only readout
(v1.24.2), export (v1.24.3), and freeze (v1.24.last) are
strictly later sub-milestones.

Critical design constraints carried verbatim from the
v1.24.0 design pin (binding):

- **Human-authored only.** Every record carries
  ``source_kind = "human"`` and
  ``reasoning_mode = "human_authored"``. The
  :data:`SOURCE_KIND_LABELS` and
  :data:`REASONING_MODE_LABELS` closed sets contain
  exactly one element each at v1.24; expanding either
  requires a fresh design pin.
- **Append-only.** No annotation ever mutates a prior
  annotation. A reviewer who wants to revise an
  annotation appends a new annotation citing the prior
  one (with ``annotation_label =
  "reviewer_disagreement_placeholder"`` if the
  disagreement is the point); the original stays in
  the book.
- **Read-only with respect to the world.** The book
  emits **exactly one ledger record** per successful
  ``add_annotation(...)`` call (a single
  :data:`world.ledger.RecordType.MANUAL_ANNOTATION_RECORDED`
  event). It mutates **no other source-of-truth book**;
  pre-existing kernel-book snapshots remain byte-
  identical pre / post call.
- **No automatic annotation entry point.** The book
  exposes :meth:`ManualAnnotationBook.add_annotation`
  only. There is **no** ``auto_annotate(...)``,
  ``infer_interaction(...)``,
  ``classify_review_frame(...)``,
  or ``propose_annotation(...)`` helper.
- **No interaction inference.** The
  :data:`ANNOTATION_LABELS` closed set explicitly does
  **not** contain ``amplify`` / ``dampen`` / ``offset``
  / ``coexist``. The
  :data:`world.forbidden_tokens.FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES`
  composed set forbids these tokens at every payload
  surface.
- **Empty by default on the kernel.** The
  ``WorldKernel.manual_annotations`` field is wired
  with ``field(default_factory=ManualAnnotationBook)``;
  an empty book emits no ledger record, leaving every
  v1.21.last canonical ``living_world_digest`` byte-
  identical at v1.24.x:

  - ``quarterly_default`` —
    ``f93bdf3f4203c20d4a58e956160b0bb1004dcdecf0648a92cc961401b705897c``
  - ``monthly_reference`` —
    ``75a91cfa35cbbc29d321ffab045eb07ce4d2ba77dc4514a009bb4e596c91879d``
  - ``scenario_monthly_reference_universe`` test-fixture
    — ``5003fdfaa45d5b5212130b1158729c692616cf2a8df9b425b226baef15566eb6``
  - v1.20.4 CLI bundle —
    ``ec37715b8b5532841311bbf14d087cf4dcca731a9dc5de3b2868f32700731aaf``

The module is **runtime-book-free** beyond the v0/v1
ledger + clock convention shared by every other storage
book. It does not import any source-of-truth book on the
engine side, does not call the v1.18.2 / v1.21.x apply
helpers, and does not register itself with the v1.16.x
closed-loop attention path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.forbidden_tokens import (
    FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES,
)
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Closed-set vocabularies (binding for v1.24.1; expanding any
# of these closed sets requires a fresh v1.24.x.x design pin).
# ---------------------------------------------------------------------------


# v1.24.0 — annotation scope is the *kind of record* the
# reviewer is annotating. The closed set is intentionally
# small.
ANNOTATION_SCOPE_LABELS: frozenset[str] = frozenset(
    {
        "stress_readout",
        "stress_program_application",
        "scenario_context_shift",
        "validation_report",
        "case_study",
        "citation_graph",
        "unknown",
    }
)


# v1.24.0 — annotation label is the *reviewer's
# observation*. The set explicitly excludes ``amplify`` /
# ``dampen`` / ``offset`` / ``coexist`` and every
# v1.18.0 / v1.19.0 / v1.21.0a / v1.22.0 forbidden token.
ANNOTATION_LABELS: frozenset[str] = frozenset(
    {
        "same_review_frame",
        "shared_context_surface",
        "uncited_stress_candidate",
        "partial_application_note",
        "citation_gap_note",
        "needs_followup_review",
        "reviewer_disagreement_placeholder",
        "unknown",
    }
)


# v1.24.0 — source-kind closed singleton. v1.24.x records
# are human-authored only.
SOURCE_KIND_LABELS: frozenset[str] = frozenset({"human"})
MANUAL_ANNOTATION_SOURCE_KIND: str = "human"


# v1.24.0 — reasoning-mode closed singleton. v1.24.x
# records are human_authored only; future LLM-mode
# extension requires a fresh design pin.
REASONING_MODE_LABELS: frozenset[str] = frozenset(
    {"human_authored"}
)
MANUAL_ANNOTATION_REASONING_MODE: str = "human_authored"


# v1.24.1 — reviewer-role closed set. ``unknown`` exists so
# a reviewer who declines to self-identify can still
# annotate.
REVIEWER_ROLE_LABELS: frozenset[str] = frozenset(
    {
        "reviewer",
        "analyst",
        "researcher",
        "auditor",
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


VISIBILITY_LABELS: frozenset[str] = frozenset(
    {
        "public",
        "restricted",
        "internal",
        "private",
        "unknown",
    }
)


# ---------------------------------------------------------------------------
# Default boundary flags (binding per v1.24.0 design §14).
#
# Every emitted ``ManualAnnotationRecord`` carries these
# flags. Callers may add additional ``True`` flags but
# **cannot** override any default to ``False``.
# ---------------------------------------------------------------------------


_DEFAULT_BOUNDARY_FLAGS_TUPLE: tuple[tuple[str, bool], ...] = (
    # v1.18.0 boundary
    ("no_actor_decision", True),
    ("no_llm_execution", True),
    ("no_price_formation", True),
    ("no_trading", True),
    ("no_financing_execution", True),
    ("no_investment_advice", True),
    ("synthetic_only", True),
    # v1.21.0a additions (re-pinned at v1.24.0)
    ("no_aggregate_stress_result", True),
    ("no_interaction_inference", True),
    ("no_field_value_claim", True),
    ("no_field_magnitude_claim", True),
    # v1.24.0 additions (manual-annotation specific)
    ("human_authored_only", True),
    ("no_auto_annotation", True),
    ("no_causal_proof", True),
    ("descriptive_only", True),
)


def _default_boundary_flags() -> dict[str, bool]:
    return dict(_DEFAULT_BOUNDARY_FLAGS_TUPLE)


_DEFAULT_BOUNDARY_FLAG_KEYS: frozenset[str] = frozenset(
    k for k, _ in _DEFAULT_BOUNDARY_FLAGS_TUPLE
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ManualAnnotationError(Exception):
    """Base class for v1.24.1 manual-annotation storage
    errors."""


class DuplicateManualAnnotationError(ManualAnnotationError):
    """Raised when an ``annotation_id`` is added twice."""


class UnknownManualAnnotationError(
    ManualAnnotationError, KeyError
):
    """Raised when an ``annotation_id`` is not found."""


# ---------------------------------------------------------------------------
# Small validation helpers (mirror the v1.21.x discipline).
# ---------------------------------------------------------------------------


def _validate_required_string(
    value: Any, *, field_name: str
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{field_name} must be a non-empty string"
        )
    return value


def _validate_optional_string(
    value: Any, *, field_name: str
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{field_name}, when present, must be a "
            "non-empty string"
        )
    return value


def _validate_label(
    value: Any, allowed: frozenset[str], *, field_name: str
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{field_name} must be a non-empty string"
        )
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {sorted(allowed)!r}; "
            f"got {value!r}"
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


def _scan_for_forbidden_keys(
    mapping: Mapping[str, Any], *, field_name: str
) -> None:
    """Reject any v1.24.0 forbidden-name token appearing
    as a key in a metadata or payload mapping."""
    for key in mapping.keys():
        if not isinstance(key, str):
            continue
        if key in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES:
            raise ValueError(
                f"{field_name} contains forbidden key "
                f"{key!r} (v1.24.0 manual-annotation "
                "boundary — annotations do not carry "
                "actor-decision / price / forecast / "
                "advice / real-data / Japan-calibration / "
                "LLM / interaction / aggregate / "
                "auto-annotation tokens)"
            )


def _scan_note_text_for_forbidden_tokens(
    text: str, *, field_name: str = "note_text"
) -> None:
    """Reject any v1.24.0 forbidden token appearing as a
    whole word (case-insensitive) in optional human-
    readable ``note_text``. ``note_text`` is descriptive
    only; never source-of-truth.

    Whitespace inside the input is normalised to ``_``
    before scanning so reviewer prose written with spaces
    (e.g. ``"investment advice"``) still matches the
    underscore-form forbidden token (``"investment_advice"``).
    The original text is preserved for storage; the
    normalised form is only used for the scan."""
    lower = text.lower()
    # Collapse runs of whitespace into a single ``_`` so a
    # multi-word phrase like ``"expected return"`` matches
    # the forbidden token ``"expected_return"``.
    normalised = re.sub(r"\s+", "_", lower)
    for token in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES:
        pattern = rf"\b{re.escape(token.lower())}\b"
        if (
            re.search(pattern, lower)
            or re.search(pattern, normalised)
        ):
            raise ValueError(
                f"{field_name} contains forbidden token "
                f"{token!r} (v1.24.0 manual-annotation "
                "boundary — note_text is descriptive only "
                "and may not carry actor-decision / price "
                "/ forecast / advice / real-data / "
                "interaction / aggregate / "
                "auto-annotation wording)"
            )


def _scan_label_value_for_forbidden_tokens(
    value: str, *, field_name: str
) -> None:
    """Reject any annotation label / scope value whose
    text contains a forbidden token. The closed-set
    membership check already rules out
    ``ANNOTATION_LABELS`` /
    ``ANNOTATION_SCOPE_LABELS`` content; this scan is a
    belt-and-braces guard against future closed-set
    extensions that accidentally introduce a forbidden
    token."""
    if value in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES:
        raise ValueError(
            f"{field_name} value {value!r} is in the "
            "v1.24.0 manual-annotation forbidden-name "
            "set"
        )


# ---------------------------------------------------------------------------
# ManualAnnotationRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualAnnotationRecord:
    """Immutable, append-only manual annotation over an
    existing citation-graph record id.

    Cardinality:

    - One record per ``add_annotation(...)`` call.
    - ``cited_record_ids`` is a non-empty tuple of
      plain-id citations to existing records (v1.21.3
      readouts, v1.21.2 program applications, v1.18.2
      scenario applications + context shifts, v1.23.3
      case-study reports, the reserved
      ``validation_report:`` plain-id format). The
      storage layer does **not** dereference these
      citations; the v1.24.2 readout surfaces unresolved
      citations separately.

    The record carries no ``causal_effect`` /
    ``impact_score`` / ``risk_score`` /
    ``forecast`` / ``prediction`` / ``recommendation``
    field, label, or value. The v1.24.0 forbidden-token
    boundary is scanned at construction time via the
    dataclass field-name guard + the metadata-key scan +
    the optional ``note_text`` scan + the label-value
    scan.
    """

    annotation_id: str
    annotation_scope_label: str
    annotation_label: str
    cited_record_ids: tuple[str, ...]
    reviewer_role_label: str = "unknown"
    source_kind: str = MANUAL_ANNOTATION_SOURCE_KIND
    reasoning_mode: str = MANUAL_ANNOTATION_REASONING_MODE
    case_study_id: str | None = None
    created_for_record_id: str | None = None
    note_text: str | None = None
    status: str = "active"
    visibility: str = "internal"
    boundary_flags: Mapping[str, bool] = field(
        default_factory=_default_boundary_flags
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "annotation_id",
        "annotation_scope_label",
        "annotation_label",
        "reviewer_role_label",
        "source_kind",
        "reasoning_mode",
        "status",
        "visibility",
    )

    LABEL_FIELDS: ClassVar[
        tuple[tuple[str, frozenset[str]], ...]
    ] = (
        ("annotation_scope_label", ANNOTATION_SCOPE_LABELS),
        ("annotation_label",       ANNOTATION_LABELS),
        ("reviewer_role_label",    REVIEWER_ROLE_LABELS),
        ("source_kind",            SOURCE_KIND_LABELS),
        ("reasoning_mode",         REASONING_MODE_LABELS),
        ("status",                 STATUS_LABELS),
        ("visibility",             VISIBILITY_LABELS),
    )

    def __post_init__(self) -> None:
        # Trip-wire: a future field rename must not collide
        # with the v1.24.0 forbidden list.
        for fname in self.__dataclass_fields__.keys():
            if fname in FORBIDDEN_MANUAL_ANNOTATION_FIELD_NAMES:
                raise ValueError(
                    f"dataclass field {fname!r} is in the "
                    "v1.24.0 manual-annotation forbidden "
                    "field-name set"
                )
        for name in self.REQUIRED_STRING_FIELDS:
            _validate_required_string(
                getattr(self, name), field_name=name
            )
        for name, allowed in self.LABEL_FIELDS:
            _validate_label(
                getattr(self, name), allowed, field_name=name
            )
        # Belt-and-braces: scan label values against the
        # forbidden set even though the closed-set
        # membership check above already rules out
        # forbidden content from the pinned closed sets.
        for name, _ in self.LABEL_FIELDS:
            _scan_label_value_for_forbidden_tokens(
                getattr(self, name), field_name=name
            )
        # cited_record_ids — non-empty tuple of non-empty
        # strings.
        cited = _validate_string_tuple(
            self.cited_record_ids,
            field_name="cited_record_ids",
        )
        if not cited:
            raise ValueError(
                "cited_record_ids must contain at least "
                "one plain-id citation"
            )
        object.__setattr__(self, "cited_record_ids", cited)
        # Optional plain-id fields.
        object.__setattr__(
            self,
            "case_study_id",
            _validate_optional_string(
                self.case_study_id,
                field_name="case_study_id",
            ),
        )
        object.__setattr__(
            self,
            "created_for_record_id",
            _validate_optional_string(
                self.created_for_record_id,
                field_name="created_for_record_id",
            ),
        )
        # Optional note_text — descriptive only; scanned
        # for forbidden tokens at construction.
        if self.note_text is not None:
            if (
                not isinstance(self.note_text, str)
                or not self.note_text
            ):
                raise ValueError(
                    "note_text, when present, must be a "
                    "non-empty string"
                )
            _scan_note_text_for_forbidden_tokens(
                self.note_text, field_name="note_text"
            )
        # boundary_flags — accept a mapping of
        # (str -> bool); reject any default override to
        # False; reject forbidden keys.
        bf = dict(self.boundary_flags)
        for key, val in bf.items():
            if not isinstance(key, str) or not key:
                raise ValueError(
                    "boundary_flags keys must be "
                    "non-empty strings"
                )
            if not isinstance(val, bool):
                raise ValueError(
                    f"boundary_flags[{key!r}] must be "
                    f"bool; got {type(val).__name__}"
                )
        for default_key, default_val in _DEFAULT_BOUNDARY_FLAGS_TUPLE:
            if default_key in bf and bf[default_key] != default_val:
                raise ValueError(
                    f"boundary_flags[{default_key!r}] "
                    "is a v1.24.0 default; cannot be "
                    "overridden to "
                    f"{bf[default_key]!r}"
                )
            # Force the default value if missing.
            bf.setdefault(default_key, default_val)
        _scan_for_forbidden_keys(
            bf, field_name="boundary_flags"
        )
        object.__setattr__(self, "boundary_flags", bf)
        # metadata — opaque, scanned for forbidden keys.
        metadata_dict = dict(self.metadata)
        _scan_for_forbidden_keys(
            metadata_dict, field_name="metadata"
        )
        object.__setattr__(self, "metadata", metadata_dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "annotation_id": self.annotation_id,
            "annotation_scope_label": (
                self.annotation_scope_label
            ),
            "annotation_label": self.annotation_label,
            "cited_record_ids": list(self.cited_record_ids),
            "reviewer_role_label": (
                self.reviewer_role_label
            ),
            "source_kind": self.source_kind,
            "reasoning_mode": self.reasoning_mode,
            "case_study_id": self.case_study_id,
            "created_for_record_id": (
                self.created_for_record_id
            ),
            "note_text": self.note_text,
            "status": self.status,
            "visibility": self.visibility,
            "boundary_flags": dict(self.boundary_flags),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# ManualAnnotationBook
# ---------------------------------------------------------------------------


@dataclass
class ManualAnnotationBook:
    """Append-only storage for v1.24.1
    :class:`ManualAnnotationRecord` instances.

    Mirrors the v1.18.1 / v1.19.3 / v1.20.1 / v1.20.2 /
    v1.21.1 / v1.21.2 storage-book convention: emits
    **exactly one ledger record** per successful
    ``add_annotation(...)`` call (a single
    :data:`world.ledger.RecordType.MANUAL_ANNOTATION_RECORDED`
    event), no extra ledger record on duplicate id,
    mutates no other source-of-truth book.

    **No automatic annotation entry point.** The book
    exposes ``add_annotation(record)`` only. There is no
    helper that auto-fills, infers, classifies, or
    proposes annotations.

    Empty by default on the kernel — pinned by
    ``test_world_kernel_manual_annotations_empty_by_default``
    + the digest trip-wires.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _annotations: dict[str, ManualAnnotationRecord] = field(
        default_factory=dict
    )

    def _now(self) -> datetime:
        if self.clock is not None:
            try:
                return self.clock.current_datetime()
            except Exception:
                pass
        return datetime.now(timezone.utc)

    def add_annotation(
        self,
        annotation: ManualAnnotationRecord,
        *,
        simulation_date: Any = None,
    ) -> ManualAnnotationRecord:
        if not isinstance(annotation, ManualAnnotationRecord):
            raise TypeError(
                "annotation must be a "
                "ManualAnnotationRecord instance"
            )
        if annotation.annotation_id in self._annotations:
            raise DuplicateManualAnnotationError(
                "Duplicate annotation_id: "
                f"{annotation.annotation_id!r}"
            )
        self._annotations[annotation.annotation_id] = (
            annotation
        )

        if self.ledger is not None:
            payload: dict[str, Any] = {
                "annotation_id": annotation.annotation_id,
                "annotation_scope_label": (
                    annotation.annotation_scope_label
                ),
                "annotation_label": (
                    annotation.annotation_label
                ),
                "cited_record_ids": list(
                    annotation.cited_record_ids
                ),
                "reviewer_role_label": (
                    annotation.reviewer_role_label
                ),
                "source_kind": annotation.source_kind,
                "reasoning_mode": (
                    annotation.reasoning_mode
                ),
                "case_study_id": annotation.case_study_id,
                "created_for_record_id": (
                    annotation.created_for_record_id
                ),
                # ``note_text`` is intentionally NOT
                # included in the ledger payload to
                # keep the audit surface
                # descriptive-only and to avoid
                # writing free-form text into the
                # source-of-truth ledger. v1.24.3
                # may surface it through an export-
                # side renderer with stricter
                # display discipline.
                "status": annotation.status,
                "visibility": annotation.visibility,
                "boundary_flags": dict(
                    annotation.boundary_flags
                ),
            }
            _scan_for_forbidden_keys(
                payload, field_name="ledger payload"
            )
            sim_date: Any = (
                simulation_date
                if simulation_date is not None
                else self._now()
            )
            self.ledger.append(
                event_type="manual_annotation_recorded",
                simulation_date=sim_date,
                object_id=annotation.annotation_id,
                source=annotation.reviewer_role_label,
                payload=payload,
                space_id="manual_annotations",
                visibility=annotation.visibility,
            )
        return annotation

    def get_annotation(
        self, annotation_id: str
    ) -> ManualAnnotationRecord:
        try:
            return self._annotations[annotation_id]
        except KeyError as exc:
            raise UnknownManualAnnotationError(
                "manual_annotation not found: "
                f"{annotation_id!r}"
            ) from exc

    def list_annotations(
        self,
    ) -> tuple[ManualAnnotationRecord, ...]:
        return tuple(self._annotations.values())

    def list_by_scope(
        self, annotation_scope_label: str
    ) -> tuple[ManualAnnotationRecord, ...]:
        return tuple(
            a
            for a in self._annotations.values()
            if a.annotation_scope_label
            == annotation_scope_label
        )

    def list_by_label(
        self, annotation_label: str
    ) -> tuple[ManualAnnotationRecord, ...]:
        return tuple(
            a
            for a in self._annotations.values()
            if a.annotation_label == annotation_label
        )

    def list_by_case_study(
        self, case_study_id: str
    ) -> tuple[ManualAnnotationRecord, ...]:
        return tuple(
            a
            for a in self._annotations.values()
            if a.case_study_id == case_study_id
        )

    def list_by_cited_record(
        self, cited_record_id: str
    ) -> tuple[ManualAnnotationRecord, ...]:
        return tuple(
            a
            for a in self._annotations.values()
            if cited_record_id in a.cited_record_ids
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "manual_annotations": [
                a.to_dict()
                for a in self._annotations.values()
            ],
        }


__all__ = [
    "ANNOTATION_LABELS",
    "ANNOTATION_SCOPE_LABELS",
    "DuplicateManualAnnotationError",
    "MANUAL_ANNOTATION_REASONING_MODE",
    "MANUAL_ANNOTATION_SOURCE_KIND",
    "ManualAnnotationBook",
    "ManualAnnotationError",
    "ManualAnnotationRecord",
    "REASONING_MODE_LABELS",
    "REVIEWER_ROLE_LABELS",
    "SOURCE_KIND_LABELS",
    "STATUS_LABELS",
    "UnknownManualAnnotationError",
    "VISIBILITY_LABELS",
]
