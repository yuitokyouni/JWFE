# v1.17 Inspection Layer — Summary

This document closes the v1.17 sequence of FWE. The sequence
ships an **inspection layer** on top of the v1.16 closed
endogenous-market-intent feedback loop: a deterministic
reporting calendar, a synthetic display path, event annotations,
a causal timeline, a regime comparison report, and a static
analyst workbench. v1.17.last itself is **docs-only** on top of
the v1.17.0 → v1.17.4 code freezes.

This is **not** a market simulator, **not** a price-formation
layer, **not** a forecast layer, **not** a trading dashboard,
**not** an investment-recommendation surface, **not** a
real-data view, **not** a Japan calibration. It is a small set
of immutable display dataclasses, three deterministic helpers,
one driver that runs read-only against the kernel, one markdown
renderer, and one single-file static HTML workbench. The
inspection layer executes nothing.

## Sequence map

| Milestone   | Module / surface                                                                                                      | Adds                                                                                                                                                                                                                                                |
| ----------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| v1.17.0     | docs only                                                                                                             | UI / report / temporal display design — three time concepts kept strictly separate (`simulation_period` quarterly economic clock; `reporting_calendar` monthly / daily-like display axis; `display_series` synthetic UI series) plus the closed-set hard naming boundary (forbidden list: `market_price` / `predicted_index` / `expected_return` / `target_price` / `forecast_path` / `real_price_series` / `price_prediction` / `investment_recommendation`). |
| v1.17.1     | `world/display_timeline.py`                                                                                           | Five immutable dataclasses (`ReportingCalendar`, `ReferenceTimelineSeries`, `SyntheticDisplayPath`, `EventAnnotationRecord`, `CausalTimelineAnnotation`) + standalone `DisplayTimelineBook` + two deterministic helpers (`build_reporting_calendar`, `build_synthetic_display_path`). Quarter-end-anchored monthly stepping; three deterministic interpolation kernels (`linear` / `step` / `hold_forward`). +66 unit tests. |
| v1.17.2     | `world/display_timeline.py` + `examples/reference_world/regime_comparison_report.py`                                   | `NamedRegimePanel` + `RegimeComparisonPanel` immutable dataclasses; three deterministic helpers (`build_named_regime_panel`, `build_regime_comparison_panel`, `render_regime_comparison_markdown`); kernel-reading driver runs each v1.11.2 regime preset (constructive / mixed / constrained / tightening) on a fresh kernel and walks the read-only book interface. Closed-set `COMPARISON_AXIS_LABELS` (8 axes). +35 tests. |
| v1.17.3     | `world/display_timeline.py` (extended)                                                                                 | Two pure-function helpers — `build_event_annotations_from_closed_loop_data` (5 closed-set rules) + `build_causal_timeline_annotations_from_closed_loop_data` (3 plain-id arrow kinds, all already on the kernel records). The `market_environment_change` annotation captures the env's **full subfield labels** (credit / funding / liquidity / volatility / refi) so two regimes whose top-level histograms collide are still visibly distinguishable. +29 tests. |
| v1.17.4     | `examples/ui/fwe_workbench_mockup.html` + `examples/ui/sample_living_world_manifest.json` + `examples/ui/README.md`     | Single-file static HTML workbench redesigned around the v1.16 closed loop: 10 bottom tabs (Cover · Inputs · Overview · Timeline · Regime Compare · Attention · Market Intent · Financing · Ledger · Appendix). Run mock fixture-switching, Validate bijection check, Compare Regimes navigation, Export HTML non-destructive status. No backend, no build, no external runtime. |
| v1.17.last  | docs only                                                                                                             | This summary, §123 in `docs/world_model.md`, the v1.17.last `RELEASE_CHECKLIST.md` snapshot, the v1.17.last `performance_boundary.md` update, the v1.17.last `test_inventory.md` header note, the v1.17.last `examples/reference_world/README.md` addendum, the v1.17.last `examples/ui/README.md` cross-link, and the v1.17.last `docs/fwe_reference_demo_design.md` headline note. |

## What v1.17 ships — the inspection surface

