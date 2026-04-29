from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


def _coerce_iso_date(value: date | str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("simulation_date must be date or ISO string")


@dataclass(frozen=True)
class PriceRecord:
    """
    A single observation of a price for an asset.

    A PriceRecord is stamped with the simulation_date at which it was
    observed and the source that produced it. Past prices are retained:
    a price at time t never overwrites the meaning of a price at t-1.
    """

    asset_id: str
    price: float
    simulation_date: str
    source: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("asset_id is required")
        if not self.source:
            raise ValueError("source is required")
        object.__setattr__(self, "simulation_date", _coerce_iso_date(self.simulation_date))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "price": self.price,
            "simulation_date": self.simulation_date,
            "source": self.source,
            "metadata": dict(self.metadata),
        }


@dataclass
class PriceBook:
    """
    Append-only history of price observations per asset.

    Responsibility:
        - record price observations
        - return the latest observation for an asset
        - return the full history for an asset
        - emit price_updated ledger records

    Non-responsibility:
        - no price formation
        - no model-based valuation
        - no comparison or arbitrage between price types
        - no decision about which source is authoritative
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _history: dict[str, list[PriceRecord]] = field(default_factory=dict)

    def set_price(
        self,
        asset_id: str,
        price: float,
        simulation_date: date | str,
        source: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> PriceRecord:
        record = PriceRecord(
            asset_id=asset_id,
            price=float(price),
            simulation_date=simulation_date,
            source=source,
            metadata=dict(metadata or {}),
        )

        history = self._history.setdefault(asset_id, [])
        history.append(record)

        self._record(
            event_type="price_updated",
            object_id=asset_id,
            simulation_date=record.simulation_date,
            source=source,
            payload={
                "asset_id": asset_id,
                "price": record.price,
                "source": source,
                "history_length": len(history),
            },
        )
        return record

    def get_latest_price(self, asset_id: str) -> PriceRecord | None:
        history = self._history.get(asset_id)
        if not history:
            return None
        return history[-1]

    def get_price_history(self, asset_id: str) -> tuple[PriceRecord, ...]:
        return tuple(self._history.get(asset_id, ()))

    def known_assets(self) -> tuple[str, ...]:
        return tuple(self._history.keys())

    def snapshot(self) -> dict[str, Any]:
        latest_prices = {
            asset_id: history[-1].to_dict()
            for asset_id, history in self._history.items()
            if history
        }
        history_lengths = {
            asset_id: len(history) for asset_id, history in self._history.items()
        }
        return {
            "count": len(latest_prices),
            "latest_prices": latest_prices,
            "history_lengths": history_lengths,
        }

    def _record(
        self,
        *,
        event_type: str,
        object_id: str,
        simulation_date: str | None,
        source: str | None,
        payload: Mapping[str, Any],
    ) -> None:
        if self.ledger is None:
            return

        sim_date = simulation_date
        if sim_date is None and self.clock is not None:
            sim_date = self.clock.current_date.isoformat()

        self.ledger.append(
            event_type=event_type,
            simulation_date=sim_date,
            object_id=object_id,
            source=source,
            payload=dict(payload),
            space_id="prices",
        )
