# v1.5 Relationship Capital Design

This document is the design rationale for the v1.5 milestone. v1.5
makes non-contractual relationships between world objects first-class
records: trust, reputation, advisory ties, main-bank-like ties,
historical support, information access, and other soft links that
contracts and ownership records cannot express.

v1.5 is structural and explicitly minimal. It stores relationship
records, supports strength updates, and provides a thin aggregation
view between two specific ids. It does **not** apply decay, decide
lending, drive investor behavior, propagate reputation effects, or
calibrate to any specific jurisdiction. Domestic behavior that consumes
relationship capital arrives in later milestones.

For the v1 design statement, see
[`v1_reference_system_design.md`](v1_reference_system_design.md).
For the inherited invariants, see
[`v1_design_principles.md`](v1_design_principles.md). For the meta-
policy on how behavior is introduced into v1, see
[`v1_behavior_boundary.md`](v1_behavior_boundary.md).

## Why contracts are not enough

The kernel already stores explicit obligations between parties:
`ContractBook` (v0.4) records loans, leases, bonds, derivatives,
purchase agreements. Each contract has parties, principal, rate,
maturity, status. That is the *legal* dimension of how two parties
interact.

But two parties also relate to each other in ways no contract
captures:

- A bank that has lent to the same firm for forty years and rolled
  the credit through three downturns has *something* the firm's other
  lenders do not — a soft commitment, an information channel, a
  reputation stake. None of it is in any contract.
- An advisor relationship between an investor and a sell-side analyst
  carries information access and trust that the advisor's formal
  contract does not enumerate.
- A chairman's seat on another firm's board (interlocking
  directorate) is a legal fact recorded somewhere, but its
  *informational* weight in cross-decisions is captured by the
  relationship, not by the seat.
- A "main bank" tie in some jurisdictions confers obligations that
  no individual contract spells out.
- An information-access tie between a regulator and a regulated
  entity may shape who learns what, when, even when no formal
  document discloses anything.

These ties matter for any later behavioral module that wants to
distinguish "first-time counterparties" from "long-term partners" —
which is exactly what v1.3+ behavior modules will need. v1.5 ships
the layer that holds them.

## Relationship capital vs contract vs ownership vs signal

| Layer            | What it stores                               | Lives in              |
| ---------------- | -------------------------------------------- | --------------------- |
| Contract         | Explicit legal obligation between parties    | `ContractBook` (v0.4) |
| Ownership        | Who holds what asset, in what quantity       | `OwnershipBook` (v0.4) |
| Signal           | A discrete information event                 | `SignalBook` (v0.7)   |
| Relationship     | Non-contractual soft link between two ids    | `RelationshipCapitalBook` (v1.5) |

A relationship is not a contract: contracts are discrete legal
artifacts; relationships are continuous-state soft ties.

A relationship is not ownership: ownership is a quantitative position
in a thing; a relationship is between two parties (or two non-party
ids — a relationship can hold between an institution and a market, an
investor and an analyst desk, a firm and a sector index).

A relationship is not a signal: signals are discrete information
events that happened at a point in time; relationships are persistent
states whose latest strength can be queried at any time. Signals can
be `evidence_refs` for a relationship — that is exactly what the field
is for.

The four layers together let a future behavioral module ask: "what
contracts bind these two parties? what does each own from the other?
what signals about each have they observed? what is the relationship
between them?" — and get four orthogonal answers.

## Relationship types

`relationship_type` is a free-form string. v1.5 enumerates none.
Suggested labels for callers:

- `"main_bank"` — a long-standing primary lending relationship
- `"advisory"` — advisor-client tie (analyst, consultant, auditor)
- `"trust"` — quantified trust score between two parties
- `"reputation"` — quantified reputation in some context
- `"historical_support"` — past instances of one party supporting
  the other through stress
- `"information_access"` — privileged channel for non-public
  information flow
- `"interlocking_directorate"` — shared board membership
- `"long_term_partnership"` — multi-decade commercial tie
- `"main_keiretsu"` — a future v2 Japan-specific tie

v1.5 stores any of these without interpretation. v2 / v3 may
populate `metadata` with type-specific parameters; v1.5 does not.

## Strength, direction, visibility

### Strength

`strength` is a numeric score whose interpretation is *domain-specific*.
A `"trust"` relationship with strength 0.7 may mean something very
different from a `"main_bank"` relationship with strength 0.7. v1.5
does not normalize across types and does not enforce a [0, 1] scale.
The book stores; consumers interpret.

This deliberately defers the question of "what scale should a strength
score live on?" — that is a calibration question and v1 stays
jurisdiction-neutral. v2 may impose conventions per type for Japan
public data; v1.5 imposes none.

### Direction

`direction` is a free-form string. Suggested labels:

- `"directed"` — asymmetric, from `source_id` to `target_id`. The
  relationship represents the source's view of the target.
- `"undirected"` — symmetric. The relationship holds equally in both
  directions; either party can claim the other as a counterparty.
- `"reciprocal"` — mutual but with potentially different strengths
  each way. Equivalent to two `"directed"` records, one in each
  direction. v1.5 lets callers represent reciprocity either way.

