"""
v1.8.7 Reference routines — first concrete endogenous routine.

This module ships the project's first concrete routine on top of
the v1.8.3 / v1.8.4 / v1.8.5 / v1.8.6 substrate:

  ``corporate_quarterly_reporting`` — a Corporate → Corporate
  self-loop routine that produces one synthetic quarterly reporting
  signal through the existing ``RoutineEngine`` plumbing.

The routine is intentionally narrow:

- It runs entirely on the diagonal ``Corporate → Corporate`` cell
  of the v1.8.3 interaction tensor (a self-loop), per the v1.8.2
  design's "diagonal is first-class" rule.
- It produces **one** ``RoutineRunRecord`` and **one**
  ``InformationSignal`` per call. Nothing else is mutated.
- The signal's payload is **synthetic and minimal**: a small set
  of toy fields (revenue index, margin index, leverage hint,
  liquidity hint, confidence) plus a self-describing statement.
  No real financials are computed; no balance sheet is updated.
- The routine does **not** trigger investor reactions, bank
  reviews, valuation refreshes, price changes, lending decisions,
  corporate actions, or policy responses. Those are explicit
  prohibitions of v1.8.7 and remain so until separate concrete
  routines land in v1.8.8+.

Three small helpers form the v1.8.7 surface:

- :func:`register_corporate_reporting_interaction` —
  registers the shared ``interaction:corporate.reporting_preparation``
  channel on the kernel's ``InteractionBook`` (idempotent).
- :func:`register_corporate_quarterly_reporting_routine` —
  registers a per-firm ``RoutineSpec`` of type
  ``"corporate_quarterly_reporting"`` on the kernel's
  ``RoutineBook`` (idempotent).
- :func:`run_corporate_quarterly_reporting` — the routine itself.
  Validates through ``kernel.routine_engine.execute_request(...)``,
  then publishes one ``InformationSignal`` whose ``related_ids``
  include the routine run's ``run_id`` so the audit trail is
  reconstructable from the ledger alone.

Cross-references:

- ``InformationSignal.related_ids`` includes the routine's
  ``run_id`` (forward link from signal to run).
- ``InformationSignal.metadata["routine_run_id"]`` carries the
  same ``run_id`` for callers that prefer payload access.
- ``RoutineRunRecord.output_refs`` includes the produced
  ``signal_id`` (forward link from run to signal). This makes the
  pairing audit-discoverable from either side.

The two pieces of ledger evidence (`routine_run_recorded` and the
following `signal_added`) appear in the order they are written: the
run record first, then the signal. Tests pin this ordering.
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
# Constants
# ---------------------------------------------------------------------------


CORPORATE_REPORTING_INTERACTION_ID: str = (
    "interaction:corporate.reporting_preparation"
)
"""Shared self-loop channel id for the corporate quarterly reporting
routine. Idempotent registration: the helper checks for existing
specs before adding."""


CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE: str = (
    "corporate_quarterly_reporting"
)
"""Controlled-vocabulary routine type for the v1.8.7 routine. Mirrors
the type used in :data:`InteractionSpec.routine_types_that_may_use_this_channel`
on the corporate-reporting channel."""


CORPORATE_REPORTING_SIGNAL_TYPE: str = "corporate_quarterly_report"
"""``signal_type`` for the produced ``InformationSignal``. Distinct
from the v1.8.2 design's ``"earnings_disclosure"`` watched-type
because v1.8.7 does **not** compute earnings — it publishes a
synthetic report."""


CORPORATE_REPORTING_SOURCE_ID: str = "source:corporate_self_reporting"
"""``source_id`` on the produced ``InformationSignal``. Synthetic;
not a real news outlet or filing system."""


_DEFAULT_REPORTING_PHASE: str = "post_close"
"""Default ``phase_id`` per the v1.8.1 §43.1 example."""


_DEFAULT_REPORTING_FREQUENCY: str = "QUARTERLY"
"""Default ``frequency`` label on the routine spec. v1.8.7 does not
register any scheduler task; the label is informational."""


_DEFAULT_REPORTING_STATEMENT: str = "synthetic quarterly reporting signal"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CorporateReportingResult:
    """
    Aggregate result of one ``run_corporate_quarterly_reporting``
    call. Carries both the engine result and the produced signal so
    callers do not have to re-look-them-up from the kernel.
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
    def as_of_date(self) -> str:
        return self.result.as_of_date

    @property
    def status(self) -> str:
        return self.result.status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_iso_date(value: date | str | None, *, kernel: Any) -> str:
    """Return ``value`` coerced to ISO ``YYYY-MM-DD``, falling back
    to the kernel clock's current date if ``value`` is ``None``."""
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


