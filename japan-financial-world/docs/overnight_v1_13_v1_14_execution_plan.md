# Overnight Execution Plan — v1.13.1 → v1.13.last (and conditionally v1.14)

> **Status: IN FLIGHT.** This document is the single source of
> truth for the long sequential session that advances FWE from
> the v1.12.last freeze (commit `4786373`) through the v1.13
> generic settlement / interbank liquidity infrastructure
> sequence and, conditionally, into the v1.14 corporate
> financing intent layer.

## Operating rules (binding)

1. **Sequential, not creative.** Each milestone follows the
   data model and field set the user named exactly. No new
   records, fields, helpers, or behaviors beyond the spec.
2. **No skipping.** v1.13.1 → v1.13.2 → v1.13.3 → v1.13.4 →
   v1.13.5 → v1.13.last in order. Only after v1.13.last is
   green may v1.14.0 be attempted.
3. **One commit per milestone.** Local commit only — push is
   reserved for the final checkpoint.
4. **Verification gate per milestone.** Each commit must clear:
   - `cd japan-financial-world && python -m pytest -q`
   - `python -m compileall -q world spaces tests examples`
   - `ruff check .` from the repo root
5. **Stop on red.** If any gate fails, halt and report. Do not
   proceed to the next milestone.
6. **No push to `main`** until the final checkpoint at the end
   of the session.
7. **No BOJ-NET, no Japan calibration, no real payment
   processing, no real balances, no trading, no price
   formation, no lending decisions, no investment advice.**
   Every record stays synthetic, label-based, append-only,
   ledger-auditable.
8. **Preserve hard boundaries and anti-overclaiming
   language.** Every milestone's docs include the relevant
   anti-claim list.
9. **Stop on broad refactor.** If a milestone would require
   touching more than its own module + ledger + kernel + tests
   + docs, stop and explain instead of forcing it.

## Pre-flight state (2026-05-04)

- Branch: `main`
- Latest commit on `main`: `4786373` (v1.12.last freeze)
- `pytest -q`: **2751 passed**
- `living_world_digest` (perf fixture):
  `e508b4bf10df217f7b561b41aea845f841b12215d5bf815587375c52cffcdcb5`
- `living_world_digest` (integration fixture):
  `e328f955922117f7d9697ea9a68877c418b818eedbab888f2d82c4b9ac4070b0`
- Per-period record count: 79 (period 0) / 81 (period 1+)
- Per-run record window: `[316, 364]`
- Hard boundary: no trading / no price formation / no lending
  decisions / no investment advice / no real data / no Japan
  calibration / no LLM execution / no behavior probabilities /
  no probabilistic forgetting.

## Primary target: v1.13.1 → v1.13.last

### v1.13.1 — `SettlementAccountBook`

**Files:**
- `world/settlement_accounts.py` (new)
- `tests/test_settlement_accounts.py` (new)
- `world/ledger.py` — add `SETTLEMENT_ACCOUNT_REGISTERED`
- `world/kernel.py` — wire `kernel.settlement_accounts`
- `docs/world_model.md` — append §93
- `docs/test_inventory.md` — bump
- `README.md` — roadmap row

**Data model — `SettlementAccountRecord`:**
`account_id`, `owner_institution_id`, `owner_type`,
`account_type`, `currency_label`, `settlement_system_id`,
`status`, `visibility`, `opened_date`, `closed_date`,
`metadata`.

**Book API:** `add_account` / `get_account` / `list_accounts`
/ `list_by_owner` / `list_by_account_type` / `list_by_status`
/ `list_active_as_of` / `snapshot`.

**Anti-claims:** no real balances, no central-bank accounting,
no real payment processing, no BOJ-NET, no Japan calibration.

### v1.13.2 — `PaymentInstructionRecord` / `SettlementEventRecord`

**Files:**
- `world/settlement_payments.py` (new) — both records + book
- `tests/test_settlement_payments.py` (new)
- `world/ledger.py` — add `PAYMENT_INSTRUCTION_REGISTERED` +
  `SETTLEMENT_EVENT_RECORDED`
- `world/kernel.py` — wire `kernel.settlement_payments`
- `docs/world_model.md` — append §94
- `docs/test_inventory.md` — bump
- `README.md` — roadmap row

**Data models per spec.** No real amounts. No settlement
execution. No RTGS queue mechanics. No securities settlement
execution. No central-bank accounting.

### v1.13.3 — `InterbankLiquidityStateRecord`

**Files:**
- `world/interbank_liquidity.py` (new)
- `tests/test_interbank_liquidity.py` (new)
- `world/ledger.py` — add `INTERBANK_LIQUIDITY_STATE_RECORDED`
- `world/kernel.py` — wire `kernel.interbank_liquidity`
- `docs/world_model.md` — append §95
- `docs/test_inventory.md` — bump
- `README.md` — roadmap row

