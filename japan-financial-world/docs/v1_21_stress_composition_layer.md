# v1.21 Stress Composition Layer — Design Note

> **Status: docs-only.** v1.21.0a — the **scope-correction
> revision** of v1.21.0 — ships no executable code, no new
> tests, no new ledger event types, no new behavior. The living
> reference world's pinned digests (`quarterly_default` =
> `f93bdf3f4203c20d4a58e956160b0bb1004dcdecf0648a92cc961401b705897c`,
> `monthly_reference` =
> `75a91cfa35cbbc29d321ffab045eb07ce4d2ba77dc4514a009bb4e596c91879d`,
> `scenario_monthly_reference_universe` test-fixture digest =
> `5003fdfaa45d5b5212130b1158729c692616cf2a8df9b425b226baef15566eb6`,
> v1.20.4 CLI bundle digest =
> `ec37715b8b5532841311bbf14d087cf4dcca731a9dc5de3b2868f32700731aaf`),
> per-period record counts, per-run windows, and pytest count
> (`4764 / 4764`) are unchanged across the entire v1.21
> sequence to date.

## v1.21.0a correction (binding) — read before everything else

External design review of the v1.21.0 design note flagged a
fundamental scope problem: the v1.21.0 framing introduced a
`StressInteractionRule` that would have **auto-classified**
overlapping stresses as `amplify` / `dampen` / `offset` /
`coexist`. That label set tacitly claims a *combined effect* is
observable — but public FWE has neither actor decisions nor
price formation, so a "combined effect" has no objective ground
truth. An auto-inferred interaction label would therefore be a
**pseudo-causal claim**, not an audit.

v1.21.0a corrects this by **narrowing the v1.21 scope** to a
**thin stress-program orchestrator + read-only multiset
readout** over the existing v1.18 scenario-driver application
chain. Specifically:

- **`StressInteractionRule` is deferred to v1.22+ (or never).**
  No auto-classifier ships in the v1.21 sequence. See the
  *Deferred: StressInteractionRule* section below for the full
  reasoning.
- **No aggregate / composite / net / dominant fields.** The
  Stress Composition Layer never computes a combined stress
  result, a net direction, a dominant label, or a composite
  risk score. Every readout is a **multiset projection** — a
  bag of plain-id citations and label tuples — never a
  reduction.
- **Reuse, not reinvent.** A `StressProgram` is a *named
  ordered bundle* of existing v1.18.1
  `scenario_driver_template_id` plain-id citations. Applying a
  program calls the existing v1.18.2 `apply_scenario_driver(...)`
  helper step by step. The resulting v1.18.2
  `ScenarioDriverApplicationRecord` /
  `ScenarioContextShiftRecord` chain remains the single source
  of truth for what the engine emitted. v1.21 adds **only** a
  program-level receipt and a read-only descriptive readout.
- **Tighter cardinality.** v1.21.0a pins **≤ 1 stress program
  per run**, **≤ 3 stress steps per program**, and **≤ 60 v1.21
  records added on top of a v1.20.3-style run** (the v1.21.0
  budget was looser; v1.21.0a tightens it).

The rest of this document is the v1.21.0a-corrected design.
The v1.21.0 framing is **superseded** by this revision and is
preserved only in git history.

## Purpose

v1.20.last froze the **monthly scenario reference universe**:
12 monthly periods × 11 generic sectors × 11 representative
synthetic firm profiles × 4 investor archetypes × 3 bank
archetypes × 51 information arrivals × **one** scheduled
scenario application (`credit_tightening_driver` at
`month_04`). A reviewer can already export a deterministic
bundle and inspect the universe / sector / monthly scenario
surface in a `file://` browser session.

Adding a second scheduled scenario today is straightforward
mechanically — the v1.20.2 `ScenarioSchedule` storage layer
already accepts multiple scheduled applications, and the v1.18.2
`apply_scenario_driver(...)` helper is idempotent and append-
only. What's missing is a **named, auditable container** that
says "these N scenario drivers belong to one stress program" and
lets a reviewer see, at a glance, *which stress program was
applied this run, in what step order, and which v1.18.2
application + context-shift records that produced*.

That container is the **Stress Composition Layer** — and after
the v1.21.0a correction, that is **all** it is. It does **not**
reason about composition; it does **not** classify overlap; it
does **not** reduce a list of context shifts into a single
direction. It is a thin orchestrator + a read-only multiset
audit.

The layer answers three inspection questions:

1. **Which stress stimuli were programmed for this run?** —
   `StressProgramTemplate` + `StressStep` (the static plan; one
   program per run, ≤ 3 steps).
2. **Which underlying v1.18.2 scenario applications were
   produced when the program was applied?** —
   `StressProgramApplicationRecord` (the per-program receipt;
   one per `apply_stress_program(...)` call) + the existing
   v1.18.2 records it cites.
3. **What stress stimuli were active in each (period, context
   surface) cell of the run?** — `StressFieldReadout` (a
   read-only multiset projection over the cited records).

Everything else — interaction inference, magnitude estimation,
amplify / dampen / offset / coexist labels, dominant-direction
labels, composite risk scores, expected stress responses,
predicted outcomes — is **out of scope** for v1.21.

## Sequence map (corrected)