def _default_routine_id(firm_id: str) -> str:
    return f"routine:{CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE}:{firm_id}"


def _default_request_id(firm_id: str, as_of_date: str) -> str:
    return (
        f"req:routine:{CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE}:"
        f"{firm_id}:{as_of_date}"
    )


def _default_signal_id(firm_id: str, as_of_date: str) -> str:
    return f"signal:corporate_quarterly_report:{firm_id}:{as_of_date}"


# ---------------------------------------------------------------------------
# Registration helpers (idempotent)
# ---------------------------------------------------------------------------


def register_corporate_reporting_interaction(kernel: Any) -> InteractionSpec:
    """
    Register (or fetch) the shared
    ``interaction:corporate.reporting_preparation`` self-loop channel
    on the kernel's ``InteractionBook``. Idempotent: re-registering
    returns the existing spec unchanged.

    The channel is the ``Corporate → Corporate`` self-loop the
    v1.8.7 routine publishes through.
    ``routine_types_that_may_use_this_channel`` is locked to
    ``("corporate_quarterly_reporting",)``.
    """
    try:
        return kernel.interactions.get_interaction(
            CORPORATE_REPORTING_INTERACTION_ID
        )
    except Exception:
        pass

    spec = InteractionSpec(
        interaction_id=CORPORATE_REPORTING_INTERACTION_ID,
        source_space_id="corporate",
        target_space_id="corporate",
        interaction_type="reporting_preparation",
        channel_type="quarterly_reporting",
        direction="self_loop",
        frequency=_DEFAULT_REPORTING_FREQUENCY,
        phase_id=_DEFAULT_REPORTING_PHASE,
        visibility="public",
        enabled=True,
        output_ref_types=("InformationSignal",),
        routine_types_that_may_use_this_channel=(
            CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE,
        ),
    )
    try:
        return kernel.interactions.add_interaction(spec)
    except DuplicateInteractionError:
        return kernel.interactions.get_interaction(
            CORPORATE_REPORTING_INTERACTION_ID
        )


def register_corporate_quarterly_reporting_routine(
    kernel: Any, *, firm_id: str, routine_id: str | None = None
) -> RoutineSpec:
    """
    Register (or fetch) a per-firm
    ``corporate_quarterly_reporting`` routine spec on the kernel's
    ``RoutineBook``. Idempotent: re-registering returns the existing
    spec unchanged.

    The spec's ``allowed_interaction_ids`` declares the
    corporate-reporting self-loop channel; v1.8.6 enforces both
    sides of the channel-permission predicate.
    """
    if not isinstance(firm_id, str) or not firm_id:
        raise ValueError("firm_id is required")
    rid = routine_id or _default_routine_id(firm_id)

    try:
        return kernel.routines.get_routine(rid)
    except Exception:
        pass

    spec = RoutineSpec(
        routine_id=rid,
        routine_type=CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE,
        owner_space_id="corporate",
        owner_id=firm_id,
        frequency=_DEFAULT_REPORTING_FREQUENCY,
        phase_id=_DEFAULT_REPORTING_PHASE,
        enabled=True,
        required_input_ref_types=(),
        optional_input_ref_types=(),
        output_ref_types=("InformationSignal",),
        allowed_interaction_ids=(CORPORATE_REPORTING_INTERACTION_ID,),
        missing_input_policy="degraded",
    )
    try:
        return kernel.routines.add_routine(spec)
    except DuplicateRoutineError:
        return kernel.routines.get_routine(rid)


# ---------------------------------------------------------------------------
# The routine itself
# ---------------------------------------------------------------------------


