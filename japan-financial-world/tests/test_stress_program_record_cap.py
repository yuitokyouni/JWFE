"""
v1.23.1 — Stress program runtime cardinality cap pin tests.

Pins the v1.21.0a binding "≤ 60 v1.21-added records per
stress-applied run" with a runtime trip-wire. v1.21.x carried
the bound only as a fixture-level assertion in
``tests/test_stress_applications.py:873`` plus a docs
sentence; v1.23.1 makes it a runtime constant
(:data:`world.stress_applications.STRESS_PROGRAM_RUN_RECORD_CAP`)
and a check at the END of
:func:`world.stress_applications.apply_stress_program` that
raises :class:`StressProgramRecordCapExceededError` when
exceeded.

The tests:

- the constant equals 60 and is importable from
  ``world.stress_applications``;
- the helper does not raise on a normal happy-path apply
  (the v1.21.x default fixture is well under the cap);
- an artificial cap-exceedance triggers the trip-wire (we
  monkey-patch the cap to a tiny number so the existing
  per-step record count blows past it without changing
  fixture behaviour);
- the v1.20.x ``manifest.record_count <= 4000`` boundary at
  the bundle layer remains binding (independent of the
  v1.21 cap).

The cap is binding for v1.21 / v1.23-added records only. A
future v1.x milestone that legitimately needs a higher cap
must update the constant under a fresh design pin (silent
extension is forbidden).
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.scenario_drivers import ScenarioDriverTemplate
from world.scheduler import Scheduler
from world.state import State
from world.stress_applications import (
    STRESS_PROGRAM_RUN_RECORD_CAP,
    StressProgramRecordCapExceededError,
    apply_stress_program,
)
from world.stress_programs import (
    StressProgramTemplate,
    StressStep,
)


# ---------------------------------------------------------------------------
# Local kernel + program fixtures.
# ---------------------------------------------------------------------------


def _bare_kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 4, 30)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _build_template(
    *,
    scenario_driver_template_id: str = (
        "scenario_driver:credit_tightening:reference"
    ),
) -> ScenarioDriverTemplate:
    return ScenarioDriverTemplate(
        scenario_driver_template_id=(
            scenario_driver_template_id
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


def _seed_kernel_with_three_step_program() -> tuple[
    WorldKernel, StressProgramTemplate
]:
    """Three-step program (max v1.21.1 cardinality). Each
    step cites a distinct v1.18.1 template registered on the
    kernel. This mirrors the v1.21.0a worst-case happy-path
    fixture used to pin ``≤ 60``."""
    kernel = _bare_kernel()
    tpl_ids = (
        "scenario_driver:credit_tightening:reference",
        "scenario_driver:funding_window_closure:reference",
        "scenario_driver:information_gap:reference",
    )
    for tpl_id in tpl_ids:
        kernel.scenario_drivers.add_template(
            _build_template(scenario_driver_template_id=tpl_id)
        )
    program_id = "stress_program:test:cap_three_step"
    program = StressProgramTemplate(
        stress_program_template_id=program_id,
        program_label="Three-step cap test",
        program_purpose_label="multi_stress_demonstration",
        stress_steps=tuple(
            StressStep(
                stress_step_id=f"{program_id}:step:{i}",
                parent_stress_program_template_id=program_id,
                step_index=i,
                scenario_driver_template_id=tpl_ids[i],
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            )
            for i in range(len(tpl_ids))
        ),
    )
    kernel.stress_programs.add_program(program)
    return kernel, program


# ---------------------------------------------------------------------------
# 1. Constant equals 60 and is importable.
# ---------------------------------------------------------------------------


def test_stress_program_run_record_cap_constant_is_60() -> None:
    """The v1.23.1 runtime constant is the byte value 60 and
    is exposed from ``world.stress_applications``."""
    assert STRESS_PROGRAM_RUN_RECORD_CAP == 60


# ---------------------------------------------------------------------------
# 2. Happy-path apply emits added records well within the cap.
# ---------------------------------------------------------------------------


def test_apply_stress_program_added_records_within_runtime_cap() -> None:
    """A 3-step program (max cardinality) must emit
    ≤ ``STRESS_PROGRAM_RUN_RECORD_CAP`` v1.21-added records.
    The trip-wire does not fire on the v1.21.x default
    fixture."""
    kernel, program = _seed_kernel_with_three_step_program()
    sa_book = kernel.scenario_applications
    apps_before = len(sa_book.list_applications())
    shifts_before = len(sa_book.list_context_shifts())
    stress_apps_before = len(
        kernel.stress_applications.list_applications()
    )

    apply_stress_program(
        kernel,
        stress_program_template_id=(
            program.stress_program_template_id
        ),
        as_of_date="2026-04-30",
    )

    apps_added = len(sa_book.list_applications()) - apps_before
    shifts_added = (
        len(sa_book.list_context_shifts()) - shifts_before
    )
    stress_apps_added = (
        len(kernel.stress_applications.list_applications())
        - stress_apps_before
    )
    v1_21_added = apps_added + shifts_added + stress_apps_added
    assert v1_21_added <= STRESS_PROGRAM_RUN_RECORD_CAP, (
        f"3-step program emitted {v1_21_added} records — "
        f"exceeds cap {STRESS_PROGRAM_RUN_RECORD_CAP}"
    )


# ---------------------------------------------------------------------------
# 3. Artificial cap-exceedance — the trip-wire fires
#    explicitly. We monkey-patch the cap to a small number
#    so the existing per-step record count blows past it.
# ---------------------------------------------------------------------------


def test_cap_violation_is_explicit_if_artificially_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting :data:`STRESS_PROGRAM_RUN_RECORD_CAP` to a
    tiny number (smaller than a 3-step program's emitted
    record count) must cause ``apply_stress_program`` to
    raise :class:`StressProgramRecordCapExceededError`
    rather than silently violating the binding."""
    import world.stress_applications as stress_applications_mod

    monkeypatch.setattr(
        stress_applications_mod,
        "STRESS_PROGRAM_RUN_RECORD_CAP",
        2,
    )

    kernel, program = _seed_kernel_with_three_step_program()

    with pytest.raises(StressProgramRecordCapExceededError):
        apply_stress_program(
            kernel,
            stress_program_template_id=(
                program.stress_program_template_id
            ),
            as_of_date="2026-04-30",
        )


# ---------------------------------------------------------------------------
# 4. The v1.20.x ``manifest.record_count <= 4000`` boundary
#    remains binding at the bundle layer — independent of
#    the v1.21 ≤ 60 stress cap.
# ---------------------------------------------------------------------------


def test_manifest_record_count_guardrail_still_4000() -> None:
    """v1.20.x boundary: the v1.20.x test corpus pins
    ``manifest.record_count <= 4000`` for the
    ``scenario_monthly_reference_universe`` fixture under
    every supported regime / scenario flag combination. The
    v1.23.1 ≤ 60 cap is independent — it counts only
    v1.21-added records, not the manifest's total record
    count.

    This pin is symbolic: it asserts the v1.21 cap is < the
    v1.20.x manifest guardrail (so the cap does not
    accidentally widen the v1.20.x boundary)."""
    v1_20_x_manifest_record_count_guardrail = 4000
    assert (
        STRESS_PROGRAM_RUN_RECORD_CAP
        < v1_20_x_manifest_record_count_guardrail
    ), (
        "v1.21.0a/v1.23.1 ≤ 60 stress cap must stay strictly "
        "less than the v1.20.x manifest.record_count <= 4000 "
        "guardrail"
    )
