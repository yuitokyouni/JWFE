from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


class OwnershipError(Exception):
    """Base class for ownership-book errors."""


class InsufficientQuantityError(OwnershipError):
    """Raised when a transfer exceeds the available quantity."""


class UnknownPositionError(OwnershipError):
    """Raised when transferring from an owner that has no position."""


@dataclass(frozen=True)
class OwnershipRecord:
    """
    A single ownership position keyed by (owner_id, asset_id).

    The book aggregates all add_position calls for the same (owner, asset)
    pair into one record. acquisition_price and metadata reflect the most
    recent add_position call. v0.4 intentionally avoids weighted averages
    or lot accounting: those are business decisions, not transport state.
    """

    owner_id: str
    asset_id: str
    quantity: float
    acquisition_price: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "asset_id": self.asset_id,
            "quantity": self.quantity,
            "acquisition_price": self.acquisition_price,
            "metadata": dict(self.metadata),
        }


@dataclass
class OwnershipBook:
    """
    Tracks who owns what.

    An OwnershipBook is a transport-layer registry: it records ownership
    facts and changes. It does not decide who buys, who sells, what an
    asset is worth, or what economic effect ownership has.

    Optional ledger and clock references let the book emit
    ownership_position_added / ownership_transferred records with the
    current simulation date. When neither is set, the book operates as a
    plain in-memory store (useful for unit tests).
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _positions: dict[tuple[str, str], OwnershipRecord] = field(default_factory=dict)

    def add_position(
        self,
        owner_id: str,
        asset_id: str,
        quantity: float,
        *,
        acquisition_price: float | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> OwnershipRecord:
        if quantity <= 0:
            raise ValueError("quantity must be positive")

        key = (owner_id, asset_id)
        existing = self._positions.get(key)

        if existing is None:
            record = OwnershipRecord(
                owner_id=owner_id,
                asset_id=asset_id,
                quantity=float(quantity),
                acquisition_price=acquisition_price,
                metadata=dict(metadata or {}),
            )
        else:
            record = OwnershipRecord(
                owner_id=owner_id,
                asset_id=asset_id,
                quantity=existing.quantity + float(quantity),
                acquisition_price=(
                    acquisition_price
                    if acquisition_price is not None
                    else existing.acquisition_price
                ),
                metadata=dict(metadata or existing.metadata),
            )

        self._positions[key] = record
        self._record(
            event_type="ownership_position_added",
            object_id=asset_id,
            payload={
                "owner_id": owner_id,
                "asset_id": asset_id,
                "delta_quantity": float(quantity),
                "new_quantity": record.quantity,
                "acquisition_price": acquisition_price,
            },
            agent_id=owner_id,
        )
        return record

    def get_positions(self, owner_id: str) -> tuple[OwnershipRecord, ...]:
        return tuple(
            record
            for (owner, _asset), record in self._positions.items()
            if owner == owner_id
        )

    def get_owners(self, asset_id: str) -> tuple[OwnershipRecord, ...]:
        return tuple(
            record
            for (_owner, asset), record in self._positions.items()
            if asset == asset_id
        )

    def get_position(self, owner_id: str, asset_id: str) -> OwnershipRecord | None:
        return self._positions.get((owner_id, asset_id))

    def all_positions(self) -> tuple[OwnershipRecord, ...]:
        return tuple(self._positions.values())

    def transfer(
        self,
        asset_id: str,
        from_owner: str,
        to_owner: str,
        quantity: float,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> tuple[OwnershipRecord | None, OwnershipRecord]:
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if from_owner == to_owner:
            raise ValueError("from_owner and to_owner must differ")

        from_key = (from_owner, asset_id)
        from_record = self._positions.get(from_key)
        if from_record is None:
            raise UnknownPositionError(
                f"No position for owner={from_owner!r} asset={asset_id!r}"
            )
        if from_record.quantity < quantity:
            raise InsufficientQuantityError(
                f"Owner {from_owner!r} has {from_record.quantity} of {asset_id!r}; "
                f"cannot transfer {quantity}"
            )

        new_from_quantity = from_record.quantity - float(quantity)
        if new_from_quantity == 0:
            del self._positions[from_key]
            new_from_record: OwnershipRecord | None = None
        else:
            new_from_record = OwnershipRecord(
                owner_id=from_record.owner_id,
                asset_id=from_record.asset_id,
                quantity=new_from_quantity,
                acquisition_price=from_record.acquisition_price,
                metadata=dict(from_record.metadata),
            )
            self._positions[from_key] = new_from_record

        to_key = (to_owner, asset_id)
        to_existing = self._positions.get(to_key)
        if to_existing is None:
            new_to_record = OwnershipRecord(
                owner_id=to_owner,
                asset_id=asset_id,
                quantity=float(quantity),
                acquisition_price=None,
                metadata=dict(metadata or {}),
            )
        else:
            new_to_record = OwnershipRecord(
                owner_id=to_owner,
                asset_id=asset_id,
                quantity=to_existing.quantity + float(quantity),
                acquisition_price=to_existing.acquisition_price,
                metadata=dict(metadata or to_existing.metadata),
            )
        self._positions[to_key] = new_to_record

        self._record(
            event_type="ownership_transferred",
            object_id=asset_id,
            source=from_owner,
            target=to_owner,
            payload={
                "asset_id": asset_id,
                "from_owner": from_owner,
                "to_owner": to_owner,
                "quantity": float(quantity),
                "from_remaining": new_from_quantity,
                "to_total": new_to_record.quantity,
            },
        )
        return new_from_record, new_to_record

    def snapshot(self) -> dict[str, Any]:
        positions = sorted(
            (record.to_dict() for record in self._positions.values()),
            key=lambda item: (item["owner_id"], item["asset_id"]),
        )
        return {"count": len(positions), "positions": positions}

    def _record(
        self,
        *,
        event_type: str,
        object_id: str,
        payload: Mapping[str, Any],
        source: str | None = None,
        target: str | None = None,
        agent_id: str | None = None,
    ) -> None:
        if self.ledger is None:
            return

        simulation_date = (
            self.clock.current_date if self.clock is not None else None
        )

        self.ledger.append(
            event_type=event_type,
            simulation_date=simulation_date,
            object_id=object_id,
            source=source,
            target=target,
            agent_id=agent_id,
            payload=dict(payload),
            space_id="ownership",
        )
