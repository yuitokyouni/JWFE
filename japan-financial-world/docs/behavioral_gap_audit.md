# Behavioral Gap Audit

> **v1.9.3.** Companion to
> [`model_mechanism_inventory.md`](model_mechanism_inventory.md).
> The inventory classifies every component; this document names
> the gap between *recordable infrastructure* and *economic
> behavior*, ranks the missing mechanisms, and recommends the
> next modeling milestone path.
>
> Like the inventory, this doc is part of the v1.9.3 audit and
> ships before any v1.9.last polish so the project does not
> overclaim.

## Verdict

The current system is an **auditable routine-driven
information-flow substrate**. It is *not yet*:

- a price-formation model;
- a credit model;
- a valuation model;
- a macro model;
- a firm-financial dynamics model;
- a forecasting model;
- a portfolio / allocation model.

The substrate is healthy. The mechanism layer is not yet present.
v1.9.4 onward starts to populate it.

## Highest-value missing mechanisms

The mechanisms below are listed in *value-to-the-substrate*
order, not in implementation difficulty order. Each names the
existing v1.8 / v1.9 plumbing it would hook into.

| Missing mechanism | What it would do | Plumbing it would hook into | Visible ledger output |
| --- | --- | --- | --- |
| **Firm financial update** | Synthetic update of `(margin_pressure, liquidity_pressure, debt_pressure)` indicators from corporate-reporting routines + world-variable observations + per-firm exposures. | `corporate_quarterly_reporting` + `WorldVariableBook` + `ExposureBook` (per-firm) + `SignalBook`. | A new `firm_financial_state` signal per firm per period. |
| **Input-cost / margin-pressure propagation** | Material / energy / logistics variables propagate into per-firm `margin_pressure`. | Variable-group filters on `WorldVariableBook` + per-firm `ExposureBook` rows. | Same firm-financial signal, with provenance refs into the variables. |
| **Valuation refresh** | Investor / bank review's selected refs produce a `ValuationRecord` claim per (subject, observer). | `ValuationBook` (already shipped at v1.1) + `SelectedObservationSet` + `valuation_mechanism`. | A `ValuationRecord` per claim + a `ValuationGap` against the seed price. |
| **Bank credit review** | Bank review's selected refs produce a credit-review note + a constraint-pressure delta. | `bank_review` + `ConstraintBook` (existing) + `credit_review_mechanism`. | A `bank_credit_review` signal + constraint pressure deltas as proposed records. |
| **Investor intent** | Investor review's selected refs produce a non-binding intent record (NOT an order, NOT a trade). | `investor_review` + a new `investor_intent` record family (small additive book). | An `investor_intent` signal naming the subject and direction label only. |
| **Constraint / covenant response** | A separate mechanism that reacts to a covenant trip *as data*, producing a `constraint_evaluated` record. | `ConstraintBook` + `ConstraintEvaluator`. | Already partially shipped at v0.x; a v1.9.x mechanism would attach for declarative responses. |
| **Macro / world-variable process** | Step a process spec from `ExternalProcessBook` and emit a new observation. | `ExternalProcessBook` (existing) + `WorldVariableBook` (existing) + `macro_process_mechanism`. | New `VariableObservation` records on the periodic schedule. |
| **Market price formation** | Price formation, order matching, market microstructure. | `PriceBook` (existing) + a `market_mechanism` adapter. | A `PRICE_UPDATED` per asset per tick. |

## Suitability ranking for the next modeling upgrade

We rank candidates against five filters:

1. **Reuses existing v1.8 / v1.9 infrastructure?** Avoids new
   substrate work.
2. **Synthetic and jurisdiction-neutral?** Stays inside the
   v1.x rails.
3. **Does not require real data?** Avoids pulling v2 (Japan
   public calibration) forward.
4. **Produces visible ledger traces?** A v1.9.x mechanism
   should appear in the report after wiring.
5. **Does not immediately require price formation?** Price
   formation is v2+; everything earlier should compose without
   it.

| Mechanism | (1) Reuses infra | (2) Synthetic | (3) No real data | (4) Visible | (5) Avoids price formation | Score |
| --- | --- | --- | --- | --- | --- | --- |
| Firm financial update | ✅ | ✅ | ✅ | ✅ | ✅ | **5/5** |
| Input-cost / margin-pressure propagation | ✅ | ✅ | ✅ | ✅ | ✅ | **5/5** |
| Valuation refresh | ✅ (v1.1) | ✅ | ✅ | ✅ | ✅ | **5/5** |
| Bank credit review | ✅ | ✅ | ✅ | ✅ | ✅ | **5/5** |
| Investor intent | ✅ | ✅ | ✅ | ✅ | ✅ | **5/5** |
| Macro process | ✅ (v1.4 stored only) | ✅ | ✅ | ✅ | ✅ | **5/5** but introduces autonomy v1.x has avoided. |
| Market price formation | ❌ (would need substrate work) | ✅ | ✅ | ✅ | ❌ — *is* price formation | **3/5** — out of scope for v1.x. |

## Recommended next modeling options

