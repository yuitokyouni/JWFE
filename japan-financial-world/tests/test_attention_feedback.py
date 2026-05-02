"""
Tests for v1.12.8 ActorAttentionStateRecord +
AttentionFeedbackRecord + AttentionFeedbackBook +
``build_attention_feedback``.

Covers field validation (including bounded ``confidence`` with
explicit bool rejection), immutability, ``add_*`` deduplication,
unknown lookup, every list / filter method, deterministic
snapshots, ledger emission with the new
``RecordType.ATTENTION_STATE_CREATED`` /
``RecordType.ATTENTION_FEEDBACK_RECORDED``, kernel wiring of the
new ``AttentionFeedbackBook``, the no-mutation guarantee against
every other v0/v1 source-of-truth book in the kernel, the
v1.12.8 deterministic rule set across every priority branch,
chaining through ``previous_attention_state_id``, no-action /
no-pricing / no-allocation invariant, no anti-field payload key,
and a jurisdiction-neutral identifier scan over both module and
test file.

Identifier and tag strings used in this test suite are
jurisdiction-neutral and synthetic.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.attention_feedback import (
    ALL_FOCUS_LABELS,
    FOCUS_LABEL_DIALOGUE,
    FOCUS_LABEL_ENGAGEMENT,
    FOCUS_LABEL_FIRM_STATE,
    FOCUS_LABEL_LIQUIDITY,
    FOCUS_LABEL_MARKET_ENVIRONMENT,
    FOCUS_LABEL_MEMORY,
    FOCUS_LABEL_VALUATION,
    TRIGGER_ENGAGEMENT_INTENT_OBSERVED,
    TRIGGER_LIQUIDITY_CREDIT_REVIEW,
    TRIGGER_RESTRICTIVE_MARKET_OBSERVED,
    TRIGGER_RISK_INTENT_OBSERVED,
    TRIGGER_ROUTINE_OBSERVED,
    TRIGGER_VALUATION_CONFIDENCE_LOW,
    ActorAttentionStateRecord,
    AttentionFeedbackBook,
    AttentionFeedbackRecord,
    DuplicateAttentionFeedbackError,
    DuplicateAttentionStateError,
    UnknownAttentionFeedbackError,
    UnknownAttentionStateError,
    build_attention_feedback,
)
from world.clock import Clock
from world.investor_intent import InvestorIntentRecord
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.market_environment import MarketEnvironmentStateRecord
from world.registry import Registry
from world.scheduler import Scheduler
from world.signals import InformationSignal
from world.state import State
from world.valuations import ValuationRecord


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


_ACTOR = "investor:reference_pension_a"
_ACTOR_TYPE = "investor"
_AS_OF = "2026-03-31"
_FIRM = "firm:reference_manufacturer_a"


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 3, 31)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _state(
    *,
    attention_state_id: str = "attention_state:investor:reference_pension_a:2026-03-31",
    actor_id: str = _ACTOR,
    actor_type: str = _ACTOR_TYPE,
    as_of_date: str = _AS_OF,
    status: str = "active",
    confidence: float = 0.7,
    max_selected_refs: int = 8,
    focus_labels: tuple[str, ...] = (FOCUS_LABEL_MEMORY,),
    focus_weights: dict | None = None,
    base_profile_ids: tuple[str, ...] = (),
    source_market_environment_state_ids: tuple[str, ...] = (),
    source_firm_state_ids: tuple[str, ...] = (),
    source_investor_intent_ids: tuple[str, ...] = (),
    source_valuation_ids: tuple[str, ...] = (),
    source_credit_review_signal_ids: tuple[str, ...] = (),
    source_dialogue_ids: tuple[str, ...] = (),
    source_escalation_candidate_ids: tuple[str, ...] = (),
    previous_attention_state_id: str | None = None,
    metadata: dict | None = None,
) -> ActorAttentionStateRecord:
    return ActorAttentionStateRecord(
        attention_state_id=attention_state_id,
        actor_id=actor_id,
        actor_type=actor_type,
        as_of_date=as_of_date,
        status=status,
        confidence=confidence,
        max_selected_refs=max_selected_refs,
        base_profile_ids=base_profile_ids,
        focus_labels=focus_labels,
        focus_weights=focus_weights or {label: 0.5 for label in focus_labels},
        source_market_environment_state_ids=source_market_environment_state_ids,
        source_firm_state_ids=source_firm_state_ids,
        source_investor_intent_ids=source_investor_intent_ids,
        source_valuation_ids=source_valuation_ids,
        source_credit_review_signal_ids=source_credit_review_signal_ids,
        source_dialogue_ids=source_dialogue_ids,
        source_escalation_candidate_ids=source_escalation_candidate_ids,
        previous_attention_state_id=previous_attention_state_id,
        metadata=metadata or {},
    )


def _feedback(
    *,
    feedback_id: str = "attention_feedback:investor:reference_pension_a:2026-03-31",
    actor_id: str = _ACTOR,
    actor_type: str = _ACTOR_TYPE,
    as_of_date: str = _AS_OF,
    new_attention_state_id: str = (
        "attention_state:investor:reference_pension_a:2026-03-31"
    ),
    feedback_type: str = "period_observed_to_next_period",
    trigger_label: str = TRIGGER_ROUTINE_OBSERVED,
    status: str = "recorded",
    confidence: float = 0.7,
    previous_attention_state_id: str | None = None,
    source_record_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> AttentionFeedbackRecord:
    return AttentionFeedbackRecord(
        feedback_id=feedback_id,
        actor_id=actor_id,
        actor_type=actor_type,
        as_of_date=as_of_date,
        new_attention_state_id=new_attention_state_id,
        feedback_type=feedback_type,
        trigger_label=trigger_label,
        status=status,
        confidence=confidence,
        previous_attention_state_id=previous_attention_state_id,
        source_record_ids=source_record_ids,
        metadata=metadata or {},
    )


def _seed_intent(
    kernel: WorldKernel,
    *,
    direction: str,
    intent_id: str | None = None,
    investor_id: str = _ACTOR,
    target_company_id: str = _FIRM,
    as_of_date: str = _AS_OF,
) -> str:
    iid = intent_id or f"intent:{investor_id}:{target_company_id}:{direction}"
    type_for_direction = {
        "risk_flag_watch": "risk_review",
        "deepen_due_diligence": "risk_review",
        "engagement_watch": "engagement_review",
        "decrease_confidence": "confidence_adjustment",
        "hold_review": "watch_adjustment",
    }.get(direction, "watch_adjustment")
    kernel.investor_intents.add_intent(
        InvestorIntentRecord(
            intent_id=iid,
            investor_id=investor_id,
            target_company_id=target_company_id,
            as_of_date=as_of_date,
            intent_type=type_for_direction,
            intent_direction=direction,
            priority="medium",
            horizon="medium_term",
            status="active",
            visibility="internal_only",
            confidence=0.5,
        )
    )
    return iid


def _seed_credit_review_signal(
    kernel: WorldKernel,
    *,
    watch_label: str,
    signal_id: str | None = None,
    bank_id: str = "bank:reference_megabank_a",
    firm_id: str = _FIRM,
    as_of_date: str = _AS_OF,
) -> str:
    sid = (
        signal_id
        or f"signal:bank_credit_review_note:{bank_id}:{firm_id}:{watch_label}"
    )
    kernel.signals.add_signal(
        InformationSignal(
            signal_id=sid,
            signal_type="bank_credit_review_note",
            subject_id=firm_id,
            source_id=bank_id,
            published_date=as_of_date,
            payload={"watch_label": watch_label},
            visibility="public",
        )
    )
    return sid


def _seed_market_env(
    kernel: WorldKernel,
    *,
    overall: str,
    env_id: str | None = None,
    as_of_date: str = _AS_OF,
) -> str:
    eid = env_id or f"market_environment:{overall}:{as_of_date}"
    kernel.market_environments.add_state(
        MarketEnvironmentStateRecord(
            environment_state_id=eid,
            as_of_date=as_of_date,
            liquidity_regime="normal",
            volatility_regime="calm",
            credit_regime="neutral",
            funding_regime="normal",
            risk_appetite_regime="neutral",
            rate_environment="low",
            refinancing_window="open",
            equity_valuation_regime="neutral",
            overall_market_access_label=overall,
            status="active",
            visibility="internal_only",
            confidence=0.5,
        )
    )
    return eid


def _seed_low_confidence_valuation(
    kernel: WorldKernel,
    *,
    valuation_id: str = "valuation:low_conf",
    confidence: float = 0.2,
    firm_id: str = _FIRM,
    valuer_id: str = _ACTOR,
    as_of_date: str = _AS_OF,
) -> str:
    kernel.valuations.add_valuation(
        ValuationRecord(
            valuation_id=valuation_id,
            subject_id=firm_id,
            valuer_id=valuer_id,
            valuation_type="reference_synthetic",
            purpose="reference_synthetic_purpose",
            method="dcf",
            as_of_date=as_of_date,
            estimated_value=100.0,
            currency="reference_unit",
            confidence=confidence,
        )
    )
    return valuation_id


# ---------------------------------------------------------------------------
# ActorAttentionStateRecord — field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"attention_state_id": ""},
        {"actor_id": ""},
        {"actor_type": ""},
        {"as_of_date": ""},
        {"status": ""},
    ],
)
def test_state_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _state(**kwargs)


@pytest.mark.parametrize("value", [-0.01, 1.01, -1.0, 1.5, 100.0])
def test_state_confidence_rejects_out_of_range(value):
    with pytest.raises(ValueError):
        _state(confidence=value)


@pytest.mark.parametrize("value", [0.0, 0.5, 1.0])
def test_state_confidence_accepts_in_range(value):
    s = _state(confidence=value)
    assert s.confidence == float(value)


def test_state_confidence_rejects_bool_true():
    with pytest.raises(ValueError):
        _state(confidence=True)


def test_state_confidence_rejects_bool_false():
    with pytest.raises(ValueError):
        _state(confidence=False)


@pytest.mark.parametrize("value", ["high", None, [], object()])
def test_state_confidence_rejects_non_numeric(value):
    with pytest.raises(ValueError):
        _state(confidence=value)


def test_state_max_selected_refs_rejects_negative():
    with pytest.raises(ValueError):
        _state(max_selected_refs=-1)


def test_state_max_selected_refs_rejects_bool():
    with pytest.raises(ValueError):
        _state(max_selected_refs=True)


def test_state_max_selected_refs_rejects_non_int():
    with pytest.raises(ValueError):
        _state(max_selected_refs=1.5)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "base_profile_ids",
        "focus_labels",
        "source_market_environment_state_ids",
        "source_firm_state_ids",
        "source_investor_intent_ids",
        "source_valuation_ids",
        "source_credit_review_signal_ids",
        "source_dialogue_ids",
        "source_escalation_candidate_ids",
    ],
)
def test_state_rejects_empty_strings_in_tuple_fields(tuple_field):
    with pytest.raises(ValueError):
        _state(**{tuple_field: ("",)})


def test_state_focus_weights_must_be_in_unit_interval():
    with pytest.raises(ValueError):
        _state(focus_labels=("firm_state",), focus_weights={"firm_state": 1.5})


def test_state_focus_weights_reject_bool():
    with pytest.raises(ValueError):
        _state(focus_labels=("firm_state",), focus_weights={"firm_state": True})


def test_state_previous_attention_state_id_optional():
    s = _state(previous_attention_state_id=None)
    assert s.previous_attention_state_id is None


def test_state_previous_attention_state_id_must_be_non_empty_string():
    with pytest.raises(ValueError):
        _state(previous_attention_state_id="")


def test_state_coerces_as_of_date_to_iso_string():
    s = _state(as_of_date=date(2026, 3, 31))
    assert s.as_of_date == "2026-03-31"


def test_state_is_frozen():
    s = _state()
    with pytest.raises(Exception):
        s.actor_id = "tampered"  # type: ignore[misc]


def test_state_to_dict_round_trips():
    s = _state(
        focus_labels=(FOCUS_LABEL_FIRM_STATE, FOCUS_LABEL_VALUATION),
        focus_weights={
            FOCUS_LABEL_FIRM_STATE: 0.6,
            FOCUS_LABEL_VALUATION: 0.4,
        },
    )
    out = s.to_dict()
    assert out["focus_labels"] == [
        FOCUS_LABEL_FIRM_STATE,
        FOCUS_LABEL_VALUATION,
    ]
    assert out["focus_weights"] == {
        FOCUS_LABEL_FIRM_STATE: 0.6,
        FOCUS_LABEL_VALUATION: 0.4,
    }


# ---------------------------------------------------------------------------
# AttentionFeedbackRecord — field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"feedback_id": ""},
        {"actor_id": ""},
        {"actor_type": ""},
        {"as_of_date": ""},
        {"new_attention_state_id": ""},
        {"feedback_type": ""},
        {"trigger_label": ""},
        {"status": ""},
    ],
)
def test_feedback_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _feedback(**kwargs)


def test_feedback_confidence_rejects_bool():
    with pytest.raises(ValueError):
        _feedback(confidence=True)


@pytest.mark.parametrize("value", [-0.01, 1.01, 1.5])
def test_feedback_confidence_rejects_out_of_range(value):
    with pytest.raises(ValueError):
        _feedback(confidence=value)


def test_feedback_is_frozen():
    f = _feedback()
    with pytest.raises(Exception):
        f.actor_id = "tampered"  # type: ignore[misc]


def test_feedback_rejects_empty_strings_in_source_record_ids():
    with pytest.raises(ValueError):
        _feedback(source_record_ids=("valid", ""))


def test_feedback_to_dict_round_trips():
    f = _feedback(
        trigger_label=TRIGGER_RISK_INTENT_OBSERVED,
        source_record_ids=("intent:a", "intent:b"),
    )
    out = f.to_dict()
    assert out["trigger_label"] == TRIGGER_RISK_INTENT_OBSERVED
    assert out["source_record_ids"] == ["intent:a", "intent:b"]


# ---------------------------------------------------------------------------
# Anti-fields — no order/trade/recommendation/etc.
# ---------------------------------------------------------------------------


_FORBIDDEN_DATACLASS_FIELDS = {
    "order",
    "order_id",
    "trade",
    "buy",
    "sell",
    "rebalance",
    "target_weight",
    "overweight",
    "underweight",
    "expected_return",
    "target_price",
    "recommendation",
    "investment_advice",
    "portfolio_allocation",
    "execution",
    "forecast_value",
    "actual_value",
    "real_data_value",
    "behavior_probability",
}


def test_attention_state_record_has_no_anti_fields():
    field_names = {f.name for f in dataclass_fields(ActorAttentionStateRecord)}
    leaked = field_names & _FORBIDDEN_DATACLASS_FIELDS
    assert not leaked, leaked


def test_feedback_record_has_no_anti_fields():
    field_names = {f.name for f in dataclass_fields(AttentionFeedbackRecord)}
    leaked = field_names & _FORBIDDEN_DATACLASS_FIELDS
    assert not leaked, leaked


# ---------------------------------------------------------------------------
# Book — CRUD
# ---------------------------------------------------------------------------


def test_book_add_and_get_attention_state():
    book = AttentionFeedbackBook()
    s = _state()
    book.add_attention_state(s)
    assert book.get_attention_state(s.attention_state_id) is s


def test_book_get_unknown_attention_state_raises():
    book = AttentionFeedbackBook()
    with pytest.raises(UnknownAttentionStateError):
        book.get_attention_state("attention_state:missing")
    with pytest.raises(KeyError):
        book.get_attention_state("attention_state:missing")


def test_book_duplicate_attention_state_id_rejected():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state())
    with pytest.raises(DuplicateAttentionStateError):
        book.add_attention_state(_state())


def test_book_add_and_get_feedback():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state())
    f = _feedback()
    book.add_feedback(f)
    assert book.get_feedback(f.feedback_id) is f


def test_book_duplicate_feedback_id_rejected():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state())
    book.add_feedback(_feedback())
    with pytest.raises(DuplicateAttentionFeedbackError):
        book.add_feedback(_feedback())


def test_book_get_unknown_feedback_raises():
    book = AttentionFeedbackBook()
    with pytest.raises(UnknownAttentionFeedbackError):
        book.get_feedback("attention_feedback:missing")
    with pytest.raises(KeyError):
        book.get_feedback("attention_feedback:missing")


# ---------------------------------------------------------------------------
# Listings + latest lookup
# ---------------------------------------------------------------------------


def test_book_list_attention_states_in_insertion_order():
    book = AttentionFeedbackBook()
    a = _state(attention_state_id="attention_state:a")
    b = _state(attention_state_id="attention_state:b")
    book.add_attention_state(a)
    book.add_attention_state(b)
    assert book.list_attention_states() == (a, b)


def test_book_list_by_actor():
    book = AttentionFeedbackBook()
    a = _state(attention_state_id="attention_state:a:2026-03-31", actor_id="actor:a")
    b = _state(attention_state_id="attention_state:b:2026-03-31", actor_id="actor:b")
    book.add_attention_state(a)
    book.add_attention_state(b)
    assert book.list_by_actor("actor:a") == (a,)
    assert book.list_by_actor("actor:b") == (b,)


def test_book_list_by_actor_type():
    book = AttentionFeedbackBook()
    inv = _state(
        attention_state_id="attention_state:inv:2026-03-31",
        actor_type="investor",
    )
    bank = _state(
        attention_state_id="attention_state:bank:2026-03-31",
        actor_id="bank:b",
        actor_type="bank",
    )
    book.add_attention_state(inv)
    book.add_attention_state(bank)
    assert book.list_by_actor_type("investor") == (inv,)
    assert book.list_by_actor_type("bank") == (bank,)


def test_book_list_by_date_filters_exactly():
    book = AttentionFeedbackBook()
    a = _state(
        attention_state_id="attention_state:a:2026-03-31",
        as_of_date="2026-03-31",
    )
    b = _state(
        attention_state_id="attention_state:a:2026-06-30",
        as_of_date="2026-06-30",
    )
    book.add_attention_state(a)
    book.add_attention_state(b)
    assert book.list_by_date("2026-03-31") == (a,)
    assert book.list_by_date("2026-06-30") == (b,)


def test_book_list_by_date_accepts_date_object():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state(as_of_date="2026-03-31"))
    out = book.list_by_date(date(2026, 3, 31))
    assert len(out) == 1


def test_book_get_latest_for_actor_returns_none_when_no_state():
    book = AttentionFeedbackBook()
    assert book.get_latest_for_actor("actor:none") is None


def test_book_get_latest_for_actor_returns_most_recently_added():
    book = AttentionFeedbackBook()
    earlier = _state(
        attention_state_id="attention_state:a:2026-03-31",
        actor_id="actor:a",
        as_of_date="2026-03-31",
    )
    later = _state(
        attention_state_id="attention_state:a:2026-06-30",
        actor_id="actor:a",
        as_of_date="2026-06-30",
    )
    book.add_attention_state(earlier)
    book.add_attention_state(later)
    assert book.get_latest_for_actor("actor:a") is later


def test_book_list_feedback_by_actor():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state())
    a_feedback = _feedback(
        feedback_id="attention_feedback:actor:a:2026-03-31", actor_id="actor:a"
    )
    b_feedback = _feedback(
        feedback_id="attention_feedback:actor:b:2026-03-31", actor_id="actor:b"
    )
    book.add_feedback(a_feedback)
    book.add_feedback(b_feedback)
    assert book.list_feedback_by_actor("actor:a") == (a_feedback,)
    assert book.list_feedback_by_actor("actor:b") == (b_feedback,)


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_book_snapshot_is_deterministic_and_sorted():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state(attention_state_id="attention_state:b"))
    book.add_attention_state(_state(attention_state_id="attention_state:a"))
    book.add_feedback(_feedback(feedback_id="attention_feedback:b"))
    book.add_feedback(_feedback(feedback_id="attention_feedback:a"))
    snap = book.snapshot()
    assert snap["attention_state_count"] == 2
    assert [s["attention_state_id"] for s in snap["attention_states"]] == [
        "attention_state:a",
        "attention_state:b",
    ]
    assert snap["feedback_count"] == 2
    assert [f["feedback_id"] for f in snap["feedbacks"]] == [
        "attention_feedback:a",
        "attention_feedback:b",
    ]


def test_book_snapshot_empty():
    snap = AttentionFeedbackBook().snapshot()
    assert snap["attention_state_count"] == 0
    assert snap["feedback_count"] == 0


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_types_exist():
    assert RecordType.ATTENTION_STATE_CREATED.value == "attention_state_created"
    assert (
        RecordType.ATTENTION_FEEDBACK_RECORDED.value
        == "attention_feedback_recorded"
    )


def test_add_attention_state_writes_one_ledger_record():
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(_state())
    assert len(ledger.records) == 1
    assert ledger.records[0].record_type is RecordType.ATTENTION_STATE_CREATED


def test_add_feedback_writes_one_ledger_record():
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(_state())
    book.add_feedback(_feedback())
    # 2 records: state_created + feedback_recorded
    assert len(ledger.records) == 2
    assert (
        ledger.records[1].record_type is RecordType.ATTENTION_FEEDBACK_RECORDED
    )


def test_attention_state_payload_carries_full_field_set():
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(
        _state(
            focus_labels=(FOCUS_LABEL_FIRM_STATE,),
            focus_weights={FOCUS_LABEL_FIRM_STATE: 0.5},
            source_firm_state_ids=("firm_state:a",),
        )
    )
    payload = ledger.records[0].payload
    expected_keys = {
        "attention_state_id",
        "actor_id",
        "actor_type",
        "as_of_date",
        "status",
        "confidence",
        "max_selected_refs",
        "base_profile_ids",
        "focus_labels",
        "focus_weights",
        "source_firm_state_ids",
        "source_market_environment_state_ids",
        "source_investor_intent_ids",
        "source_valuation_ids",
        "source_credit_review_signal_ids",
        "source_dialogue_ids",
        "source_escalation_candidate_ids",
        "previous_attention_state_id",
    }
    assert set(payload.keys()) >= expected_keys


def test_attention_state_payload_carries_no_anti_field_keys():
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(_state())
    payload = ledger.records[0].payload
    leaked = set(payload.keys()) & _FORBIDDEN_DATACLASS_FIELDS
    assert not leaked


def test_feedback_payload_carries_no_anti_field_keys():
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(_state())
    book.add_feedback(_feedback())
    payload = ledger.records[1].payload
    leaked = set(payload.keys()) & _FORBIDDEN_DATACLASS_FIELDS
    assert not leaked


def test_book_emits_only_attention_event_types():
    """The book must not emit any action / pricing /
    contract-mutation / order / trade record."""
    forbidden_event_types = {
        "order_submitted",
        "price_updated",
        "contract_created",
        "contract_status_updated",
        "contract_covenant_breached",
        "ownership_position_added",
        "ownership_transferred",
        "institution_action_recorded",
        "valuation_added",
    }
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(_state())
    book.add_feedback(_feedback())
    seen = {r.record_type.value for r in ledger.records}
    assert seen.isdisjoint(forbidden_event_types)


def test_book_without_ledger_does_not_raise():
    book = AttentionFeedbackBook()
    book.add_attention_state(_state())
    book.add_feedback(_feedback())


def test_duplicate_add_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = AttentionFeedbackBook(ledger=ledger)
    book.add_attention_state(_state())
    with pytest.raises(DuplicateAttentionStateError):
        book.add_attention_state(_state())
    assert len(ledger.records) == 1


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_attention_feedback_book():
    k = _kernel()
    assert isinstance(k.attention_feedback, AttentionFeedbackBook)
    assert k.attention_feedback.ledger is k.ledger
    assert k.attention_feedback.clock is k.clock


def test_kernel_add_state_emits_to_kernel_ledger():
    k = _kernel()
    k.attention_feedback.add_attention_state(_state())
    records = k.ledger.filter(event_type="attention_state_created")
    assert len(records) == 1


def test_kernel_simulation_date_uses_clock():
    k = _kernel()
    k.attention_feedback.add_attention_state(_state())
    rec = k.ledger.records[-1]
    assert rec.simulation_date == "2026-03-31"


# ---------------------------------------------------------------------------
# build_attention_feedback — rule-set classifier
# ---------------------------------------------------------------------------


def test_helper_kernel_required():
    with pytest.raises(ValueError):
        build_attention_feedback(
            None, actor_id=_ACTOR, actor_type=_ACTOR_TYPE, as_of_date=_AS_OF
        )


def test_helper_actor_id_required():
    k = _kernel()
    with pytest.raises(ValueError):
        build_attention_feedback(
            k, actor_id="", actor_type=_ACTOR_TYPE, as_of_date=_AS_OF
        )


def test_helper_actor_type_required():
    k = _kernel()
    with pytest.raises(ValueError):
        build_attention_feedback(
            k, actor_id=_ACTOR, actor_type="", as_of_date=_AS_OF
        )


def test_helper_no_evidence_yields_routine_observed_with_memory_focus():
    k = _kernel()
    out = build_attention_feedback(
        k, actor_id=_ACTOR, actor_type=_ACTOR_TYPE, as_of_date=_AS_OF
    )
    assert out.feedback.trigger_label == TRIGGER_ROUTINE_OBSERVED
    assert out.attention_state.focus_labels == (FOCUS_LABEL_MEMORY,)


def test_helper_risk_intent_yields_risk_focus():
    k = _kernel()
    intent_id = _seed_intent(k, direction="risk_flag_watch")
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_id,),
    )
    assert out.feedback.trigger_label == TRIGGER_RISK_INTENT_OBSERVED
    labels = set(out.attention_state.focus_labels)
    assert FOCUS_LABEL_FIRM_STATE in labels
    assert FOCUS_LABEL_MARKET_ENVIRONMENT in labels


def test_helper_engagement_intent_yields_engagement_focus():
    k = _kernel()
    intent_id = _seed_intent(k, direction="engagement_watch")
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_id,),
    )
    assert out.feedback.trigger_label == TRIGGER_ENGAGEMENT_INTENT_OBSERVED
    labels = set(out.attention_state.focus_labels)
    assert FOCUS_LABEL_ENGAGEMENT in labels
    assert FOCUS_LABEL_DIALOGUE in labels


def test_helper_low_confidence_intent_yields_valuation_focus():
    k = _kernel()
    intent_id = _seed_intent(k, direction="decrease_confidence")
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_id,),
    )
    assert out.feedback.trigger_label == TRIGGER_VALUATION_CONFIDENCE_LOW
    assert FOCUS_LABEL_VALUATION in out.attention_state.focus_labels


def test_helper_low_valuation_confidence_triggers_valuation_focus():
    k = _kernel()
    val_id = _seed_low_confidence_valuation(k, confidence=0.2)
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        valuation_ids=(val_id,),
    )
    assert FOCUS_LABEL_VALUATION in out.attention_state.focus_labels


def test_helper_liquidity_credit_review_yields_funding_focus():
    k = _kernel()
    sid = _seed_credit_review_signal(k, watch_label="liquidity_watch")
    out = build_attention_feedback(
        k,
        actor_id="bank:reference_megabank_a",
        actor_type="bank",
        as_of_date=_AS_OF,
        credit_review_signal_ids=(sid,),
    )
    assert out.feedback.trigger_label == TRIGGER_LIQUIDITY_CREDIT_REVIEW


def test_helper_restrictive_market_yields_liquidity_credit_focus():
    k = _kernel()
    eid = _seed_market_env(k, overall="selective_or_constrained")
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        market_environment_state_ids=(eid,),
    )
    assert out.feedback.trigger_label == TRIGGER_RESTRICTIVE_MARKET_OBSERVED
    assert FOCUS_LABEL_LIQUIDITY in out.attention_state.focus_labels


# ---------------------------------------------------------------------------
# Chaining via previous_attention_state_id
# ---------------------------------------------------------------------------


def test_helper_chains_through_previous_attention_state_id():
    k = _kernel()
    out_p0 = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date="2026-03-31",
    )
    assert out_p0.attention_state.previous_attention_state_id is None

    out_p1 = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date="2026-06-30",
    )
    assert (
        out_p1.attention_state.previous_attention_state_id
        == out_p0.attention_state_id
    )
    assert out_p1.feedback.previous_attention_state_id == (
        out_p0.attention_state_id
    )


def test_helper_idempotent_on_attention_state_id():
    k = _kernel()
    out1 = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        attention_state_id="attention_state:fixed",
        feedback_id="attention_feedback:fixed",
    )
    out2 = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        attention_state_id="attention_state:fixed",
        feedback_id="attention_feedback:fixed",
    )
    assert out1.attention_state is out2.attention_state
    assert out1.feedback is out2.feedback
    assert len(k.attention_feedback.list_attention_states()) == 1
    assert len(k.attention_feedback.list_feedback()) == 1


def test_helper_deterministic_for_identical_inputs():
    k_a = _kernel()
    intent_a = _seed_intent(k_a, direction="risk_flag_watch")
    out_a = build_attention_feedback(
        k_a,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_a,),
    )

    k_b = _kernel()
    intent_b = _seed_intent(k_b, direction="risk_flag_watch")
    out_b = build_attention_feedback(
        k_b,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_b,),
    )
    assert (
        out_a.attention_state.to_dict() == out_b.attention_state.to_dict()
    )
    assert out_a.feedback.to_dict() == out_b.feedback.to_dict()


def test_helper_records_source_evidence_id_tuples():
    k = _kernel()
    intent_id = _seed_intent(k, direction="risk_flag_watch")
    eid = _seed_market_env(k, overall="selective_or_constrained")
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_id,),
        market_environment_state_ids=(eid,),
    )
    assert out.attention_state.source_investor_intent_ids == (intent_id,)
    assert out.attention_state.source_market_environment_state_ids == (eid,)
    assert intent_id in out.feedback.source_record_ids


def test_helper_tolerates_unresolved_evidence_ids():
    k = _kernel()
    out = build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=("intent:does_not_exist",),
    )
    # Source ids are recorded as data; rule set treats them as
    # absent and falls through to routine.
    assert out.feedback.trigger_label == TRIGGER_ROUTINE_OBSERVED
    assert out.attention_state.source_investor_intent_ids == (
        "intent:does_not_exist",
    )


# ---------------------------------------------------------------------------
# No-mutation guarantee
# ---------------------------------------------------------------------------


def test_helper_does_not_mutate_other_kernel_books():
    k = _kernel()
    intent_id = _seed_intent(k, direction="engagement_watch")
    snaps_before = {
        "ownership": k.ownership.snapshot(),
        "contracts": k.contracts.snapshot(),
        "prices": k.prices.snapshot(),
        "constraints": k.constraints.snapshot(),
        "signals": k.signals.snapshot(),
        "valuations": k.valuations.snapshot(),
        "institutions": k.institutions.snapshot(),
        "external_processes": k.external_processes.snapshot(),
        "relationships": k.relationships.snapshot(),
        "interactions": k.interactions.snapshot(),
        "routines": k.routines.snapshot(),
        "attention": k.attention.snapshot(),
        "variables": k.variables.snapshot(),
        "exposures": k.exposures.snapshot(),
        "stewardship": k.stewardship.snapshot(),
        "engagement": k.engagement.snapshot(),
        "escalations": k.escalations.snapshot(),
        "strategic_responses": k.strategic_responses.snapshot(),
        "industry_conditions": k.industry_conditions.snapshot(),
        "market_conditions": k.market_conditions.snapshot(),
        "capital_market_readouts": k.capital_market_readouts.snapshot(),
        "market_environments": k.market_environments.snapshot(),
        "firm_financial_states": k.firm_financial_states.snapshot(),
        "investor_intents": k.investor_intents.snapshot(),
    }
    build_attention_feedback(
        k,
        actor_id=_ACTOR,
        actor_type=_ACTOR_TYPE,
        as_of_date=_AS_OF,
        investor_intent_ids=(intent_id,),
    )
    for name, before in snaps_before.items():
        assert getattr(k, name).snapshot() == before, name


# ---------------------------------------------------------------------------
# Vocabulary export
# ---------------------------------------------------------------------------


def test_all_focus_labels_carry_no_forbidden_word():
    forbidden = {
        "buy",
        "sell",
        "rating",
        "approved",
        "rejected",
        "default",
        "pd",
        "lgd",
        "ead",
        "advice",
        "recommendation",
        "underwrite",
        "trade",
        "order",
    }
    for label in ALL_FOCUS_LABELS:
        assert not (set(label.lower().split("_")) & forbidden), label


# ---------------------------------------------------------------------------
# Jurisdiction-neutral identifier scan
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
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


def test_attention_feedback_module_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parent.parent
        / "world"
        / "attention_feedback.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, token
