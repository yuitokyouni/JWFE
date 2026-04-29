from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

import copy
import hashlib
import json

from .ledger import Ledger, RecordType


class StateLayer(str, Enum):
    TRUE = "true_state"
    PUBLISHED = "published_state"
    MARKET = "market_state"
    PERCEIVED = "perceived_state"


class StateAccessError(PermissionError):
    pass


def _coerce_timestamp(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))

    if not isinstance(value, datetime):
        raise TypeError("timestamp must be datetime, ISO string, or None")

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _coerce_simulation_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise TypeError("simulation_date must be date, string, or None")


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, set):
        return tuple(_freeze(v) for v in sorted(value, key=str))
    return copy.deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [_thaw(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return copy.deepcopy(value)


def _stable_hash(value: Any, length: int = 16) -> str:
    raw = json.dumps(
        _thaw(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


@dataclass(frozen=True)
class StateEntry:
    layer: StateLayer
    object_id: str
    version: int
    value: Any
    updated_at: datetime
    simulation_date: str | None
    source: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "layer", StateLayer(self.layer))
        object.__setattr__(self, "updated_at", _coerce_timestamp(self.updated_at))
        object.__setattr__(self, "simulation_date", _coerce_simulation_date(self.simulation_date))
        object.__setattr__(self, "value", _freeze(self.value))
        object.__setattr__(self, "metadata", _freeze(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "layer": self.layer.value,
            "object_id": self.object_id,
            "version": self.version,
            "value": _thaw(self.value),
            "updated_at": self.updated_at.isoformat(),
            "simulation_date": self.simulation_date,
            "source": self.source,
            "metadata": _thaw(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StateEntry:
        return cls(
            layer=StateLayer(data["layer"]),
            object_id=data["object_id"],
            version=int(data["version"]),
            value=data["value"],
            updated_at=_coerce_timestamp(data["updated_at"]),
            simulation_date=data.get("simulation_date"),
            source=data.get("source"),
            metadata=data.get("metadata") or {},
        )


@dataclass(frozen=True)
class StateSnapshot:
    snapshot_id: str
    created_at: datetime
    simulation_date: str | None
    state_hash: str
    entries: Mapping[str, Mapping[str, StateEntry]]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return self.snapshot_id

    def __post_init__(self) -> None:
        normalized: dict[str, Mapping[str, StateEntry]] = {}

        for layer, object_map in self.entries.items():
            layer_name = StateLayer(layer).value
            normalized[layer_name] = MappingProxyType(
                {
                    object_id: entry if isinstance(entry, StateEntry) else StateEntry.from_dict(entry)
                    for object_id, entry in object_map.items()
                }
            )

        object.__setattr__(self, "created_at", _coerce_timestamp(self.created_at))
        object.__setattr__(self, "simulation_date", _coerce_simulation_date(self.simulation_date))
        object.__setattr__(self, "entries", MappingProxyType(normalized))
        object.__setattr__(self, "metadata", _freeze(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at.isoformat(),
            "simulation_date": self.simulation_date,
            "state_hash": self.state_hash,
            "entries": {
                layer: {
                    object_id: entry.to_dict()
                    for object_id, entry in object_map.items()
                }
                for layer, object_map in self.entries.items()
            },
            "metadata": _thaw(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> StateSnapshot:
        return cls(
            snapshot_id=data["snapshot_id"],
            created_at=_coerce_timestamp(data["created_at"]),
            simulation_date=data.get("simulation_date"),
            state_hash=data["state_hash"],
            entries=data["entries"],
            metadata=data.get("metadata") or {},
        )


class StateStore:
    def __init__(self) -> None:
        self._current: dict[StateLayer, dict[str, StateEntry]] = {
            layer: {} for layer in StateLayer
        }
        self._history: dict[tuple[str, str], list[StateEntry]] = {}

    def set_state(
        self,
        layer: StateLayer | str,
        object_id: str,
        value: Any,
        *,
        source: str | None = None,
        simulation_date: date | str | None = None,
        metadata: Mapping[str, Any] | None = None,
        owner_id: str | None = None,
        updated_at: datetime | str | None = None,
    ) -> StateEntry:
        layer = StateLayer(layer)

        if not object_id:
            raise ValueError("object_id is required")

        metadata_dict = dict(metadata or {})

        if layer == StateLayer.PERCEIVED:
            if owner_id is not None:
                metadata_dict["owner_id"] = owner_id
            if "owner_id" not in metadata_dict:
                raise ValueError("perceived_state requires owner_id")

        current = self._current[layer].get(object_id)
        version = 1 if current is None else current.version + 1

        entry = StateEntry(
            layer=layer,
            object_id=object_id,
            version=version,
            value=value,
            updated_at=_coerce_timestamp(updated_at),
            simulation_date=_coerce_simulation_date(simulation_date),
            source=source,
            metadata=metadata_dict,
        )

        self._current[layer][object_id] = entry
        self._history.setdefault((layer.value, object_id), []).append(entry)
        return entry

    def read_state(
        self,
        layer: StateLayer | str,
        object_id: str,
        *,
        requester_role: str = "system",
        requester_id: str | None = None,
    ) -> Any:
        entry = self.read_entry(
            layer,
            object_id,
            requester_role=requester_role,
            requester_id=requester_id,
        )
        return _thaw(entry.value)

    def read_entry(
        self,
        layer: StateLayer | str,
        object_id: str,
        *,
        requester_role: str = "system",
        requester_id: str | None = None,
    ) -> StateEntry:
        layer = StateLayer(layer)
        entry = self._current[layer].get(object_id)

        if entry is None:
            raise KeyError(f"state not found: layer={layer.value}, object_id={object_id}")

        self._assert_can_read(
            entry,
            requester_role=requester_role,
            requester_id=requester_id,
        )

        return entry

    def history(
        self,
        layer: StateLayer | str,
        object_id: str,
        *,
        requester_role: str = "system",
        requester_id: str | None = None,
    ) -> tuple[StateEntry, ...]:
        layer = StateLayer(layer)

        if object_id in self._current[layer]:
            self._assert_can_read(
                self._current[layer][object_id],
                requester_role=requester_role,
                requester_id=requester_id,
            )

        return tuple(self._history.get((layer.value, object_id), ()))

    def query_layer(
        self,
        layer: StateLayer | str,
        *,
        requester_role: str = "system",
        requester_id: str | None = None,
    ) -> dict[str, Any]:
        layer = StateLayer(layer)
        result: dict[str, Any] = {}

        for object_id, entry in self._current[layer].items():
            try:
                self._assert_can_read(
                    entry,
                    requester_role=requester_role,
                    requester_id=requester_id,
                )
            except StateAccessError:
                continue
            result[object_id] = _thaw(entry.value)

        return result

    def create_snapshot(
        self,
        *,
        simulation_date: date | str | None = None,
        source: str = "state",
        ledger: Ledger | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> StateSnapshot:
        simulation_date = _coerce_simulation_date(simulation_date)
        metadata = dict(metadata or {})

        entries = {
            layer.value: dict(object_map)
            for layer, object_map in self._current.items()
        }

        canonical_entries = {
            layer: {
                object_id: entry.to_dict()
                for object_id, entry in object_map.items()
            }
            for layer, object_map in entries.items()
        }

        state_hash = f"sha256:{_stable_hash(canonical_entries, length=32)}"
        snapshot_id = f"snapshot_{_stable_hash({'simulation_date': simulation_date, 'state_hash': state_hash}, length=16)}"

        snapshot = StateSnapshot(
            snapshot_id=snapshot_id,
            created_at=_coerce_timestamp(None),
            simulation_date=simulation_date,
            state_hash=state_hash,
            entries=entries,
            metadata=metadata,
        )

        if ledger is not None:
            ledger.append(
                RecordType.STATE_SNAPSHOT_CREATED,
                simulation_date=simulation_date,
                source=source,
                object_id=snapshot_id,
                payload={
                    "snapshot_id": snapshot_id,
                    "state_hash": state_hash,
                    "layer_counts": {
                        layer.value: len(object_map)
                        for layer, object_map in self._current.items()
                    },
                },
                metadata=metadata,
            )

        return snapshot

    def restore_snapshot(self, snapshot: StateSnapshot) -> None:
        self._current = {layer: {} for layer in StateLayer}
        self._history = {}

        for layer_name, object_map in snapshot.entries.items():
            layer = StateLayer(layer_name)
            for object_id, entry in object_map.items():
                self._current[layer][object_id] = entry
                self._history.setdefault((layer.value, object_id), []).append(entry)

    def _assert_can_read(
        self,
        entry: StateEntry,
        *,
        requester_role: str,
        requester_id: str | None,
    ) -> None:
        role = requester_role.lower()

        if role in {"system", "world", "regulator"}:
            return

        if entry.layer == StateLayer.TRUE:
            if role == "investor":
                raise StateAccessError("investor cannot directly read true_state")

            if requester_id != entry.object_id:
                raise StateAccessError(
                    f"{requester_role} cannot read true_state of {entry.object_id}"
                )

        if entry.layer == StateLayer.PERCEIVED:
            owner_id = entry.metadata.get("owner_id")

            if owner_id is None:
                raise StateAccessError("perceived_state without owner_id is not readable")

            if requester_id != owner_id:
                raise StateAccessError(
                    f"{requester_id} cannot read perceived_state owned by {owner_id}"
                )


class State:
    """Minimal mutable state facade for the v0 world kernel."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._snapshots: list[StateSnapshot] = []

    def initialize_object(
        self,
        object_id: str,
        initial_state: dict[str, Any] | None = None,
    ) -> None:
        if object_id in self._data:
            raise ValueError(f"State already exists for object: {object_id}")
        self._data[object_id] = copy.deepcopy(initial_state or {})

    def get(self, object_id: str) -> dict[str, Any]:
        return copy.deepcopy(self._data[object_id])

    def set_field(self, object_id: str, key: str, value: Any) -> None:
        if object_id not in self._data:
            raise KeyError(f"Unknown object in state: {object_id}")
        self._data[object_id][key] = value

    def snapshot(self, simulation_date: date) -> StateSnapshot:
        entries = {
            StateLayer.TRUE.value: {
                object_id: StateEntry(
                    layer=StateLayer.TRUE,
                    object_id=object_id,
                    version=1,
                    value=value,
                    updated_at=_coerce_timestamp(None),
                    simulation_date=simulation_date,
                    source="state",
                )
                for object_id, value in self._data.items()
            },
            StateLayer.PUBLISHED.value: {},
            StateLayer.MARKET.value: {},
            StateLayer.PERCEIVED.value: {},
        }
        canonical_entries = {
            layer: {
                object_id: entry.to_dict()
                for object_id, entry in object_map.items()
            }
            for layer, object_map in entries.items()
        }
        state_hash = f"sha256:{_stable_hash(canonical_entries, length=32)}"
        snapshot = StateSnapshot(
            snapshot_id=f"snapshot:{simulation_date.isoformat()}",
            created_at=_coerce_timestamp(None),
            simulation_date=simulation_date,
            state_hash=state_hash,
            entries=entries,
        )
        self._snapshots.append(snapshot)
        return snapshot

    def snapshots(self) -> list[StateSnapshot]:
        return list(self._snapshots)
