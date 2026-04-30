# v1 Behavior Boundary

This document defines the **policy for how behavior is introduced in v1**.
v0 contained no behavior. v1 introduces it gradually, one module at a time,
with explicit rules each module must satisfy before its behavior is
considered legitimate.

For the v1 design statement, see
[`v1_reference_system_design.md`](v1_reference_system_design.md). For the
invariants every behavior must preserve, see
[`v1_design_principles.md`](v1_design_principles.md). For the module
sequence, see [`v1_module_plan.md`](v1_module_plan.md). This document is
the meta-rule for *how* behavior enters the system.

## Why a behavior boundary is needed

Once anything in the simulation acts, three new failure modes become
possible that v0 could not produce:

1. **Hidden side effects.** A function can do more than its name says,
   and the audit trail won't catch it because the side effect routes
   around the ledger.
2. **Implicit coupling.** A behavior in one space can read state out of
   another space's internals, creating a dependency that doesn't pass
   through any channel listed in §15 of `world_model.md`.
3. **Untestable feedback.** A behavior reacts to a signal that another
   behavior just emitted, producing a chain that can only be debugged
   by re-running and watching.

The v0 invariants (no cross-space mutation, ledger of every change,
read-only projections) are designed to prevent all three. But v0
enforces them by *not having* behaviors. v1 has behaviors. So v1 needs
a stricter discipline at the moment behaviors are introduced — not
weaker.

## The four-property contract for every v1 behavior

Every v1 behavior must satisfy all four:

### 1. Explicit inputs

The behavior reads through documented APIs. It does not reach into
private fields. Acceptable input sources:

- the canonical books (`OwnershipBook`, `ContractBook`, `PriceBook`,
  `ConstraintBook`, `SignalBook`)
- read-only projections (`BalanceSheetProjector`, `ConstraintEvaluator`,
  `LendingExposure`, `PortfolioExposure`, future v1.1 valuations,
  future v1.5 relationship views)
- events received via `observe()`
- the behavior's own `Space`-local state

Forbidden as input:

- another `Space`'s `_firms` / `_banks` / `_investors` / `_markets` /
  `_listings` / `_property_*` / `_authorities` / `_instruments` /
  `_factors` / `_sources` / `_channels` (any underscore-prefixed
  attribute on another space)
- the contents of another space's `bind()`-captured refs (those refs
  exist for the owning space, not for cross-space sneaking)
- ledger records the behavior wrote within the same tick (no
  self-reading; ledger is for downstream and audit, not for
  intra-tick communication)

### 2. Explicit outputs

The behavior produces effects through documented channels:

- mutations of the canonical books (e.g., `OwnershipBook.transfer`,
  `ContractBook.update_status`, `PriceBook.set_price`,
  `ConstraintBook.add_constraint`, `SignalBook.add_signal`)
- additions to v1's new stores (the v1.1 valuation book, the v1.5
  relationship book) through their own documented APIs
- `WorldEvent` publications via `EventBus.publish`
- ledger records via the kernel's standard logging path
- updates to its own space's local state

Forbidden as output:

- direct attribute writes on any other space
- direct attribute writes on another behavior's intermediate state
- silent fix-ups that "shouldn't really need a record" — if it's a
  state change, it produces a ledger entry (see contract item 3)

### 3. Ledger record for every meaningful change

A meaningful change is anything a future replay needs to reconstruct.
v0 already requires this for kernel mutations (the book-level
`*_added` / `*_updated` records). v1 extends it to behavioral
decisions and comparisons:

- a decision (e.g., "bank chose to extend the loan") emits a record
  with the decision input refs in `parent_record_ids`
- a comparison (e.g., "method A says X, method B says Y, diff Δ")
  emits a record with both source records as parents
