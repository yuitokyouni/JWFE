"""
v1.16.1 endogenous market-intent direction classifier.

A **pure deterministic function** mapping a small set of
already-cited evidence inputs into one safe
``InvestorMarketIntentRecord.intent_direction_label`` value.
Implements the eight-priority rule table pinned in the v1.16.0
design note (`docs/v1_16_endogenous_market_intent_direction_design.md`).

This module is **runtime-book-free** by construction:

- It does **not** import any source-of-truth book
  (``Ledger``, ``WorldKernel``, ``InvestorMarketIntentBook``, ...).
- It does **not** accept a kernel argument; the caller is
  responsible for resolving evidence and passing it in. Therefore
  it cannot mutate the ``PriceBook`` (or anything else).
- It depends only on
  :data:`world.market_intents.INTENT_DIRECTION_LABELS` for the
  closed-set output vocabulary check.

The classifier reads only the inputs given to it. There is no
global state, no time dependency, no randomness, no calibrated
probability, no LLM call, no real-data lookup, no Japan
calibration. Two calls with byte-identical inputs return
byte-identical :meth:`MarketIntentClassificationResult.to_dict`
output.

The function deliberately does **not** accept ``period_idx`` /
``investor_idx`` / ``firm_idx`` — the v1.15.5 rotation those
indices drove is the thing v1.16 replaces. The success condition
(pinned by tests) is:

    The same ``(investor, security)`` pair can produce different
    safe market-interest labels because the evidence context
    differs, **not** because of index rotation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from world.market_intents import INTENT_DIRECTION_LABELS


# ---------------------------------------------------------------------------
# Closed-set helper sets
# ---------------------------------------------------------------------------


# Forbidden trade-instruction verbs that must never appear in the
# classifier's output. Closed-set membership on
# ``intent_direction_label`` already rejects them — these are
# **never** in :data:`INTENT_DIRECTION_LABELS`. The list below is
# kept as a separate frozenset so tests can assert the disjoint
# invariant explicitly.
FORBIDDEN_OUTPUT_LABELS: frozenset[str] = frozenset(
    {
        "buy",
        "sell",
        "order",
        "target_weight",
        "overweight",
        "underweight",
        "execution",
    }
)

# Attention-focus categories used by the rule table.
ENGAGEMENT_FOCUS_LABELS: frozenset[str] = frozenset(
    {
        "engagement",
        "dialogue",
        "stewardship_theme",
        "stewardship",
    }
)
LIQUIDITY_FUNDING_FOCUS_LABELS: frozenset[str] = frozenset(
    {
        "liquidity",
        "funding",
    }
)
FIRM_VALUATION_MARKET_FOCUS_LABELS: frozenset[str] = frozenset(
    {
        "firm_state",
        "valuation",
        "market_environment",
        "market_condition",
    }
)

# Market-environment access label categories used by the rule
# table. Permissive — the classifier accepts any string for
# ``market_environment_access_label`` and only checks membership
# in these small sets within rules.
CONSTRAINED_MES_LABELS: frozenset[str] = frozenset(
    {
        "constrained",
        "closed",
    }
)
SELECTIVE_OR_CONSTRAINED_MES_LABELS: frozenset[str] = frozenset(
    {
        "selective",
        "constrained",
        "closed",
    }
)
CONSTRUCTIVE_MES_LABELS: frozenset[str] = frozenset(
    {
        "open",
        "open_or_constructive",
        "constructive",
    }
)

# Investor-intent direction sets used by rules. The strings come
# from the v1.12.1 ``InvestorIntentRecord.intent_direction``
# vocabulary (see ``world/investor_intent.py``); the classifier
# never enforces membership against that vocabulary, so a caller
# can pass any non-empty string. Rule predicates are written as
# explicit set memberships so unfamiliar inputs simply fall
# through to the default.
ENGAGEMENT_INVESTOR_INTENTS: frozenset[str] = frozenset(
    {"engagement_watch"}
)
RISK_FLAG_INVESTOR_INTENTS: frozenset[str] = frozenset(
    {"risk_flag_watch"}
)
DUE_DILIGENCE_INVESTOR_INTENTS: frozenset[str] = frozenset(
    {"deepen_due_diligence"}
)
ROUTINE_OR_ENGAGEMENT_INTENTS: frozenset[str] = frozenset(
    {"routine", "engagement_watch"}
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MarketIntentClassifierError(Exception):
    """Base class for v1.16.1 market-intent-classifier errors."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_optional_unit(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be a number or None; got {value!r}"
        )
    if not (0.0 <= float(value) <= 1.0):
        raise ValueError(
            f"{field_name} must be between 0 and 1 inclusive; got {value!r}"
        )
    return float(value)


