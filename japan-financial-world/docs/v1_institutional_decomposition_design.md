# v1.3 Institutional Decomposition and Action Contract

This document is the design rationale for the v1.3 milestone. v1.3 adds
**institutions, mandates, instrument profiles, and recorded
institutional actions** as kernel-level objects, plus the **4-property
action contract** that every future v1 behavior module must follow when
it produces an action record.

v1.3 is structural. It introduces no central bank reaction function,
no policy decision logic, no liquidity operation, no regulatory impact,
no Japan-specific calibration, no scenarios. The deliberate scope is to
ship the *shape* of institutional action — explicit inputs, explicit
outputs, ledger trail, no cross-space mutation — so that v1.3+
behavioral modules have a single contract to implement against.

For the v1 design statement, see
[`v1_reference_system_design.md`](v1_reference_system_design.md). For
the inherited invariants, see
[`v1_design_principles.md`](v1_design_principles.md). For the meta-
policy on how behavior is introduced into v1, see
[`v1_behavior_boundary.md`](v1_behavior_boundary.md). v1.3 is the first
v1 module that produces *recorded behavior* rather than purely passive
state, so the action contract documented below is load-bearing for
everything later in v1.

## Why institutions are not just PolicySpace state

`PolicySpace` (v0.14, §34.2) classifies which policy authorities and
which instruments exist as *domain-space facts*. v1.3's
`InstitutionBook` operates one layer up. It represents institutions as
**kernel-level actors**: not "who PolicySpace knows about", but "who
the world recognizes as having mandates and instruments and who can
record actions".

The two layers can coexist. Their concerns are distinct:

| Concern                                  | PolicySpace (§34.2)             | InstitutionBook (v1.3)        |
| ---------------------------------------- | ------------------------------- | ----------------------------- |
| Which authorities have policy roles?     | yes (`PolicyAuthorityState`)    | yes (`InstitutionProfile`)    |
| Which instruments exist?                 | yes (`PolicyInstrumentState`)   | yes (`PolicyInstrumentProfile`) |
| Who has what *mandate*?                  | no                              | yes (`MandateRecord`)         |
| Audit trail of *recorded actions*?       | no                              | yes (`InstitutionalActionRecord`) |
| Layer                                    | domain space                    | kernel-level book             |
| Driven by                                | Policy reading SignalBook       | reusable v1.3+ behavior       |

PolicySpace will continue to exist and continue to classify policy-
domain entities. Future v1.3+ behavior that *produces* policy actions
(e.g., a v1.3 reference reaction function in PolicySpace) consumes
mandates from `InstitutionBook`, references instruments from there,
and records its action via `add_action_record(...)`. PolicySpace
remains the domain space; `InstitutionBook` is the action-and-audit
layer.

A practical implication: institutions (and their actions) are not
limited to policy. The same shape applies to:

- a regulator producing a supervisory review action
- an exchange operator producing a trading-rule announcement
- a deposit insurer producing a coverage adjustment
- a sovereign treasury producing a debt-issuance plan
- a foreign central bank producing a rate-decision signal that flows
  into ExternalSpace

All of these fit the same `InstitutionalActionRecord` schema. v1.3
ships the schema; v1.3+ modules ship the actual behavior that creates
records of each type.

## Institution types

`institution_type` is a free-form string. v1 deliberately enumerates
none — types are conventions chosen by the caller. Examples that
v2 will use:

- `central_bank`
- `treasury` / `finance_ministry`
- `financial_regulator`
- `securities_commission`
- `deposit_insurer`
- `exchange_authority`
- `market_operator`
- `payment_system_operator`
- `foreign_central_bank` (relevant for ExternalSpace v1.4 in the
  upstream direction)
- `international_organization`

v1.3 stores whatever string the caller provides. v2 calibrates real
institutions; v3 may add proprietary types if required.

The `jurisdiction_label` field is similarly free-form. v1 keeps
labels neutral (e.g. `"neutral_jurisdiction"`,
`"reference_jurisdiction_a"`) so institution shapes are separable
from real-jurisdiction calibration. **Test
`test_jurisdiction_label_is_label_only_not_calibration` asserts the
field accepts any string with no validation.**

## Mandates and instruments

A real institution carries multiple mandates that interact and
sometimes conflict — price stability vs financial stability vs
employment maximization, for a central bank; consumer protection vs
market efficiency, for a regulator. v1.3 stores them as separate
`MandateRecord`s so later milestones can reason about each
independently.

Instrument profiles are stored similarly. Each
`PolicyInstrumentProfile` ties an `instrument_id` to an
`institution_id` (foreign key, unvalidated per v0/v1 cross-reference
rule) and a `target_domain` describing what the instrument is meant
to influence. The `instrument_id` namespace is the same as
PolicySpace's `PolicyInstrumentState.instrument_id`, so the same
instrument can appear in both layers; v1.3 does not enforce a join.

## Recorded actions vs decided actions

