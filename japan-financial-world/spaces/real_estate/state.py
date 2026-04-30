from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class RealEstateStateError(Exception):
    """Base class for real-estate-space state errors."""


class DuplicatePropertyMarketStateError(RealEstateStateError):
    """Raised when a property_market_id is added twice."""


class DuplicatePropertyAssetStateError(RealEstateStateError):
    """Raised when an asset_id is added twice."""


@dataclass(frozen=True)
class PropertyMarketState:
    """
    Minimal internal record RealEstateSpace keeps about a property market.

    A property market is a regional / typological grouping (e.g.,
    "Tokyo central office", "Osaka residential", "Fukuoka logistics").
    v0.12 stores identity-level facts only: which market, what region
    it covers, what property type, what tier, what status. It does
    NOT store cap rate, vacancy rate, rent index, transaction volume,
    or any other dynamic that real-estate behavior would need —
    because v0.12 does not implement that behavior.

    The intent is to give RealEstateSpace just enough native
    classification to organize property assets by market without
    introducing market-formation logic.
    """

    property_market_id: str
    region: str = "unspecified"
    property_type: str = "unspecified"
    tier: str = "unspecified"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.property_market_id:
            raise ValueError("property_market_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "property_market_id": self.property_market_id,
            "region": self.region,
            "property_type": self.property_type,
            "tier": self.tier,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PropertyAssetState:
    """
    Identity-level record for a single real estate asset.

    Each PropertyAssetState is keyed by ``asset_id`` (its WorldID) and
    declares which property market it belongs to via
    ``property_market_id``. The market reference is a foreign key, not
    a composite key — a property asset belongs to exactly one property
    market in v0.12.

    Contrast with v0.11 ListingState
    --------------------------------
    Exchange listings are *relations*: the same asset can appear on
    multiple markets (cross-listed equity), so listings are keyed by
    ``(market_id, asset_id)``. Property assets in v0.12 cannot be in
    two property markets at once — a building is in Tokyo central or
    in Osaka residential, not both — so the natural primary key is
    just ``asset_id``. v0.12 does not validate that the referenced
    ``property_market_id`` is registered in the space; that lookup
    is the caller's responsibility.

    What this record does NOT carry: cap rate, NOI, rent roll, lease
    schedule, vacancy %, valuation, comparable sales. These are the
    foundation of real-estate behavior, and v0.12 does not implement
    that behavior.
    """

    asset_id: str
    property_market_id: str
    asset_type: str = "unspecified"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if not self.property_market_id:
            raise ValueError("property_market_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "property_market_id": self.property_market_id,
            "asset_type": self.asset_type,
            "status": self.status,
            "metadata": dict(self.metadata),
        }
