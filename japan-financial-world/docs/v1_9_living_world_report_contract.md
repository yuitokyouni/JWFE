# v1.9.1-prep — Living World Trace Report Contract

> **Status:** prep / contract only. v1.9.1 has not been implemented;
> this document defines the report contract the future
> `LivingWorldTraceReport` will be built against. No production code
> ships in v1.9.1-prep; a small contract test
> (`tests/test_living_reference_world_report_contract.py`) pins the
> v1.9.0 result schema invariants the reporter will rely on.

## v1.9.1 purpose

v1.9.1 will ship a deterministic **human-readable + machine-readable
trace report** over the v1.9.0 multi-period sweep. The report's
relationship to v1.9.0 mirrors v1.8.15's relationship to v1.8.14: it
is **read-only explainability**, not new modeling.

For the v1.8.15 design the report is built on top of, see
[`world_model.md`](world_model.md) §57 and
`world/ledger_trace_report.py`.

## Schema audit (v1.9.0 result vs. v1.9.1 needs)

This section is the contract: every checklist item below must remain
true for the v1.9.1 reporter to compose. The contract test
(`tests/test_living_reference_world_report_contract.py`) re-asserts
the structural ones that can be checked at the dataclass level.

### `LivingReferenceWorldResult` — required fields

All present on the v1.9.0 dataclass:

| Field | Present | Why the reporter needs it |
| --- | --- | --- |
| `run_id` | ✅ | Title / report id derivation. |
| `period_count` | ✅ | Section count; sanity check. |
| `firm_ids` | ✅ | Setup summary; per-firm coverage check. |
| `investor_ids` | ✅ | Setup + attention divergence. |
| `bank_ids` | ✅ | Same. |
| `per_period_summaries` | ✅ | Per-period table rows. |
| `created_record_ids` | ✅ | Cross-check against ledger slice. |
| `ledger_record_count_before` | ✅ | Slice start index. |
| `ledger_record_count_after` | ✅ | Slice end index. |
| `metadata` | ✅ | Forward-compatible audit fields. |

### `LivingReferencePeriodSummary` — required fields

All present on the v1.9.0 dataclass:

| Field | Present | Why the reporter needs it |
| --- | --- | --- |
| `period_id` | ✅ | Section header. |
| `as_of_date` | ✅ | Section header / chronology. |
| `corporate_signal_ids` | ✅ | Per-period corporate-report count. |
| `corporate_run_ids` | ✅ | (Bonus — not strictly required, but used for the per-period routine count.) |
| `investor_menu_ids` | ✅ | Per-period investor menu count. |
| `bank_menu_ids` | ✅ | Per-period bank menu count. |
| `investor_selection_ids` | ✅ | Set-difference computation (read selections from kernel). |
| `bank_selection_ids` | ✅ | Same. |
| `investor_review_run_ids` | ✅ | Per-period investor review-run count. |
| `bank_review_run_ids` | ✅ | Same. |
| `investor_review_signal_ids` | ✅ | Per-period investor review-note count. |
| `bank_review_signal_ids` | ✅ | Same. |
| `record_count_created` | ✅ | Per-period table rows. |
| `metadata` | ✅ | Carries `ledger_record_count_before` / `_after` so the per-period ledger slice is reachable. |

### Audit verdict — **no code change required**

The v1.9.0 schema is sufficient for the v1.9.1 reporter. Two
derivations need care; both are derivable from the existing
schema and do not justify a code change.

**Derivation 1 — investor / bank set-difference overlap on
selected refs.** Intentionally **not** materialised on the period
summary, because v1.9.0 supports `len(investors) > 1` and
`len(banks) > 1`. A single `shared_refs` tuple would require an
opinionated reduction (intersection-of-all? union-of-pairs?). The
v1.9.1 reporter will compute these at render time by reading
`kernel.attention.get_selection(selection_id).selected_refs` for
each selection in the period — the same read-only pattern v1.8.15
uses for its ledger slice walk.

**Derivation 2 — the infra prelude.** v1.9.0's
`run_living_reference_world` registers interactions, per-firm
corporate routines, per-actor attention profiles, and per-actor
review routines **before** entering the period loop. Those writes
land in `kernel.ledger.records` *between*
`result.ledger_record_count_before` and
`per_period_summaries[0].metadata["ledger_record_count_before"]`.
As a consequence:

```
infra_record_count = (
    per_period_summaries[0].metadata["ledger_record_count_before"]
    - result.ledger_record_count_before
)
sum(p.record_count_created for p in per_period_summaries)
    + infra_record_count
    == result.ledger_record_count_after - result.ledger_record_count_before
    == result.created_record_count
```

This is **expected and honest**: per-period `record_count_created`
covers only what the period itself wrote, not the one-off
registration prelude. The v1.9.1 reporter must surface the
prelude separately:

- The Markdown report's "Setup summary" section should include an
  `infra_records` line equal to `infra_record_count`.
- The "Per-period summary table" must continue to show only
  per-period activity (corporate / menu / selection / review
  counts and `record_count_created`); the totals row is
  optional and, if present, must add the `infra_records` to the
  per-period sum.
- The "Ledger event-type counts" section covers the **entire**
  slice (`record_count == ledger_record_count_after -
  ledger_record_count_before`), so the prelude's
  `interaction_added`, `routine_added`, and
  `attention_profile_added` records are counted there.

The contract test below pins the algebraic relationship so any
future v1.9.x change that breaks it (e.g., moving infra into
period 1) fails loudly here.

## Report input policy

The future `build_living_world_report(...)` should follow the same
rules as `build_endogenous_chain_report(...)` (v1.8.15):

- **Take both `kernel` and `LivingReferenceWorldResult`.** The
  result is the *structural index* (which actors, which periods,
  which menus / selections / review runs); the kernel is the
  ground truth (every record id resolves there; selected refs live
  on stored selections).
- **Read-only.** No `add_*` calls on any book; no `ledger.append`.
  Tests must assert byte equality of every kernel book (and the
  ledger length) before and after `build_living_world_report` +
  `render_living_world_markdown` + `to_dict`.
- **Re-walk the ledger slice** to compute event-type counts and
  cross-check `created_record_ids`. Mismatches become **warnings**,
  not exceptions.
- **Re-walk per-period selections** (via the kernel, not via raw
  ledger payloads) to compute set differences. Selection refs are
  authoritative on `SelectedObservationSet.selected_refs`.

## Output contract

v1.9.1 should ship:

- `LivingWorldTraceReport` — immutable dataclass with at least:
  - `report_id`, `run_id`, `period_count`, `firm_count`,
    `investor_count`, `bank_count`;
  - `start_record_index`, `end_record_index`, `record_count`;
  - `record_type_counts` — sorted tuple of `(event_type, count)`;
  - `per_period_rows` — one entry per period with
    `as_of_date`, `corporate_count`, `investor_menu_count`,
    `bank_menu_count`, `investor_selection_count`,
    `bank_selection_count`, `investor_review_count`,
    `bank_review_count`, `record_count_created`;
  - `attention_divergence_rows` — one entry per (investor or bank,
    period) with `actor_id`, `actor_kind`, `period_id`,
    `as_of_date`, `selected_ref_count`, plus the per-pair
    set-difference counts;
  - `warnings` — non-fatal validation strings;
  - `metadata` — at least `renderer`, `format_version`, the
    chain's hard-boundary statement, and the actor / firm /
    period counts echoed for audit.
- `LivingWorldTraceReport.to_dict()` — JSON-friendly projection;
  tuples become lists, mappings become dicts.
- `render_living_world_markdown(report)` — deterministic compact
  Markdown with fixed section layout (see next section).

## Markdown section layout

The renderer's section order is **fixed** so two reports built
from byte-identical results render to byte-identical Markdown.
v1.9.1's renderer must include, in this order:

1. **`# {chain_name}`** — title (default `living_reference_world`).
2. **Setup summary** — bulleted list of `firms` / `investors` /
   `banks` / `period_count` / `report_id` / chain status (if the
   v1.9.0 helper grows a chain-level status field; today the
   per-period summaries carry the only status signal).
3. **Per-period summary table** — one row per period with
   `as_of_date`, corporate report count, menu / selection /
   review counts (investor and bank columns), and
   `record_count_created`.
4. **Attention divergence summary** — one row per
   (investor, period) and one row per (bank, period) with
   `selected_ref_count`. Optional pairwise rows below for
   investor × bank within the same period showing
   `shared` / `investor_only` / `bank_only` counts.
