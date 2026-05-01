"""
v1.8.15 Ledger trace report.

A read-only reporting layer over the v1.8.14 endogenous chain.
Turns the slice of ``kernel.ledger.records`` produced during a
``run_reference_endogenous_chain`` call into:

- a deterministic, immutable :class:`LedgerTraceReport`,
- a deterministic dict via :meth:`LedgerTraceReport.to_dict`, and
- a deterministic compact Markdown rendering via
  :func:`render_endogenous_chain_markdown`.

The report exists for **explainability and demo presentation**,
not for new modeling. v1.8.15 introduces no new ledger types,
no new economic behavior, no new routines, no scheduler changes,
and no kernel mutation. The reporter walks the ledger slice
already populated by v1.8.14 component helpers and packages it
into a shape that humans and downstream consumers can read.

What v1.8.15 deliberately does NOT do
-------------------------------------

- No price formation, trading, lending decisions, valuation
  refresh, impact estimation, sensitivity calculation, DSCR / LTV
  updates, covenant enforcement, corporate actions, policy
  reactions, scenario engines.
- No new ledger writes. The reporter does not call ``add_*`` on
  any book and does not ``append`` to the ledger.
- No new RecordTypes. Counts and bucketing reuse the seven event
  types the chain already emits.
- No real Japan calibration; no real data ingestion.

What the reporter buys you
--------------------------

A single ``build_endogenous_chain_report(kernel, chain_result)``
call gives you:

- An ordered tuple of every record id the chain produced, plus
  the matching event types.
- A breakdown by record type (so you can sanity-check that you
  got the expected one corporate run / two menus / two
  selections / two review runs / three signals at a glance).
- Bucketed ids (routine runs / signals / menus / selections)
  ready to be looked up against `kernel.routines` /
  `kernel.signals` / `kernel.attention`.
- The v1.8.12 set differences (``investor_only`` /
  ``bank_only`` / ``shared``) carried forward verbatim.
- A ``warnings`` tuple naming any cross-check that did not pass:
  for instance, a chain result whose ``created_record_ids`` do
  not match the ledger slice (someone pushed extra records
  while the chain was running, or trimmed the ledger after the
  fact). Warnings are *informative*, not fatal — the report
  still builds so the caller can decide what to do.

Determinism
-----------

For a given (kernel, chain_result) pair, the report (and its
``to_dict`` / Markdown projections) is byte-identical across
fresh process invocations. Counts are sorted by event type;
ordered ids reflect ledger order; the Markdown layout is fixed.
v1.8.15 does not consult the wall clock and does not introduce
any hashing dependencies that v1.7's manifest tests would care
about.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from world.ledger import RecordType
from world.reference_chain import EndogenousChainResult


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_DEFAULT_CHAIN_NAME: str = "reference_endogenous_chain"

# The seven event types the v1.8.14 chain emits when run on a
# kernel. Used by the validation pass to flag missing components
# without crashing — the report still builds for partial chains.
_EXPECTED_CHAIN_EVENT_TYPES: tuple[str, ...] = (
    RecordType.INTERACTION_ADDED.value,
    RecordType.ROUTINE_ADDED.value,
    RecordType.ROUTINE_RUN_RECORDED.value,
    RecordType.SIGNAL_ADDED.value,
    RecordType.ATTENTION_PROFILE_ADDED.value,
    RecordType.OBSERVATION_MENU_CREATED.value,
    RecordType.OBSERVATION_SET_SELECTED.value,
)


# ---------------------------------------------------------------------------
# Report record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerTraceReport:
    """
    Immutable summary of one endogenous-chain ledger slice.

    Field semantics
    ---------------
    - ``report_id`` is a stable id derived from the chain. Default
      is ``"report:" + chain_name + ":" + as_of_date`` when the
      caller does not override; uniqueness is the caller's
      responsibility.
    - ``chain_name`` is a human label (default
      ``"reference_endogenous_chain"``). Free-form.
    - ``start_record_index`` / ``end_record_index`` mirror the
      chain result's ledger counts so the original slice can be
      re-walked at any time.
    - ``record_count`` is ``end_record_index - start_record_index``
      and is also the length of every ordered tuple below.
    - ``record_type_counts`` is a sorted tuple of
      ``(event_type, count)`` pairs covering every event type the
      slice contains. The pairs are sorted by event type for
      determinism.
    - ``ordered_record_ids`` and ``ordered_record_types`` are the
      ledger slice projected to ``object_id`` and
      ``record_type.value`` respectively, preserving order. They
      are pairwise: ``ordered_record_ids[i]`` was emitted with
      ``ordered_record_types[i]``.
    - ``routine_run_ids`` / ``signal_ids`` / ``menu_ids`` /
      ``selection_ids`` bucket the ordered ids by role for
      convenience. Each tuple preserves ledger order.
    - The ``*_selected_refs`` fields are carried forward
      verbatim from the chain result so a downstream consumer
      reading the report alone can see what each actor selected.
    - ``warnings`` is a tuple of free-form strings naming
      validation issues (slice / chain mismatch, count mismatch,
      missing expected event type, etc.). v1.8.15 chooses warning
      semantics over hard failure so a caller can still read the
      report and decide what to do.
    - ``metadata`` is free-form. Suggested keys: ``"renderer"``,
      ``"format_version"``, ``"chain_status"``.
    """

    report_id: str
    chain_name: str
    start_record_index: int
    end_record_index: int
    record_count: int
    record_type_counts: tuple[tuple[str, int], ...]
    ordered_record_ids: tuple[str, ...]
    ordered_record_types: tuple[str, ...]
    routine_run_ids: tuple[str, ...]
    signal_ids: tuple[str, ...]
    menu_ids: tuple[str, ...]
    selection_ids: tuple[str, ...]
    investor_selected_refs: tuple[str, ...] = field(default_factory=tuple)
    bank_selected_refs: tuple[str, ...] = field(default_factory=tuple)
    shared_selected_refs: tuple[str, ...] = field(default_factory=tuple)
    investor_only_refs: tuple[str, ...] = field(default_factory=tuple)
    bank_only_refs: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.report_id, str) or not self.report_id:
            raise ValueError("report_id must be a non-empty string")
        if not isinstance(self.chain_name, str) or not self.chain_name:
            raise ValueError("chain_name must be a non-empty string")
        if self.start_record_index < 0:
            raise ValueError("start_record_index must be >= 0")
        if self.end_record_index < self.start_record_index:
            raise ValueError(
                "end_record_index must be >= start_record_index"
            )
        if self.record_count != (
            self.end_record_index - self.start_record_index
        ):
            raise ValueError(
                "record_count must equal end_record_index - start_record_index"
            )
        if len(self.ordered_record_ids) != self.record_count:
            raise ValueError(
                "ordered_record_ids must have length equal to record_count"
            )
        if len(self.ordered_record_types) != self.record_count:
            raise ValueError(
                "ordered_record_types must have length equal to record_count"
            )

        # Normalize tuples and reject empty entries deterministically.
        for tuple_field_name in (
            "ordered_record_ids",
            "ordered_record_types",
            "routine_run_ids",
            "signal_ids",
            "menu_ids",
            "selection_ids",
            "investor_selected_refs",
            "bank_selected_refs",
            "shared_selected_refs",
            "investor_only_refs",
            "bank_only_refs",
            "warnings",
        ):
            value = tuple(getattr(self, tuple_field_name))
            for entry in value:
                if not isinstance(entry, str) or not entry:
                    raise ValueError(
                        f"{tuple_field_name} entries must be non-empty strings"
                    )
            object.__setattr__(self, tuple_field_name, value)

        # record_type_counts: tuple of (str, int), sorted by event type.
        normalized_counts: list[tuple[str, int]] = []
        for entry in self.record_type_counts:
            if (
                not isinstance(entry, tuple)
                or len(entry) != 2
                or not isinstance(entry[0], str)
                or not entry[0]
                or not isinstance(entry[1], int)
                or entry[1] < 0
            ):
                raise ValueError(
                    "record_type_counts entries must be (non-empty str, "
                    f"non-negative int); got {entry!r}"
                )
            normalized_counts.append((entry[0], entry[1]))
        object.__setattr__(
            self,
            "record_type_counts",
            tuple(sorted(normalized_counts)),
        )

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        """Deterministic dict projection. Tuples become lists;
        ``record_type_counts`` becomes a list of two-element lists
        for JSON-friendliness."""
        return {
            "report_id": self.report_id,
            "chain_name": self.chain_name,
            "start_record_index": self.start_record_index,
            "end_record_index": self.end_record_index,
            "record_count": self.record_count,
            "record_type_counts": [
                [event_type, count]
                for event_type, count in self.record_type_counts
            ],
            "ordered_record_ids": list(self.ordered_record_ids),
            "ordered_record_types": list(self.ordered_record_types),
            "routine_run_ids": list(self.routine_run_ids),
            "signal_ids": list(self.signal_ids),
            "menu_ids": list(self.menu_ids),
            "selection_ids": list(self.selection_ids),
            "investor_selected_refs": list(self.investor_selected_refs),
            "bank_selected_refs": list(self.bank_selected_refs),
            "shared_selected_refs": list(self.shared_selected_refs),
            "investor_only_refs": list(self.investor_only_refs),
            "bank_only_refs": list(self.bank_only_refs),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_endogenous_chain_report(
    kernel: Any,
    chain_result: EndogenousChainResult,
    *,
    chain_name: str = _DEFAULT_CHAIN_NAME,
    report_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> LedgerTraceReport:
    """
    Build a :class:`LedgerTraceReport` for ``chain_result`` by
    re-walking the kernel's ledger between
    ``ledger_record_count_before`` and ``ledger_record_count_after``.

    This is a **read-only** operation: ``kernel`` is consulted but
    never mutated, and no new ledger records are appended.

    Validation
    ----------

    The builder performs three soft cross-checks and emits a
    warning string for each that fails (the report still builds):

    1. The ledger slice's length must equal
       ``chain_result.created_record_count``. A mismatch usually
       means someone wrote to the ledger after the chain returned
       — the slice the report is reading is not the chain's slice.
    2. The ledger slice's ordered ``object_id`` values must equal
       ``chain_result.created_record_ids``. A mismatch usually
       means the ledger was rewritten or trimmed.
    3. Every event type in :data:`_EXPECTED_CHAIN_EVENT_TYPES`
       should appear at least once. A missing event type is a
       genuine partial chain (e.g., the corporate report skipped)
       — informative, not fatal.

    The validation behaviour is deliberately permissive so that
    callers can still inspect partial chains. v1.8.15 prefers
    "show what is there with warnings attached" over "refuse to
    render."
    """
    if kernel is None:
        raise ValueError("kernel is required")
    if not isinstance(chain_result, EndogenousChainResult):
        raise TypeError(
            "chain_result must be an EndogenousChainResult; "
            f"got {type(chain_result).__name__}"
        )
    if not isinstance(chain_name, str) or not chain_name:
        raise ValueError("chain_name must be a non-empty string")
    if report_id is not None and not (
        isinstance(report_id, str) and report_id
    ):
        raise ValueError("report_id must be a non-empty string or None")

    start_idx = chain_result.ledger_record_count_before
    end_idx = chain_result.ledger_record_count_after
    if start_idx < 0 or end_idx < start_idx:
        raise ValueError(
            "chain_result has invalid ledger indices "
            f"(start={start_idx}, end={end_idx})"
        )

    ledger_records = kernel.ledger.records
    # Bound end_idx to the ledger's current length so we never
    # IndexError on a trimmed ledger; warn instead.
    safe_end = min(end_idx, len(ledger_records))
    slice_records = list(ledger_records[start_idx:safe_end])

    ordered_record_ids: list[str] = []
    ordered_record_types: list[str] = []
    routine_run_ids: list[str] = []
    signal_ids: list[str] = []
    menu_ids: list[str] = []
    selection_ids: list[str] = []
    counts: dict[str, int] = {}

    for record in slice_records:
        # object_id may legally be None on some record types, but
        # the chain we report on always sets it. Skip silently if
        # absent — the slice has its full length, ordered_record_*
        # tuples will be shorter, and the validation pass below
        # will note the mismatch.
        oid = record.object_id
        event_type = record.record_type.value
        counts[event_type] = counts.get(event_type, 0) + 1
        if not isinstance(oid, str) or not oid:
            continue
        ordered_record_ids.append(oid)
        ordered_record_types.append(event_type)
        if event_type == RecordType.ROUTINE_RUN_RECORDED.value:
            routine_run_ids.append(oid)
        elif event_type == RecordType.SIGNAL_ADDED.value:
            signal_ids.append(oid)
        elif event_type == RecordType.OBSERVATION_MENU_CREATED.value:
            menu_ids.append(oid)
        elif event_type == RecordType.OBSERVATION_SET_SELECTED.value:
            selection_ids.append(oid)

    warnings: list[str] = []
    if safe_end != end_idx:
        warnings.append(
            f"chain_result claims end_record_index={end_idx} but "
            f"kernel.ledger.records has length {len(ledger_records)}; "
            f"slice truncated to {safe_end}"
        )

    expected_count = chain_result.created_record_count
    if len(slice_records) != expected_count:
        warnings.append(
            f"ledger slice length ({len(slice_records)}) does not match "
            f"chain_result.created_record_count ({expected_count})"
        )
    if tuple(
        r.object_id for r in slice_records
    ) != chain_result.created_record_ids:
        warnings.append(
            "ledger slice object_ids do not match "
            "chain_result.created_record_ids"
        )

    seen_event_types = set(counts.keys())
    for expected in _EXPECTED_CHAIN_EVENT_TYPES:
        if expected not in seen_event_types:
            warnings.append(f"expected event type missing: {expected}")

    record_count = len(slice_records)
    rid = report_id or f"report:{chain_name}:{chain_result.as_of_date}"

    final_metadata = {
        "renderer": "v1.8.15",
        "format_version": "1",
        "chain_corporate_status": chain_result.corporate_status,
        "chain_investor_review_status": chain_result.investor_review_status,
        "chain_bank_review_status": chain_result.bank_review_status,
        "chain_as_of_date": chain_result.as_of_date,
        "chain_firm_id": chain_result.firm_id,
        "chain_investor_id": chain_result.investor_id,
        "chain_bank_id": chain_result.bank_id,
        "chain_claimed_end_record_index": end_idx,
    }
    if metadata:
        final_metadata.update(dict(metadata))

    return LedgerTraceReport(
        report_id=rid,
        chain_name=chain_name,
        start_record_index=start_idx,
        # Bound end_record_index to what we actually scanned so
        # __post_init__ stays internally consistent. The original
        # claim (end_idx) is preserved in the warning message and
        # in metadata for forensic use.
        end_record_index=safe_end,
        record_count=record_count,
        record_type_counts=tuple(sorted(counts.items())),
        ordered_record_ids=tuple(ordered_record_ids),
        ordered_record_types=tuple(ordered_record_types),
        routine_run_ids=tuple(routine_run_ids),
        signal_ids=tuple(signal_ids),
        menu_ids=tuple(menu_ids),
        selection_ids=tuple(selection_ids),
        investor_selected_refs=chain_result.investor_selected_refs,
        bank_selected_refs=chain_result.bank_selected_refs,
        shared_selected_refs=chain_result.shared_selected_refs,
        investor_only_refs=chain_result.investor_only_selected_refs,
        bank_only_refs=chain_result.bank_only_selected_refs,
        warnings=tuple(warnings),
        metadata=final_metadata,
    )


# ---------------------------------------------------------------------------
# Markdown renderer
# ---------------------------------------------------------------------------


def render_endogenous_chain_markdown(report: LedgerTraceReport) -> str:
    """
    Compact deterministic Markdown rendering of ``report``.

    The layout is fixed and contains no timestamps, no random ids,
    and no field that consults the wall clock. Two reports built
    from byte-identical chain results render to byte-identical
    Markdown. Tests pin this property.
    """
    md = report.to_dict()
    lines: list[str] = []

    lines.append(f"# {md['chain_name']}")
    lines.append("")
    lines.append(f"- **report_id**: `{md['report_id']}`")
    lines.append(f"- **chain_status (corporate)**: `{md['metadata']['chain_corporate_status']}`")
    lines.append(
        f"- **chain_status (investor_review)**: "
        f"`{md['metadata']['chain_investor_review_status']}`"
    )
    lines.append(
        f"- **chain_status (bank_review)**: "
        f"`{md['metadata']['chain_bank_review_status']}`"
    )
    lines.append(f"- **as_of_date**: `{md['metadata']['chain_as_of_date']}`")
    lines.append(
        f"- **ledger_slice**: `[{md['start_record_index']}, "
        f"{md['end_record_index']})` ({md['record_count']} records)"
    )
    lines.append("")

    lines.append("## Records by event type")
    lines.append("")
    if md["record_type_counts"]:
        for event_type, count in md["record_type_counts"]:
            lines.append(f"- `{event_type}`: {count}")
    else:
        lines.append("- _(none)_")
    lines.append("")

    lines.append("## Routine runs")
    lines.append("")
    if md["routine_run_ids"]:
        for rid in md["routine_run_ids"]:
            lines.append(f"- `{rid}`")
    else:
        lines.append("- _(none)_")
    lines.append("")

    lines.append("## Signals")
    lines.append("")
    if md["signal_ids"]:
        for sid in md["signal_ids"]:
            lines.append(f"- `{sid}`")
    else:
        lines.append("- _(none)_")
    lines.append("")

    lines.append("## Attention")
    lines.append("")
    lines.append(f"- menus: {len(md['menu_ids'])}")
    for mid in md["menu_ids"]:
        lines.append(f"  - `{mid}`")
    lines.append(f"- selections: {len(md['selection_ids'])}")
    for sid in md["selection_ids"]:
        lines.append(f"  - `{sid}`")
    lines.append("")

    lines.append("## Selection overlap")
    lines.append("")
    lines.append(
        f"- shared: {len(md['shared_selected_refs'])} | "
        f"investor_only: {len(md['investor_only_refs'])} | "
        f"bank_only: {len(md['bank_only_refs'])}"
    )
    if md["shared_selected_refs"]:
        lines.append("- **shared**:")
        for ref in md["shared_selected_refs"]:
            lines.append(f"  - `{ref}`")
    if md["investor_only_refs"]:
        lines.append("- **investor_only**:")
        for ref in md["investor_only_refs"]:
            lines.append(f"  - `{ref}`")
    if md["bank_only_refs"]:
        lines.append("- **bank_only**:")
        for ref in md["bank_only_refs"]:
            lines.append(f"  - `{ref}`")
    lines.append("")

    lines.append("## Warnings")
    lines.append("")
    if md["warnings"]:
        for warning in md["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- _(none)_")
    lines.append("")

    # Trailing newline + deterministic ordering — no trailing whitespace.
    return "\n".join(lines).rstrip() + "\n"