The direction value affects the v1.5 view aggregation rule (see
§ "Direction handling in build_relationship_view" below).

### Visibility

`visibility` is a free-form string. Suggested labels: `"public"`,
`"private"`, `"restricted"`, `"inferred"`, `"rumored"`. v1.5 stores
the label and propagates it to the ledger record's `visibility` field
but does **not** enforce visibility filtering at read time. A consumer
that wants to filter relationships by who can see them must do so
explicitly; v1.5 does not gate `list_*` calls by observer identity.

The reason for the deferred enforcement matches the v0.7 SignalBook
discussion: visibility-as-policy is a *consumer* concern, not a
storage concern. The book records what is visible to whom; the
consumer decides how to act on that.

## Evidence refs and causal traceability

`evidence_refs` on a relationship is a tuple of WorldIDs / record IDs
that justify why the relationship exists. v1.5 supports any kind:

- a contract id (the relationship is anchored in a long-standing
  loan)
- a signal id (a published rating or analyst report supports the
  relationship)
- an institutional action id (the relationship was strengthened by a
  recorded action)
- a valuation id (the relationship is sourced from a valuation that
  cited cross-effects)
- an external observation id (the relationship reflects a historical
  external regime)
- a ledger record id (the relationship was created in response to a
  specific past event)

The book does not validate that the referenced records exist (the v0
/ v1 cross-reference rule). The point of the field is *audit-trail
reconstruction*: a future replay engine can walk evidence_refs to
understand why a relationship was recorded.

This is the relationship-layer counterpart to v1.3's
`InstitutionalActionRecord.parent_record_ids`: both fields turn the
ledger into a causal graph rather than a flat log. A reviewer can ask
"why does this main-bank relationship exist?" and follow
`evidence_refs` to the contracts and historical-support actions that
justified it.

## Why decay is stored but not applied

`decay_rate` is a field on `RelationshipRecord` and v1.5 stores it
verbatim. v1.5 does **not** apply it: when you read a relationship
back, the strength you see is the stored value, not
`strength * exp(-decay_rate * elapsed)`.

The reasons:

1. **Decay is calibration, not architecture.** The half-life of trust,
   the persistence of advisor relationships, the longevity of
   main-bank ties — these are jurisdiction-specific empirical
   parameters. v1 stays jurisdiction-neutral. v2 (Japan public) and
   v3 (proprietary) calibrate the parameters and wire the decay
   engine.
2. **Decay model is a future-milestone concern.** Continuous
   exponential decay, step-down on covenant breaches, ratchet-up on
   repeated successful interactions — each is a different decay
   model. v1.5 should not commit to one. Storing `decay_rate` as a
   parameter slot lets v2 / later v1 modules pick a model and
   populate the slot consistently.
3. **Audit-trail clarity.** If decay were auto-applied, two reads of
   the same relationship at different dates would return different
   strengths. That makes the read path stateful in a way the rest of
   the kernel avoids. v1.5's reads are deterministic: a relationship's
   strength at any moment is whatever was last written, full stop.

A future behavior module that wants decayed strength computes it
itself from `(strength, decay_rate, as_of_date, current_date)`, or
calls `update_strength` to record a decayed value as a new fact.
Either path keeps the audit trail clear.

Test `test_decay_rate_stored_but_not_applied` enforces this rule by
constructing a relationship with `decay_rate=0.99` and a year-old
`as_of_date` and verifying the read still returns the original
strength.

## RelationshipCapitalBook API

CRUD:

- `add_relationship(record)` — append; rejects duplicate id; emits
  `relationship_added` to the ledger.
- `get_relationship(relationship_id)` — raises `UnknownRelationshipError`
  for unknown ids.
- `list_by_source(source_id)` / `list_by_target(target_id)` /
  `list_by_type(relationship_type)` — indexed reads.
- `list_between(source_id, target_id)` — directional: returns
  records with the exact (source, target) pair. Callers wanting both
  directions call twice.

Strength updates:

- `update_strength(relationship_id, new_strength, as_of_date=None,
  reason=None)` — replaces the record under the id with a copy
  carrying the new strength. The previous strength and the supplied
  reason are recorded to the ledger so the history is reconstructable
  without keeping every prior record live. If `as_of_date` is omitted,
  the existing record's `as_of_date` is preserved.

Aggregation view:

- `build_relationship_view(subject_id, counterparty_id)` — see
  next section.

Snapshot:

- `snapshot()` — sorted, JSON-friendly view of all relationships.

`get_relationship` raises on unknown id; `list_*` calls return
empty tuples.

## Direction handling in build_relationship_view

`build_relationship_view(A, B)` returns a `RelationshipView` summing
strengths from A's perspective. The inclusion rule is:

- All `(source=A, target=B)` records are included regardless of
  `direction`.
- `(source=B, target=A)` records are included **only** when their
  `direction` is `"undirected"` or `"reciprocal"`. Those go both ways
  by definition. `"directed"` records in the reverse direction
  describe B's view of A — they belong to `build_relationship_view(B, A)`,
  not to the view from A.