| Milestone     | Module / surface                                                                     | Adds                                                                                                                                                                                                                                                                                                              |
| ------------- | ------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| v1.21.0       | docs only (superseded by this revision)                                              | Original design that introduced `StressInteractionRule` + `STRESS_INTERACTION_LABELS` + auto-inferred composition labels. Now superseded by v1.21.0a; preserved only in git history.                                                                                                                              |
| **v1.21.0a**  | docs only (this document)                                                            | Scope correction. Defer `StressInteractionRule` to v1.22+; narrow v1.21 to thin orchestration + read-only multiset readout; remove all aggregate / composite / net / dominant / interaction language; tighten cardinality (≤ 1 program / run, ≤ 3 steps / program, ≤ 60 added records); extend forbidden-name list. |
| v1.21.1       | `world/stress_programs.py`                                                           | Storage only: `StressProgramTemplate` + `StressStep` + one append-only `StressProgramBook`. Empty by default. No runtime behavior. No scenario application. No context shift emission. **Existing profile digests unchanged** unless a stress program is explicitly registered + applied.                       |
| v1.21.2       | `world/stress_applications.py`                                                       | `StressProgramApplicationRecord` + one append-only `StressApplicationBook` + `apply_stress_program(...)` thin helper. Internally calls existing v1.18.2 `apply_scenario_driver(...)` in ordinal step order. Emits **one program-level receipt** that **collects** the underlying `scenario_application_ids`. **Does not infer interactions, does not emit interaction labels, does not mutate any source-of-truth book.** Existing profile digests unchanged unless `apply_stress_program(...)` is explicitly invoked. |
| v1.21.3       | `world/stress_readout.py` + `examples/reference_world/stress_field_summary.py`       | `StressFieldReadout` helper + `render_stress_field_summary_markdown(...)` renderer. **Read-only.** Multiset-only output. **No reduce / fold / aggregate / composite fields.** Optional UI strip in the v1.20.5 Universe tab gated by *first pinning* the CLI markdown summary; the UI strip ships only after the markdown surface is byte-stable. |
| v1.21.last    | docs only                                                                            | Single-page reader-facing summary, freeze pin, release-readiness snapshot, cross-links.                                                                                                                                                                                                                            |

## Design constraints (binding at v1.21.0a)

- **Reuse existing v1.18.1 `scenario_driver_template_id` ids.**
  Every `StressStep` cites a v1.18.1
  `scenario_driver_template_id` via plain id; v1.21 does **not**
  introduce a parallel scenario-family taxonomy.
- **Reuse existing v1.18.2 `apply_scenario_driver(...)` helper.**
  v1.21.2's `apply_stress_program(...)` is a *thin orchestrator*
  — it walks `step_index` in ascending order and calls
  `apply_scenario_driver(...)` once per step. It does **not**
  re-implement v1.18.2 emission logic and does **not** emit any
  context-shift records itself.
- **Reuse existing closed-set vocabularies.** v1.21.0a deletes
  every interaction / composition / output label that
  v1.21.0 introduced. The only **new** closed sets v1.21 may
  introduce are:
  - a small `STRESS_PROGRAM_PURPOSE_LABELS` frozenset (5–8
    entries, jurisdiction-neutral) for the program's static
    label,
  - a small `STRESS_PROGRAM_HORIZON_LABELS` frozenset (3–4
    entries: `monthly_12_period` / `quarterly_4_period` /
    `custom_synthetic` / `unknown`),
  - `STRESS_PROGRAM_APPLICATION_STATUS_LABELS` mirroring v1.18.2
    `APPLICATION_STATUS_LABELS` verbatim (no new labels).
  
  Every other v1.21 dataclass field reuses an existing v1.18.1 /
  v1.18.2 / v1.20.2 closed set:
  `scenario_family_label` / `driver_group_label` /
  `context_surface_label` / `shift_direction_label` /
  `event_date_policy_label` / `severity_label` /
  `affected_actor_scope_label` / `application_status_label` /
  `reasoning_mode` / `reasoning_slot` / `visibility` / `status` /
  `scheduled_month_label` / `scheduled_period_index`. **If a new
  vocabulary becomes unavoidable in v1.21.1 / v1.21.2 / v1.21.3,
  the introducing milestone must justify the addition in its
  design pin and add a closed-set vocabulary test.**
- **No price, no forecast, no expected return, no target price,
  no buy / sell, no order, no trade, no execution, no clearing,
  no settlement, no financing execution, no lending decision, no
  firm decision, no investor action, no bank approval, no real
  data, no Japan calibration, no LLM output.** v1.21 extends the
  forbidden-field-name list with **the v1.21.0a aggregate /
  composite / net / dominant tokens** (see *Forbidden naming
  boundary* below).
- **No interaction inference.** No label like `amplify`,
  `dampen`, `offset`, `coexist`, `overlap_resolved` is computed
  by any helper. The full closed set
  `STRESS_INTERACTION_LABELS` introduced in v1.21.0 is
  **deleted** at v1.21.0a; if interaction-style annotation is
  ever reconsidered (see *Deferred: StressInteractionRule*
  below), it must be `manual_annotation`-only and never
  inferred by a helper.
