from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Literal


KNOWN_OBJECT_TYPES = {
    "firm",
    "investor",
    "bank",
    "market",
    "property_market",
    "information_signal",
    "contract",
    "asset",
}


COLLECTION_KEY_TO_TYPE = {
    "firms": "firm",
    "investors": "investor",
    "banks": "bank",
    "markets": "market",
    "property_markets": "property_market",
    "information_signals": "information_signal",
    "contracts": "contract",
    "assets": "asset",
}


# v0 fallback.
# If schemas/*.yaml define their own required fields, loader can pass those instead.
DEFAULT_REQUIRED_FIELDS = {
    "firm": ["id", "name"],
    "investor": ["id", "name"],
    "bank": ["id", "name"],
    "market": ["id", "name"],
    "property_market": ["id", "name"],
    "information_signal": ["id", "name"],
    "contract": ["id", "name"],
    "asset": ["id", "name"],
}


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning"]
    message: str
    source_path: str | None = None
    object_type: str | None = None
    object_id: str | None = None


def normalize_object_type(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().lower().replace("-", "_")

    aliases = {
        "signal": "information_signal",
        "info_signal": "information_signal",
        "propertymarket": "property_market",
        "information_signal": "information_signal",
    }

    normalized = aliases.get(normalized, normalized)

    if normalized in KNOWN_OBJECT_TYPES:
        return normalized

    return None


def infer_object_type(
    obj: Mapping[str, Any],
    *,
    type_hint: str | None = None,
    source_path: str | Path | None = None,
) -> str | None:
    hinted = normalize_object_type(type_hint)
    if hinted is not None:
        return hinted

    explicit = normalize_object_type(
        obj.get("type")
        or obj.get("object_type")
        or obj.get("entity_type")
    )
    if explicit is not None:
        return explicit

    object_id = obj.get("id")
    if isinstance(object_id, str) and ":" in object_id:
        prefix = object_id.split(":", 1)[0]
        by_prefix = normalize_object_type(prefix)
        if by_prefix is not None:
            return by_prefix

    if source_path is not None:
        stem = Path(source_path).stem
        singular = stem[:-1] if stem.endswith("s") else stem
        by_filename = normalize_object_type(singular)
        if by_filename is not None:
            return by_filename

    return None


def validate_required_fields(
    obj: Mapping[str, Any],
    *,
    object_type: str,
    required_fields: list[str] | None = None,
    source_path: str | Path | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    object_id = obj.get("id")
    required = required_fields or DEFAULT_REQUIRED_FIELDS.get(object_type, ["id"])

    for field in required:
        value = obj.get(field)
        if value is None or value == "":
            issues.append(
                ValidationIssue(
                    severity="error",
                    message=f"Missing required field: {field}",
                    source_path=str(source_path) if source_path is not None else None,
                    object_type=object_type,
                    object_id=str(object_id) if object_id is not None else None,
                )
            )

    return issues


def validate_id_prefix(
    obj: Mapping[str, Any],
    *,
    object_type: str,
    source_path: str | Path | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    object_id = obj.get("id")
    if not isinstance(object_id, str):
        return [
            ValidationIssue(
                severity="error",
                message="Field 'id' must be a string",
                source_path=str(source_path) if source_path is not None else None,
                object_type=object_type,
                object_id=None,
            )
        ]

    expected_prefix = f"{object_type}:"
    if not object_id.startswith(expected_prefix):
        issues.append(
            ValidationIssue(
                severity="warning",
                message=f"ID prefix does not match object type. Expected prefix: {expected_prefix}",
                source_path=str(source_path) if source_path is not None else None,
                object_type=object_type,
                object_id=object_id,
            )
        )

    return issues


def validate_registry_object(
    obj: Mapping[str, Any],
    *,
    object_type: str,
    required_fields_by_type: dict[str, list[str]] | None = None,
    source_path: str | Path | None = None,
) -> list[ValidationIssue]:
    required_fields = None
    if required_fields_by_type is not None:
        required_fields = required_fields_by_type.get(object_type)

    issues: list[ValidationIssue] = []
    issues.extend(
        validate_required_fields(
            obj,
            object_type=object_type,
            required_fields=required_fields,
            source_path=source_path,
        )
    )

    if "id" in obj:
        issues.extend(
            validate_id_prefix(
                obj,
                object_type=object_type,
                source_path=source_path,
            )
        )

    return issues