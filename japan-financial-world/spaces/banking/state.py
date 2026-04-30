from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class BankingStateError(Exception):
    """Base class for banking-space state errors."""


class DuplicateBankStateError(BankingStateError):
    """Raised when a bank_id is added twice."""


@dataclass(frozen=True)
class BankState:
    """
    Minimal internal record BankSpace keeps about a bank.

    Mirrors the FirmState pattern from §27: identity-level facts only.
    A BankState stores which bank, what type it is, what tier it
    occupies, and what status it is currently in. v0.9 deliberately
    leaves out everything else — capital, deposits, loan book, RWA,
    NPL ratio, spread — because those are derivable (or will be
    derivable) from the world's books.

    The intent is to give BankSpace just enough native classification
    to organize banks (e.g., for filtering by type or tier when
    selecting which banks to read views for) without introducing
    credit behavior.
    """

    bank_id: str
    bank_type: str = "unspecified"
    tier: str = "unspecified"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bank_id:
            raise ValueError("bank_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "bank_id": self.bank_id,
            "bank_type": self.bank_type,
            "tier": self.tier,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class LendingExposure:
    """
    Read-only view of a single lending position the bank holds.

    A LendingExposure is a *projection* derived from ContractBook. It is
    rebuilt every time it is requested. Mutating it has no effect on the
    underlying contract.

    v0.9 simplifications (intentional):
        - The exposure carries face-value `principal` only; no
          present-value, no accrued interest, no amortization.
        - `borrower_id` is whatever sits in `metadata["borrower_id"]`
          on the contract. v0.9 does not infer roles from the parties
          tuple.
        - No credit-quality classification (performing / non-performing
          / impaired). That is a domain decision deferred to later
          milestones.
        - Status is copied from the contract verbatim.

    The intent of LendingExposure is to give BankSpace an ergonomic
    view of "what loans does this bank hold?" without forcing callers
    to grep contract metadata themselves.
    """

    contract_id: str
    lender_id: str
    borrower_id: str | None
    principal: float | None
    contract_type: str
    status: str
    collateral_asset_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "collateral_asset_ids", tuple(self.collateral_asset_ids)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "lender_id": self.lender_id,
            "borrower_id": self.borrower_id,
            "principal": self.principal,
            "contract_type": self.contract_type,
            "status": self.status,
            "collateral_asset_ids": list(self.collateral_asset_ids),
        }
