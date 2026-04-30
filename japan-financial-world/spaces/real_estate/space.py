from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spaces.domain import DomainSpace
from spaces.real_estate.state import (
    DuplicatePropertyAssetStateError,
    DuplicatePropertyMarketStateError,
    PropertyAssetState,
    PropertyMarketState,
)
from world.prices import PriceBook, PriceRecord
from world.scheduler import Frequency


@dataclass
class RealEstateSpace(DomainSpace):
    """
    Real Estate Space — minimum internal state for property markets and
    property assets.

    v0.12 scope:
        - hold a mapping of property_market_id -> PropertyMarketState
        - hold a mapping of asset_id -> PropertyAssetState
          (each asset declares the property_market_id it belongs to)
        - read PriceBook for latest price and price history of a
          property asset
        - read SignalBook for visibility-filtered signals
        - log property_market_state_added and property_asset_state_added
          when those records enter the space

    v0.12 explicitly does NOT implement:
        - real estate price formation, appraisals, or model marks
        - cap rate updates, rent updates, vacancy dynamics
        - transaction matching or property market clearing
        - fire sale logic, distressed sale dynamics
        - collateral haircut or LTV breach reactions
        - REIT NAV computation or investment-vehicle logic
        - any mutation of source books or other spaces

    Beyond the common refs supplied by :class:`DomainSpace`,
    RealEstateSpace captures :attr:`prices` so it can answer simple
    price-history queries on registered property assets. The
    DomainSpace accessors (:meth:`get_balance_sheet_view`,
    :meth:`get_constraint_evaluations`, :meth:`get_visible_signals`)
    are inherited unchanged — RealEstate rarely needs the first two
    but the inheritance is consistent and free.

    Contrast with ExchangeSpace (§31)
    ---------------------------------
    Exchange listings are relations keyed by ``(market_id, asset_id)``
    because the same asset can appear on multiple markets. Property
    assets in v0.12 belong to exactly one property market, so they
    are keyed by ``asset_id`` alone with ``property_market_id`` as a
    foreign key. The two-entity shape is the same; the cardinality of
    the asset → market relationship differs.
    """

    space_id: str = "real_estate"
    frequencies: tuple[Frequency, ...] = (
        Frequency.MONTHLY,
        Frequency.QUARTERLY,
    )
    prices: PriceBook | None = None
    _property_markets: dict[str, PropertyMarketState] = field(default_factory=dict)
    _property_assets: dict[str, PropertyAssetState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lifecycle hook — extends DomainSpace.bind() with prices
    # ------------------------------------------------------------------

    def bind(self, kernel: Any) -> None:
        """Extend DomainSpace.bind() to also capture ``prices``."""
        super().bind(kernel)
        if self.prices is None:
            self.prices = kernel.prices

    # ------------------------------------------------------------------
    # Property market CRUD
    # ------------------------------------------------------------------

    def add_property_market_state(
        self,
        market_state: PropertyMarketState,
    ) -> PropertyMarketState:
        if market_state.property_market_id in self._property_markets:
            raise DuplicatePropertyMarketStateError(
                f"Duplicate property_market_id: {market_state.property_market_id}"
            )
        self._property_markets[market_state.property_market_id] = market_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="property_market_state_added",
                simulation_date=simulation_date,
                object_id=market_state.property_market_id,
                payload={
                    "property_market_id": market_state.property_market_id,
                    "region": market_state.region,
                    "property_type": market_state.property_type,
                    "tier": market_state.tier,
                    "status": market_state.status,
                },
                space_id=self.space_id,
            )
        return market_state

    def get_property_market_state(
        self,
        property_market_id: str,
    ) -> PropertyMarketState | None:
        return self._property_markets.get(property_market_id)

    def list_property_markets(self) -> tuple[PropertyMarketState, ...]:
        """Return all registered property markets in insertion order."""
        return tuple(self._property_markets.values())

    # ------------------------------------------------------------------
    # Property asset CRUD
    # ------------------------------------------------------------------

    def add_property_asset_state(
        self,
        asset_state: PropertyAssetState,
    ) -> PropertyAssetState:
        if asset_state.asset_id in self._property_assets:
            raise DuplicatePropertyAssetStateError(
                f"Duplicate asset_id: {asset_state.asset_id}"
            )
        self._property_assets[asset_state.asset_id] = asset_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="property_asset_state_added",
                simulation_date=simulation_date,
                object_id=asset_state.asset_id,
                target=asset_state.property_market_id,
                payload={
                    "asset_id": asset_state.asset_id,
                    "property_market_id": asset_state.property_market_id,
                    "asset_type": asset_state.asset_type,
                    "status": asset_state.status,
                },
                space_id=self.space_id,
            )
        return asset_state

    def get_property_asset_state(
        self,
        asset_id: str,
    ) -> PropertyAssetState | None:
        return self._property_assets.get(asset_id)

    def list_property_assets(self) -> tuple[PropertyAssetState, ...]:
        """Return all registered property assets in insertion order."""
        return tuple(self._property_assets.values())

    def list_assets_in_property_market(
        self,
        property_market_id: str,
    ) -> tuple[PropertyAssetState, ...]:
        """
        Return every property asset declared to belong to the given market.

        This is a filter over registered ``PropertyAssetState`` records
        whose ``property_market_id`` matches. v0.12 does not validate
        that ``property_market_id`` itself is registered; an asset may
        reference a market_id that has not yet been added (or never
        will be).
        """
        return tuple(
            asset
            for asset in self._property_assets.values()
            if asset.property_market_id == property_market_id
        )

    # ------------------------------------------------------------------
    # Price-derived views
    # ------------------------------------------------------------------

    def get_latest_price(self, asset_id: str) -> PriceRecord | None:
        """
        Return the most recent PriceRecord for a property asset.

        Returns ``None`` if the asset has no recorded price or if
        :attr:`prices` is unbound. As in §31 (ExchangeSpace), v0.12
        does not gate price reads on whether the asset is registered
        in this space — the ``PriceBook`` is the canonical price
        source regardless of classification.
        """
        if self.prices is None:
            return None
        return self.prices.get_latest_price(asset_id)

    def get_price_history(
        self,
        asset_id: str,
    ) -> tuple[PriceRecord, ...]:
        """
        Return the chronological PriceRecord history for a property asset.

        Returns ``()`` if the asset has no recorded price or if
        :attr:`prices` is unbound.
        """
        if self.prices is None:
            return ()
        return self.prices.get_price_history(asset_id)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """
        Return a deterministic, JSON-friendly view of the space.

        Property markets are sorted by ``property_market_id``. Property
        assets are sorted by ``asset_id``. Both are stable across runs.
        """
        property_markets = sorted(
            (market.to_dict() for market in self._property_markets.values()),
            key=lambda item: item["property_market_id"],
        )
        property_assets = sorted(
            (asset.to_dict() for asset in self._property_assets.values()),
            key=lambda item: item["asset_id"],
        )
        return {
            "space_id": self.space_id,
            "property_market_count": len(property_markets),
            "property_asset_count": len(property_assets),
            "property_markets": property_markets,
            "property_assets": property_assets,
        }