The final inspection surface lets a reader inspect, in finite
read steps, the v1.16 closed loop's behaviour on any
deterministic regime preset:

```
period N
  ActorAttentionState.focus_labels                    (v1.12.8 ∪ v1.16.3)
        │
        ▼
  InvestorMarketIntentRecord                          (v1.15.2 — directed by
                                                        the v1.16.1 classifier
                                                        rewired in v1.16.2)
        │
        ▼
  AggregatedMarketInterestRecord                      (v1.15.3)
        │
        ▼
  IndicativeMarketPressureRecord                      (v1.15.4)
        │
        ▼
  CapitalStructureReviewCandidate / CorporateFinancingPathRecord
                                                       (v1.14.3 / v1.14.4
                                                        + v1.15.6 citations)
        │
        ▼
period N+1
  ActorAttentionState.focus_labels widened by          (v1.16.3)
   the deterministic mapping over the period-N pressure /
   path records, then passed through the v1.12.9 budget /
   decay / saturation pipeline
```

A reader can answer the five inspection questions defined at
v1.17.0 by following plain-id citations from the rendered
output:

1. **What happened?** — the **Overview** tab's compact KPI
   cards plus the **Timeline** tab's `SyntheticDisplayPath` +
   event annotations.
2. **Which actor saw what?** — the **Attention** tab's diff
   strip (Previous focus / Trigger / New focus / Dropped /
   Reinforced / Why) plus the per-actor cards.
3. **Which evidence changed?** — the **Market Intent** tab's
   per-investor classifier rule_id + evidence summary.
4. **Which intent / review / pressure changed?** — the
   **Market Intent** + **Financing** tabs, with citations to
   the prior-period record that drove the change.
5. **What changed in the next period?** — the **Regime
   Compare** tab's subfield differentiator row plus the
   per-regime "Events & causal trace" block (v1.17.3) under
   the comparison table.

### v1.17.1 — Temporal Display Series

- `world/display_timeline.py` is a **standalone** module — not
  registered with `WorldKernel`. The `DisplayTimelineBook`
  carries no `ledger` or `clock` attribute, never writes to the
  ledger, and never mutates any source-of-truth book. A
  trip-wire test pins that exercising the v1.17.1 helpers on a
  default-fixture kernel leaves `living_world_digest`
  byte-identical and `kernel.prices.snapshot()` byte-equal.
- Five immutable frozen dataclasses with strict closed-set
  validation: `ReportingCalendar` (`FREQUENCY_LABELS` =
  `{quarterly, monthly, daily_like, unknown}`),
  `ReferenceTimelineSeries`, `SyntheticDisplayPath`
  (`INTERPOLATION_LABELS` = `{step, linear, hold_forward,
  event_weighted, unknown}`), `EventAnnotationRecord`
  (`ANNOTATION_TYPE_LABELS` of seven kinds and `SEVERITY_LABELS`
  of four), and `CausalTimelineAnnotation`.
- Two deterministic helpers — `build_reporting_calendar(...)`
  with a quarter-end-anchored stepping rule (no day-of-month
  drift through short months) and
  `build_synthetic_display_path(...)` with three interpolation
  kernels (`linear` / `step` / `hold_forward`;
  `event_weighted` and `unknown` defer to v1.17.3 and fall back
  to `hold_forward`). Anchors are sorted by date so the same
  pairs in any order produce the same path.
- `display_values` are synthetic ordinals in `[0.0, 1.0]` —
  **never** prices, returns, NAV, benchmark levels, or forecasts.
  Tests pin the absence of forbidden display-name field /
  payload keys.

### v1.17.2 — Regime Comparison Report

- Two new immutable dataclasses (`NamedRegimePanel`,
  `RegimeComparisonPanel`) plus three deterministic helpers
  (`build_named_regime_panel(...)`, `build_regime_comparison_panel(...)`,
  `render_regime_comparison_markdown(...)`).
- Closed-set `COMPARISON_AXIS_LABELS` — 8 axes: `attention_focus`
  / `market_intent_direction` / `aggregated_market_interest` /
  `indicative_market_pressure` / `financing_path_constraint` /
  `financing_path_coherence` / `unresolved_refs` /
  `record_count_digest`.
