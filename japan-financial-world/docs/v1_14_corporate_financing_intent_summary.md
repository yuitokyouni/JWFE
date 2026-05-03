# v1.14 Corporate Financing Intent — Summary

This document closes the v1.14 sequence of FWE. The sequence
ships a **jurisdiction-neutral, label-only, synthetic** corporate
financing reasoning chain layered on top of the v1.12 endogenous
attention loop and the v1.13 generic settlement / interbank-
liquidity substrate. v1.14.last itself is docs-only on top of the
v1.14.1 → v1.14.5 code freezes.

This is **not** a financing-execution layer, **not** an
underwriting / syndication / bookbuilding layer, **not** a pricing
layer, **not** a capital-structure-optimisation layer, and **not**
a Japan calibration. It is a small set of immutable record types,
append-only books, ledger event types, and one bounded per-period
synthesis phase. The chain executes nothing.

## Sequence map

| Milestone   | Module / surface                                     | Adds                                                                                                                                                                                                              |
| ----------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| v1.14.0     | docs only                                            | Corporate-financing-intent design vocabulary; explicitly out of scope: financing execution, loan approval, securities issuance, underwriting, pricing, optimal capital structure decision, investment advice.    |
| v1.14.1     | `world/corporate_financing.py`                       | `CorporateFinancingNeedRecord` + `CorporateFinancingNeedBook`. Ledger event `corporate_financing_need_recorded`. Four label fields (horizon / purpose / urgency / synthetic-size). Storage only.                  |
| v1.14.2     | `world/funding_options.py`                           | `FundingOptionCandidate` + `FundingOptionCandidateBook`. Ledger event `funding_option_candidate_recorded`. Seven closed-set-enforced label fields. Storage only.                                                  |
| v1.14.3     | `world/capital_structure.py`                         | `CapitalStructureReviewCandidate` + `CapitalStructureReviewBook`. Ledger event `capital_structure_review_candidate_recorded`. Eight closed-set-enforced label fields. Storage only.                               |
| v1.14.4     | `world/financing_paths.py`                           | `CorporateFinancingPathRecord` + `CorporateFinancingPathBook` + deterministic `build_corporate_financing_path` helper. Five closed-set-enforced label fields. Graph / audit object linking need → option → review. |
| v1.14.5     | `world/reference_living_world.py` (per-period sweep) | First living-world integration: `5 × firms` records / period (1 need + 2 options + 1 review + 1 path); `LivingReferencePeriodSummary` gains four id-tuple fields; markdown report adds `## Corporate financing`.  |
| v1.14.last  | docs only                                            | This summary, §105 in `docs/world_model.md`, `RELEASE_CHECKLIST.md` snapshot, `performance_boundary.md` update, `README.md` headline.                                                                              |

## What v1.14 ships

The final living-world chain is:

```
market environment   (v1.12.2)
  → firm latent state   (v1.12.0)
  → investor intent  /  valuation   /  bank credit review
       (v1.12.1     /  v1.12.5    /  v1.12.6 / v1.12.7)
  → corporate financing need        (v1.14.1)
  → funding option candidates       (v1.14.2)
  → capital structure review        (v1.14.3)
  → financing path                  (v1.14.4 / v1.14.5)
```

- **Records:** four new immutable-dataclass record types
  (need, funding-option candidate, capital-structure-review
  candidate, financing-path), all carrying closed-set-enforced
  label fields, a `[0,1]` synthetic confidence (booleans
  rejected), and plain-id source-reference tuples cross-
  referencing the v1.12 / v1.13 substrate (firm states, market
  environments, interbank liquidity, bank credit reviews,
  investor intents).
- **Books:** four new append-only books wired into
  `WorldKernel`: `corporate_financing_needs`, `funding_options`,
  `capital_structure_reviews`, `financing_paths`. Each book
  emits one ledger record per add call and refuses to mutate
  any other source-of-truth book.
- **Ledger events:** four new record types
  (`corporate_financing_need_recorded`,
  `funding_option_candidate_recorded`,
  `capital_structure_review_candidate_recorded`,
  `corporate_financing_path_recorded`).
- **Closed-set vocabularies:** five label axes on each layer
  enforced at construction. The full vocabulary is pinned in
  the per-milestone `world_model.md` sections (§99 / §101 /
  §102 / §103) and in module-level `frozenset` constants tested
  for exact set equality.
- **Builder (v1.14.4):** `build_corporate_financing_path`
  derives `path_type_label` / `coherence_label` /
  `constraint_label` / `next_review_label` deterministically
  from the cited records. Reads only the cited ids via
  `get_need` / `get_candidate`; never iterates the books
  globally (pinned by a trip-wire test on every `list_*` and
  `snapshot` of the cited books).
