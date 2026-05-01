# Expected Ledger Story

This document narrates what `run_reference_loop.py` produces, step by
step, so a reader can compare the live ledger output against the
intended causal chain.

The narrative has two parts: the **setup** (registry / seed records
that the demo creates before the loop starts) and the **loop**
(the seven steps of `ReferenceLoopRunner` + the next-tick delivery).

The script returns the populated kernel; `kernel.ledger.records` is
the canonical trace.

## Part A — Setup

Before any step of the reference loop fires, the demo registers
entities and seeds two pieces of supporting state.

1. **Entity registration.** Every entry in `entities.yaml` is added
   to its corresponding kernel space. Each registration emits one
   `object_registered` ledger record (registry side) and one
   identity-level state record (`firm_state_added`, `bank_state_added`,
   `investor_state_added`, `market_state_added`,
   `property_market_state_added`, `information_source_state_added`,
   `policy_authority_state_added`, `external_factor_state_added`).

2. **External process spec.** `entities.yaml` declares two factor
   processes (`process:reference_macro_index` and
   `process:reference_fx_pair`); the script writes the macro
   process to `ExternalProcessBook` and emits
   `external_process_added`. (The FX process is declared in the
   catalog for completeness but is not used by the loop.)

3. **Institution profile.** The central-bank institution profile
   (`institution:reference_central_bank`) is added to
   `InstitutionBook`, emitting `institution_profile_added`. v1.3
   distinguishes `PolicyAuthorityState` (v0 identity-level state)
   from `InstitutionProfile` (v1.3 institution book record); both
   exist in the demo.

4. **Seed price.** The valued firm
   (`firm:reference_manufacturer_a`) has its latest price set to
   `95.0` on `2026-01-01`. This emits `price_updated`. The number
   95 is illustrative; it is chosen so that step-3 valuation of
   `110.0` produces a positive gap of `+15` (about `+15.8%`).

5. **Seed ownership.** Two investors hold positions in the valued
   firm and one holds a position in `firm:reference_manufacturer_b`.
   Each call emits `ownership_position_added`. The ownership is
   static — no buying or selling happens in the demo. The positions
   exist solely to show that the demo world has multi-investor
   populations.

After setup, `kernel.ledger.records` already contains dozens of
records. The seven loop records that follow are appended on top of
this baseline.

## Part B — The seven-step reference loop

Each step has:
- a one-line summary,
- the ledger record type emitted,
- the cross-references that link the record to its predecessors.

### Step 1: external observation

- **What:** Record an `ExternalFactorObservation` for
  `factor:reference_macro_index` on `2026-01-01`, stamped with
  `phase_id="overnight"`.
- **Mechanism:** `runner.record_external_observation(...)` →
  `kernel.external_processes.create_constant_observation(...)`.
- **Ledger record:** `external_observation_added`. The record's
  `object_id` is the observation id; its `source` is the source id
  passed to the runner; its `payload` carries `factor_id`, `value`,
  `phase_id`.
- **Cross-reference forward to step 2:** The signal in step 2
  references this observation via `related_ids`.

### Step 2: signal from observation

- **What:** Emit an `InformationSignal` (`signal:reference_macro_observed_001`)
  with `signal_type="macro_indicator"`,
  `source_id="source:reference_news_outlet"`, and `subject_id`
  pointing at the factor.
- **Mechanism:** `runner.emit_signal_from_observation(...)` →
  `kernel.signals.add_signal(signal)`. The signal's `payload`
  contains `observation_id`, `factor_id`, `value`. `related_ids`
  contains `(observation_id,)`.
- **Ledger record:** `signal_added`.
- **Cross-reference back:** `related_ids` → step-1 observation id.
- **Cross-reference forward to step 3:** The valuation references
  this signal via `related_ids` and `inputs["signal_id"]`.

### Step 3: valuation referencing the signal

- **What:** A reference research desk (`valuer:reference_research_desk`)
  records a DCF valuation of `firm:reference_manufacturer_a` worth
  `110.0` `reference_unit`s as of `2026-01-01`, with confidence
  `0.7`. The valuation lists the step-2 signal as its input.
- **Mechanism:** `runner.record_valuation_from_signal(...)` →
  `kernel.valuations.add_valuation(valuation)`. `related_ids` =
  `(signal_id,)`. `inputs["signal_id"]` = signal id.
- **Ledger record:** `valuation_added`. Its `record_id` becomes a
  parent of the step-4 and step-5 records.

### Step 4: comparator → ValuationGap

- **What:** Compare the step-3 valuation to the latest priced
  observation of `firm:reference_manufacturer_a` (set during
  Setup §4 to `95.0`). The comparator computes `absolute_gap = 15.0`
  and `relative_gap ≈ 15 / 95 ≈ 0.158`.