- New `examples/reference_world/regime_comparison_report.py`
  driver runs each v1.11.2 regime preset on a fresh kernel and
  walks the read-only book interface
  (`list_attention_states` / `list_intents` / `list_records` /
  `list_paths`) to extract closed-loop label histograms. The
  driver is read-only against the kernel — a test pins
  re-extraction is byte-identical and `kernel.prices.snapshot()`
  is byte-equal pre/post.
- Markdown renderer outputs a deterministic side-by-side
  `## Regime comparison — <panel_id>` table with one column per
  regime preset, sorted-key histograms in each cell, and a
  closing `_Synthetic display only — counts of the labels …
  Not a forecast, not a price, not a recommendation._`
  disclaimer.

### v1.17.3 — Event Annotation + Causal Timeline Inspector

- Two new pure-function helpers in `world/display_timeline.py`
  that read **anonymous record-like inputs** (duck-typed via
  `getattr`; no source-of-truth book imports) and emit
  deterministic `EventAnnotationRecord` /
  `CausalTimelineAnnotation` tuples using a closed-set rule
  table. Five event kinds (Rule 1: env =
  `selective_or_constrained` → `market_environment_change`
  with **full subfield labels** in metadata + `annotation_label`;
  Rule 2: pressure constrained / closed →
  `market_pressure_change`; Rule 3: financing path
  `market_access_constraint` → `financing_constraint`; Rule 4:
  financing path `conflicting_evidence` → `causal_checkpoint`;
  Rule 5: attention focus contains v1.16.3 fresh labels →
  `attention_shift`). Three plain-id arrow kinds (env →
  pressure; pressure → financing; prior pressure / path →
  next-period attention).
- `NamedRegimePanel` extended with `event_annotations` and
  `causal_annotations` tuple fields. The markdown renderer adds
  three new comparison rows (Event annotations by type / Top
  events date · type · source / Causal arrows by kind) and a
  per-regime "Events & causal trace" block with up to 6 top
  events and 6 top causal arrows formatted as bullet lists with
  monospace ids.
- The **`market_environment_change`** annotation embeds the
  env's full closed-set subfield labels (`credit_regime` /
  `funding_regime` / `liquidity_regime` / `volatility_regime` /
  `refinancing_window`) in both `metadata` and the human-
  readable `annotation_label` so two regimes whose
  `overall_market_access_label` collide
  (`constrained` vs `tightening` both at
  `selective_or_constrained`) are still distinguishable —
  `credit=stressed, funding=normal, refi=open` (constrained)
  vs `credit=tightening, funding=expensive, refi=selective`
  (tightening). A test pins that distinction in the default
  fixture.

### v1.17.4 — Static Workbench Redesign

- The single-file static HTML workbench (single open under
  `file://`, no backend, no build, no external runtime) is
  reorganised around the v1.16 closed loop:

  ```
  Cover · Inputs · Overview · Timeline · Regime Compare ·
  Attention · Market Intent · Financing · Ledger · Appendix
  ```

- New tabs: **Overview** (small SVG closed-loop diagram + 6
  compact KPI cards), **Timeline** (renamed from Outputs;
  Synthetic Display Path + KPI row + causal table),
  **Regime Compare** (the v1.17.2 / v1.17.3 panel promoted to
  its own tab with the subfield differentiator row), **Market
  Intent** (3 tables: investor intent + classifier rule_id /
  aggregated interest / indicative pressure), **Financing** (3
  tables: path summary / funding option candidates / capital
  structure review with v1.15.6 pressure citation).
- Reshaped tabs: **Attention** gains a v1.17.4 diff strip at
  the top (Previous focus / Trigger / New focus / Dropped /
  Reinforced / Why) so the reader sees *what changed* before
  scrolling into the per-actor cards. **Inputs** keeps the
  configuration surface and folds the Strategy / behavior
  modules table into a default-collapsed `<details>`.
