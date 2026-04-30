from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


class InstitutionError(Exception):
    """Base class for institution-layer errors."""


class DuplicateInstitutionProfileError(InstitutionError):
    """Raised when an institution_id is added twice."""


class DuplicateMandateError(InstitutionError):
    """Raised when a mandate_id is added twice."""


class DuplicateInstrumentProfileError(InstitutionError):
    """Raised when an instrument_id is added twice in InstitutionBook."""


class DuplicateInstitutionalActionError(InstitutionError):
    """Raised when an action_id is added twice."""


class UnknownInstitutionProfileError(InstitutionError, KeyError):
    """Raised when an institution_id is not found."""


class UnknownInstitutionalActionError(InstitutionError, KeyError):
    """Raised when an action_id is not found."""


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstitutionProfile:
    """
    Identity-level record for an institutional actor.

    An institution is a real-world organization with a mandate and
    instruments — a central bank, a treasury, a financial regulator, a
    deposit insurer, an exchange authority, a market operator. v1.3
    stores classification only: which institution, what kind, under
    what jurisdiction *label*, with what mandate summary, over what
    authority scope, in what status.

    Field semantics
    ---------------
    - ``jurisdiction_label`` is a free-form string. v1 deliberately
      uses neutral labels such as ``"neutral_jurisdiction"`` or
      ``"reference_jurisdiction_a"`` so that institution shapes are
      separable from jurisdiction calibration. v2 will populate this
      field with real jurisdiction identifiers (e.g. ``"jp"``); v1.3
      treats the field as a label, not as a calibration anchor.
    - ``mandate_summary`` is a one-line free-form summary. The full
      mandate set lives in :class:`MandateRecord`.
    - ``authority_scope`` is a tuple of free-form domain strings (e.g.
      ``("monetary_policy", "lender_of_last_resort")``). v1.3 does not
      enumerate or validate scopes.
    - ``status`` defaults to ``"active"``.
    """

    institution_id: str
    institution_type: str
    jurisdiction_label: str = "neutral_jurisdiction"
    mandate_summary: str = ""
    authority_scope: tuple[str, ...] = field(default_factory=tuple)
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.institution_id:
            raise ValueError("institution_id is required")
        if not self.institution_type:
            raise ValueError("institution_type is required")
        object.__setattr__(self, "authority_scope", tuple(self.authority_scope))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "institution_id": self.institution_id,
            "institution_type": self.institution_type,
            "jurisdiction_label": self.jurisdiction_label,
            "mandate_summary": self.mandate_summary,
            "authority_scope": list(self.authority_scope),
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MandateRecord:
    """
    A single mandate held by an institution.

    A real institution may carry multiple mandates that interact and
    sometimes conflict (e.g. price stability vs financial stability vs
    employment maximization). v1.3 stores them as separate records so
    later milestones can reason about them individually.

    Fields
    ------
    - ``priority`` is a free-form integer. Lower values rank higher;
      v1.3 does not enforce a specific scale. Future modules that
      aggregate mandates can interpret the field according to the
      institution.
    """

    mandate_id: str
    institution_id: str
    mandate_type: str
    description: str = ""
    priority: int = 0
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mandate_id:
            raise ValueError("mandate_id is required")
        if not self.institution_id:
            raise ValueError("institution_id is required")
        if not self.mandate_type:
            raise ValueError("mandate_type is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "mandate_id": self.mandate_id,
            "institution_id": self.institution_id,
            "mandate_type": self.mandate_type,
            "description": self.description,
            "priority": self.priority,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PolicyInstrumentProfile:
    """
    Profile of a policy instrument owned by an institution.

    Distinct from v0.14's :class:`PolicyInstrumentState` (which lives
    inside ``PolicySpace`` as a domain-space classification). The v1.3
    profile sits at the kernel level and ties an instrument to a
    specific :class:`InstitutionProfile`. Both layers can coexist; they
    answer different questions:

    - PolicyInstrumentState — "what instruments exist in PolicySpace?"
    - PolicyInstrumentProfile — "which institution owns / wields this
      instrument, and what does it target?"

    Fields
    ------
    - ``target_domain`` is a free-form label naming what the instrument
      is meant to influence (e.g. ``"short_rate"``, ``"bank_capital"``,
      ``"exchange_rate"``). v1.3 does not enumerate domains.
    """

    instrument_id: str
    institution_id: str
    instrument_type: str
    target_domain: str = "unspecified"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.instrument_id:
            raise ValueError("instrument_id is required")
        if not self.institution_id:
            raise ValueError("institution_id is required")
        if not self.instrument_type:
            raise ValueError("instrument_type is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "institution_id": self.institution_id,
            "instrument_type": self.instrument_type,
            "target_domain": self.target_domain,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class InstitutionalActionRecord:
    """
    A record of one institutional action.

    v1.3 stores actions as facts: "this institution, on this date,
    took this action, drawing on these inputs, producing these
    outputs". The action record itself does **not** mutate the world.
    The mutations (price changes, new contracts, new signals, etc.)
    flow through the existing kernel-level books and are referenced
    here via ``input_refs``, ``output_refs``, ``target_ids``, and
    ``instrument_ids``.

    The 4-property action contract
    ------------------------------
    Every InstitutionalActionRecord must satisfy:

    1. **Explicit inputs.** ``input_refs`` lists the WorldIDs / record
       IDs the action consumed. Empty tuple is allowed (some actions
       are seed actions); ``None`` is not.
    2. **Explicit outputs.** ``output_refs`` lists what the action
       produced. Empty tuple is allowed.
    3. **Ledger record.** Adding the action to ``InstitutionBook``
       emits an ``institution_action_recorded`` ledger record with
       ``parent_record_ids`` preserved.
    4. **No direct cross-space mutation.** The action record itself
       cannot modify other books or other spaces. Side effects must
       go through the documented channels (OwnershipBook,
       ContractBook, PriceBook, SignalBook, ConstraintBook,
       ValuationBook, EventBus) and are referenced from this record,
       not driven by it.

    This is the contract every v1.3+ behavioral module will follow
    when it produces an action.
    """

    action_id: str
    institution_id: str
    action_type: str
    as_of_date: str
    phase_id: str | None = None
    input_refs: tuple[str, ...] = field(default_factory=tuple)
    output_refs: tuple[str, ...] = field(default_factory=tuple)
    target_ids: tuple[str, ...] = field(default_factory=tuple)
    instrument_ids: tuple[str, ...] = field(default_factory=tuple)
    payload: Mapping[str, Any] = field(default_factory=dict)
    parent_record_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("action_id is required")
        if not self.institution_id:
            raise ValueError("institution_id is required")
        if not self.action_type:
            raise ValueError("action_type is required")
        if not self.as_of_date:
            raise ValueError("as_of_date is required")
        object.__setattr__(self, "as_of_date", _coerce_iso_date(self.as_of_date))
        object.__setattr__(self, "input_refs", tuple(self.input_refs))
        object.__setattr__(self, "output_refs", tuple(self.output_refs))
        object.__setattr__(self, "target_ids", tuple(self.target_ids))
        object.__setattr__(self, "instrument_ids", tuple(self.instrument_ids))
        object.__setattr__(self, "parent_record_ids", tuple(self.parent_record_ids))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "institution_id": self.institution_id,
            "action_type": self.action_type,
            "as_of_date": self.as_of_date,
            "phase_id": self.phase_id,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "target_ids": list(self.target_ids),
            "instrument_ids": list(self.instrument_ids),
            "payload": dict(self.payload),
            "parent_record_ids": list(self.parent_record_ids),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# InstitutionBook
# ---------------------------------------------------------------------------


@dataclass
class InstitutionBook:
    """
    Storage for institutional profiles, mandates, instruments, and
    recorded actions.

    Like every other v0/v1 book, ``InstitutionBook`` is append-only,
    emits ledger records on mutation, and refuses to mutate any other
    book. It is read by future v1.3+ behavioral modules but does not
    drive them.

    The four entity types it stores share kernel-level identity:
    ``institution_id``, ``mandate_id``, ``instrument_id``, ``action_id``
    are all unique within their own bucket. Cross-references (a
    mandate's ``institution_id``, an action's ``instrument_ids``, etc.)
    are recorded as data and **not** validated for resolution — this
    matches the v0 / v1 cross-reference rule.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _institutions: dict[str, InstitutionProfile] = field(default_factory=dict)
    _mandates: dict[str, MandateRecord] = field(default_factory=dict)
    _instruments: dict[str, PolicyInstrumentProfile] = field(default_factory=dict)
    _actions: dict[str, InstitutionalActionRecord] = field(default_factory=dict)
    _mandates_by_institution: dict[str, list[str]] = field(default_factory=dict)
    _instruments_by_institution: dict[str, list[str]] = field(default_factory=dict)
    _actions_by_institution: dict[str, list[str]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # InstitutionProfile
    # ------------------------------------------------------------------

    def add_institution_profile(
        self, profile: InstitutionProfile
    ) -> InstitutionProfile:
        if profile.institution_id in self._institutions:
            raise DuplicateInstitutionProfileError(
                f"Duplicate institution_id: {profile.institution_id}"
            )
        self._institutions[profile.institution_id] = profile

        if self.ledger is not None:
            self.ledger.append(
                event_type="institution_profile_added",
                simulation_date=self._now(),
                object_id=profile.institution_id,
                payload={
                    "institution_id": profile.institution_id,
                    "institution_type": profile.institution_type,
                    "jurisdiction_label": profile.jurisdiction_label,
                    "mandate_summary": profile.mandate_summary,
                    "authority_scope": list(profile.authority_scope),
                    "status": profile.status,
                },
                space_id="institutions",
            )
        return profile

    def get_institution_profile(self, institution_id: str) -> InstitutionProfile:
        try:
            return self._institutions[institution_id]
        except KeyError as exc:
            raise UnknownInstitutionProfileError(
                f"Institution not found: {institution_id!r}"
            ) from exc

    def list_by_type(
        self, institution_type: str
    ) -> tuple[InstitutionProfile, ...]:
        return tuple(
            profile
            for profile in self._institutions.values()
            if profile.institution_type == institution_type
        )

    def all_institutions(self) -> tuple[InstitutionProfile, ...]:
        return tuple(self._institutions.values())

    # ------------------------------------------------------------------
    # MandateRecord
    # ------------------------------------------------------------------

    def add_mandate(self, record: MandateRecord) -> MandateRecord:
        if record.mandate_id in self._mandates:
            raise DuplicateMandateError(
                f"Duplicate mandate_id: {record.mandate_id}"
            )
        self._mandates[record.mandate_id] = record
        self._mandates_by_institution.setdefault(
            record.institution_id, []
        ).append(record.mandate_id)

        if self.ledger is not None:
            self.ledger.append(
                event_type="institution_mandate_added",
                simulation_date=self._now(),
                object_id=record.mandate_id,
                target=record.institution_id,
                payload={
                    "mandate_id": record.mandate_id,
                    "institution_id": record.institution_id,
                    "mandate_type": record.mandate_type,
                    "priority": record.priority,
                    "status": record.status,
                },
                space_id="institutions",
            )
        return record

    def list_mandates_by_institution(
        self, institution_id: str
    ) -> tuple[MandateRecord, ...]:
        ids = self._mandates_by_institution.get(institution_id, [])
        return tuple(self._mandates[mid] for mid in ids)

    # ------------------------------------------------------------------
    # PolicyInstrumentProfile
    # ------------------------------------------------------------------

    def add_instrument_profile(
        self, profile: PolicyInstrumentProfile
    ) -> PolicyInstrumentProfile:
        if profile.instrument_id in self._instruments:
            raise DuplicateInstrumentProfileError(
                f"Duplicate instrument_id: {profile.instrument_id}"
            )
        self._instruments[profile.instrument_id] = profile
        self._instruments_by_institution.setdefault(
            profile.institution_id, []
        ).append(profile.instrument_id)

        if self.ledger is not None:
            self.ledger.append(
                event_type="institution_instrument_added",
                simulation_date=self._now(),
                object_id=profile.instrument_id,
                target=profile.institution_id,
                payload={
                    "instrument_id": profile.instrument_id,
                    "institution_id": profile.institution_id,
                    "instrument_type": profile.instrument_type,
                    "target_domain": profile.target_domain,
                    "status": profile.status,
                },
                space_id="institutions",
            )
        return profile

    def list_instruments_by_institution(
        self, institution_id: str
    ) -> tuple[PolicyInstrumentProfile, ...]:
        ids = self._instruments_by_institution.get(institution_id, [])
        return tuple(self._instruments[iid] for iid in ids)

    # ------------------------------------------------------------------
    # InstitutionalActionRecord
    # ------------------------------------------------------------------

    def add_action_record(
        self, record: InstitutionalActionRecord
    ) -> InstitutionalActionRecord:
        if record.action_id in self._actions:
            raise DuplicateInstitutionalActionError(
                f"Duplicate action_id: {record.action_id}"
            )
        self._actions[record.action_id] = record
        self._actions_by_institution.setdefault(
            record.institution_id, []
        ).append(record.action_id)

        if self.ledger is not None:
            self.ledger.append(
                event_type="institution_action_recorded",
                simulation_date=record.as_of_date,
                object_id=record.action_id,
                source=record.institution_id,
                payload={
                    "action_id": record.action_id,
                    "institution_id": record.institution_id,
                    "action_type": record.action_type,
                    "phase_id": record.phase_id,
                    "input_refs": list(record.input_refs),
                    "output_refs": list(record.output_refs),
                    "target_ids": list(record.target_ids),
                    "instrument_ids": list(record.instrument_ids),
                },
                parent_record_ids=record.parent_record_ids,
                space_id="institutions",
            )
        return record

    def get_action_record(self, action_id: str) -> InstitutionalActionRecord:
        try:
            return self._actions[action_id]
        except KeyError as exc:
            raise UnknownInstitutionalActionError(
                f"Action not found: {action_id!r}"
            ) from exc

    def list_actions_by_institution(
        self, institution_id: str
    ) -> tuple[InstitutionalActionRecord, ...]:
        ids = self._actions_by_institution.get(institution_id, [])
        return tuple(self._actions[aid] for aid in ids)

    def all_actions(self) -> tuple[InstitutionalActionRecord, ...]:
        return tuple(self._actions.values())

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        institutions = sorted(
            (p.to_dict() for p in self._institutions.values()),
            key=lambda item: item["institution_id"],
        )
        mandates = sorted(
            (m.to_dict() for m in self._mandates.values()),
            key=lambda item: item["mandate_id"],
        )
        instruments = sorted(
            (i.to_dict() for i in self._instruments.values()),
            key=lambda item: item["instrument_id"],
        )
        actions = sorted(
            (a.to_dict() for a in self._actions.values()),
            key=lambda item: item["action_id"],
        )
        return {
            "institution_count": len(institutions),
            "mandate_count": len(mandates),
            "instrument_count": len(instruments),
            "action_count": len(actions),
            "institutions": institutions,
            "mandates": mandates,
            "instruments": instruments,
            "actions": actions,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
