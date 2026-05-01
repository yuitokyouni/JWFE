# v1.8 Release Summary

This document is the canonical "what's in v1.8" reference. v1.8 is
the *endogenous routine, interaction, attention, variable, exposure,
chain harness, and trace report* milestone — built sub-release by
sub-release between v1.7 freeze and v1.9 Living Reference World.

For the v0 contract see
[`v0_release_summary.md`](v0_release_summary.md). For the v1.0 –
v1.7 reference financial system see
[`v1_release_summary.md`](v1_release_summary.md). For the running
constitutional design log see
[`world_model.md`](world_model.md) (§43 – §57 cover v1.8).

## v1.8 purpose

v1.8 was the milestone where the project moved from "structural
record types frozen at v1.7" to **"endogenous activity layer that
makes ledger records appear without an external observation
arriving."** v1.7 already provided the substrate (books, projection
hooks, the ledger as a causal trace, the four-property action
contract). v1.8 added the missing piece: a way for the world to
*do things on its own*, deterministically and without invoking
shocks or scenarios.

The conceptual result of v1.8:

> **External shocks are not the engine of the world.** Endogenous
> routines, interaction topology, attention, variables, exposures,
> and review traces now form a minimal non-shock chain.

The technical result of v1.8:

> A **deterministic, auditable endogenous chain** can be run with
> a single helper call (`run_reference_endogenous_chain`) and
> rendered as a human-readable report
> (`render_endogenous_chain_markdown`).

## Shipped sub-releases

Every v1.8 sub-release was additive: no v1.0 – v1.7 record was
modified destructively, and every sub-release shipped with its own
test additions and a docs section in `world_model.md`.

| Sub-release | Scope | Where to read |
| ----------- | ----- | ------------- |
| **v1.8.0** Experiment Harness | `world/experiment.py` — config-driven driver around the v1.7 reference demo, JSON manifest, SHA-256 ledger digest replay gate. No new modeling behavior. | `docs/v1_experiment_harness_design.md` |
| **v1.8.1** Endogenous Reference Dynamics — Design | The seven candidate routine types and the **anti-scenario discipline** (variable absence is partial / degraded, not silent failure). Design only. | `docs/v1_endogenous_reference_dynamics_design.md` |
| **v1.8.2** Interaction Topology + Attention — Design | Spaces as nodes in a directed multigraph; channel-level interactions; **heterogeneous attention** (each actor has a different `AttentionProfile`). Design only. | `docs/v1_interaction_topology_design.md` |
| **v1.8.3** `InteractionBook` + Tensor View | Sparse `InteractionBook` storing `InteractionSpec` records; matrix / tensor projection views over the inter-space channel graph. Storage + lookup; no execution. | `world_model.md` §45 |
| **v1.8.4** `RoutineBook` + `RoutineRunRecord` | Storage + audit only: routine specs and run records, plus the `routine_can_use_interaction(...)` predicate against `InteractionBook`. No execution. | `world_model.md` §46 |
| **v1.8.5** `AttentionProfile` + `ObservationMenu` + `SelectedObservationSet` | Storage layer for heterogeneous attention; `AttentionBook` plus the `profile_matches_menu` structural-overlap predicate. No menu auto-construction. | `world_model.md` §47 |
| **v1.8.6** Routine Engine plumbing | Caller-initiated `RoutineEngine.execute_request(...)` — interaction compatibility check, selected-ref collection, `RoutineRunRecord` write through the existing ledger path. No scheduler integration; no automatic firing. | `world_model.md` §48 |
| **v1.8.7** Corporate Quarterly Reporting Routine | First concrete routine on the Corporate → Corporate self-loop. Writes one synthetic `corporate_quarterly_report` `InformationSignal` per call. Synthetic only; no economic computation. | `world_model.md` §49 |
| **v1.8.8** Reference Variable Layer — Design (+ hardening) | Names the universe of observable world-context variables and adds the source / scope / **exposure** hooks plus the **four-gate rule** (visibility → availability → selection → consumption). Design only. | `docs/v1_reference_variable_layer_design.md` |
| **v1.8.9** `WorldVariableBook` | Code: `ReferenceVariableSpec` + `VariableObservation`, append-only revision history with `vintage_id` / `revision_of`, look-ahead-bias-free `list_observations_visible_as_of(...)` and `latest_observation(..., as_of_date=...)`. | `world_model.md` §51 |
| **v1.8.10** Exposure / Dependency Layer | Code: `ExposureBook` storing per-actor `ExposureRecord` entries (`subject_id × variable_id × direction × magnitude × metric × validity window`). Distinct from `AttentionProfile.watched_*` — exposure is *what affects* the actor, attention is *what they watch*. Magnitude is a synthetic dependency strength, not a calibrated sensitivity. | `world_model.md` §52 |
| **v1.8.11** `ObservationMenu` Builder | Code: `ObservationMenuBuilder` joins `AttentionBook` + `SignalBook` + `WorldVariableBook` + `ExposureBook` and writes one `ObservationMenu` per `build_menu` call through the existing `OBSERVATION_MENU_CREATED` ledger path. Implements gates 1+2 (visibility + availability) of the four-gate rule. | `world_model.md` §53 |
| **v1.8.12** Attention Variable Hooks + Investor / Bank Attention Demo | Code: `AttentionProfile` extended additively with `watched_variable_ids` / `watched_variable_groups` / `watched_exposure_types` / `watched_exposure_metrics`; `world/reference_attention.py` ships `run_investor_bank_attention_demo`, the first place where heterogeneous attention against a shared variable + exposure layer produces structurally different `SelectedObservationSet` records for two actors looking at the same world. **Selection is recorded as data; no review routine, no economic mutation.** | `world_model.md` §54 |
| **v1.8.13** Investor / Bank Review Routines | Code: two narrow consumer routines (`investor_review`, `bank_review`) on Investors → Investors and Banking → Banking self-loops that read `SelectedObservationSet` records through `RoutineEngine` and emit one synthetic review-note `InformationSignal` each. **Audit artifacts only — no buy / sell / lend / cover / valuation / price behavior.** | `world_model.md` §55 |
| **v1.8.14** Endogenous Chain Harness | Code: `world/reference_chain.py::run_reference_endogenous_chain` orchestrates the v1.8.7 / v1.8.12 / v1.8.13 helpers in order and returns a deterministic `EndogenousChainResult`. **Orchestration only** — no new economic behavior, no new ledger record types, no scheduler auto-firing, no world-construction logic. The summary is convenience; the same chain is fully reconstructable from `kernel.ledger.records[before:after]`. | `world_model.md` §56 |
| **v1.8.15** Ledger Trace Report | Code: `world/ledger_trace_report.py` turns the chain's ledger slice into a deterministic immutable `LedgerTraceReport`, plus `to_dict` and Markdown projections. Read-only explainability — no new ledger writes, no new RecordTypes, no kernel mutation. CLI now accepts `--markdown`. | `world_model.md` §57 |
| **v1.8.16** Freeze / Readiness | Docs and release-readiness only. No new code behavior. Consolidates v1.8 as a coherent milestone, updates the README, ships the v1.9 plan, and defines the v1.9.last public-prototype target. | `world_model.md` §58 |

