"""
Tests for v1.9.4 Reference Firm Operating Pressure Assessment
Mechanism.

Pins the v1.9.4 contract end-to-end:

- adapter satisfies the v1.9.3 / v1.9.3.1 :class:`MechanismAdapter`
  Protocol;
- adapter has a valid :class:`MechanismSpec` (model_id,
  model_family="firm_financial_mechanism", version,
  calibration_status="synthetic", deterministic);
- adapter reads ``request.evidence`` only — never touches a
  kernel or any book;
- adapter does not mutate the request (the v1.9.3.1 deep-freeze
  guarantees this; we re-pin the property here);
- missing evidence yields ``status="degraded"`` rather than
  crashing;
- pressure scores are all in ``[0, 1]``;
- ``overall_pressure`` is the deterministic mean of the five
  dimensions;
- two adapter calls on byte-identical requests produce
  byte-identical outputs;
- the proposed signal mapping has the right shape (signal_type,
  payload, related_ids, metadata, boundary);
- caller helper commits exactly one signal through SignalBook;
- ``evidence_refs`` lineage is preserved verbatim on the
  :class:`MechanismRunRecord`;
- no mutation of valuations / prices / ownership / contracts /
  constraints / variables / exposures / institutions /
  external_processes / relationships across the helper's call;
- synthetic-only identifiers (word-boundary forbidden-token
  check).
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from world.clock import Clock
from world.exposures import ExposureRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.mechanisms import (
    MechanismAdapter,
    MechanismOutputBundle,
    MechanismRunRecord,
    MechanismRunRequest,
    MechanismSpec,
)
from world.reference_firm_pressure import (
    FIRM_PRESSURE_MECHANISM_VERSION,
    FIRM_PRESSURE_MODEL_FAMILY,
    FIRM_PRESSURE_MODEL_ID,
    FIRM_PRESSURE_SIGNAL_TYPE,
    FirmPressureMechanismAdapter,
    FirmPressureMechanismResult,
    run_reference_firm_pressure_mechanism,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State
from world.variables import ReferenceVariableSpec, VariableObservation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FIRM = "firm:reference_manufacturer_a"
_AS_OF = "2026-04-30"


_REFERENCE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("variable:reference_oil_price", "energy_power"),
    ("variable:reference_long_rate_10y", "rates"),
    ("variable:reference_fx_pair_a", "fx"),
    ("variable:reference_steel_price", "material"),
    ("variable:reference_freight_index", "logistics"),
)


_REFERENCE_EXPOSURES: tuple[tuple[str, str, str, str, float], ...] = (
    (
        "exposure:firm_a:energy",
        "variable:reference_oil_price",
        "input_cost",
        "operating_cost_pressure",
        0.4,
    ),
    (
        "exposure:firm_a:rates",
        "variable:reference_long_rate_10y",
        "funding_cost",
        "debt_service_burden",
        0.3,
    ),
    (
        "exposure:firm_a:fx",
        "variable:reference_fx_pair_a",
        "translation",
        "fx_translation_pressure",
        0.2,
    ),
    (
        "exposure:firm_a:steel",
        "variable:reference_steel_price",
        "input_cost",
        "operating_cost_pressure",
        0.5,
    ),
    (
        "exposure:firm_a:freight",
        "variable:reference_freight_index",
        "input_cost",
        "operating_cost_pressure",
        0.15,
    ),
)


def _seed_kernel() -> WorldKernel:
    k = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 4, 30)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )
    for vid, vgroup in _REFERENCE_VARIABLES:
        k.variables.add_variable(
            ReferenceVariableSpec(
                variable_id=vid,
                variable_name=vid,
                variable_group=vgroup,
                variable_type="level",
                source_space_id="external",
                canonical_unit="index",
                frequency="QUARTERLY",
                observation_kind="released",
            )
        )
        k.variables.add_observation(
            VariableObservation(
                observation_id=f"obs:{vid}:2026Q1",
                variable_id=vid,
                as_of_date="2026-04-15",
                value=100.0,
                unit="index",
                vintage_id="2026Q1_initial",
            )
        )
    for exp_id, var_id, etype, metric, mag in _REFERENCE_EXPOSURES:
        k.exposures.add_exposure(
            ExposureRecord(
                exposure_id=exp_id,
                subject_id=_FIRM,
                subject_type="firm",
                variable_id=var_id,
                exposure_type=etype,
                metric=metric,
                direction="positive",
                magnitude=mag,
            )
        )
    return k


def _all_observation_ids() -> tuple[str, ...]:
    return tuple(f"obs:{vid}:2026Q1" for vid, _ in _REFERENCE_VARIABLES)


def _all_exposure_ids() -> tuple[str, ...]:
    return tuple(eid for eid, *_ in _REFERENCE_EXPOSURES)


def _run_default(k: WorldKernel) -> FirmPressureMechanismResult:
    return run_reference_firm_pressure_mechanism(
        k,
        firm_id=_FIRM,
        as_of_date=_AS_OF,
        variable_observation_ids=_all_observation_ids(),
        exposure_ids=_all_exposure_ids(),
    )


# ---------------------------------------------------------------------------
# Spec / Protocol contract
# ---------------------------------------------------------------------------


def test_adapter_satisfies_mechanism_adapter_protocol():
    adapter = FirmPressureMechanismAdapter()
    assert isinstance(adapter, MechanismAdapter)


def test_adapter_spec_has_required_fields():
    adapter = FirmPressureMechanismAdapter()
    spec = adapter.spec
    assert isinstance(spec, MechanismSpec)
    assert spec.model_id == FIRM_PRESSURE_MODEL_ID
    assert spec.model_family == FIRM_PRESSURE_MODEL_FAMILY
    assert spec.model_family == "firm_financial_mechanism"
    assert spec.version == FIRM_PRESSURE_MECHANISM_VERSION
    assert spec.calibration_status == "synthetic"
    assert spec.stochasticity == "deterministic"
    assert "VariableObservation" in spec.required_inputs
    assert "ExposureRecord" in spec.required_inputs
    assert "InformationSignal" in spec.output_types


def test_adapter_apply_returns_mechanism_output_bundle():
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
    )
    output = adapter.apply(request)
    assert isinstance(output, MechanismOutputBundle)


def test_adapter_does_not_accept_kernel_argument():
    """The adapter contract is `apply(request)`; passing a kernel
    must fail."""
    adapter = FirmPressureMechanismAdapter()
    with pytest.raises(TypeError):
        adapter.apply(_seed_kernel())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Adapter is read-only against the kernel (the v1.9.3.1 invariant)
# ---------------------------------------------------------------------------


def test_adapter_can_run_without_a_kernel():
    """The adapter must compute proposals from
    request.evidence alone — no kernel reference required."""
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "VariableObservation": [
                {
                    "observation_id": "o:1",
                    "variable_id": "v:fx",
                    "variable_group": "fx",
                    "value": 100.0,
                    "as_of_date": "2026-04-15",
                },
            ],
            "ExposureRecord": [
                {
                    "exposure_id": "e:1",
                    "subject_id": _FIRM,
                    "variable_id": "v:fx",
                    "exposure_type": "translation",
                    "metric": "fx_translation_pressure",
                    "magnitude": 0.4,
                },
            ],
        },
        evidence_refs=("o:1", "e:1"),
    )
    output = adapter.apply(request)
    assert output.status == "completed"
    assert len(output.proposed_signals) == 1
    payload = output.proposed_signals[0]["payload"]
    assert payload["fx_translation_pressure"] == 0.4
    # Other dimensions zero because no evidence in those variable
    # groups.
    assert payload["input_cost_pressure"] == 0.0
    assert payload["energy_power_pressure"] == 0.0


# ---------------------------------------------------------------------------
# Degraded status on missing evidence
# ---------------------------------------------------------------------------


def test_apply_with_no_evidence_returns_degraded_not_crash():
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
    )
    output = adapter.apply(request)
    assert output.status == "degraded"
    assert len(output.proposed_signals) == 1
    payload = output.proposed_signals[0]["payload"]
    assert payload["overall_pressure"] == 0.0
    for dim in (
        "input_cost_pressure",
        "energy_power_pressure",
        "debt_service_pressure",
        "fx_translation_pressure",
        "logistics_pressure",
    ):
        assert payload[dim] == 0.0


def test_apply_with_only_observations_returns_degraded():
    """No exposures -> nothing for the firm to be exposed to ->
    degraded (every dimension zero, anti-scenario rule)."""
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "VariableObservation": [
                {
                    "observation_id": "o:1",
                    "variable_id": "v:fx",
                    "variable_group": "fx",
                },
            ],
        },
    )
    output = adapter.apply(request)
    assert output.status == "degraded"


def test_apply_with_only_exposures_returns_degraded():
    """No observations -> no observable pressure source ->
    degraded."""
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "ExposureRecord": [
                {
                    "exposure_id": "e:1",
                    "subject_id": _FIRM,
                    "variable_id": "v:fx",
                    "exposure_type": "translation",
                    "metric": "fx_translation_pressure",
                    "magnitude": 0.4,
                },
            ],
        },
    )
    output = adapter.apply(request)
    assert output.status == "degraded"


# ---------------------------------------------------------------------------
# Pressure-score arithmetic
# ---------------------------------------------------------------------------


def test_pressure_dimensions_are_in_zero_one_range():
    k = _seed_kernel()
    result = _run_default(k)
    payload = result.output.proposed_signals[0]["payload"]
    for dim in (
        "input_cost_pressure",
        "energy_power_pressure",
        "debt_service_pressure",
        "fx_translation_pressure",
        "logistics_pressure",
        "overall_pressure",
    ):
        assert 0.0 <= payload[dim] <= 1.0, f"{dim}={payload[dim]} out of [0,1]"


def test_overall_pressure_is_mean_of_five_dimensions():
    k = _seed_kernel()
    result = _run_default(k)
    payload = result.output.proposed_signals[0]["payload"]
    expected = (
        payload["input_cost_pressure"]
        + payload["energy_power_pressure"]
        + payload["debt_service_pressure"]
        + payload["fx_translation_pressure"]
        + payload["logistics_pressure"]
    ) / 5
    assert abs(payload["overall_pressure"] - expected) < 1e-9


def test_pressure_sum_clamped_to_one():
    """Two material-cost exposures with magnitudes 0.6 + 0.7
    would sum to 1.3; the dimension must clamp to 1.0."""
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "VariableObservation": [
                {
                    "observation_id": "o:steel",
                    "variable_id": "v:steel",
                    "variable_group": "material",
                },
                {
                    "observation_id": "o:copper",
                    "variable_id": "v:copper",
                    "variable_group": "material",
                },
            ],
            "ExposureRecord": [
                {
                    "exposure_id": "e:steel",
                    "subject_id": _FIRM,
                    "variable_id": "v:steel",
                    "exposure_type": "input_cost",
                    "metric": "operating_cost_pressure",
                    "magnitude": 0.6,
                },
                {
                    "exposure_id": "e:copper",
                    "subject_id": _FIRM,
                    "variable_id": "v:copper",
                    "exposure_type": "input_cost",
                    "metric": "operating_cost_pressure",
                    "magnitude": 0.7,
                },
            ],
        },
    )
    payload = adapter.apply(request).proposed_signals[0]["payload"]
    assert payload["input_cost_pressure"] == 1.0


# ---------------------------------------------------------------------------
# Determinism + request immutability
# ---------------------------------------------------------------------------


def test_apply_is_deterministic_across_two_calls():
    # Build the same request twice from byte-identical seed
    # kernels; the outputs must be byte-identical.
    a = _run_default(_seed_kernel())
    b = _run_default(_seed_kernel())

    assert a.output.proposed_signals[0]["payload"] == (
        b.output.proposed_signals[0]["payload"]
    )
    assert a.signal_id == b.signal_id


def test_apply_does_not_mutate_request():
    """The v1.9.3.1 deep-freeze guarantees the request is
    immutable; the adapter cannot mutate it. Re-pin here for the
    concrete adapter."""
    adapter = FirmPressureMechanismAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "VariableObservation": [
                {"observation_id": "o:1", "variable_id": "v:fx", "variable_group": "fx"},
            ],
            "ExposureRecord": [
                {
                    "exposure_id": "e:1",
                    "subject_id": _FIRM,
                    "variable_id": "v:fx",
                    "exposure_type": "translation",
                    "metric": "fx_translation_pressure",
                    "magnitude": 0.4,
                },
            ],
        },
    )
    pre = request.to_dict()
    adapter.apply(request)
    post = request.to_dict()
    assert pre == post


# ---------------------------------------------------------------------------
# Proposed signal shape
# ---------------------------------------------------------------------------


def test_proposed_signal_has_required_fields():
    k = _seed_kernel()
    result = _run_default(k)
    proposed = result.output.proposed_signals[0]
    for field in (
        "signal_id",
        "signal_type",
        "subject_id",
        "source_id",
        "published_date",
        "effective_date",
        "visibility",
        "payload",
        "related_ids",
        "metadata",
    ):
        assert field in proposed, f"proposed signal missing {field}"
    assert proposed["signal_type"] == FIRM_PRESSURE_SIGNAL_TYPE
    assert proposed["subject_id"] == _FIRM


def test_proposed_signal_payload_includes_all_pressure_dimensions():
    k = _seed_kernel()
    result = _run_default(k)
    payload = result.output.proposed_signals[0]["payload"]
    for dim in (
        "input_cost_pressure",
        "energy_power_pressure",
        "debt_service_pressure",
        "fx_translation_pressure",
        "logistics_pressure",
        "overall_pressure",
    ):
        assert dim in payload
    assert payload["calibration_status"] == "synthetic"
    assert "evidence_counts" in payload
    counts = payload["evidence_counts"]
    assert counts["variable_observations"] == 5
    assert counts["exposure_records"] == 5


def test_proposed_signal_metadata_carries_boundary_statement():
    k = _seed_kernel()
    result = _run_default(k)
    metadata = result.output.proposed_signals[0]["metadata"]
    assert metadata["model_id"] == FIRM_PRESSURE_MODEL_ID
    assert metadata["calibration_status"] == "synthetic"
    assert "no financial-statement update" in metadata["boundary"]


# ---------------------------------------------------------------------------
# Caller helper end-to-end
# ---------------------------------------------------------------------------


def test_caller_helper_commits_exactly_one_pressure_signal():
    k = _seed_kernel()
    before_signals = len(k.signals.all_signals())
    result = _run_default(k)
    after_signals = k.signals.all_signals()
    assert len(after_signals) - before_signals == 1
    assert isinstance(result, FirmPressureMechanismResult)
    sig = k.signals.get_signal(result.signal_id)
    assert sig.signal_type == FIRM_PRESSURE_SIGNAL_TYPE


def test_caller_helper_resolves_evidence_from_books():
    k = _seed_kernel()
    result = _run_default(k)
    evidence = result.request.evidence
    assert len(evidence["VariableObservation"]) == 5
    assert len(evidence["ExposureRecord"]) == 5
    # Caller hydrated variable_group from WorldVariableBook.
    for obs in evidence["VariableObservation"]:
        assert "variable_group" in obs
        assert obs["variable_group"] in {
            "energy_power",
            "rates",
            "fx",
            "material",
            "logistics",
        }


def test_caller_helper_returns_run_record_with_lineage():
    k = _seed_kernel()
    result = _run_default(k)
    run = result.run_record
    assert isinstance(run, MechanismRunRecord)
    # input_refs preserves caller-supplied evidence_refs verbatim.
    assert run.input_refs == result.request.evidence_refs
    assert run.committed_output_refs == (result.signal_id,)
    assert run.model_id == FIRM_PRESSURE_MODEL_ID
    assert run.model_family == FIRM_PRESSURE_MODEL_FAMILY


def test_caller_helper_evidence_refs_default_concatenation():
    """When evidence_refs is omitted, the default is observations
    + exposures + signals in input order, verbatim."""
    k = _seed_kernel()
    result = _run_default(k)
    expected = _all_observation_ids() + _all_exposure_ids()
    assert result.request.evidence_refs == expected


def test_caller_helper_explicit_evidence_refs_preserved_verbatim():
    k = _seed_kernel()
    custom = (
        "exposure:firm_a:fx",
        "obs:variable:reference_fx_pair_a:2026Q1",
        "exposure:firm_a:rates",
        "obs:variable:reference_long_rate_10y:2026Q1",
    )
    result = run_reference_firm_pressure_mechanism(
        k,
        firm_id=_FIRM,
        as_of_date=_AS_OF,
        variable_observation_ids=_all_observation_ids(),
        exposure_ids=_all_exposure_ids(),
        evidence_refs=custom,
    )
    assert result.request.evidence_refs == custom
    assert result.run_record.input_refs == custom


def test_caller_helper_uses_kernel_clock_when_date_omitted():
    k = _seed_kernel()
    result = run_reference_firm_pressure_mechanism(
        k,
        firm_id=_FIRM,
        variable_observation_ids=_all_observation_ids(),
        exposure_ids=_all_exposure_ids(),
    )
    assert result.request.as_of_date == _AS_OF


# ---------------------------------------------------------------------------
# Defensive errors
# ---------------------------------------------------------------------------


def test_caller_helper_rejects_kernel_none():
    with pytest.raises(ValueError):
        run_reference_firm_pressure_mechanism(
            None, firm_id=_FIRM, as_of_date=_AS_OF
        )


def test_caller_helper_rejects_empty_firm_id():
    k = _seed_kernel()
    with pytest.raises(ValueError):
        run_reference_firm_pressure_mechanism(k, firm_id="", as_of_date=_AS_OF)


# ---------------------------------------------------------------------------
# No-mutation guarantee against every other v0/v1/v1.8 book
# ---------------------------------------------------------------------------


def _capture_state(k: WorldKernel) -> dict[str, Any]:
    return {
        "valuations": k.valuations.snapshot(),
        "prices": k.prices.snapshot(),
        "ownership": k.ownership.snapshot(),
        "contracts": k.contracts.snapshot(),
        "constraints": k.constraints.snapshot(),
        "exposures": k.exposures.snapshot(),
        "variables": k.variables.snapshot(),
        "institutions": k.institutions.snapshot(),
        "external_processes": k.external_processes.snapshot(),
        "relationships": k.relationships.snapshot(),
        # Routines, attention, interactions are read-only too —
        # the v1.9.4 mechanism doesn't even read them.
        "routines": k.routines.snapshot(),
        "attention": k.attention.snapshot(),
        "interactions": k.interactions.snapshot(),
    }


def test_caller_helper_does_not_mutate_other_books():
    k = _seed_kernel()
    before = _capture_state(k)
    _run_default(k)
    after = _capture_state(k)
    assert before == after


def test_caller_helper_writes_only_one_signal_no_other_records():
    """The only side effect should be one InformationSignal +
    its ledger entry. Routine runs, attention selections, etc.,
    must not appear."""
    k = _seed_kernel()
    before_ledger = len(k.ledger.records)
    before_signals = len(k.signals.all_signals())
    _run_default(k)
    after_ledger = len(k.ledger.records)
    after_signals = len(k.signals.all_signals())
    # Exactly one signal added; exactly one ledger record (the
    # signal_added entry from SignalBook.add_signal).
    assert after_signals - before_signals == 1
    assert after_ledger - before_ledger == 1


# ---------------------------------------------------------------------------
# Synthetic-only identifiers (word-boundary forbidden-token check)
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "nyse",
)


def test_module_constants_use_no_jurisdiction_specific_tokens():
    candidates = (
        FIRM_PRESSURE_MODEL_ID,
        FIRM_PRESSURE_MODEL_FAMILY,
        FIRM_PRESSURE_SIGNAL_TYPE,
    )
    for c in candidates:
        for token in _FORBIDDEN_TOKENS:
            assert token not in c.lower(), c


def test_signal_identifiers_are_synthetic():
    k = _seed_kernel()
    result = _run_default(k)
    sig = k.signals.get_signal(result.signal_id)
    candidates = [
        sig.signal_id,
        sig.signal_type,
        sig.subject_id,
        sig.source_id,
    ]
    for id_str in candidates:
        lower = id_str.lower()
        for token in _FORBIDDEN_TOKENS:
            for sep in (" ", ":", "/", "-", "_", "(", ")", ",", ".", "'", '"'):
                if f"{sep}{token}{sep}" in f" {lower} ":
                    pytest.fail(
                        f"forbidden token {token!r} appears in id {id_str!r}"
                    )