- **No aggregate fields.** No `aggregate_shift_direction`,
  `combined_context_label`, `net_pressure_label`,
  `dominant_stress_label`, `composite_risk_label`,
  `stress_intensity_score`, `stress_amplification_score`,
  `expected_response`, `forecasted_outcome`, or any equivalent.
  `StressFieldReadout` is a **multiset projection** — every
  field is either a plain-id citation, a label tuple, or a
  count. No reductions.
- **All records append-only.** Existing source-of-truth books
  (PriceBook, ContractBook, ConstraintBook, OwnershipBook,
  InstitutionsBook, MarketEnvironmentBook, FirmFinancialStateBook,
  InterbankLiquidityStateBook, IndustryConditionBook,
  MarketConditionBook) are byte-identical pre / post v1.21
  invocation.
- **All readouts read-only.** The v1.21.3
  `StressFieldReadout` helper walks the v1.21.2 + v1.18.2
  records once and emits readouts; it never mutates any input
  and never re-reads runtime state. Re-running the helper on
  the same input produces byte-identical readouts.
- **Cardinality bounded.** See *Cardinality (binding)* below.

## Four dataclass shapes (interface sketches only — no implementation)

The shapes below are **interface sketches**, not
implementations. v1.21.1 / v1.21.2 / v1.21.3 will land the
actual `@dataclass(frozen=True)` definitions with closed-set
validation, `__post_init__` guards, and `to_dict` methods
mirroring the v1.18 / v1.20 patterns.

The v1.21.0 draft listed **six** dataclass shapes
(`StressProgramTemplate`, `StressStep`,
`StressFieldApplicationRecord`, `StressInteractionRule`,
`StressFieldReadout`, optional `StressFieldSummaryProjection`).
v1.21.0a reduces this to **four**:

- `StressProgramTemplate` — kept, simplified.
- `StressStep` — kept, simplified.
- `StressProgramApplicationRecord` — renamed from the v1.21.0
  `StressFieldApplicationRecord` and re-scoped from
  per-step to **per-program**. One receipt per
  `apply_stress_program(...)` call.
- `StressFieldReadout` — kept but stripped of every interpretive
  label; now a pure multiset projection.

Dropped at v1.21.0a:

- `StressInteractionRule` — deferred to v1.22+ (or never); see
  the *Deferred: StressInteractionRule* section below.
- `StressFieldSummaryProjection` — folded into the v1.21.3
  markdown summary renderer; not a separate dataclass.

### 1. `StressProgramTemplate`

A *named, ordered bundle* of existing v1.18.1 scenario drivers.
The orchestration unit. A program is reusable across runs /
fixtures.

```
StressProgramTemplate
    stress_program_template_id      str
    program_label                   str (free-form, label-only,
                                          jurisdiction-neutral)
    program_purpose_label           str (closed-set; small —
                                          see Closed-set
                                          vocabulary discipline
                                          below)
    horizon_label                   str (closed-set; small)
    step_count                      int  # MUST be 1, 2, or 3
                                          # (v1.21.0a cardinality
                                          # binding)
    stress_step_ids                 tuple[str, ...]  # plain-id;
                                          # length == step_count;
                                          # ordered (apply order
                                          # = list order)
    severity_label                  str (REUSED: v1.18.1
                                          SEVERITY_LABELS)
    affected_actor_scope_label      str (REUSED: v1.18.1
                                          AFFECTED_ACTOR_SCOPE_LABELS)
    reasoning_mode                  str (binding default
                                          "rule_based_fallback")
    reasoning_policy_id             str
    reasoning_slot                  str (binding default
                                          "future_llm_compatible")
    status                          str (REUSED: v1.18.1
                                          STATUS_LABELS)
    visibility                      str (REUSED: v1.18.1
                                          VISIBILITY_LABELS)
    metadata                        Mapping[str, Any]
                                      # opaque; scanned for
                                      # FORBIDDEN_STRESS_FIELD_NAMES
```

### 2. `StressStep`

One stress step inside a program. Wraps a v1.18.1
`scenario_driver_template_id` with the per-step ordinal +
optional scheduling. A stress step is the **plan**; the runtime
emission is the v1.18.2 `ScenarioDriverApplicationRecord` that
`apply_stress_program(...)` produces by calling the existing
v1.18.2 helper.

```
StressStep
    stress_step_id                      str
    stress_program_template_id          str  # plain-id
    step_index                          int  # ordinal, 0..2
                                              # (≤ 3 steps per
                                              # program)
    scenario_driver_template_id         str  # plain-id, REUSE
                                              # v1.18.1
    # OPTIONAL scheduling — if present, used by v1.21.4 (NOT
    # YET SCOPED) to fire the step on the named period.
    # v1.21.1 / v1.21.2 ignore these fields; the v1.21.2 helper
    # accepts an explicit as_of_date kwarg per step.
    scheduled_period_index              int | None
                                              # 0..11 (or None)
    scheduled_month_label               str | None
                                              # REUSED: v1.20.2
                                              # SCHEDULED_MONTH_LABELS
    status                              str (REUSED)
    visibility                          str (REUSED)
    metadata                            Mapping[str, Any]
```

### 3. `StressProgramApplicationRecord`

Append-only **program-level receipt** emitted by
`apply_stress_program(...)`. One receipt per `apply_stress_program`
call, regardless of step count. The receipt **collects** the
underlying v1.18.2 `scenario_application_ids` produced by the
ordinal `apply_scenario_driver(...)` calls; it does **not**
re-emit context-shift records and does **not** classify
interactions.

