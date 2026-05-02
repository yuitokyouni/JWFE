"""
v1.13.1 SettlementAccountRecord + SettlementAccountBook.

The first concrete code milestone in the v1.13 generic central
bank settlement infrastructure sequence (v1.13.0 was docs-only;
see ``docs/v1_13_generic_central_bank_settlement_design.md`` and
``world_model.md`` §87 for the full design).

v1.13.1 ships **storage only** — append-only records of
synthetic settlement accounts at a generic settlement system.
There are **no real balances**, **no central-bank accounting**,
**no real payment processing**, **no real-system mapping**,
**no Japan calibration**. Every identifier is
jurisdiction-neutral and synthetic. (Real-system identifiers
like the Japanese RTGS system are explicitly out of scope for
public FWE; see the v1.13.0 design note for the public /
private boundary.)

Records are immutable; the book is append-only and emits exactly
one ledger record per ``add_account`` call
(``RecordType.SETTLEMENT_ACCOUNT_REGISTERED``). It refuses to
mutate any other source-of-truth book in the kernel.

Anti-fields (binding)
=====================

The record deliberately has **no** ``balance``,
``available_credit``, ``pending_settlement_amount``,
``interest_accrued``, ``debit_limit``, ``credit_line``,
``cash_balance``, ``reserve_balance``, ``required_reserve``,
``policy_rate``, ``order``, ``trade``, ``recommendation``,
``investment_advice``, ``forecast_value``, ``actual_value``,
``real_data_value``, or ``behavior_probability`` field. Tests
pin the absence on both the dataclass field set and the ledger
payload key set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SettlementAccountError(Exception):
    """Base class for v1.13.1 settlement-account-layer errors."""


class DuplicateSettlementAccountError(SettlementAccountError):
    """Raised when an account_id is added twice."""


class UnknownSettlementAccountError(SettlementAccountError, KeyError):
    """Raised when an account_id is not found."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("date must be a date or ISO string")