v1.3 explicitly distinguishes *recorded* actions from *decided*
actions:

- A **decided action** is the output of a reaction function or
  decision rule: "given this state, the institution chooses to do X."
  v1.3 does **not** implement any decision logic.
- A **recorded action** is a fact: "on this date, this institution
  performed this action; here is what it consumed and what it
  produced."

`InstitutionalActionRecord` records facts. A future v1.3+ reaction
function may *create* an `InstitutionalActionRecord` as the output of
its decision, but v1.3 itself only ships the recording mechanism.
Tests construct action records manually to verify the recording shape;
no decision logic runs.

This separation is what makes v1.3's contract reusable. The same
schema works for:

- "the institution decided to do X via reaction function R" (future)
- "the institution announced X as a scheduled communication" (future)
- "the institution responded to crisis Y" (future)
- "the institution executed routine operation Z" (future)

In every case, the record names the inputs the institution drew on,
the outputs it produced, and the parent ledger records that justify
why this action happened. The record itself does not justify
anything; it just preserves the chain.

## The 4-property action contract

Every `InstitutionalActionRecord` satisfies four properties. This is
the contract every v1.3+ behavior module must implement when it
produces an institutional action.

### 1. Explicit inputs

`input_refs` is a tuple of WorldIDs / record IDs that the action
depended on. Examples:

- `("price:asset_a", "price:asset_b")` — depended on observed prices
- `("valuation:v_001",)` — depended on a valuation claim
- `("signal:rating_action_x",)` — depended on a rating signal
- `("ownership:agent_a:asset_b",)` — depended on a position

Empty tuple is allowed (some actions are seed actions or have no
data dependencies). `None` is not — `input_refs` is always a tuple
on the immutable record.

The point of `input_refs` is **traceability**: a reviewer auditing
the simulation must be able to look at the action record and know
exactly what the action saw. Future behavior modules that want to
read additional data must add it to `input_refs`; otherwise the
action is hiding part of its dependency graph.

### 2. Explicit outputs

`output_refs` is a tuple of records produced by the action.
Examples:

- `("signal:announcement_a",)` — produced an information signal
- `("price:asset_b@2026-01-15",)` — produced a price observation
- `("contract:loan_002",)` — produced a contract
- `("event:rate_change_003",)` — produced a `WorldEvent`

Empty tuple is allowed (informational actions may produce nothing
that needs ID-tracking; the ledger record itself preserves the
action). `None` is not.

The output references are not the *creation* of those records —
v1.3 forbids the action record from creating side effects directly
(see property 4 below). The references point to records that *some
other writer* (the institution's behavior code, in the appropriate
book) created and that the action wants to claim authorship over.

### 3. Ledger record

`InstitutionBook.add_action_record` emits an
`institution_action_recorded` ledger record on every `add_action_record`
call (when a ledger is configured). The ledger record:

- Has `object_id = action_id`, `source = institution_id`.
- Carries `parent_record_ids` exactly as supplied on the action
  record (the action's `parent_record_ids` field becomes the
  ledger record's `parent_record_ids` field).
- Mirrors the action's `input_refs`, `output_refs`, `target_ids`,
  `instrument_ids` in payload for downstream querying.

**Why parent_record_ids matter**: an institutional action
typically depends on other ledger records — the price observation
it read, the rating signal it received, the prior covenant test
that triggered review. Listing those parents on the action record
turns the ledger from a flat append-only log into a causal graph.
A future replay engine can walk parents from any action and
reconstruct the chain that produced it without re-running the
simulation.

This is invariant 6 from
[`v1_design_principles.md`](v1_design_principles.md), implemented
for institutions.

### 4. No direct cross-space mutation

`InstitutionBook.add_action_record` writes only to:

- The `_actions` map and per-institution index (its own state).
- The ledger (via `append`).

It does **not** write to:

- `OwnershipBook`, `ContractBook`, `PriceBook`, `ConstraintBook`,
  `SignalBook`, `ValuationBook`.
- Any domain space's internal state.

If a real institutional action *should* produce a price observation,
a contract update, a new signal, or any other state change, the
behavior module that decides on the action must:

1. Make the appropriate kernel-level book mutation directly via
   that book's documented API (e.g.
   `kernel.signals.add_signal(...)`).
2. Then record an `InstitutionalActionRecord` whose `output_refs`
   point to the records just produced and whose
   `parent_record_ids` link the action ledger record to its
   inputs and to the action itself.

The action record claims authorship and provides an audit trail.
It does not perform the mutation. Test
`test_action_record_does_not_mutate_other_books` enforces this:
adding an action that *references* prices, ownership, signals,
and instruments leaves every other book byte-identical.

## Why v1.3 does not implement policy behavior

v1.3 is the third v1 implementation milestone. The first (v1.1
Valuation) introduced new state. The second (v1.2 Intraday Phases)
introduced scheduling infrastructure. v1.3 introduces the *recording
schema* for institutional behavior — but explicitly not the behavior
itself.

