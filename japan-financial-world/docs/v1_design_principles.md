# v1 Design Principles

This document lists the **invariants every v1 module must preserve**. These
rules are inherited from the v0 world kernel (see
[`v0_release_summary.md`](v0_release_summary.md)) and tightened where v1's
introduction of behavior creates new ways to violate them.

A v1 module that breaks any of these without an explicit, documented
decision is breaking the v1 contract. Reviewers should reject such a module
on architectural grounds, not only on test grounds.

## The seven inherited invariants

### 1. Spaces do not directly mutate each other

A v1 space's `step()` may compute, decide, and emit. It must not reach into
another space's internal state map. Cross-space effects must travel through
one of the explicit channels:

- ownership records (mutated through `OwnershipBook`)
- contracts (mutated through `ContractBook`)
- prices (appended through `PriceBook`)
- signals (added through `SignalBook`)
- WorldEvents (published through `EventBus`)

A bank deciding to extend a loan in v1.3 does not write into
`CorporateSpace`'s firm map. It calls `kernel.contracts.add_contract(...)`
or `update_status(...)`. The corporate firm reads its own balance sheet
view to learn that its liabilities changed. This is the v0 §14 rule,
restated for the world where decisions exist.

A consequence: every v1 reference behavior must articulate which channel
its outputs flow through. If a behavior cannot be expressed through one of
the five channels above, it is the wrong shape — it is trying to be two
spaces at once.

### 2. EventBus transports; it does not interpret

`EventBus` carries `WorldEvent` records from publishers to addressed
targets. It does not:

- inspect payload contents to decide who should receive a message
- throttle, batch, prioritize, or de-duplicate semantically
- attach meaning to `event_type` strings (those are domain-neutral tags)
- couple delivery to signal visibility (transport and visibility are
  orthogonal — see v0 §26.5)

v1 reference behavior must preserve the bus's content-blindness. If a v1
space wants to filter incoming events, the filter belongs in that space's
`observe()`, not in the bus. If a v1 space wants to deliver to a subset
based on payload, it computes the target list and addresses the event;
the bus delivers what it is told.

The next-tick delivery rule (publication on day D, visible from D+1) also
holds in v1. Any v1 behavior that needs same-day reaction is a sign that
either the time scale is wrong (use intraday phases from v1.2) or the
data structure is wrong (use a projection read, not a transported event).

### 3. SignalBook stores signals; InformationSpace classifies

`SignalBook` is the canonical store of `InformationSignal` records. It owns
content, visibility, effective dates, and the `mark_observed` audit step.
`InformationSpace` classifies *who produces* signals (sources) and
*through what medium* they are distributed (channels). The two are kept
distinct precisely so v1 narrative dynamics can be added in
`InformationSpace` without the kernel's signal store growing opinions.

In v1:

- New behaviors may publish new signals via `SignalBook.add_signal`. They
  must record the signal content honestly (no after-the-fact rewriting).
- New behaviors may classify new sources / channels via
  `InformationSpace`. The classification is not the signal.
- A v1 space that interprets a signal does so locally (in its own
  `observe()` / `step()`). It does not modify the signal.
- Visibility is a fact of the signal, set at creation time. v1 may
  introduce reference rules for *how visibility is decided when a signal
  is created*, but never for retroactively changing visibility.

### 4. PriceBook stores observed prices

`PriceBook` is append-only and stores prices that have been *observed* —
prices someone reported, recorded, or marked. It is not the same thing
as worth.

In v1:

- A reference market clearing in `ExchangeSpace` v1 produces an observed
  price; that price is appended via `PriceBook.set_price`.
- A reference appraisal in `RealEstateSpace` v1 produces an observed
  price (with `source="appraisal"`); that too is appended.
- A reference model valuation in v1.1 — see invariant 5 — does **not**
  go into `PriceBook`. It goes into the new fundamentals / valuation
  layer.
- Old prices are never overwritten or deleted. New observations append
  with their own `simulation_date` and `source`.

### 5. Valuation must not be treated as price or truth

This is the principle that motivates v1.1 entirely. A reference valuation
(DCF estimate, P/E mark, NAV calc, cap-rate-based building value) is
**not** a price. It is a claim about value made by some method, often
disagreed with by other methods.

v1 must keep these distinct:

- `PriceBook` records observed prices with a `source` (e.g.,
  `"exchange"`, `"appraisal"`, `"system"`).
- The new valuation layer (v1.1) records valuation claims with a
  `method` (e.g., `"dcf"`, `"book_value"`, `"comparable_sales"`).
- A `BalanceSheetView` may carry a `valuation_basis` field so that
  callers know whether `asset_value` came from observed prices,
  reference model valuations, or a blend. v1.1 chooses the default
  basis explicitly.