def _coerce_optional_iso_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    return _coerce_iso_date(value)


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SettlementAccountRecord:
    """Immutable record of one synthetic settlement account at a
    generic settlement system.

    Field semantics
    ---------------
    - ``account_id`` is the stable id; unique within a
      ``SettlementAccountBook``.
    - ``owner_institution_id`` names the institution that holds
      the account. Free-form jurisdiction-neutral string.
    - ``owner_type`` is a small free-form tag (e.g.,
      ``"participant_bank"``, ``"clearing_member"``,
      ``"investor_custodian"``). v1.13.1 stores the tag without
      enforcing membership in any specific list.
    - ``account_type`` is a small free-form tag (e.g.,
      ``"reserve_account"``, ``"settlement_account"``,
      ``"restricted_account"``).
    - ``currency_label`` is a free-form synthetic currency tag
      (``"reference_currency_a"``, ``"reference_currency_b"``,
      etc.). **Never** an ISO 4217 code or any real currency.
    - ``settlement_system_id`` is a free-form tag naming the
      synthetic settlement system the account is held at.
      **Never** a real-system identifier (e.g., a real RTGS or
      large-value payment system name); those map at v2 / v3.
    - ``status`` is a small free-form lifecycle tag
      (``"active"`` / ``"frozen"`` / ``"closed"``).
    - ``visibility`` is a free-form generic visibility tag.
    - ``opened_date`` is the required ISO ``YYYY-MM-DD`` date.
    - ``closed_date`` is an optional ISO date; ``None`` means
      open.
    - ``metadata`` is free-form.

    Anti-fields
    -----------
    See module docstring. v1.13.1 stores **no** balance, no
    accounting figure, no calibrated number.
    """

    account_id: str
    owner_institution_id: str
    owner_type: str
    account_type: str
    currency_label: str
    settlement_system_id: str
    status: str
    visibility: str
    opened_date: str
    closed_date: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "account_id",
        "owner_institution_id",
        "owner_type",
        "account_type",
        "currency_label",
        "settlement_system_id",
        "status",
        "visibility",
        "opened_date",
    )

    def __post_init__(self) -> None:
        for name in self.REQUIRED_STRING_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, (str, date)) or (
                isinstance(value, str) and not value
            ):
                raise ValueError(f"{name} is required")

        object.__setattr__(
            self, "opened_date", _coerce_iso_date(self.opened_date)
        )
        object.__setattr__(
            self, "closed_date", _coerce_optional_iso_date(self.closed_date)
        )

        if (
            self.closed_date is not None
            and self.closed_date < self.opened_date
        ):
            raise ValueError(
                "closed_date must be on or after opened_date"
            )

        object.__setattr__(self, "metadata", dict(self.metadata))

    def is_active_as_of(self, as_of: date | str) -> bool:
        """Return True iff the account is open and not closed at
        the given date. ``status`` must also be ``"active"``."""
        target = _coerce_iso_date(as_of)
        if self.status != "active":
            return False
        if target < self.opened_date:
            return False
        if self.closed_date is not None and target > self.closed_date:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "owner_institution_id": self.owner_institution_id,
            "owner_type": self.owner_type,
            "account_type": self.account_type,
            "currency_label": self.currency_label,
            "settlement_system_id": self.settlement_system_id,
            "status": self.status,
            "visibility": self.visibility,
            "opened_date": self.opened_date,
            "closed_date": self.closed_date,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class SettlementAccountBook:
    """Append-only storage for ``SettlementAccountRecord`` instances.

    The book emits exactly one ledger record per ``add_account``
    call (``RecordType.SETTLEMENT_ACCOUNT_REGISTERED``) and
    refuses to mutate any other source-of-truth book in the
    kernel. v1.13.1 ships storage and read-only listings only —
    no payment processing, no balance update, no settlement
    execution.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _accounts: dict[str, SettlementAccountRecord] = field(
        default_factory=dict
    )

    def add_account(
        self, account: SettlementAccountRecord
    ) -> SettlementAccountRecord:
        if account.account_id in self._accounts:
            raise DuplicateSettlementAccountError(
                f"Duplicate account_id: {account.account_id}"
            )
        self._accounts[account.account_id] = account

        if self.ledger is not None:
            self.ledger.append(
                event_type="settlement_account_registered",
                simulation_date=self._now(),
                object_id=account.account_id,
                source=account.owner_institution_id,
                payload={
                    "account_id": account.account_id,
                    "owner_institution_id": account.owner_institution_id,
                    "owner_type": account.owner_type,
                    "account_type": account.account_type,
                    "currency_label": account.currency_label,
                    "settlement_system_id": account.settlement_system_id,
                    "status": account.status,
                    "visibility": account.visibility,
                    "opened_date": account.opened_date,
                    "closed_date": account.closed_date,
                },
                space_id="settlement",
                visibility=account.visibility,
            )
        return account

    def get_account(self, account_id: str) -> SettlementAccountRecord:
        try:
            return self._accounts[account_id]
        except KeyError as exc:
            raise UnknownSettlementAccountError(
                f"Settlement account not found: {account_id!r}"
            ) from exc

    def list_accounts(self) -> tuple[SettlementAccountRecord, ...]:
        return tuple(self._accounts.values())

    def list_by_owner(
        self, owner_institution_id: str
    ) -> tuple[SettlementAccountRecord, ...]:
        return tuple(
            a
            for a in self._accounts.values()
            if a.owner_institution_id == owner_institution_id
        )

    def list_by_account_type(
        self, account_type: str
    ) -> tuple[SettlementAccountRecord, ...]:
        return tuple(
            a
            for a in self._accounts.values()
            if a.account_type == account_type
        )

    def list_by_status(
        self, status: str
    ) -> tuple[SettlementAccountRecord, ...]:
        return tuple(
            a for a in self._accounts.values() if a.status == status
        )

    def list_active_as_of(
        self, as_of: date | str
    ) -> tuple[SettlementAccountRecord, ...]:
        return tuple(
            a for a in self._accounts.values() if a.is_active_as_of(as_of)
        )

    def snapshot(self) -> dict[str, Any]:
        accounts = sorted(
            (a.to_dict() for a in self._accounts.values()),
            key=lambda item: item["account_id"],
        )
        return {
            "account_count": len(accounts),
            "accounts": accounts,
        }

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