Reasons:

1. **One concern per milestone.** Recording the shape of an action
   is its own design problem. The action contract — what fields are
   required, how the ledger chain works, how mutations are kept out —
   deserves its own milestone before any specific behavior consumes
   it. Conflating "the recording schema" with "the central bank's
   reaction function" would couple two unrelated risks: the schema
   would have to be re-litigated whenever a new behavior arrived.
2. **Multiple consumers.** Many future modules will produce
   institutional actions, not just one. v1.3 ships a contract that
   serves all of them. v1.3+ behavior modules — a reference policy
   reaction in PolicySpace, a reference supervisory review in a
   regulator, a reference exchange announcement in ExchangeSpace —
   all use the same schema.
3. **Reviewability.** A reviewer of v1.3 can examine the action
   contract on its own merits. A reviewer of v1.3+ behavior can
   examine the behavior knowing the contract is already settled.

This is the same separation between "data layer" and "behavior
layer" that the v1.1 Valuation Layer used: v1.1 stored valuation
claims and made comparing them possible without deciding anything;
v1.3 stores action records and makes the ledger graph reconstructable
without deciding anything.

## Why Japan-specific institutions belong to v2/v3

`InstitutionProfile.jurisdiction_label` is a free-form string. v1.3
deliberately uses neutral labels (`"neutral_jurisdiction"`,
`"reference_jurisdiction_a"`) and does not validate the field. The
reasons match those for keeping v1 jurisdiction-neutral overall:

- Institutions in different jurisdictions have different mandates,
  different instrument sets, different review cadences, and
  different relationships to other institutions. Encoding any of
  that as v1 logic would couple v1 to a specific jurisdiction.
- v2 will populate jurisdiction labels with real values and will
  add Japan-specific institution profiles (`jurisdiction_label="jp"`),
  Japan-specific mandates (BoJ price-stability target, FSA
  regulatory mandate, MoF debt management mandate), and
  Japan-specific instrument profiles. Those records will live in
  v2's data files / setup code, not in v1.3.
- v3 may further add proprietary or paid-data institutions
  (e.g., narrowly-scoped private regulators, off-exchange market
  operators) that v2's public-data layer cannot capture.

The neutrality is testable. **Test
`test_jurisdiction_label_is_label_only_not_calibration` constructs
profiles with multiple labels including the empty string and
verifies all are accepted without modification.**

## What v1.3 ships

In scope:

- `world/institutions.py` with four immutable records
  (`InstitutionProfile`, `MandateRecord`, `PolicyInstrumentProfile`,
  `InstitutionalActionRecord`) and `InstitutionBook` with the full
  CRUD surface (add / get / list_by, plus `snapshot`).
- Four new ledger record types: `institution_profile_added`,
  `institution_mandate_added`, `institution_instrument_added`,
  `institution_action_recorded`. The action record preserves
  `parent_record_ids` from the source record onto the ledger
  record.
- Kernel wiring: `kernel.institutions: InstitutionBook` with
  `__post_init__` propagating the kernel's `clock` and `ledger`.
- Tests: 35 covering the 4 dataclasses' shape, validation,
  immutability, CRUD, list filters, action contract preservation,
  snapshot determinism, ledger writes, no-mutation guarantee,
  jurisdiction-label neutrality, and kernel wiring.

Out of scope:

- Central bank reaction functions, policy rate setting, liquidity
  operations, regulatory rule changes.
- Any decision logic that *creates* `InstitutionalActionRecord`s
  from world state. v1.3+ behavior modules will do this; v1.3
  ships only the recording schema.
- Country-specific institutions or jurisdiction-calibrated
  behavior (those are v2 / v3).
- Automatic signal creation, EventBus delivery, or any cross-space
  side effect from action records.
- FX, scenarios, external shocks.

## v1.3 success criteria

v1.3 is complete when **all** of the following hold:

1. Four immutable dataclasses exist with all documented fields and
   reject empty required fields.
2. `InstitutionBook` provides the full CRUD surface listed above
   plus `snapshot()`, all with append-only semantics.
3. Duplicate `institution_id` / `mandate_id` / `instrument_id` /
   `action_id` are each rejected with their dedicated `Duplicate*`
   error.
4. The four ledger record types exist and are emitted on the
   corresponding `add_*` calls when a ledger is configured.
5. `institution_action_recorded` ledger records preserve
   `parent_record_ids` from the source action record.
6. `kernel.institutions` is exposed with default wiring (clock and
   ledger propagated in `__post_init__`).
7. Adding an action record does not mutate `OwnershipBook`,
   `ContractBook`, `PriceBook`, `ConstraintBook`, `SignalBook`, or
   `ValuationBook`.
8. `jurisdiction_label` accepts any free-form string without
   validation; v1.3 does not couple to any specific jurisdiction.
9. All previous milestones (v0 through v1.2.1) continue to pass.
