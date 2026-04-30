# v1 Module Plan

This document defines the planned **sequence of v1 modules**. Each entry
is a milestone-sized scope: small enough to land coherently, large enough
to push behavior forward.

The order below is the expected order of implementation. Each module
depends on its predecessors plus a defined subset of v0 modules. None of
them depend on Japan-specific calibration — that is v2's job.

For the higher-level statement of what v1 is, see
[`v1_reference_system_design.md`](v1_reference_system_design.md). For the
invariants every module must preserve, see
[`v1_design_principles.md`](v1_design_principles.md). For how each
module's behavior is bounded, see
[`v1_behavior_boundary.md`](v1_behavior_boundary.md).

## Sequence overview

| Module | Title                                  | Adds                                                  |
| ------ | -------------------------------------- | ----------------------------------------------------- |
| v1.1   | Valuation Layer                        | Fundamentals, valuation methods, valuation comparisons |
| v1.2   | Intraday Phase Scheduler               | Phases inside a calendar day                           |
| v1.3   | Institutional Decomposition            | Reference behavior in each domain space                |
| v1.4   | ExternalWorld Process                  | Stochastic processes for external factors              |
| v1.5   | Relationship Capital Layer             | Cross-agent reputation / counterparty history          |
| v1.6   | First Closed-loop Reference System     | End-to-end signal → decision → action → state cycle    |

## v1.1 Valuation Layer

### Purpose

Give the world a structured way to record what things are *worth*
beyond their last observed price. This is the gateway from "data we
saw" (PriceBook) to "claims about value" (multiple methods, multiple
viewpoints) without conflating the two.

### What it may add

- A `FundamentalsBook` (or similarly named store) keyed by agent or
  asset, holding domain-neutral fields such as `revenue_run_rate`,
  `operating_margin`, `book_value`, `cash_flow_estimate`,
  `cap_rate_assumption`. Field set is jurisdiction-neutral; v2 fills
  these from real Japan public sources.
- A `ValuationBook` storing `ValuationRecord`s with `method`,
  `as_of_date`, `value`, `source`, `confidence`. Append-only, like
  PriceBook. One asset can carry many simultaneous valuations from
  many methods.
- Reference valuation methods: simple DCF, P/E mark, P/B mark, NAV
  for funds, cap-rate-based property valuation. Each is a
  jurisdiction-neutral, fully-defined math function — no Japan
  parameters.
- `ValuationView` projections that compute valuations on demand from
  fundamentals + reference methods.
- A comparison helper that records "method A says X, method B says
  Y, they disagree by Δ" as a ledger record.
- An optional `valuation_basis` field on `BalanceSheetView` so
  consumers can choose whether `asset_value` reflects observed
  prices, model valuations, or a defined blend.

### What it must not add yet

- Any Japan-specific fundamentals input. Sample fundamentals in
  tests are synthetic.
- Any decision that uses valuation as a trigger (e.g., a bank
  tightening because LTV computed from valuation is high). That is
  v1.3.
- Any narrative interpretation of valuation disagreement (e.g.,
  "the market thinks X is mispriced"). v1.5 / v1.6 may consume the
  comparison record but v1.1 only records it.
- Time-varying valuation (valuations that update themselves on a
  schedule). Each valuation is a one-shot record at a given
  `as_of_date`. A v1.4 process can drive *fundamentals*
  stochastically; v1.1 itself is non-stochastic.
- Mutation of `PriceBook`. Valuations and prices are separate stores.

### Dependency on v0 modules

- `Registry` — for asset and agent identity.
- `Clock` — for `as_of_date`.
- `Ledger` — for `valuation_added` / `valuation_compared` records.
- `BalanceSheetProjector` — extended with optional `valuation_basis`
  parameter (additive change; default behavior unchanged).
- `OwnershipBook` — read for "what does this agent own that we
  should value?".
- `PriceBook` — read for "what is the latest market price, for
  comparison with model valuation?".

## v1.2 Intraday Phase Scheduler

### Purpose

Make ordering inside a calendar day explicit. v0's smallest time unit
is one day; v1.2 introduces phases (e.g., `pre_market`, `market`,
`post_market`, `settlement`) so v1.3 reference market clearing can
happen in a meaningful order relative to investor intent and
settlement.

### What it may add

- A populated `Phase` enum (currently `Phase.MAIN` only) with the
  reference set of phases. Names are jurisdiction-neutral.
- An extended `Scheduler` that dispatches due tasks through ordered
  phases on each tick.
- A `phase` parameter on `TaskSpec` that defaults to `MAIN` so all
  v0 tasks continue to work unchanged.
- An optional per-phase ledger marker (e.g., `phase_started` /
  `phase_ended`) so the audit trail records when intraday phases
  ran.
- Tests confirming that v0 spaces (which all use `Phase.MAIN`)
  still produce identical task sequences after v1.2 ships.

