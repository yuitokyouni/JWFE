"""
v1.23.1 — Cross-layer metadata stamp contract pin tests.

Pins the v1.21.2 ↔ v1.21.3 metadata-stamp glue: every
v1.18.2 ``ScenarioDriverApplicationRecord`` emitted by
``apply_stress_program(...)`` carries a
``metadata[STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY]``
matching the program-level receipt id, and a
``metadata[STRESS_STEP_ID_METADATA_KEY]`` matching the
v1.21.1 step id; ``build_stress_field_readout(...)`` reads
those keys to filter v1.18.2 records by stress program /
stress step at readout-build time.

The contract was unpinned at v1.21.last — round-2 review
flagged zero hits for ``metadata["stress_program_application_id"]``
in the test corpus. v1.23.1 adds:

- forward direction: every per-step v1.18.2 record carries
  the matching stamp keys / values;
- reverse direction: the readout's
  ``scenario_application_ids`` resolve exactly to the
  stamped v1.18.2 records (an unstamped v1.18.2 record in
  the same kernel must NOT appear in the readout);
- round-trip: stress-applied kernel → readout →
  ``scenario_application_ids`` matches the stamped records;
- partial / missing-stamp behaviour: a v1.18.2 record
  whose metadata lacks the stamp surfaces as unresolved /
  unknown rather than silently misclassifying;
- the metadata-stamp constants equal their string-literal
  values (no rename drift).

The pins add no new behaviour — they only assert what
v1.21.2 / v1.21.3 already do. v1.23.1 introduces named
constants in ``world.stress_applications`` so a future
rename requires updating one place.
"""

from __future__ import annotations

from datetime import date

from world.clock import Clock
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.scenario_applications import (
    ScenarioDriverApplicationRecord,
    apply_scenario_driver,
)
from world.scenario_drivers import ScenarioDriverTemplate
from world.scheduler import Scheduler
from world.state import State
from world.stress_applications import (
    STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY,
    STRESS_STEP_ID_METADATA_KEY,
    apply_stress_program,
)
from world.stress_programs import (
    StressProgramTemplate,
    StressStep,
)
from world.stress_readout import build_stress_field_readout


# ---------------------------------------------------------------------------
# Local kernel + program fixtures (mirror the v1.21.2 test
# discipline — minimal, deterministic, no real-data).
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


def _seed_kernel_with_two_step_program() -> tuple[
    WorldKernel, StressProgramTemplate
]:
    """Two-step program citing two distinct v1.18.1 templates,
    both registered on the kernel. Both steps resolve in the
    happy path."""
    kernel = _bare_kernel()
    tpl_ids = (
        "scenario_driver:credit_tightening:reference",
        "scenario_driver:funding_window_closure:reference",
    )
    for tpl_id in tpl_ids:
        kernel.scenario_drivers.add_template(
            _build_template(scenario_driver_template_id=tpl_id)
        )
    program_id = "stress_program:test:metadata_stamp"
    program = StressProgramTemplate(
        stress_program_template_id=program_id,
        program_label="Two-step metadata-stamp test",
        program_purpose_label="twin_credit_funding_stress",
        stress_steps=(
            StressStep(
                stress_step_id=f"{program_id}:step:0",
                parent_stress_program_template_id=program_id,
                step_index=0,
                scenario_driver_template_id=tpl_ids[0],
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            ),
            StressStep(
                stress_step_id=f"{program_id}:step:1",
                parent_stress_program_template_id=program_id,
                step_index=1,
                scenario_driver_template_id=tpl_ids[1],
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            ),
        ),
    )
    kernel.stress_programs.add_program(program)
    return kernel, program


# ---------------------------------------------------------------------------
# 1. Forward direction — apply writes the stamp keys.
# ---------------------------------------------------------------------------


