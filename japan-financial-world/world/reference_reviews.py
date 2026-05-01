"""
v1.8.13 Reference review routines — investor + bank.

This module ships the project's first concrete *consumer* routines
on top of the v1.8.12 attention substrate. Where v1.8.7 published a
synthetic corporate report on the diagonal `Corporate → Corporate`
self-loop, v1.8.13 ships two diagonal *self-loop review* routines:

  ``investor_review`` — Investors → Investors self-loop. Reads one
    or more ``SelectedObservationSet`` records via
    ``RoutineEngine``, persists exactly one ``RoutineRunRecord``,
    and emits exactly one synthetic ``investor_review_note``
    ``InformationSignal``.

  ``bank_review`` — Banking → Banking self-loop. Same shape.

Both are **review** routines, not **decision** routines. They turn
heterogeneous attention into auditable run records — the chain
"corporate reporting → menus → heterogeneous selected observations
→ investor / bank review run records → synthetic review notes" can
now be reconstructed from the ledger alone.

What v1.8.13 deliberately does NOT do
-------------------------------------

- No buy / sell decisions, portfolio rebalancing, lending
  decisions, covenant enforcement, valuation refresh, impact
  estimation, sensitivity calculation, DSCR / LTV update, price
  formation, corporate actions, or policy reactions. A
  v1.8.13 review routine is forbidden from mutating any of:
  ``ValuationBook``, ``PriceBook``, ``OwnershipBook``,
  ``ContractBook``, ``ConstraintBook``, ``ExposureBook``,
  ``WorldVariableBook``, ``InstitutionBook``,
  ``ExternalProcessBook``, or any other v0/v1 source-of-truth
  book except its own ``RoutineBook`` write (via the engine) and
  its own ``SignalBook`` write (the review note).
- No automatic execution. The routines are caller-initiated and do
  not hook into ``tick()`` / ``run()``.
- No real data, no Japan calibration, no scenario engine.
- No new ledger record types. Run records flow through
  ``ROUTINE_RUN_RECORDED``; review notes flow through
  ``SIGNAL_ADDED``.

The two pieces of ledger evidence (`routine_run_recorded` then
`signal_added`) appear in this order — tests pin it.

Cross-references
----------------

- ``InformationSignal.related_ids`` includes the routine's
  ``run_id`` (forward link from signal to run).
- ``InformationSignal.metadata["routine_run_id"]`` carries the
  same ``run_id`` for callers that prefer payload access.
- ``RoutineRunRecord.output_refs`` includes the produced
  ``signal_id`` (forward link from run to signal). Bidirectional
  audit is reconstructable from either side.

Synthetic review-note payload
-----------------------------

The signal's ``payload`` carries **count summaries only** — total
input refs, plus per-axis counts (signals / variable observations /
exposures) — and a synthetic statement. v1.8.13 deliberately does
not interpret the contents economically: it does not score risk,
flag covenants, generate buy / sell / hold notes, or otherwise
take a view. The note is an audit artifact, not a decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from world.interactions import (
    DuplicateInteractionError,
    InteractionSpec,
)
from world.routine_engine import (
    RoutineExecutionRequest,
    RoutineExecutionResult,
)
from world.routines import DuplicateRoutineError, RoutineSpec
from world.signals import InformationSignal


# ---------------------------------------------------------------------------
# Constants — controlled vocabulary
# ---------------------------------------------------------------------------


INVESTOR_REVIEW_ROUTINE_TYPE: str = "investor_review"
BANK_REVIEW_ROUTINE_TYPE: str = "bank_review"

INVESTOR_REVIEW_INTERACTION_ID: str = "interaction:investors.investor_review"
BANK_REVIEW_INTERACTION_ID: str = "interaction:banking.bank_credit_review"

INVESTOR_REVIEW_SIGNAL_TYPE: str = "investor_review_note"
BANK_REVIEW_SIGNAL_TYPE: str = "bank_review_note"

_INVESTOR_REVIEW_SOURCE_ID: str = "source:investor_self_review"
_BANK_REVIEW_SOURCE_ID: str = "source:bank_self_review"

_DEFAULT_REVIEW_FREQUENCY: str = "QUARTERLY"
_DEFAULT_REVIEW_PHASE: str = "post_close"

_DEFAULT_INVESTOR_STATEMENT: str = "synthetic investor review note"
_DEFAULT_BANK_STATEMENT: str = "synthetic bank review note"


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReviewRoutineResult:
    """
    Aggregate result of one review-routine call. Carries both the
    engine result and the produced review-note signal so callers do
    not have to re-look-them-up from the kernel.

    Used by both ``run_investor_review`` and ``run_bank_review`` —
    the two flows are symmetric, so a single result type keeps the
    surface small.
    """

    result: RoutineExecutionResult
    signal: InformationSignal

    @property
    def run_id(self) -> str:
        return self.result.run_id

    @property
    def signal_id(self) -> str:
        return self.signal.signal_id

    @property
    def routine_id(self) -> str:
        return self.result.routine_id

    @property
    def routine_type(self) -> str:
        return self.result.routine_type

    @property
    def as_of_date(self) -> str:
        return self.result.as_of_date

    @property
    def status(self) -> str:
        return self.result.status


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _coerce_iso_date(value: date | str | None, *, kernel: Any) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value:
        return value
    if value is None:
        if (
            kernel.clock is not None
            and kernel.clock.current_date is not None
        ):
            return kernel.clock.current_date.isoformat()
        raise ValueError(
            "as_of_date is None and the kernel clock has no current_date; "
            "supply as_of_date explicitly."
        )
    raise TypeError(
        f"as_of_date must be a date / ISO string / None; got {value!r}"
    )


def _validate_required_string(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} is required and must be a non-empty string")
    return value


def _default_investor_routine_id(investor_id: str) -> str:
    return f"routine:{INVESTOR_REVIEW_ROUTINE_TYPE}:{investor_id}"


def _default_bank_routine_id(bank_id: str) -> str:
    return f"routine:{BANK_REVIEW_ROUTINE_TYPE}:{bank_id}"


def _default_request_id(routine_type: str, actor_id: str, as_of_date: str) -> str:
    return f"req:routine:{routine_type}:{actor_id}:{as_of_date}"


def _default_signal_id(routine_type: str, actor_id: str, as_of_date: str) -> str:
    return f"signal:{routine_type}:{actor_id}:{as_of_date}"


def _classify_input_refs(
    kernel: Any, input_refs: tuple[str, ...]
) -> dict[str, int]:
    """Count how many of the resolved input refs live in each
    relevant book.

    The classification is structural — we ask each book whether the
    ref id resolves there. Refs that resolve in none of the three
    canonical book types are bucketed as ``"other"`` so the totals
    always add up. v1.8.13 does **not** validate that refs *should*
    resolve; the classification is purely descriptive.
    """
    counts = {
        "signal": 0,
        "variable_observation": 0,
        "exposure": 0,
        "other": 0,
    }
    for ref in input_refs:
        if _try_get_signal(kernel, ref):
            counts["signal"] += 1
            continue
        if _try_get_variable_observation(kernel, ref):
            counts["variable_observation"] += 1
            continue
        if _try_get_exposure(kernel, ref):
            counts["exposure"] += 1
            continue
        counts["other"] += 1
    return counts


def _try_get_signal(kernel: Any, ref: str) -> bool:
    try:
        kernel.signals.get_signal(ref)
        return True
    except Exception:
        return False


def _try_get_variable_observation(kernel: Any, ref: str) -> bool:
    try:
        kernel.variables.get_observation(ref)
        return True
    except Exception:
        return False


def _try_get_exposure(kernel: Any, ref: str) -> bool:
    try:
        kernel.exposures.get_exposure(ref)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Interaction registration (idempotent)
# ---------------------------------------------------------------------------


def register_investor_review_interaction(kernel: Any) -> InteractionSpec:
    """Register or fetch the Investors → Investors self-loop
    review channel. Idempotent."""
    try:
        return kernel.interactions.get_interaction(
            INVESTOR_REVIEW_INTERACTION_ID
        )
    except Exception:
        pass

    spec = InteractionSpec(
        interaction_id=INVESTOR_REVIEW_INTERACTION_ID,
        source_space_id="investors",
        target_space_id="investors",
        interaction_type="investor_review",
        channel_type="investor_review_channel",
        direction="self_loop",
        frequency=_DEFAULT_REVIEW_FREQUENCY,
        phase_id=_DEFAULT_REVIEW_PHASE,
        visibility="public",
        enabled=True,
        output_ref_types=("InformationSignal",),
        routine_types_that_may_use_this_channel=(
            INVESTOR_REVIEW_ROUTINE_TYPE,
        ),
    )
    try:
        return kernel.interactions.add_interaction(spec)
    except DuplicateInteractionError:
        return kernel.interactions.get_interaction(
            INVESTOR_REVIEW_INTERACTION_ID
        )


def register_bank_review_interaction(kernel: Any) -> InteractionSpec:
    """Register or fetch the Banking → Banking self-loop credit-review
    channel. Idempotent."""
    try:
        return kernel.interactions.get_interaction(
            BANK_REVIEW_INTERACTION_ID
        )
    except Exception:
        pass

    spec = InteractionSpec(
        interaction_id=BANK_REVIEW_INTERACTION_ID,
        source_space_id="banking",
        target_space_id="banking",
        interaction_type="bank_credit_review",
        channel_type="bank_credit_review_channel",
        direction="self_loop",
        frequency=_DEFAULT_REVIEW_FREQUENCY,
        phase_id=_DEFAULT_REVIEW_PHASE,
        visibility="public",
        enabled=True,
        output_ref_types=("InformationSignal",),
        routine_types_that_may_use_this_channel=(
            BANK_REVIEW_ROUTINE_TYPE,
        ),
    )
    try:
        return kernel.interactions.add_interaction(spec)
    except DuplicateInteractionError:
        return kernel.interactions.get_interaction(
            BANK_REVIEW_INTERACTION_ID
        )


# ---------------------------------------------------------------------------
# Routine registration (idempotent)
# ---------------------------------------------------------------------------


def register_investor_review_routine(
    kernel: Any,
    *,
    investor_id: str,
    routine_id: str | None = None,
    frequency: str = _DEFAULT_REVIEW_FREQUENCY,
    phase_id: str = _DEFAULT_REVIEW_PHASE,
) -> RoutineSpec:
    """Register or fetch a per-investor ``investor_review`` routine
    spec. Idempotent."""
    _validate_required_string(investor_id, name="investor_id")
    rid = routine_id or _default_investor_routine_id(investor_id)
    try:
        return kernel.routines.get_routine(rid)
    except Exception:
        pass

    spec = RoutineSpec(
        routine_id=rid,
        routine_type=INVESTOR_REVIEW_ROUTINE_TYPE,
        owner_space_id="investors",
        owner_id=investor_id,
        frequency=frequency,
        phase_id=phase_id,
        enabled=True,
        required_input_ref_types=(),
        optional_input_ref_types=(
            "InformationSignal",
            "VariableObservation",
            "ExposureRecord",
        ),
        output_ref_types=("InformationSignal",),
        allowed_interaction_ids=(INVESTOR_REVIEW_INTERACTION_ID,),
        missing_input_policy="degraded",
    )
    try:
        return kernel.routines.add_routine(spec)
    except DuplicateRoutineError:
        return kernel.routines.get_routine(rid)


def register_bank_review_routine(
    kernel: Any,
    *,
    bank_id: str,
    routine_id: str | None = None,
    frequency: str = _DEFAULT_REVIEW_FREQUENCY,
    phase_id: str = _DEFAULT_REVIEW_PHASE,
) -> RoutineSpec:
    """Register or fetch a per-bank ``bank_review`` routine spec.
    Idempotent."""
    _validate_required_string(bank_id, name="bank_id")
    rid = routine_id or _default_bank_routine_id(bank_id)
    try:
        return kernel.routines.get_routine(rid)
    except Exception:
        pass

    spec = RoutineSpec(
        routine_id=rid,
        routine_type=BANK_REVIEW_ROUTINE_TYPE,
        owner_space_id="banking",
        owner_id=bank_id,
        frequency=frequency,
        phase_id=phase_id,
        enabled=True,
        required_input_ref_types=(),
        optional_input_ref_types=(
            "InformationSignal",
            "VariableObservation",
            "ExposureRecord",
        ),
        output_ref_types=("InformationSignal",),
        allowed_interaction_ids=(BANK_REVIEW_INTERACTION_ID,),
        missing_input_policy="degraded",
    )
    try:
        return kernel.routines.add_routine(spec)
    except DuplicateRoutineError:
        return kernel.routines.get_routine(rid)


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------


def run_investor_review(
    kernel: Any,
    *,
    investor_id: str,
    selected_observation_set_ids: tuple[str, ...] = (),
    as_of_date: date | str | None = None,
    phase_id: str = _DEFAULT_REVIEW_PHASE,
    routine_id: str | None = None,
    interaction_id: str = INVESTOR_REVIEW_INTERACTION_ID,
    confidence: float = 1.0,
    statement: str = _DEFAULT_INVESTOR_STATEMENT,
    explicit_input_refs: tuple[str, ...] = (),
) -> ReviewRoutineResult:
    """Run the v1.8.13 investor review routine.

    Flow (mirrors the v1.8.7 corporate-reporting pattern):

    1. Resolve ``as_of_date``.
    2. Build a :class:`RoutineExecutionRequest` declaring the
       investor-review interaction and the caller-supplied
       ``selected_observation_set_ids``.
    3. Call ``kernel.routine_engine.execute_request(request)`` —
       which collects refs out of each selected set, persists one
       ``RoutineRunRecord`` through ``RoutineBook.add_run_record``,
       and emits the ``ROUTINE_RUN_RECORDED`` ledger entry. Status
       defaults to ``"completed"`` when refs flow through, or
       ``"degraded"`` when they don't (v1.8.1 anti-scenario rule).
    4. Build one ``InformationSignal`` whose ``payload`` carries
       count summaries only (no economic interpretation) and whose
       ``related_ids`` / ``metadata`` link back to the run.
    5. Add the signal via ``kernel.signals.add_signal(signal)`` —
       which emits the ``SIGNAL_ADDED`` ledger entry.

    The pre-supplied ``output_refs=(signal_id,)`` on the request
    means the run record's ``output_refs`` already names the signal
    when the run is written; the signal's ``related_ids=(run_id,)``
    closes the loop.

    Side effects (the only writes v1.8.13 performs):

    - One ``RoutineRunRecord`` in ``RoutineBook``.
    - One ``InformationSignal`` in ``SignalBook``.
    - Two corresponding ledger entries (in that order).

    No price, ownership, contract, valuation, constraint, exposure,
    variable, attention, institution, or external-process state is
    mutated. v1.8.13 reviewers should reject any review-routine PR
    that crosses any of these boundaries.
    """
    return _run_review(
        kernel,
        actor_id=investor_id,
        actor_id_field_name="investor_id",
        routine_type=INVESTOR_REVIEW_ROUTINE_TYPE,
        signal_type=INVESTOR_REVIEW_SIGNAL_TYPE,
        source_id=_INVESTOR_REVIEW_SOURCE_ID,
        default_routine_id_fn=_default_investor_routine_id,
        selected_observation_set_ids=selected_observation_set_ids,
        as_of_date=as_of_date,
        phase_id=phase_id,
        routine_id=routine_id,
        interaction_id=interaction_id,
        confidence=confidence,
        statement=statement,
        explicit_input_refs=explicit_input_refs,
    )


def run_bank_review(
    kernel: Any,
    *,
    bank_id: str,
    selected_observation_set_ids: tuple[str, ...] = (),
    as_of_date: date | str | None = None,
    phase_id: str = _DEFAULT_REVIEW_PHASE,
    routine_id: str | None = None,
    interaction_id: str = BANK_REVIEW_INTERACTION_ID,
    confidence: float = 1.0,
    statement: str = _DEFAULT_BANK_STATEMENT,
    explicit_input_refs: tuple[str, ...] = (),
) -> ReviewRoutineResult:
    """Run the v1.8.13 bank review routine. Symmetric to
    :func:`run_investor_review` — see that docstring for the
    flow and side-effect contract."""
    return _run_review(
        kernel,
        actor_id=bank_id,
        actor_id_field_name="bank_id",
        routine_type=BANK_REVIEW_ROUTINE_TYPE,
        signal_type=BANK_REVIEW_SIGNAL_TYPE,
        source_id=_BANK_REVIEW_SOURCE_ID,
        default_routine_id_fn=_default_bank_routine_id,
        selected_observation_set_ids=selected_observation_set_ids,
        as_of_date=as_of_date,
        phase_id=phase_id,
        routine_id=routine_id,
        interaction_id=interaction_id,
        confidence=confidence,
        statement=statement,
        explicit_input_refs=explicit_input_refs,
    )


def _run_review(
    kernel: Any,
    *,
    actor_id: str,
    actor_id_field_name: str,
    routine_type: str,
    signal_type: str,
    source_id: str,
    default_routine_id_fn,
    selected_observation_set_ids: tuple[str, ...],
    as_of_date: date | str | None,
    phase_id: str,
    routine_id: str | None,
    interaction_id: str,
    confidence: float,
    statement: str,
    explicit_input_refs: tuple[str, ...],
) -> ReviewRoutineResult:
    _validate_required_string(actor_id, name=actor_id_field_name)

    iso_date = _coerce_iso_date(as_of_date, kernel=kernel)
    rid = routine_id or default_routine_id_fn(actor_id)
    request_id = _default_request_id(routine_type, actor_id, iso_date)
    signal_id = _default_signal_id(routine_type, actor_id, iso_date)

    request = RoutineExecutionRequest(
        request_id=request_id,
        routine_id=rid,
        as_of_date=iso_date,
        phase_id=phase_id,
        interaction_ids=(interaction_id,),
        selected_observation_set_ids=tuple(selected_observation_set_ids),
        explicit_input_refs=tuple(explicit_input_refs),
        output_refs=(signal_id,),
    )
    result = kernel.routine_engine.execute_request(request)

    counts = _classify_input_refs(kernel, result.input_refs)

    signal = InformationSignal(
        signal_id=signal_id,
        signal_type=signal_type,
        subject_id=actor_id,
        source_id=source_id,
        published_date=iso_date,
        effective_date=iso_date,
        visibility="public",
        confidence=confidence,
        payload={
            "actor_id": actor_id,
            "review_type": routine_type,
            "as_of_date": iso_date,
            "selected_ref_count": len(result.input_refs),
            "selected_signal_count": counts["signal"],
            "selected_variable_observation_count": counts[
                "variable_observation"
            ],
            "selected_exposure_count": counts["exposure"],
            "selected_other_count": counts["other"],
            "selected_observation_set_ids": list(
                selected_observation_set_ids
            ),
            "statement": statement,
            "status": result.status,
        },
        related_ids=(result.run_id,),
        metadata={
            "routine_run_id": result.run_id,
            "routine_type": routine_type,
            "interaction_id": interaction_id,
        },
    )
    kernel.signals.add_signal(signal)

    return ReviewRoutineResult(result=result, signal=signal)