- Top-ribbon buttons (deterministic, no network, no kernel
  mutation):
  - **Load sample run** — parses the inline JSON manifest and
    fills the data-bound tables.
  - **Run mock** — reads the active regime pill and updates
    Overview KPIs / Timeline header / Attention diff strip /
    digest-short from a static `SAMPLE_RUNS` fixture. The
    Python engine is not invoked.
  - **Validate** — runs a strict in-page sanity check on the
    bottom-tab ↔ sheet-article bijection (10 of each, no
    orphans, no duplicates, all required ids present, ledger
    records table present, regime-compare card present). Status
    updates to `validation passed · static UI` or names the
    first failure.
  - **Compare Regimes** — activates the dedicated Regime
    Compare tab and flashes the comparison card.
  - **Export HTML** — non-destructive. Status updates to
    `export not implemented in static prototype · use browser
    Save Page / Print`.
- A constant `static fixture only · no backend execution`
  sub-status is permanently visible in the top-ribbon stack so
  the no-engine-execution discipline is on screen at a glance.

A subsequent audit pass (post v1.17.4) removed four orphan
unreachable `<article>` blocks (`sheet-market`, `sheet-firms`,
`sheet-investors`, `sheet-banks`) so the workbench has an exact
**1:1 mapping**: 10 bottom tabs ↔ 10 sheet articles, no orphans,
no duplicates. The strengthened `Validate` button enforces that
bijection at runtime.

## What v1.17 explicitly is not

- **Not a market simulator.** The display layer renders records
  the v1.16 closed loop already emits; it invents no new
  economic edge.
- **Not a higher-frequency simulation.** The
  `reporting_calendar` and `display_series` are display-only
  axes. The `simulation_period` is the sole economic clock
  (quarterly).
- **Not price formation.** No `market_price`, no
  `predicted_index`, no `predicted_path`, no `expected_return`,
  no `target_price`, no `forecast_path`, no `forecast_index`,
  no `real_price_series`, no `actual_price`, no `quoted_price`,
  no `last_trade`, no `nav`, no `index_value`, no
  `benchmark_value`, no `valuation_target`. These names are
  pinned by the v1.17.0 `FORBIDDEN_DISPLAY_NAMES` frozenset and
  scanned for absence by tests.
- **Not trading.** No order submission, no order book, no
  matching, no execution, no clearing, no settlement, no
  quote dissemination, no bid / ask, no `PriceBook` mutation.
- **Not investment advice.** No `recommendation`, no
  `investment_advice`, no `price_prediction`, no
  `investment_recommendation`. These appear in the workbench
  HTML only inside negation / boundary / forbidden-list
  contexts (e.g. the JS comment that lists them as
  "deliberately absent", or `Probability claims · OFF` rows).
- **Not real data.** No real exchange / broker / index /
  regulator / issuer identifier appears in any v1.17 module,
  fixture, test, or rendered view. Every numeric value is a
  synthetic ordinal in `[0.0, 1.0]` or a closed-set label.
- **Not a Japan calibration.** All venue ids, security ids,
  and labels are jurisdiction-neutral and synthetic. Real-
  venue calibration (JPX / TSE / OSE / NEX / etc.) remains
  private JFWE territory (v2 / v3 only).
- **Not LLM execution.** No model, no prompt, no API call, no
  generated content. Every label, count, and rendering is
  deterministic from the cited records.
- **Not a learned model.** No training data, no gradient, no
  fitting, no cross-validation, no backtest. Every rule is a
  Boolean combination of closed-set / bounded-numeric inputs.

## Performance boundary at v1.17.last

- **Per-period record count (default fixture):** **108**
  (period 0) / **110** (periods 1+). **Unchanged** from
  v1.16.last. v1.17.x added zero records to the per-period
  sweep — the display layer runs only when the report / UI
  asks for it, and the regime-comparison driver runs each
  preset on its own freshly-seeded kernel.
- **Per-run window (default fixture):** **`[432, 480]`**.
  Unchanged.
