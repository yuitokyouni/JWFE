# Research Note 001 — Stress Composition without Outcome Inference

*Companion note to v1.21.last (Stress Composition Layer freeze).
Explains the research meaning of v1.21 — why the layer is a thin
orchestrator + read-only multiset readout rather than a stress-
outcome inference engine, and what kind of research object the
v1.21 surface actually is.*

This note is a research statement, not a design document. The
binding design pin lives in
[`v1_21_stress_composition_layer.md`](v1_21_stress_composition_layer.md);
the constitutional context lives in
[`world_model.md`](world_model.md) §130. This note is the layer
*above* those: what v1.21 is *for*, in the sense of the research
question it is meant to support.

---

## 1. Problem

Most simulation work that touches "stress" jumps directly to
clean **scenario comparison**: pick a baseline run, pick a
stressed run, compute a delta on some outcome variable
(portfolio loss, default rate, capital ratio, expected return),
and call the delta the "stress impact."

Clean scenario comparison is too simple for financial-world
modeling, for three reasons that compound:

1. **The baseline-vs-stress delta presupposes a single outcome
   metric** — a price, a P&L, a default probability — that the
   engine can output. A public synthetic world that explicitly
   refuses to produce prices, P&Ls, or default probabilities
   has no such metric to difference against. The framing does
   not apply.
2. **Real stress periods are rarely one-stress events.** Credit
   tightening overlaps with funding stress, which overlaps with
   demand contraction, which overlaps with regulatory tightening.
   An engine that reduces all of that to a single "combined
   stress impact" number is silently asserting a causal model of
   how stresses interact — a model that the engine cannot
   ground without real-world feedback.
3. **The audit consumer is a human reviewer, not a backtest
   harness.** A reviewer asks "what records were emitted, on
   what surfaces, citing what sources, in what order, and where
   did downstream actors fail to resolve them?" — not "what
   number did the model produce." A scenario-delta-on-an-
   outcome-metric framing optimises for the second question and
   makes the first question harder to answer.

v1.21 declines all three of those defaults.

---

## 2. Core idea

The v1.21 framing reduces to one move: **stress stimuli are
append-only inputs to context surfaces; the model does not
infer combined outcomes; it records context shifts and the
downstream citation trail.**

Concretely:

- A **stress program** is an ordered bundle of synthetic
  stimuli. Each step cites a v1.18.1 `ScenarioDriverTemplate`
  by id and is applied via the v1.18.2
  `apply_scenario_driver(...)` helper. The orchestrator emits
  exactly one program-level receipt; it never reduces the
  steps.
- A **context surface** is one of a closed set of named
  surfaces (`market_environment`, `industry_condition`,
  `interbank_liquidity`, …) on which a step can record a
  context shift. The surface name is structural; it carries no
  outcome implication.
- A **shift** is a new append-only `ScenarioContextShiftRecord`
  on a surface, citing the program, the step, and the driver
  template. The pre-existing source-of-truth book is *not*
  mutated.
- A **multiset readout** projects, per surface, the ordered
  multiset of `(shift_direction_label, scenario_family_label,
  cited_source_context_record_ids)` triples plus per-step
  resolution state and warnings. Order of emission is
  preserved as the audit signal; nothing is reduced.
- A **downstream citation trail** is the chain of records that
  later cite the shift — actor attention selections, review
  notes, intent surfaces, operating-pressure assessments —
  through plain-id citation fields, never through
  cross-mutation.

Composition under this framing is an **observation**, not an
**inference**. Two stresses on the same surface in the same
period are recorded as two entries in a multiset; no
`amplify` / `dampen` / `offset` / `coexist` label is computed.
A reviewer who wants to claim that two stresses interact must
write that claim themselves, as a separate
`manual_annotation` record citing specific cells of the
multiset readout.

---

## 3. Research object

The research object that v1.21 produces is a **directed
citation graph**, not a number. The graph's edges are plain-id
citations recorded on append-only ledger records; the graph's
nodes are the records themselves.

The graph shape (from stimulus to downstream consumer):

```
StressProgramApplicationRecord
    │   (cites: stress_program_template_id, scenario_application_ids[])
    ▼
ScenarioDriverApplicationRecord                         (one per step)
    │   (cites: scenario_driver_template_id, program_application_id)
    ▼
ScenarioContextShiftRecord                              (one or more per step,
    │                                                    one per shift on a surface)
    │   (cites: scenario_application_id, target_context_record_ids[])
    ▼
Actor attention / review / intent / pressure records   (downstream citations)
        │
        ▼
StressFieldReadout                                     (read-only projection;
                                                        no ledger emission)
        │
        ▼
render_stress_field_summary_markdown(...)              (deterministic markdown,
                                                        suitable for an audit note)
```

What this graph is for, as a research object:

- **A reviewer can walk it.** Every line of the markdown summary
  resolves back to specific records on specific context surfaces
  in specific periods. There is no opaque step where a model
  "decided" something the trail does not capture.
- **A test can pin it.** The `living_world_digest` is a SHA-256
  hash over the canonical record sequence. A regression that
  changes the graph changes the digest; a test fails before the
  graph reaches a reviewer.
- **A boundary can scan it.** The forbidden-name list scans
  every dataclass field name, payload key, metadata key, and
  module text token; a regression that smuggles in
  outcome-inference language fails CI before it ships.

The graph is **the engine's output**. There is no other output.

---

## 4. What this is not

To keep the framing honest:

- **Not price prediction.** No price formation, no expected
  return, no target price, no scenario probability weight, no
  magnitude. The graph contains no price node.