```
StressProgramApplicationRecord
    stress_program_application_id       str
    stress_program_template_id          str  # plain-id
    as_of_date                          str  # ISO YYYY-MM-DD
                                              # (program-level
                                              # invocation date;
                                              # individual steps
                                              # may carry their
                                              # own dates as
                                              # collected on the
                                              # cited
                                              # ScenarioDriverApplicationRecord
                                              # objects)
    application_status_label            str (REUSED: v1.18.2
                                              APPLICATION_STATUS_LABELS;
                                              v1.21 ships no new
                                              status labels)
    cited_stress_step_ids               tuple[str, ...]  # in
                                              # ordinal order
    cited_scenario_application_ids      tuple[str, ...]  # plain-id;
                                              # COLLECTED from the
                                              # underlying v1.18.2
                                              # apply_scenario_driver
                                              # calls; one per
                                              # successfully-applied
                                              # step
    cited_scenario_context_shift_ids    tuple[str, ...]  # plain-id;
                                              # collected from the
                                              # cited v1.18.2
                                              # application records
    unresolved_step_count               int  # how many steps did
                                              # NOT produce a
                                              # v1.18.2 application
                                              # record (e.g. missing
                                              # template); 0 in the
                                              # happy path
    reasoning_mode                      str (binding "rule_based_fallback")
    reasoning_policy_id                 str
    reasoning_slot                      str (binding "future_llm_compatible")
    boundary_flags                      Mapping[str, bool]
                                          # default 8-flag set +
                                          # v1.21 additions:
                                          #   no_actor_decision    True
                                          #   no_field_value_claim  True
                                          #   no_field_magnitude_claim True
                                          #   no_aggregate_stress_result True
                                          #   no_interaction_inference True
    status                              str (REUSED)
    visibility                          str (REUSED)
    metadata                            Mapping[str, Any]
```

### 4. `StressFieldReadout`

Per-`(period, context_surface)` **read-only multiset
projection** over the cited v1.21.2 program-application receipt
+ the v1.18.2 application + context-shift records. Every field
is either a plain-id citation, a label tuple, or a count. **No
reductions.**

```
StressFieldReadout
    stress_field_readout_id             str
    as_of_date                          str  # ISO YYYY-MM-DD
    period_index                        int  # 0-based, 0..11
    month_label                         str (REUSED: v1.20.2)
    context_surface_label               str (REUSED: v1.18.2)
    # Multiset projection — ALL TUPLES, NO REDUCTIONS.
    active_stress_program_template_ids  tuple[str, ...]  # plain-id;
                                              # in v1.21 always
                                              # length 0 or 1
                                              # (≤ 1 program /
                                              # run)
    active_stress_step_ids              tuple[str, ...]  # plain-id;
                                              # ≤ 3
    active_scenario_driver_template_ids tuple[str, ...]  # plain-id;
                                              # REUSED v1.18.1
    active_scenario_application_ids     tuple[str, ...]  # plain-id;
                                              # cites v1.18.2
                                              # ScenarioDriverApplicationRecord
                                              # ids
    active_scenario_context_shift_ids   tuple[str, ...]  # plain-id;
                                              # cites v1.18.2
                                              # ScenarioContextShiftRecord
                                              # ids
    active_scenario_family_labels       tuple[str, ...]  # REUSED:
                                              # v1.18.1
                                              # SCENARIO_FAMILY_LABELS;
                                              # PRESERVED AS A LIST,
                                              # NOT DEDUPED, NOT
                                              # COUNTED INTO A
                                              # HISTOGRAM
    active_shift_direction_labels       tuple[str, ...]  # REUSED:
                                              # v1.18.2
                                              # SHIFT_DIRECTION_LABELS;
                                              # ditto — list, not
                                              # reduction
    cited_source_context_record_ids     tuple[str, ...]  # plain-id;
                                              # the
                                              # source_context_record_ids
                                              # COLLECTED from the
                                              # cited v1.18.2
                                              # context-shift records
    downstream_citation_ids             tuple[str, ...]  # plain-id;
                                              # OPTIONAL; if the
                                              # caller supplies a
                                              # downstream-citation
                                              # index (e.g. a list
                                              # of v1.15.5
                                              # InvestorMarketIntent
                                              # ids that cite a
                                              # context-shift id),
                                              # those plain ids are
                                              # echoed here verbatim
    unresolved_reference_count          int  # echo of the v1.18.2
                                              # unresolved_ref_count
                                              # SUM across cited
                                              # records — this is
                                              # a count, not a
                                              # reduction
    status                              str (REUSED)
    visibility                          str (REUSED)
    metadata                            Mapping[str, Any]
```

`StressFieldReadout` does **not** carry any of the following
fields (binding):

- `aggregate_shift_direction` / `aggregate_context_label`
- `combined_context_label` / `combined_shift_direction`
- `net_pressure_label` / `net_stress_direction`
- `composite_risk_label` / `composite_market_access_label`
- `dominant_stress_label`
- `total_stress_intensity` / `stress_amplification_score` /
  `stress_intensity_score`
- `predicted_stress_effect` / `projected_stress_effect`
- `expected_field_response` / `expected_response`
- `forecasted_outcome`
- `interaction_label` / `output_context_label`
- `composition_label` / `dominant_shift_direction_label`