- **Default 4-period sweep total:** **460 records**. Unchanged.
- **Integration-test `living_world_digest`:**
  **`f93bdf3f4203c20d4a58e956160b0bb1004dcdecf0648a92cc961401b705897c`**.
  Unchanged from v1.16.last across all v1.17 milestones —
  v1.17.0 was docs-only, v1.17.1 / v1.17.2 / v1.17.3 are
  display modules and helpers that never write to the kernel,
  and v1.17.4 was a static-HTML edit. Trip-wire tests at
  v1.17.1 (`test_default_living_world_run_does_not_create_display_records`)
  and v1.17.2 (`test_extract_regime_run_snapshot_does_not_mutate_kernel`)
  pin that the digest does not move when the helpers are
  exercised.
- **Test count:** **4165 / 4165** passing. Up from 4033 / 4033
  at v1.16.last (+132 across v1.17.1 / v1.17.2 / v1.17.3).
  v1.17.0 / v1.17.4 are docs / static-HTML only and add no
  pytest tests; the in-page Validate button enforces the
  workbench-side invariants instead.

## UI status at v1.17.last

- **Type:** single-file static HTML prototype.
- **File:** `examples/ui/fwe_workbench_mockup.html`.
- **Backend:** none.
- **Build tools:** none.
- **External runtime:** none.
- **Network I/O:** none. The inline JSON manifest and the
  `SAMPLE_RUNS` fixture make every interaction work under
  `file://` without `fetch()`.
- **Run mock:** fixture-switching only — the Python engine is
  **not** invoked. Same regime selection → byte-identical UI
  state. Status reads `mock UI run · <regime> · static fixture
  · no engine execution`.
- **Compare Regimes:** static / display-report navigation —
  activates the Regime Compare tab and flashes the
  comparison card. The displayed digests, histograms, and
  causal arrows come from the inline `SAMPLE_RUNS` fixture
  and the inline JSON manifest, **not** from a live engine
  run.
- **Validate:** strict in-page bijection check (tab count ==
  sheet count; every tab points to a real sheet; every sheet
  has a tab; no duplicates; all required ids present; ledger
  records present; regime-compare card present). Status
  updates to `validation passed · static UI` or names the
  first failure.
- **Export HTML:** non-destructive. Updates the status strip
  to `export not implemented in static prototype · use
  browser Save Page / Print`. There is no file-system API.
- **Bottom-tab ↔ sheet article mapping:** 10 ↔ 10 bijection,
  enforced at runtime by Validate.
- **Sample fixture status:** the embedded digest, per-period
  record count, and per-run window are clearly tagged
  `digest_kind: sample_fixture` / `fixture_kind:
  sample_fixture` / `fixture_note: …` in the manifest. The
  workbench renders them with a `(sample fixture)` annotation
  next to each value.

## Discipline preserved bit-for-bit

Every v1.9.x / v1.10.x / v1.11.x / v1.12.x / v1.13.x / v1.14.x /
v1.15.x / v1.16.x boundary anti-claim is preserved unchanged at
v1.17.last:

- No real data, no Japan calibration, no LLM-agent execution,
  no behaviour probability, no learned model.
- No price formation, no trading, no portfolio allocation, no
  investment advice, no rating.
- No lending decision, no covenant enforcement, no contract
  mutation, no constraint mutation, no default declaration.
- No financing execution, no loan approval, no securities
  issuance, no underwriting, no syndication, no allocation, no
  pricing.
- The v1.12.6 watch-label classifier is unchanged.
- The v1.12.9 attention-budget discipline is preserved
  bit-for-bit; v1.16.3 fresh focus passes through the same
  decay / saturation pipeline.
- The v1.13.5 settlement / interbank-liquidity substrate is
  unchanged.
- The v1.14 corporate-financing record set is unchanged in
  vocabulary; v1.15.6 added two citation slots and v1.16.x
  added zero new vocabulary.
- The v1.15 `SAFE_INTENT_LABELS` vocabulary is unchanged.
- The v1.16.1 classifier output is strictly in
  `INTENT_DIRECTION_LABELS` (= `SAFE_INTENT_LABELS ∪
  {"unknown"}`); the forbidden trade-instruction verbs are
  disjoint by construction.
