# v1.4 ExternalWorld Process Design

This document is the design rationale for the v1.4 milestone. v1.4
makes external factors first-class objects in the kernel: it lets the
world declare *how an external factor evolves* (process), record
*what was observed* (observation), and replay *a known trajectory*
(scenario path), all without causing any domestic economic behavior.

v1.4 is structural and explicitly minimal. It ships only two
generation helpers — constant-process replay and scenario-path
replay. It does **not** generate shocks, does not implement random
walks or regime switching, does not load real Japan public or
proprietary data, and does not propagate observations to PriceBook,
SignalBook, or any domain space.

For the v1 design statement, see
[`v1_reference_system_design.md`](v1_reference_system_design.md).
For the inherited invariants, see
[`v1_design_principles.md`](v1_design_principles.md). For the v1
behavior contract that future stochastic-process modules will
satisfy, see [`v1_behavior_boundary.md`](v1_behavior_boundary.md).

## Why external factors are first-class objects

`ExternalSpace` (v0.14, §34.3) already ships
`ExternalFactorState` — an identity-level classifier for which
exogenous factors the world tracks. v1.4 adds the next layer: a
process that *defines how the factor evolves*, observations that
*record what value the factor took*, and scenario paths that *replay
a deterministic trajectory*.

The reason for separating process from observation from scenario
path is that the three answer different questions:

- **Process** — "what kind of dynamic does this factor follow, and
  what parameters define it?" Examples: a constant 0.7% short rate,
  a random-walk-with-drift exchange rate, a regime-switching
  commodity price.
- **Observation** — "what value did the world actually see at this
  moment?" An observation is a recorded fact, not a forecast.
- **Scenario path** — "what trajectory do we want this factor to
  take in this run?" A scenario path is a deterministic schedule,
  used for tests and for reference scenarios where reproducibility
  matters more than realism.

A real factor often has all three. A USD/JPY rate has a stochastic
process spec, has actual observations recorded each business day,
and may have a scenario path overlaid for what-if analysis. v1.4
stores all three independently and lets later milestones (or test
fixtures) decide which one drives a given run.

## Process vs observation vs scenario path

| Concept        | Question                          | Lifetime           | Stored in                    |
| -------------- | --------------------------------- | ------------------ | ---------------------------- |
| Process        | "How does this factor evolve?"    | Long (definition)  | `ExternalProcessBook` (process map) |
| Observation    | "What did we see at time T?"      | Forever (append-only) | `ExternalProcessBook` (observation map) |
| Scenario path  | "What trajectory should we replay?" | Long (definition) | `ExternalProcessBook` (path map)    |

A process and a scenario path can co-exist for the same factor: the
process declares the long-term dynamic, the path overrides for a
specific test or sub-period. Observations record what actually
happened, regardless of which produced them.

## Why v1.4 does not implement shocks

v1.4 explicitly ships only two generation helpers:

- `create_constant_observation(process_id, as_of_date, ...)` — uses
  the process's `base_value` to produce an observation at the given
  date. The "process" is just a stored constant.
- `create_observation_from_path(path_id, as_of_date, ...)` — looks
  up the matching point on a scenario path and produces an
  observation from it. Pure replay; no math.

It does **not** ship:

- random-walk generation
- mean-reverting generation (Ornstein-Uhlenbeck or analog)
- regime-switching generation
- historical-data loading from any source
- shock primitives ("oil shock", "war", "FX crash")

The reasons match v1.1 / v1.3:

1. **Calibration cost.** A random walk needs a drift, a volatility,
   and a seed. Mean reversion needs a long-term level, a half-life,
   and noise. Regime switching needs transition probabilities. Each
   parameter is a calibration decision, and v1 stays jurisdiction-
   neutral. Picking parameters in v1.4 would either commit to
   neutral but unrealistic numbers (so v2 has to overwrite
   everything) or import real values (so v1 is no longer neutral).
2. **Reusability of the schema.** The process / observation /
   scenario path schema is the same regardless of the dynamic. v1.4
   ships the schema once. Later milestones add the dynamics on top
   without reshaping the storage layer.
