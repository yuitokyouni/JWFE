"""
Tests for v1.16.1 endogenous market-intent direction classifier.
"""

from __future__ import annotations

import inspect

import pytest

from world.market_intent_classifier import (
    FIRM_VALUATION_MARKET_FOCUS_LABELS,
    FORBIDDEN_OUTPUT_LABELS,
    MarketIntentClassificationResult,
    classify_market_intent_direction,
)
from world.market_intents import INTENT_DIRECTION_LABELS


# ---------------------------------------------------------------------------
# Module-level invariants
# ---------------------------------------------------------------------------


def test_forbidden_labels_are_disjoint_from_output_vocabulary():
    """The closed-set output vocabulary
    (``INTENT_DIRECTION_LABELS``) and the forbidden trade-
    instruction verbs (``FORBIDDEN_OUTPUT_LABELS``) are disjoint
    by construction. Closed-set membership on the result's
    ``intent_direction_label`` field rejects every forbidden verb
    structurally."""
    assert FORBIDDEN_OUTPUT_LABELS.isdisjoint(INTENT_DIRECTION_LABELS)


def test_signature_does_not_accept_period_idx_or_actor_indices():
    """The whole point of v1.16.1 is to replace v1.15.5's
    rotation-by-position. The classifier must not accept any
    positional index input that could re-introduce rotation."""
    sig = inspect.signature(classify_market_intent_direction)
    forbidden_param_names = {
        "period_idx",
        "investor_idx",
        "firm_idx",
        "period_index",
        "investor_index",
        "firm_index",
        "rotation_index",
    }
    leaked = set(sig.parameters.keys()) & forbidden_param_names
    assert not leaked, (
        f"classify_market_intent_direction must not accept "
        f"index inputs that could re-introduce rotation; leaked: "
        f"{sorted(leaked)}"
    )


def test_module_does_not_import_runtime_books():
    """The classifier module is runtime-book-free by
    construction. It must not import ``Ledger``, ``WorldKernel``,
    ``InvestorMarketIntentBook``, or any other source-of-truth
    book — taking a kernel argument is the only way to mutate
    state, and the classifier accepts none.

    Permitted imports: ``world.market_intents`` (only for the
    closed-set vocabulary :data:`INTENT_DIRECTION_LABELS`).
    """
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parent.parent
        / "world"
        / "market_intent_classifier.py"
    )
    text = module_path.read_text(encoding="utf-8")
    forbidden_imports = (
        "from world.ledger ",
        "from world.kernel ",
        "from world.market_intents import InvestorMarketIntent",
        "from world.market_intents import Investor",
        "from world.market_intents import Duplicate",
        "from world.market_intents import Unknown",
        "from world.market_interest ",
        "from world.market_pressure ",
        "from world.securities ",
        "from world.investor_intent ",
        "from world.valuations ",
        "from world.firm_state ",
        "from world.market_environment ",
        "from world.attention ",
        "from world.attention_feedback ",
    )
    for needle in forbidden_imports:
        assert needle not in text, (
            f"market_intent_classifier.py must not contain {needle!r} "
            "(runtime-book-free by construction)"
        )


# ---------------------------------------------------------------------------
# Result dataclass — field validation
# ---------------------------------------------------------------------------


def test_result_rejects_label_outside_intent_direction_labels():
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="not_a_real_label",
            rule_id="x",
            status="classified",
            confidence=0.5,
        )


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_OUTPUT_LABELS))
def test_result_rejects_every_forbidden_trade_instruction_verb(forbidden):
    """Belt-and-braces: even though the closed-set check on
    ``intent_direction_label`` would already reject every
    forbidden verb (because none is in
    ``INTENT_DIRECTION_LABELS``), the dataclass also explicitly
    refuses them. A future contributor who accidentally adds
    ``"buy"`` to ``INTENT_DIRECTION_LABELS`` would still be
    blocked here."""
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label=forbidden,
            rule_id="x",
            status="classified",
            confidence=0.5,
        )


def test_result_rejects_empty_required_strings():
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="",
            rule_id="x",
            status="classified",
            confidence=0.5,
        )
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="hold_review",
            rule_id="",
            status="classified",
            confidence=0.5,
        )
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="hold_review",
            rule_id="x",
            status="",
            confidence=0.5,
        )


