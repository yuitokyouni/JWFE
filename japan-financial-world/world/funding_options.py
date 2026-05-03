"""
v1.14.2 FundingOptionCandidate +
FundingOptionCandidateBook.

Append-only **label-based** synthetic record naming a possible
financing route for a corporate financing need. Storage only —
there is **no loan origination, no DCM execution, no ECM
execution, no underwriting, no syndication, no security
issuance, no bookbuilding, no allocation, no loan approval, no
interest rate, no spread, no fee, no offering price, no
calibrated take-up probability, no investment advice, no real
data ingestion, no Japan calibration**.

A ``FundingOptionCandidate`` represents a *possible* financing
route — never an executed financing, never an underwriting
commitment, never a loan approval, never a securities issuance,
never a price.

The record carries seven small label fields drawn from closed
sets (see module-level constants). Membership is enforced at
construction so that downstream readers can rely on the
vocabulary:

    - ``option_type_label``       — what kind of route this is
    - ``instrument_class_label``  — generic instrument family
    - ``maturity_band_label``     — generic maturity bucket
    - ``seniority_label``         — generic seniority bucket
    - ``accessibility_label``     — generic accessibility posture
    - ``urgency_fit_label``       — fit against the cited need
    - ``market_fit_label``        — fit against market environment

Plus a synthetic ``confidence`` ordering in ``[0.0, 1.0]`` and
plain-id cross-references to the records the synthesis read
(``CorporateFinancingNeedRecord`` ids, ``MarketEnvironmentState``
ids, ``InterbankLiquidityStateRecord`` ids, firm-state ids,
bank-credit-review-signal ids, investor-intent ids).
Cross-references are stored as data and not validated against
any other book per the v0/v1 cross-reference rule.

The record carries **no** ``rate``, ``spread``, ``fee``,
``coupon``, ``price``, ``offering_price``, ``allocation``,
``underwriting``, ``syndication``, ``commitment``,
``approval``, ``executed``, ``take_up_probability``,
``expected_return``, ``recommendation``, ``investment_advice``,
or ``real_data_value`` field. Tests pin the absence on both the
dataclass field set and the ledger payload key set.

The book emits exactly one ledger record per ``add_candidate``
call (``RecordType.FUNDING_OPTION_CANDIDATE_RECORDED``) and
refuses to mutate any other source-of-truth book in the kernel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Closed-set label vocabularies
# ---------------------------------------------------------------------------


OPTION_TYPE_LABELS: frozenset[str] = frozenset(
    {
        "bank_loan_candidate",
        "bond_issuance_candidate",
        "equity_issuance_candidate",
        "internal_cash_candidate",
        "asset_sale_candidate",
        "hybrid_security_candidate",
        "unknown",
    }
)

INSTRUMENT_CLASS_LABELS: frozenset[str] = frozenset(
    {
        "loan",
        "bond",
        "equity",
        "internal_funding",
        "asset_disposal",
        "hybrid",
        "unknown",
    }
)

MATURITY_BAND_LABELS: frozenset[str] = frozenset(
    {
        "short_term",
        "medium_term",
        "long_term",
        "perpetual_or_equity_like",
        "unknown",
    }
)

SENIORITY_LABELS: frozenset[str] = frozenset(
    {
        "senior",
        "subordinated",
        "unsecured",
        "secured",
        "equity_like",
        "not_applicable",
        "unknown",
    }
)

ACCESSIBILITY_LABELS: frozenset[str] = frozenset(
    {
        "accessible",
        "selective",
        "constrained",
        "unavailable",
        "unknown",
    }
)

URGENCY_FIT_LABELS: frozenset[str] = frozenset(
    {
        "immediate",
        "near_term",
        "medium_term",
        "strategic",
        "unknown",
    }
)

MARKET_FIT_LABELS: frozenset[str] = frozenset(
    {
        "supportive",
        "mixed",
        "restrictive",
        "unknown",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FundingOptionError(Exception):
    """Base class for v1.14.2 funding-option-layer errors."""


class DuplicateFundingOptionCandidateError(FundingOptionError):
    """Raised when a funding_option_id is added twice."""


class UnknownFundingOptionCandidateError(FundingOptionError, KeyError):
    """Raised when a funding_option_id is not found."""


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


def _validate_label(
    value: str, allowed: frozenset[str], *, field_name: str
) -> None:
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {sorted(allowed)!r}; "
            f"got {value!r}"
        )


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FundingOptionCandidate:
    """Immutable record of one possible financing route for a
    firm's corporate financing need at a point in time.

    See module docstring for label vocabularies; v1.14.2 enforces
    closed-set membership at construction so downstream readers
    can rely on the small label sets.

    Field semantics
    ---------------
    - ``funding_option_id`` is the stable id; unique within a
      ``FundingOptionCandidateBook``.
    - ``firm_id`` names the firm whose financing-need posture
      this candidate is built against. Free-form
      jurisdiction-neutral string.
    - ``as_of_date`` is the required ISO date.
    - the seven label fields take values from the closed sets
      defined as module-level frozensets.
    - ``confidence`` is a synthetic ``[0.0, 1.0]`` scalar — the
      synthesis's ordering on how strongly the cited evidence
      supports this route. Booleans rejected. **Never** a
      calibrated take-up probability or any external-action
      probability.
    - ``status`` is a small free-form lifecycle tag.
    - ``visibility`` is a free-form generic visibility tag.
    - ``source_*_ids`` are tuples of plain-id cross-references.
    - ``metadata`` is free-form.
    """

    funding_option_id: str
    firm_id: str
    as_of_date: str
    option_type_label: str
    instrument_class_label: str
    maturity_band_label: str
    seniority_label: str
    accessibility_label: str
    urgency_fit_label: str
    market_fit_label: str
    status: str
    visibility: str
    confidence: float
    source_need_ids: tuple[str, ...] = field(default_factory=tuple)
    source_market_environment_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_interbank_liquidity_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_firm_state_ids: tuple[str, ...] = field(default_factory=tuple)
    source_bank_credit_review_signal_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_investor_intent_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "funding_option_id",
        "firm_id",
        "as_of_date",
        "option_type_label",
        "instrument_class_label",
        "maturity_band_label",
        "seniority_label",
        "accessibility_label",
        "urgency_fit_label",
        "market_fit_label",
        "status",
        "visibility",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "source_need_ids",
        "source_market_environment_state_ids",
        "source_interbank_liquidity_state_ids",
        "source_firm_state_ids",
        "source_bank_credit_review_signal_ids",
        "source_investor_intent_ids",
    )

    LABEL_FIELDS: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = (
        ("option_type_label", OPTION_TYPE_LABELS),
        ("instrument_class_label", INSTRUMENT_CLASS_LABELS),
        ("maturity_band_label", MATURITY_BAND_LABELS),
        ("seniority_label", SENIORITY_LABELS),
        ("accessibility_label", ACCESSIBILITY_LABELS),
        ("urgency_fit_label", URGENCY_FIT_LABELS),
        ("market_fit_label", MARKET_FIT_LABELS),
    )

    def __post_init__(self) -> None:
        if isinstance(self.as_of_date, date):
            object.__setattr__(
                self, "as_of_date", _coerce_iso_date(self.as_of_date)
            )

        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} is required")

        for label_field, allowed in self.LABEL_FIELDS:
            _validate_label(
                getattr(self, label_field),
                allowed,
                field_name=label_field,
            )

        if (
            isinstance(self.confidence, bool)
            or not isinstance(self.confidence, (int, float))
        ):
            raise ValueError("confidence must be a number")
        if not (0.0 <= float(self.confidence) <= 1.0):
            raise ValueError(
                "confidence must be between 0 and 1 inclusive "
                "(synthetic ordering only; not a calibrated "
                "take-up probability)"
            )
        object.__setattr__(self, "confidence", float(self.confidence))

        object.__setattr__(
            self, "as_of_date", _coerce_iso_date(self.as_of_date)
        )

        for tuple_field_name in self.TUPLE_FIELDS:
            value = getattr(self, tuple_field_name)
            normalized = _normalize_string_tuple(
                value, field_name=tuple_field_name
            )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "funding_option_id": self.funding_option_id,
            "firm_id": self.firm_id,
            "as_of_date": self.as_of_date,
            "option_type_label": self.option_type_label,
            "instrument_class_label": self.instrument_class_label,
            "maturity_band_label": self.maturity_band_label,
            "seniority_label": self.seniority_label,
            "accessibility_label": self.accessibility_label,
            "urgency_fit_label": self.urgency_fit_label,
            "market_fit_label": self.market_fit_label,
            "status": self.status,
            "visibility": self.visibility,
            "confidence": self.confidence,
            "source_need_ids": list(self.source_need_ids),
            "source_market_environment_state_ids": list(
                self.source_market_environment_state_ids
            ),
            "source_interbank_liquidity_state_ids": list(
                self.source_interbank_liquidity_state_ids
            ),
            "source_firm_state_ids": list(self.source_firm_state_ids),
            "source_bank_credit_review_signal_ids": list(
                self.source_bank_credit_review_signal_ids
            ),
            "source_investor_intent_ids": list(self.source_investor_intent_ids),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class FundingOptionCandidateBook:
    """Append-only storage for v1.14.2
    ``FundingOptionCandidate`` instances. The book emits exactly
    one ledger record per ``add_candidate`` call
    (``RecordType.FUNDING_OPTION_CANDIDATE_RECORDED``) and
    refuses to mutate any other source-of-truth book.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _candidates: dict[str, FundingOptionCandidate] = field(
        default_factory=dict
    )

    def add_candidate(
        self, candidate: FundingOptionCandidate
    ) -> FundingOptionCandidate:
        if candidate.funding_option_id in self._candidates:
            raise DuplicateFundingOptionCandidateError(
                f"Duplicate funding_option_id: {candidate.funding_option_id}"
            )
        self._candidates[candidate.funding_option_id] = candidate

        if self.ledger is not None:
            self.ledger.append(
                event_type="funding_option_candidate_recorded",
                simulation_date=self._now(),
                object_id=candidate.funding_option_id,
                source=candidate.firm_id,
                payload={
                    "funding_option_id": candidate.funding_option_id,
                    "firm_id": candidate.firm_id,
                    "as_of_date": candidate.as_of_date,
                    "option_type_label": candidate.option_type_label,
                    "instrument_class_label": candidate.instrument_class_label,
                    "maturity_band_label": candidate.maturity_band_label,
                    "seniority_label": candidate.seniority_label,
                    "accessibility_label": candidate.accessibility_label,
                    "urgency_fit_label": candidate.urgency_fit_label,
                    "market_fit_label": candidate.market_fit_label,
                    "status": candidate.status,
                    "visibility": candidate.visibility,
                    "confidence": candidate.confidence,
                    "source_need_ids": list(candidate.source_need_ids),
                    "source_market_environment_state_ids": list(
                        candidate.source_market_environment_state_ids
                    ),
                    "source_interbank_liquidity_state_ids": list(
                        candidate.source_interbank_liquidity_state_ids
                    ),
                    "source_firm_state_ids": list(
                        candidate.source_firm_state_ids
                    ),
                    "source_bank_credit_review_signal_ids": list(
                        candidate.source_bank_credit_review_signal_ids
                    ),
                    "source_investor_intent_ids": list(
                        candidate.source_investor_intent_ids
                    ),
                },
                space_id="funding_options",
                visibility=candidate.visibility,
                confidence=candidate.confidence,
            )
        return candidate

    def get_candidate(self, funding_option_id: str) -> FundingOptionCandidate:
        try:
            return self._candidates[funding_option_id]
        except KeyError as exc:
            raise UnknownFundingOptionCandidateError(
                f"Funding option candidate not found: {funding_option_id!r}"
            ) from exc

    def list_candidates(self) -> tuple[FundingOptionCandidate, ...]:
        return tuple(self._candidates.values())

    def list_by_firm(
        self, firm_id: str
    ) -> tuple[FundingOptionCandidate, ...]:
        return tuple(
            c for c in self._candidates.values() if c.firm_id == firm_id
        )

    def list_by_option_type(
        self, option_type_label: str
    ) -> tuple[FundingOptionCandidate, ...]:
        return tuple(
            c
            for c in self._candidates.values()
            if c.option_type_label == option_type_label
        )

    def list_by_instrument_class(
        self, instrument_class_label: str
    ) -> tuple[FundingOptionCandidate, ...]:
        return tuple(
            c
            for c in self._candidates.values()
            if c.instrument_class_label == instrument_class_label
        )

    def list_by_accessibility(
        self, accessibility_label: str
    ) -> tuple[FundingOptionCandidate, ...]:
        return tuple(
            c
            for c in self._candidates.values()
            if c.accessibility_label == accessibility_label
        )

    def list_by_status(
        self, status: str
    ) -> tuple[FundingOptionCandidate, ...]:
        return tuple(
            c for c in self._candidates.values() if c.status == status
        )

    def list_by_date(
        self, as_of: date | str
    ) -> tuple[FundingOptionCandidate, ...]:
        target = _coerce_iso_date(as_of)
        return tuple(
            c for c in self._candidates.values() if c.as_of_date == target
        )

    def list_by_need(
        self, need_id: str
    ) -> tuple[FundingOptionCandidate, ...]:
        return tuple(
            c
            for c in self._candidates.values()
            if need_id in c.source_need_ids
        )

    def snapshot(self) -> dict[str, Any]:
        candidates = sorted(
            (c.to_dict() for c in self._candidates.values()),
            key=lambda item: item["funding_option_id"],
        )
        return {
            "candidate_count": len(candidates),
            "candidates": candidates,
        }

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
