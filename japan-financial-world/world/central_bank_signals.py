"""
v1.13.4 CentralBankOperationSignalRecord +
CollateralEligibilitySignalRecord + CentralBankSignalBook.

Two append-only generic, jurisdiction-neutral signal records and a
single book that holds them. Storage only — both records are
**label-based** with a synthetic ``confidence`` ordering in
``[0.0, 1.0]``.

``CentralBankOperationSignalRecord`` names a generic central-bank
operation as a label (e.g. ``open_market_operation`` /
``standing_facility`` / ``policy_communication`` / ``unknown``)
with a direction label, a horizon label, and provenance
cross-references. There is **no operation amount, no policy
rate, no monetary-policy stance numeric, no real central-bank
operation execution, no Japan calibration, no real-system
mapping**.

``CollateralEligibilitySignalRecord`` names a generic
collateral-eligibility judgement as a label (eligibility +
haircut tier) for a synthetic collateral class. There is **no
haircut percentage, no margin number, no real collateral
revaluation, no securities settlement execution, no Japan
calibration**.

Both records carry no `amount` / `currency_value` / `balance` /
`policy_rate` / `interest` / `order` / `trade` /
`recommendation` / `investment_advice` / `forecast_value` /
`actual_value` / `real_data_value` / `behavior_probability`
field. Tests pin the absence on both the dataclass field set and
the ledger payload key set.

The book emits exactly one ledger record per ``add_operation``
or ``add_eligibility`` call (``RecordType.CENTRAL_BANK_OPERATION_SIGNAL_RECORDED``
or ``RecordType.COLLATERAL_ELIGIBILITY_SIGNAL_RECORDED``) and
refuses to mutate any other source-of-truth book in the kernel.
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


class CentralBankSignalError(Exception):
    """Base class for v1.13.4 central-bank-signal-layer errors."""


class DuplicateCentralBankOperationSignalError(CentralBankSignalError):
    """Raised when an operation_signal_id is added twice."""


class UnknownCentralBankOperationSignalError(
    CentralBankSignalError, KeyError
):
    """Raised when an operation_signal_id is not found."""


class DuplicateCollateralEligibilitySignalError(CentralBankSignalError):
    """Raised when an eligibility_signal_id is added twice."""


class UnknownCollateralEligibilitySignalError(
    CentralBankSignalError, KeyError
):
    """Raised when an eligibility_signal_id is not found."""


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


def _validate_required_strings(
    instance: Any, names: tuple[str, ...]
) -> None:
    for name in names:
        value = getattr(instance, name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} is required")


def _validate_confidence(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number")
    if not (0.0 <= float(value) <= 1.0):
        raise ValueError(
            "confidence must be between 0 and 1 inclusive "
            "(synthetic ordering only; not a calibrated probability)"
        )
    return float(value)


# ---------------------------------------------------------------------------
# CentralBankOperationSignalRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CentralBankOperationSignalRecord:
    """Immutable label-based record of one synthetic generic
    central-bank operation signal. See module docstring for
    anti-claims.

    Fields
    ------
    - ``operation_signal_id`` is the stable id; unique within a
      ``CentralBankSignalBook``.
    - ``authority_id`` names the generic monetary-policy authority
      (free-form jurisdiction-neutral string).
    - ``as_of_date`` is the required ISO date.
    - ``operation_label`` (e.g. ``open_market_operation`` /
      ``standing_facility`` / ``policy_communication`` / ``unknown``).
    - ``direction_label`` (e.g. ``inject`` / ``withdraw`` /
      ``neutral`` / ``unknown``).
    - ``horizon_label`` (e.g. ``intraday`` / ``short_term`` /
      ``medium_term`` / ``long_term`` / ``unknown``).
    - ``status`` is a free-form lifecycle tag.
    - ``visibility`` is a free-form generic visibility tag.
    - ``confidence`` is a synthetic ``[0.0, 1.0]`` scalar.
    - ``source_*_ids`` are tuples of plain-id cross-references.
    - ``metadata`` is free-form.
    """

    operation_signal_id: str
    authority_id: str
    as_of_date: str
    operation_label: str
    direction_label: str
    horizon_label: str
    status: str
    visibility: str
    confidence: float
    source_settlement_account_ids: tuple[str, ...] = field(default_factory=tuple)
    source_interbank_liquidity_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_market_environment_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "operation_signal_id",
        "authority_id",
        "as_of_date",
        "operation_label",
        "direction_label",
        "horizon_label",
        "status",
        "visibility",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "source_settlement_account_ids",
        "source_interbank_liquidity_state_ids",
        "source_market_environment_state_ids",
    )

    def __post_init__(self) -> None:
        if isinstance(self.as_of_date, date):
            object.__setattr__(
                self, "as_of_date", _coerce_iso_date(self.as_of_date)
            )
        _validate_required_strings(self, self.REQUIRED_STRING_FIELDS)
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )
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
            "operation_signal_id": self.operation_signal_id,
            "authority_id": self.authority_id,
            "as_of_date": self.as_of_date,
            "operation_label": self.operation_label,
            "direction_label": self.direction_label,
            "horizon_label": self.horizon_label,
            "status": self.status,
            "visibility": self.visibility,
            "confidence": self.confidence,
            "source_settlement_account_ids": list(
                self.source_settlement_account_ids
            ),
            "source_interbank_liquidity_state_ids": list(
                self.source_interbank_liquidity_state_ids
            ),
            "source_market_environment_state_ids": list(
                self.source_market_environment_state_ids
            ),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# CollateralEligibilitySignalRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CollateralEligibilitySignalRecord:
    """Immutable label-based record of one synthetic
    collateral-eligibility judgement for a generic synthetic
    collateral class. See module docstring for anti-claims.

    Fields
    ------
    - ``eligibility_signal_id`` is the stable id; unique within a
      ``CentralBankSignalBook``.
    - ``authority_id`` names the generic eligibility authority
      (free-form jurisdiction-neutral string).
    - ``collateral_class_label`` names the synthetic collateral
      class (e.g. ``reference_government_paper`` /
      ``reference_corporate_paper`` /
      ``reference_short_term_paper`` / ``unknown``). Always
      synthetic; never a real-instrument identifier.
    - ``as_of_date`` is the required ISO date.
    - ``eligibility_label`` (e.g. ``eligible`` /
      ``conditionally_eligible`` / ``ineligible`` / ``unknown``).
    - ``haircut_tier_label`` (e.g. ``tier_low`` /
      ``tier_medium`` / ``tier_high`` / ``tier_severe`` /
      ``unknown``). **Never a percentage**.
    - ``status`` is a free-form lifecycle tag.
    - ``visibility`` is a free-form generic visibility tag.
    - ``confidence`` is a synthetic ``[0.0, 1.0]`` scalar.
    - ``source_*_ids`` are tuples of plain-id cross-references.
    - ``metadata`` is free-form.
    """

    eligibility_signal_id: str
    authority_id: str
    collateral_class_label: str
    as_of_date: str
    eligibility_label: str
    haircut_tier_label: str
    status: str
    visibility: str
    confidence: float
    source_market_environment_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_interbank_liquidity_state_ids: tuple[str, ...] = field(
        default_factory=tuple
    )
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "eligibility_signal_id",
        "authority_id",
        "collateral_class_label",
        "as_of_date",
        "eligibility_label",
        "haircut_tier_label",
        "status",
        "visibility",
    )

    TUPLE_FIELDS: ClassVar[tuple[str, ...]] = (
        "source_market_environment_state_ids",
        "source_interbank_liquidity_state_ids",
    )

    def __post_init__(self) -> None:
        if isinstance(self.as_of_date, date):
            object.__setattr__(
                self, "as_of_date", _coerce_iso_date(self.as_of_date)
            )
        _validate_required_strings(self, self.REQUIRED_STRING_FIELDS)
        object.__setattr__(
            self, "confidence", _validate_confidence(self.confidence)
        )
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
            "eligibility_signal_id": self.eligibility_signal_id,
            "authority_id": self.authority_id,
            "collateral_class_label": self.collateral_class_label,
            "as_of_date": self.as_of_date,
            "eligibility_label": self.eligibility_label,
            "haircut_tier_label": self.haircut_tier_label,
            "status": self.status,
            "visibility": self.visibility,
            "confidence": self.confidence,
            "source_market_environment_state_ids": list(
                self.source_market_environment_state_ids
            ),
            "source_interbank_liquidity_state_ids": list(
                self.source_interbank_liquidity_state_ids
            ),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class CentralBankSignalBook:
    """Append-only storage for v1.13.4 central-bank operation
    signals and collateral eligibility signals. Two record
    families share one book; ids are independent across
    families. The book emits exactly one ledger record per add
    call and refuses to mutate any other source-of-truth book.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _operations: dict[str, CentralBankOperationSignalRecord] = field(
        default_factory=dict
    )
    _eligibilities: dict[str, CollateralEligibilitySignalRecord] = field(
        default_factory=dict
    )

    # --- operations ---

    def add_operation(
        self, signal: CentralBankOperationSignalRecord
    ) -> CentralBankOperationSignalRecord:
        if signal.operation_signal_id in self._operations:
            raise DuplicateCentralBankOperationSignalError(
                f"Duplicate operation_signal_id: "
                f"{signal.operation_signal_id}"
            )
        self._operations[signal.operation_signal_id] = signal

        if self.ledger is not None:
            self.ledger.append(
                event_type="central_bank_operation_signal_recorded",
                simulation_date=self._now(),
                object_id=signal.operation_signal_id,
                source=signal.authority_id,
                payload={
                    "operation_signal_id": signal.operation_signal_id,
                    "authority_id": signal.authority_id,
                    "as_of_date": signal.as_of_date,
                    "operation_label": signal.operation_label,
                    "direction_label": signal.direction_label,
                    "horizon_label": signal.horizon_label,
                    "status": signal.status,
                    "visibility": signal.visibility,
                    "confidence": signal.confidence,
                    "source_settlement_account_ids": list(
                        signal.source_settlement_account_ids
                    ),
                    "source_interbank_liquidity_state_ids": list(
                        signal.source_interbank_liquidity_state_ids
                    ),
                    "source_market_environment_state_ids": list(
                        signal.source_market_environment_state_ids
                    ),
                },
                space_id="central_bank_signals",
                visibility=signal.visibility,
                confidence=signal.confidence,
            )
        return signal

    def get_operation(
        self, operation_signal_id: str
    ) -> CentralBankOperationSignalRecord:
        try:
            return self._operations[operation_signal_id]
        except KeyError as exc:
            raise UnknownCentralBankOperationSignalError(
                f"Operation signal not found: {operation_signal_id!r}"
            ) from exc

    def list_operations(
        self,
    ) -> tuple[CentralBankOperationSignalRecord, ...]:
        return tuple(self._operations.values())

    def list_operations_by_authority(
        self, authority_id: str
    ) -> tuple[CentralBankOperationSignalRecord, ...]:
        return tuple(
            s
            for s in self._operations.values()
            if s.authority_id == authority_id
        )

    def list_operations_by_label(
        self, operation_label: str
    ) -> tuple[CentralBankOperationSignalRecord, ...]:
        return tuple(
            s
            for s in self._operations.values()
            if s.operation_label == operation_label
        )

    # --- eligibilities ---

    def add_eligibility(
        self, signal: CollateralEligibilitySignalRecord
    ) -> CollateralEligibilitySignalRecord:
        if signal.eligibility_signal_id in self._eligibilities:
            raise DuplicateCollateralEligibilitySignalError(
                f"Duplicate eligibility_signal_id: "
                f"{signal.eligibility_signal_id}"
            )
        self._eligibilities[signal.eligibility_signal_id] = signal

        if self.ledger is not None:
            self.ledger.append(
                event_type="collateral_eligibility_signal_recorded",
                simulation_date=self._now(),
                object_id=signal.eligibility_signal_id,
                source=signal.authority_id,
                payload={
                    "eligibility_signal_id": signal.eligibility_signal_id,
                    "authority_id": signal.authority_id,
                    "collateral_class_label": signal.collateral_class_label,
                    "as_of_date": signal.as_of_date,
                    "eligibility_label": signal.eligibility_label,
                    "haircut_tier_label": signal.haircut_tier_label,
                    "status": signal.status,
                    "visibility": signal.visibility,
                    "confidence": signal.confidence,
                    "source_market_environment_state_ids": list(
                        signal.source_market_environment_state_ids
                    ),
                    "source_interbank_liquidity_state_ids": list(
                        signal.source_interbank_liquidity_state_ids
                    ),
                },
                space_id="central_bank_signals",
                visibility=signal.visibility,
                confidence=signal.confidence,
            )
        return signal

    def get_eligibility(
        self, eligibility_signal_id: str
    ) -> CollateralEligibilitySignalRecord:
        try:
            return self._eligibilities[eligibility_signal_id]
        except KeyError as exc:
            raise UnknownCollateralEligibilitySignalError(
                f"Eligibility signal not found: {eligibility_signal_id!r}"
            ) from exc

    def list_eligibilities(
        self,
    ) -> tuple[CollateralEligibilitySignalRecord, ...]:
        return tuple(self._eligibilities.values())

    def list_eligibilities_by_class(
        self, collateral_class_label: str
    ) -> tuple[CollateralEligibilitySignalRecord, ...]:
        return tuple(
            s
            for s in self._eligibilities.values()
            if s.collateral_class_label == collateral_class_label
        )

    def list_eligibilities_by_label(
        self, eligibility_label: str
    ) -> tuple[CollateralEligibilitySignalRecord, ...]:
        return tuple(
            s
            for s in self._eligibilities.values()
            if s.eligibility_label == eligibility_label
        )

    # --- snapshot / clock ---

    def snapshot(self) -> dict[str, Any]:
        operations = sorted(
            (s.to_dict() for s in self._operations.values()),
            key=lambda item: item["operation_signal_id"],
        )
        eligibilities = sorted(
            (s.to_dict() for s in self._eligibilities.values()),
            key=lambda item: item["eligibility_signal_id"],
        )
        return {
            "operation_count": len(operations),
            "operations": operations,
            "eligibility_count": len(eligibilities),
            "eligibilities": eligibilities,
        }

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