def _validate_required_label(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{field_name} must be a non-empty string (use 'unknown' "
            f"if absent); got {value!r}"
        )
    return value


def _validate_string_tuple(
    value: Iterable[str], *, field_name: str
) -> tuple[str, ...]:
    normalized = tuple(value)
    for entry in normalized:
        if not isinstance(entry, str) or not entry:
            raise ValueError(
                f"{field_name} entries must be non-empty strings; "
                f"got {entry!r}"
            )
    return normalized


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketIntentClassificationResult:
    """Immutable result of one
    :func:`classify_market_intent_direction` call.

    Field semantics
    ---------------
    - ``intent_direction_label`` — one of
      :data:`world.market_intents.INTENT_DIRECTION_LABELS`
      (= v1.15 ``SAFE_INTENT_LABELS`` ∪ ``{"unknown"}``). The
      forbidden trade-instruction verbs (``buy`` / ``sell`` /
      ``order`` / ``target_weight`` / ``overweight`` /
      ``underweight`` / ``execution``) are rejected by closed-set
      membership.
    - ``rule_id`` — short string naming the rule that fired
      (e.g. ``"priority_3a_risk_flag_watch"``). Useful for audit
      explanation and for downstream filtering.
    - ``status`` — one of:
        * ``"classified"`` — a specific rule (priorities 2–7) fired.
        * ``"evidence_deficient"`` — every input was absent / unknown
          (priority 1; ``intent_direction_label == "unknown"``).
        * ``"default_fallback"`` — some evidence was present but no
          specific rule fired (priority 8;
          ``intent_direction_label == "hold_review"``).
    - ``confidence`` — synthetic ``[0.0, 1.0]`` ordering on how
      strongly the cited evidence supports the result. **Never**
      a calibrated probability of any external action. Booleans
      rejected.
    - ``evidence_summary`` — a serialisable mapping naming the
      inputs the classifier saw (with ``None`` for absent
      numerics, ``"unknown"``-style sentinels for absent labels,
      and an empty list for absent focus labels). Present so the
      caller can audit *why* a particular rule fired.
    - ``unresolved_or_missing_count`` — count of input sources
      that were absent or ``unknown`` (0 to 5).
    - ``metadata`` — free-form mapping for the caller.
    """

    intent_direction_label: str
    rule_id: str
    status: str
    confidence: float
    evidence_summary: Mapping[str, Any] = field(default_factory=dict)
    unresolved_or_missing_count: int = 0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.intent_direction_label, str) or not self.intent_direction_label:
            raise ValueError("intent_direction_label is required")
        if self.intent_direction_label not in INTENT_DIRECTION_LABELS:
            raise ValueError(
                "intent_direction_label must be one of "
                f"{sorted(INTENT_DIRECTION_LABELS)!r}; "
                f"got {self.intent_direction_label!r}"
            )
        if self.intent_direction_label in FORBIDDEN_OUTPUT_LABELS:
            raise ValueError(
                f"intent_direction_label {self.intent_direction_label!r} "
                "is a forbidden trade-instruction verb"
            )

        if not isinstance(self.rule_id, str) or not self.rule_id:
            raise ValueError("rule_id is required")
        if not isinstance(self.status, str) or not self.status:
            raise ValueError("status is required")

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "confidence must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated "
                "probability of any external action)"
            )
        object.__setattr__(self, "confidence", float(self.confidence))

        if (
            isinstance(self.unresolved_or_missing_count, bool)
            or not isinstance(self.unresolved_or_missing_count, int)
        ):
            raise ValueError(
                "unresolved_or_missing_count must be a non-negative int"
            )
        if self.unresolved_or_missing_count < 0:
            raise ValueError(
                "unresolved_or_missing_count must be non-negative"
            )

        object.__setattr__(self, "evidence_summary", dict(self.evidence_summary))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_direction_label": self.intent_direction_label,
            "rule_id": self.rule_id,
            "status": self.status,
            "confidence": self.confidence,
            "evidence_summary": dict(self.evidence_summary),
            "unresolved_or_missing_count": self.unresolved_or_missing_count,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------


def _build_evidence_summary(
    *,
    investor_intent_direction: str,
    valuation_confidence: float | None,
    firm_market_access_pressure: float | None,
    market_environment_access_label: str,
    focus_labels: tuple[str, ...],
    has_intent: bool,
    has_mes: bool,
) -> dict[str, Any]:
    return {
        "investor_intent_direction": (
            investor_intent_direction if has_intent else None
        ),
        "valuation_confidence": valuation_confidence,
        "firm_market_access_pressure": firm_market_access_pressure,
        "market_environment_access_label": (
            market_environment_access_label if has_mes else None
        ),
        "attention_focus_labels": list(focus_labels),
    }