3. **Audit trail clarity.** Observations are append-only and stamped
   with `source_id`, `process_id`, and `confidence`. A v2 random-walk
   generator can attribute observations cleanly to its process; a
   v3 proprietary-data importer can attribute observations to its
   data source. v1.4 makes the attribution slot exist; v2 / v3
   populate it differently.

The two minimal helpers — constant + scenario path — are enough to
test the schema and to write the first reference closed-loop
scenarios in v1.6 without writing any stochastic code in v1.

## Why domestic impact is deferred

An observation that the USD/JPY rate moved should *eventually*
matter for an investor's portfolio valuation, a bank's cross-
currency credit decision, a corporate's hedging position, an
exchange's foreign-listed-share clearing. v1.4 records the
observation but does **not** propagate it. None of those domestic
impacts run in v1.4.

The reason is the v1 behavior contract: a behavior that *consumes*
an observation must satisfy the four-property contract from
[`v1_behavior_boundary.md`](v1_behavior_boundary.md) — explicit
inputs, explicit outputs, ledger record, no direct cross-space
mutation. v1.4 ships the observation that the contract's inputs
will reference; the consuming behavior is its own milestone.

Concretely:

- A future investor allocation rule (later v1) may read
  `kernel.external_processes.latest_observation("factor:fx")` as part
  of its inputs and emit an `InstitutionalActionRecord` with
  `input_refs=("observation:...",)`.
- A future bank cross-currency credit rule may read the same
  observation and emit a credit decision with the observation in
  its `parent_record_ids`.
- A future market clearing in `ExchangeSpace` may treat external
  factor observations as inputs to its reference matching.

In all three cases the observation already exists in v1.4; the
behavior arrives later.

## How v2 / v3 plug in calibrated data

The v1.4 layer is designed for clean replacement at the data layer
without code changes:

- **v2 (Japan public calibration)** populates the same
  `ExternalProcessBook` with real factors:
  `factor:jp_overnight_rate`, `factor:usd_jpy_spot`,
  `factor:wti_brent_spread`, `factor:jgb_10y_yield`. Processes get
  parameters tuned to public Japan data: BoJ open-data short rates,
  BoJ FX rates, Ministry of Finance JGB auction results. v2 may
  ship its own process types beyond v1.4's two helpers (random
  walks, AR(1) processes calibrated to public time series), all
  built on the v1.4 schema.
- **v3 (proprietary / commercial calibration)** populates the same
  book with proprietary or paid-data factors: vendor-specific FX
  marks, commercial macro forecasts, expert-curated regime
  classifications. v3 process types may be more elaborate (jump
  diffusions, expert-rule overrides), but they go through the same
  `ExternalFactorProcess` slot.

The schema does not need to change between v1, v2, and v3. The
generation logic does.

## v1.4 record types

### `ExternalFactorProcess`

Immutable. Fields: `process_id`, `factor_id`, `factor_type`,
`process_type`, `unit`, `base_value`, `status`, `metadata`. The
`process_type` is a free-form string with suggested labels
documented in `world/external_processes.py`. `base_value` is used
only by the constant helper; other process types may leave it
`None` and store parameters in `metadata`.

### `ExternalFactorObservation`

Immutable. Fields: `observation_id`, `factor_id`, `as_of_date`,
`value`, `unit`, `source_id`, optional `phase_id`, optional
`process_id`, `confidence`, `related_ids`, `metadata`.

`process_id` is optional because not every observation comes from a
process. A manually entered "we saw X at T" observation is valid;
it carries `process_id=None` and uses `source_id` to identify the
recorder.

### `ExternalScenarioPoint`

Immutable. Fields: `factor_id`, `as_of_date`, `value`, `unit`,
optional `phase_id`, `metadata`. A point is the building block of
a scenario path.

### `ExternalScenarioPath`

Immutable. Fields: `path_id`, `factor_id`, `points` (tuple of
points), `source_id`, `metadata`. A path holds a single factor's
trajectory. All points must share the path's `factor_id`; the path
validates this on construction.

## ExternalProcessBook API

- Process CRUD: `add_process`, `get_process`, `list_processes_by_factor`,
  `list_processes_by_type`, `all_processes`.
- Observation CRUD: `add_observation`, `get_observation`,
  `list_observations_by_factor`, `latest_observation`,
  `all_observations`.