A valuation is also not "truth". Two methods can disagree, and the
disagreement itself is information. v1.1's design must allow multiple
valuations to coexist and be compared without picking a winner inside
the layer. Picking which method drives a downstream decision is the job
of the consuming behavior (e.g., a v1.3 bank's credit decision picks
which valuation it underwrites against), not the valuation layer's.

### 6. Ledger records meaningful state changes and comparisons

The `Ledger` is the audit trail. In v0 it recorded mutations: object
registrations, position adds, contract creations, status changes, signal
adds, etc. v1 must extend this honestly:

- Every behavior that produces a state change emits a ledger record. If
  a v1 bank extends a loan, the loan creation appears in the ledger.
  The decision that led to the extension also appears, with
  `parent_record_ids` linking to the inputs the decision read.
- Every meaningful comparison emits a ledger record. If a v1 valuation
  layer compares method A and method B and reports a disagreement, the
  comparison itself is a ledger entry, with both source records as
  parents.
- Tick-level dispatch records (`task_executed`) remain neutral
  bookkeeping; v1 does not need to log every step inside a task body
  unless the step is itself a state change.

The `parent_record_ids` field is the load-bearing piece. It is what
turns a flat ledger into a causal graph. v1 behavior must populate it
whenever its output depends on prior records — particularly for
decision records, comparison records, and propagated effects.

### 7. Read-only projections must not mutate source books

Projections like `BalanceSheetProjector`, `ConstraintEvaluator`, and
the per-space `LendingExposure` / `PortfolioExposure` views are pure
reads. They may emit ledger entries (a constraint evaluation produces
a `constraint_evaluated` record), but they must not mutate
`OwnershipBook`, `ContractBook`, `PriceBook`, `ConstraintBook`, or
`SignalBook`.

In v1 this rule extends to the new valuation layer. A `ValuationView`
or `FundamentalsProjection` may compute, but must not write into the
book it derives from. The new valuation store (v1.1) is itself a
write-target for explicit `set_valuation(...)` calls; reads are
non-mutating.

The cross-space integration test
(`test_world_kernel_full_structure.py` in v0.15) checks the no-mutation
property by snapshotting books before and after read operations. v1
must extend this test or add an analogous one to cover any new
read-only projection.

## How the seven invariants fit together

The seven invariants are not independent — they share a single
underlying claim: **every meaningful effect in the simulation must be
recorded explicitly through a defined channel, and never as an
implicit side-effect of a function call.** That claim is what makes
the simulation auditable and replayable.

| Invariant                               | What it forbids                                  |
| --------------------------------------- | ------------------------------------------------ |
| 1. No direct cross-space mutation       | Hidden coupling between domain spaces            |
| 2. EventBus does not interpret          | Hidden routing logic in the transport layer      |
| 3. SignalBook stores; Info classifies   | Signal content drift after creation              |
| 4. PriceBook stores observed prices     | Conflating observed prices with model marks      |
| 5. Valuation is not price or truth      | Implicit "the right answer" inside the model     |
| 6. Ledger records changes + comparisons | Unaudited reasoning chains                       |
| 7. Read-only projections do not mutate  | Side effects masquerading as queries             |

Together they ensure that v1's introduction of behavior does not
quietly weaken the v0 contract. A v1 reviewer can ask, for any new
module, "which invariant does this strengthen, and which does it risk
violating?" — and that question has crisp answers.

## How v1 enforces these invariants

The enforcement mechanisms are the same ones v0 uses:

- **Tests**. Every v1 milestone adds tests that snapshot every
  source-of-truth book before its read operations and verify they
  are unchanged afterwards.
- **Ledger checks**. Every v1 milestone's tests assert that the
  expected ledger record types appear after a behavior runs, and that
  `parent_record_ids` is populated for derived records.
- **Type-level constraints**. `BalanceSheetView`, `ConstraintEvaluation`,
  `LendingExposure`, `PortfolioExposure` are immutable dataclasses. v1
  projections follow the same pattern. Mutation-by-accident is hard
  when the targets are frozen.
- **Code review**. The seven invariants in this document are the
  checklist. A change that needs to relax one of them is the change
  that needs the loudest discussion.

## What this document does not cover

- **The list of v1 modules** is in
  [`v1_module_plan.md`](v1_module_plan.md).
- **The behavior introduction policy** (how new behavior enters the
  system) is in
  [`v1_behavior_boundary.md`](v1_behavior_boundary.md).
- **The position of v1 relative to v0 / v2 / v3** is in
  [`v1_reference_system_design.md`](v1_reference_system_design.md).

These four documents together are the v1.0-prep gate.