These are scanned for under the v1.21.0a forbidden-name list at
the v1.21.1 / v1.21.2 / v1.21.3 module-text + dataclass-field
+ payload-key + metadata-key boundary tests.

## Deferred: StressInteractionRule

The v1.21.0 design introduced `StressInteractionRule` with an
auto-classifier that mapped `(triggering_stress_step_ids ×
shared_context_surface_label)` to a closed-set
`interaction_label` ∈ `{amplify, dampen, offset, coexist,
unknown}`. **v1.21.0a defers this to v1.22+ (or never)** for
the following reasons:

1. **`amplify` / `dampen` / `offset` imply that a combined
   effect is observable.** Public FWE has neither actor
   decisions nor price formation, so a "combined effect" has
   no objective ground truth. Two simultaneous context shifts
   on `market_environment` may or may not interact in the real
   world — but FWE has no real world to ground that claim.
2. **An auto-inferred interaction label would be a pseudo-
   causal claim.** The classifier in v1.21.0 was a closed-set
   rule-based table, which sounds defensible — but a closed-set
   rule is *still* a claim about reality, just one that hides
   behind discrete labels. A reviewer reading
   `interaction_label = amplify` will read it as "the engine
   confirmed these stresses amplify each other", which is not
   what the rule actually says.
3. **The audit value is in citations, not classifications.**
   A reviewer wants to see *which stresses were active on
   which surface in which month* — the `StressFieldReadout`
   multiset already answers that. They do **not** need the
   engine to interpret the overlap for them. Interpretation is
   the human reviewer's job, supported by the citations.
4. **Removing the inference reduces surface area.** The v1.21.0
   draft introduced `STRESS_INTERACTION_LABELS`,
   `STRESS_OUTPUT_CONTEXT_LABELS` (a superset of the v1.18.2
   shift directions plus `mixed` / `neutral`), an interaction
   classifier helper, an interaction book, and per-record audit
   shape — all of which v1.21.0a deletes. The smaller surface
   is easier to freeze and easier to audit.

If interaction-style annotation is **ever** reconsidered (in
v1.22 or beyond), the binding constraints below carry forward:

- It MUST be `manual_annotation`-only — a human reviewer types
  in `interaction_label = amplify` after reading the multiset
  citations, with their own analyst id and timestamp on the
  annotation record.
- It MUST cite explicit evidence (e.g., a markdown analyst note
  pinned to a specific `(period, context_surface,
  active_stress_step_id_set)` cell of the multiset readout).
- It MUST NEVER be inferred by a helper, a classifier, a
  closed-set rule table, an LLM, or any other automated layer.
- It MUST NOT replace the multiset readout — the readout
  remains the authoritative audit; the annotation is a separate
  layer on top.

The forbidden-name list extends to cover the
`amplify` / `dampen` / `offset` family in any **non-annotation**
context (see *Forbidden naming boundary* below).

## Cardinality (binding)

- **≤ 1 stress program per run.** v1.21 does not register two
  stress programs on the same kernel; the v1.21.1
  `StressProgramBook.add_program` raises `DuplicateProgramError`
  if a second program is added.
- **≤ 3 stress steps per program.** v1.21.1
  `StressProgramTemplate.__post_init__` rejects `step_count >
  3`. The pin echoes the v1.20.0 budget headroom: 1 program × 3
  steps + the existing v1.20.3 + v1.18.2 chains stays under the
  v1.20.0 ≤ 4000 hard guardrail.
- **`StressProgramApplicationRecord` is per-program**, not
  per-step. One receipt per `apply_stress_program(...)` call,
  regardless of how many steps the program has. The underlying
  v1.18.2 `ScenarioDriverApplicationRecord` count is `≤ 3`
  (one per step that succeeds).
- **Per-period `StressFieldReadout` count ≤ 8** (one per
  context surface), so per-run readout count ≤ 12 × 8 = 96.
- **v1.21 records added per stress-applied run ≤ 60.** The
  budget breakdown:
  - 1 program template + 3 step records (v1.21.1 storage),
  - 1 program application receipt (v1.21.2),
  - ≤ 96 readouts (v1.21.3) — but a default fixture would emit
    far fewer (most surfaces are empty),
  - **≤ ~60 in practice**; the test pin is `≤ 60`.
- **`manifest.record_count ≤ 4000`** remains unchanged from
  v1.20.0. The v1.20.4 CLI fixture currently sits at **3241**;
  v1.21 is allotted up to 60 additional records, so any v1.21-
  enabled run profile stays comfortably under the guardrail.

**Forbidden loop shapes** (binding, carried forward and
extended):

- `O(P × I × F × scenario)` (v1.20)
- `O(P × I × F × venue)` (v1.20)
- `O(P × F × order)` (v1.20)
- `O(P × day × ...)` (v1.20)
- `O(P × I × F × stress_step)` (NEW at v1.21)
- `O(P × stress_step × stress_step × stress_step × ...)`
  factorial (NEW at v1.21)
- `O(P × stress × scenario_family × surface × actor_id)`
  (NEW at v1.21)
- `O(P × day × stress_step)` (NEW at v1.21)
- **Full `scenario × sector × firm × investor × bank` expansion**
  (carried forward verbatim as forbidden)

## Closed-set vocabulary discipline (binding)