- The v1.16.2 living-world `intent_direction_label` is
  produced by the v1.16.1 classifier — never by an index
  rotation.
- The v1.16.3 `ActorAttentionStateRecord.focus_labels` widening
  reads only cited prior-period pressure / path ids — never a
  global scan.
- The `PriceBook` is byte-equal across the full default sweep
  — pinned by tests at v1.15.5, v1.15.6, v1.16.2, v1.16.3,
  v1.17.1, and v1.17.2.
- The v1.9.last public-prototype freeze, the v1.12.last
  attention-loop freeze, the v1.13.last settlement-substrate
  freeze, the v1.14.last corporate-financing-intent freeze,
  the v1.15.last securities-market-intent freeze, the v1.16.last
  endogenous-market-intent feedback freeze, and the v1.8.0
  public release remain untouched.

## Known limitations

The v1.17 layer is a **rendering of the v1.16 closed loop**.
Specific limitations a reader should know about:

1. **No live engine execution from the UI.** The static
   workbench is a post-hoc inspector. The "Run mock" button is
   fixture switching only; running the engine still requires
   `python -m examples.reference_world.run_living_reference_world`
   on the command line.
2. **Sample fixture in the workbench is older.** The embedded
   digest / per-period count in the workbench manifest reflects
   an earlier engine snapshot and is tagged accordingly. The
   live v1.16.last runtime emits 108 / 110 records per period
   and a `[432, 480]` per-run window; the inline fixture's
   83 / `[324, 372]` numbers are a pre-v1.15.x snapshot kept
   for layout fidelity.
3. **Regime-comparison fixtures collide on coarse labels.**
   The v1.11.2 default fixture maps `constrained` and
   `tightening` to the same coarse closed-loop labels
   (`risk_reduction_review 24` etc.). v1.17.3's environment-
   subfield enrichment is the explicit remediation; the
   subfield row + per-regime causal trace block surface the
   real differences.
4. **No real-time / event-driven view.** The workbench renders
   a quarterly run on a monthly / daily-like display axis —
   the daily-like granularity is a reading aid, not a
   higher-frequency simulation.
5. **Inspection layer, not interpretation.** v1.17 makes the
   loop's causal structure operationally legible to a human
   reader; it does **not** interpret the labels, infer real-
   world meaning, or draw any conclusion about the modelled
   behaviour. Every label remains a closed-set ordinal over a
   synthetic vocabulary.

## What v1.18+ does next

v1.17.last freezes the public-FWE inspection layer. The next
roadmap candidates remain:

- **v1.18 — scenario library / exogenous event templates.** A
  small library of named, deterministic, reproducible scenario
  templates (e.g. `tightening_credit`, `equity_correction`,
  `liquidity_event`, `dialogue_breakdown`) that compose with
  the existing `--regime` presets and the v1.17.2
  `RegimeComparisonPanel`. Still no real-data, no calibration,
  no execution.
- **v1.19 — local run bridge / report export (conditional).**
  If UI execution becomes necessary, a small CLI-driven
  bridge that writes a regime-comparison panel + causal-trace
  report to disk (markdown / JSON), which the static workbench
  can then `Load sample run` against. Still no backend, no
  build, no network.
- **v2.0 — Japan public calibration in private JFWE.** Real-
  venue / real-issuer / real-regulator calibration moves to
  private JFWE only. Public FWE remains jurisdiction-neutral
  and synthetic.
- **Future price formation remains gated.** Out of scope until
  the v1.16 / v1.17 surface is operationally legible to a
  reviewer who has not read this codebase. The v1.17 layer is
  the prerequisite for ever revisiting that gate; adding price
  formation on top of an opaque layer would defeat the
  auditability goal of the v1.16 freeze.

The v1.17 chain stays display-only and label-only forever.
Future milestones may *cite* the v1.17 display objects (plain-id
cross-references, additional rendering kinds), but they may
**never** mutate the v1.17 vocabulary, replace the deterministic
helpers with stochastic ones, or introduce execution paths on
top of the inspection layer.