### What it must not add yet

- Any phase-specific behavior (no auction matching, no halt logic).
  v1.2 is scheduling infrastructure, not market microstructure.
- Phase calendars per market (e.g., TSE-specific phase boundaries).
  That is v2.
- Phases shorter than "named conceptual block of a day". v1.2 does
  not introduce wall-clock times or seconds.
- Cross-day phases (e.g., a settlement phase that spans two days).
  v1.2 keeps phases inside a single calendar day.

### Dependency on v0 modules

- `Scheduler` — extended (additive: `phase` already exists in
  TaskSpec).
- `Clock` — unchanged.
- `Ledger` — extended with `phase_started` / `phase_ended` types if
  needed.
- `BaseSpace.task_specs()` — unchanged behavior; v0 spaces continue
  to declare `MAIN` phase implicitly.

## v1.3 Institutional Decomposition

### Purpose

Give each domain space its first reference behavior. After v1.3,
spaces *do something* on their tasks — they do not merely classify.

### What it may add

Per-space, all reference (jurisdiction-neutral) and all expressed
through the five permitted cross-space channels:

- **CorporateSpace v1**: revenue / earnings update rule reading
  fundamentals + signals; corporate-action vocabulary (dividend,
  buyback, issuance) emitted as `WorldEvent`s; capex / delever /
  borrow heuristics gated by `BalanceSheetView` and
  `ConstraintEvaluation`. Decisions emit ledger records; mutations
  (dividend cash decrement, debt increase) flow through
  `OwnershipBook` / `ContractBook`.
- **BankSpace v1**: a reference credit decision rule reading
  `LendingExposure` and `ConstraintEvaluation`s, returning
  decisions (extend / tighten / call). Decisions update contracts
  via `ContractBook.update_status` or trigger new contracts via
  `ContractBook.add_contract`.
- **InvestorSpace v1**: a reference allocation rule reading
  `PortfolioExposure` and `BalanceSheetView`, emitting *intent*
  events on the `EventBus` for `ExchangeSpace` to consume.
- **ExchangeSpace v1**: a reference matching mechanism (continuous
  double auction or call auction; the v1 reference choice is one
  per asset class) consuming intent events and producing
  `price_updated` records and ownership transfers.
- **RealEstateSpace v1**: a reference cap-rate / rent / vacancy
  update rule emitting new property valuations through the v1.1
  valuation layer.
- **InformationSpace v1**: scheduled signal emission rules (earnings
  date triggers, rating-review triggers); a reference visibility-
  decay rule for rumor-class signals.
- **PolicySpace v1**: a reference reaction function (e.g., a
  generic policy rate rule reading aggregated macro signals,
  emitting rate-change announcements as both signals and
  `WorldEvent`s).
- **ExternalSpace v1**: stub interface for v1.4's process layer to
  connect to.

### What it must not add yet

- Any Japan-specific institution. No `bank:mufg`, no `firm:toyota`,
  no `authority:boj`. Tests use neutral identifiers.
- Any Japan-specific calibration parameters (rate corridors, tax
  rates, regulatory ratios). Reference parameters are chosen for
  obviousness, not realism.
- Closed-loop dynamics across all eight spaces simultaneously.
  v1.3 introduces per-space behavior; the closed loop is v1.6.
- Relationship-aware decisions (e.g., bank prefers its long-time
  borrower). That requires v1.5.
- Intraday-phase-aware decisions in spaces that do not need them.
  v1.3 spaces that do need ordering (Exchange, Investor) consume
  v1.2 phases; others stay daily.

### Dependency on v0 modules

- All eight `DomainSpace` subclasses — extended.
- All five canonical books — read and written through their
  documented APIs.
- `EventBus` — used for cross-space intent / announcement
  transport.
- `BalanceSheetProjector`, `ConstraintEvaluator` — read by spaces
  that gate decisions on financial state.

### Dependency on v1 modules

- v1.1 (Valuation) — RealEstateSpace's cap-rate updates produce
  valuations via v1.1's layer.
- v1.2 (Intraday phases) — Exchange and Investor behavior is
  ordered through phases.

## v1.4 ExternalWorld Process

### Purpose

Drive external factors forward in time according to declared
stochastic processes, without those processes living inside any
specific domain space.

### What it may add

- Per-`ExternalFactorState` process spec in metadata (e.g.,
  `{"process": "random_walk", "drift": ..., "vol": ...}` or
  `{"process": "ar1", "phi": ..., "sigma": ...}`).
- A v1 ExternalWorld runner that reads the specs and produces
  factor observations on the declared frequency, recorded via a
  new ledger event type (`factor_value_observed` or analog).
- A small library of jurisdiction-neutral reference processes:
  random walk, AR(1), regime switch, mean reversion. Each fully
  parameterized at the call site.
- Hooks for v1.3 PolicySpace and others to read factor observations
  via `ExternalSpace`.
