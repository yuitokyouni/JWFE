"""
v1.12.8 ActorAttentionStateRecord + AttentionFeedbackRecord +
AttentionFeedbackBook + ``build_attention_feedback``.

The first **cross-period attention feedback** layer in public
FWE. Through v1.12.7 attention was load-bearing **within a
period** for investor intent, valuation lite, and bank credit
review lite. v1.12.8 closes the loop *across* periods:

    period N market environment / firm state / investor intent
    / valuation / bank credit review
    -> attention feedback
    -> next-period actor attention state
    -> period N+1 selected evidence changes (observably).

This stays synthetic, deterministic, and **non-binding**. It
does not introduce trading, price formation, lending decisions,
investment recommendations, portfolio allocation, target
weights, expected returns, recommendations, real data
ingestion, Japan calibration, LLM-agent execution, or behavior
probabilities.

Per ``docs/world_model.md`` §90 and the v1.12.8 task spec:

- :class:`ActorAttentionStateRecord` — immutable per-(actor,
  period) state describing what the actor will *focus* on in
  the next period. Carries a small free-form ``focus_labels``
  tuple (e.g., ``"firm_state"``, ``"engagement"``,
  ``"market_environment"``, ``"funding"``), an additive
  ``focus_weights`` mapping (synthetic, not calibrated, in
  ``[0.0, 1.0]``), and the ``previous_attention_state_id``
  chain link.
- :class:`AttentionFeedbackRecord` — immutable per-(actor,
  period) feedback record naming what *triggered* the new
  attention state. Carries ``feedback_type``, ``trigger_label``,
  and the source ids the rule set walked.
- :class:`AttentionFeedbackBook` — append-only storage with
  ``add_attention_state`` / ``get_attention_state`` /
  ``list_attention_states`` / ``list_by_actor`` /
  ``list_by_actor_type`` / ``list_by_date`` /
  ``get_latest_for_actor`` / ``add_feedback`` / ``get_feedback``
  / ``list_feedback`` / ``list_feedback_by_actor`` / ``snapshot``.
- :func:`build_attention_feedback` — deterministic helper
  reading the cited ids and applying the v1.12.8 rule set;
  emits exactly one new attention state + one feedback record.
  Idempotent on ``attention_state_id`` (and on ``feedback_id``
  via the same default formula).

The book emits exactly one ledger record per ``add_*`` call
(``RecordType.ATTENTION_STATE_CREATED`` and
``RecordType.ATTENTION_FEEDBACK_RECORDED``) and refuses to
mutate any other source-of-truth book in the kernel.

Anti-fields (binding)
=====================

The records deliberately have **no** ``order``, ``trade``,
``rebalance``, ``target_weight``, ``buy``, ``sell``,
``recommendation``, ``investment_advice``, ``expected_return``,
``target_price``, ``portfolio_allocation``, ``execution``,
``forecast_value``, ``actual_value``, ``real_data_value``, or
``behavior_probability`` field. Tests pin the absence on the
dataclass field set and on the ledger payload key set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Iterable, Mapping, Sequence

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AttentionFeedbackError(Exception):
    """Base class for attention-feedback-layer errors."""


class DuplicateAttentionStateError(AttentionFeedbackError):
    """Raised when an attention_state_id is added twice."""


class UnknownAttentionStateError(AttentionFeedbackError, KeyError):
    """Raised when an attention_state_id is not found."""


class DuplicateAttentionFeedbackError(AttentionFeedbackError):
    """Raised when a feedback_id is added twice."""


class UnknownAttentionFeedbackError(AttentionFeedbackError, KeyError):
    """Raised when a feedback_id is not found."""


# ---------------------------------------------------------------------------
# Vocabulary (illustrative, jurisdiction-neutral)
# ---------------------------------------------------------------------------


# v1.12.8 deterministic feedback labels. None is a calibrated
# probability; none is a regulator-recognised credit measure or
# market view. Tests pin the priority-order classifier against
# the closed set below.
FOCUS_LABEL_FIRM_STATE: str = "firm_state"
FOCUS_LABEL_MARKET_ENVIRONMENT: str = "market_environment"
FOCUS_LABEL_MARKET_ACCESS: str = "market_access"
FOCUS_LABEL_FUNDING: str = "funding"
FOCUS_LABEL_LIQUIDITY: str = "liquidity"
FOCUS_LABEL_CREDIT: str = "credit"
FOCUS_LABEL_REFINANCING_WINDOW: str = "refinancing_window"
FOCUS_LABEL_VALUATION: str = "valuation"
FOCUS_LABEL_ENGAGEMENT: str = "engagement"
FOCUS_LABEL_DIALOGUE: str = "dialogue"
FOCUS_LABEL_ESCALATION: str = "escalation"
FOCUS_LABEL_STEWARDSHIP: str = "stewardship"
FOCUS_LABEL_MEMORY: str = "memory"

ALL_FOCUS_LABELS: tuple[str, ...] = (
    FOCUS_LABEL_FIRM_STATE,
    FOCUS_LABEL_MARKET_ENVIRONMENT,
    FOCUS_LABEL_MARKET_ACCESS,
    FOCUS_LABEL_FUNDING,
    FOCUS_LABEL_LIQUIDITY,
    FOCUS_LABEL_CREDIT,
    FOCUS_LABEL_REFINANCING_WINDOW,
    FOCUS_LABEL_VALUATION,
    FOCUS_LABEL_ENGAGEMENT,
    FOCUS_LABEL_DIALOGUE,
    FOCUS_LABEL_ESCALATION,
    FOCUS_LABEL_STEWARDSHIP,
    FOCUS_LABEL_MEMORY,
)


# v1.12.8 trigger labels. Each names which prior-period
# observation drove the new focus. The list is illustrative;
# tests pin the closed set used by the v1.12.8 rule set.
TRIGGER_RISK_INTENT_OBSERVED: str = "risk_intent_observed"
TRIGGER_ENGAGEMENT_INTENT_OBSERVED: str = "engagement_intent_observed"
TRIGGER_VALUATION_CONFIDENCE_LOW: str = "valuation_confidence_low"
TRIGGER_LIQUIDITY_CREDIT_REVIEW: str = "liquidity_or_refinancing_credit_review"
TRIGGER_RESTRICTIVE_MARKET_OBSERVED: str = "restrictive_market_observed"
TRIGGER_ROUTINE_OBSERVED: str = "routine_observed"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


def _normalize_string_tuple(
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
# ActorAttentionStateRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActorAttentionStateRecord:
    """Immutable per-(actor, period) attention state.

    Represents what the actor *will focus on* in the next
    period. Carries:

    - ``focus_labels`` — small free-form tuple of label tags
      (e.g., ``"firm_state"``, ``"engagement"``,
      ``"market_environment"``). v1.12.8 stores the tags
      without enforcing membership in any specific list;
      tests pin the closed set the v1.12.8 rule set produces.
    - ``focus_weights`` — additive synthetic weight per label
      in ``[0.0, 1.0]``. Booleans rejected. **Never** a
      calibrated sensitivity.
    - ``base_profile_ids`` — tuple of ``AttentionProfile`` ids
      this state is layered on top of.
    - ``max_selected_refs`` — synthetic non-negative integer
      that future menu builders may use as a soft cap on how
      many refs to surface per period. v1.12.8 stores it; the
      menu builder does not yet enforce it.
    - eight ``source_*_ids`` tuples naming the prior-period
      records the rule set walked.
    - ``previous_attention_state_id`` — optional chain link
      to the actor's prior attention state.
    """

    attention_state_id: str
    actor_id: str
    actor_type: str
    as_of_date: str
    status: str
    confidence: float
    max_selected_refs: int
    base_profile_ids: tuple[str, ...] = field(default_factory=tuple)
    focus_labels: tuple[str, ...] = field(default_factory=tuple)
    focus_weights: Mapping[str, float] = field(default_factory=dict)
    source_market_environment_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_firm_state_ids: tuple[str, ...] = field(default_factory=tuple)
    source_investor_intent_ids: tuple[str, ...] = field(default_factory=tuple)
    source_valuation_ids: tuple[str, ...] = field(default_factory=tuple)
    source_credit_review_signal_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_dialogue_ids: tuple[str, ...] = field(default_factory=tuple)
    source_escalation_candidate_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    previous_attention_state_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "attention_state_id",
        "actor_id",
        "actor_type",
        "as_of_date",
        "status",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "base_profile_ids",
        "focus_labels",
        "source_market_environment_state_ids",
        "source_firm_state_ids",
        "source_investor_intent_ids",
        "source_valuation_ids",
        "source_credit_review_signal_ids",
        "source_dialogue_ids",
        "source_escalation_candidate_ids",
    )

    def __post_init__(self) -> None:
        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, (str, date)) or (
                isinstance(value, str) and not value
            ):
                raise ValueError(f"{name} is required")

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "confidence must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated "
                "probability)"
            )
        object.__setattr__(self, "confidence", float(self.confidence))

        if (
            isinstance(self.max_selected_refs, bool)
            or not isinstance(self.max_selected_refs, int)
        ):
            raise ValueError("max_selected_refs must be a non-negative int")
        if self.max_selected_refs < 0:
            raise ValueError("max_selected_refs must be non-negative")

        object.__setattr__(
            self, "as_of_date", _coerce_iso_date(self.as_of_date)
        )

        for tuple_field_name in self.TUPLE_FIELDS:
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        if self.previous_attention_state_id is not None and (
            not isinstance(self.previous_attention_state_id, str)
            or not self.previous_attention_state_id
        ):
            raise ValueError(
                "previous_attention_state_id must be a non-empty "
                "string or None"
            )

        # focus_weights — every value bounded in [0.0, 1.0],
        # bool rejected.
        normalized_weights: dict[str, float] = {}
        for label, weight in dict(self.focus_weights).items():
            if not isinstance(label, str) or not label:
                raise ValueError(
                    "focus_weights keys must be non-empty strings"
                )
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError(
                    "focus_weights values must be numbers in [0.0, 1.0]"
                )
            if not (0.0 <= float(weight) <= 1.0):
                raise ValueError(
                    "focus_weights values must lie in [0.0, 1.0]"
                )
            normalized_weights[label] = float(weight)
        object.__setattr__(self, "focus_weights", normalized_weights)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "attention_state_id": self.attention_state_id,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "as_of_date": self.as_of_date,
            "status": self.status,
            "confidence": self.confidence,
            "max_selected_refs": self.max_selected_refs,
            "base_profile_ids": list(self.base_profile_ids),
            "focus_labels": list(self.focus_labels),
            "focus_weights": dict(self.focus_weights),
            "source_market_environment_state_ids": list(
                self.source_market_environment_state_ids
            ),
            "source_firm_state_ids": list(self.source_firm_state_ids),
            "source_investor_intent_ids": list(
                self.source_investor_intent_ids
            ),
            "source_valuation_ids": list(self.source_valuation_ids),
            "source_credit_review_signal_ids": list(
                self.source_credit_review_signal_ids
            ),
            "source_dialogue_ids": list(self.source_dialogue_ids),
            "source_escalation_candidate_ids": list(
                self.source_escalation_candidate_ids
            ),
            "previous_attention_state_id": self.previous_attention_state_id,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# AttentionFeedbackRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AttentionFeedbackRecord:
    """Immutable per-(actor, period) feedback record naming
    *what triggered* the new attention state.

    - ``feedback_type`` is a small free-form lifecycle tag
      (``"period_observed_to_next_period"`` is the v1.12.8
      default; future variants may name out-of-band feedback).
    - ``trigger_label`` is the dominant trigger the rule set
      identified (e.g., ``"risk_intent_observed"``,
      ``"engagement_intent_observed"``).
    - ``source_record_ids`` is a tuple of plain-id
      cross-references to the records the rule set walked.
    """

    feedback_id: str
    actor_id: str
    actor_type: str
    as_of_date: str
    new_attention_state_id: str
    feedback_type: str
    trigger_label: str
    status: str
    confidence: float
    previous_attention_state_id: str | None = None
    source_record_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "feedback_id",
        "actor_id",
        "actor_type",
        "as_of_date",
        "new_attention_state_id",
        "feedback_type",
        "trigger_label",
        "status",
    )

    def __post_init__(self) -> None:
        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, (str, date)) or (
                isinstance(value, str) and not value
            ):
                raise ValueError(f"{name} is required")

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "confidence must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated "
                "probability)"
            )
        object.__setattr__(self, "confidence", float(self.confidence))

        object.__setattr__(
            self, "as_of_date", _coerce_iso_date(self.as_of_date)
        )

        if self.previous_attention_state_id is not None and (
            not isinstance(self.previous_attention_state_id, str)
            or not self.previous_attention_state_id
        ):
            raise ValueError(
                "previous_attention_state_id must be a non-empty "
                "string or None"
            )

        object.__setattr__(
            self,
            "source_record_ids",
            _normalize_string_tuple(
                self.source_record_ids, field_name="source_record_ids"
            ),
        )

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "as_of_date": self.as_of_date,
            "new_attention_state_id": self.new_attention_state_id,
            "feedback_type": self.feedback_type,
            "trigger_label": self.trigger_label,
            "status": self.status,
            "confidence": self.confidence,
            "previous_attention_state_id": self.previous_attention_state_id,
            "source_record_ids": list(self.source_record_ids),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class AttentionFeedbackBook:
    """
    Append-only storage for v1.12.8 attention-state and
    feedback records.

    The book emits exactly one ledger record per ``add_*`` call
    (``RecordType.ATTENTION_STATE_CREATED`` and
    ``RecordType.ATTENTION_FEEDBACK_RECORDED``) and refuses to
    mutate any other source-of-truth book in the kernel.
    v1.12.8 ships storage and read-only listings only — no
    automatic propagation, no order, no trade, no allocation.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _attention_states: dict[str, ActorAttentionStateRecord] = field(
        default_factory=dict
    )
    _feedbacks: dict[str, AttentionFeedbackRecord] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # Attention-state CRUD
    # ------------------------------------------------------------------

    def add_attention_state(
        self, state: ActorAttentionStateRecord
    ) -> ActorAttentionStateRecord:
        if state.attention_state_id in self._attention_states:
            raise DuplicateAttentionStateError(
                f"Duplicate attention_state_id: {state.attention_state_id}"
            )
        self._attention_states[state.attention_state_id] = state

        if self.ledger is not None:
            self.ledger.append(
                event_type="attention_state_created",
                simulation_date=self._now(),
                object_id=state.attention_state_id,
                source=state.actor_id,
                payload={
                    "attention_state_id": state.attention_state_id,
                    "actor_id": state.actor_id,
                    "actor_type": state.actor_type,
                    "as_of_date": state.as_of_date,
                    "status": state.status,
                    "confidence": state.confidence,
                    "max_selected_refs": state.max_selected_refs,
                    "base_profile_ids": list(state.base_profile_ids),
                    "focus_labels": list(state.focus_labels),
                    "focus_weights": dict(state.focus_weights),
                    "source_market_environment_state_ids": list(
                        state.source_market_environment_state_ids
                    ),
                    "source_firm_state_ids": list(
                        state.source_firm_state_ids
                    ),
                    "source_investor_intent_ids": list(
                        state.source_investor_intent_ids
                    ),
                    "source_valuation_ids": list(
                        state.source_valuation_ids
                    ),
                    "source_credit_review_signal_ids": list(
                        state.source_credit_review_signal_ids
                    ),
                    "source_dialogue_ids": list(state.source_dialogue_ids),
                    "source_escalation_candidate_ids": list(
                        state.source_escalation_candidate_ids
                    ),
                    "previous_attention_state_id": (
                        state.previous_attention_state_id
                    ),
                },
                space_id="attention_feedback",
                visibility="internal_only",
                confidence=state.confidence,
            )
        return state

    def get_attention_state(
        self, attention_state_id: str
    ) -> ActorAttentionStateRecord:
        try:
            return self._attention_states[attention_state_id]
        except KeyError as exc:
            raise UnknownAttentionStateError(
                f"Attention state not found: {attention_state_id!r}"
            ) from exc

    def list_attention_states(
        self,
    ) -> tuple[ActorAttentionStateRecord, ...]:
        return tuple(self._attention_states.values())

    def list_by_actor(
        self, actor_id: str
    ) -> tuple[ActorAttentionStateRecord, ...]:
        return tuple(
            s
            for s in self._attention_states.values()
            if s.actor_id == actor_id
        )

    def list_by_actor_type(
        self, actor_type: str
    ) -> tuple[ActorAttentionStateRecord, ...]:
        return tuple(
            s
            for s in self._attention_states.values()
            if s.actor_type == actor_type
        )

    def list_by_date(
        self, as_of: date | str
    ) -> tuple[ActorAttentionStateRecord, ...]:
        target = _coerce_iso_date(as_of)
        return tuple(
            s
            for s in self._attention_states.values()
            if s.as_of_date == target
        )

    def get_latest_for_actor(
        self, actor_id: str
    ) -> ActorAttentionStateRecord | None:
        """Return the most recently added attention state for
        ``actor_id``, or ``None`` if no state exists for that
        actor yet.

        "Most recently added" is *insertion order*, not
        ``as_of_date`` order — callers who insert out of
        chronological order should not rely on this helper.
        The v1.12.8 living world inserts in chronological order
        period by period.
        """
        latest: ActorAttentionStateRecord | None = None
        for s in self._attention_states.values():
            if s.actor_id == actor_id:
                latest = s
        return latest

    # ------------------------------------------------------------------
    # Feedback CRUD
    # ------------------------------------------------------------------

    def add_feedback(
        self, feedback: AttentionFeedbackRecord
    ) -> AttentionFeedbackRecord:
        if feedback.feedback_id in self._feedbacks:
            raise DuplicateAttentionFeedbackError(
                f"Duplicate feedback_id: {feedback.feedback_id}"
            )
        self._feedbacks[feedback.feedback_id] = feedback

        if self.ledger is not None:
            self.ledger.append(
                event_type="attention_feedback_recorded",
                simulation_date=self._now(),
                object_id=feedback.feedback_id,
                source=feedback.actor_id,
                payload={
                    "feedback_id": feedback.feedback_id,
                    "actor_id": feedback.actor_id,
                    "actor_type": feedback.actor_type,
                    "as_of_date": feedback.as_of_date,
                    "new_attention_state_id": feedback.new_attention_state_id,
                    "feedback_type": feedback.feedback_type,
                    "trigger_label": feedback.trigger_label,
                    "status": feedback.status,
                    "confidence": feedback.confidence,
                    "previous_attention_state_id": (
                        feedback.previous_attention_state_id
                    ),
                    "source_record_ids": list(feedback.source_record_ids),
                },
                space_id="attention_feedback",
                visibility="internal_only",
                confidence=feedback.confidence,
            )
        return feedback

    def get_feedback(
        self, feedback_id: str
    ) -> AttentionFeedbackRecord:
        try:
            return self._feedbacks[feedback_id]
        except KeyError as exc:
            raise UnknownAttentionFeedbackError(
                f"Attention feedback not found: {feedback_id!r}"
            ) from exc

    def list_feedback(
        self,
    ) -> tuple[AttentionFeedbackRecord, ...]:
        return tuple(self._feedbacks.values())

    def list_feedback_by_actor(
        self, actor_id: str
    ) -> tuple[AttentionFeedbackRecord, ...]:
        return tuple(
            f for f in self._feedbacks.values() if f.actor_id == actor_id
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        states = sorted(
            (s.to_dict() for s in self._attention_states.values()),
            key=lambda item: item["attention_state_id"],
        )
        feedbacks = sorted(
            (f.to_dict() for f in self._feedbacks.values()),
            key=lambda item: item["feedback_id"],
        )
        return {
            "attention_state_count": len(states),
            "attention_states": states,
            "feedback_count": len(feedbacks),
            "feedbacks": feedbacks,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()


# ---------------------------------------------------------------------------
# Build helper — deterministic synthetic rule set
# ---------------------------------------------------------------------------


# v1.12.8 deterministic rule set thresholds. Small, documented,
# illustrative; tests pin the qualitative ordering, not specific
# arithmetic. None is a calibrated probability; none is a market
# view.
_VALUATION_LOW_CONFIDENCE_THRESHOLD: float = 0.4
_DEFAULT_FEEDBACK_CONFIDENCE: float = 0.7
_DEFAULT_FOCUS_WEIGHT: float = 0.5
_BASE_MAX_SELECTED_REFS: int = 8
_RESTRICTIVE_OVERALL_LABEL: str = "selective_or_constrained"


# v1.12.8 intent-direction → focus-label mapping. The mapping is
# additive; multiple intents can produce overlapping focus sets.
_RISK_INTENT_DIRECTIONS: frozenset[str] = frozenset(
    {"risk_flag_watch", "deepen_due_diligence"}
)
_ENGAGEMENT_INTENT_DIRECTIONS: frozenset[str] = frozenset(
    {"engagement_watch"}
)
_LOW_CONFIDENCE_INTENT_DIRECTIONS: frozenset[str] = frozenset(
    {"decrease_confidence"}
)


# v1.12.8 watch-label → focus-label mapping for bank credit
# review. The mapping is additive.
_LIQUIDITY_OR_REFINANCING_WATCH_LABELS: frozenset[str] = frozenset(
    {"liquidity_watch", "refinancing_watch"}
)
_MARKET_ACCESS_WATCH_LABELS: frozenset[str] = frozenset(
    {"market_access_watch"}
)


@dataclass(frozen=True)
class AttentionFeedbackBuildResult:
    """Return type for :func:`build_attention_feedback`.

    Carries both produced records so the caller can branch on
    the resolved attention state without re-fetching.
    """

    attention_state_id: str
    feedback_id: str
    attention_state: ActorAttentionStateRecord
    feedback: AttentionFeedbackRecord


def _default_attention_state_id(
    actor_id: str, as_of_date: str
) -> str:
    return f"attention_state:{actor_id}:{as_of_date}"


def _default_feedback_id(actor_id: str, as_of_date: str) -> str:
    return f"attention_feedback:{actor_id}:{as_of_date}"


def _classify_focus_labels(
    *,
    intent_directions: frozenset[str],
    watch_labels: frozenset[str],
    restrictive_market: bool,
    low_valuation_confidence: bool,
) -> tuple[tuple[str, ...], str]:
    """v1.12.8 deterministic focus-label classifier.

    Returns ``(focus_labels, trigger_label)``.

    Rules (additive — focus_labels is a union; trigger_label is
    the highest-priority one):

    1. ``risk_intent_observed`` — when any intent direction is
       in ``{risk_flag_watch, deepen_due_diligence}``. Adds
       ``firm_state``, ``market_environment``, ``market_access``
       to focus.
    2. ``engagement_intent_observed`` — when any intent
       direction is ``engagement_watch``. Adds ``engagement``,
       ``dialogue``, ``stewardship``, ``escalation``.
    3. ``valuation_confidence_low`` — when intent direction is
       ``decrease_confidence`` OR a cited valuation has
       ``confidence < 0.4``. Adds ``valuation``, ``firm_state``,
       ``market_environment``.
    4. ``liquidity_or_refinancing_credit_review`` — when any
       bank-credit-review watch label is ``liquidity_watch`` or
       ``refinancing_watch``. Adds ``firm_state``,
       ``market_environment``, ``funding``.
    5. ``restrictive_market_observed`` — when overall market
       access is ``selective_or_constrained``. Adds
       ``liquidity``, ``credit``, ``refinancing_window``.
    6. ``routine_observed`` — fallback. Adds ``memory``.

    The trigger_label is the highest-priority rule that fired
    (1 > 2 > 3 > 4 > 5 > 6).
    """
    focus_set: set[str] = set()
    trigger_label = TRIGGER_ROUTINE_OBSERVED

    if intent_directions & _RISK_INTENT_DIRECTIONS:
        focus_set.update(
            {
                FOCUS_LABEL_FIRM_STATE,
                FOCUS_LABEL_MARKET_ENVIRONMENT,
                FOCUS_LABEL_MARKET_ACCESS,
            }
        )
        if trigger_label == TRIGGER_ROUTINE_OBSERVED:
            trigger_label = TRIGGER_RISK_INTENT_OBSERVED

    if intent_directions & _ENGAGEMENT_INTENT_DIRECTIONS:
        focus_set.update(
            {
                FOCUS_LABEL_ENGAGEMENT,
                FOCUS_LABEL_DIALOGUE,
                FOCUS_LABEL_STEWARDSHIP,
                FOCUS_LABEL_ESCALATION,
            }
        )
        if trigger_label == TRIGGER_ROUTINE_OBSERVED:
            trigger_label = TRIGGER_ENGAGEMENT_INTENT_OBSERVED

    if (
        intent_directions & _LOW_CONFIDENCE_INTENT_DIRECTIONS
        or low_valuation_confidence
    ):
        focus_set.update(
            {
                FOCUS_LABEL_VALUATION,
                FOCUS_LABEL_FIRM_STATE,
                FOCUS_LABEL_MARKET_ENVIRONMENT,
            }
        )
        if trigger_label == TRIGGER_ROUTINE_OBSERVED:
            trigger_label = TRIGGER_VALUATION_CONFIDENCE_LOW

    if watch_labels & _LIQUIDITY_OR_REFINANCING_WATCH_LABELS:
        focus_set.update(
            {
                FOCUS_LABEL_FIRM_STATE,
                FOCUS_LABEL_MARKET_ENVIRONMENT,
                FOCUS_LABEL_FUNDING,
            }
        )
        if trigger_label == TRIGGER_ROUTINE_OBSERVED:
            trigger_label = TRIGGER_LIQUIDITY_CREDIT_REVIEW
    if watch_labels & _MARKET_ACCESS_WATCH_LABELS:
        focus_set.update(
            {
                FOCUS_LABEL_MARKET_ENVIRONMENT,
                FOCUS_LABEL_MARKET_ACCESS,
                FOCUS_LABEL_FUNDING,
            }
        )
        if trigger_label == TRIGGER_ROUTINE_OBSERVED:
            trigger_label = TRIGGER_LIQUIDITY_CREDIT_REVIEW

    if restrictive_market:
        focus_set.update(
            {
                FOCUS_LABEL_LIQUIDITY,
                FOCUS_LABEL_CREDIT,
                FOCUS_LABEL_REFINANCING_WINDOW,
            }
        )
        if trigger_label == TRIGGER_ROUTINE_OBSERVED:
            trigger_label = TRIGGER_RESTRICTIVE_MARKET_OBSERVED

    if not focus_set:
        # Fallback — every actor carries at least one label so a
        # downstream LLM-agent step never reads an empty focus
        # tuple.
        focus_set.add(FOCUS_LABEL_MEMORY)

    return tuple(sorted(focus_set)), trigger_label


def build_attention_feedback(
    kernel: Any,
    *,
    actor_id: str,
    actor_type: str,
    as_of_date: date | str,
    base_profile_ids: Sequence[str] = (),
    investor_intent_ids: Sequence[str] = (),
    credit_review_signal_ids: Sequence[str] = (),
    market_environment_state_ids: Sequence[str] = (),
    firm_state_ids: Sequence[str] = (),
    valuation_ids: Sequence[str] = (),
    dialogue_ids: Sequence[str] = (),
    escalation_candidate_ids: Sequence[str] = (),
    attention_state_id: str | None = None,
    feedback_id: str | None = None,
    feedback_type: str = "period_observed_to_next_period",
    metadata: Mapping[str, Any] | None = None,
) -> AttentionFeedbackBuildResult:
    """
    v1.12.8 — build one new attention state + feedback record
    for ``(actor_id, as_of_date)``.

    Reads only the cited ids (attention discipline; never a
    global book scan). Idempotent: a state already added under
    the same ``attention_state_id`` is returned unchanged with a
    fresh feedback record only if the ``feedback_id`` differs.

    Writes only to ``kernel.attention_feedback`` and the kernel
    ledger; never to any other source-of-truth book.

    The previous-period attention state for ``actor_id`` (if
    any) is looked up via
    :meth:`AttentionFeedbackBook.get_latest_for_actor` and
    chained as ``previous_attention_state_id``.

    Defensive: unresolved cited ids are tolerated (recorded as
    data on ``source_*_ids`` tuples but do not block emission).
    """
    if kernel is None:
        raise ValueError("kernel is required")
    if not isinstance(actor_id, str) or not actor_id:
        raise ValueError(
            "actor_id is required and must be a non-empty string"
        )
    if not isinstance(actor_type, str) or not actor_type:
        raise ValueError(
            "actor_type is required and must be a non-empty string"
        )

    iso_date = _coerce_iso_date(as_of_date)
    asid = attention_state_id or _default_attention_state_id(
        actor_id, iso_date
    )
    fbid = feedback_id or _default_feedback_id(actor_id, iso_date)

    book: AttentionFeedbackBook = kernel.attention_feedback

    # Idempotency on attention_state_id.
    try:
        existing_state = book.get_attention_state(asid)
        try:
            existing_feedback = book.get_feedback(fbid)
        except UnknownAttentionFeedbackError:
            existing_feedback = None
        if existing_feedback is not None:
            return AttentionFeedbackBuildResult(
                attention_state_id=existing_state.attention_state_id,
                feedback_id=existing_feedback.feedback_id,
                attention_state=existing_state,
                feedback=existing_feedback,
            )
    except UnknownAttentionStateError:
        pass

    # ------------------------------------------------------------------
    # Read cited evidence (tolerantly) and classify focus labels.
    # ------------------------------------------------------------------
    intent_directions: set[str] = set()
    for iid in investor_intent_ids:
        try:
            intent = kernel.investor_intents.get_intent(iid)
        except Exception:
            continue
        intent_directions.add(intent.intent_direction)

    watch_labels: set[str] = set()
    for sid in credit_review_signal_ids:
        try:
            sig = kernel.signals.get_signal(sid)
        except Exception:
            continue
        watch_label = sig.payload.get("watch_label") if sig.payload else None
        if isinstance(watch_label, str) and watch_label:
            watch_labels.add(watch_label)

    restrictive_market = False
    for eid in market_environment_state_ids:
        try:
            env = kernel.market_environments.get_state(eid)
        except Exception:
            continue
        if env.overall_market_access_label == _RESTRICTIVE_OVERALL_LABEL:
            restrictive_market = True

    low_valuation_confidence = False
    for vid in valuation_ids:
        try:
            valuation = kernel.valuations.get_valuation(vid)
        except Exception:
            continue
        confidence = getattr(valuation, "confidence", None)
        if (
            isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) < _VALUATION_LOW_CONFIDENCE_THRESHOLD
        ):
            low_valuation_confidence = True
            break

    focus_labels, trigger_label = _classify_focus_labels(
        intent_directions=frozenset(intent_directions),
        watch_labels=frozenset(watch_labels),
        restrictive_market=restrictive_market,
        low_valuation_confidence=low_valuation_confidence,
    )

    # All focus labels carry a uniform default weight of 0.5 in
    # v1.12.8. Future calibration milestones may differentiate
    # weights per label / per actor.
    focus_weights = {label: _DEFAULT_FOCUS_WEIGHT for label in focus_labels}

    # ``max_selected_refs`` is a synthetic non-negative integer
    # the menu builder may use as a soft cap. Default formula:
    # base + len(focus_labels). v1.12.8 stores it; v1.12.9+ may
    # enforce it.
    max_selected_refs = _BASE_MAX_SELECTED_REFS + len(focus_labels)

    # ------------------------------------------------------------------
    # Resolve previous-period attention state (chain link).
    # ------------------------------------------------------------------
    prior_state = book.get_latest_for_actor(actor_id)
    previous_attention_state_id = (
        prior_state.attention_state_id if prior_state is not None else None
    )

    # ------------------------------------------------------------------
    # Compose the new attention state + feedback records.
    # ------------------------------------------------------------------
    state = ActorAttentionStateRecord(
        attention_state_id=asid,
        actor_id=actor_id,
        actor_type=actor_type,
        as_of_date=iso_date,
        status="active",
        confidence=_DEFAULT_FEEDBACK_CONFIDENCE,
        max_selected_refs=max_selected_refs,
        base_profile_ids=tuple(base_profile_ids),
        focus_labels=focus_labels,
        focus_weights=focus_weights,
        source_market_environment_state_ids=tuple(market_environment_state_ids),
        source_firm_state_ids=tuple(firm_state_ids),
        source_investor_intent_ids=tuple(investor_intent_ids),
        source_valuation_ids=tuple(valuation_ids),
        source_credit_review_signal_ids=tuple(credit_review_signal_ids),
        source_dialogue_ids=tuple(dialogue_ids),
        source_escalation_candidate_ids=tuple(escalation_candidate_ids),
        previous_attention_state_id=previous_attention_state_id,
        metadata=dict(metadata or {}),
    )
    try:
        book.add_attention_state(state)
    except DuplicateAttentionStateError:
        # Already present (idempotent re-run); fetch the
        # existing record so the feedback row references it.
        state = book.get_attention_state(asid)

    source_record_ids = tuple(
        list(investor_intent_ids)
        + list(credit_review_signal_ids)
        + list(market_environment_state_ids)
        + list(firm_state_ids)
        + list(valuation_ids)
        + list(dialogue_ids)
        + list(escalation_candidate_ids)
    )

    feedback = AttentionFeedbackRecord(
        feedback_id=fbid,
        actor_id=actor_id,
        actor_type=actor_type,
        as_of_date=iso_date,
        new_attention_state_id=state.attention_state_id,
        feedback_type=feedback_type,
        trigger_label=trigger_label,
        status="recorded",
        confidence=_DEFAULT_FEEDBACK_CONFIDENCE,
        previous_attention_state_id=previous_attention_state_id,
        source_record_ids=source_record_ids,
        metadata=dict(metadata or {}),
    )
    try:
        book.add_feedback(feedback)
    except DuplicateAttentionFeedbackError:
        feedback = book.get_feedback(fbid)

    return AttentionFeedbackBuildResult(
        attention_state_id=state.attention_state_id,
        feedback_id=feedback.feedback_id,
        attention_state=state,
        feedback=feedback,
    )