def test_stress_application_writes_metadata_stamp_keys() -> None:
    """Every per-step v1.18.2 record carries the v1.23.1
    metadata-stamp keys / values; the program-level receipt
    id matches the stamp; the step id matches the stamp."""
    kernel, program = _seed_kernel_with_two_step_program()
    receipt = apply_stress_program(
        kernel,
        stress_program_template_id=(
            program.stress_program_template_id
        ),
        as_of_date="2026-04-30",
    )

    apps = kernel.scenario_applications.list_applications()
    assert len(apps) == 2

    # Forward direction: every emitted v1.18.2 application
    # record carries the stamp keys.
    stamped: list[ScenarioDriverApplicationRecord] = []
    for app in apps:
        md = app.metadata or {}
        assert (
            STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY in md
        ), (
            "v1.18.2 app missing "
            f"{STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY!r}"
        )
        assert STRESS_STEP_ID_METADATA_KEY in md, (
            "v1.18.2 app missing "
            f"{STRESS_STEP_ID_METADATA_KEY!r}"
        )
        assert (
            md[STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY]
            == receipt.stress_program_application_id
        )
        # Step id must match one of the program's actual step
        # ids.
        program_step_ids = {
            s.stress_step_id for s in program.stress_steps
        }
        assert (
            md[STRESS_STEP_ID_METADATA_KEY]
            in program_step_ids
        )
        stamped.append(app)

    # Both v1.18.2 records are stamped.
    assert len(stamped) == 2


# ---------------------------------------------------------------------------
# 2. Reverse direction — readout reads the stamp keys.
# ---------------------------------------------------------------------------


def test_stress_readout_reads_same_metadata_stamp_keys() -> None:
    """The v1.21.3 readout filters v1.18.2 records by the
    stamp keys; an unrelated v1.18.2 record (not stamped)
    must NOT appear in the readout."""
    kernel, program = _seed_kernel_with_two_step_program()
    receipt = apply_stress_program(
        kernel,
        stress_program_template_id=(
            program.stress_program_template_id
        ),
        as_of_date="2026-04-30",
    )

    # Inject an unrelated, unstamped v1.18.2 application
    # citing a third template.
    extra_tpl_id = (
        "scenario_driver:information_gap:reference"
    )
    kernel.scenario_drivers.add_template(
        _build_template(
            scenario_driver_template_id=extra_tpl_id,
        )
    )
    apply_scenario_driver(
        kernel,
        scenario_driver_template_id=extra_tpl_id,
        as_of_date="2026-04-30",
    )

    readout = build_stress_field_readout(
        kernel,
        stress_program_application_id=(
            receipt.stress_program_application_id
        ),
    )

    # The readout cites only the stamped v1.18.2 application
    # ids.
    assert set(readout.scenario_application_ids) == set(
        receipt.scenario_application_ids
    )
    # The unstamped extra v1.18.2 record is NOT cited.
    extra_apps = tuple(
        a
        for a in kernel.scenario_applications.list_applications()
        if (
            (a.metadata or {}).get(
                STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY
            )
            is None
        )
    )
    assert len(extra_apps) == 1
    extra_app_id = extra_apps[0].scenario_application_id
    assert (
        extra_app_id not in readout.scenario_application_ids
    )
    assert readout.resolved_step_count == 2
    assert readout.unresolved_step_count == 0


# ---------------------------------------------------------------------------
# 3. Round-trip — stamp survives apply → readout walk.
# ---------------------------------------------------------------------------


def test_metadata_stamp_contract_round_trip() -> None:
    """Apply program → build readout → assert each cited
    v1.18.2 app's stamp resolves to the program receipt."""
    kernel, program = _seed_kernel_with_two_step_program()
    receipt = apply_stress_program(
        kernel,
        stress_program_template_id=(
            program.stress_program_template_id
        ),
        as_of_date="2026-04-30",
    )
    readout = build_stress_field_readout(
        kernel,
        stress_program_application_id=(
            receipt.stress_program_application_id
        ),
    )

    apps_by_id = {
        a.scenario_application_id: a
        for a in kernel.scenario_applications.list_applications()
    }
    for app_id in readout.scenario_application_ids:
        app = apps_by_id[app_id]
        md = app.metadata or {}
        assert (
            md[STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY]
            == receipt.stress_program_application_id
        )
        # And the corresponding step id is one of the
        # program's step ids.
        program_step_ids = {
            s.stress_step_id for s in program.stress_steps
        }
        assert (
            md[STRESS_STEP_ID_METADATA_KEY]
            in program_step_ids
        )