- a no-op decision is recorded only if the no-op is meaningful
  (e.g., "bank reviewed the loan and chose to do nothing" is a
  meaningful audit trace; "the daily task fired and there was no
  data to process" is not)

The granularity rule: **if a future audit would ask "why did this
happen?", the answer must be reachable through `parent_record_ids`
without re-running the simulation.** Behaviors must populate the
chain.

### 4. No direct cross-space mutation

This is invariant 1 from
[`v1_design_principles.md`](v1_design_principles.md), restated as
behavior policy: a v1 behavior can change another space's
*observable* state only by going through one of the five permitted
channels (ownership, contract, price, signal, event). Anything else
is wrong shape.

The simplest test: if a v1 behavior's effect on another space cannot
be reproduced by re-running it from the kernel-level books and
events alone, the behavior is breaking this rule.

## v1.1 Valuation is non-behavioral

v1.1 (Valuation Layer) is a special case. It introduces new state
(the fundamentals book, the valuation book) and new ledger record
types, but its operations are **not behavior** in the sense the four-
property contract addresses.

Specifically:

- v1.1 stores valuation claims (one method's view of an asset's worth
  at an `as_of_date`).
- v1.1 compares valuation claims (method A vs method B) and records
  the comparison.
- v1.1 does **not** decide anything based on a valuation. A valuation
  is data, not a trigger.
- v1.1 does **not** propagate to any other space. A v1.3 bank that
  wants to use a valuation reads the valuation; the valuation layer
  itself does not push.
- v1.1 does **not** drive prices. Valuations live in their own store,
  separate from `PriceBook` (invariant 4 in
  `v1_design_principles.md`).

This means v1.1 is the only v1 module where the four-property contract
above does not fully apply — because there is no decision to apply it
to. v1.1 still must satisfy invariants 1, 4, 5, 6, 7 from
`v1_design_principles.md` (no cross-space mutation, prices stay in
PriceBook, valuation is not price or truth, ledger records every
state change and comparison, reads are non-mutating). Those are
*data discipline*, not behavior discipline.

The reason for this carve-out is to keep v1.1 from being delayed by
behavior discussions that don't apply. Picking which valuation method
drives a bank's credit decision is a later-v1 question. v1.1 only
ships the valuations that later modules will choose between.

## v1.3 ships the action contract; behavior comes later

v1.3 (Institutional Decomposition and Action Contract) introduces
`InstitutionalActionRecord` — the first record type whose existence
explicitly anticipates *behavior*. The four-property contract above
is implemented as the schema of that record:

- `input_refs` is the explicit-inputs property.
- `output_refs` is the explicit-outputs property.
- The `institution_action_recorded` ledger event with preserved
  `parent_record_ids` is the ledger-record property.
- `InstitutionBook.add_action_record` writing only to its own
  store and the ledger is the no-cross-space-mutation property.

But v1.3 itself does **not** generate any actions. It ships the
*recording schema* so future v1 behavior modules — a reference
policy reaction function in PolicySpace, a reference supervisory
review in a regulator, a reference exchange announcement in
ExchangeSpace — all use the same contract when they create action
records. v1.3 is to v1 behavior what v0 was to v1 as a whole: the
shape comes first; the behavior arrives in later milestones.

This means that adding v1.3 does not add any of the items in the
out-of-scope table below. Those items remain owned by their
respective future modules. v1.3 only widens the data layer to make
recording them auditable when they finally arrive.

## Out-of-scope behaviors with their owning module

To make the boundary concrete, here is the explicit assignment of
each not-yet-implemented behavior to the module that will introduce
it. Anyone reaching for one of these in an earlier module is acting
out of scope.

| Behavior                                 | Earliest module       |
| ---------------------------------------- | --------------------- |
| Trading / order generation               | v1.3 (Investor + Exchange) |
| Order matching / clearing                | v1.3 (Exchange)       |
| Price formation                          | v1.3 (Exchange)       |
| Bank credit decision                     | v1.3 (Banking)        |
| Bank tightening / loosening              | v1.3 (Banking)        |
| Default detection                        | v1.3 (Banking) — *reference rule only*; full default modeling later |
| Corporate action (dividend, buyback, issuance) | v1.3 (Corporate) |
| Corporate revenue / earnings update      | v1.3 (Corporate)      |
| Capex / borrow / delever decision        | v1.3 (Corporate)      |
| Cap rate / rent / vacancy update         | v1.3 (Real Estate)    |
| Information emission scheduling          | v1.3 (Information)    |
| Visibility decay for rumors              | v1.3 (Information)    |
| Policy reaction function                 | v1.3 (Policy)         |
| External stochastic process (RW / AR / regime) | v1.4              |
| Cross-agent reputation / trust dynamics  | v1.5                  |
| Closed-loop signal → decision → action   | v1.6                  |

If a v1 implementation pull request introduces one of the above
*before* its assigned module, that pull request is out of scope.

## Behaviors that remain out of scope through all of v1

The following are deliberately not in v1 at all. They wait for v2 or
v3:

- Japan-specific institutional behavior (BoJ reaction calibrated to
  real Japan macro, MUFG-specific credit policy, GPIF-specific
  allocation, etc.) — v2.
- Japanese-jurisdiction calibration of any reference parameter — v2.
- Proprietary, expert, or paid-data calibration — v3.
- Real-time data ingestion of any kind — v2 / v3.
- Multi-jurisdiction simultaneous economies — v1 has one
  jurisdiction-neutral economy; multi-jurisdiction is post-v3.
- High-frequency / nanosecond trading — v1's intraday phases are
  conceptual blocks of a day, not microseconds.
- Full natural-language news generation — v1 emits structured
  signals; prose generation is a later concern.
- LLM-driven agent reasoning — v1 reference behavior is closed-form
  rules.

## How behavior introduction is reviewed

When a v1 module's pull request lands, reviewers should answer five
questions explicitly. The answers should be in the milestone document
(e.g., `world_model.md` §36+ for v1.1) or in the PR description:

1. **What new behavior does this introduce?** State the inputs,
   outputs, decision points, and the channels its effects flow
   through.
2. **Which v0 / v1 invariants does it touch?** Reference the seven
   invariants in `v1_design_principles.md` by number.
3. **Where does the behavior's audit trail live?** Identify the
   ledger record types it produces and how `parent_record_ids` is
   populated.
4. **What test demonstrates it works?** A single end-to-end test in
   the milestone's test file is enough; the test must verify both
   that the behavior runs and that it does not violate invariants.
5. **What did this PR explicitly *not* do?** Restate the boundary
   for the milestone — which behaviors from the table above remain
   for later modules.

A PR that cannot answer all five concisely is not ready to merge.

## Why the boundary is loud

v0 worked because the boundary was unmistakable: no behavior, full
stop. v1's boundary is a sliding one — behavior enters one module at
a time. That sliding boundary is exactly where errors creep in.
Loud documentation, explicit per-module scope statements, and the
five-question review checklist together replace the "no behavior"
brick wall with a series of well-marked gates.

The cost of this loudness is some repetition between this document,
`v1_design_principles.md`, and `v1_module_plan.md`. That repetition
is intentional. Each document approaches the same boundary from a
different direction (policy / invariants / sequence) so that any one
of them, read alone, gives a reviewer enough context to spot a
violation.
