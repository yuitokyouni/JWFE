"""
v1.9.3 Mechanism interface (contract only — no behavior).

This module ships the **contract** that v1.9.4+ economic-behavior
mechanisms will plug into. v1.9.3 adds no economic behavior; the
five types defined here are pure data + a Protocol. Concrete
mechanisms (firm-financial, valuation, credit-review,
investor-intent, and later market mechanisms) attach as
:class:`MechanismAdapter` implementations in subsequent
milestones.

Why an interface ships before any mechanism
-------------------------------------------

The v1.9.3 audit
(``docs/model_mechanism_inventory.md`` + ``docs/behavioral_gap_audit.md``)
records that the project so far is a **routine-driven
information-flow substrate** rather than a model. Mechanisms are
the missing layer. Locking the interface now — in a milestone
that does not introduce any behavior — means that v1.9.4's first
mechanism cannot accidentally introduce a divergent shape.

Principles (also documented in the inventory)
---------------------------------------------

1. **Mechanisms do not directly mutate books.** They *propose*
   outputs; the caller decides what is committed.
2. **Mechanisms consume typed refs / selected observations /
   state views.** Inputs are explicit; no hidden globals.
3. **Mechanisms return proposed records or output bundles.**
4. **The caller decides which outputs are committed.**
5. **Every mechanism run is ledger-auditable** — through a
   :class:`MechanismRunRecord` the caller writes (the record is
   immutable; a future v1.9.x may give it its own ledger
   record-type, or fold it into ``ROUTINE_RUN_RECORDED``).
6. **Each mechanism declares**: ``model_id``, ``model_family``,
   ``version``, ``assumptions``, ``calibration_status``,
   ``stochasticity``, ``required_inputs``, ``output_types``.
7. **Reference mechanisms are simple and synthetic.** v1.9.4 –
   v1.9.6 mechanisms are jurisdiction-neutral, deterministic
   (or pinned-seed stochastic), and produce visible ledger
   traces.
8. **Advanced mechanisms attach as adapters.** FCN (Fundamental
   / Chartist / Noise), herding, minority-game, speculation
   game, LOB-style market microstructure adapters are explicit
   v2+ candidates. The :class:`MechanismAdapter` Protocol is
   exactly the seam they will use.

Suggested mechanism families (v1.9.4+)
---------------------------------------

- ``firm_financial_mechanism`` — synthetic margin / liquidity /
  debt pressure update.
- ``valuation_mechanism`` — selected refs → ``ValuationRecord``
  proposals.
- ``credit_review_mechanism`` — selected refs → credit-review
  notes + constraint-pressure deltas.
- ``investor_intent_mechanism`` — selected refs → non-binding
  ``investor_intent`` records (no orders, no trades).
- ``market_mechanism`` — FCN / herding / minority-game /
  speculation-game / LOB adapters. v2+ territory.

Anti-scope
----------

v1.9.3 does **not** ship:

- any concrete mechanism (those are v1.9.4 onward);
- any new ledger record type;
- any auto-firing scheduler hook (mechanisms remain
  caller-initiated, like the rest of v1.x);
- any economic interpretation of any record;
- any real-data ingestion or Japan-specific calibration.

Calibration vocabulary
----------------------

``MechanismSpec.calibration_status`` is a free-form string but
should follow this vocabulary so future tooling can group
mechanisms by maturity:

- ``"synthetic"`` — illustrative round numbers, not calibrated
  to any data.
- ``"public_data_calibrated"`` — driven by openly available data
  (v2 territory).
- ``"proprietary_calibrated"`` — driven by paid / expert data
  (v3 territory; private repo only).

Stochasticity vocabulary
------------------------

``MechanismSpec.stochasticity`` is a free-form string but should
follow:

- ``"deterministic"`` — given the same input, same output.
- ``"pinned_seed"`` — randomness derived from a declared seed,
  reproducible byte-for-byte.
- ``"open_seed"`` — non-reproducible randomness. Forbidden in
  v1.x deterministic-replay milestones.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable


# Canonical labels reserved by v1.9.3. Concrete mechanisms in
# v1.9.4+ are encouraged to use these strings so the inventory
# tooling can group them; free-form values are still permitted.
MECHANISM_FAMILIES: tuple[str, ...] = (
    "firm_financial_mechanism",
    "valuation_mechanism",
    "credit_review_mechanism",
    "investor_intent_mechanism",
    "market_mechanism",
    "macro_process_mechanism",
)

CALIBRATION_STATUSES: tuple[str, ...] = (
    "synthetic",
    "public_data_calibrated",
    "proprietary_calibrated",
)

STOCHASTICITY_LABELS: tuple[str, ...] = (
    "deterministic",
    "pinned_seed",
    "open_seed",
)


# ---------------------------------------------------------------------------
# MechanismSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MechanismSpec:
    """
    Declarative description of a mechanism.

    A spec is **data**: it carries no behavior. Concrete
    mechanisms ship a spec instance plus an
    :class:`MechanismAdapter` that interprets inputs against the
    spec. Two adapters with byte-identical specs must produce
    byte-identical outputs on byte-identical inputs (the
    deterministic-replay invariant).

    Field semantics
    ---------------
    - ``model_id`` is a stable, unique id for this mechanism.
      Suggested format: ``"mechanism:<family>:<short_label>"``.
    - ``model_family`` names the broad mechanism family
      (suggested values in :data:`MECHANISM_FAMILIES`).
    - ``version`` is a free-form version string. Suggested:
      semantic-version style ``"1.0"`` / ``"1.0.1"``.
    - ``assumptions`` is a tuple of free-form strings naming
      the modeling assumptions a reader should know about.
      Suggested examples: ``"linear_pressure_aggregation"``,
      ``"ignores_lag_structure"``, ``"jurisdiction_neutral"``.
    - ``calibration_status`` follows
      :data:`CALIBRATION_STATUSES`.
    - ``stochasticity`` follows :data:`STOCHASTICITY_LABELS`.
    - ``required_inputs`` is a tuple naming the input record
      types the adapter expects (e.g.,
      ``"SelectedObservationSet"``, ``"VariableObservation"``,
      ``"ExposureRecord"``).
    - ``output_types`` is a tuple naming the proposed-record
      types the adapter emits (e.g., ``"InformationSignal"``,
      ``"ValuationRecord"``).
    - ``metadata`` is free-form: provenance notes, references,
      doc paths.
    """

    model_id: str
    model_family: str
    version: str
    assumptions: tuple[str, ...] = field(default_factory=tuple)
    calibration_status: str = "synthetic"
    stochasticity: str = "deterministic"
    required_inputs: tuple[str, ...] = field(default_factory=tuple)
    output_types: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("model_id", "model_family", "version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{name} is required and must be a non-empty string"
                )
        if not isinstance(self.calibration_status, str) or not self.calibration_status:
            raise ValueError("calibration_status is required")
        if not isinstance(self.stochasticity, str) or not self.stochasticity:
            raise ValueError("stochasticity is required")

        for tuple_field_name in (
            "assumptions",
            "required_inputs",
            "output_types",
        ):
            value = tuple(getattr(self, tuple_field_name))
            for entry in value:
                if not isinstance(entry, str) or not entry:
                    raise ValueError(
                        f"{tuple_field_name} entries must be non-empty strings"
                    )
            object.__setattr__(self, tuple_field_name, value)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_family": self.model_family,
            "version": self.version,
            "assumptions": list(self.assumptions),
            "calibration_status": self.calibration_status,
            "stochasticity": self.stochasticity,
            "required_inputs": list(self.required_inputs),
            "output_types": list(self.output_types),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# MechanismInputBundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MechanismInputBundle:
    """
    Typed input bundle for one mechanism call.

    The bundle is **read-only**. Concrete mechanisms must not
    mutate any field; the dataclass is frozen to enforce this at
    runtime.

    Field semantics
    ---------------
    - ``request_id`` is a stable id for this invocation. Used to
      derive the resulting :class:`MechanismRunRecord` id.
    - ``model_id`` echoes the spec's id so the bundle is
      self-describing (the caller can route the same bundle to
      different adapters by changing only this field).
    - ``actor_id`` is the actor on whose behalf the mechanism is
      running (firm / investor / bank / external observer).
    - ``as_of_date`` is ISO ``YYYY-MM-DD``.
    - ``selected_observation_set_ids`` is a tuple of
      :class:`SelectedObservationSet` ids the mechanism may
      consume.
    - ``input_refs`` is a tuple of arbitrary record ids
      (signals, observations, exposures, valuations, ...) the
      caller hands in directly. Mechanisms must declare what
      types they expect via the spec's ``required_inputs``.
    - ``state_views`` is a free-form mapping from a logical name
      to a deterministic snapshot dict (e.g., a balance-sheet
      view). Stored as data; not mutable.
    - ``parameters`` is a free-form mapping carrying any extra
      caller-supplied mechanism parameters (e.g., a synthetic
      sensitivity weight). v1.9.3 does not constrain the shape
      beyond JSON-friendliness.
    - ``metadata`` is free-form.
    """

    request_id: str
    model_id: str
    actor_id: str
    as_of_date: str
    selected_observation_set_ids: tuple[str, ...] = field(default_factory=tuple)
    input_refs: tuple[str, ...] = field(default_factory=tuple)
    state_views: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    parameters: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("request_id", "model_id", "actor_id", "as_of_date"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{name} is required and must be a non-empty string"
                )

        for tuple_field_name in (
            "selected_observation_set_ids",
            "input_refs",
        ):
            value = tuple(getattr(self, tuple_field_name))
            for entry in value:
                if not isinstance(entry, str) or not entry:
                    raise ValueError(
                        f"{tuple_field_name} entries must be non-empty strings"
                    )
            object.__setattr__(self, tuple_field_name, value)

        # state_views: dict[str, dict[str, Any]]; freeze copies.
        normalised_views: dict[str, dict[str, Any]] = {}
        for k, v in dict(self.state_views).items():
            if not isinstance(k, str) or not k:
                raise ValueError("state_views keys must be non-empty strings")
            normalised_views[k] = dict(v) if isinstance(v, Mapping) else {"value": v}
        object.__setattr__(self, "state_views", normalised_views)

        object.__setattr__(self, "parameters", dict(self.parameters))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model_id": self.model_id,
            "actor_id": self.actor_id,
            "as_of_date": self.as_of_date,
            "selected_observation_set_ids": list(
                self.selected_observation_set_ids
            ),
            "input_refs": list(self.input_refs),
            "state_views": {k: dict(v) for k, v in self.state_views.items()},
            "parameters": dict(self.parameters),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# MechanismOutputBundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MechanismOutputBundle:
    """
    Typed output bundle from one mechanism call.

    The bundle carries **proposals**, not commits. The caller
    chooses which proposals (if any) to write through to a book.
    A mechanism that wants something committed lists it here;
    nothing else flips state.

    Field semantics
    ---------------
    - ``request_id`` mirrors the input bundle's request id.
    - ``model_id`` echoes the spec.
    - ``status`` is a free-form short label. Suggested vocabulary
      (mirroring v1.8.1 anti-scenario discipline): ``"completed"``
      when inputs flowed through cleanly; ``"degraded"`` when
      some inputs were missing or empty; ``"skipped"`` when the
      adapter chose not to run; ``"failed"`` is reserved for
      hard errors (mechanisms should prefer ``degraded``).
    - ``proposed_signals`` / ``proposed_valuation_records`` /
      ``proposed_constraint_pressure_deltas`` /
      ``proposed_intent_records`` /
      ``proposed_run_records`` are tuples of dataclass-shaped
      *proposals*. v1.9.3 carries them as opaque tuples of dicts
      so the contract does not pull in v1.9.4+ record types
      prematurely. Adapters in v1.9.4+ may switch to typed
      tuples per family.
    - ``output_summary`` is a free-form mapping carrying any
      counts, ranges, or audit fields the mechanism wants the
      :class:`MechanismRunRecord` to capture.
    - ``warnings`` is a tuple of free-form non-fatal warning
      strings.
    - ``metadata`` is free-form.
    """

    request_id: str
    model_id: str
    status: str = "completed"
    proposed_signals: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    proposed_valuation_records: tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    proposed_constraint_pressure_deltas: tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    proposed_intent_records: tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    proposed_run_records: tuple[Mapping[str, Any], ...] = field(
        default_factory=tuple
    )
    output_summary: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("request_id", "model_id", "status"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{name} is required and must be a non-empty string"
                )

        for tuple_field_name in (
            "proposed_signals",
            "proposed_valuation_records",
            "proposed_constraint_pressure_deltas",
            "proposed_intent_records",
            "proposed_run_records",
        ):
            value = tuple(getattr(self, tuple_field_name))
            for entry in value:
                if not isinstance(entry, Mapping):
                    raise ValueError(
                        f"{tuple_field_name} entries must be Mapping[str, Any]"
                    )
            normalised = tuple(dict(entry) for entry in value)
            object.__setattr__(self, tuple_field_name, normalised)

        warnings_value = tuple(self.warnings)
        for entry in warnings_value:
            if not isinstance(entry, str) or not entry:
                raise ValueError("warnings entries must be non-empty strings")
        object.__setattr__(self, "warnings", warnings_value)

        object.__setattr__(self, "output_summary", dict(self.output_summary))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def total_proposed_count(self) -> int:
        return (
            len(self.proposed_signals)
            + len(self.proposed_valuation_records)
            + len(self.proposed_constraint_pressure_deltas)
            + len(self.proposed_intent_records)
            + len(self.proposed_run_records)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "model_id": self.model_id,
            "status": self.status,
            "proposed_signals": [dict(e) for e in self.proposed_signals],
            "proposed_valuation_records": [
                dict(e) for e in self.proposed_valuation_records
            ],
            "proposed_constraint_pressure_deltas": [
                dict(e) for e in self.proposed_constraint_pressure_deltas
            ],
            "proposed_intent_records": [
                dict(e) for e in self.proposed_intent_records
            ],
            "proposed_run_records": [
                dict(e) for e in self.proposed_run_records
            ],
            "output_summary": dict(self.output_summary),
            "warnings": list(self.warnings),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# MechanismRunRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MechanismRunRecord:
    """
    Append-only audit record of one mechanism invocation.

    Captures the contractually relevant facts: who ran, what
    spec, what inputs (by id, not value), what proposals came
    out (by count + summary), what status, and where the actual
    proposed records ended up *after* the caller committed them.

    The record is **data**. v1.9.3 does not introduce a new
    ledger record type for it; v1.9.4 may either fold it into the
    existing ``ROUTINE_RUN_RECORDED`` shape or introduce
    ``MECHANISM_RUN_RECORDED`` as an additive type.

    Field semantics
    ---------------
    - ``run_id`` is the stable id of the run. Default formula:
      ``"mechanism_run:" + request_id``.
    - ``request_id`` mirrors the bundle.
    - ``model_id`` / ``model_family`` / ``version`` echo the
      spec.
    - ``actor_id`` echoes the input bundle.
    - ``as_of_date`` echoes the input bundle.
    - ``input_summary_hash`` and ``output_summary_hash`` are
      free-form opaque digest strings if the caller computed
      them; v1.9.3 does not require any specific hash function.
    - ``input_refs`` is the resolved (deduped, ordered) tuple of
      input record ids the mechanism actually consumed.
    - ``committed_output_refs`` is the tuple of record ids the
      caller wrote to its books after consuming
      :class:`MechanismOutputBundle`. May be a subset of the
      proposals when the caller dropped some.
    - ``status`` mirrors the output bundle.
    - ``parent_record_ids`` lets the run point back to upstream
      records (the four-property action contract's lineage
      hook).
    - ``metadata`` is free-form.
    """

    run_id: str
    request_id: str
    model_id: str
    model_family: str
    version: str
    actor_id: str
    as_of_date: str
    status: str = "completed"
    input_refs: tuple[str, ...] = field(default_factory=tuple)
    committed_output_refs: tuple[str, ...] = field(default_factory=tuple)
    parent_record_ids: tuple[str, ...] = field(default_factory=tuple)
    input_summary_hash: str | None = None
    output_summary_hash: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "request_id",
            "model_id",
            "model_family",
            "version",
            "actor_id",
            "as_of_date",
            "status",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(
                    f"{name} is required and must be a non-empty string"
                )

        for tuple_field_name in (
            "input_refs",
            "committed_output_refs",
            "parent_record_ids",
        ):
            value = tuple(getattr(self, tuple_field_name))
            for entry in value:
                if not isinstance(entry, str) or not entry:
                    raise ValueError(
                        f"{tuple_field_name} entries must be non-empty strings"
                    )
            object.__setattr__(self, tuple_field_name, value)

        for hash_field_name in ("input_summary_hash", "output_summary_hash"):
            value = getattr(self, hash_field_name)
            if value is not None and not (isinstance(value, str) and value):
                raise ValueError(
                    f"{hash_field_name} must be a non-empty string or None"
                )

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "request_id": self.request_id,
            "model_id": self.model_id,
            "model_family": self.model_family,
            "version": self.version,
            "actor_id": self.actor_id,
            "as_of_date": self.as_of_date,
            "status": self.status,
            "input_refs": list(self.input_refs),
            "committed_output_refs": list(self.committed_output_refs),
            "parent_record_ids": list(self.parent_record_ids),
            "input_summary_hash": self.input_summary_hash,
            "output_summary_hash": self.output_summary_hash,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# MechanismAdapter Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class MechanismAdapter(Protocol):
    """
    The Protocol that v1.9.4+ concrete mechanisms implement.

    An adapter is an object exposing a :class:`MechanismSpec`
    and an ``apply`` method. The adapter is responsible for
    interpreting an :class:`MechanismInputBundle` against the
    spec and returning a :class:`MechanismOutputBundle` of
    proposals. The adapter must **not** mutate any kernel book;
    every persistence step lives in the caller.

    The Protocol is ``runtime_checkable`` so tests can assert
    ``isinstance(adapter, MechanismAdapter)`` cheaply. The check
    is structural — any class with a ``spec`` attribute and an
    ``apply`` method satisfies it.
    """

    spec: MechanismSpec

    def apply(
        self, bundle: MechanismInputBundle
    ) -> MechanismOutputBundle: ...