def test_result_rejects_bool_confidence():
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="hold_review",
            rule_id="x",
            status="classified",
            confidence=True,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_result_rejects_out_of_range_confidence(bad):
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="hold_review",
            rule_id="x",
            status="classified",
            confidence=bad,
        )


def test_result_rejects_negative_unresolved_count():
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="hold_review",
            rule_id="x",
            status="classified",
            confidence=0.5,
            unresolved_or_missing_count=-1,
        )


def test_result_rejects_bool_unresolved_count():
    with pytest.raises(ValueError):
        MarketIntentClassificationResult(
            intent_direction_label="hold_review",
            rule_id="x",
            status="classified",
            confidence=0.5,
            unresolved_or_missing_count=True,  # type: ignore[arg-type]
        )


def test_result_is_frozen():
    r = MarketIntentClassificationResult(
        intent_direction_label="hold_review",
        rule_id="x",
        status="classified",
        confidence=0.5,
    )
    with pytest.raises(Exception):
        r.intent_direction_label = "tampered"  # type: ignore[misc]


def test_result_to_dict_round_trips():
    r = MarketIntentClassificationResult(
        intent_direction_label="hold_review",
        rule_id="rule_abc",
        status="classified",
        confidence=0.5,
        evidence_summary={"k": "v"},
        unresolved_or_missing_count=2,
        metadata={"note": "synthetic"},
    )
    out = r.to_dict()
    assert out == {
        "intent_direction_label": "hold_review",
        "rule_id": "rule_abc",
        "status": "classified",
        "confidence": 0.5,
        "evidence_summary": {"k": "v"},
        "unresolved_or_missing_count": 2,
        "metadata": {"note": "synthetic"},
    }


# ---------------------------------------------------------------------------
# Classifier — input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"investor_intent_direction": ""},
        {"market_environment_access_label": ""},
    ],
)
def test_classifier_rejects_empty_required_string_inputs(kwargs):
    with pytest.raises(ValueError):
        classify_market_intent_direction(**kwargs)


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_classifier_rejects_out_of_range_valuation_confidence(bad):
    with pytest.raises(ValueError):
        classify_market_intent_direction(valuation_confidence=bad)


@pytest.mark.parametrize("bad", [-0.01, 1.01, -1.0, 2.0])
def test_classifier_rejects_out_of_range_firm_pressure(bad):
    with pytest.raises(ValueError):
        classify_market_intent_direction(firm_market_access_pressure=bad)


def test_classifier_rejects_bool_valuation_confidence():
    with pytest.raises(ValueError):
        classify_market_intent_direction(valuation_confidence=True)  # type: ignore[arg-type]


def test_classifier_rejects_bool_firm_pressure():
    with pytest.raises(ValueError):
        classify_market_intent_direction(firm_market_access_pressure=True)  # type: ignore[arg-type]


def test_classifier_rejects_non_numeric_confidence():
    with pytest.raises(ValueError):
        classify_market_intent_direction(valuation_confidence="0.5")  # type: ignore[arg-type]


def test_classifier_rejects_empty_string_in_focus_labels():
    with pytest.raises(ValueError):
        classify_market_intent_direction(attention_focus_labels=("",))


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_classifier_accepts_in_range_valuation_confidence(good):
    classify_market_intent_direction(valuation_confidence=good)


@pytest.mark.parametrize("good", [0.0, 0.5, 1.0])
def test_classifier_accepts_in_range_firm_pressure(good):
    classify_market_intent_direction(firm_market_access_pressure=good)


# ---------------------------------------------------------------------------
# Priority 1 — evidence-deficient
# ---------------------------------------------------------------------------


def test_priority_1_all_inputs_unknown_returns_unknown():
    r = classify_market_intent_direction()
    assert r.intent_direction_label == "unknown"
    assert r.rule_id == "priority_1_evidence_deficient"
    assert r.status == "evidence_deficient"
    assert r.confidence == 0.0
    assert r.unresolved_or_missing_count == 5


def test_priority_1_explicit_unknowns_returns_unknown():
    r = classify_market_intent_direction(
        investor_intent_direction="unknown",
        valuation_confidence=None,
        firm_market_access_pressure=None,
        market_environment_access_label="unknown",
        attention_focus_labels=(),
    )
    assert r.intent_direction_label == "unknown"