def run_corporate_quarterly_reporting(
    kernel: Any,
    *,
    firm_id: str,
    as_of_date: date | str | None = None,
    phase_id: str = _DEFAULT_REPORTING_PHASE,
    routine_id: str | None = None,
    interaction_id: str = CORPORATE_REPORTING_INTERACTION_ID,
    revenue_index: float = 100.0,
    margin_index: float = 0.10,
    leverage_hint: float = 1.0,
    liquidity_hint: float = 1.0,
    confidence: float = 1.0,
    explicit_input_refs: tuple[str, ...] | None = None,
    statement: str = _DEFAULT_REPORTING_STATEMENT,
) -> CorporateReportingResult:
    """
    Run the v1.8.7 corporate quarterly reporting routine for a firm.

    The flow:

    1. Resolve ``as_of_date`` (argument or ``kernel.clock``).
    2. Build a :class:`RoutineExecutionRequest` against the firm's
       ``corporate_quarterly_reporting`` routine spec, declaring
       the corporate-reporting self-loop interaction.
    3. Call ``kernel.routine_engine.execute_request(request)``,
       which validates interaction compatibility, persists one
       :class:`RoutineRunRecord` via
       ``RoutineBook.add_run_record``, and emits the
       ``routine_run_recorded`` ledger entry.
    4. Build one :class:`InformationSignal` whose ``related_ids``
       include the run id (so the signal is back-referenceable to
       the run from the ledger alone) and whose ``payload`` carries
       the synthetic toy fields.
    5. Add the signal via ``kernel.signals.add_signal(signal)``,
       which emits the ``signal_added`` ledger entry.

    Defaults:

    - ``explicit_input_refs`` defaults to ``(firm_id,)`` so the
      run is recorded as ``status="completed"``. Pass ``()`` to
      record a ``status="degraded"`` run (v1.8.1 anti-scenario
      discipline: a run with no inputs is *degraded*, not
      *failed*).
    - ``revenue_index``, ``margin_index``, ``leverage_hint``,
      ``liquidity_hint`` are illustrative round numbers chosen for
      traceability. They are **not** computed from any balance
      sheet, price book, or external observation. v1.8.7 does not
      compute economics.

    Returns a :class:`CorporateReportingResult` carrying both the
    engine result and the produced signal.

    Side effects (the only writes v1.8.7 performs):

    - One ``RoutineRunRecord`` in ``RoutineBook``.
    - One ``InformationSignal`` in ``SignalBook``.
    - The two corresponding ledger entries (in that order).

    No price, ownership, contract, valuation, constraint,
    relationship, institution, or external-process state is
    mutated. v1.8.7 reviewers should reject any routine PR that
    crosses any of these boundaries.
    """
    if not isinstance(firm_id, str) or not firm_id:
        raise ValueError("firm_id is required")

    iso_date = _coerce_iso_date(as_of_date, kernel=kernel)
    rid = routine_id or _default_routine_id(firm_id)
    request_id = _default_request_id(firm_id, iso_date)
    signal_id = _default_signal_id(firm_id, iso_date)

    if explicit_input_refs is None:
        # Default: include the firm_id so the run is "completed".
        # Caller can pass an empty tuple to record a "degraded" run
        # (v1.8.1 anti-scenario discipline).
        explicit_input_refs = (firm_id,)

    # Step 1-3: persist the routine run record through the engine.
    request = RoutineExecutionRequest(
        request_id=request_id,
        routine_id=rid,
        as_of_date=iso_date,
        phase_id=phase_id,
        interaction_ids=(interaction_id,),
        explicit_input_refs=tuple(explicit_input_refs),
        output_refs=(signal_id,),
    )
    result = kernel.routine_engine.execute_request(request)

    # Step 4-5: publish the synthetic reporting signal, linked back
    # to the run record by id.
    signal = InformationSignal(
        signal_id=signal_id,
        signal_type=CORPORATE_REPORTING_SIGNAL_TYPE,
        subject_id=firm_id,
        source_id=CORPORATE_REPORTING_SOURCE_ID,
        published_date=iso_date,
        effective_date=iso_date,
        visibility="public",
        confidence=confidence,
        payload={
            "firm_id": firm_id,
            "reporting_period": iso_date,
            "revenue_index": float(revenue_index),
            "margin_index": float(margin_index),
            "leverage_hint": float(leverage_hint),
            "liquidity_hint": float(liquidity_hint),
            "confidence": float(confidence),
            "statement": statement,
        },
        related_ids=(result.run_id,),
        metadata={
            "routine_run_id": result.run_id,
            "routine_type": CORPORATE_QUARTERLY_REPORTING_ROUTINE_TYPE,
            "interaction_id": interaction_id,
        },
    )
    kernel.signals.add_signal(signal)

    return CorporateReportingResult(result=result, signal=signal)