- Scenario path CRUD: `add_scenario_path`, `get_scenario_path`,
  `get_scenario_point(path_id, as_of_date, phase_id)`,
  `all_scenario_paths`.
- Helpers: `create_constant_observation`,
  `create_observation_from_path`.
- `snapshot()` returns a sorted, JSON-friendly view of all three
  buckets.

`get_*` methods raise `Unknown*Error` for unknown ids (matching the
v0.4 / v1.1 / v1.3 book convention).
`get_scenario_point` returns `None` for a missing point on a known
path; it raises `UnknownScenarioPathError` for an unknown path.

## Cross-reference rule

`factor_id` on processes / observations and `process_id` on
observations are **not** validated for resolution. v1.4 does not
require a factor to be registered in `ExternalSpace` before a
process can reference it; it does not require the referenced
process to exist before an observation can claim it. This matches
the v0 / v1 cross-reference rule: cross-references are recorded as
data, not enforced as invariants.

The motivation is the same as before: v2 / v3 calibration may
populate factors and processes in either order, and forcing a join
at construction time would block flexible loading patterns. Tests
that want stricter resolution can add their own.

## What v1.4 ships

In scope:

- `world/external_processes.py` with the four immutable records and
  `ExternalProcessBook`.
- Three new ledger record types: `external_process_added`,
  `external_observation_added`, `external_scenario_path_added`.
- Two minimal generation helpers: `create_constant_observation` and
  `create_observation_from_path`.
- Kernel wiring: `kernel.external_processes` with default
  `__post_init__` propagation of `clock` and `ledger`.
- Tests covering all four record dataclasses, the full CRUD
  surface, the two helpers, the latest-observation lookup, the
  scenario-point lookup with missing → None, the no-mutation
  guarantee against all six other source-of-truth books, ledger
  writes, and kernel wiring.

## What v1.4 does not ship

Out of scope:

- Stochastic process generation (random walk, mean reversion,
  regime switching, jump diffusion). Those are later milestones.
- Historical replay from real data files. Loading public Japan
  data is a v2 task.
- Domestic propagation of observations: no automatic price update,
  no signal emission, no domain-space reaction. Behavior modules
  that consume observations satisfy the v1 four-property contract
  in their own milestones.
- FX conversion. v1.1's `ValuationComparator` already declines to
  convert; v1.4 likewise does not.
- Shock primitives. There is no built-in "oil shock" or "war"
  helper, and no semantic interpretation of any factor type.
- Country-specific institutions, instruments, or data sources.

## v1.4 success criteria

v1.4 is complete when **all** of the following hold:

1. The four immutable dataclasses exist with all documented fields
   and reject empty required fields where applicable.
2. `ExternalProcessBook` provides the full CRUD surface
   (`add_process`, `get_process`, `list_processes_by_factor`,
   `list_processes_by_type`, `add_observation`, `get_observation`,
   `list_observations_by_factor`, `latest_observation`,
   `add_scenario_path`, `get_scenario_path`, `get_scenario_point`)
   plus `snapshot`.
3. Duplicate ids in each bucket are rejected with the appropriate
   `Duplicate*Error`. Unknown lookups raise `Unknown*Error`.
4. `latest_observation` returns the highest-`as_of_date` observation
   for a factor, or `None` if none exists.
5. `get_scenario_point` returns `None` for a missing point on an
   existing path, and raises `UnknownScenarioPathError` for an
   unknown path.
6. `create_constant_observation` produces an observation whose
   value matches the process's `base_value` and whose
   `observation_id` is deterministic in `(process_id, as_of_date,
   phase_id)`. It rejects non-constant processes and `None`
   `base_value`.
7. `create_observation_from_path` produces an observation from a
   matching scenario point, returns `None` for a missing point, and
   raises for an unknown path.
8. The three ledger record types are emitted on the corresponding
   `add_*` calls when a ledger is configured.
9. `kernel.external_processes` is exposed with default wiring
   (`clock` and `ledger` propagated in `__post_init__`).
10. Adding processes / observations / scenario paths does not
    mutate any other source-of-truth book (`OwnershipBook`,
    `ContractBook`, `PriceBook`, `ConstraintBook`, `SignalBook`,
    `ValuationBook`, `InstitutionBook`).
11. All previous milestones (v0 through v1.3) continue to pass.