- **Living-world integration (v1.14.5):** the chain runs once
  per firm per period **after** the v1.12.8 attention-feedback
  phase and **before** period summary assembly. Bounded by
  `P × F` per layer — never `O(P × F × I)` or
  `O(P × F × B × option_count)`.

## What v1.14 explicitly is not

- **Not financing execution.** No loan origination, no bond
  issuance, no equity issuance, no securities issuance, no
  funding disbursement, no allocation, no commitment.
- **Not underwriting / syndication / bookbuilding.** No
  underwriter mandate, no syndicate construction, no order book,
  no allocation table, no oversubscription / undersubscription.
- **Not a pricing layer.** No interest rate, no spread, no
  coupon, no fee, no offering price, no target price, no
  expected return, no take-up probability.
- **Not a capital-structure optimisation.** No optimal capital
  structure decision, no leverage optimum, no D/E target, no
  WACC calculation, no real leverage ratio, no rating model.
- **Not a credit-risk / rating layer.** No PD, no LGD, no EAD,
  no internal rating, no default declaration, no covenant
  enforcement.
- **Not an investment-advice layer.** No selected_option, no
  optimal_option, no recommendation, no investment_advice, no
  buy / sell / overweight / underweight / order / trade.
- **Not a real-data layer.** No real corporate-finance data,
  no real bond / loan / equity issuance data, no real
  underwriting fees, no real allocation tables, no real-system
  identifiers.
- **Not a Japan calibration.** All ids, labels, and confidence
  scalars are jurisdiction-neutral, synthetic, and illustrative.
  Real-system Japan-shaped calibration is private JFWE territory
  (v2 / v3 only).

## Performance boundary at v1.14.last

- **Per-period record count (default fixture):** 96 (period 0)
  / 98 (periods 1+). Up from 81 / 83 at v1.13.last. The +15
  per period is `5 × firms = 5 × 3 = 15` v1.14.5 records (1
  need + 2 options + 1 capital-structure review + 1 financing
  path per firm).
- **Per-run window (default fixture):** `[384, 432]` records.
  Up from `[324, 372]` at v1.13.last. Default 4-period sweep
  emits **408** records.
- **Integration-test `living_world_digest`:**
  `3df73fd4f152c16d1188f5c15b69bdc8a5cd6061b637ea35af671e86c6fa2d71`
  (v1.14.5; previously
  `916e410d829bec0be26b92989fa2d5438b80637a5c56afd785e0b56cfbebb379`
  at v1.13.5 / v1.13.6 — unchanged through v1.14.1 → v1.14.4
  because those milestones were storage-only). The shift is by
  design: v1.14.5 wiring adds new ledger records and four new
  id tuples per period summary.
- **Test count:** 3391 / 3391 passing. Up from 3066 / 3066 at
  v1.13.last (+325 across v1.14.1 → v1.14.5).
- The v1.14.1 / v1.14.2 / v1.14.3 / v1.14.4 modules are
  storage-only on the default kernel; v1.14.5 is the first
  v1.14 milestone on the per-period sweep.

## Discipline preserved bit-for-bit

Every v1.9.x / v1.10.x / v1.11.x / v1.12.x / v1.13.x boundary
anti-claim is preserved unchanged at v1.14.last:

- No real data, no Japan calibration, no LLM-agent execution,
  no behaviour probability.
- No price formation, no trading, no portfolio allocation, no
  investment advice, no rating.
- No lending decision, no covenant enforcement, no contract
  mutation, no constraint mutation, no default declaration.
- The v1.12.6 watch-label classifier is unchanged at v1.14.5.
- The v1.13.5 settlement / interbank-liquidity substrate is
  unchanged; v1.14.5 cites those ids without mutating them.
- The v1.9.last public-prototype freeze, the v1.12.last
  attention-loop freeze, and the v1.8.0 public release remain
  untouched.

## What v1.15 does next

v1.15 begins the **securities market intent aggregation** layer.
Investor intents do not directly update prices; they are first
aggregated by a broker / exchange / market-venue abstraction
into security-level market pressure. That pressure can later
feed back into equity-issuance accessibility, dilution concern,
market access, and the capital-structure review. v1.15.0 is
docs-only design; subsequent v1.15.x milestones will ship
`ListedSecurityRecord`, `MarketVenueRecord`,
`InvestorTradingIntentRecord`, `AggregatedMarketInterestRecord`,
and `IndicativeMarketPressureRecord` storage. No order
submission, no order matching, no trade execution, no clearing,
no settlement, no real exchange mechanics, no real price
formation, no Japan calibration. See
[`v1_15_securities_market_intent_aggregation_design.md`](v1_15_securities_market_intent_aggregation_design.md).