**Labels:**
- `liquidity_regime`: ample / normal / tight / stressed /
  unknown
- `settlement_pressure`: low / moderate / high / severe /
  unknown
- `reserve_access_label`: available / constrained / unknown
- `funding_stress_label`: low / moderate / elevated / stressed
  / unknown

**Anti-claims:** no real balances, no calibrated liquidity
model, no bank default, no lending decision.

### v1.13.4 — `CentralBankOperationSignal` / `CollateralEligibilitySignal`

**Files:**
- `world/central_bank_signals.py` (new)
- `tests/test_central_bank_signals.py` (new)
- `world/ledger.py` — add `CENTRAL_BANK_OPERATION_SIGNAL_RECORDED`
  + `COLLATERAL_ELIGIBILITY_SIGNAL_RECORDED`
- `world/kernel.py` — wire `kernel.central_bank_signals`
- `docs/world_model.md` — append §96
- `docs/test_inventory.md` — bump
- `README.md` — roadmap row

**Anti-claims:** no actual operation execution, no monetary
policy reaction function, no collateral valuation, no
jurisdiction-specific eligibility rule.

### v1.13.5 — MarketEnvironment / BankCreditReview integration

**Files:**
- `world/market_environment.py` — add additive
  `evidence_interbank_liquidity_state_ids` slot to
  `MarketEnvironmentStateRecord`; let
  `build_market_environment_state` accept the kwarg
- `world/reference_bank_credit_review_lite.py` — add
  `explicit_interbank_liquidity_state_ids` kwarg to the
  attention-conditioned helper
- `world/reference_living_world.py` — per-period interbank
  liquidity phase: one state per bank per period (`B × P`),
  cited downstream by market environment + bank credit review
- `tests/test_market_environment.py`,
  `tests/test_reference_bank_credit_review_lite.py`,
  `tests/test_living_reference_world.py` — extend
- `docs/world_model.md` — append §97
- `docs/test_inventory.md` — bump
- `docs/performance_boundary.md` — bump per-period budget by
  `B = 2`
- `README.md` — roadmap row

**Boundaries:** no settlement execution, no payment-flow
simulation, no dense bank-to-bank network. Per-period adds B
records (one liquidity state per bank).

### v1.13.last — Freeze

**Files:**
- `docs/v1_13_generic_settlement_infrastructure_summary.md`
  (new) — mirror the v1.12.last summary doc shape
- `docs/world_model.md` — append §98 freeze section
- `docs/test_inventory.md` — bump headline to v1.13.last
- `docs/performance_boundary.md` — refresh with v1.13.x final
  numbers
- `RELEASE_CHECKLIST.md` — append v1.13.last readiness
  snapshot
- `README.md` — bump current-runtime-milestone headline

**Must say:** v1.13 does not implement BOJ-NET. v1.13 does not
process payments. v1.13 does not implement real balances,
RTGS, central-bank accounting, monetary policy, or securities
settlement. It provides a generic synthetic infrastructure
layer for future jurisdiction-specific mapping.

## Secondary target (only if v1.13.last is fully green)

### v1.14.0 — Corporate Financing Intent design (docs-only)

**Files:**
- `docs/v1_14_corporate_financing_intent_design.md` (new)
- `docs/world_model.md` — append §99
- `README.md` — roadmap row

**Concepts:** `CorporateFinancingNeedRecord`,
`FundingOptionCandidate`, `CapitalStructureReviewCandidate`.

**Anti-claims:** no loan origination, no DCM/ECM execution,
no underwriting, no security issuance, no bookbuilding, no
pricing, no investment advice.

## Tertiary target (only if time remains and tests stay green)

### v1.14.1 — `CorporateFinancingNeedRecord` storage

**Files:**
- `world/corporate_financing.py` (new)
- `tests/test_corporate_financing.py` (new)
- `world/ledger.py` — add `CORPORATE_FINANCING_NEED_RECORDED`
- `world/kernel.py` — wire `kernel.corporate_financing`
- `docs/world_model.md` — append §100
- `docs/test_inventory.md` — bump
- `README.md` — roadmap row

**Anti-claims:** no financing execution, no loan approval, no
bond issuance, no equity issuance, no pricing, no real
amounts.

**Living-world integration:** explicitly out of scope tonight.

## Final report contents

When the session ends (success, halt, or partial), produce a
compact report listing:
- milestones completed
- commit hashes
- final test count
- files changed
- whether `living_world_digest` changed
- whether performance boundary changed
- unresolved TODOs
- whether v1.14.1 was attempted or skipped
- exact next recommended milestone
