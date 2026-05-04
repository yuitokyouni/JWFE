"""
v1.18.3 — Scenario report driver.

Kernel-reading bridge between
:mod:`world.scenario_drivers` / :mod:`world.scenario_applications`
and the v1.17 inspection layer in :mod:`world.display_timeline`.

The driver:

- builds a deterministic synthetic scenario fixture (one
  :class:`world.scenario_drivers.ScenarioDriverTemplate` per
  v1.18.2-mapped family by default, plus a ``thematic`` template
  to exercise the ``no_direct_shift`` fallback);
- registers each template via
  :meth:`world.scenario_drivers.ScenarioDriverTemplateBook.add_template`;
- applies each template via
  :func:`world.scenario_applications.apply_scenario_driver` (so
  every emitted :class:`ScenarioContextShiftRecord` carries the
  v1.18.0 audit-metadata block);
- reads the kernel's read-only scenario_applications book;
- builds :class:`EventAnnotationRecord` and
  :class:`CausalTimelineAnnotation` tuples via the v1.18.3
  display helpers;
- renders a deterministic markdown report via
  :func:`render_scenario_application_markdown`.

The driver mutates **no** pre-existing context record. It does
not run the living reference world. It does not touch the
``PriceBook``. It does not move the default-fixture
``living_world_digest`` for a sweep on a *different* fresh
kernel. v1.18.3 is **report / display integration only**.

This is **synthetic display only** — no price formation, no
trading, no financing execution, no investment advice, no
forecast, no real data, no Japan calibration, no LLM execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable

from world.clock import Clock
from world.display_timeline import (
    CausalTimelineAnnotation,
    EventAnnotationRecord,
    build_causal_timeline_annotations_from_scenario_shifts,
    build_event_annotations_from_scenario_shifts,
    render_scenario_application_markdown,
)
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.scenario_applications import apply_scenario_driver
from world.scenario_drivers import ScenarioDriverTemplate
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Default scenario fixture
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ScenarioFixtureEntry:
    """One entry in the default v1.18.3 scenario fixture: a
    template plus the cited synthetic context-record ids the
    helper will pass to :func:`apply_scenario_driver`."""

    template: ScenarioDriverTemplate
    source_context_record_ids: tuple[str, ...]


def build_default_scenario_fixture() -> tuple[
    _ScenarioFixtureEntry, ...
]:
    """Return a deterministic six-template fixture exercising
    every v1.18.2-mapped family plus the ``no_direct_shift``
    fallback path."""
    return (
        _ScenarioFixtureEntry(
            template=ScenarioDriverTemplate(
                scenario_driver_template_id=(
                    "scenario_driver:rate_repricing:reference"
                ),
                scenario_family_label="rate_repricing_driver",
                driver_group_label="macro_rates",
                driver_label=(
                    "Synthetic rising-rate context shift"
                ),
                event_date_policy_label="quarter_start",
                severity_label="medium",
                affected_actor_scope_label="market_wide",
                expected_annotation_type_label=(
                    "market_environment_change"
                ),
                affected_evidence_bucket_labels=(
                    "market_environment_state",
                ),
            ),
            source_context_record_ids=(
                "synthetic:env:reference:1",
            ),
        ),
        _ScenarioFixtureEntry(
            template=ScenarioDriverTemplate(
                scenario_driver_template_id=(
                    "scenario_driver:credit_tightening:reference"
                ),
                scenario_family_label=(
                    "credit_tightening_driver"
                ),
                driver_group_label="credit_liquidity",
                driver_label=(
                    "Synthetic credit-tightening context shift"
                ),
                event_date_policy_label="quarter_start",
                severity_label="high",
                affected_actor_scope_label="market_wide",
                expected_annotation_type_label=(
                    "financing_constraint"
                ),
                affected_evidence_bucket_labels=(
                    "market_environment_state",
                    "market_condition",
                ),
            ),
            source_context_record_ids=(
                "synthetic:env:reference:1",
                "synthetic:market_condition:reference:1",
            ),
        ),
        _ScenarioFixtureEntry(
            template=ScenarioDriverTemplate(
                scenario_driver_template_id=(
                    "scenario_driver:funding_window_closure:reference"
                ),
                scenario_family_label=(
                    "funding_window_closure_driver"
                ),
                driver_group_label="credit_liquidity",
                driver_label=(
                    "Synthetic funding-window closure"
                ),
                event_date_policy_label="quarter_start",
                severity_label="high",
                affected_actor_scope_label="firms_only",
                expected_annotation_type_label=(
                    "financing_constraint"
                ),
                affected_evidence_bucket_labels=(
                    "market_condition",
                ),
            ),
            source_context_record_ids=(
                "synthetic:market_condition:reference:1",
            ),
        ),
        _ScenarioFixtureEntry(
            template=ScenarioDriverTemplate(
                scenario_driver_template_id=(
                    "scenario_driver:liquidity_stress:reference"
                ),
                scenario_family_label=(
                    "liquidity_stress_driver"
                ),
                driver_group_label="credit_liquidity",
                driver_label=(
                    "Synthetic interbank-liquidity stress"
                ),
                event_date_policy_label="quarter_start",
                severity_label="stress",
                affected_actor_scope_label="banks_only",
                expected_annotation_type_label=(
                    "market_environment_change"
                ),
                affected_evidence_bucket_labels=(
                    "interbank_liquidity_state",
                ),
            ),
            source_context_record_ids=(
                "synthetic:interbank_liquidity:reference:1",
            ),
        ),
        _ScenarioFixtureEntry(
            template=ScenarioDriverTemplate(
                scenario_driver_template_id=(
                    "scenario_driver:information_gap:reference"
                ),
                scenario_family_label=(
                    "information_gap_driver"
                ),
                driver_group_label="information_attention",
                driver_label=(
                    "Synthetic evidence-deficient situation"
                ),
                event_date_policy_label="quarter_start",
                severity_label="low",
                affected_actor_scope_label="all_actors",
                expected_annotation_type_label=(
                    "attention_shift"
                ),
                affected_evidence_bucket_labels=(),
            ),
            source_context_record_ids=(),
        ),
        _ScenarioFixtureEntry(
            template=ScenarioDriverTemplate(
                scenario_driver_template_id=(
                    "scenario_driver:thematic_attention:reference"
                ),
                scenario_family_label=(
                    "thematic_attention_driver"
                ),
                driver_group_label="information_attention",
                driver_label=(
                    "Synthetic theme observation "
                    "(unmapped fallback path)"
                ),
                event_date_policy_label="quarter_start",
                severity_label="low",
                affected_actor_scope_label="market_wide",
                expected_annotation_type_label=(
                    "attention_shift"
                ),
                affected_evidence_bucket_labels=(),
            ),
            source_context_record_ids=(),
        ),
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


_DEFAULT_AS_OF_DATE: date = date(2026, 3, 31)


def _fresh_scenario_kernel(as_of_date: date) -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=as_of_date),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


@dataclass(frozen=True)
class ScenarioReportSnapshot:
    """Immutable bundle returned by :func:`run_scenario_report`."""

    panel_id: str
    as_of_date: str
    scenario_driver_templates: tuple[ScenarioDriverTemplate, ...]
    scenario_application_records: tuple[Any, ...]
    scenario_context_shift_records: tuple[Any, ...]
    event_annotations: tuple[EventAnnotationRecord, ...]
    causal_annotations: tuple[CausalTimelineAnnotation, ...]
    markdown: str


def run_scenario_report(
    *,
    fixture: Iterable[_ScenarioFixtureEntry] | None = None,
    as_of_date: date | str = _DEFAULT_AS_OF_DATE,
    panel_id: str = "v1.18.3:default_scenario_fixture",
) -> ScenarioReportSnapshot:
    """Build the v1.18.3 scenario report on a fresh kernel.

    A fresh :class:`WorldKernel` is constructed (so this driver
    cannot move any other run's ``living_world_digest``); each
    fixture template is registered and applied; the resulting
    appended records are read via the kernel's read-only book
    interface; the v1.18.3 display helpers turn them into
    annotations; and a deterministic markdown report is
    rendered.

    Same fixture + same ``as_of_date`` → byte-identical
    markdown.
    """
    if fixture is None:
        fixture_tuple = build_default_scenario_fixture()
    else:
        fixture_tuple = tuple(fixture)
    if isinstance(as_of_date, str):
        iso_date = as_of_date
        anchor = date.fromisoformat(as_of_date)
    elif isinstance(as_of_date, date):
        iso_date = as_of_date.isoformat()
        anchor = as_of_date
    else:
        raise TypeError(
            "as_of_date must be a date or ISO date string"
        )

    kernel = _fresh_scenario_kernel(anchor)

    templates: list[ScenarioDriverTemplate] = []
    for entry in fixture_tuple:
        kernel.scenario_drivers.add_template(entry.template)
        apply_scenario_driver(
            kernel,
            scenario_driver_template_id=(
                entry.template.scenario_driver_template_id
            ),
            as_of_date=anchor,
            source_context_record_ids=(
                entry.source_context_record_ids
            ),
        )
        templates.append(entry.template)

    applications = (
        kernel.scenario_applications.list_applications()
    )
    shifts = (
        kernel.scenario_applications.list_context_shifts()
    )
    events = build_event_annotations_from_scenario_shifts(
        scenario_application_records=applications,
        scenario_context_shift_records=shifts,
    )
    causal = (
        build_causal_timeline_annotations_from_scenario_shifts(
            scenario_application_records=applications,
            scenario_context_shift_records=shifts,
        )
    )
    markdown = render_scenario_application_markdown(
        panel_id=panel_id,
        scenario_driver_templates=templates,
        scenario_application_records=applications,
        scenario_context_shift_records=shifts,
        event_annotations=events,
        causal_annotations=causal,
    )

    return ScenarioReportSnapshot(
        panel_id=panel_id,
        as_of_date=iso_date,
        scenario_driver_templates=tuple(templates),
        scenario_application_records=tuple(applications),
        scenario_context_shift_records=tuple(shifts),
        event_annotations=events,
        causal_annotations=causal,
        markdown=markdown,
    )


def main() -> None:
    """Print the default v1.18.3 scenario report to stdout."""
    snapshot = run_scenario_report()
    print(snapshot.markdown)


if __name__ == "__main__":
    main()