def _classified_result(
    *,
    intent_direction_label: str,
    rule_id: str,
    evidence_count: int,
    evidence_summary: Mapping[str, Any],
    unresolved_or_missing_count: int,
) -> MarketIntentClassificationResult:
    """Constructor helper for the priority 2–7 branches.

    Confidence formula (deterministic, documented):
    ``0.5 + 0.05 * evidence_count``, clamped to ``[0.5, 0.75]``
    over the 0–5 evidence-source range. So ``evidence_count = 1``
    → 0.55, ``evidence_count = 5`` → 0.75. Higher confidence when
    more evidence sources are present *and* a specific rule fires.
    """
    confidence = min(0.5 + 0.05 * evidence_count, 0.75)
    return MarketIntentClassificationResult(
        intent_direction_label=intent_direction_label,
        rule_id=rule_id,
        status="classified",
        confidence=confidence,
        evidence_summary=evidence_summary,
        unresolved_or_missing_count=unresolved_or_missing_count,
    )


def classify_market_intent_direction(
    *,
    investor_intent_direction: str = "unknown",
    valuation_confidence: float | None = None,
    firm_market_access_pressure: float | None = None,
    market_environment_access_label: str = "unknown",
    attention_focus_labels: Iterable[str] = (),
) -> MarketIntentClassificationResult:
    """Classify one investor's market-interest direction toward a
    listed security from cited evidence.

    The function is **pure**: same inputs → byte-identical output.
    It accepts no kernel argument and reads no global state. The
    caller is responsible for resolving evidence (typically via
    the v1.12.3 :class:`EvidenceResolver` or by reading specific
    record ids) and passing the small abstract inputs below.

    Parameters
    ----------
    investor_intent_direction
        Per-investor / per-firm review-posture direction (v1.12.1
        ``InvestorIntentRecord.intent_direction``). Pass
        ``"unknown"`` if no intent is cited.
    valuation_confidence
        Aggregated valuation confidence in ``[0.0, 1.0]`` (v1.9.5
        / v1.12.5 ``ValuationRecord.confidence``). Pass ``None``
        if no valuation is cited. Booleans rejected.
    firm_market_access_pressure
        Firm latent market-access pressure in ``[0.0, 1.0]``
        (v1.12.0 ``FirmFinancialStateRecord.market_access_pressure``).
        Pass ``None`` if no firm state is cited. Booleans rejected.
    market_environment_access_label
        Per-period market-environment overall access label (v1.12.2
        ``MarketEnvironmentStateRecord.overall_market_access_regime_label``).
        Pass ``"unknown"`` if no environment is cited. Permissive —
        the rule table only checks membership in small fixed sets.
    attention_focus_labels
        Tuple of v1.12.8 focus labels for this actor in this period
        (``ActorAttentionStateRecord.focus_labels``). Pass ``()`` if
        no attention state is cited.

    Returns
    -------
    MarketIntentClassificationResult
        Immutable result naming the chosen
        ``intent_direction_label`` (∈
        :data:`world.market_intents.INTENT_DIRECTION_LABELS`), the
        ``rule_id`` that fired, a synthetic confidence in
        ``[0.0, 1.0]``, the ``evidence_summary`` the classifier
        saw, the ``unresolved_or_missing_count`` (0–5), and a
        free-form ``metadata`` mapping.

    Notes
    -----
    The function does **not** accept ``period_idx`` /
    ``investor_idx`` / ``firm_idx``. The v1.15.5 four-cycle
    rotation those indices drove is the thing v1.16 replaces. The
    success condition (pinned by tests) is that two calls with the
    same evidence return the **same** label, and two calls with
    different evidence may return **different** labels — without
    any positional input.
    """

    investor_intent_direction = _validate_required_label(
        investor_intent_direction, field_name="investor_intent_direction"
    )
    valuation_confidence = _validate_optional_unit(
        valuation_confidence, field_name="valuation_confidence"
    )
    firm_market_access_pressure = _validate_optional_unit(
        firm_market_access_pressure,
        field_name="firm_market_access_pressure",
    )
    market_environment_access_label = _validate_required_label(
        market_environment_access_label,
        field_name="market_environment_access_label",
    )
    focus_labels = _validate_string_tuple(
        attention_focus_labels, field_name="attention_focus_labels"
    )

    has_intent = investor_intent_direction != "unknown"
    has_valuation = valuation_confidence is not None
    has_firm_pressure = firm_market_access_pressure is not None
    has_mes = market_environment_access_label != "unknown"
    has_focus = bool(focus_labels)

    evidence_count = sum(
        [has_intent, has_valuation, has_firm_pressure, has_mes, has_focus]
    )
    unresolved_or_missing_count = 5 - evidence_count

    evidence_summary = _build_evidence_summary(
        investor_intent_direction=investor_intent_direction,
        valuation_confidence=valuation_confidence,
        firm_market_access_pressure=firm_market_access_pressure,
        market_environment_access_label=market_environment_access_label,
        focus_labels=focus_labels,
        has_intent=has_intent,
        has_mes=has_mes,
    )

    # ----- Priority 1 — every input absent / unknown ----------------------
    if evidence_count == 0:
        return MarketIntentClassificationResult(
            intent_direction_label="unknown",
            rule_id="priority_1_evidence_deficient",
            status="evidence_deficient",
            confidence=0.0,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    focus_set = set(focus_labels)
    high_pressure = (
        has_firm_pressure and firm_market_access_pressure >= 0.7
    )
    constrained_env = (
        has_mes
        and market_environment_access_label in CONSTRAINED_MES_LABELS
    )
    selective_or_constrained_env = (
        has_mes
        and market_environment_access_label in SELECTIVE_OR_CONSTRAINED_MES_LABELS
    )
    constructive_env = (
        has_mes
        and market_environment_access_label in CONSTRUCTIVE_MES_LABELS
    )

    # ----- Priority 2 — engagement-linked review --------------------------
    if (
        investor_intent_direction in ENGAGEMENT_INVESTOR_INTENTS
        and focus_set & ENGAGEMENT_FOCUS_LABELS
    ):
        return _classified_result(
            intent_direction_label="engagement_linked_review",
            rule_id="priority_2_engagement_linked_review",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    # ----- Priority 3 — risk-reduction review -----------------------------
    if investor_intent_direction in RISK_FLAG_INVESTOR_INTENTS:
        return _classified_result(
            intent_direction_label="risk_reduction_review",
            rule_id="priority_3a_risk_flag_watch",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )
    if (
        investor_intent_direction in DUE_DILIGENCE_INVESTOR_INTENTS
        and (high_pressure or constrained_env)
    ):
        return _classified_result(
            intent_direction_label="risk_reduction_review",
            rule_id="priority_3b_due_diligence_pressure",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    # ----- Priority 4 — liquidity watch -----------------------------------
    if (
        focus_set & LIQUIDITY_FUNDING_FOCUS_LABELS
        and selective_or_constrained_env
    ):
        return _classified_result(
            intent_direction_label="liquidity_watch",
            rule_id="priority_4a_liquidity_focus_constrained_env",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )
    if high_pressure and focus_set & LIQUIDITY_FUNDING_FOCUS_LABELS:
        return _classified_result(
            intent_direction_label="liquidity_watch",
            rule_id="priority_4b_high_pressure_liquidity_focus",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    # ----- Priority 5 — reduce interest -----------------------------------
    if (
        has_valuation
        and valuation_confidence < 0.4
        and constrained_env
    ):
        return _classified_result(
            intent_direction_label="reduce_interest",
            rule_id="priority_5a_low_confidence_constrained_env",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )
    if (
        investor_intent_direction in DUE_DILIGENCE_INVESTOR_INTENTS
        and has_valuation
        and valuation_confidence < 0.5
        and has_firm_pressure
        and firm_market_access_pressure >= 0.5
    ):
        return _classified_result(
            intent_direction_label="reduce_interest",
            rule_id="priority_5b_due_diligence_pressure_low_confidence",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    # ----- Priority 6 — increase interest ---------------------------------
    if (
        has_valuation
        and valuation_confidence >= 0.6
        and has_firm_pressure
        and firm_market_access_pressure < 0.4
        and constructive_env
        and investor_intent_direction in ROUTINE_OR_ENGAGEMENT_INTENTS
    ):
        return _classified_result(
            intent_direction_label="increase_interest",
            rule_id="priority_6_high_confidence_low_pressure_constructive",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    # ----- Priority 7 — rebalance review ----------------------------------
    if focus_set & FIRM_VALUATION_MARKET_FOCUS_LABELS:
        return _classified_result(
            intent_direction_label="rebalance_review",
            rule_id="priority_7_firm_valuation_market_focus",
            evidence_count=evidence_count,
            evidence_summary=evidence_summary,
            unresolved_or_missing_count=unresolved_or_missing_count,
        )

    # ----- Priority 8 — default fallback ----------------------------------
    return MarketIntentClassificationResult(
        intent_direction_label="hold_review",
        rule_id="priority_8_default",
        status="default_fallback",
        confidence=0.3,
        evidence_summary=evidence_summary,
        unresolved_or_missing_count=unresolved_or_missing_count,
    )