This is the conservative interpretation: a `"directed"` record stays
on the side of its declared source, and only explicit symmetry
(`"undirected"` / `"reciprocal"`) propagates across.

`total_strength` is the simple sum of strengths over the included
records. v1.5 does not:

- apply `decay_rate` before summing
- normalize across types
- weight by confidence
- deduplicate across direction
- filter by visibility

These are interpretation concerns. v1.5 only sums what's there.

## Why Japan main-bank calibration is v2/v3, not v1.5

The "main bank" concept is real, important, and Japan-specific in
its detailed form. v1.5 supports `relationship_type="main_bank"` as
a string label and stores any strength a caller assigns. It does not
calibrate to any actual Japanese institution.

The reasons:

1. **The strength scale is calibration.** A main-bank relationship
   strength of 0.8 means whatever the calibrating layer says it
   means. v1 cannot pick the meaning without committing to a
   specific jurisdiction's empirical findings.
2. **The decay model is calibration.** How fast does a main-bank
   relationship erode through a downturn? Through an M&A event?
   Through a generation change at the bank? These are empirical
   questions answered differently in different markets and at
   different times. v2 / v3 answer them; v1.5 stores the parameter
   slot.
3. **The behavioral consequences are calibration.** What does a
   main-bank relationship of strength 0.8 actually *do* in a credit
   decision? Discount the spread? Reduce the collateral haircut?
   Trigger a rescue? Each is a behavioral choice that a real
   Japanese bank's internal policy may answer differently from a
   reference module's.

v1.5 ships the recording. v2 will calibrate Japan-specific main-bank
relationships from public data (regulatory disclosures, financial
filings, public statements). v3 may layer in proprietary or
expert-curated overrides.

## What v1.5 ships

In scope:

- `world/relationships.py` with `RelationshipRecord` (immutable, 12
  fields), `RelationshipView` (immutable derived view), and
  `RelationshipCapitalBook` with the full CRUD surface plus
  `update_strength`, `build_relationship_view`, and `snapshot`.
- Two ledger record types: `relationship_added` and
  `relationship_strength_updated`. Strength updates record the
  previous strength and the supplied reason.
- Kernel wiring: `kernel.relationships` with default `__post_init__`
  propagation of `clock` and `ledger`.
- Tests covering all CRUD, list helpers, `update_strength` with
  ledger preservation of reason, evidence_refs preservation,
  decay-stored-not-applied, view aggregation (forward + undirected
  reverse, no decay applied), no behavior triggered by view, and
  no-mutation guarantee against all eight other source-of-truth
  books.

## What v1.5 does not ship

Out of scope:

- Lending decisions, investor behavior, automatic rescue / support,
  reputation dynamics, automatic information advantage. All belong
  to later milestones that consume relationships and satisfy the v1
  four-property action contract.
- Decay application. `decay_rate` is stored verbatim; v1.5 does not
  compute decayed strength.
- Reputation contagion across third parties (A's trust in B
  influencing C's trust in B). v1.5 records pairwise relationships;
  it does not propagate.
- Information-asymmetry models that compute *how much* a
  relationship affects information flow. v1.5 records the tie; it
  does not model the asymmetry.
- Visibility filtering at read time. v1.5 stores the visibility
  label; consumers decide how to filter.
- Network analytics (centrality, communities, clustering). Those
  are derivable from `snapshot()` if needed; v1.5 stores edges, not
  metrics.
- Japan-specific main-bank calibration and any other
  jurisdiction-specific relationship structures.
- Scenario interpretation, price impact, credit decisions, trading.

## v1.5 success criteria

v1.5 is complete when **all** of the following hold:

1. `RelationshipRecord` exists with all twelve documented fields and
   is immutable. Required fields are validated; `confidence` is
   bounded to [0, 1].
2. `RelationshipView` exists as an immutable derived record.
3. `RelationshipCapitalBook` provides `add_relationship`,
   `get_relationship`, `list_by_source`, `list_by_target`,
   `list_by_type`, `list_between`, `update_strength`,
   `build_relationship_view`, and `snapshot`.
4. Duplicate ids are rejected with `DuplicateRelationshipError`.
   Unknown lookups raise `UnknownRelationshipError`.
5. `update_strength` replaces the record in place, preserves all
   other fields, optionally updates `as_of_date`, and records a
   `relationship_strength_updated` ledger event with the previous
   strength and supplied reason.
6. `evidence_refs` is preserved through add and get unchanged.
7. `decay_rate` is stored verbatim and **not** automatically applied
   on read. Test enforces this.
8. `build_relationship_view` aggregates forward records plus
   undirected / reciprocal reverse records, sums strengths without
   applying decay, and triggers no behavior in any other book.
9. The two ledger record types are emitted on the corresponding
   `add_*` / update calls when a ledger is configured.
10. `kernel.relationships` is exposed with default wiring (clock and
    ledger propagated in `__post_init__`).
11. v1.5 mutates none of `OwnershipBook`, `ContractBook`,
    `PriceBook`, `ConstraintBook`, `SignalBook`, `ValuationBook`,
    `InstitutionBook`, or `ExternalProcessBook`.
12. All previous milestones (v0 through v1.4) continue to pass.