# ---------------------------------------------------------------------------
# Priority 2 — engagement_linked_review
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "focus", [("engagement",), ("dialogue",), ("stewardship_theme",), ("stewardship",)]
)
def test_priority_2_engagement_watch_with_engagement_focus_fires(focus):
    r = classify_market_intent_direction(
        investor_intent_direction="engagement_watch",
        attention_focus_labels=focus,
    )
    assert r.intent_direction_label == "engagement_linked_review"
    assert r.rule_id == "priority_2_engagement_linked_review"
    assert r.status == "classified"


def test_priority_2_engagement_watch_without_engagement_focus_does_not_fire():
    """``engagement_watch`` alone (no engagement focus) should NOT
    trigger priority 2; the engagement-linked rule requires both
    the intent direction *and* the focus theme."""
    r = classify_market_intent_direction(
        investor_intent_direction="engagement_watch",
        attention_focus_labels=("liquidity",),
        market_environment_access_label="constrained",
    )
    # falls through to priority 4 (liquidity focus + constrained env)
    assert r.intent_direction_label == "liquidity_watch"


# ---------------------------------------------------------------------------
# Priority 3 — risk_reduction_review
# ---------------------------------------------------------------------------


def test_priority_3a_risk_flag_watch_fires_unconditionally():
    r = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
    )
    assert r.intent_direction_label == "risk_reduction_review"
    assert r.rule_id == "priority_3a_risk_flag_watch"


def test_priority_3a_risk_flag_watch_dominates_other_inputs():
    """Even with high valuation confidence + open env + low firm
    pressure (which would otherwise trip priority 6), risk_flag_watch
    wins because priority 3 sits above priority 6."""
    r = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
        valuation_confidence=0.9,
        firm_market_access_pressure=0.1,
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label == "risk_reduction_review"


def test_priority_3b_due_diligence_high_pressure_fires():
    r = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        firm_market_access_pressure=0.7,
    )
    assert r.intent_direction_label == "risk_reduction_review"
    assert r.rule_id == "priority_3b_due_diligence_pressure"


def test_priority_3b_due_diligence_constrained_env_fires():
    r = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        market_environment_access_label="constrained",
    )
    assert r.intent_direction_label == "risk_reduction_review"
    assert r.rule_id == "priority_3b_due_diligence_pressure"


def test_priority_3b_due_diligence_closed_env_fires():
    r = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        market_environment_access_label="closed",
    )
    assert r.intent_direction_label == "risk_reduction_review"


def test_priority_3b_due_diligence_low_pressure_open_env_does_not_fire():
    """``deepen_due_diligence`` alone with healthy environment
    should NOT fire priority 3b — neither high pressure nor
    constrained env triggers."""
    r = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        firm_market_access_pressure=0.2,
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label != "risk_reduction_review"


# ---------------------------------------------------------------------------
# Priority 4 — liquidity_watch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("focus", [("liquidity",), ("funding",), ("liquidity", "funding")])
@pytest.mark.parametrize(
    "env", ["selective", "constrained", "closed"]
)
def test_priority_4a_liquidity_focus_constrained_env_fires(focus, env):
    r = classify_market_intent_direction(
        attention_focus_labels=focus,
        market_environment_access_label=env,
    )
    assert r.intent_direction_label == "liquidity_watch"
    assert r.rule_id == "priority_4a_liquidity_focus_constrained_env"


