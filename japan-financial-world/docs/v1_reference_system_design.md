# v1 Reference System Design

This document is the **design gate** between the frozen v0 world kernel and
the start of v1 implementation. It is written before any v1 code lands. Its
purpose is to fix the boundary between v1 and the layers above and below it,
so that future v1 work cannot accidentally drift into v0 (kernel) or v2/v3
(Japan calibration) territory.

This document does not describe v1's modules in detail — that is
[`v1_module_plan.md`](v1_module_plan.md). It does not describe the
invariants every v1 module must obey — that is
[`v1_design_principles.md`](v1_design_principles.md). It does not describe
how behavior is introduced — that is
[`v1_behavior_boundary.md`](v1_behavior_boundary.md). It describes **what
v1 is, what v1 is not, and why the line is drawn where it is.**

## Position in the version stack

| Version | Statement                                                              |
| ------- | ---------------------------------------------------------------------- |
| v0.xx   | A jurisdiction-neutral **world kernel** — structure, no behavior.      |
| v1.xx   | A jurisdiction-neutral **reference financial system** — structure plus reference behavior. |
| v2.xx   | Japan **public calibration** of v1 — same model, real public data.     |
| v3.xx   | Japan **proprietary / commercial calibration** — same model, paid / expert data. |

v1 sits between a behavior-free skeleton (v0) and a Japan-tuned simulator
(v2). Its job is to demonstrate that the v0 skeleton can carry behavior —
in any plausible jurisdiction — without breaking the structural invariants
v0 worked fifteen milestones to establish.

The four-layer stack is the single most load-bearing claim in the
project. Every later milestone must respect it.

## What v0 was

v0 is now frozen. Its content is the world kernel:

- Identity (`Registry`), time (`Clock`, `Scheduler`), audit (`Ledger`),
  state (`State` / `StateSnapshot`)
- Network books (`OwnershipBook`, `ContractBook`, `PriceBook`)
- Projections (`BalanceSheetProjector`, `ConstraintEvaluator`,
  `LendingExposure`, `PortfolioExposure`)
- Information (`SignalBook`, `WorldEvent`, `EventBus`)
- The `DomainSpace` abstraction and the eight concrete spaces

v0 contains **no economic behavior**. No agent acts. No price forms. No
constraint triggers a consequence. No signal moves a market. v0 is a
constitution, not a simulator.

For the full content of v0, see
[`v0_release_summary.md`](v0_release_summary.md).

## What v1 is

v1 is a **jurisdiction-neutral reference financial system**. It introduces
behavior on top of v0 — but only behavior that is fully expressible
without naming a specific country, central bank, firm, fund, or data feed.

v1 includes:

- A reference **valuation** layer (v1.1) so that worth is more than
  face-value face value, but expressed against neutral fundamentals.
- An **intraday phase scheduler** (v1.2) so that within a calendar day
  there can be ordered phases (pre-market / market / settlement / etc.).
- **Institutional decomposition** (v1.3): each domain space gains
  reference behavior — corporate revenue / earnings updates, bank
  credit decisions, investor allocation, exchange clearing, real-estate
  cap-rate updates, information emission, policy reaction, external
  shock generation. All in *neutral form* — generic Taylor-style rule,
  generic continuous double auction, generic AR(1) factor process.
- An **ExternalWorld process layer** (v1.4) that drives external
  factors forward stochastically with declared parameters.
- A **relationship capital** layer (v1.5) that records cross-agent
  trust / reputation / counterparty-history at the kernel level so
  every space can read it.
- A **first closed-loop reference economy** (v1.6) that ties the above
  together: signal → decision → action → state change → new signal.

v1 is the first version where the simulation is actually *running*, in
the sense that something happens between t and t+1 beyond bookkeeping.
But everything that happens is reference logic — chosen for clarity and
testability, not for resemblance to any specific Japanese institution.

## What v1 is not

v1 must not contain:

- **Japan-specific identifiers.** No `firm:toyota`, `bank:mufg`,
  `investor:gpif`, `authority:boj`, `factor:usd_jpy`, or any other
  WorldID that names a real Japanese entity. v1 test fixtures may use
  jurisdiction-neutral names like `firm:reference_manufacturer_a`
  if needed.
- **Japan public data.** No JCER macro series, no BoJ statistics, no
  TSE listings, no JPMorgan / Bloomberg / etc. data feeds. Any time
  series in v1 is synthetic or reference.
- **Proprietary or paid data.** Same exclusion as v2 plus any expert
  knowledge curated for commercial use. Belongs to v3.
- **Calibrated parameters.** A reference AR(1) process in v1.4 has
  parameters chosen to make the test deterministic and the math
  obvious. Calibrating those parameters to actual JGB yield series is
  a v2 task.
- **Final realism in any space.** v1 reference behavior is the
  *minimum* behavior that closes the feedback loop. Increasing realism
  for a specific institution belongs to v2 or v3.

## Why the line is drawn here

The split between v1 (reference behavior) and v2 (Japan calibration)
exists because **model code and calibration data have very different
review cadences**.

- Model code changes when the architecture or reference logic changes.
  It is reviewed by people who understand the code and the math. A v1
  release can stand still for months.
- Calibration data changes whenever the underlying world changes.
  Quarterly earnings drop. Macro releases. Rate decisions. Index
  rebalances. v2 may release frequently because Japan releases
  frequently.

If the two were entangled — if `bank:mufg`'s capital ratio was
hard-coded into a `BankSpace` Python file — every Japan recalibration
would touch model code and every model change would invalidate
calibration runs. v1 keeps them separate so v2 can move quickly without
breaking v1's invariants and v1 can evolve without invalidating v2's
data drops.

The same argument extends to v3: proprietary data has higher provenance
constraints and a different access model than public data, so it
deserves its own layer.

## What v1 inherits from v0

v1 builds on v0 as additive code, not structural rewrite. That means:

- Every v0 module remains usable. `WorldKernel`, `Ledger`, `EventBus`,
  the eight `DomainSpace` subclasses, every read-only projection — all
  of them stay. v1 modules consume them.
- Every v0 invariant is preserved. v1 spaces still must not directly
  mutate each other. The `EventBus` next-tick rule still holds. The
  `Ledger` is still append-only. Read-only projections still must not
  mutate the books they read from.
- Every v0 ledger event type still means what it meant in v0. v1 may
  add new types but not redefine existing ones.

The complete invariant list is in
[`v1_design_principles.md`](v1_design_principles.md).

## What v1.0-prep delivers

This is v1.0-prep — the design gate. It contains four documents and a
README pointer. No Python code is added or changed. No tests are added
or removed. The 444 v0 tests must continue to pass.

The four prep documents are:

1. **This document** (`v1_reference_system_design.md`) — what v1 is,
   what it is not, why.
2. [`v1_design_principles.md`](v1_design_principles.md) — the
   invariants every v1 module must preserve.
3. [`v1_module_plan.md`](v1_module_plan.md) — the six v1 modules in
   planned order, each with its scope boundary.
4. [`v1_behavior_boundary.md`](v1_behavior_boundary.md) — the policy
   for how v1 introduces behavior, including the special case that
   v1.1 valuation is non-behavioral.

After these documents are accepted, v1.1 (Valuation Layer) becomes the
first implementation milestone of the v1 line. Until then, the
codebase remains at v0 freeze with documentation describing the
upcoming gate.

## Decision: do not start v1.1 yet

v1.0-prep does not implement valuation. It does not implement
fundamentals. It does not change runtime behavior. The deliberate gap
between this design gate and v1.1's first commit is the moment to
catch any mismatch between the four prep documents — to ensure the
invariants in `v1_design_principles.md` are consistent with the
modules in `v1_module_plan.md`, and that the behavior policy in
`v1_behavior_boundary.md` does not contradict the v0 contract from
`v0_release_summary.md`.

Once v1.1 starts, code will reference these documents. They are the
contract.