# ---------------------------------------------------------------------------
# 4. Failing-path — a v1.18.2 record whose metadata lacks
#    the stamp must NOT appear in the readout (treat as
#    unrelated rather than silently misclassifying).
# ---------------------------------------------------------------------------


def test_readout_surfaces_missing_metadata_stamp_as_warning_or_unresolved() -> None:
    """A v1.18.2 application record with a stress-step id
    matching a program's step id, but WITHOUT the
    program-application-id stamp, must NOT be matched to the
    program by the readout. The step continues to look
    unresolved (template missing → ``template_missing``
    reason) — i.e., the readout's stamp filter is the only
    legal way to claim a v1.18.2 record belongs to a
    program."""
    kernel = _bare_kernel()
    tpl_id = "scenario_driver:credit_tightening:reference"
    kernel.scenario_drivers.add_template(
        _build_template(scenario_driver_template_id=tpl_id)
    )
    program_id = "stress_program:test:missing_stamp"
    program = StressProgramTemplate(
        stress_program_template_id=program_id,
        program_label="Missing-stamp test",
        program_purpose_label="single_credit_tightening_stress",
        stress_steps=(
            StressStep(
                stress_step_id=f"{program_id}:step:0",
                parent_stress_program_template_id=program_id,
                step_index=0,
                scenario_driver_template_id=tpl_id,
                event_date_policy_label="quarter_end",
                scheduled_month_label="month_04",
            ),
        ),
    )
    kernel.stress_programs.add_program(program)

    # Apply the v1.18.2 helper directly with metadata that
    # carries the step id but NOT the stress-program-
    # application-id stamp. This mimics a misuse pattern
    # where a caller hand-crafts a v1.18.2 record without
    # going through ``apply_stress_program``.
    apply_scenario_driver(
        kernel,
        scenario_driver_template_id=tpl_id,
        as_of_date="2026-04-30",
        metadata={
            STRESS_STEP_ID_METADATA_KEY: (
                f"{program_id}:step:0"
            ),
        },
    )

    # Build a synthetic program-application receipt by hand
    # so we can ask the readout to look for it. Use the same
    # receipt id format the orchestrator would have used,
    # but DO NOT mutate the v1.18.2 record's metadata.
    from world.stress_applications import (
        StressProgramApplicationRecord,
    )

    receipt_id = (
        f"stress_program_application:{program_id}:2026-04-30"
    )
    fake_receipt = StressProgramApplicationRecord(
        stress_program_application_id=receipt_id,
        stress_program_template_id=program_id,
        as_of_date="2026-04-30",
        scenario_application_ids=(),
        scenario_context_shift_ids=(),
        unresolved_step_count=1,
        application_status_label="rejected",
    )
    kernel.stress_applications.add_application(fake_receipt)

    readout = build_stress_field_readout(
        kernel, stress_program_application_id=receipt_id
    )

    # The readout treats the unstamped v1.18.2 record as
    # unrelated. The step is unresolved, the
    # ``unresolved_step_count`` is 1, and warnings surface
    # the partial application.
    assert readout.unresolved_step_count == 1
    assert readout.resolved_step_count == 0
    assert readout.is_partial
    assert any(
        "partial application" in w.lower()
        for w in readout.warnings
    )


# ---------------------------------------------------------------------------
# 5. Constant equality — the v1.23.1 named constants equal
#    their byte-pinned string values. A future rename has to
#    update the constants here AND in the design pin.
# ---------------------------------------------------------------------------


def test_metadata_stamp_key_constants_equal_existing_serialized_strings() -> None:
    """The v1.23.1 named constants must equal the v1.21.2
    string-literal keys (``"stress_program_application_id"``
    and ``"stress_step_id"``) byte-for-byte. v1.23.1
    introduces no new keys; the consolidation is name-only."""
    assert (
        STRESS_PROGRAM_APPLICATION_ID_METADATA_KEY
        == "stress_program_application_id"
    )
    assert STRESS_STEP_ID_METADATA_KEY == "stress_step_id"