v1.21.0a is **conservative**: prefer reusing existing
vocabularies over introducing new ones. The only **new** closed
sets v1.21 may introduce are:

| Vocabulary                                  | Why a new set is justified                                                                                                                                                                  |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `STRESS_PROGRAM_PURPOSE_LABELS`             | program-level static label has no v1.18 / v1.20 analog (a *program* is a v1.21 concept). Closed at 5–8 entries; jurisdiction-neutral; no real-data tokens; no forecast tokens.            |
| `STRESS_PROGRAM_HORIZON_LABELS`             | program-level horizon (`monthly_12_period` / `quarterly_4_period` / `custom_synthetic` / `unknown`); no v1.18 / v1.20 analog; closed at 4 entries.                                          |

Every other v1.21 dataclass field **MUST reuse** an existing
closed set:

- `scenario_family_label` ← v1.18.1 `SCENARIO_FAMILY_LABELS`
- `driver_group_label` ← v1.18.1 `DRIVER_GROUP_LABELS`
- `context_surface_label` ← v1.18.2 `CONTEXT_SURFACE_LABELS`
- `shift_direction_label` ← v1.18.2 `SHIFT_DIRECTION_LABELS`
- `event_date_policy_label` ← v1.18.1 `EVENT_DATE_POLICY_LABELS`
- `severity_label` ← v1.18.1 `SEVERITY_LABELS`
- `affected_actor_scope_label` ← v1.18.1 `AFFECTED_ACTOR_SCOPE_LABELS`
- `application_status_label` ← v1.18.2 `APPLICATION_STATUS_LABELS`
- `reasoning_mode` ← v1.18.0 `REASONING_MODE_LABELS`
- `reasoning_slot` ← v1.18.0 `REASONING_SLOT_LABELS`
- `status` ← v1.18.1 `STATUS_LABELS`
- `visibility` ← v1.18.1 `VISIBILITY_LABELS`
- `scheduled_month_label` ← v1.20.2 `SCHEDULED_MONTH_LABELS`
- `scheduled_period_index` ← v1.20.2 `MONTHLY_PERIOD_INDEX_MIN` /
  `MONTHLY_PERIOD_INDEX_MAX` bound

If a v1.21.1 / v1.21.2 / v1.21.3 milestone discovers that a new
closed set is unavoidable, the introducing milestone MUST:

1. **Justify** the addition in its design pin (a paragraph in
   the relevant `world_model.md` section explaining why no
   existing set fits).
2. **Add a closed-set vocabulary test** mirroring the v1.18 /
   v1.20 pattern (e.g., `test_stress_*_labels_closed_set`
   pinning the exact frozenset contents).
3. **Add a forbidden-token test** that the new set's labels do
   not collide with any existing forbidden name.

## Forbidden naming boundary (binding)

`FORBIDDEN_STRESS_FIELD_NAMES` extends the v1.18.0 / v1.19.3 /
v1.20.0 forbidden-field-name lists with the **v1.21.0a aggregate
/ composite / net / dominant tokens**. Scanned recursively
across every dataclass field name, every payload key, every
metadata key, and the module text + test text via the
regression-test pattern carried from v1.20.x.

**Carried forward verbatim:**

- v1.18.0 actor-decision tokens: `firm_decision`,
  `investor_action`, `bank_approval`, `trading_decision`,
  `optimal_capital_structure`, `buy`, `sell`, `order`, `trade`,
  `execution`, `price`, `market_price`, `predicted_index`,
  `forecast_path`, `expected_return`, `target_price`,
  `recommendation`, `investment_advice`, `real_data_value`,
  `japan_calibration`, `llm_output`, `llm_prose`, `prompt_text`.
- v1.19.3 Japan-real-data tokens: `real_indicator_value`,
  `cpi_value`, `gdp_value`, `policy_rate`, `real_release_date`.
- v1.20.0 real-issuer / licensed-taxonomy tokens:
  `real_company_name`, `real_sector_weight`, `market_cap`,
  `leverage_ratio`, `revenue`, `ebitda`, `net_income`,
  `real_financial_value`, `gics`, `msci`, `sp_index`, `topix`,
  `nikkei`, `jpx`.

**NEW at v1.21.0a (forecast-shaped + aggregate / composite /
net / dominant tokens):**

- `stress_magnitude`
- `stress_magnitude_in_basis_points`
- `stress_magnitude_in_percent`
- `stress_probability_weight`
- `expected_field_response`
- `expected_stress_path`
- `stress_forecast_path`
- `stress_buy_signal`
- `stress_sell_signal`
- `stress_target_price`
- `stress_expected_return`
- `stress_outcome_label`
- `aggregate_shift_direction`
- `aggregate_context_label`
- `combined_context_label`
- `combined_shift_direction`
- `net_pressure_label`
- `net_stress_direction`
- `composite_risk_label`
- `composite_market_access_label`
- `dominant_stress_label`
- `total_stress_intensity`
- `stress_amplification_score`
- `predicted_stress_effect`
- `projected_stress_effect`

The classifier-style tokens deleted from v1.21.0
(`amplify` / `dampen` / `offset` / `coexist` /
`stress_interaction_label` / `output_context_label` /
`composition_label`) are also added to the forbidden list as
field names — they may appear only inside the deferred
`StressInteractionRule` discussion above (which is text-only)
and inside this forbidden-list literal block (which the
test-file scan strips before scanning, mirroring the v1.20.x
`_strip_forbidden_literal` discipline).