def test_priority_4b_high_pressure_liquidity_focus_fires():
    """High firm pressure + liquidity focus should fire priority
    4b even when the environment is otherwise unstressed."""
    r = classify_market_intent_direction(
        firm_market_access_pressure=0.8,
        attention_focus_labels=("liquidity",),
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label == "liquidity_watch"
    assert r.rule_id == "priority_4b_high_pressure_liquidity_focus"


def test_priority_4_liquidity_focus_open_env_low_pressure_does_not_fire():
    r = classify_market_intent_direction(
        firm_market_access_pressure=0.2,
        attention_focus_labels=("liquidity",),
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label != "liquidity_watch"


# ---------------------------------------------------------------------------
# Priority 5 — reduce_interest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["constrained", "closed"])
def test_priority_5a_low_confidence_constrained_env_fires(env):
    r = classify_market_intent_direction(
        valuation_confidence=0.3,
        market_environment_access_label=env,
    )
    assert r.intent_direction_label == "reduce_interest"
    assert r.rule_id == "priority_5a_low_confidence_constrained_env"


def test_priority_5a_low_confidence_open_env_does_not_fire():
    r = classify_market_intent_direction(
        valuation_confidence=0.3,
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label != "reduce_interest"


def test_priority_5b_due_diligence_low_confidence_high_pressure_fires():
    r = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        valuation_confidence=0.4,
        firm_market_access_pressure=0.6,
        market_environment_access_label="selective",
    )
    # Note: priority 3b also fires on (deepen_due_diligence, high
    # pressure). The 0.6 threshold here is below the 0.7 high-
    # pressure cutoff, and the env is "selective" (not
    # constrained), so priority 3b does NOT fire. This isolates
    # priority 5b.
    assert r.intent_direction_label == "reduce_interest"
    assert r.rule_id == "priority_5b_due_diligence_pressure_low_confidence"


# ---------------------------------------------------------------------------
# Priority 6 — increase_interest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "env", ["open", "open_or_constructive", "constructive"]
)
@pytest.mark.parametrize("intent", ["routine", "engagement_watch"])
def test_priority_6_increase_interest_fires(env, intent):
    r = classify_market_intent_direction(
        investor_intent_direction=intent,
        valuation_confidence=0.7,
        firm_market_access_pressure=0.2,
        market_environment_access_label=env,
    )
    assert r.intent_direction_label == "increase_interest"
    assert r.rule_id == "priority_6_high_confidence_low_pressure_constructive"


def test_priority_6_engagement_watch_with_engagement_focus_loses_to_priority_2():
    """If engagement_watch + engagement focus AND priority-6
    conditions are simultaneously true, priority 2 wins (higher
    in the table)."""
    r = classify_market_intent_direction(
        investor_intent_direction="engagement_watch",
        valuation_confidence=0.7,
        firm_market_access_pressure=0.2,
        market_environment_access_label="open_or_constructive",
        attention_focus_labels=("engagement",),
    )
    assert r.intent_direction_label == "engagement_linked_review"


def test_priority_6_low_confidence_does_not_fire():
    r = classify_market_intent_direction(
        investor_intent_direction="routine",
        valuation_confidence=0.5,  # below 0.6 cutoff
        firm_market_access_pressure=0.2,
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label != "increase_interest"


def test_priority_6_high_pressure_does_not_fire():
    r = classify_market_intent_direction(
        investor_intent_direction="routine",
        valuation_confidence=0.7,
        firm_market_access_pressure=0.5,  # above 0.4 cutoff
        market_environment_access_label="open_or_constructive",
    )
    assert r.intent_direction_label != "increase_interest"


def test_priority_6_constrained_env_does_not_fire():
    r = classify_market_intent_direction(
        investor_intent_direction="routine",
        valuation_confidence=0.7,
        firm_market_access_pressure=0.2,
        market_environment_access_label="constrained",
    )
    assert r.intent_direction_label != "increase_interest"


# ---------------------------------------------------------------------------
# Priority 7 — rebalance_review
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "focus", [("firm_state",), ("valuation",), ("market_environment",), ("market_condition",)]
)
def test_priority_7_firm_or_valuation_focus_fires(focus):
    r = classify_market_intent_direction(
        attention_focus_labels=focus,
    )
    assert r.intent_direction_label == "rebalance_review"
    assert r.rule_id == "priority_7_firm_valuation_market_focus"


# ---------------------------------------------------------------------------
# Priority 8 — default fallback
# ---------------------------------------------------------------------------


def test_priority_8_default_returns_hold_review():
    """Some evidence is present (a routine intent) but no specific
    rule fires → default fallback to ``hold_review``."""
    r = classify_market_intent_direction(
        investor_intent_direction="routine",
    )
    assert r.intent_direction_label == "hold_review"
    assert r.rule_id == "priority_8_default"
    assert r.status == "default_fallback"
    assert r.confidence == 0.3


def test_priority_8_default_fires_with_some_evidence_but_no_rule_match():
    """Investor in routine review, no useful focus, neutral
    valuation, healthy firm, no environment evidence → no rule
    fires → default."""
    r = classify_market_intent_direction(
        investor_intent_direction="routine",
        valuation_confidence=0.5,
        firm_market_access_pressure=0.5,
    )
    assert r.intent_direction_label == "hold_review"


# ---------------------------------------------------------------------------
# Priority ordering — multi-trigger cases
# ---------------------------------------------------------------------------


def test_priority_3_beats_priority_4():
    """``risk_flag_watch`` (priority 3) wins even when liquidity
    focus + constrained env (priority 4) is also true."""
    r = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
        attention_focus_labels=("liquidity",),
        market_environment_access_label="constrained",
    )
    assert r.intent_direction_label == "risk_reduction_review"


