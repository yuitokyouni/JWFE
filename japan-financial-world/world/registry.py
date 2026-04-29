from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .ids import (
    AGENT_KINDS,
    WorldID,
    category_for_kind,
    parse_world_id,
)


class RegistryError(Exception):
    """Base class for registry-related errors."""


class DuplicateIDError(RegistryError):
    """Raised when an object with the same WorldID is already registered."""


class UnknownIDError(RegistryError, KeyError):
    """Raised when an object ID is not found in the registry."""


class RegistryTypeError(RegistryError, TypeError):
    """Raised when an object is registered through the wrong register_* method."""


@dataclass(frozen=True, slots=True)
class RegisteredObject:
    id: str
    kind: str
    type: str
    space: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RegistryRecord:
    id: WorldID
    type: str
    category: str
    obj: Any
    metadata: dict[str, Any] = field(default_factory=dict)


_MISSING = object()


class Registry:
    """
    Central reference point for world objects.

    Responsibilities:
        - register objects by stable WorldID
        - prevent duplicate IDs
        - retrieve objects by ID
        - list objects by type/category
        - store optional metadata

    Non-responsibilities:
        - no scheduling
        - no ledger/accounting
        - no scenario logic
        - no profit calculation
        - no investment strategy
        - no credit judgment
    """

    def __init__(self) -> None:
        self._records: dict[str, RegistryRecord] = {}
        self._by_type: dict[str, list[str]] = {}
        self._by_category: dict[str, list[str]] = {}

    def register(self, obj: RegisteredObject) -> None:
        self._register(
            obj=obj,
            object_id=obj.id,
            expected_category=category_for_kind(parse_world_id(obj.id).kind),
            allowed_kinds=frozenset({parse_world_id(obj.id).kind}),
            metadata={
                "type": obj.type,
                "space": obj.space,
                "attributes": dict(obj.attributes),
            },
        )

    def get(self, object_id: str | WorldID) -> RegisteredObject:
        obj = self.get_by_id(object_id)
        if not isinstance(obj, RegisteredObject):
            record = self.get_record(object_id)
            return RegisteredObject(
                id=str(record.id),
                kind=record.category,
                type=str(record.metadata.get("type", record.type)),
                space=str(record.metadata.get("space", "unknown")),
                attributes=dict(record.metadata.get("attributes", {})),
            )
        return obj

    def all(self) -> list[RegisteredObject]:
        return [self.get(object_id) for object_id in self._records]

    def by_kind(self, kind: str) -> list[RegisteredObject]:
        return [obj for obj in self.all() if obj.kind == kind]

    def __contains__(self, object_id: object) -> bool:
        if not isinstance(object_id, str):
            return False
        return object_id in self._records

    def register_agent(
        self,
        agent: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register(
            obj=agent,
            object_id=object_id,
            expected_category="agent",
            allowed_kinds=AGENT_KINDS,
            metadata=metadata,
        )

    def register_asset(
        self,
        asset: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register_single_kind(
            obj=asset,
            object_id=object_id,
            expected_kind="asset",
            metadata=metadata,
        )

    def register_contract(
        self,
        contract: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register_single_kind(
            obj=contract,
            object_id=object_id,
            expected_kind="contract",
            metadata=metadata,
        )

    def register_market(
        self,
        market: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register_single_kind(
            obj=market,
            object_id=object_id,
            expected_kind="market",
            metadata=metadata,
        )

    def register_signal(
        self,
        signal: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register_single_kind(
            obj=signal,
            object_id=object_id,
            expected_kind="signal",
            metadata=metadata,
        )

    def register_price(
        self,
        price: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register_single_kind(
            obj=price,
            object_id=object_id,
            expected_kind="price",
            metadata=metadata,
        )

    def register_space(
        self,
        space: Any,
        *,
        object_id: str | WorldID | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> RegistryRecord:
        return self._register_single_kind(
            obj=space,
            object_id=object_id,
            expected_kind="space",
            metadata=metadata,
        )

    def get_by_id(
        self,
        object_id: str | WorldID,
        *,
        default: Any = _MISSING,
    ) -> Any:
        record = self._records.get(str(parse_world_id(object_id)))

        if record is None:
            if default is not _MISSING:
                return default
            raise UnknownIDError(f"Object not found: {object_id!r}")

        return record.obj

    def get_record(self, object_id: str | WorldID) -> RegistryRecord:
        record = self._records.get(str(parse_world_id(object_id)))

        if record is None:
            raise UnknownIDError(f"Object not found: {object_id!r}")

        return record

    def list_by_type(self, type_name: str) -> list[Any]:
        """
        List objects by concrete ID type.

        Examples:
            list_by_type("firm") -> all firm agents
            list_by_type("bank") -> all bank agents
            list_by_type("asset") -> all assets
            list_by_type("price") -> all prices

        Special case:
            list_by_type("agent") -> all firm / bank / investor objects
        """
        if type_name == "agent":
            ids = self._by_category.get("agent", [])
        else:
            ids = self._by_type.get(type_name, [])

        return [self._records[object_id].obj for object_id in ids]

    def list_records_by_type(self, type_name: str) -> list[RegistryRecord]:
        if type_name == "agent":
            ids = self._by_category.get("agent", [])
        else:
            ids = self._by_type.get(type_name, [])

        return [self._records[object_id] for object_id in ids]

    def export_registry_snapshot(self) -> dict[str, Any]:
        """
        Export a simple registry snapshot.

        The object itself is intentionally not serialized.
        This method is for inspection/debugging, not persistence.
        """
        records = []

        for object_id in sorted(self._records):
            record = self._records[object_id]
            records.append(
                {
                    "id": str(record.id),
                    "type": record.type,
                    "category": record.category,
                    "object_class": record.obj.__class__.__name__,
                    "metadata": dict(record.metadata),
                }
            )

        return {
            "count": len(records),
            "records": records,
        }

    def _register_single_kind(
        self,
        *,
        obj: Any,
        object_id: str | WorldID | None,
        expected_kind: str,
        metadata: Mapping[str, Any] | None,
    ) -> RegistryRecord:
        return self._register(
            obj=obj,
            object_id=object_id,
            expected_category=expected_kind,
            allowed_kinds=frozenset({expected_kind}),
            metadata=metadata,
        )

    def _register(
        self,
        *,
        obj: Any,
        object_id: str | WorldID | None,
        expected_category: str,
        allowed_kinds: frozenset[str],
        metadata: Mapping[str, Any] | None,
    ) -> RegistryRecord:
        world_id = self._extract_world_id(obj=obj, object_id=object_id)

        if world_id.kind not in allowed_kinds:
            raise RegistryTypeError(
                f"Cannot register ID {world_id!s} as {expected_category!r}. "
                f"Allowed ID kinds here are: {sorted(allowed_kinds)}"
            )

        actual_category = category_for_kind(world_id.kind)
        if actual_category != expected_category:
            raise RegistryTypeError(
                f"Category mismatch for ID {world_id!s}: "
                f"expected {expected_category!r}, got {actual_category!r}"
            )

        raw_id = str(world_id)
        if raw_id in self._records:
            raise DuplicateIDError(f"Duplicate WorldID: {raw_id}")

        record = RegistryRecord(
            id=world_id,
            type=world_id.kind,
            category=actual_category,
            obj=obj,
            metadata=dict(metadata or {}),
        )

        self._records[raw_id] = record
        self._by_type.setdefault(record.type, []).append(raw_id)
        self._by_category.setdefault(record.category, []).append(raw_id)

        return record

    def _extract_world_id(
        self,
        *,
        obj: Any,
        object_id: str | WorldID | None,
    ) -> WorldID:
        if object_id is not None:
            return parse_world_id(object_id)

        if isinstance(obj, WorldID):
            return obj

        if isinstance(obj, Mapping):
            if "id" in obj:
                return parse_world_id(obj["id"])
            if "world_id" in obj:
                return parse_world_id(obj["world_id"])

        if hasattr(obj, "id"):
            return parse_world_id(getattr(obj, "id"))

        if hasattr(obj, "world_id"):
            return parse_world_id(getattr(obj, "world_id"))

        raise RegistryError(
            "Object has no ID. Provide object_id=... or give the object "
            "an 'id' or 'world_id' attribute."
        )
