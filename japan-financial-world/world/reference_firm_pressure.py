"""
v1.9.4 Reference Firm Operating Pressure Assessment Mechanism.

This module ships the project's **first concrete mechanism** on
top of the v1.9.3 / v1.9.3.1 mechanism interface. It assesses
synthetic operating / financing pressure on a firm from resolved
variable observations and exposure records, then proposes one
diagnostic ``firm_operating_pressure_assessment`` signal. The
proposal is committed through the existing
``SignalBook.add_signal`` ledger path; the caller writes one
signal per call.

Hard boundary
-------------

This mechanism only proposes a **pressure assessment signal**.
It does **not**:

- update ``FirmState`` or any other firm-state book;
- update ``BalanceSheetView`` or any balance-sheet line item;
- update cash, leverage, revenue, margin, or any financial
  statement line item;
- imply accounting realisation;
- imply shareholder pressure (that is a stakeholder-pressure
  mechanism for a later milestone, with a different family);
- trigger any corporate action;
- make any economic decision;
- update prices, valuations, ownership, contracts, constraints,
  variables, or exposures.

Conceptual distinction
----------------------

- **Operating / financing pressure** (this mechanism) — input
  cost / energy / rates / FX / logistics variables create a
  diagnostic pressure score. That score is a signal an observer
  can attend to; it is not a financial statement claim.
- **Stakeholder pressure** (NOT in v1.9.4) — investor / bank /
  shareholder pressure on a firm. That belongs to a separate
  ``stakeholder_pressure_mechanism`` family in a later
  milestone.
- **Pressure assessment vs financial state mutation** —
  pressure is a diagnostic signal an investor or bank may use
  in a v1.9.5 / v1.9.6 review; it is *never* a substitute for a
  v1.9.x firm-financial-update mechanism (which does not exist
  and is not the next milestone).

Endogeneity discipline (v1.8.1 anti-scenario rule, restated)
------------------------------------------------------------

- The routine is the engine. The mechanism only runs when the
  caller invokes it; the kernel does not auto-fire it.
- Variable observations are *inputs*. The mechanism does not
  generate observations.
- **Absence of observations produces neutral / degraded output,
  not silence.** A request with no evidence still produces an
  assessment — every dimension at zero, ``status="degraded"``.
- Presence of observations does not auto-trigger any action.
  The signal is data; whether anyone reads it is a v1.9.5+ /
  caller-side concern.

Mechanism interface contract
----------------------------

The adapter implements the v1.9.3 / v1.9.3.1
:class:`MechanismAdapter` Protocol:

- ``apply(request: MechanismRunRequest) -> MechanismOutputBundle``
  reads ``request.evidence`` and returns proposals;
- the adapter does **not** accept a kernel parameter;
- the adapter does **not** read any book or the ledger;
- the adapter does **not** mutate ``request``;
- the adapter does **not** commit any proposal — that is the
  caller's job (in :func:`run_reference_firm_pressure_mechanism`).

Pressure dimensions
-------------------

Five synthetic pressure dimensions, each a deterministic float
in ``[0, 1]``:

- ``input_cost_pressure`` — material / supply variables ×
  input-cost exposures.
- ``energy_power_pressure`` — energy / power variables ×
  input-cost exposures.
- ``debt_service_pressure`` — rates / credit variables ×
  funding / discount-rate exposures.
- ``fx_translation_pressure`` — fx variables × translation
  exposures.
- ``logistics_pressure`` — logistics variables × input-cost or
  supply-chain exposures.

Plus one summary:

- ``overall_pressure`` — the deterministic mean of the five
  dimensions.

Calibration status: ``"synthetic"``. Magnitudes are synthetic
dependency strengths (per the v1.8.10 ``ExposureRecord``
contract), not calibrated sensitivities.

Caller responsibilities
-----------------------

The caller:

1. resolves variable observation ids into observation dicts via
   ``WorldVariableBook`` (each dict carries ``observation_id``,
   ``variable_id``, ``variable_group``, ``value``, ``unit``,
   ``as_of_date``);
2. resolves exposure ids into exposure dicts via
   ``ExposureBook`` (``exposure_id``, ``subject_id``,
   ``variable_id``, ``exposure_type``, ``metric``,
   ``magnitude``);
3. optionally resolves corporate-reporting signal ids into
   signal dicts via ``SignalBook``;
4. builds a :class:`MechanismRunRequest` with deterministic
   ``evidence_refs`` ordering (caller's choice — the adapter
   preserves it verbatim);
5. calls ``adapter.apply(request)``;
6. commits the one proposed signal through
   ``kernel.signals.add_signal``;
7. constructs a :class:`MechanismRunRecord` for audit and
   returns it alongside the result.

v1.9.4 deliberately does not introduce a new ``MechanismBook``;
the run record is returned as audit data on the result. A later
milestone may introduce a kernel-level book if it earns its
keep.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from world.mechanisms import (
    MechanismOutputBundle,
    MechanismRunRecord,
    MechanismRunRequest,
    MechanismSpec,
)
from world.signals import InformationSignal


# ---------------------------------------------------------------------------
# Controlled vocabulary
# ---------------------------------------------------------------------------


FIRM_PRESSURE_MODEL_ID: str = (
    "mechanism:firm_financial_mechanism:reference_firm_pressure_v0"
)
FIRM_PRESSURE_MODEL_FAMILY: str = "firm_financial_mechanism"
FIRM_PRESSURE_SIGNAL_TYPE: str = "firm_operating_pressure_assessment"
FIRM_PRESSURE_MECHANISM_VERSION: str = "0.1"
FIRM_PRESSURE_SOURCE_ID: str = "source:firm_operating_pressure_self_assessment"


# Pressure-dimension definitions: each names the exposure_types
# and variable_groups that contribute. Free-form vocabulary —
# extending the set just means adding a row.
_PRESSURE_DIMENSIONS: tuple[
    tuple[str, frozenset[str], frozenset[str]], ...
] = (
    (
        "input_cost_pressure",
        frozenset({"input_cost"}),
        frozenset({"material", "input_costs", "raw_materials"}),
    ),
    (
        "energy_power_pressure",
        frozenset({"input_cost"}),
        frozenset({"energy_power", "energy"}),
    ),
    (
        "debt_service_pressure",
        frozenset({"funding_cost", "discount_rate"}),
        frozenset({"rates", "credit"}),
    ),
    (
        "fx_translation_pressure",
        frozenset({"translation"}),
        frozenset({"fx"}),
    ),
    (
        "logistics_pressure",
        frozenset({"input_cost", "supply_chain"}),
        frozenset({"logistics", "freight", "shipping"}),
    ),
)


_PRESSURE_DIMENSION_NAMES: tuple[str, ...] = tuple(
    name for name, _, _ in _PRESSURE_DIMENSIONS
)


# ---------------------------------------------------------------------------
# Spec singleton
# ---------------------------------------------------------------------------


_DEFAULT_SPEC: MechanismSpec = MechanismSpec(
    model_id=FIRM_PRESSURE_MODEL_ID,
    model_family=FIRM_PRESSURE_MODEL_FAMILY,
    version=FIRM_PRESSURE_MECHANISM_VERSION,
    assumptions=(
        "synthetic_exposure_weights",
        "linear_pressure_aggregation",
        "no_lag_structure",
        "no_real_data",
        "no_calibration",
        "diagnostic_signal_only_no_financial_statement_update",
    ),
    calibration_status="synthetic",
    stochasticity="deterministic",
    required_inputs=(
        "VariableObservation",
        "ExposureRecord",
    ),
    output_types=("InformationSignal",),
    metadata={
        "pressure_dimensions": list(_PRESSURE_DIMENSION_NAMES),
        "boundary": "pressure_assessment_signal_only_no_financial_state_mutation",
    },
)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmPressureMechanismAdapter:
    """
    The v1.9.4 adapter. Pure function over
    :class:`MechanismRunRequest`; produces one
    :class:`MechanismOutputBundle` carrying a single proposed
    pressure-assessment signal.

    The adapter is **immutable** (frozen dataclass) and **does
    not** carry kernel state. Two adapters with the same spec
    produce byte-identical outputs on byte-identical requests
    (the deterministic-replay invariant).
    """

    spec: MechanismSpec = _DEFAULT_SPEC

    def apply(
        self, request: MechanismRunRequest
    ) -> MechanismOutputBundle:
        if not isinstance(request, MechanismRunRequest):
            raise TypeError(
                "request must be a MechanismRunRequest; "
                f"got {type(request).__name__}"
            )

        observations = list(_iter_records(request.evidence, "VariableObservation"))
        exposures = list(_iter_records(request.evidence, "ExposureRecord"))
        information_signals = list(
            _iter_records(request.evidence, "InformationSignal")
        )

        # Filter exposures to the firm whose pressure we are assessing.
        firm_exposures = [
            exp
            for exp in exposures
            if exp.get("subject_id") == request.actor_id
        ]

        # Compute the five pressure dimensions deterministically.
        pressures: dict[str, float] = {}
        for name, exposure_types, variable_groups in _PRESSURE_DIMENSIONS:
            pressures[name] = _compute_pressure_dimension(
                firm_exposures,
                observations,
                relevant_exposure_types=exposure_types,
                relevant_variable_groups=variable_groups,
            )

        overall_pressure = sum(pressures.values()) / len(pressures)

        # Status: degraded when there is no evidence to assess at
        # all, OR when every dimension came out at zero (the v1.8.1
        # anti-scenario rule: empty evidence is degraded, not
        # silence).
        evidence_present = bool(observations) or bool(firm_exposures)
        any_pressure = any(p > 0.0 for p in pressures.values())
        status = "completed" if evidence_present and any_pressure else "degraded"

        # Build the proposed signal mapping. Note: the caller is
        # responsible for committing this through SignalBook.
        signal_id = _default_signal_id(request.actor_id, request.as_of_date)
        related_ids = list(_iter_information_signal_ids(information_signals))

        proposed_signal: dict[str, Any] = {
            "signal_id": signal_id,
            "signal_type": FIRM_PRESSURE_SIGNAL_TYPE,
            "subject_id": request.actor_id,
            "source_id": FIRM_PRESSURE_SOURCE_ID,
            "published_date": request.as_of_date,
            "effective_date": request.as_of_date,
            "visibility": "public",
            "confidence": 1.0,
            "payload": {
                "actor_id": request.actor_id,
                "as_of_date": request.as_of_date,
                **pressures,
                "overall_pressure": overall_pressure,
                "evidence_counts": {
                    "variable_observations": len(observations),
                    "exposure_records": len(firm_exposures),
                    "information_signals": len(information_signals),
                },
                "calibration_status": "synthetic",
                "status": status,
            },
            "related_ids": related_ids,
            "metadata": {
                "model_id": self.spec.model_id,
                "model_family": self.spec.model_family,
                "version": self.spec.version,
                "calibration_status": self.spec.calibration_status,
                "boundary": (
                    "pressure_assessment_signal_only; "
                    "no financial-statement update; "
                    "no decision; no auto-trigger"
                ),
            },
        }

        return MechanismOutputBundle(
            request_id=request.request_id,
            model_id=self.spec.model_id,
            status=status,
            proposed_signals=(proposed_signal,),
            output_summary={
                **pressures,
                "overall_pressure": overall_pressure,
                "evidence_counts": {
                    "variable_observations": len(observations),
                    "exposure_records": len(firm_exposures),
                    "information_signals": len(information_signals),
                },
            },
            metadata={
                "model_id": self.spec.model_id,
                "calibration_status": self.spec.calibration_status,
            },
        )


# ---------------------------------------------------------------------------
# Pressure computation helpers
# ---------------------------------------------------------------------------


def _iter_records(evidence: Mapping[str, Any], key: str):
    """Yield record-dicts under ``evidence[key]`` if present.

    Returns an empty iterator for missing keys so the adapter
    tolerates incomplete evidence (the v1.8.1 anti-scenario
    rule: missing input is degraded, not failure).
    """
    bundle = evidence.get(key)
    if bundle is None:
        return
    if isinstance(bundle, Mapping):
        # Single record handed in as a dict — wrap.
        yield bundle
        return
    for entry in bundle:
        if isinstance(entry, Mapping):
            yield entry


def _iter_information_signal_ids(signals):
    for sig in signals:
        sid = sig.get("signal_id")
        if isinstance(sid, str) and sid:
            yield sid


def _compute_pressure_dimension(
    exposures: list[Mapping[str, Any]],
    observations: list[Mapping[str, Any]],
    *,
    relevant_exposure_types: frozenset[str],
    relevant_variable_groups: frozenset[str],
) -> float:
    """Combine exposures × observations into one pressure score
    in ``[0, 1]``.

    Algorithm (deterministic; documented in the module
    docstring):

    1. Collect ``variable_id``s of observations whose
       ``variable_group`` is in ``relevant_variable_groups``.
       This is the set of variables for which we have evidence
       in this dimension.
    2. Sum the magnitudes of exposures whose
       ``exposure_type`` is in ``relevant_exposure_types`` AND
       whose ``variable_id`` is in the set from step 1.
    3. Clamp the sum to ``[0, 1]``.

    A dimension with no relevant observations evaluates to 0;
    a dimension with no relevant exposures evaluates to 0;
    the dimension only contributes when both sides intersect
    (which is when the firm is actually exposed and the
    pressure source is observable).

    Synthetic-only: magnitudes are dependency strengths in
    ``[0, 1]``, not sensitivities. The clamp prevents pathological
    sums; it is not a saturation model.
    """
    relevant_var_ids: set[str] = set()
    for obs in observations:
        group = obs.get("variable_group")
        var_id = obs.get("variable_id")
        if (
            isinstance(group, str)
            and group in relevant_variable_groups
            and isinstance(var_id, str)
            and var_id
        ):
            relevant_var_ids.add(var_id)

    if not relevant_var_ids:
        return 0.0

    total = 0.0
    for exp in exposures:
        exp_type = exp.get("exposure_type")
        var_id = exp.get("variable_id")
        magnitude = exp.get("magnitude")
        if (
            isinstance(exp_type, str)
            and exp_type in relevant_exposure_types
            and isinstance(var_id, str)
            and var_id in relevant_var_ids
            and isinstance(magnitude, (int, float))
            and not isinstance(magnitude, bool)
        ):
            total += float(magnitude)

    return max(0.0, min(1.0, total))


# ---------------------------------------------------------------------------
# Result + caller helper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmPressureMechanismResult:
    """Aggregate result of one
    :func:`run_reference_firm_pressure_mechanism` call.

    Carries:

    - the :class:`MechanismRunRequest` the caller built (for
      replay);
    - the :class:`MechanismOutputBundle` the adapter returned
      (proposals; not yet committed);
    - the :class:`MechanismRunRecord` (audit data; v1.9.4 does
      not introduce a kernel-level mechanism book — the record
      is returned to the caller for inspection / future
      promotion);
    - the resulting ``signal_id`` once the caller committed the
      proposed signal.
    """

    request: MechanismRunRequest
    output: MechanismOutputBundle
    run_record: MechanismRunRecord
    signal_id: str
    pressure_summary: Mapping[str, float]

    @property
    def status(self) -> str:
        return self.output.status

    @property
    def overall_pressure(self) -> float:
        return float(self.pressure_summary.get("overall_pressure", 0.0))


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


def _default_signal_id(firm_id: str, as_of_date: str) -> str:
    return f"signal:{FIRM_PRESSURE_SIGNAL_TYPE}:{firm_id}:{as_of_date}"


def _default_request_id(firm_id: str, as_of_date: str) -> str:
    return f"req:firm_pressure:{firm_id}:{as_of_date}"


def run_reference_firm_pressure_mechanism(
    kernel: Any,
    *,
    firm_id: str,
    as_of_date: date | str | None = None,
    evidence_refs: Sequence[str] | None = None,
    variable_observation_ids: Sequence[str] | None = None,
    exposure_ids: Sequence[str] | None = None,
    corporate_signal_ids: Sequence[str] | None = None,
    request_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> FirmPressureMechanismResult:
    """
    Caller-side helper that resolves evidence from the kernel,
    invokes the v1.9.4 :class:`FirmPressureMechanismAdapter`,
    and commits the one proposed signal through
    ``kernel.signals.add_signal``.

    The adapter never sees ``kernel``. The contract:

    - **Caller** resolves ``variable_observation_ids`` from
      ``WorldVariableBook``, ``exposure_ids`` from
      ``ExposureBook``, and (optionally)
      ``corporate_signal_ids`` from ``SignalBook``. Each
      resolved record becomes a JSON-friendly dict in
      ``request.evidence``.
    - **Adapter** reads ``request.evidence`` only.
    - **Caller** commits the adapter's proposed signal.

    Side effects (the only writes v1.9.4 performs):

    - One ``InformationSignal`` in ``SignalBook`` (via
      ``add_signal``, which emits the existing ``signal_added``
      ledger entry).

    No ``firm_state``, ``balance_sheet``, ``valuation``,
    ``price``, ``ownership``, ``contract``, ``constraint``,
    ``variable``, ``exposure``, ``institution``, or
    ``external_process`` book is mutated. Tests pin every one
    of these.
    """
    if kernel is None:
        raise ValueError("kernel is required")
    if not isinstance(firm_id, str) or not firm_id:
        raise ValueError("firm_id is required and must be a non-empty string")

    iso_date = _coerce_iso_date(as_of_date, kernel=kernel)
    rid = request_id or _default_request_id(firm_id, iso_date)

    # ------------------------------------------------------------------
    # 1. Resolve evidence from books.
    # ------------------------------------------------------------------
    evidence: dict[str, list[dict[str, Any]]] = {
        "VariableObservation": [],
        "ExposureRecord": [],
        "InformationSignal": [],
    }

    for oid in tuple(variable_observation_ids or ()):
        obs = kernel.variables.get_observation(oid)
        try:
            spec = kernel.variables.get_variable(obs.variable_id)
            variable_group = spec.variable_group
        except Exception:
            variable_group = None
        evidence["VariableObservation"].append(
            {
                "observation_id": obs.observation_id,
                "variable_id": obs.variable_id,
                "variable_group": variable_group,
                "as_of_date": obs.as_of_date,
                "value": obs.value,
                "unit": obs.unit,
            }
        )

    for eid in tuple(exposure_ids or ()):
        exp = kernel.exposures.get_exposure(eid)
        evidence["ExposureRecord"].append(
            {
                "exposure_id": exp.exposure_id,
                "subject_id": exp.subject_id,
                "subject_type": exp.subject_type,
                "variable_id": exp.variable_id,
                "exposure_type": exp.exposure_type,
                "metric": exp.metric,
                "magnitude": float(exp.magnitude),
                "direction": exp.direction,
            }
        )

    for sid in tuple(corporate_signal_ids or ()):
        sig = kernel.signals.get_signal(sid)
        evidence["InformationSignal"].append(
            {
                "signal_id": sig.signal_id,
                "signal_type": sig.signal_type,
                "subject_id": sig.subject_id,
                "published_date": sig.published_date,
            }
        )

    # ------------------------------------------------------------------
    # 2. Build evidence_refs (caller-preserved order).
    # ------------------------------------------------------------------
    if evidence_refs is None:
        # Default deterministic concatenation: observations, then
        # exposures, then signals — matching the order the caller
        # passed them. Caller may override via the explicit
        # `evidence_refs` parameter to record a different lineage
        # order (e.g., chronological).
        resolved_refs: tuple[str, ...] = (
            tuple(variable_observation_ids or ())
            + tuple(exposure_ids or ())
            + tuple(corporate_signal_ids or ())
        )
    else:
        resolved_refs = tuple(evidence_refs)

    # ------------------------------------------------------------------
    # 3. Build the request.
    # ------------------------------------------------------------------
    request = MechanismRunRequest(
        request_id=rid,
        model_id=FIRM_PRESSURE_MODEL_ID,
        actor_id=firm_id,
        as_of_date=iso_date,
        selected_observation_set_ids=(),
        evidence_refs=resolved_refs,
        evidence=evidence,
        metadata=dict(metadata or {}),
    )

    # ------------------------------------------------------------------
    # 4. Apply the adapter (read-only; no kernel access).
    # ------------------------------------------------------------------
    adapter = FirmPressureMechanismAdapter()
    output = adapter.apply(request)

    # ------------------------------------------------------------------
    # 5. Commit the one proposed signal through SignalBook.
    # ------------------------------------------------------------------
    if not output.proposed_signals:
        raise RuntimeError(
            "FirmPressureMechanismAdapter returned no proposed signal; "
            "the v1.9.4 contract requires exactly one"
        )
    proposed = output.proposed_signals[0]

    signal = InformationSignal(
        signal_id=proposed["signal_id"],
        signal_type=proposed["signal_type"],
        subject_id=proposed["subject_id"],
        source_id=proposed["source_id"],
        published_date=proposed["published_date"],
        effective_date=proposed.get("effective_date", proposed["published_date"]),
        visibility=proposed.get("visibility", "public"),
        confidence=float(proposed.get("confidence", 1.0)),
        payload=dict(proposed.get("payload", {})),
        related_ids=tuple(proposed.get("related_ids", ())),
        metadata=dict(proposed.get("metadata", {})),
    )
    kernel.signals.add_signal(signal)

    # ------------------------------------------------------------------
    # 6. Build the audit run record.
    # ------------------------------------------------------------------
    summary: dict[str, float] = {
        name: float(output.output_summary.get(name, 0.0))
        for name in (*_PRESSURE_DIMENSION_NAMES, "overall_pressure")
    }

    run_record = MechanismRunRecord(
        run_id=f"mechanism_run:{request.request_id}",
        request_id=request.request_id,
        model_id=adapter.spec.model_id,
        model_family=adapter.spec.model_family,
        version=adapter.spec.version,
        actor_id=request.actor_id,
        as_of_date=request.as_of_date,
        status=output.status,
        input_refs=request.evidence_refs,
        committed_output_refs=(signal.signal_id,),
        metadata={
            "calibration_status": adapter.spec.calibration_status,
            "pressure_summary": summary,
        },
    )

    return FirmPressureMechanismResult(
        request=request,
        output=output,
        run_record=run_record,
        signal_id=signal.signal_id,
        pressure_summary=summary,
    )