def test_priority_3b_beats_priority_5b_when_pressure_is_high():
    """Both priority 3b (deepen_due_diligence + high pressure /
    constrained env) and priority 5b (deepen_due_diligence + low
    confidence + moderate pressure) read the same intent. When
    pressure is high enough to trip 3b, 3b wins because it sits
    above 5b."""
    r = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        valuation_confidence=0.3,  # would trigger 5b on its own with selective
        firm_market_access_pressure=0.8,  # high → trips 3b
        market_environment_access_label="selective",
    )
    assert r.intent_direction_label == "risk_reduction_review"
    assert r.rule_id == "priority_3b_due_diligence_pressure"


def test_priority_4_beats_priority_5_when_constrained_and_liquidity_focus():
    """Liquidity focus + constrained env + low confidence: both
    priority 4 (liquidity_watch) and priority 5a (reduce_interest
    on low confidence + constrained env) would fire. Priority 4
    is higher → liquidity_watch wins."""
    r = classify_market_intent_direction(
        valuation_confidence=0.3,
        market_environment_access_label="constrained",
        attention_focus_labels=("liquidity",),
    )
    assert r.intent_direction_label == "liquidity_watch"


def test_priority_2_beats_priority_7_when_engagement_focus_present():
    """``engagement`` is in both ENGAGEMENT_FOCUS_LABELS and would
    not trigger priority 7 (which uses firm/valuation/market
    focus). With engagement_watch + engagement focus, priority 2
    fires before priority 7 has a chance."""
    r = classify_market_intent_direction(
        investor_intent_direction="engagement_watch",
        attention_focus_labels=("engagement", "valuation"),
    )
    assert r.intent_direction_label == "engagement_linked_review"


# ---------------------------------------------------------------------------
# v1.16 success condition — endogeneity, not rotation
# ---------------------------------------------------------------------------


def test_same_evidence_always_returns_same_label():
    """Determinism: byte-identical inputs → byte-identical outputs.
    There is no period_idx, no random seed, no time, and no
    global state to perturb."""
    kwargs = {
        "investor_intent_direction": "deepen_due_diligence",
        "valuation_confidence": 0.4,
        "firm_market_access_pressure": 0.7,
        "market_environment_access_label": "constrained",
        "attention_focus_labels": ("firm_state",),
    }
    r1 = classify_market_intent_direction(**kwargs)
    r2 = classify_market_intent_direction(**kwargs)
    assert r1.to_dict() == r2.to_dict()


def test_no_period_idx_dependence_regression():
    """The v1.15.5 rotation drove direction by
    ``(period_idx + investor_idx + firm_idx) % 4``. v1.16.1's
    classifier accepts no positional inputs at all — there is
    no kwarg the caller could pass that would simulate a
    period change. The signature test (above) pins the
    parameter list; this test pins that two calls with
    identical evidence are identical *even when called many
    times*."""
    kwargs = {
        "investor_intent_direction": "engagement_watch",
        "attention_focus_labels": ("engagement",),
    }
    results = [classify_market_intent_direction(**kwargs) for _ in range(5)]
    first = results[0].to_dict()
    for r in results[1:]:
        assert r.to_dict() == first


def test_evidence_difference_can_change_label_for_same_pair():
    """The v1.16 success condition: the same ``(investor,
    security)`` pair can produce **different** safe labels because
    the evidence context differs. Here we simulate the same
    investor+security across two regimes — same caller — and the
    classifier returns different labels."""
    constructive = classify_market_intent_direction(
        investor_intent_direction="routine",
        valuation_confidence=0.7,
        firm_market_access_pressure=0.2,
        market_environment_access_label="open_or_constructive",
    )
    constrained = classify_market_intent_direction(
        investor_intent_direction="deepen_due_diligence",
        valuation_confidence=0.3,
        firm_market_access_pressure=0.8,
        market_environment_access_label="closed",
    )
    assert constructive.intent_direction_label == "increase_interest"
    assert constrained.intent_direction_label == "risk_reduction_review"
    assert constructive.intent_direction_label != constrained.intent_direction_label


