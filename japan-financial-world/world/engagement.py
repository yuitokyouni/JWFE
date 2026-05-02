"""
v1.10.2 PortfolioCompanyDialogueRecord + DialogueBook.

Implements the second concrete primitive of the v1.10 engagement /
strategic-response layer named in
``docs/v1_10_universal_engagement_and_response_design.md`` and §70 of
``docs/world_model.md``:

- ``PortfolioCompanyDialogueRecord`` — a single immutable, append-only
  record naming that an *engagement contact* happened in a given
  period between an investor / steward / asset owner (the
  *initiator*) and a portfolio company (the *counterparty*), under
  zero or more stewardship themes, with a generic outcome label and
  a generic next-step label.
- ``DialogueBook`` — append-only storage with read-only listings, a
  date-keyed listing helper, and a deterministic snapshot.

Scope discipline (v1.10.2)
==========================

A ``PortfolioCompanyDialogueRecord`` is **dialogue metadata**, not a
transcript and not an engagement-execution engine. It records *that*
a contact happened, *who* it was between, *which* themes it
referenced, *what* generic outcome label the steward attached to it,
and *what* generic next-step label the steward attached to it. It
does not store verbatim or paraphrased contents, meeting notes,
attendee lists, non-public company information, named-client
material, or expert-interview content — those are restricted under
``docs/public_private_boundary.md`` and never appear in public FWE.

By itself, a dialogue record:

- does **not** vote, file proxies, or execute any AGM / EGM action;
- does **not** escalate any concern (escalation candidates are a
  separate v1.10.3 primitive);
- does **not** produce any corporate-response candidate (corporate
  response candidates are a separate v1.10.3 primitive);
- does **not** recommend any investment, divestment, or weight
  change;
- does **not** trade, change ownership, or move any price;
- does **not** form any forecast or behavior probability;
- does **not** mutate any other source-of-truth book in the kernel
  (only the ``DialogueBook`` itself and the kernel ledger are
  written to).

The record fields are jurisdiction-neutral by construction. The book
refuses to validate the controlled-vocabulary fields (``dialogue_type``,
``status``, ``outcome_label``, ``next_step_label``, ``visibility``,
``initiator_type``, ``counterparty_type``) against any specific
country, regulator, code, or named institution — those calibrations
live in v2 (Japan public-data) and beyond, not here.

Cross-references (``initiator_id``, ``counterparty_id``,
``theme_ids``, ``related_signal_ids``, ``related_valuation_ids``,
``related_pressure_signal_ids``) are recorded as data and **not**
validated for resolution against any other book, per the v0/v1
cross-reference rule already used by ``world/attention.py``,
``world/routines.py``, and ``world/stewardship.py``.

v1.10.2 ships zero economic behavior: no price formation, no trading,
no lending decisions, no corporate actions, no policy reaction
functions, no Japan calibration, no calibrated behavior
probabilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class EngagementError(Exception):
    """Base class for engagement-layer errors."""


class DuplicateDialogueError(EngagementError):
    """Raised when a dialogue_id is added twice."""


class UnknownDialogueError(EngagementError, KeyError):
    """Raised when a dialogue_id is not found."""


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
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PortfolioCompanyDialogueRecord:
    """
    Immutable record of one portfolio-company engagement touchpoint.

    A dialogue record names that an engagement contact happened
    between an investor / steward (the *initiator*) and a portfolio
    company (the *counterparty*) on a given date, under zero or more
    stewardship themes, with generic outcome and next-step labels.
    The record is **dialogue metadata only** — it does not carry
    verbatim or paraphrased contents.

    Field semantics
    ---------------
    - ``dialogue_id`` is the stable id; unique within a
      ``DialogueBook``. Dialogues are append-only — a record is
      never mutated in place; instead, a new record is added (with a
      different ``dialogue_id``) when the engagement state changes.
    - ``initiator_id`` and ``initiator_type`` name the investor /
      asset owner / steward who initiated the contact. Free-form
      strings; cross-references are recorded as data and not
      validated against the registry.
    - ``counterparty_id`` and ``counterparty_type`` name the
      portfolio company / firm on the receiving side of the contact.
      Free-form strings; cross-references are recorded as data and
      not validated against the registry.
    - ``as_of_date`` is the required ISO ``YYYY-MM-DD`` date naming
      the period the dialogue is recorded against.
    - ``dialogue_type`` is a free-form controlled-vocabulary tag
      describing the kind of contact. Suggested generic,
      jurisdiction-neutral labels: ``"private_meeting"``,
      ``"public_statement"``, ``"private_letter"``,
      ``"questionnaire_response"``, ``"information_request"``,
      ``"follow_up_meeting"``. v1.10.2 stores the tag without
      enforcing membership in any specific list.
    - ``theme_ids`` is a tuple of stewardship-theme ids referenced
      by the dialogue. Cross-references are stored as data and not
      validated against ``StewardshipBook``.
    - ``related_signal_ids`` is a tuple of signal ids referenced by
      the dialogue (e.g., disclosure signals, observation signals).
      Cross-references are not validated against ``SignalBook``.
    - ``related_valuation_ids`` is a tuple of valuation ids
      referenced by the dialogue. Cross-references are not
      validated against ``ValuationBook``.
    - ``related_pressure_signal_ids`` is a tuple of v1.9.4 pressure
      assessment signal ids referenced by the dialogue. Recorded as
      a separate slot from ``related_signal_ids`` so the audit trace
      can distinguish ordinary information signals from firm
      operating-pressure assessments without re-parsing the signal
      payloads.
    - ``status`` is a small free-form tag tracking the dialogue's
      lifecycle stage in the steward's own framing. Recommended
      jurisdiction-neutral labels: ``"draft"`` / ``"logged"`` /
      ``"awaiting_response"`` / ``"resolved"`` / ``"closed"``.
    - ``outcome_label`` is a small free-form tag describing the
      generic outcome class the steward attached to the contact.
      Recommended jurisdiction-neutral labels: ``"acknowledged"`` /
      ``"partial_response"`` / ``"no_response"`` /
      ``"information_received"`` / ``"position_unchanged"``.
      **Never** a forecast and **never** a calibrated probability.
    - ``next_step_label`` is a small free-form tag describing the
      generic follow-up class the steward attached to the contact.
      Recommended jurisdiction-neutral labels: ``"no_action"`` /
      ``"continue_monitoring"`` / ``"follow_up_meeting"`` /
      ``"escalation_candidate"`` / ``"close_engagement"``. The label
      is metadata only — it does **not** by itself trigger any
      escalation, voting, trading, or corporate-response
      mechanism.
    - ``visibility`` is a free-form generic visibility tag.
      Recommended jurisdiction-neutral labels: ``"public"`` /
      ``"internal_only"`` / ``"restricted"``. The label is metadata
      only and **does not** gate access at the runtime layer in
      v1.10.2 — it is recorded so that downstream filtering and
      downstream JFWE Public / JFWE Proprietary boundaries can rely
      on it.
    - ``metadata`` is free-form for provenance, parameters, and
      steward notes. **Must not** carry verbatim or paraphrased
      dialogue contents, meeting notes, attendee lists, non-public
      company information, named-client material, or expert-interview
      content.

    Anti-fields
    -----------
    The record deliberately has **no** ``transcript``, ``content``,
    ``notes``, ``minutes``, ``attendees``, or equivalent fields. A
    public-FWE record stores generic labels and IDs only; verbatim
    or paraphrased dialogue contents are restricted artifacts under
    ``docs/public_private_boundary.md``.
    """

    dialogue_id: str
    initiator_id: str
    counterparty_id: str
    initiator_type: str
    counterparty_type: str
    as_of_date: str
    dialogue_type: str
    status: str
    outcome_label: str
    next_step_label: str
    visibility: str
    theme_ids: tuple[str, ...] = field(default_factory=tuple)
    related_signal_ids: tuple[str, ...] = field(default_factory=tuple)
    related_valuation_ids: tuple[str, ...] = field(default_factory=tuple)
    related_pressure_signal_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "dialogue_id",
        "initiator_id",
        "counterparty_id",
        "initiator_type",
        "counterparty_type",
        "as_of_date",
        "dialogue_type",
        "status",
        "outcome_label",
        "next_step_label",
        "visibility",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "theme_ids",
        "related_signal_ids",
        "related_valuation_ids",
        "related_pressure_signal_ids",
    )

    def __post_init__(self) -> None:
        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, (str, date)) or (
                isinstance(value, str) and not value
            ):
                raise ValueError(f"{name} is required")

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
            "dialogue_id": self.dialogue_id,
            "initiator_id": self.initiator_id,
            "counterparty_id": self.counterparty_id,
            "initiator_type": self.initiator_type,
            "counterparty_type": self.counterparty_type,
            "as_of_date": self.as_of_date,
            "dialogue_type": self.dialogue_type,
            "status": self.status,
            "outcome_label": self.outcome_label,
            "next_step_label": self.next_step_label,
            "visibility": self.visibility,
            "theme_ids": list(self.theme_ids),
            "related_signal_ids": list(self.related_signal_ids),
            "related_valuation_ids": list(self.related_valuation_ids),
            "related_pressure_signal_ids": list(
                self.related_pressure_signal_ids
            ),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class DialogueBook:
    """
    Append-only storage for ``PortfolioCompanyDialogueRecord`` instances.

    The book emits exactly one ledger record per ``add_dialogue`` call
    (``RecordType.PORTFOLIO_COMPANY_DIALOGUE_RECORDED``) and refuses to
    mutate any other source-of-truth book in the kernel. v1.10.2 ships
    storage and read-only listings only — no automatic dialogue
    inference, no engagement execution, no escalation, no
    corporate-response generation, no economic behavior.

    Cross-references (``initiator_id``, ``counterparty_id``,
    ``theme_ids``, ``related_signal_ids``, ``related_valuation_ids``,
    ``related_pressure_signal_ids``) are recorded as data and not
    validated against any other book, per the v0/v1 cross-reference
    rule.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _dialogues: dict[str, PortfolioCompanyDialogueRecord] = field(
        default_factory=dict
    )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_dialogue(
        self, dialogue: PortfolioCompanyDialogueRecord
    ) -> PortfolioCompanyDialogueRecord:
        if dialogue.dialogue_id in self._dialogues:
            raise DuplicateDialogueError(
                f"Duplicate dialogue_id: {dialogue.dialogue_id}"
            )
        self._dialogues[dialogue.dialogue_id] = dialogue

        if self.ledger is not None:
            self.ledger.append(
                event_type="portfolio_company_dialogue_recorded",
                simulation_date=self._now(),
                object_id=dialogue.dialogue_id,
                source=dialogue.initiator_id,
                target=dialogue.counterparty_id,
                payload={
                    "dialogue_id": dialogue.dialogue_id,
                    "initiator_id": dialogue.initiator_id,
                    "counterparty_id": dialogue.counterparty_id,
                    "initiator_type": dialogue.initiator_type,
                    "counterparty_type": dialogue.counterparty_type,
                    "as_of_date": dialogue.as_of_date,
                    "dialogue_type": dialogue.dialogue_type,
                    "status": dialogue.status,
                    "outcome_label": dialogue.outcome_label,
                    "next_step_label": dialogue.next_step_label,
                    "visibility": dialogue.visibility,
                    "theme_ids": list(dialogue.theme_ids),
                    "related_signal_ids": list(dialogue.related_signal_ids),
                    "related_valuation_ids": list(
                        dialogue.related_valuation_ids
                    ),
                    "related_pressure_signal_ids": list(
                        dialogue.related_pressure_signal_ids
                    ),
                },
                space_id="engagement",
                agent_id=dialogue.initiator_id,
                visibility=dialogue.visibility,
            )
        return dialogue

    def get_dialogue(
        self, dialogue_id: str
    ) -> PortfolioCompanyDialogueRecord:
        try:
            return self._dialogues[dialogue_id]
        except KeyError as exc:
            raise UnknownDialogueError(
                f"Dialogue not found: {dialogue_id!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Listings
    # ------------------------------------------------------------------

    def list_dialogues(self) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        """Every dialogue, in insertion order."""
        return tuple(self._dialogues.values())

    def list_by_initiator(
        self, initiator_id: str
    ) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        return tuple(
            d
            for d in self._dialogues.values()
            if d.initiator_id == initiator_id
        )

    def list_by_counterparty(
        self, counterparty_id: str
    ) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        return tuple(
            d
            for d in self._dialogues.values()
            if d.counterparty_id == counterparty_id
        )

    def list_by_theme(
        self, theme_id: str
    ) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        return tuple(
            d for d in self._dialogues.values() if theme_id in d.theme_ids
        )

    def list_by_status(
        self, status: str
    ) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        return tuple(
            d for d in self._dialogues.values() if d.status == status
        )

    def list_by_dialogue_type(
        self, dialogue_type: str
    ) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        return tuple(
            d
            for d in self._dialogues.values()
            if d.dialogue_type == dialogue_type
        )

    def list_by_date(
        self, as_of: date | str
    ) -> tuple[PortfolioCompanyDialogueRecord, ...]:
        target = _coerce_iso_date(as_of)
        return tuple(
            d for d in self._dialogues.values() if d.as_of_date == target
        )

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        dialogues = sorted(
            (d.to_dict() for d in self._dialogues.values()),
            key=lambda item: item["dialogue_id"],
        )
        return {
            "dialogue_count": len(dialogues),
            "dialogues": dialogues,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
