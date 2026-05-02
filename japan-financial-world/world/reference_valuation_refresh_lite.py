"""
v1.9.5 Reference Valuation Refresh Lite Mechanism.

This module ships the project's **second concrete mechanism** on
top of the v1.9.3 / v1.9.3.1 mechanism interface. It consumes
the v1.9.4 firm-pressure-assessment signal (plus optional
corporate reporting signals, selected observation sets, variable
observations, and exposures), and proposes one **opinionated
synthetic** :class:`ValuationRecord` that is committed through
the existing v1.1 ``ValuationBook.add_valuation`` ledger path.

Hard boundary
-------------

This is **not a true valuation model.** It is a synthetic
reference mechanism showing how diagnostic pressure and selected
evidence can produce an auditable valuation claim. The mechanism
explicitly does **not**:

- form, observe, or move any market price;
- trade, allocate, or rebalance any portfolio;
- make a buy / sell / hold recommendation;
- make a lending decision;
- enforce or trip a covenant;
- update any firm financial statement, balance-sheet line item,
  cash, leverage, revenue, margin, or DSCR / LTV measure;
- imply that the produced ``estimated_value`` is the canonical
  truth — it is **one valuer's opinionated claim** under the
  synthetic, jurisdiction-neutral assumptions documented below;
- imply investment advice of any kind;
- ingest real data, calibrate to any real economy, or run a
  scenario engine.

What the mechanism *is*: an auditable transformation of
*pressure + evidence → opinionated valuation claim*. The claim is
data; what (if anything) any consumer of that claim does with it
is a v1.9.6+ / caller-side concern.

Method label
------------

The mechanism stamps every produced ``ValuationRecord`` with
``method = "synthetic_lite_pressure_adjusted"`` so a reader can
unambiguously identify the modelling style and reject any reading
that treats the claim as canonical.

Calibration vocabulary
----------------------

``calibration_status = "synthetic"``. The valuation arithmetic is
a small linear pressure-adjustment formula on a baseline value
the caller supplies. Magnitudes are illustrative round numbers,
not calibrated sensitivities (per the v1.8.10 ``ExposureRecord``
contract).

Algorithm (deterministic; documented inline in
:func:`_compute_valuation_payload`)
------------------------------------------------------------

Given a pressure assessment with ``overall_pressure ∈ [0, 1]``
and a caller-supplied ``baseline_value``:

    pressure_haircut_fraction
        = pressure_haircut_per_unit_pressure * overall_pressure
    estimated_value
        = baseline_value * (1 - clamp(pressure_haircut_fraction, 0, 1))
    confidence
        = clamp(
            1 - confidence_decay_per_unit_pressure * overall_pressure,
            0,
            1,
        )

Default coefficients are deliberately conservative
(``pressure_haircut_per_unit_pressure = 0.30``,
``confidence_decay_per_unit_pressure = 0.40``) — pressure of 1.0
on the canonical fixture trims the baseline value by 30% and
drops confidence to 0.6. Coefficients are caller-overridable
through ``parameters`` on the request, but the defaults are
recorded in ``MechanismSpec.assumptions`` so an auditor can read
them off the spec.

Degraded path
-------------

If no pressure assessment signal is present in the evidence, the
mechanism returns ``status = "degraded"`` and proposes a
**baseline-only** valuation: ``estimated_value = baseline_value``,
``confidence = 1.0`` (when a baseline is supplied) or
``estimated_value = None`` (when no baseline is supplied either).
The mechanism never crashes on missing optional evidence.

Mechanism interface contract
----------------------------

The adapter implements the v1.9.3 / v1.9.3.1
:class:`MechanismAdapter` Protocol:

- ``apply(request: MechanismRunRequest) -> MechanismOutputBundle``
  reads ``request.evidence`` and ``request.parameters`` only;
- the adapter does **not** accept a kernel parameter;
- the adapter does **not** read any book or the ledger;
- the adapter does **not** mutate ``request``;
- the adapter does **not** commit any proposal — that is the
  caller's job in :func:`run_reference_valuation_refresh_lite`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from world.evidence import (
    ActorContextFrame,
    EvidenceResolutionError,
    StrictEvidenceResolutionError,
    resolve_actor_context,
)
from world.mechanisms import (
    MechanismOutputBundle,
    MechanismRunRecord,
    MechanismRunRequest,
    MechanismSpec,
)
from world.valuations import (
    UnknownValuationError,
    ValuationRecord,
)


# ---------------------------------------------------------------------------
# Controlled vocabulary
# ---------------------------------------------------------------------------


VALUATION_REFRESH_MODEL_ID: str = (
    "mechanism:valuation_mechanism:reference_valuation_refresh_lite_v0"
)
VALUATION_REFRESH_MODEL_FAMILY: str = "valuation_mechanism"
VALUATION_REFRESH_MECHANISM_VERSION: str = "0.1"
VALUATION_REFRESH_METHOD_LABEL: str = "synthetic_lite_pressure_adjusted"
VALUATION_REFRESH_VALUATION_TYPE: str = "synthetic_firm_equity_estimate"
VALUATION_REFRESH_PURPOSE: str = "reference_pressure_aware_valuation"

# Pressure-signal type the v1.9.4 mechanism emits (kept as a
# string here so the import graph stays one-way: v1.9.5 consumes
# v1.9.4's *output*, not v1.9.4's module surface).
_FIRM_PRESSURE_SIGNAL_TYPE: str = "firm_operating_pressure_assessment"

# Default coefficients (caller-overridable through
# request.parameters). Synthetic; not calibrated.
_DEFAULT_PRESSURE_HAIRCUT_PER_UNIT_PRESSURE: float = 0.30
_DEFAULT_CONFIDENCE_DECAY_PER_UNIT_PRESSURE: float = 0.40


# ---------------------------------------------------------------------------
# Spec singleton
# ---------------------------------------------------------------------------


_DEFAULT_SPEC: MechanismSpec = MechanismSpec(
    model_id=VALUATION_REFRESH_MODEL_ID,
    model_family=VALUATION_REFRESH_MODEL_FAMILY,
    version=VALUATION_REFRESH_MECHANISM_VERSION,
    assumptions=(
        "linear_pressure_haircut_on_baseline_value",
        f"default_pressure_haircut_per_unit_pressure={_DEFAULT_PRESSURE_HAIRCUT_PER_UNIT_PRESSURE}",
        f"default_confidence_decay_per_unit_pressure={_DEFAULT_CONFIDENCE_DECAY_PER_UNIT_PRESSURE}",
        "baseline_value_supplied_by_caller_not_observed",
        "no_real_data",
        "no_calibration",
        "opinionated_claim_not_canonical_truth",
        "no_price_movement",
        "no_decision",
    ),
    calibration_status="synthetic",
    stochasticity="deterministic",
    required_inputs=(
        # The pressure signal is the primary input; the others are
        # optional and used only to populate `inputs` / `related_ids`
        # for audit lineage.
        "InformationSignal",
        "VariableObservation",
        "ExposureRecord",
        "SelectedObservationSet",
    ),
    output_types=("ValuationRecord",),
    metadata={
        "method": VALUATION_REFRESH_METHOD_LABEL,
        "valuation_type": VALUATION_REFRESH_VALUATION_TYPE,
        "purpose": VALUATION_REFRESH_PURPOSE,
        "boundary": (
            "valuation_claim_only; no_price_movement; "
            "no_investment_advice; synthetic_only; "
            "no_canonical_truth_claim"
        ),
    },
)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValuationRefreshLiteAdapter:
    """
    The v1.9.5 adapter. Pure function over
    :class:`MechanismRunRequest`; produces one
    :class:`MechanismOutputBundle` carrying a single proposed
    :class:`ValuationRecord` mapping.

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

        signals = list(_iter_records(request.evidence, "InformationSignal"))
        observations = list(_iter_records(request.evidence, "VariableObservation"))
        exposures = list(_iter_records(request.evidence, "ExposureRecord"))
        selections = list(
            _iter_records(request.evidence, "SelectedObservationSet")
        )

        # Pull the firm pressure signal (the primary input).
        pressure_signal = _find_pressure_signal(signals, request.actor_id)
        overall_pressure = _safe_float(
            (pressure_signal or {}).get("payload", {}).get("overall_pressure"),
            default=0.0,
        )
        pressure_signal_id = (
            pressure_signal.get("signal_id") if pressure_signal else None
        )
        pressure_status = (
            (pressure_signal or {}).get("payload", {}).get("status")
        )

        # Caller-supplied parameters: baseline_value (optional),
        # plus the two coefficient overrides.
        params = request.parameters
        baseline_value = _safe_float(params.get("baseline_value"), default=None)
        haircut_coef = _safe_float(
            params.get("pressure_haircut_per_unit_pressure"),
            default=_DEFAULT_PRESSURE_HAIRCUT_PER_UNIT_PRESSURE,
        )
        confidence_decay = _safe_float(
            params.get("confidence_decay_per_unit_pressure"),
            default=_DEFAULT_CONFIDENCE_DECAY_PER_UNIT_PRESSURE,
        )
        currency = (
            params.get("currency") if isinstance(params.get("currency"), str)
            else "unspecified"
        ) or "unspecified"
        numeraire = (
            params.get("numeraire")
            if isinstance(params.get("numeraire"), str)
            else "unspecified"
        ) or "unspecified"
        valuation_id_override = params.get("valuation_id")

        # Compute estimated_value + confidence.
        if pressure_signal is None:
            # Degraded: no pressure evidence. Conservative output.
            status = "degraded"
            if baseline_value is not None:
                estimated_value: float | None = baseline_value
                confidence = 1.0
            else:
                estimated_value = None
                confidence = 0.0
        else:
            status = "completed"
            haircut_fraction = max(
                0.0, min(1.0, haircut_coef * overall_pressure)
            )
            if baseline_value is None:
                estimated_value = None
                confidence = max(
                    0.0, min(1.0, 1.0 - confidence_decay * overall_pressure)
                )
            else:
                estimated_value = baseline_value * (1.0 - haircut_fraction)
                confidence = max(
                    0.0, min(1.0, 1.0 - confidence_decay * overall_pressure)
                )

        # Build provenance.
        related_ids: list[str] = []
        if pressure_signal_id:
            related_ids.append(pressure_signal_id)
        for sig in signals:
            sid = sig.get("signal_id")
            if (
                isinstance(sid, str)
                and sid
                and sid not in related_ids
                and sig.get("signal_type") != _FIRM_PRESSURE_SIGNAL_TYPE
            ):
                related_ids.append(sid)
        for sel in selections:
            sid = sel.get("selection_id")
            if isinstance(sid, str) and sid and sid not in related_ids:
                related_ids.append(sid)

        # Build inputs (audit-friendly summary; keep it small so
        # the ledger payload doesn't bloat).
        inputs_summary: dict[str, Any] = {
            "overall_pressure": overall_pressure,
            "baseline_value": baseline_value,
            "pressure_signal_id": pressure_signal_id,
            "evidence_counts": {
                "information_signals": len(signals),
                "variable_observations": len(observations),
                "exposure_records": len(exposures),
                "selected_observation_sets": len(selections),
            },
            "pressure_signal_status": pressure_status,
        }

        valuation_id = (
            valuation_id_override
            if isinstance(valuation_id_override, str) and valuation_id_override
            else _default_valuation_id(request.actor_id, request.as_of_date)
        )

        proposed_valuation: dict[str, Any] = {
            "valuation_id": valuation_id,
            "subject_id": request.actor_id,
            # The valuer is supplied via metadata so the adapter
            # need not look it up; the caller helper can override
            # via parameters["valuer_id"] (see below).
            "valuer_id": (
                params.get("valuer_id")
                if isinstance(params.get("valuer_id"), str)
                and params.get("valuer_id")
                else f"valuer:{self.spec.model_id}"
            ),
            "valuation_type": VALUATION_REFRESH_VALUATION_TYPE,
            "purpose": VALUATION_REFRESH_PURPOSE,
            "method": VALUATION_REFRESH_METHOD_LABEL,
            "as_of_date": request.as_of_date,
            "estimated_value": estimated_value,
            "currency": currency,
            "numeraire": numeraire,
            "confidence": confidence,
            "assumptions": {
                "pressure_haircut_per_unit_pressure": haircut_coef,
                "confidence_decay_per_unit_pressure": confidence_decay,
                "linear_pressure_haircut_on_baseline_value": True,
                "baseline_value_supplied_by_caller": baseline_value is not None,
            },
            "inputs": inputs_summary,
            "related_ids": related_ids,
            "metadata": {
                "model_id": self.spec.model_id,
                "model_family": self.spec.model_family,
                "version": self.spec.version,
                "calibration_status": self.spec.calibration_status,
                "method": VALUATION_REFRESH_METHOD_LABEL,
                "no_price_movement": True,
                "no_investment_advice": True,
                "synthetic_only": True,
                "pressure_signal_id": pressure_signal_id,
                "boundary": (
                    "valuation_claim_only; "
                    "no_price_movement; "
                    "no_investment_advice; "
                    "synthetic_only; "
                    "no_canonical_truth_claim"
                ),
            },
        }

        return MechanismOutputBundle(
            request_id=request.request_id,
            model_id=self.spec.model_id,
            status=status,
            proposed_valuation_records=(proposed_valuation,),
            output_summary={
                "estimated_value": estimated_value,
                "confidence": confidence,
                "overall_pressure": overall_pressure,
                "baseline_value": baseline_value,
                "pressure_signal_id": pressure_signal_id,
                "method": VALUATION_REFRESH_METHOD_LABEL,
            },
            metadata={
                "model_id": self.spec.model_id,
                "calibration_status": self.spec.calibration_status,
            },
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _iter_records(evidence: Mapping[str, Any], key: str):
    """Yield record-dicts under ``evidence[key]`` if present.

    Returns an empty iterator for missing keys so the adapter
    tolerates incomplete evidence (the v1.8.1 anti-scenario
    rule).
    """
    bundle = evidence.get(key)
    if bundle is None:
        return
    if isinstance(bundle, Mapping):
        yield bundle
        return
    for entry in bundle:
        if isinstance(entry, Mapping):
            yield entry


def _find_pressure_signal(
    signals: list[Mapping[str, Any]], actor_id: str
) -> Mapping[str, Any] | None:
    """Pick the one v1.9.4 firm-pressure-assessment signal that
    matches ``actor_id``. Returns the first match in
    declaration order; returns ``None`` if none.
    """
    for sig in signals:
        if (
            sig.get("signal_type") == _FIRM_PRESSURE_SIGNAL_TYPE
            and sig.get("subject_id") == actor_id
        ):
            return sig
    return None


def _safe_float(value: Any, *, default: float | None) -> float | None:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    return default


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


def _default_valuation_id(firm_id: str, as_of_date: str) -> str:
    return f"valuation:reference_lite:{firm_id}:{as_of_date}"


def _default_request_id(firm_id: str, as_of_date: str) -> str:
    return f"req:valuation_refresh_lite:{firm_id}:{as_of_date}"


# ---------------------------------------------------------------------------
# Caller-side helper + result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValuationRefreshLiteResult:
    """Aggregate result of one
    :func:`run_reference_valuation_refresh_lite` call.

    Carries the request, the adapter's output bundle, the audit
    :class:`MechanismRunRecord`, and the resulting
    ``valuation_id`` once the caller committed the proposed
    record.
    """

    request: MechanismRunRequest
    output: MechanismOutputBundle
    run_record: MechanismRunRecord
    valuation_id: str
    valuation_summary: Mapping[str, Any]

    @property
    def status(self) -> str:
        return self.output.status

    @property
    def estimated_value(self) -> float | None:
        return self.valuation_summary.get("estimated_value")

    @property
    def confidence(self) -> float:
        return float(self.valuation_summary.get("confidence", 0.0))


def run_reference_valuation_refresh_lite(
    kernel: Any,
    *,
    firm_id: str,
    valuer_id: str,
    as_of_date: date | str | None = None,
    pressure_signal_ids: Sequence[str] | None = None,
    corporate_signal_ids: Sequence[str] | None = None,
    selected_observation_set_ids: Sequence[str] | None = None,
    variable_observation_ids: Sequence[str] | None = None,
    exposure_ids: Sequence[str] | None = None,
    baseline_value: float | None = None,
    currency: str = "unspecified",
    numeraire: str = "unspecified",
    pressure_haircut_per_unit_pressure: float | None = None,
    confidence_decay_per_unit_pressure: float | None = None,
    evidence_refs: Sequence[str] | None = None,
    request_id: str | None = None,
    valuation_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ValuationRefreshLiteResult:
    """
    Caller-side helper that resolves evidence from the kernel,
    invokes the v1.9.5 :class:`ValuationRefreshLiteAdapter`, and
    commits the one proposed :class:`ValuationRecord` through
    ``kernel.valuations.add_valuation``.

    The adapter never sees ``kernel``. The contract:

    - **Caller** resolves ``pressure_signal_ids`` (the v1.9.4
      firm-pressure-assessment signals), ``corporate_signal_ids``,
      ``selected_observation_set_ids``,
      ``variable_observation_ids``, and ``exposure_ids`` from the
      respective books. Each resolved record becomes a
      JSON-friendly dict in ``request.evidence``.
    - **Adapter** reads ``request.evidence`` +
      ``request.parameters`` only.
    - **Caller** commits the adapter's proposed valuation.

    Side effects (the only writes v1.9.5 performs):

    - One :class:`ValuationRecord` in
      :class:`world.valuations.ValuationBook` (via
      ``add_valuation``, which emits the existing
      ``valuation_added`` ledger entry).

    No price, ownership, contract, constraint, exposure, variable,
    institution, external-process, relationship, routine,
    attention, or interaction state is mutated. Tests pin every
    one of these.

    Parameters of note
    ------------------
    - ``valuer_id``: required; identifies the entity whose opinion
      is being recorded (an investor, an analyst desk, etc.).
      Free-form string; not validated against the registry.
    - ``baseline_value``: optional float. The pressure-haircut
      formula uses this as the starting point; without a baseline
      the mechanism still produces a record (with
      ``estimated_value=None``) but the claim is degraded.
    - ``currency`` / ``numeraire``: passed through to the
      :class:`ValuationRecord`. Default ``"unspecified"`` (the
      v1.1 neutral label).
    - ``pressure_haircut_per_unit_pressure`` /
      ``confidence_decay_per_unit_pressure``: optional
      coefficient overrides. Defaults are documented in the
      module docstring and embedded in
      ``MechanismSpec.assumptions``.
    """
    if kernel is None:
        raise ValueError("kernel is required")
    if not isinstance(firm_id, str) or not firm_id:
        raise ValueError("firm_id is required and must be a non-empty string")
    if not isinstance(valuer_id, str) or not valuer_id:
        raise ValueError("valuer_id is required and must be a non-empty string")

    iso_date = _coerce_iso_date(as_of_date, kernel=kernel)
    rid = request_id or _default_request_id(firm_id, iso_date)

    # ------------------------------------------------------------------
    # 1. Resolve evidence from books.
    # ------------------------------------------------------------------
    evidence: dict[str, list[dict[str, Any]]] = {
        "InformationSignal": [],
        "VariableObservation": [],
        "ExposureRecord": [],
        "SelectedObservationSet": [],
    }

    for sid in tuple(pressure_signal_ids or ()) + tuple(corporate_signal_ids or ()):
        sig = kernel.signals.get_signal(sid)
        evidence["InformationSignal"].append(
            {
                "signal_id": sig.signal_id,
                "signal_type": sig.signal_type,
                "subject_id": sig.subject_id,
                "source_id": sig.source_id,
                "published_date": sig.published_date,
                "payload": dict(sig.payload),
                "metadata": dict(sig.metadata),
            }
        )

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

    for sel_id in tuple(selected_observation_set_ids or ()):
        sel = kernel.attention.get_selection(sel_id)
        evidence["SelectedObservationSet"].append(
            {
                "selection_id": sel.selection_id,
                "actor_id": sel.actor_id,
                "menu_id": sel.menu_id,
                "selected_refs": list(sel.selected_refs),
                "as_of_date": sel.as_of_date,
            }
        )

    # ------------------------------------------------------------------
    # 2. Build evidence_refs (caller-preserved order).
    # ------------------------------------------------------------------
    if evidence_refs is None:
        resolved_refs: tuple[str, ...] = (
            tuple(pressure_signal_ids or ())
            + tuple(corporate_signal_ids or ())
            + tuple(selected_observation_set_ids or ())
            + tuple(variable_observation_ids or ())
            + tuple(exposure_ids or ())
        )
    else:
        resolved_refs = tuple(evidence_refs)

    # ------------------------------------------------------------------
    # 3. Build adapter parameters.
    # ------------------------------------------------------------------
    parameters: dict[str, Any] = {
        "valuer_id": valuer_id,
        "currency": currency,
        "numeraire": numeraire,
    }
    if baseline_value is not None:
        parameters["baseline_value"] = float(baseline_value)
    if pressure_haircut_per_unit_pressure is not None:
        parameters["pressure_haircut_per_unit_pressure"] = float(
            pressure_haircut_per_unit_pressure
        )
    if confidence_decay_per_unit_pressure is not None:
        parameters["confidence_decay_per_unit_pressure"] = float(
            confidence_decay_per_unit_pressure
        )
    if valuation_id is not None:
        parameters["valuation_id"] = valuation_id

    # ------------------------------------------------------------------
    # 4. Build the request.
    # ------------------------------------------------------------------
    request = MechanismRunRequest(
        request_id=rid,
        model_id=VALUATION_REFRESH_MODEL_ID,
        actor_id=firm_id,
        as_of_date=iso_date,
        selected_observation_set_ids=tuple(selected_observation_set_ids or ()),
        evidence_refs=resolved_refs,
        evidence=evidence,
        parameters=parameters,
        metadata=dict(metadata or {}),
    )

    # ------------------------------------------------------------------
    # 5. Apply the adapter (read-only; no kernel access).
    # ------------------------------------------------------------------
    adapter = ValuationRefreshLiteAdapter()
    output = adapter.apply(request)

    # ------------------------------------------------------------------
    # 6. Commit the one proposed valuation through ValuationBook.
    # ------------------------------------------------------------------
    if not output.proposed_valuation_records:
        raise RuntimeError(
            "ValuationRefreshLiteAdapter returned no proposed valuation; "
            "the v1.9.5 contract requires exactly one"
        )
    proposed = output.proposed_valuation_records[0]

    record = ValuationRecord(
        valuation_id=proposed["valuation_id"],
        subject_id=proposed["subject_id"],
        valuer_id=proposed["valuer_id"],
        valuation_type=proposed["valuation_type"],
        purpose=proposed["purpose"],
        method=proposed["method"],
        as_of_date=proposed["as_of_date"],
        estimated_value=proposed.get("estimated_value"),
        currency=proposed.get("currency", "unspecified"),
        numeraire=proposed.get("numeraire", "unspecified"),
        confidence=float(proposed.get("confidence", 1.0)),
        assumptions=dict(proposed.get("assumptions", {})),
        inputs=dict(proposed.get("inputs", {})),
        related_ids=tuple(proposed.get("related_ids", ())),
        metadata=dict(proposed.get("metadata", {})),
    )
    kernel.valuations.add_valuation(record)

    # ------------------------------------------------------------------
    # 7. Audit run record.
    # ------------------------------------------------------------------
    summary: dict[str, Any] = {
        "estimated_value": output.output_summary.get("estimated_value"),
        "confidence": float(output.output_summary.get("confidence", 0.0)),
        "overall_pressure": float(
            output.output_summary.get("overall_pressure", 0.0)
        ),
        "baseline_value": output.output_summary.get("baseline_value"),
        "pressure_signal_id": output.output_summary.get("pressure_signal_id"),
        "method": output.output_summary.get("method"),
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
        committed_output_refs=(record.valuation_id,),
        metadata={
            "calibration_status": adapter.spec.calibration_status,
            "valuation_summary": summary,
        },
    )

    return ValuationRefreshLiteResult(
        request=request,
        output=output,
        run_record=run_record,
        valuation_id=record.valuation_id,
        valuation_summary=summary,
    )


# ---------------------------------------------------------------------------
# v1.12.5 — attention-conditioned valuation refresh lite helper
# ---------------------------------------------------------------------------


# v1.12.5 — small, documented, deterministic synthetic deltas. The
# attention-conditioned helper applies these on top of the v1.9.5
# pressure-haircut formula so the resulting valuation is sensitive
# to *what evidence the valuer actually selected*. Magnitudes are
# illustrative round numbers; the qualitative ordering (more
# resolved evidence → higher confidence; restrictive market /
# unresolved refs → lower confidence; restrictive market →
# additional small downward adjustment to estimated_value) is what
# tests pin, never specific calibrated numbers.
_ATTN_CONFIDENCE_RESOLVED_BUCKET_BONUS: float = 0.02
_ATTN_CONFIDENCE_RESOLVED_BUCKET_BONUS_CAP: float = 0.10
_ATTN_CONFIDENCE_UNRESOLVED_PENALTY: float = 0.05
_ATTN_CONFIDENCE_UNRESOLVED_PENALTY_CAP: float = 0.20
_ATTN_RESTRICTIVE_MARKET_VALUE_HAIRCUT: float = 0.02
_ATTN_RESTRICTIVE_RISK_APPETITE_VALUE_HAIRCUT: float = 0.01
_ATTN_PRESSURE_HIGH_THRESHOLD: float = 0.7

_RESTRICTIVE_OVERALL_LABEL: str = "selective_or_constrained"
_RESTRICTIVE_RISK_APPETITE_LABEL: str = "risk_off"


def run_attention_conditioned_valuation_refresh_lite(
    kernel: Any,
    *,
    firm_id: str,
    valuer_id: str,
    as_of_date: date | str | None = None,
    selected_observation_set_ids: Sequence[str] = (),
    explicit_pressure_signal_ids: Sequence[str] = (),
    explicit_corporate_signal_ids: Sequence[str] = (),
    explicit_firm_state_ids: Sequence[str] = (),
    explicit_market_readout_ids: Sequence[str] = (),
    explicit_market_environment_state_ids: Sequence[str] = (),
    explicit_variable_observation_ids: Sequence[str] = (),
    explicit_exposure_ids: Sequence[str] = (),
    baseline_value: float | None = None,
    currency: str = "unspecified",
    numeraire: str = "unspecified",
    pressure_haircut_per_unit_pressure: float | None = None,
    confidence_decay_per_unit_pressure: float | None = None,
    valuation_id: str | None = None,
    request_id: str | None = None,
    strict: bool = False,
    metadata: Mapping[str, Any] | None = None,
) -> ValuationRefreshLiteResult:
    """
    v1.12.5 — attention-conditioned valuation-refresh-lite helper.

    Builds an :class:`ActorContextFrame` for the valuer (treated as
    the actor whose attention conditions this run) on
    ``(firm_id, as_of_date)`` via the v1.12.3
    :func:`world.evidence.resolve_actor_context` substrate, then
    runs the v1.9.5 pressure-haircut adapter on **only the resolved
    frame ids**, and applies a small documented v1.12.5 synthetic
    delta to the produced ``estimated_value`` and ``confidence``
    based on what the resolver surfaced for *this* valuer.

    Idempotent: a valuation already present under the same
    ``valuation_id`` returns the existing record unchanged. The
    helper is read-only over every other source-of-truth book; it
    writes only to ``kernel.valuations`` and the kernel ledger via
    ``ValuationBook.add_valuation``.

    The helper reads only what the resolver surfaced for *this*
    valuer on *this* date — never a global book scan. Pressure
    signals, corporate signals, firm states, market readouts,
    market environment states, variable observations, and exposures
    can all be surfaced through the actor's ``SelectedObservationSet``
    selection refs OR through the explicit-id kwargs the helper
    exposes. Resolved ids land in the matching evidence bucket on
    the produced :class:`ValuationRecord`'s ``related_ids`` /
    ``inputs`` fields; unresolved refs land in the record's
    ``metadata["unresolved_refs"]`` list. The resolver's
    ``context_frame_id`` / ``status`` / ``confidence`` are stamped
    on ``metadata``.

    The helper does **not**:

    - introduce real data ingestion or any Japan-specific
      calibration;
    - compute beta, WACC, D/E, equity premium, or cost of capital;
    - decide impairment;
    - recommend an investment / form a price / form a target price
      / form an expected return;
    - match orders / clear trades / execute any DCM/ECM action;
    - dispatch to an LLM agent or an external solver;
    - mutate any other source-of-truth book in the kernel;
    - scan books globally — only the resolver's surfaced ids drive
      classification.

    The synthetic delta v1.12.5 introduces (small, documented,
    deterministic) on top of the v1.9.5 formula:

    - **More resolved evidence**:
      ``confidence += 0.02 * resolved_buckets`` (capped at +0.10).
      Where ``resolved_buckets`` counts how many of the helper's
      seven evidence buckets had at least one resolved id.
    - **Unresolved refs**:
      ``confidence -= 0.05 * unresolved_count`` (capped at -0.20).
    - **Restrictive market readout / environment**:
      ``estimated_value *= 1 - 0.02`` if any resolved readout has
      ``overall_market_access_label == "selective_or_constrained"``
      OR any resolved environment state has the same label.
    - **risk_off market environment**:
      additional ``estimated_value *= 1 - 0.01``.

    The deltas only fire when ``estimated_value`` is not ``None``;
    confidence is always clamped to ``[0, 1]``. Tests pin the
    qualitative ordering (more cited → higher confidence;
    restrictive → lower estimated_value), never the absolute
    arithmetic.

    Strict mode (``strict=True``) is forwarded to the resolver and
    raises :class:`StrictEvidenceResolutionError` on any unresolved
    id; the helper does not commit a valuation in that case.
    """
    if kernel is None:
        raise ValueError("kernel is required")
    if not isinstance(firm_id, str) or not firm_id:
        raise ValueError("firm_id is required and must be a non-empty string")
    if not isinstance(valuer_id, str) or not valuer_id:
        raise ValueError(
            "valuer_id is required and must be a non-empty string"
        )

    iso_date = _coerce_iso_date(as_of_date, kernel=kernel)
    rid = request_id or _default_request_id(firm_id, iso_date)
    vid = valuation_id or _default_valuation_id(firm_id, iso_date)

    # --------------------------------------------------------------
    # Idempotency check — same valuation_id returns the existing
    # record's audit shape unchanged.
    # --------------------------------------------------------------
    try:
        existing = kernel.valuations.get_valuation(vid)
    except UnknownValuationError:
        existing = None
    except Exception:
        existing = None
    if existing is not None:
        existing_summary: dict[str, Any] = {
            "estimated_value": existing.estimated_value,
            "confidence": float(existing.confidence),
            "overall_pressure": float(
                existing.inputs.get("overall_pressure", 0.0)
                if isinstance(existing.inputs, Mapping)
                else 0.0
            ),
            "baseline_value": (
                existing.inputs.get("baseline_value")
                if isinstance(existing.inputs, Mapping)
                else None
            ),
            "pressure_signal_id": (
                existing.inputs.get("pressure_signal_id")
                if isinstance(existing.inputs, Mapping)
                else None
            ),
            "method": existing.method,
        }
        existing_request = MechanismRunRequest(
            request_id=rid,
            model_id=VALUATION_REFRESH_MODEL_ID,
            actor_id=firm_id,
            as_of_date=iso_date,
            evidence_refs=tuple(existing.related_ids),
        )
        existing_output = MechanismOutputBundle(
            request_id=rid,
            model_id=VALUATION_REFRESH_MODEL_ID,
            status="completed",
            proposed_valuation_records=(),
            output_summary=existing_summary,
        )
        existing_run_record = MechanismRunRecord(
            run_id=f"mechanism_run:{rid}",
            request_id=rid,
            model_id=VALUATION_REFRESH_MODEL_ID,
            model_family=VALUATION_REFRESH_MODEL_FAMILY,
            version=VALUATION_REFRESH_MECHANISM_VERSION,
            actor_id=firm_id,
            as_of_date=iso_date,
            status="completed",
            input_refs=tuple(existing.related_ids),
            committed_output_refs=(existing.valuation_id,),
            metadata={
                "calibration_status": "synthetic",
                "valuation_summary": existing_summary,
                "idempotent_replay": True,
            },
        )
        return ValuationRefreshLiteResult(
            request=existing_request,
            output=existing_output,
            run_record=existing_run_record,
            valuation_id=existing.valuation_id,
            valuation_summary=existing_summary,
        )

    # --------------------------------------------------------------
    # Pass 1 — resolve actor context. Strict mode raises *before*
    # any record is committed.
    # --------------------------------------------------------------
    frame: ActorContextFrame = resolve_actor_context(
        kernel,
        actor_id=valuer_id,
        actor_type="valuer",
        as_of_date=iso_date,
        selected_observation_set_ids=tuple(selected_observation_set_ids),
        explicit_signal_ids=(
            tuple(explicit_pressure_signal_ids)
            + tuple(explicit_corporate_signal_ids)
        ),
        explicit_variable_observation_ids=tuple(
            explicit_variable_observation_ids
        ),
        explicit_exposure_ids=tuple(explicit_exposure_ids),
        explicit_market_readout_ids=tuple(explicit_market_readout_ids),
        explicit_market_environment_state_ids=tuple(
            explicit_market_environment_state_ids
        ),
        explicit_firm_state_ids=tuple(explicit_firm_state_ids),
        strict=strict,
    )

    # --------------------------------------------------------------
    # Pass 2 — read evidence ONLY from the resolver's surfaced ids
    # and shape the v1.9.5 evidence bundle. The adapter never sees
    # the kernel; only the request.evidence the helper packs.
    # --------------------------------------------------------------
    evidence: dict[str, list[dict[str, Any]]] = {
        "InformationSignal": [],
        "VariableObservation": [],
        "ExposureRecord": [],
        "SelectedObservationSet": [],
    }

    pressure_signal_id_resolved: str | None = None
    for sid in frame.resolved_signal_ids:
        try:
            sig = kernel.signals.get_signal(sid)
        except Exception:
            continue
        sig_dict = {
            "signal_id": sig.signal_id,
            "signal_type": sig.signal_type,
            "subject_id": sig.subject_id,
            "source_id": sig.source_id,
            "published_date": sig.published_date,
            "payload": dict(sig.payload),
            "metadata": dict(sig.metadata),
        }
        evidence["InformationSignal"].append(sig_dict)
        if (
            sig.signal_type == _FIRM_PRESSURE_SIGNAL_TYPE
            and sig.subject_id == firm_id
            and pressure_signal_id_resolved is None
        ):
            pressure_signal_id_resolved = sig.signal_id

    for oid in frame.resolved_variable_observation_ids:
        try:
            obs = kernel.variables.get_observation(oid)
        except Exception:
            continue
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

    for eid in frame.resolved_exposure_ids:
        try:
            exp = kernel.exposures.get_exposure(eid)
        except Exception:
            continue
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

    for sel_id in frame.selected_observation_set_ids:
        try:
            sel = kernel.attention.get_selection(sel_id)
        except Exception:
            continue
        evidence["SelectedObservationSet"].append(
            {
                "selection_id": sel.selection_id,
                "actor_id": sel.actor_id,
                "menu_id": sel.menu_id,
                "selected_refs": list(sel.selected_refs),
                "as_of_date": sel.as_of_date,
            }
        )

    # Build evidence_refs from the resolver's frame in canonical
    # bucket order. This is the lineage the audit MechanismRunRecord
    # carries.
    resolved_refs_list: list[str] = []
    for bucket_ids in (
        frame.resolved_signal_ids,
        frame.resolved_variable_observation_ids,
        frame.resolved_exposure_ids,
        frame.resolved_market_condition_ids,
        frame.resolved_market_readout_ids,
        frame.resolved_market_environment_state_ids,
        frame.resolved_industry_condition_ids,
        frame.resolved_firm_state_ids,
        frame.resolved_valuation_ids,
        frame.resolved_dialogue_ids,
        frame.resolved_escalation_candidate_ids,
        frame.resolved_stewardship_theme_ids,
    ):
        for ref_id in bucket_ids:
            if ref_id not in resolved_refs_list:
                resolved_refs_list.append(ref_id)
    for sel_id in frame.selected_observation_set_ids:
        if sel_id not in resolved_refs_list:
            resolved_refs_list.append(sel_id)
    resolved_refs: tuple[str, ...] = tuple(resolved_refs_list)

    # --------------------------------------------------------------
    # Pass 3 — assemble adapter parameters and run.
    # --------------------------------------------------------------
    parameters: dict[str, Any] = {
        "valuer_id": valuer_id,
        "currency": currency,
        "numeraire": numeraire,
        "valuation_id": vid,
    }
    if baseline_value is not None:
        parameters["baseline_value"] = float(baseline_value)
    if pressure_haircut_per_unit_pressure is not None:
        parameters["pressure_haircut_per_unit_pressure"] = float(
            pressure_haircut_per_unit_pressure
        )
    if confidence_decay_per_unit_pressure is not None:
        parameters["confidence_decay_per_unit_pressure"] = float(
            confidence_decay_per_unit_pressure
        )

    request = MechanismRunRequest(
        request_id=rid,
        model_id=VALUATION_REFRESH_MODEL_ID,
        actor_id=firm_id,
        as_of_date=iso_date,
        selected_observation_set_ids=tuple(frame.selected_observation_set_ids),
        evidence_refs=resolved_refs,
        evidence=evidence,
        parameters=parameters,
        metadata=dict(metadata or {}),
    )

    adapter = ValuationRefreshLiteAdapter()
    output = adapter.apply(request)

    if not output.proposed_valuation_records:
        raise RuntimeError(
            "ValuationRefreshLiteAdapter returned no proposed valuation; "
            "the v1.12.5 contract requires exactly one"
        )
    proposed = dict(output.proposed_valuation_records[0])

    # --------------------------------------------------------------
    # Pass 4 — apply v1.12.5 attention deltas. These are small,
    # documented synthetic adjustments — not calibrated sensitivities
    # — driven by what the resolver surfaced for *this* valuer.
    # --------------------------------------------------------------
    estimated_value = proposed.get("estimated_value")
    confidence = float(proposed.get("confidence", 0.0))

    # Count resolved buckets (a synthetic ordering on attention
    # breadth — more buckets surfaced → small confidence bonus).
    resolved_buckets_present = sum(
        1
        for bucket_ids in (
            frame.resolved_signal_ids,
            frame.resolved_variable_observation_ids,
            frame.resolved_exposure_ids,
            frame.resolved_market_readout_ids,
            frame.resolved_market_environment_state_ids,
            frame.resolved_firm_state_ids,
            frame.resolved_valuation_ids,
        )
        if bucket_ids
    )
    confidence_bonus = min(
        _ATTN_CONFIDENCE_RESOLVED_BUCKET_BONUS_CAP,
        _ATTN_CONFIDENCE_RESOLVED_BUCKET_BONUS * resolved_buckets_present,
    )
    unresolved_count = len(frame.unresolved_refs)
    confidence_penalty = min(
        _ATTN_CONFIDENCE_UNRESOLVED_PENALTY_CAP,
        _ATTN_CONFIDENCE_UNRESOLVED_PENALTY * unresolved_count,
    )
    confidence = max(0.0, min(1.0, confidence + confidence_bonus - confidence_penalty))

    # Restrictive market environment / readout — small downward
    # adjustment to estimated_value when present (only fires when a
    # numeric value is computable).
    restrictive_market = False
    risk_off_environment = False
    if estimated_value is not None:
        for rid_resolved in frame.resolved_market_readout_ids:
            try:
                readout = kernel.capital_market_readouts.get_readout(rid_resolved)
            except Exception:
                continue
            if (
                getattr(readout, "overall_market_access_label", None)
                == _RESTRICTIVE_OVERALL_LABEL
            ):
                restrictive_market = True
                break
        for env_id in frame.resolved_market_environment_state_ids:
            try:
                env = kernel.market_environments.get_state(env_id)
            except Exception:
                continue
            if (
                getattr(env, "overall_market_access_label", None)
                == _RESTRICTIVE_OVERALL_LABEL
            ):
                restrictive_market = True
            if (
                getattr(env, "risk_appetite_regime", None)
                == _RESTRICTIVE_RISK_APPETITE_LABEL
            ):
                risk_off_environment = True

        if restrictive_market:
            estimated_value = float(estimated_value) * (
                1.0 - _ATTN_RESTRICTIVE_MARKET_VALUE_HAIRCUT
            )
        if risk_off_environment:
            estimated_value = float(estimated_value) * (
                1.0 - _ATTN_RESTRICTIVE_RISK_APPETITE_VALUE_HAIRCUT
            )

    proposed["estimated_value"] = estimated_value
    proposed["confidence"] = confidence

    # --------------------------------------------------------------
    # Pass 5 — stamp v1.12.5 attention metadata onto the proposed
    # record's metadata dict (no new field on the dataclass).
    # --------------------------------------------------------------
    record_metadata: dict[str, Any] = dict(proposed.get("metadata", {}))
    record_metadata["attention_conditioned"] = True
    record_metadata["context_frame_id"] = frame.context_frame_id
    record_metadata["context_frame_status"] = frame.status
    record_metadata["context_frame_confidence"] = frame.confidence
    record_metadata["resolved_buckets_present"] = resolved_buckets_present
    record_metadata["restrictive_market_resolved"] = bool(restrictive_market)
    record_metadata["risk_off_environment_resolved"] = bool(
        risk_off_environment
    )
    if frame.unresolved_refs:
        record_metadata["unresolved_refs"] = [
            r.to_dict() for r in frame.unresolved_refs
        ]
    proposed["metadata"] = record_metadata

    # --------------------------------------------------------------
    # Pass 6 — extend related_ids with the resolver's surfaced ids
    # (de-duplicated, first-seen order). The pressure signal id
    # already lives in v1.9.5's related_ids; the resolver's other
    # surfaced ids are the audit trail for the attention bottleneck.
    # --------------------------------------------------------------
    related_ids: list[str] = list(proposed.get("related_ids", ()))
    for ref_id in resolved_refs:
        if ref_id not in related_ids:
            related_ids.append(ref_id)
    proposed["related_ids"] = related_ids

    # --------------------------------------------------------------
    # Pass 7 — commit the record.
    # --------------------------------------------------------------
    record = ValuationRecord(
        valuation_id=proposed["valuation_id"],
        subject_id=proposed["subject_id"],
        valuer_id=proposed["valuer_id"],
        valuation_type=proposed["valuation_type"],
        purpose=proposed["purpose"],
        method=proposed["method"],
        as_of_date=proposed["as_of_date"],
        estimated_value=proposed.get("estimated_value"),
        currency=proposed.get("currency", "unspecified"),
        numeraire=proposed.get("numeraire", "unspecified"),
        confidence=float(proposed.get("confidence", 1.0)),
        assumptions=dict(proposed.get("assumptions", {})),
        inputs=dict(proposed.get("inputs", {})),
        related_ids=tuple(proposed.get("related_ids", ())),
        metadata=dict(proposed.get("metadata", {})),
    )
    kernel.valuations.add_valuation(record)

    summary: dict[str, Any] = {
        "estimated_value": proposed.get("estimated_value"),
        "confidence": float(proposed.get("confidence", 0.0)),
        "overall_pressure": float(
            output.output_summary.get("overall_pressure", 0.0)
        ),
        "baseline_value": output.output_summary.get("baseline_value"),
        "pressure_signal_id": pressure_signal_id_resolved,
        "method": output.output_summary.get("method"),
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
        committed_output_refs=(record.valuation_id,),
        metadata={
            "calibration_status": adapter.spec.calibration_status,
            "valuation_summary": summary,
            "attention_conditioned": True,
            "context_frame_id": frame.context_frame_id,
            "context_frame_status": frame.status,
            "context_frame_confidence": frame.confidence,
        },
    )

    return ValuationRefreshLiteResult(
        request=request,
        output=output,
        run_record=run_record,
        valuation_id=record.valuation_id,
        valuation_summary=summary,
    )


# Re-export for convenience.
__all__ = [
    "VALUATION_REFRESH_MECHANISM_VERSION",
    "VALUATION_REFRESH_METHOD_LABEL",
    "VALUATION_REFRESH_MODEL_FAMILY",
    "VALUATION_REFRESH_MODEL_ID",
    "VALUATION_REFRESH_PURPOSE",
    "VALUATION_REFRESH_VALUATION_TYPE",
    "ValuationRefreshLiteAdapter",
    "ValuationRefreshLiteResult",
    "run_reference_valuation_refresh_lite",
    "run_attention_conditioned_valuation_refresh_lite",
    "EvidenceResolutionError",
    "StrictEvidenceResolutionError",
]