Each option is a self-contained v1.9.x sub-release. The contract
is the same in every case: ship a `MechanismSpec` + an adapter
(`world/mechanisms.py`'s contract) + a small test suite + a
sentence in the trace report. No substrate change.

### Option A — Firm Financial State Update

`corporate_quarterly_reporting`'s synthetic payload is currently
hand-coded round numbers. A v1.9.4 `firm_financial_mechanism`
would compute `(margin_pressure, liquidity_pressure,
debt_pressure)` from the firm's exposures and the visible world
variables on the as-of date.

- *Inputs*: `firm_id`, `as_of_date`, exposures filtered to firm,
  visible variable observations.
- *Outputs*: a `firm_financial_state` `InformationSignal` plus
  the existing `corporate_quarterly_report` signal.
- *Anti-scope*: no balance-sheet update; no cash-flow projection;
  no real numbers; no Japan calibration.

### Option B — Valuation Refresh Lite

Investor / bank review's selected refs become inputs to a
`valuation_mechanism` that emits one `ValuationRecord` per
(observer, subject). The existing v1.1 `ValuationComparator`
computes `ValuationGap` against the seed price.

- *Inputs*: an investor or bank `SelectedObservationSet`,
  plus the firm's currently-recorded `firm_financial_state`
  (if Option A has shipped) or the synthetic payload otherwise.
- *Outputs*: a `ValuationRecord` proposal + an automatic
  `ValuationGap` through the existing comparator.
- *Anti-scope*: no buy / sell / hold note; no portfolio impact;
  no recommendation framing.

### Option C — Bank Credit Review Lite

Bank review's selected refs feed a `credit_review_mechanism`
that produces a `bank_credit_review` signal + a constraint-
pressure delta record.

- *Inputs*: a bank `SelectedObservationSet` + the bank's
  exposures.
- *Outputs*: a `bank_credit_review` signal + a constraint
  pressure delta (proposed only; the caller decides whether to
  commit it to `ConstraintBook`).
- *Anti-scope*: no lending decision; no covenant trip; no
  default detection.

### Option D — Input Cost Propagation

A focused subset of Option A: only the `material` /
`energy_power` / `logistics` variable groups propagate into
`margin_pressure`. Smaller surface; same shape; useful as a
stepping stone if Option A as a whole is too large for a single
sub-release.

### Option E — Investor Intent Layer

Investor review's selected refs produce a non-binding
`investor_intent` record. Crucially this is **not** an order,
**not** a trade, and **not** a portfolio action — it is a
recordable opinion that a future v2+ market mechanism could read.

- *Inputs*: an investor `SelectedObservationSet` + the
  investor's exposures.
- *Outputs*: a small `investor_intent` record (subject_id,
  direction_label ∈ {"increase", "neutral", "decrease",
  "no_view"}, confidence).
- *Anti-scope*: no order; no trade; no allocation; no impact
  on `OwnershipBook`; the record is *attention*, not
  *decision*.

## Recommended next path

The recommended path **assumes the v1.9.2 replay / manifest
slot is already filled** (it is — see `world_model.md` §62).
The recommended path the user originally drafted listed
"Replay / Manifest" at v1.9.6; in fact that work shipped at
v1.9.2. The path therefore renumbers:

| Milestone | Scope | Status |
| --- | --- | --- |
| v1.9.0 | Living Reference World Demo. | Shipped (§59) |
| v1.9.1-prep | Report contract audit. | Shipped (§60) |
| v1.9.1 | Living World Trace Report. | Shipped (§61) |
| v1.9.2 | Living World Replay / Manifest / Digest. | Shipped (§62) |
| **v1.9.3** | **Model Mechanism Inventory + Behavioral Gap Audit + Mechanism Interface.** | **This milestone (§63).** |
| v1.9.4 | Synthetic Firm Financial Update / Margin Pressure (Option A or D). | Next |
| v1.9.5 | Valuation Refresh Lite (Option B). | After v1.9.4 |
| v1.9.6 | Bank Credit Review Lite (Option C). | After v1.9.5 |
| v1.9.7 | Performance Boundary (sparse-iteration / complexity-budget hardening). | After v1.9.6 |
| v1.9.last | First lightweight public prototype. | After v1.9.7 |

If a v1.9.x change ever requires going outside this list, the
two anti-scope rails still apply:

- **No price formation in v1.x.** That is v2+.
- **No real data in v1.x.** That is v2+.

## Anti-overclaiming language for the public prototype

Every v1.9.x sub-release and the v1.9.last freeze should say,
verbatim or in spirit:

> FWE / JFWE is research software. The current public prototype
> is **not a forecasting model**, **not investment advice**,
> and **not calibrated** to any real economy or institution.
> What it currently demonstrates is **auditable endogenous
> information and review flows** across a small synthetic world,
> with deterministic reports, replay-determinism manifests, and
> explicit no-economic-behavior boundaries. **Financial decision
> behavior is intentionally limited.** Mechanism layers
> (firm-financial, valuation, credit-review, investor-intent,
> market) attach to the substrate one milestone at a time and
> are documented in `docs/model_mechanism_inventory.md` and
> `docs/behavioral_gap_audit.md`.

The README already uses this framing in spirit; v1.9.3 tightens
the wording in two places (the opening paragraph and the
"Current capability" section) to match.

## How to use this audit

- **For v1.9.4 planning:** pick Option A or D from the
  "Recommended next modeling options" section above; ship it
  as a `MechanismAdapter` in `world/mechanisms_*.py`; pin the
  spec, run record, and read-only invariant in tests.
- **For public-facing communication:** quote the anti-overclaiming
  paragraph above; do not promise anything beyond what
  the inventory says is shipped.
- **For internal milestone framing:** every v1.9.x sub-release
  must declare which mechanism family it shipped and which
  ledger record types its outputs flow through. The
  `MechanismRunRecord` shape gives a uniform place to record
  this.

## Read this with

- [`model_mechanism_inventory.md`](model_mechanism_inventory.md) — the per-component classification.
- [`world_model.md`](world_model.md) §63 — the v1.9.3 audit section.
- [`v1_9_living_reference_world_plan.md`](v1_9_living_reference_world_plan.md) — the renumbered v1.9 path.
- [`public_prototype_plan.md`](public_prototype_plan.md) — the v1.9.last public-prototype gates.
