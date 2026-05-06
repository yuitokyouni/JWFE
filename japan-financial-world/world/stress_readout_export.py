"""
v1.22.1 — Stress Readout Export Projection.

Kernel-aware helper that projects v1.21.3 stress readouts into
the v1.22.1 ``RunExportBundle.stress_readout`` payload section.

This module is the bridge between:

- :mod:`world.stress_readout` (v1.21.3 read-only multiset
  projection over a stress program application + the v1.18.2
  records the program emitted), and
- :mod:`world.run_export` (the v1.19.x runtime-book-free data
  carrier; v1.22.1 adds a descriptive-only ``stress_readout``
  payload section, validated against
  :data:`world.run_export.STRESS_READOUT_ENTRY_REQUIRED_KEYS`
  and
  :data:`world.run_export.FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS`).

Binding (v1.22.0 design pin §3.4):

- The export entry contains exactly 19 descriptive-only keys
  (a strict subset of :class:`world.stress_readout.StressFieldReadout`
  output: ``readout_id`` and ``metadata`` are intentionally
  dropped from the export shape).
- The section is **empty** (returns ``()``) when no v1.21
  stress program has been applied to the kernel; the export
  bundle's ``to_dict`` output then **omits** the
  ``stress_readout`` key entirely (preserving byte-identity
  with pre-v1.22 bundles).
- Cardinality (binding from v1.21.0a): at most one stress
  program per run, hence at most one entry in the section.
- Stable, deterministic ordering: entries are emitted in the
  order :meth:`world.stress_applications.StressProgramApplicationBook.list_applications`
  returns them (insertion order, which is the v1.21.2
  ``apply_stress_program(...)`` call order).

What this module does NOT do (binding):

- It does **not** call
  :func:`world.stress_applications.apply_stress_program` or
  :func:`world.scenario_applications.apply_scenario_driver`.
- It does **not** emit a ledger record.
- It does **not** mutate any source-of-truth book.
- It does **not** introduce a new dataclass, a new label
  vocabulary, or a new ledger event type.
- It does **not** infer interaction labels
  (``amplify`` / ``dampen`` / ``offset`` / ``coexist`` —
  deferred to v1.22+ as ``manual_annotation``-only per
  v1.21.0a §130.7).
- It does **not** emit aggregate / combined / net / dominant
  / composite stress output.
- It does **not** emit impact / outcome / risk_score /
  forecast / prediction / recommendation fields.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Mapping

from world.stress_readout import (
    StressFieldReadout,
    build_stress_field_readout,
)


if TYPE_CHECKING:
    from world.kernel import WorldKernel


__all__ = (
    "build_stress_readout_export_section",
    "stress_field_readout_to_export_entry",
)


def stress_field_readout_to_export_entry(
    readout: StressFieldReadout,
) -> dict[str, Any]:
    """Project a :class:`StressFieldReadout` into the v1.22.1
    19-key descriptive-only export entry.

    The mapping mirrors :data:`world.run_export.STRESS_READOUT_ENTRY_REQUIRED_KEYS`
    exactly. ``readout_id`` and ``metadata`` are intentionally
    dropped (the v1.22.0 design pin restricts the export shape
    to plain-id citation surfaces and per-step resolution
    counts).

    The output is fully derived from ``readout``: same readout
    → byte-identical entry. List-typed fields preserve the
    readout's emission order verbatim (no sorting, no
    de-duplication).
    """
    if not isinstance(readout, StressFieldReadout):
        raise TypeError(
            "stress_field_readout_to_export_entry expects a "
            "StressFieldReadout instance"
        )
    return {
        "stress_program_application_id": (
            readout.stress_program_application_id
        ),
        "stress_program_template_id": (
            readout.stress_program_template_id
        ),
        "as_of_date": readout.as_of_date,
        "total_step_count": readout.total_step_count,
        "resolved_step_count": readout.resolved_step_count,
        "unresolved_step_count": readout.unresolved_step_count,
        "active_step_ids": list(readout.active_step_ids),
        "unresolved_step_ids": list(
            readout.unresolved_step_ids
        ),
        "unresolved_reason_labels": list(
            readout.unresolved_reason_labels
        ),
        "is_partial": readout.is_partial,
        "scenario_driver_template_ids": list(
            readout.scenario_driver_template_ids
        ),
        "scenario_application_ids": list(
            readout.scenario_application_ids
        ),
        "scenario_context_shift_ids": list(
            readout.scenario_context_shift_ids
        ),
        "context_surface_labels": list(
            readout.context_surface_labels
        ),
        "shift_direction_labels": list(
            readout.shift_direction_labels
        ),
        "scenario_family_labels": list(
            readout.scenario_family_labels
        ),
        "source_context_record_ids": list(
            readout.source_context_record_ids
        ),
        "downstream_citation_ids": list(
            readout.downstream_citation_ids
        ),
        "warnings": list(readout.warnings),
    }


def build_stress_readout_export_section(
    kernel: "WorldKernel",
    *,
    downstream_citation_ids_by_application_id: (
        Mapping[str, Iterable[str]] | None
    ) = None,
) -> tuple[dict[str, Any], ...]:
    """Return the v1.22.1 ``stress_readout`` payload section
    for ``kernel``.

    Behaviour:

    - When ``kernel.stress_applications`` is empty, returns
      ``()`` — the empty section. The export bundle's
      ``to_dict`` output then omits the ``stress_readout``
      key entirely, preserving byte-identity with pre-v1.22
      bundles. **No digest movement.**
    - When ``kernel.stress_applications`` has one or more
      records (v1.21.0a cardinality pins at most one per
      run), returns a tuple of one entry per application,
      built via :func:`build_stress_field_readout` then
      projected via
      :func:`stress_field_readout_to_export_entry`.

    The optional ``downstream_citation_ids_by_application_id``
    argument lets a CLI caller supply downstream citation ids
    keyed by ``stress_program_application_id``. Missing keys
    → empty downstream-citation tuple for that application.

    Read-only:

    - Does not mutate ``kernel``.
    - Does not emit a ledger record.
    - Does not call
      :func:`world.stress_applications.apply_stress_program`.
    - Does not call
      :func:`world.scenario_applications.apply_scenario_driver`.

    Same kernel state → byte-identical section.
    """
    book = getattr(kernel, "stress_applications", None)
    if book is None:
        return ()
    applications = book.list_applications()
    if not applications:
        return ()
    citation_map: dict[str, tuple[str, ...]] = {}
    if downstream_citation_ids_by_application_id is not None:
        for k, v in (
            downstream_citation_ids_by_application_id.items()
        ):
            citation_map[k] = tuple(v)

    entries: list[dict[str, Any]] = []
    for application in applications:
        readout = build_stress_field_readout(
            kernel,
            stress_program_application_id=(
                application.stress_program_application_id
            ),
            downstream_citation_ids=citation_map.get(
                application.stress_program_application_id, ()
            ),
        )
        entries.append(
            stress_field_readout_to_export_entry(readout)
        )
    return tuple(entries)
