"""
Tests for v1.9.5 Reference Valuation Refresh Lite Mechanism.

Pins the v1.9.5 contract end-to-end:

- adapter satisfies the v1.9.3 / v1.9.3.1 :class:`MechanismAdapter`
  Protocol;
- :class:`MechanismSpec` is valid (model_family
  ``"valuation_mechanism"``, calibration ``"synthetic"``,
  deterministic);
- adapter does not accept a kernel argument;
- adapter runs without a kernel (reads ``request.evidence`` only);
- missing pressure evidence yields ``status="degraded"`` with a
  conservative output (baseline-only or ``None``);
- proposed valuation carries every required field including the
  method label ``"synthetic_lite_pressure_adjusted"``;
- metadata includes the four boundary flags
  (``no_price_movement`` / ``no_investment_advice`` /
  ``synthetic_only`` / ``model_id``) and the ``pressure_signal_id``
  when the pressure signal was supplied;
- adapter is deterministic across two byte-identical requests;
- request is not mutated by ``apply``;
- caller helper commits exactly one ``ValuationRecord`` through
  ``ValuationBook.add_valuation``;
- ``evidence_refs`` lineage is preserved verbatim on the
  :class:`MechanismRunRecord`;
- no mutation of prices / ownership / contracts / firm-state /
  variables / exposures / institutions / external_processes /
  relationships / routines / attention / interactions; signals
  grow only by the input pressure-signal we wrote in setup
  (the adapter does not emit a signal of its own);
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
    run_reference_firm_pressure_mechanism,
)
from world.evidence import StrictEvidenceResolutionError
from world.firm_state import FirmFinancialStateRecord
from world.market_conditions import MarketConditionRecord
from world.market_environment import MarketEnvironmentStateRecord
from world.market_surface_readout import build_capital_market_readout
from world.reference_valuation_refresh_lite import (
    VALUATION_REFRESH_MECHANISM_VERSION,
    VALUATION_REFRESH_METHOD_LABEL,
    VALUATION_REFRESH_MODEL_FAMILY,
    VALUATION_REFRESH_MODEL_ID,
    ValuationRefreshLiteAdapter,
    ValuationRefreshLiteResult,
    run_attention_conditioned_valuation_refresh_lite,
    run_reference_valuation_refresh_lite,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State
from world.variables import ReferenceVariableSpec, VariableObservation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_FIRM = "firm:reference_manufacturer_a"
_VALUER = "valuer:reference_analyst_desk_a"
_AS_OF = "2026-04-30"
_BASELINE = 1_000_000.0


_REFERENCE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("variable:reference_oil_price", "energy_power"),
    ("variable:reference_long_rate_10y", "rates"),
    ("variable:reference_fx_pair_a", "fx"),
    ("variable:reference_steel_price", "material"),
)


_REFERENCE_EXPOSURES: tuple[tuple[str, str, str, float], ...] = (
    ("exposure:firm_a:energy", "variable:reference_oil_price", "input_cost", 0.4),
    ("exposure:firm_a:rates", "variable:reference_long_rate_10y", "funding_cost", 0.3),
    ("exposure:firm_a:fx", "variable:reference_fx_pair_a", "translation", 0.2),
    ("exposure:firm_a:steel", "variable:reference_steel_price", "input_cost", 0.5),
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
    for exp_id, var_id, etype, mag in _REFERENCE_EXPOSURES:
        k.exposures.add_exposure(
            ExposureRecord(
                exposure_id=exp_id,
                subject_id=_FIRM,
                subject_type="firm",
                variable_id=var_id,
                exposure_type=etype,
                metric="operating_cost_pressure",
                direction="positive",
                magnitude=mag,
            )
        )
    return k


def _all_observation_ids() -> tuple[str, ...]:
    return tuple(f"obs:{vid}:2026Q1" for vid, _ in _REFERENCE_VARIABLES)


def _all_exposure_ids() -> tuple[str, ...]:
    return tuple(eid for eid, *_ in _REFERENCE_EXPOSURES)


def _seed_with_pressure_signal() -> tuple[WorldKernel, str, float]:
    """Seed a kernel and run v1.9.4 to produce the pressure
    signal that v1.9.5 consumes."""
    k = _seed_kernel()
    pressure_result = run_reference_firm_pressure_mechanism(
        k,
        firm_id=_FIRM,
        as_of_date=_AS_OF,
        variable_observation_ids=_all_observation_ids(),
        exposure_ids=_all_exposure_ids(),
    )
    return k, pressure_result.signal_id, pressure_result.overall_pressure


def _run_default(
    k: WorldKernel, pressure_signal_id: str
) -> ValuationRefreshLiteResult:
    return run_reference_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        pressure_signal_ids=(pressure_signal_id,),
        baseline_value=_BASELINE,
    )


# ---------------------------------------------------------------------------
# Spec / Protocol contract
# ---------------------------------------------------------------------------


def test_adapter_satisfies_mechanism_adapter_protocol():
    adapter = ValuationRefreshLiteAdapter()
    assert isinstance(adapter, MechanismAdapter)


def test_adapter_spec_has_required_fields():
    adapter = ValuationRefreshLiteAdapter()
    spec = adapter.spec
    assert isinstance(spec, MechanismSpec)
    assert spec.model_id == VALUATION_REFRESH_MODEL_ID
    assert spec.model_family == VALUATION_REFRESH_MODEL_FAMILY
    assert spec.model_family == "valuation_mechanism"
    assert spec.version == VALUATION_REFRESH_MECHANISM_VERSION
    assert spec.calibration_status == "synthetic"
    assert spec.stochasticity == "deterministic"
    assert "InformationSignal" in spec.required_inputs
    assert "ValuationRecord" in spec.output_types


def test_adapter_apply_returns_mechanism_output_bundle():
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
    )
    output = adapter.apply(request)
    assert isinstance(output, MechanismOutputBundle)


def test_adapter_does_not_accept_kernel_argument():
    adapter = ValuationRefreshLiteAdapter()
    with pytest.raises(TypeError):
        adapter.apply(_seed_kernel())  # type: ignore[arg-type]


def test_adapter_runs_without_a_kernel():
    """Adapter must compute proposals from request.evidence
    alone — no kernel reference."""
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "InformationSignal": [
                {
                    "signal_id": "signal:firm_operating_pressure_assessment:test",
                    "signal_type": "firm_operating_pressure_assessment",
                    "subject_id": _FIRM,
                    "payload": {"overall_pressure": 0.5, "status": "completed"},
                },
            ],
        },
        parameters={"baseline_value": _BASELINE, "valuer_id": _VALUER},
    )
    output = adapter.apply(request)
    assert output.status == "completed"
    assert len(output.proposed_valuation_records) == 1
    proposed = output.proposed_valuation_records[0]
    # baseline 1M × (1 − 0.30 × 0.5) = 850k
    assert abs(proposed["estimated_value"] - 850_000.0) < 1e-6
    # confidence 1 − 0.40 × 0.5 = 0.8
    assert abs(proposed["confidence"] - 0.8) < 1e-9


# ---------------------------------------------------------------------------
# Degraded path (missing pressure evidence)
# ---------------------------------------------------------------------------


def test_apply_with_no_pressure_signal_returns_degraded_with_baseline():
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        parameters={"baseline_value": _BASELINE, "valuer_id": _VALUER},
    )
    output = adapter.apply(request)
    assert output.status == "degraded"
    proposed = output.proposed_valuation_records[0]
    # No pressure → no haircut → estimated_value == baseline
    assert proposed["estimated_value"] == _BASELINE
    assert proposed["confidence"] == 1.0


def test_apply_with_no_pressure_and_no_baseline_returns_degraded_none():
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        parameters={"valuer_id": _VALUER},
    )
    output = adapter.apply(request)
    assert output.status == "degraded"
    proposed = output.proposed_valuation_records[0]
    assert proposed["estimated_value"] is None
    assert proposed["confidence"] == 0.0


def test_pressure_signal_for_other_actor_is_ignored():
    """The adapter only picks up pressure signals whose
    subject_id matches request.actor_id."""
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "InformationSignal": [
                {
                    "signal_id": "signal:firm_operating_pressure_assessment:other",
                    "signal_type": "firm_operating_pressure_assessment",
                    "subject_id": "firm:other",
                    "payload": {"overall_pressure": 0.9},
                },
            ],
        },
        parameters={"baseline_value": _BASELINE, "valuer_id": _VALUER},
    )
    output = adapter.apply(request)
    # No pressure signal matched our firm → degraded.
    assert output.status == "degraded"
    proposed = output.proposed_valuation_records[0]
    assert proposed["estimated_value"] == _BASELINE


# ---------------------------------------------------------------------------
# Pressure → valuation arithmetic
# ---------------------------------------------------------------------------


def test_zero_pressure_gives_baseline_value_unchanged():
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "InformationSignal": [
                {
                    "signal_id": "s:1",
                    "signal_type": "firm_operating_pressure_assessment",
                    "subject_id": _FIRM,
                    "payload": {"overall_pressure": 0.0},
                },
            ],
        },
        parameters={"baseline_value": _BASELINE, "valuer_id": _VALUER},
    )
    proposed = adapter.apply(request).proposed_valuation_records[0]
    assert proposed["estimated_value"] == _BASELINE
    assert proposed["confidence"] == 1.0


def test_full_pressure_caps_haircut_and_decays_confidence():
    """At pressure=1, default haircut coefficient 0.30 trims
    baseline by 30%; confidence decays by 0.40."""
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "InformationSignal": [
                {
                    "signal_id": "s:1",
                    "signal_type": "firm_operating_pressure_assessment",
                    "subject_id": _FIRM,
                    "payload": {"overall_pressure": 1.0},
                },
            ],
        },
        parameters={"baseline_value": _BASELINE, "valuer_id": _VALUER},
    )
    proposed = adapter.apply(request).proposed_valuation_records[0]
    assert abs(proposed["estimated_value"] - _BASELINE * 0.70) < 1e-6
    assert abs(proposed["confidence"] - 0.60) < 1e-9


def test_caller_supplied_coefficients_override_defaults():
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "InformationSignal": [
                {
                    "signal_id": "s:1",
                    "signal_type": "firm_operating_pressure_assessment",
                    "subject_id": _FIRM,
                    "payload": {"overall_pressure": 0.5},
                },
            ],
        },
        parameters={
            "baseline_value": _BASELINE,
            "valuer_id": _VALUER,
            "pressure_haircut_per_unit_pressure": 0.5,
            "confidence_decay_per_unit_pressure": 0.2,
        },
    )
    proposed = adapter.apply(request).proposed_valuation_records[0]
    # 0.5 * 0.5 = 0.25 haircut → 750k
    assert abs(proposed["estimated_value"] - 750_000.0) < 1e-6
    # 1 - 0.2 * 0.5 = 0.9 confidence
    assert abs(proposed["confidence"] - 0.9) < 1e-9


# ---------------------------------------------------------------------------
# Determinism + immutability
# ---------------------------------------------------------------------------


def test_apply_is_deterministic_across_two_calls():
    a = _run_default(*_seed_with_pressure_signal()[:2])
    # _seed_with_pressure_signal returns (kernel, signal_id, overall);
    # we only need (kernel, signal_id) for _run_default.
    b = _run_default(*_seed_with_pressure_signal()[:2])
    assert a.estimated_value == b.estimated_value
    assert a.confidence == b.confidence
    assert a.valuation_id == b.valuation_id


def test_apply_does_not_mutate_request():
    adapter = ValuationRefreshLiteAdapter()
    request = MechanismRunRequest(
        request_id="req:1",
        model_id=adapter.spec.model_id,
        actor_id=_FIRM,
        as_of_date=_AS_OF,
        evidence={
            "InformationSignal": [
                {
                    "signal_id": "s:1",
                    "signal_type": "firm_operating_pressure_assessment",
                    "subject_id": _FIRM,
                    "payload": {"overall_pressure": 0.5},
                },
            ],
        },
        parameters={"baseline_value": _BASELINE, "valuer_id": _VALUER},
    )
    pre = request.to_dict()
    adapter.apply(request)
    post = request.to_dict()
    assert pre == post


# ---------------------------------------------------------------------------
# Proposed valuation shape + boundary flags
# ---------------------------------------------------------------------------


def test_proposed_valuation_has_required_fields():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = _run_default(k, signal_id)
    proposed = result.output.proposed_valuation_records[0]
    for field in (
        "valuation_id",
        "subject_id",
        "valuer_id",
        "valuation_type",
        "purpose",
        "method",
        "as_of_date",
        "estimated_value",
        "currency",
        "numeraire",
        "confidence",
        "assumptions",
        "inputs",
        "related_ids",
        "metadata",
    ):
        assert field in proposed, f"missing field: {field}"


def test_proposed_valuation_method_label_is_synthetic_lite():
    k, signal_id, _ = _seed_with_pressure_signal()
    proposed = _run_default(k, signal_id).output.proposed_valuation_records[0]
    assert proposed["method"] == VALUATION_REFRESH_METHOD_LABEL
    assert proposed["method"] == "synthetic_lite_pressure_adjusted"


def test_proposed_valuation_metadata_carries_boundary_flags():
    k, signal_id, _ = _seed_with_pressure_signal()
    proposed = _run_default(k, signal_id).output.proposed_valuation_records[0]
    metadata = proposed["metadata"]
    assert metadata["no_price_movement"] is True
    assert metadata["no_investment_advice"] is True
    assert metadata["synthetic_only"] is True
    assert metadata["model_id"] == VALUATION_REFRESH_MODEL_ID
    assert metadata["pressure_signal_id"] == signal_id
    assert metadata["calibration_status"] == "synthetic"


def test_proposed_valuation_related_ids_include_pressure_signal():
    k, signal_id, _ = _seed_with_pressure_signal()
    proposed = _run_default(k, signal_id).output.proposed_valuation_records[0]
    assert signal_id in proposed["related_ids"]


# ---------------------------------------------------------------------------
# Caller helper
# ---------------------------------------------------------------------------


def test_caller_helper_commits_exactly_one_valuation_record():
    k, signal_id, _ = _seed_with_pressure_signal()
    before = len(k.valuations.all_valuations())
    result = _run_default(k, signal_id)
    after = k.valuations.all_valuations()
    assert len(after) - before == 1
    assert isinstance(result, ValuationRefreshLiteResult)
    record = k.valuations.get_valuation(result.valuation_id)
    assert record.valuation_type == "synthetic_firm_equity_estimate"
    assert record.method == VALUATION_REFRESH_METHOD_LABEL


def test_caller_helper_returns_run_record_with_lineage():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = _run_default(k, signal_id)
    run = result.run_record
    assert isinstance(run, MechanismRunRecord)
    assert run.input_refs == result.request.evidence_refs
    assert run.committed_output_refs == (result.valuation_id,)
    assert run.model_id == VALUATION_REFRESH_MODEL_ID
    assert run.model_family == VALUATION_REFRESH_MODEL_FAMILY


def test_caller_helper_preserves_evidence_refs_verbatim():
    k, signal_id, _ = _seed_with_pressure_signal()
    custom = (
        signal_id,
        "exposure:firm_a:fx",
        "obs:variable:reference_oil_price:2026Q1",
    )
    result = run_reference_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        pressure_signal_ids=(signal_id,),
        exposure_ids=("exposure:firm_a:fx",),
        variable_observation_ids=("obs:variable:reference_oil_price:2026Q1",),
        baseline_value=_BASELINE,
        evidence_refs=custom,
    )
    assert result.request.evidence_refs == custom
    assert result.run_record.input_refs == custom


def test_caller_helper_uses_kernel_clock_when_date_omitted():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = run_reference_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:test_kernel_clock",
    )
    assert result.request.as_of_date == _AS_OF


# ---------------------------------------------------------------------------
# Defensive errors
# ---------------------------------------------------------------------------


def test_caller_helper_rejects_kernel_none():
    with pytest.raises(ValueError):
        run_reference_valuation_refresh_lite(
            None, firm_id=_FIRM, valuer_id=_VALUER, as_of_date=_AS_OF
        )


def test_caller_helper_rejects_empty_firm_id():
    k = _seed_kernel()
    with pytest.raises(ValueError):
        run_reference_valuation_refresh_lite(
            k, firm_id="", valuer_id=_VALUER, as_of_date=_AS_OF
        )


def test_caller_helper_rejects_empty_valuer_id():
    k = _seed_kernel()
    with pytest.raises(ValueError):
        run_reference_valuation_refresh_lite(
            k, firm_id=_FIRM, valuer_id="", as_of_date=_AS_OF
        )


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def _capture_state(k: WorldKernel) -> dict[str, Any]:
    return {
        "prices": k.prices.snapshot(),
        "ownership": k.ownership.snapshot(),
        "contracts": k.contracts.snapshot(),
        "constraints": k.constraints.snapshot(),
        "exposures": k.exposures.snapshot(),
        "variables": k.variables.snapshot(),
        "institutions": k.institutions.snapshot(),
        "external_processes": k.external_processes.snapshot(),
        "relationships": k.relationships.snapshot(),
        "routines": k.routines.snapshot(),
        "attention": k.attention.snapshot(),
        "interactions": k.interactions.snapshot(),
        "signal_count": len(k.signals.all_signals()),
    }


def test_caller_helper_does_not_mutate_other_books():
    k, signal_id, _ = _seed_with_pressure_signal()
    before = _capture_state(k)
    _run_default(k, signal_id)
    after = _capture_state(k)
    # Valuations grew by exactly 1 (the committed valuation);
    # everything else is byte-equal.
    assert before == after


def test_caller_helper_writes_only_one_valuation_record_no_other_records():
    k, signal_id, _ = _seed_with_pressure_signal()
    before_ledger = len(k.ledger.records)
    before_valuations = len(k.valuations.all_valuations())
    _run_default(k, signal_id)
    after_ledger = len(k.ledger.records)
    after_valuations = len(k.valuations.all_valuations())
    assert after_valuations - before_valuations == 1
    # Exactly one new ledger record (the valuation_added entry
    # from ValuationBook.add_valuation).
    assert after_ledger - before_ledger == 1


# ---------------------------------------------------------------------------
# Synthetic-only identifiers
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "nyse",
)


def test_module_constants_use_no_jurisdiction_specific_tokens():
    candidates = (
        VALUATION_REFRESH_MODEL_ID,
        VALUATION_REFRESH_MODEL_FAMILY,
        VALUATION_REFRESH_METHOD_LABEL,
    )
    for c in candidates:
        for token in _FORBIDDEN_TOKENS:
            assert token not in c.lower(), c


def test_committed_valuation_identifiers_are_synthetic():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = _run_default(k, signal_id)
    record = k.valuations.get_valuation(result.valuation_id)
    candidates = [
        record.valuation_id,
        record.subject_id,
        record.valuer_id,
        record.valuation_type,
        record.method,
        record.purpose,
    ]
    for id_str in candidates:
        lower = id_str.lower()
        for token in _FORBIDDEN_TOKENS:
            for sep in (" ", ":", "/", "-", "_", "(", ")", ",", ".", "'", '"'):
                if f"{sep}{token}{sep}" in f" {lower} ":
                    pytest.fail(
                        f"forbidden token {token!r} appears in id {id_str!r}"
                    )


# ===========================================================================
# v1.12.5 — attention-conditioned valuation refresh lite helper
# ===========================================================================


_FORBIDDEN_VALUATION_PAYLOAD_KEYS = frozenset(
    {
        "target_price",
        "expected_return",
        "recommendation",
        "investment_advice",
        "buy",
        "sell",
        "overweight",
        "underweight",
        "rebalance",
        "target_weight",
        "portfolio_allocation",
        "execution",
        "order",
        "trade",
        "forecast_value",
        "real_data_value",
    }
)


def _seed_market_environment(
    kernel: WorldKernel,
    *,
    env_id: str = "market_environment:2026-04-30",
    overall_market_access_label: str = "open_or_constructive",
    risk_appetite_regime: str = "neutral",
    as_of_date: str = _AS_OF,
) -> str:
    kernel.market_environments.add_state(
        MarketEnvironmentStateRecord(
            environment_state_id=env_id,
            as_of_date=as_of_date,
            liquidity_regime="normal",
            volatility_regime="calm",
            credit_regime="neutral",
            funding_regime="normal",
            risk_appetite_regime=risk_appetite_regime,
            rate_environment="low",
            refinancing_window="open",
            equity_valuation_regime="neutral",
            overall_market_access_label=overall_market_access_label,
            status="active",
            visibility="internal_only",
            confidence=0.5,
        )
    )
    return env_id


def _seed_firm_state(
    kernel: WorldKernel,
    *,
    state_id: str = "firm_state:firm:reference_manufacturer_a:2026-04-30",
    firm_id: str = _FIRM,
    as_of_date: str = _AS_OF,
    funding_need_intensity: float = 0.4,
    market_access_pressure: float = 0.4,
) -> str:
    kernel.firm_financial_states.add_state(
        FirmFinancialStateRecord(
            state_id=state_id,
            firm_id=firm_id,
            as_of_date=as_of_date,
            status="active",
            visibility="internal_only",
            margin_pressure=0.4,
            liquidity_pressure=0.4,
            debt_service_pressure=0.4,
            market_access_pressure=market_access_pressure,
            funding_need_intensity=funding_need_intensity,
            response_readiness=0.5,
            confidence=0.5,
        )
    )
    return state_id


def _seed_capital_market_readout(
    kernel: WorldKernel,
    *,
    as_of_date: str = _AS_OF,
    regime_overall: str = "open_or_constructive",
) -> tuple[str, tuple[str, ...]]:
    if regime_overall == "open_or_constructive":
        directions = {
            "reference_rates": "supportive",
            "credit_spreads": "stable",
            "equity_market": "supportive",
            "funding_market": "supportive",
            "liquidity_market": "stable",
        }
    elif regime_overall == "selective_or_constrained":
        directions = {
            "reference_rates": "tightening",
            "credit_spreads": "restrictive",
            "equity_market": "restrictive",
            "funding_market": "mixed",
            "liquidity_market": "tightening",
        }
    else:
        raise ValueError(f"unknown overall {regime_overall!r}")
    spec_meta = (
        ("market:reference_rates_general", "reference_rates", "rate_level"),
        (
            "market:reference_credit_spreads_general",
            "credit_spreads",
            "spread_level",
        ),
        (
            "market:reference_equity_general",
            "equity_market",
            "valuation_environment",
        ),
        (
            "market:reference_funding_general",
            "funding_market",
            "funding_window",
        ),
        (
            "market:reference_liquidity_general",
            "liquidity_market",
            "liquidity_regime",
        ),
    )
    cids: list[str] = []
    for market_id, market_type, condition_type in spec_meta:
        cid = f"market_condition:{market_id}:{as_of_date}"
        kernel.market_conditions.add_condition(
            MarketConditionRecord(
                condition_id=cid,
                market_id=market_id,
                market_type=market_type,
                as_of_date=as_of_date,
                condition_type=condition_type,
                direction=directions[market_type],
                strength=0.5,
                time_horizon="medium_term",
                confidence=0.5,
                status="active",
                visibility="internal_only",
            )
        )
        cids.append(cid)
    readout = build_capital_market_readout(
        kernel,
        as_of_date=as_of_date,
        market_condition_ids=tuple(cids),
    )
    return readout.readout_id, tuple(cids)


def _seed_selection_with_refs(
    kernel: WorldKernel,
    *,
    selection_id: str,
    actor_id: str,
    selected_refs: tuple[str, ...],
    as_of_date: str = _AS_OF,
) -> str:
    """Seed an AttentionProfile + ObservationMenu + selection so the
    helper test can drive the resolver from a real
    SelectedObservationSet."""
    from world.attention import (
        AttentionProfile,
        ObservationMenu,
        SelectedObservationSet,
    )

    profile_id = f"profile:{actor_id}"
    try:
        kernel.attention.get_profile(profile_id)
    except Exception:
        kernel.attention.add_profile(
            AttentionProfile(
                profile_id=profile_id,
                actor_id=actor_id,
                actor_type="investor",
                update_frequency="QUARTERLY",
            )
        )
    menu_id = f"menu:{actor_id}:{as_of_date}"
    try:
        kernel.attention.get_menu(menu_id)
    except Exception:
        kernel.attention.add_menu(
            ObservationMenu(
                menu_id=menu_id,
                actor_id=actor_id,
                as_of_date=as_of_date,
            )
        )
    kernel.attention.add_selection(
        SelectedObservationSet(
            selection_id=selection_id,
            actor_id=actor_id,
            attention_profile_id=profile_id,
            menu_id=menu_id,
            selection_reason="explicit",
            as_of_date=as_of_date,
            status="completed",
            selected_refs=selected_refs,
        )
    )
    return selection_id


# ---------------------------------------------------------------------------
# v1.12.5 — resolver call + frame metadata
# ---------------------------------------------------------------------------


def test_attn_helper_records_context_frame_metadata():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
    )
    record = k.valuations.get_valuation(result.valuation_id)
    assert record.metadata.get("attention_conditioned") is True
    assert record.metadata.get("context_frame_id") == (
        f"context_frame:{_VALUER}:{_AS_OF}"
    )
    assert record.metadata.get("context_frame_status") in {
        "resolved",
        "partially_resolved",
        "empty",
    }
    cf_conf = record.metadata.get("context_frame_confidence")
    assert isinstance(cf_conf, (int, float)) and not isinstance(cf_conf, bool)
    assert 0.0 <= float(cf_conf) <= 1.0


def test_attn_helper_reads_only_selected_or_explicit_evidence():
    """Seed a pressure signal that the helper would surface only if
    it scanned globally; pass nothing; assert the helper produced a
    baseline-confidence valuation that did NOT consume it."""
    k, signal_id, _ = _seed_with_pressure_signal()
    # Caller passes no selected / explicit ids → the resolver
    # surfaces nothing → adapter takes the degraded path.
    result = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        baseline_value=_BASELINE,
    )
    record = k.valuations.get_valuation(result.valuation_id)
    # No pressure signal resolved → degraded path → estimated_value
    # equals the baseline (no haircut).
    assert record.estimated_value == _BASELINE
    # The pressure signal that exists in the kernel is NOT in
    # related_ids — the helper did not scan globally.
    assert signal_id not in record.related_ids


def test_attn_helper_unresolved_explicit_id_lands_in_unresolved_metadata():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=("signal:does_not_exist",),
        baseline_value=_BASELINE,
    )
    record = k.valuations.get_valuation(result.valuation_id)
    unresolved = record.metadata.get("unresolved_refs")
    assert unresolved is not None
    assert any(
        r["ref_id"] == "signal:does_not_exist" for r in unresolved
    )
    # Frame confidence is below 1.0 because at least one cited id
    # failed to resolve.
    assert record.metadata.get("context_frame_confidence") < 1.0
    assert record.metadata.get("context_frame_status") == (
        "partially_resolved"
    )


def test_attn_helper_strict_mode_raises_on_unknown_refs():
    k = _seed_kernel()
    with pytest.raises(StrictEvidenceResolutionError):
        run_attention_conditioned_valuation_refresh_lite(
            k,
            firm_id=_FIRM,
            valuer_id=_VALUER,
            as_of_date=_AS_OF,
            explicit_pressure_signal_ids=("signal:does_not_exist",),
            baseline_value=_BASELINE,
            strict=True,
        )
    # Strict failure must NOT leave a partial valuation in the book.
    assert k.valuations.all_valuations() == ()


def test_attn_helper_strict_mode_passes_when_all_resolve():
    k, signal_id, _ = _seed_with_pressure_signal()
    result = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        strict=True,
    )
    record = k.valuations.get_valuation(result.valuation_id)
    assert record.metadata.get("context_frame_status") == "resolved"


# ---------------------------------------------------------------------------
# v1.12.5 — headline divergence test (the success criterion)
# ---------------------------------------------------------------------------


def test_attn_divergence_three_valuers_three_evidence_sets_diverge():
    """Headline v1.12.5 test. Three valuers cite three different
    evidence sets for the same firm and same period; the helper
    must produce records that differ on at least one of
    (estimated_value, confidence). This proves attention is
    load-bearing for valuation.

    Valuer A cites: pressure signal only (the v1.9.5 baseline path).
    Valuer B cites: pressure signal + restrictive market env.
    Valuer C cites: nothing (degraded path).
    """
    k, signal_id, _ = _seed_with_pressure_signal()
    env_id = _seed_market_environment(
        k,
        env_id="market_environment:divergence:2026-04-30",
        overall_market_access_label="selective_or_constrained",
        risk_appetite_regime="risk_off",
    )

    result_a = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_analyst_desk_a",
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:divergence:a",
    )
    result_b = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_analyst_desk_b",
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        explicit_market_environment_state_ids=(env_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:divergence:b",
    )
    result_c = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_analyst_desk_c",
        as_of_date=_AS_OF,
        baseline_value=_BASELINE,
        valuation_id="valuation:divergence:c",
    )

    rec_a = k.valuations.get_valuation(result_a.valuation_id)
    rec_b = k.valuations.get_valuation(result_b.valuation_id)
    rec_c = k.valuations.get_valuation(result_c.valuation_id)

    # At least two of the three must differ on either
    # estimated_value or confidence.
    triples = [
        (rec_a.estimated_value, rec_a.confidence),
        (rec_b.estimated_value, rec_b.confidence),
        (rec_c.estimated_value, rec_c.confidence),
    ]
    distinct = set(triples)
    assert len(distinct) >= 2, (
        f"three valuers must produce at least two distinct "
        f"(estimated_value, confidence) triples; got {triples!r}"
    )

    # Pin the qualitative ordering: B's restrictive market resolved
    # a downward synthetic delta, so B's estimated_value must be
    # strictly lower than A's (same baseline, same pressure signal).
    assert rec_b.estimated_value is not None
    assert rec_a.estimated_value is not None
    assert rec_b.estimated_value < rec_a.estimated_value
    # C took the degraded path → estimated_value equals baseline.
    assert rec_c.estimated_value == _BASELINE


# ---------------------------------------------------------------------------
# v1.12.5 — selection refs flow through to resolved buckets
# ---------------------------------------------------------------------------


def test_attn_helper_selection_ref_flows_through_to_signal_bucket():
    """Seed a SelectedObservationSet whose selected_refs include a
    pressure-signal id; assert the helper's resolved frame routed
    it into the signal bucket and the record reflects it (the
    v1.9.5 pressure haircut fires)."""
    k, signal_id, _ = _seed_with_pressure_signal()
    sel_id = _seed_selection_with_refs(
        k,
        selection_id="selection:via_attention",
        actor_id=_VALUER,
        selected_refs=(signal_id,),
    )
    result = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        selected_observation_set_ids=(sel_id,),
        baseline_value=_BASELINE,
    )
    record = k.valuations.get_valuation(result.valuation_id)
    # The pressure signal is in related_ids (resolver routed it
    # through the signal bucket).
    assert signal_id in record.related_ids
    # And the v1.9.5 pressure haircut fired (estimated_value
    # strictly below the baseline).
    assert record.estimated_value is not None
    assert record.estimated_value < _BASELINE


# ---------------------------------------------------------------------------
# v1.12.5 — no source-book mutation
# ---------------------------------------------------------------------------


def _capture_state_attn(k: WorldKernel) -> dict[str, Any]:
    return {
        "prices": k.prices.snapshot(),
        "ownership": k.ownership.snapshot(),
        "contracts": k.contracts.snapshot(),
        "constraints": k.constraints.snapshot(),
        "exposures": k.exposures.snapshot(),
        "variables": k.variables.snapshot(),
        "institutions": k.institutions.snapshot(),
        "external_processes": k.external_processes.snapshot(),
        "relationships": k.relationships.snapshot(),
        "routines": k.routines.snapshot(),
        "attention": k.attention.snapshot(),
        "interactions": k.interactions.snapshot(),
        "market_conditions": k.market_conditions.snapshot(),
        "capital_market_readouts": k.capital_market_readouts.snapshot(),
        "market_environments": k.market_environments.snapshot(),
        "firm_financial_states": k.firm_financial_states.snapshot(),
        "signal_count": len(k.signals.all_signals()),
    }


def test_attn_helper_does_not_mutate_other_books():
    k, signal_id, _ = _seed_with_pressure_signal()
    fsid = _seed_firm_state(k)
    rid, _ = _seed_capital_market_readout(k)
    env_id = _seed_market_environment(k)
    before = _capture_state_attn(k)
    run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        explicit_firm_state_ids=(fsid,),
        explicit_market_readout_ids=(rid,),
        explicit_market_environment_state_ids=(env_id,),
        baseline_value=_BASELINE,
    )
    after = _capture_state_attn(k)
    assert before == after


# ---------------------------------------------------------------------------
# v1.12.5 — anti-fields on the ledger payload
# ---------------------------------------------------------------------------


def test_attn_helper_emits_no_forbidden_payload_keys():
    k, signal_id, _ = _seed_with_pressure_signal()
    run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
    )
    val_records = k.ledger.filter(event_type="valuation_added")
    assert val_records
    for rec in val_records:
        leaked = (
            set(rec.payload.keys()) & _FORBIDDEN_VALUATION_PAYLOAD_KEYS
        )
        assert not leaked, (
            f"v1.12.5 helper leaked forbidden payload keys: "
            f"{sorted(leaked)}"
        )
    # The committed valuation's metadata must not carry anti-fields.
    record = k.valuations.list_by_subject(_FIRM)[0]
    assert not (
        set(record.metadata.keys()) & _FORBIDDEN_VALUATION_PAYLOAD_KEYS
    )
    # And no anti-field event types in the ledger at all.
    forbidden_event_types = {
        "order_submitted",
        "price_updated",
        "ownership_position_added",
        "ownership_transferred",
        "contract_created",
        "contract_status_updated",
        "contract_covenant_breached",
    }
    seen_event_types = {r.record_type.value for r in k.ledger.records}
    assert seen_event_types.isdisjoint(forbidden_event_types)


# ---------------------------------------------------------------------------
# v1.12.5 — determinism + idempotency
# ---------------------------------------------------------------------------


def test_attn_helper_deterministic_for_identical_inputs():
    """Two fresh kernels with identical inputs produce
    byte-identical record output."""
    k_a, sig_a, _ = _seed_with_pressure_signal()
    out_a = run_attention_conditioned_valuation_refresh_lite(
        k_a,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(sig_a,),
        baseline_value=_BASELINE,
    )
    rec_a = k_a.valuations.get_valuation(out_a.valuation_id)

    k_b, sig_b, _ = _seed_with_pressure_signal()
    out_b = run_attention_conditioned_valuation_refresh_lite(
        k_b,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(sig_b,),
        baseline_value=_BASELINE,
    )
    rec_b = k_b.valuations.get_valuation(out_b.valuation_id)

    assert rec_a.to_dict() == rec_b.to_dict()


def test_attn_helper_idempotent_on_valuation_id():
    k, signal_id, _ = _seed_with_pressure_signal()
    out1 = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:idempotent",
    )
    out2 = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:idempotent",
    )
    assert out1.valuation_id == out2.valuation_id
    # Only one record committed.
    assert len(k.valuations.list_by_subject(_FIRM)) == 1


# ---------------------------------------------------------------------------
# v1.12.5 — confidence-ordering pin (more cited → higher confidence)
# ---------------------------------------------------------------------------


def test_attn_helper_more_resolved_evidence_yields_higher_confidence():
    """Pin the qualitative ordering: a valuer who cites more
    resolved evidence sees a strictly-higher synthetic confidence
    on the produced valuation than a valuer who cites only the
    pressure signal (under the same pressure signal and baseline)."""
    k, signal_id, _ = _seed_with_pressure_signal()
    fsid = _seed_firm_state(k)
    rid, _ = _seed_capital_market_readout(k)

    result_thin = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_thin",
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:confidence:thin",
    )
    result_rich = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_rich",
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        explicit_firm_state_ids=(fsid,),
        explicit_market_readout_ids=(rid,),
        baseline_value=_BASELINE,
        valuation_id="valuation:confidence:rich",
    )

    rec_thin = k.valuations.get_valuation(result_thin.valuation_id)
    rec_rich = k.valuations.get_valuation(result_rich.valuation_id)

    assert rec_rich.confidence > rec_thin.confidence


def test_attn_helper_unresolved_refs_lower_confidence():
    """A valuer with one unresolved cited id sees a lower
    confidence than the same valuer with the same pressure signal
    but no unresolved id."""
    k, signal_id, _ = _seed_with_pressure_signal()
    result_clean = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_clean",
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
        valuation_id="valuation:unresolved:clean",
    )
    result_dirty = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id="valuer:reference_dirty",
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        explicit_firm_state_ids=(
            "firm_state:does_not_exist_a",
            "firm_state:does_not_exist_b",
        ),
        baseline_value=_BASELINE,
        valuation_id="valuation:unresolved:dirty",
    )
    rec_clean = k.valuations.get_valuation(result_clean.valuation_id)
    rec_dirty = k.valuations.get_valuation(result_dirty.valuation_id)
    assert rec_dirty.confidence < rec_clean.confidence


# ---------------------------------------------------------------------------
# v1.12.5 — defensive errors
# ---------------------------------------------------------------------------


def test_attn_helper_rejects_kernel_none():
    with pytest.raises(ValueError):
        run_attention_conditioned_valuation_refresh_lite(
            None,
            firm_id=_FIRM,
            valuer_id=_VALUER,
            as_of_date=_AS_OF,
        )


def test_attn_helper_rejects_empty_firm_id():
    k = _seed_kernel()
    with pytest.raises(ValueError):
        run_attention_conditioned_valuation_refresh_lite(
            k,
            firm_id="",
            valuer_id=_VALUER,
            as_of_date=_AS_OF,
        )


def test_attn_helper_rejects_empty_valuer_id():
    k = _seed_kernel()
    with pytest.raises(ValueError):
        run_attention_conditioned_valuation_refresh_lite(
            k,
            firm_id=_FIRM,
            valuer_id="",
            as_of_date=_AS_OF,
        )


# ---------------------------------------------------------------------------
# v1.12.5 — jurisdiction-neutral identifier scan
# ---------------------------------------------------------------------------


def test_attn_helper_committed_record_uses_no_jurisdiction_specific_tokens():
    """Mirror the existing _FORBIDDEN_TOKENS test for the v1.12.5
    helper output."""
    k, signal_id, _ = _seed_with_pressure_signal()
    result = run_attention_conditioned_valuation_refresh_lite(
        k,
        firm_id=_FIRM,
        valuer_id=_VALUER,
        as_of_date=_AS_OF,
        explicit_pressure_signal_ids=(signal_id,),
        baseline_value=_BASELINE,
    )
    record = k.valuations.get_valuation(result.valuation_id)
    candidates = [
        record.valuation_id,
        record.subject_id,
        record.valuer_id,
        record.valuation_type,
        record.method,
        record.purpose,
        record.metadata.get("context_frame_id", ""),
    ]
    for id_str in candidates:
        lower = str(id_str).lower()
        for token in _FORBIDDEN_TOKENS:
            for sep in (" ", ":", "/", "-", "_", "(", ")", ",", ".", "'", '"'):
                if f"{sep}{token}{sep}" in f" {lower} ":
                    pytest.fail(
                        f"forbidden token {token!r} appears in id "
                        f"{id_str!r}"
                    )