- **Mechanism:** `runner.compare_valuation_to_price(valuation_id)`
  → `kernel.valuation_comparator.compare_to_latest_price(...)`. The
  `ValuationGap` is **not** stored — it is returned for use by
  step 5. The comparison itself is recorded.
- **Ledger record:** `valuation_compared`. Its `parent_record_ids`
  contain the step-3 `valuation_added` record id.
- **Cross-reference forward to step 5:** The institutional action
  in step 5 reads both the valuation and the gap; its
  `parent_record_ids` will include both step-3 and step-4 record
  ids.

### Step 5: institutional action

- **What:** The reference central bank
  (`institution:reference_central_bank`) records an
  `InstitutionalActionRecord` of type
  `"reference_macro_statement"` on `2026-01-01`,
  stamped with `phase_id="post_close"`. The action declares:
  - `input_refs = (valuation_id,)` — what it read,
  - `output_refs = (signal:reference_followup_001,)` — what its
    writer plans to emit (step 6),
  - `target_ids = (firm:reference_manufacturer_a,)` — what it is
    about,
  - `parent_record_ids` = (`valuation_added`, `valuation_compared`)
    record ids — the ledger lineage.
- **Mechanism:** `runner.record_institutional_action(...)` →
  `kernel.institutions.add_action_record(action)`.
- **Ledger record:** `institution_action_recorded`.
- **Important:** The action does not mutate any other book.
  Per v1.3's four-property action contract, side effects (the
  follow-up signal in step 6, the event publication in step 7)
  are *referenced* by this action but are produced by the
  runner's later steps.

### Step 6: follow-up signal

- **What:** A second `InformationSignal` (`signal:reference_followup_001`)
  is emitted with `source_id = institution:reference_central_bank`,
  `subject_id = firm:reference_manufacturer_a`, and `related_ids =
  (action_id,)`. `payload["action_id"]` carries the action id.
- **Mechanism:** `runner.emit_signal_from_action(...)` →
  `kernel.signals.add_signal(signal)`.
- **Ledger record:** `signal_added`. Note this is the **second**
  `signal_added` record produced by the loop (the first was step 2).
- **Cross-reference closure:** The step-5 action's `output_refs`
  already named this signal id. So step 5's *plan* and step 6's
  *write* match.

### Step 7: WorldEvent published; next-tick delivery

- **What:** A `WorldEvent` (`event:reference_announcement_001`) is
  published with `source_space = "information"` and
  `target_spaces = ("banking", "investors")`. `payload =
  {"signal_id": signal_id_followup}`. `related_ids =
  (signal_id_followup,)`.
- **Mechanism:** `runner.publish_signal_event(...)` →
  `kernel.event_bus.publish(event)`. The runner also writes
  `event_published` to the ledger explicitly (mirroring what
  `BaseSpace.emit()` records) so direct-bus and space-driven
  publication produce equivalent audit trails.
- **Ledger record (immediate):** `event_published`.
- **Day-1 tick:** No delivery yet. Per the v0.3 next-tick rule,
  events with `publication_date == current_date` are not delivered
  in the same tick.
- **Day-2 tick:** Both targets receive. The ledger gains two
  `event_delivered` records, one per target.

## After the loop

Inspecting the ledger after `kernel.run(days=2)`, you should see all
seven loop record types present, in this order, plus the setup
records that preceded the loop. The script prints a summary that
includes:

- total ledger record count,
- a breakdown of `record.event_type → count`,
- the seven loop-step record ids in chain order,
- the two delivery target spaces.

If you copy any record id from the printout and search the ledger
for records whose `parent_record_ids` contain it, you can trace the
chain forward; if you take a leaf record (e.g., `event_delivered`)
and walk back through `parent_record_ids` (and domain-level
cross-references like `related_ids` and `input_refs`), you can
reconstruct the full chain back to the original observation.

That round-trip — leaf-to-root reconstructable from the ledger
alone — is the v1 invariant that the demo validates end-to-end.

## What the demo does NOT show

To re-emphasize:

- **No price moves.** `firm:reference_manufacturer_a`'s price is
  unchanged at `95.0` after the loop runs.
- **No portfolio changes.** Investors' holdings are identical
  before and after.
- **No bank credit decisions.** The two banks are populated for
  the demo composition but do not act.
- **No corporate actions.** The five firms are populated but do
  not issue, buy back, or update earnings.
- **No policy decisions.** The central bank's `InstitutionProfile`
  exists, and one institutional action is *recorded*, but no
  policy rate or instrument value changes.
- **No information dynamics.** Two signals are emitted, but no
  rumor propagation, source credibility update, or visibility decay
  happens.
- **No external dynamics.** The macro process is `process_type =
  "constant"`; its observation value is exactly its `base_value`.
  No random walk, AR(1), or regime switch happens.

The demo's value is structural completeness, not realism.