## Suggested tests (for v1.21.1 / v1.21.2 / v1.21.3)

These tests will land alongside the code milestones; **v1.21.0a
ships none**. The test names below are pinned at v1.21.0a.

### v1.21.1 storage tests (`tests/test_stress_programs.py`)

- `test_stress_program_template_is_storage_only`
- `test_stress_program_book_empty_by_default_keeps_existing_digests`
  — pins that `quarterly_default` `f93bdf3f…b705897c`,
  `monthly_reference` `75a91cfa…91879d`, and
  `scenario_monthly_reference_universe` test fixture
  `5003fdfaa45d…f15566eb6` are byte-identical when no stress
  program is registered.
- `test_stress_program_rejects_more_than_three_steps`
- `test_stress_program_rejects_zero_steps`
- `test_stress_program_step_index_is_zero_based_and_dense`
- `test_stress_program_fields_do_not_include_forbidden_names`
  — scans `__dataclass_fields__`, `to_dict()` keys, payload
  keys, and metadata keys against `FORBIDDEN_STRESS_FIELD_NAMES`.
- `test_stress_program_introduces_no_new_behavior`
- closed-set vocabulary tests for the two new sets
  (`STRESS_PROGRAM_PURPOSE_LABELS`,
  `STRESS_PROGRAM_HORIZON_LABELS`).
- ledger one-record-per-add, snapshot determinism, kernel
  wiring (mirrors v1.20.1 / v1.20.2 patterns).
- module-text + test-text jurisdiction-neutral scan +
  licensed-taxonomy scan + v1.21.0a forecast / aggregate /
  composite / net / dominant token scan.

### v1.21.2 application tests (`tests/test_stress_applications.py`)

- `test_apply_stress_program_calls_apply_scenario_driver_in_ordinal_order`
  — pins that the v1.18.2 helper is invoked once per step in
  ascending `step_index` order.
- `test_stress_program_application_emits_one_program_receipt`
  — exactly one `StressProgramApplicationRecord` per
  `apply_stress_program(...)` call.
- `test_stress_program_application_collects_underlying_scenario_application_ids`
  — `cited_scenario_application_ids` lists every v1.18.2 record
  produced by the ordinal step calls, in step order.
- `test_apply_stress_program_emits_no_interaction_label`
  — scans the produced records for any of `amplify` / `dampen`
  / `offset` / `coexist` / `interaction_label` / `composition_label`
  / `aggregate_*` / `combined_*` / `net_*` / `dominant_*` /
  `composite_*` tokens. Any hit fails.
- `test_apply_stress_program_does_not_mutate_source_of_truth_books`
  — every snapshot listed under *Design constraints* is
  byte-identical pre / post call.
- `test_record_count_added_by_stress_program_within_60`
  — pins the cardinality budget.
- `test_existing_profiles_unchanged_without_explicit_stress_program`
  — `quarterly_default` / `monthly_reference` /
  `scenario_monthly_reference_universe` `living_world_digest`s
  unchanged across the v1.21.2 ship when
  `apply_stress_program(...)` is never called.

### v1.21.3 readout tests (`tests/test_stress_field_readout.py`)

- `test_stress_field_readout_is_read_only`
  — runs the helper twice on the same kernel + program-
  application receipt; second call produces byte-identical
  readouts.
- `test_stress_field_readout_is_multiset_only`
  — every readout field is either a plain-id citation, a
  label tuple, or a count. No reduction (no `aggregate_*`,
  `combined_*`, `net_*`, `dominant_*`, `composite_*`,
  `interaction_label`, `composition_label`,
  `output_context_label`, `dominant_shift_direction_label`,
  `expected_*`, `predicted_*`, `forecasted_*`,
  `total_*_intensity`, `*_amplification_score`,
  `*_intensity_score`).
- `test_stress_field_readout_has_no_aggregate_combined_net_dominant_fields`
  — explicit allowlist test on `__dataclass_fields__` /
  `to_dict()` keys.
- `test_render_stress_field_summary_contains_active_stresses_without_magnitude`
  — the markdown summary lists `active_stress_program_template_ids`,
  `active_stress_step_ids`, `active_scenario_driver_template_ids`,
  per-month, per-context-surface; never renders a number with
  basis-points / percent / score / magnitude / probability /
  expected / predicted / forecast units.
- `test_ui_strip_does_not_display_price_forecast_risk_score_or_recommendation`
  — when the v1.21.3 UI strip ships (gated on the markdown
  summary first being byte-stable), a manual smoke confirms
  the rendered DOM contains none of: `price`, `forecast`,
  `risk score`, `risk_score`, `recommendation`, `buy`, `sell`,
  `target price`, `expected return`, `prediction`, `outcome`,
  `magnitude`, `intensity`, `amplification`, `aggregate`,
  `composite`, `dominant`, `net stress`, `combined stress`.

## UI guidance (binding for v1.21.3 / future)

**Do not make Ledger the first view.** The v1.20.5 Universe tab
remains the headline read for a v1.21-enabled run.

The first UI addition (v1.21.3 or later) MUST be **minimal**:

- **Universe tab — Active stresses timeline strip above the
  sector heatmap.** A single horizontal strip with **12 monthly
  cells**.