- Reproducibility: each process call accepts a `seed` and the
  ledger records the seed used.

### What it must not add yet

- Japan-tuned parameters for any process (those are v2).
- Calibrated transition probabilities for regime switches based on
  real Japan data (also v2).
- Cross-factor dependencies (e.g., USD/JPY ↔ JGB yields) modeled
  as joint distributions. v1.4 keeps factors independent; joint
  modeling is a future v1 sub-milestone or v2.
- Historical replay (re-running a real Japan series). That is v2.
- Endogenous factor updates triggered by domestic-market events
  (e.g., domestic crash → external risk-off). The mechanism for
  cross-jurisdiction feedback can be set up but does not run in
  v1.4; it activates in v1.6.

### Dependency on v0 modules

- `ExternalSpace` — host for factor / source classification.
- `Ledger` — for observation records.
- `Clock` — for time advancement.
- `EventBus` — optional: factor observations may also emit signal-
  bearing `WorldEvent`s for spaces that subscribe.

### Dependency on v1 modules

- v1.1 valuation layer is independent; v1.4 may or may not feed
  into valuations depending on the v1.6 closed-loop design.

## v1.5 Relationship Capital Layer

### Purpose

Record the cross-agent dimension that affects credit, allocation,
and information weighting but does not belong inside any single
space — counterparty history, trust, repeat-business effects, the
"who has worked with whom and how it went" dimension.

### What it may add

- A new kernel-level book or layer storing directed relationships
  between agents (e.g., `RelationshipBook` keyed by
  `(from_agent_id, to_agent_id, relation_type)` with strength,
  history, last-update fields).
- Read-only `RelationshipView` projections for spaces to consume.
- Reference relationship update rules (e.g., trust decays over
  time; successful repayment reinforces; default zeroes).
- Rules for relationships to influence v1.3 behavior (e.g., a
  bank's reference credit decision is parameterized by its trust
  in the borrower).
- Ledger event types for relationship adds, updates, breaks.

### What it must not add yet

- Japan-specific relationship structures (keiretsu, main-bank
  relationships, institutional cross-shareholding). Those are v2.
- Reputation contagion across third parties (A's trust in B
  influencing C's trust in B). v1.5 keeps relationships pairwise.
- Information-asymmetry models that compute *how much* trust
  changes information value. v1.5 records trust; v1.6 closed-loop
  ties it to consumption.
- Network analytics (centrality, communities). Those are
  derivable; v1.5 stores edges, not metrics.

### Dependency on v0 modules

- `Registry` — for agent identity.
- `Ledger`, `Clock`, `EventBus` — standard.

### Dependency on v1 modules

- v1.3 institutional decomposition — relationships influence
  institutional reference behavior.

## v1.6 First Closed-loop Reference System

### Purpose

Tie the previous five modules together into a complete
signal → decision → action → state-change → new-signal cycle, run
end-to-end in a reference scenario.

### What it may add

- An end-to-end test that demonstrates: ExternalSpace publishes a
  reference macro shift; PolicySpace reacts via reference rule;
  BankSpace tightens credit; CorporateSpace responds with reference
  borrow / capex behavior; ExchangeSpace clears equity prices via
  reference matching; InvestorSpace rebalances; SignalBook /
  InformationSpace emit downstream signals; the cycle returns to
  ExternalSpace via v1.4 process feedback or stops at a planned
  horizon.
- Whatever wiring is missing between v1.1–v1.5 to make the loop
  run cleanly.
- Acceptance criteria: a one-year run produces a coherent ledger
  trace (no orphaned records, every effect has a parent), all
  invariants from `v1_design_principles.md` hold, and the test
  is reproducible with a documented seed.

### What it must not add yet

- Any Japan calibration. The v1.6 reference scenario uses synthetic
  parameters chosen for clarity, not realism.
- Multiple jurisdictions running simultaneously. v1.6 is one
  jurisdiction-neutral economy.
- High-frequency dynamics (the loop runs at v1.2's intraday phases
  at most; nothing faster).
- Stochastic divergence in the test — the reference scenario must
  be deterministic given a seed, so the test can assert exact
  ledger-record counts.

### Dependency on v0 modules

- All of them. v1.6 is the first time the entire kernel is
  exercised under behavior.

### Dependency on v1 modules

- v1.1 through v1.5. v1.6 cannot land before they do.

## What this plan does not commit to

- **Exact module boundaries.** A module above might split into two
  milestones during implementation (e.g., v1.3a / v1.3b) if the
  scope turns out larger than expected.
- **Calendar dates.** No timing is implied. Each module ships when
  its tests pass and its design boundary holds.
- **Backwards-incompatible changes** to v0. All v1 work is additive
  unless an explicit, documented decision allows otherwise (and no
  such decision is anticipated).

The order is committed; the granularity may vary.