- **Not causal proof.** A citation edge from a stress program
  to a downstream actor record means "this downstream record
  cited the stress" — not "this stress caused this downstream
  record." Real-world causation is not in the engine's reach.
- **Not investment advice.** The downstream consumer is a
  human reviewer reading a markdown audit note, not an order
  book or a portfolio system. Nothing in the graph is read as a
  market view.
- **Not real-data calibration.** The synthetic universe carries
  the `*_reference_*` / `_like` synthetic-only naming
  convention. No real institutional identifiers, no licensed
  taxonomies, no public-data feeds, no Japan calibration. v2.x
  / v3.x is where calibration questions begin.

---

## 5. Why this may matter

The narrow positive claim — what the engine *might* be useful
for, stated cautiously:

- **Attention crowding becomes inspectable.** The v1.12 finite
  attention budget plus the v1.18 / v1.20 / v1.21 stimulus
  chain produces a graph in which a reviewer can see whether
  one stress's downstream citations crowd out another's in the
  same period. If a stress arrives but no downstream actor
  cites it (because attention is saturated by an earlier
  stress), the multiset readout shows it; the markdown summary
  prints it. That is a different kind of question than
  "what was the loss."
- **Blind spots become audit-visible.** Steps that fail to
  resolve (`unresolved_step_count > 0`,
  `unresolved_reason_labels ∈ {template_missing,
  unknown_failure}`) are surfaced in the receipt and as a
  PARTIAL APPLICATION banner in the markdown summary. The
  engine refuses to silently swallow a missing template.
- **Audit trails under overlapping stress become tractable.**
  The graph is byte-deterministic and reconstructable; two
  reviewers running the same fixture produce identical traces.
  Disagreement about what happened reduces to disagreement
  about what the trail *means*, not about what the trail *is*.

The negative phrasing matters: this is "may matter" because
the question of whether such trails are useful at all *to a
reviewer who is not the author* is not yet answered. v1.21
makes the experiment runnable; it does not make the experiment
succeed.

---

## 6. Open questions

This is the part of the note that explicitly does not pretend
to have answers. Each question must be answered before any
higher-layer claim is reasonable.

**How to validate without prices.** A scenario-delta framing
validates against an outcome metric. A citation-graph framing
has no outcome metric. What is the analogue of out-of-sample
validation for an audit graph? Replay determinism is necessary
but not sufficient.

**How to compare citation graphs to analyst reports or crisis
narratives.** A reviewer reading a published crisis post-mortem
can identify which stresses overlapped, which actors noticed
which stresses, and which signals were missed. Can a v1.21
citation graph be matched, even loosely, to such a narrative on
a synthetic universe shaped to mimic the narrative's
conditions? Without a matching protocol the graph is just a
trace.

**How to prevent the label taxonomy from becoming arbitrary.**
Every closed-set vocabulary (`shift_direction_label`,
`scenario_family_label`, `severity_label`, `surface_label`,
`affected_actor_scope_label`) is a design choice. As more
stress families are added, the temptation to grow the taxonomy
grows. What discipline keeps it tight enough that two
reviewers reach the same labelling on the same fixture?

**How to measure attention crowding.** The v1.12 attention
budget makes crowding *possible*; the v1.21 readout makes it
*inspectable*. Neither makes it *measurable* in a way that
generalises. Is there a defensible metric — counted in
citation-graph terms, not in price terms — that captures "this
stress was emitted but no downstream actor cited it"?

**How to decide when manual_annotation interaction is
justified.** The v1.21.0a deferral keeps interaction-style
labels (`amplify` / `dampen` / `offset` / `coexist`) out of
the engine; they may only ever appear as a human-authored
`manual_annotation` record citing explicit evidence from the
multiset readout. What is the protocol for deciding that the
evidence is sufficient? The risk is that
`manual_annotation` becomes a backdoor through which outcome
inference re-enters the system without the engine's
discipline.

These questions are tracked here, in this note, rather than in
the design pin. The design pin describes what is shipped; this
note describes what is not yet known.

---

## 7. Next experiment

The smallest concrete next experiment, sized to one synthetic
universe and one stress program:

1. Use the v1.20.4 `scenario_monthly_reference_universe`
   profile with `--regime constrained` as the synthetic
   substrate.
2. Apply one v1.21 stress program with two or three steps
   over distinct context surfaces (e.g., one
   `credit_tightening_driver`-family step on
   `interbank_liquidity`, one
   `industry_condition_driver`-family step on
   `industry_condition`).
3. Build the v1.21.3 `StressFieldReadout` and render the
   markdown summary.
4. Inspect: do the downstream citations (actor attention
   selections, review notes, intent surfaces, operating-
   pressure assessments) change in a *traceable, bounded, and
   non-predictive* way?
   - **Traceable** means: every changed downstream record
     cites a specific shift on a specific surface at a
     specific period; the citation walks back to the program
     receipt cleanly.
   - **Bounded** means: the change does not propagate beyond
     the surfaces touched by the program; pre-existing books
     remain byte-identical pre / post (re-checked via
     digest).
   - **Non-predictive** means: nothing in the changed
     downstream records claims an outcome — no price, no
     forecast, no expected response, no recommendation.

If those three properties hold across a small set of programs
on a single synthetic universe, the engine has met the v1.21
research bar: a citation graph that survives overlapping
stress without overclaiming. If they do not hold, the gap
points at the next milestone — not at retrofitting an outcome
metric onto v1.21.

That is the only thing v1.21 is for.