# ---------------------------------------------------------------------------
# Confidence + evidence count
# ---------------------------------------------------------------------------


def test_confidence_zero_when_evidence_deficient():
    r = classify_market_intent_direction()
    assert r.confidence == 0.0


def test_confidence_03_when_default_fallback():
    r = classify_market_intent_direction(
        investor_intent_direction="routine",
    )
    assert r.confidence == 0.3


def test_confidence_increases_with_more_evidence():
    """Specific-rule branches assign confidence as
    ``0.5 + 0.05 * evidence_count``."""
    one_source = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
    )
    five_sources = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
        valuation_confidence=0.5,
        firm_market_access_pressure=0.5,
        market_environment_access_label="selective",
        attention_focus_labels=("firm_state",),
    )
    assert one_source.intent_direction_label == "risk_reduction_review"
    assert five_sources.intent_direction_label == "risk_reduction_review"
    assert five_sources.confidence > one_source.confidence


def test_unresolved_count_matches_missing_inputs():
    r = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
    )
    assert r.unresolved_or_missing_count == 4

    r2 = classify_market_intent_direction(
        investor_intent_direction="risk_flag_watch",
        valuation_confidence=0.5,
        firm_market_access_pressure=0.5,
        market_environment_access_label="selective",
        attention_focus_labels=("firm_state",),
    )
    assert r2.unresolved_or_missing_count == 0


# ---------------------------------------------------------------------------
# Output vocabulary — exhaustive
# ---------------------------------------------------------------------------


def test_every_classifier_output_is_in_intent_direction_labels():
    """Drive the classifier through a representative grid and
    assert that every returned ``intent_direction_label`` is in
    the closed-set output vocabulary."""
    grid = [
        # priority 1
        {},
        # priority 2
        {
            "investor_intent_direction": "engagement_watch",
            "attention_focus_labels": ("engagement",),
        },
        # priority 3a
        {"investor_intent_direction": "risk_flag_watch"},
        # priority 3b
        {
            "investor_intent_direction": "deepen_due_diligence",
            "firm_market_access_pressure": 0.8,
        },
        # priority 4a
        {
            "attention_focus_labels": ("liquidity",),
            "market_environment_access_label": "constrained",
        },
        # priority 4b
        {
            "firm_market_access_pressure": 0.8,
            "attention_focus_labels": ("funding",),
        },
        # priority 5a
        {
            "valuation_confidence": 0.3,
            "market_environment_access_label": "closed",
        },
        # priority 5b
        {
            "investor_intent_direction": "deepen_due_diligence",
            "valuation_confidence": 0.4,
            "firm_market_access_pressure": 0.6,
            "market_environment_access_label": "selective",
        },
        # priority 6
        {
            "investor_intent_direction": "routine",
            "valuation_confidence": 0.7,
            "firm_market_access_pressure": 0.2,
            "market_environment_access_label": "open_or_constructive",
        },
        # priority 7
        {"attention_focus_labels": ("firm_state",)},
        # priority 8
        {"investor_intent_direction": "routine"},
    ]
    for kwargs in grid:
        r = classify_market_intent_direction(**kwargs)
        assert r.intent_direction_label in INTENT_DIRECTION_LABELS, kwargs
        assert r.intent_direction_label not in FORBIDDEN_OUTPUT_LABELS, kwargs


def test_priority_7_focus_set_is_exact():
    assert FIRM_VALUATION_MARKET_FOCUS_LABELS == frozenset(
        {"firm_state", "valuation", "market_environment", "market_condition"}
    )


# ---------------------------------------------------------------------------
# Jurisdiction-neutral identifier scan
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
    "target2", "fedwire", "chaps", "bojnet",
)


def test_test_file_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    text = Path(__file__).read_text(encoding="utf-8").lower()
    table_start = text.find("_forbidden_tokens = (")
    table_end = text.find(")", table_start) + 1
    if table_start != -1 and table_end > 0:
        text = text[:table_start] + text[table_end:]
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token


def test_module_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parent.parent
        / "world"
        / "market_intent_classifier.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
