"""
Tests for the v1.9.3 mechanism interface contract.

These tests pin the **shape** of the five types in
``world/mechanisms.py`` so v1.9.4+ concrete mechanisms cannot
accidentally break the contract by adding / removing required
fields.

v1.9.3 ships no behavior, so no behavior is tested here. Every
assertion is structural:

- the dataclasses are immutable (``frozen=True``);
- every required field exists with the documented name;
- every required field validates non-empty / non-negative inputs;
- ``to_dict`` round-trips JSON-friendly;
- the ``MechanismAdapter`` Protocol's ``isinstance`` check
  recognises a minimally-shaped class.

If a test in this file fails, a v1.9.4 mechanism cannot be safely
landed without first updating
``docs/model_mechanism_inventory.md`` and the contract.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass

import pytest

from world.mechanisms import (
    CALIBRATION_STATUSES,
    MECHANISM_FAMILIES,
    STOCHASTICITY_LABELS,
    MechanismAdapter,
    MechanismInputBundle,
    MechanismOutputBundle,
    MechanismRunRecord,
    MechanismSpec,
)


# ---------------------------------------------------------------------------
# Required-field contract
# ---------------------------------------------------------------------------


_REQUIRED_SPEC_FIELDS: frozenset[str] = frozenset(
    {
        "model_id",
        "model_family",
        "version",
        "assumptions",
        "calibration_status",
        "stochasticity",
        "required_inputs",
        "output_types",
        "metadata",
    }
)


_REQUIRED_INPUT_FIELDS: frozenset[str] = frozenset(
    {
        "request_id",
        "model_id",
        "actor_id",
        "as_of_date",
        "selected_observation_set_ids",
        "input_refs",
        "state_views",
        "parameters",
        "metadata",
    }
)


_REQUIRED_OUTPUT_FIELDS: frozenset[str] = frozenset(
    {
        "request_id",
        "model_id",
        "status",
        "proposed_signals",
        "proposed_valuation_records",
        "proposed_constraint_pressure_deltas",
        "proposed_intent_records",
        "proposed_run_records",
        "output_summary",
        "warnings",
        "metadata",
    }
)


_REQUIRED_RUN_RECORD_FIELDS: frozenset[str] = frozenset(
    {
        "run_id",
        "request_id",
        "model_id",
        "model_family",
        "version",
        "actor_id",
        "as_of_date",
        "status",
        "input_refs",
        "committed_output_refs",
        "parent_record_ids",
        "input_summary_hash",
        "output_summary_hash",
        "metadata",
    }
)


def test_every_required_dataclass_is_a_dataclass():
    assert is_dataclass(MechanismSpec)
    assert is_dataclass(MechanismInputBundle)
    assert is_dataclass(MechanismOutputBundle)
    assert is_dataclass(MechanismRunRecord)


def test_mechanism_spec_required_fields():
    actual = {f.name for f in fields(MechanismSpec)}
    missing = _REQUIRED_SPEC_FIELDS - actual
    assert missing == set()


def test_mechanism_input_bundle_required_fields():
    actual = {f.name for f in fields(MechanismInputBundle)}
    missing = _REQUIRED_INPUT_FIELDS - actual
    assert missing == set()


def test_mechanism_output_bundle_required_fields():
    actual = {f.name for f in fields(MechanismOutputBundle)}
    missing = _REQUIRED_OUTPUT_FIELDS - actual
    assert missing == set()


def test_mechanism_run_record_required_fields():
    actual = {f.name for f in fields(MechanismRunRecord)}
    missing = _REQUIRED_RUN_RECORD_FIELDS - actual
    assert missing == set()


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def _spec() -> MechanismSpec:
    return MechanismSpec(
        model_id="mechanism:firm_financial_mechanism:reference_v0",
        model_family="firm_financial_mechanism",
        version="0.1",
    )


def test_spec_is_frozen():
    spec = _spec()
    with pytest.raises(Exception):
        spec.model_id = "tampered"  # type: ignore[misc]


def test_input_bundle_is_frozen():
    bundle = MechanismInputBundle(
        request_id="req:1",
        model_id=_spec().model_id,
        actor_id="firm:reference_a",
        as_of_date="2026-04-30",
    )
    with pytest.raises(Exception):
        bundle.request_id = "tampered"  # type: ignore[misc]


def test_output_bundle_is_frozen():
    output = MechanismOutputBundle(
        request_id="req:1",
        model_id=_spec().model_id,
    )
    with pytest.raises(Exception):
        output.request_id = "tampered"  # type: ignore[misc]


def test_run_record_is_frozen():
    run = MechanismRunRecord(
        run_id="mechanism_run:req:1",
        request_id="req:1",
        model_id=_spec().model_id,
        model_family="firm_financial_mechanism",
        version="0.1",
        actor_id="firm:reference_a",
        as_of_date="2026-04-30",
    )
    with pytest.raises(Exception):
        run.run_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validation: empty / wrong-type inputs are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model_id": ""},
        {"model_family": ""},
        {"version": ""},
        {"calibration_status": ""},
        {"stochasticity": ""},
    ],
)
def test_spec_rejects_empty_required_strings(kwargs):
    base = {
        "model_id": "mechanism:x:y",
        "model_family": "firm_financial_mechanism",
        "version": "0.1",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        MechanismSpec(**base)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "assumptions",
        "required_inputs",
        "output_types",
    ],
)
def test_spec_rejects_empty_strings_in_tuple_fields(tuple_field):
    with pytest.raises(ValueError):
        MechanismSpec(
            model_id="mechanism:x:y",
            model_family="firm_financial_mechanism",
            version="0.1",
            **{tuple_field: ("ok", "")},
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_id": ""},
        {"model_id": ""},
        {"actor_id": ""},
        {"as_of_date": ""},
    ],
)
def test_input_bundle_rejects_empty_required_strings(kwargs):
    base = {
        "request_id": "req:1",
        "model_id": "mechanism:x:y",
        "actor_id": "firm:reference_a",
        "as_of_date": "2026-04-30",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        MechanismInputBundle(**base)


def test_output_bundle_rejects_non_mapping_proposals():
    with pytest.raises(ValueError):
        MechanismOutputBundle(
            request_id="req:1",
            model_id="mechanism:x:y",
            proposed_signals=("not-a-mapping",),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"run_id": ""},
        {"request_id": ""},
        {"model_id": ""},
        {"model_family": ""},
        {"version": ""},
        {"actor_id": ""},
        {"as_of_date": ""},
        {"status": ""},
    ],
)
def test_run_record_rejects_empty_required_strings(kwargs):
    base = {
        "run_id": "mechanism_run:req:1",
        "request_id": "req:1",
        "model_id": "mechanism:x:y",
        "model_family": "firm_financial_mechanism",
        "version": "0.1",
        "actor_id": "firm:reference_a",
        "as_of_date": "2026-04-30",
    }
    base.update(kwargs)
    with pytest.raises(ValueError):
        MechanismRunRecord(**base)


# ---------------------------------------------------------------------------
# to_dict round-trips through JSON
# ---------------------------------------------------------------------------


def test_spec_to_dict_round_trips_through_json():
    spec = MechanismSpec(
        model_id="mechanism:x:y",
        model_family="firm_financial_mechanism",
        version="0.1",
        assumptions=("a",),
        required_inputs=("VariableObservation",),
        output_types=("InformationSignal",),
        metadata={"k": "v"},
    )
    encoded = json.dumps(spec.to_dict(), sort_keys=True, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["model_id"] == spec.model_id
    assert decoded["assumptions"] == ["a"]
    assert decoded["required_inputs"] == ["VariableObservation"]


def test_input_bundle_to_dict_round_trips_through_json():
    bundle = MechanismInputBundle(
        request_id="req:1",
        model_id="mechanism:x:y",
        actor_id="firm:reference_a",
        as_of_date="2026-04-30",
        selected_observation_set_ids=("sel:1",),
        state_views={"balance_sheet": {"cash": 100.0}},
        parameters={"sensitivity": 0.5},
    )
    encoded = json.dumps(bundle.to_dict(), sort_keys=True, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["selected_observation_set_ids"] == ["sel:1"]
    assert decoded["state_views"] == {"balance_sheet": {"cash": 100.0}}
    assert decoded["parameters"] == {"sensitivity": 0.5}


def test_output_bundle_total_proposed_count_sums_correctly():
    output = MechanismOutputBundle(
        request_id="req:1",
        model_id="mechanism:x:y",
        proposed_signals=({"id": "s:1"}, {"id": "s:2"}),
        proposed_valuation_records=({"id": "v:1"},),
    )
    assert output.total_proposed_count == 3


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


def test_minimal_adapter_satisfies_protocol():
    spec = _spec()

    class _Stub:
        def __init__(self, s: MechanismSpec) -> None:
            self.spec = s

        def apply(self, bundle: MechanismInputBundle) -> MechanismOutputBundle:
            return MechanismOutputBundle(
                request_id=bundle.request_id,
                model_id=bundle.model_id,
            )

    stub = _Stub(spec)
    assert isinstance(stub, MechanismAdapter)


def test_class_without_apply_does_not_satisfy_protocol():
    class _MissingApply:
        spec = _spec()

    assert not isinstance(_MissingApply(), MechanismAdapter)


# ---------------------------------------------------------------------------
# Vocabulary constants
# ---------------------------------------------------------------------------


def test_mechanism_families_includes_recommended_set():
    expected = {
        "firm_financial_mechanism",
        "valuation_mechanism",
        "credit_review_mechanism",
        "investor_intent_mechanism",
        "market_mechanism",
    }
    assert expected.issubset(set(MECHANISM_FAMILIES))


def test_calibration_statuses_covers_three_canonical_levels():
    assert set(CALIBRATION_STATUSES) == {
        "synthetic",
        "public_data_calibrated",
        "proprietary_calibrated",
    }


def test_stochasticity_labels_covers_three_canonical_levels():
    assert set(STOCHASTICITY_LABELS) == {
        "deterministic",
        "pinned_seed",
        "open_seed",
    }


# ---------------------------------------------------------------------------
# Anti-behavior: instantiating these types does not touch a kernel
# ---------------------------------------------------------------------------


def test_constructing_interface_records_does_not_require_a_kernel():
    """Sanity check: every interface dataclass is pure data and
    constructs without needing any v0/v1 book or kernel. v1.9.3
    ships no behavior; this test pins that property."""
    _ = MechanismSpec(
        model_id="m:1",
        model_family="firm_financial_mechanism",
        version="0.1",
    )
    _ = MechanismInputBundle(
        request_id="req:1",
        model_id="m:1",
        actor_id="firm:a",
        as_of_date="2026-04-30",
    )
    _ = MechanismOutputBundle(request_id="req:1", model_id="m:1")
    _ = MechanismRunRecord(
        run_id="mr:1",
        request_id="req:1",
        model_id="m:1",
        model_family="firm_financial_mechanism",
        version="0.1",
        actor_id="firm:a",
        as_of_date="2026-04-30",
    )