5. **Ledger event-type counts** — sorted `(event_type, count)`
   pairs covering the chain's slice (the same seven types
   v1.8.15 expects). Sums to `record_count`.
6. **Warnings** — non-fatal validation strings, one per line.
7. **Boundaries** — a fixed paragraph restating the v1.9.0 hard
   rails:

   > **No price formation, no trading, no lending decisions, no
   > valuation behavior, no Japan calibration, no real data.**

   The text is part of the contract so any v1.9.1 PR that drops
   it is rejected.

## Determinism rules

- **Sort all collection-derived counts** before serialisation
  (`record_type_counts` sorted by event type;
  `attention_divergence_rows` sorted by `(period_id, actor_kind,
  actor_id)`).
- **Preserve insertion order** for ledger-derived ordered tuples
  (`ordered_record_ids`, `created_record_ids`).
- **No timestamps**, no random ids, no wall-clock dependencies.
- **No floating-point accumulation**. Counts are integers.
- **Markdown layout is fixed** — section titles, ordering, and
  bullet style are part of the contract.

Two `LivingWorldTraceReport`s produced from identically-seeded
fresh kernels must compare equal under `to_dict()`; their Markdown
must be byte-identical. The contract test below pins the
**input-side** half of this property; the v1.9.1 implementation
will pin the **output-side** half.

## Warning vocabulary

The reporter emits **non-fatal warning strings** rather than
crashing on cross-check failures. The v1.8.15 reporter establishes
the precedent. Suggested warning strings (the v1.9.1 reporter is
free to adapt the wording, but the *triggering* conditions are the
contract):

- `"chain_result claims end_record_index=N but kernel.ledger.records has length M"`
  — the chain result's slice extends past the kernel's current
  ledger (someone trimmed the ledger after the run returned).
- `"ledger slice length (N) does not match result.created_record_count (M)"`
  — the result's bookkeeping disagrees with the slice it claims.
- `"ledger slice object_ids do not match result.created_record_ids"`
  — the result is from a different chain than the kernel believes.
- `"expected event type missing: {event_type}"` — one of the
  seven canonical chain event types is absent from the slice
  (informative; the chain may have run partially).
- `"period {period_id}: expected {N} corporate signals, found {M}"`
  — fan-out mismatch on a specific period.
- `"period {period_id}: investor selection {selection_id} has zero refs"`
  — an actor's selection is empty in this period (anti-scenario:
  this is *degraded*, not a failure).
- `"period {period_id}: bank selection {selection_id} has zero refs"`
  — symmetric.

## Hard-boundary statement (mandatory)

Every Markdown report **must** include the following paragraph
verbatim under the `## Boundaries` heading:

> No price formation, no trading, no lending decisions, no
> valuation behavior, no Japan calibration, no real data.

This is a presentation-layer guarantee that the reporter cannot
quietly omit. The contract test below pins it on the input side
(every code path that drives the reporter has the data needed to
emit it); the v1.9.1 implementation pins it on the output side
(the renderer always emits it, and tests assert its presence in
the rendered string).

## What v1.9.1 deliberately does not do

The v1.9.1 reporter is explainability-only. It must **not**:

- add new economic behavior, new routines, new books, or new
  ledger record types;
- change `LivingReferenceWorldResult` /
  `LivingReferencePeriodSummary` schemas;
- depend on real data, web services, or non-deterministic state;
- present economic claims (no risk scores, no exposure rankings,
  no implied buy / sell / lend recommendations);
- replace the ledger as the source of truth — the report is
  convenience over the ledger.

## v1.9.1-prep success criteria

§v1.9.1-prep is complete when **all** hold:

1. The audit verdict ("no code change required") is recorded in
   this document with the schema cross-check tables.
2. `tests/test_living_reference_world_report_contract.py` pins
   the report-critical invariants as a regression gate.
3. `docs/v1_9_living_reference_world_plan.md` is updated to point
   at this document.
4. `docs/world_model.md` carries a short v1.9.1-prep note
   acknowledging the audit.
5. `pytest -q` passes (1368 prior + the contract test additions);
   `compileall` clean; `ruff check .` clean.
6. No production code changes. v1.9.0's
   `world/reference_living_world.py` is byte-identical before and
   after this milestone.