## What v1.8 explicitly does NOT contain

The v1.8 line stays inside the same hard rails the rest of v1
respects:

- **No price formation, trading, or order matching.**
- **No bank credit / lending decisions, default detection, or
  covenant trips.**
- **No investor strategy, allocation, or rebalancing.**
- **No valuation refresh behavior** — the v1.1 comparator stays
  read-only; no impact estimation, sensitivity calculation, DSCR /
  LTV update, or covenant pressure scoring.
- **No corporate actions, earnings dynamics, or cash-flow
  projection.**
- **No policy reaction functions, rate-setting rules, or scenario
  engines.**
- **No Japan calibration.** All ids are synthetic and pass the
  word-boundary forbidden-token check (`world/experiment.py::_FORBIDDEN_TOKENS`).
- **No real data ingestion.** No public-data licenses are wired,
  and v1.8 does not read external sources at runtime.
- **No autonomous execution.** Every chain step is caller-initiated;
  `kernel.tick()` and `kernel.run(days=N)` never fire any v1.8
  routine.

These belong to v1+ behavioral milestones, v2 (Japan public), and v3
(Japan proprietary). v1.8 is **infrastructure for endogenous
activity**, not the activity itself.

## Test surface at v1.8 freeze

`pytest -q` from `japan-financial-world/` reports `1341 passed`:

- 444 v0 tests (frozen at v0.16)
- 188 v1.0 – v1.7 frozen-reference tests
- 709 post-v1.7 tests covering the reference demo + replay +
  manifest + catalog-shape regression + experiment harness, the
  v1.8.3 / v1.8.4 / v1.8.5 / v1.8.6 / v1.8.7 storage + engine +
  first-routine surface, the v1.8.9 / v1.8.10 variable / exposure
  storage layers, the v1.8.11 menu builder, the v1.8.12 attention
  demo, the v1.8.13 review routines, the v1.8.14 chain harness, and
  the v1.8.15 ledger trace report.

For the test breakdown by component see
[`test_inventory.md`](test_inventory.md).

## Where v1.8 sits relative to v1.9

| Direction        | Owns                                                  |
| ---------------- | ----------------------------------------------------- |
| v1.8 (this freeze) | Infrastructure for endogenous activity: interaction topology, routines, attention, variables, exposures, chain harness, trace report. |
| v1.9             | A small synthetic multi-period **Living Reference World Demo** that sweeps the v1.8.14 chain over a few quarters / firms / actors so recurring reporting → attention → review cycles produce ledger activity without external shocks. Plan in [`v1_9_living_reference_world_plan.md`](v1_9_living_reference_world_plan.md). |
| v1.9.last        | First lightweight public prototype: deterministic CLI demo, Markdown report, README explaining scope in 60 seconds, CI green, gitleaks clean. Plan in [`public_prototype_plan.md`](public_prototype_plan.md). |
| v2               | Japan public-data calibration design gate. Not started. |
| v3               | Japan proprietary / commercial calibration. Private.   |

If a feature request would change a v1.8 record shape, it is a
v1+ behavioral milestone; if it would require Japan public data, it
is v2; if it would require paid data or expert overrides, it is v3.
v1.9 stays inside the same anti-shock / anti-Japan-calibration /
anti-economic-behavior rails as v1.8.