- **Each cell lists or dots active stress families.** Family
  here means the v1.18.1 `scenario_family_label`. The cell
  text echoes the label verbatim.
- **Hover shows active stress steps and emitted context shifts.**
  A tooltip or expandable detail row lists the
  `active_stress_step_ids` and the
  `active_scenario_context_shift_ids` (cited plain ids only).

The strip MUST NOT include:

- **No bar height.** No vertical encoding of magnitude.
- **No magnitude.** No basis-points, percent, score, intensity,
  amplification.
- **No risk score.** No composite, net, dominant, aggregate,
  combined.
- **No arrows implying propagation.** No "stress X → outcome Y"
  arrows. Citations are listed, not animated.
- **No `impact` / `amplification` / `prediction` / `outcome`
  wording.** Use neutral phrasing — "stress X is active in
  month M on surface S", "N records cite stress X", "stress
  step S maps to scenario family F".

The purpose of the strip is to show, at a glance:

1. **Which stress stimuli were active each month** (the
   `active_stress_step_ids` per month).
2. **Which context surfaces received append-only shifts**
   (the `active_scenario_context_shift_ids` per
   `(period, context_surface)`).
3. **Which downstream records cited those shifts** (the
   `downstream_citation_ids`, when supplied).

The **hard wording disciplines** carried forward from v1.20.5
remain binding:

- The UI MUST NEVER render "stress X caused outcome Y", "stress
  X has impact Z basis points", "stress X is more likely than
  stress Y", "stress X predicts …", or any equivalent.
- The UI MUST NEVER render a numeric magnitude on a stress step
  or a context shift.
- The UI MUST NEVER suggest a buy / sell / hold / allocation /
  rebalance action.
- `textContent` only — never `innerHTML` for user-loaded JSON.
- No `eval`, no `fetch` / XHR, no backend, no file-system
  write, no `location.hash` mutation during bundle load,
  no scroll jump, no active-sheet shift.

## Naming boundary (binding, carried forward)

- No real companies; no real sector weights; no real
  financial values; no real indicator values; no real
  release dates; no real institutional identifiers.
- Sector labels carry the `_like` suffix; firm ids follow
  the synthetic `firm:reference_<sector>_a` pattern; no
  public-FWE module text or test depends on bare `GICS`,
  `MSCI`, `S&P`, `FactSet`, `Bloomberg`, `Refinitiv`,
  `TOPIX`, `Nikkei`, or `JPX` tokens.
- Stress program / step / application ids follow synthetic
  patterns (`stress_program:<purpose_label>:<run_id>` /
  `stress_step:<program_id>:<step_index>` /
  `stress_program_application:<program_id>:<as_of_date>`
  respectively).

## Read-in order (for a v1.21 reviewer)

1. [`v1_20_monthly_scenario_reference_universe_summary.md`](v1_20_monthly_scenario_reference_universe_summary.md)
   for the v1.20 frozen surface.
2. This document — the **v1.21.0a-corrected** design.
3. `world_model.md` §129 (v1.20) → §130 (v1.21) for the
   cross-position in the FWE module map.
4. The v1.21.last single-page summary (will be added at
   freeze time, mirroring
   `v1_20_monthly_scenario_reference_universe_summary.md`).

## Deliverables for v1.21.0a (this PR)

- This document (the v1.21.0a-corrected design note).
- `docs/world_model.md` §130 — refreshed to reflect the four-
  shape narrowing, the deferred `StressInteractionRule`
  rationale, and the tightened cardinality.
- `docs/v1_20_monthly_scenario_reference_universe_summary.md`
  "Next roadmap candidates" row for "v1.21 Stress Composition
  Layer" — refreshed to reflect the thin-orchestrator framing.
- **No** runtime implementation.
- **No** new Python modules.
- **No** new record types.
- **No** new closed-set vocabularies (the two new sets pinned
  in *Closed-set vocabulary discipline* will land at v1.21.1
  alongside the storage code).

Validation gate (this PR):

- `pytest -q` → **4764 / 4764** (unchanged).
- `python -m compileall world spaces tests examples` → clean.
- `ruff check .` → clean.
- All v1.20.last digests preserved byte-identical.

## Forward pointer

v1.21.1 will land
[`world/stress_programs.py`](../world/stress_programs.py)
(storage only — `StressProgramTemplate` + `StressStep` +
`StressProgramBook`, empty by default). v1.21.2 will land
[`world/stress_applications.py`](../world/stress_applications.py)
with `StressProgramApplicationRecord`, the append-only
`StressApplicationBook`, and the thin
`apply_stress_program(...)` orchestrator that calls the existing
v1.18.2 `apply_scenario_driver(...)` helper in ordinal step
order. v1.21.3 will land
[`world/stress_readout.py`](../world/stress_readout.py) with the
`StressFieldReadout` multiset-projection helper and a
deterministic markdown summary renderer; the v1.20.5 Universe-
tab strip ships **only after** the markdown summary is
byte-stable. v1.21.last will freeze the v1.21 sequence
(docs-only).

The `quarterly_default` / `monthly_reference` /
`scenario_monthly_reference_universe` digests must remain
**byte-identical** to v1.20.last across the entire v1.21
sequence. Any drift is a regression — never an intended
upgrade — and must be reverted.
