from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class InvestorStateError(Exception):
    """Base class for investors-space state errors."""


class DuplicateInvestorStateError(InvestorStateError):
    """Raised when an investor_id is added twice."""


@dataclass(frozen=True)
class InvestorState:
    """
    Minimal internal record InvestorSpace keeps about an investor.

    Mirrors FirmState (§27) and BankState (§28): identity-level facts
    only. An InvestorState stores which investor, what type they are,
    what tier they occupy, and what status they are currently in. v0.10
    deliberately leaves out everything else — AUM, NAV, allocation
    weights, mandate, return target, risk profile — because those are
    derivable (or will be derivable) from the world's books.

    The intent is to give InvestorSpace just enough native classification
    to organize investors (e.g., for filtering by type or tier when
    selecting which investors to read views for) without introducing
    trading behavior.
    """

    investor_id: str
    investor_type: str = "unspecified"
    tier: str = "unspecified"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.investor_id:
            raise ValueError("investor_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "investor_id": self.investor_id,
            "investor_type": self.investor_type,
            "tier": self.tier,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PortfolioExposure:
    """
    Read-only view of a single position the investor holds.

    A PortfolioExposure is a *projection* derived from OwnershipBook
    cross-referenced with PriceBook (for valuation) and Registry (for
    asset-type classification). It is rebuilt every time it is
    requested. Mutating it has no effect on the underlying books.

    v0.10 simplifications (intentional):
        - market_value = quantity * latest_price when both are present;
          ``None`` otherwise. No model price, no time-weighted average.
        - latest_price is taken from the most recent PriceBook
          observation regardless of source. If multiple sources priced
          the same asset, the latest wins.
        - asset_type comes from Registry only. If the asset is not
          registered, asset_type is ``None``. v0.10 does not infer
          types from id prefixes or any other heuristic.
        - Missing data does not crash. Missing-price and missing-
          asset-type cases are reflected in ``metadata`` flags so the
          caller can detect them; they do not alter quantity.
        - No strategy or intent is inferred from holdings. A position
          in an asset is just a position; whether the investor is long,
          short, hedging, market-making, or rebalancing is not for
          v0.10 to decide.
    """

    investor_id: str
    asset_id: str
    quantity: float
    latest_price: float | None
    market_value: float | None
    asset_type: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "investor_id": self.investor_id,
            "asset_id": self.asset_id,
            "quantity": self.quantity,
            "latest_price": self.latest_price,
            "market_value": self.market_value,
            "asset_type": self.asset_type,
            "metadata": dict(self.metadata),
        }
