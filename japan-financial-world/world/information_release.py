"""
v1.19.3 — ``InformationReleaseCalendar`` storage.

Storage layer that lets the v1.19.3 ``monthly_reference`` run
profile look meaningfully different from a naive 12x quarterly
loop. The module ships three immutable record shapes
(``InformationReleaseCalendar`` / ``ScheduledIndicatorRelease`` /
``InformationArrivalRecord``) and one append-only book
(``InformationReleaseBook``).

Critical design constraints pinned at v1.19.0 (binding):

- Information arrival is **not** data ingestion. No real
  indicator value, no real institutional identifier, no real
  release date beyond a synthetic month-end fixture. Japan's
  release cadence is a **design reference only**, never encoded
  as canonical data.
- The release layer is **append-only**. Adding an arrival
  record never mutates a pre-existing context record on any
  other source-of-truth book — the v1.18.2 / v1.18.3 / v1.19.1
  no-mutation discipline is preserved.
- Records carry the v1.18.0 / v1.18.2 audit shape — every
  arrival record has ``reasoning_mode`` /
  ``reasoning_policy_id`` / ``reasoning_slot`` defaults so a
  future audited reasoning policy (potentially LLM-backed in
  private JFWE) can replace the v1.19.x rule-based fallback
  without changing the audit surface.
- The v1.19.0 default boundary-flag set is carried on every
  arrival record (``synthetic_only`` / ``no_price_formation`` /
  ``no_trading`` / ``no_investment_advice`` / ``no_real_data``
  / ``no_japan_calibration`` / ``no_llm_execution`` /
  ``display_or_export_only``).

The module is **runtime-book-free** beyond the v0/v1 ledger +
clock convention shared by every other storage book — it does
not import any source-of-truth book on the engine side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar, Iterable, Mapping

from world.clock import Clock
from world.ledger import Ledger, RecordType


# ---------------------------------------------------------------------------
# Closed-set vocabularies
#
# Every label tuple here is the v1.19.0 design pin.
# The closed-set discipline is binding (every record validates
# against these frozensets at construction).
# ---------------------------------------------------------------------------


RELEASE_CADENCE_LABELS: frozenset[str] = frozenset(
    {
        "monthly",
        "quarterly",
        "meeting_based",
        "weekly",
        "daily_operational",
        "ad_hoc",
        "display_only",
        "unknown",
    }
)


INDICATOR_FAMILY_LABELS: frozenset[str] = frozenset(
    {
        "central_bank_policy",
        "inflation",
        "labor_market",
        "production_supply",
        "consumption_demand",
        "capex_investment",
        "gdp_national_accounts",
        "market_liquidity",
        "fiscal_policy",
        "sector_specific",
        "information_gap",
        "unknown",
    }
)


RELEASE_IMPORTANCE_LABELS: frozenset[str] = frozenset(
    {
        "routine",
        "high_attention",
        "regime_relevant",
        "stress_relevant",
        "unknown",
    }
)


JURISDICTION_SCOPE_LABELS: frozenset[str] = frozenset(
    {
        "jurisdiction_neutral",
        "generic_developed_market",
        "generic_emerging_market",
        "unknown",
    }
)


ARRIVAL_STATUS_LABELS: frozenset[str] = frozenset(
    {
        "arrived",
        "delayed",
        "missing",
        "not_scheduled",
        "unknown",
    }
)


REASONING_MODE_LABELS: frozenset[str] = frozenset(
    {
        "rule_based_fallback",
        "future_llm_compatible",
        "external_policy_slot",
        "unknown",
    }
)


REASONING_SLOT_LABELS: frozenset[str] = frozenset(
    {
        "future_llm_compatible",
        "rule_based_only",
        "not_applicable",
        "unknown",
    }
)


STATUS_LABELS: frozenset[str] = frozenset(
    {
        "draft",
        "active",
        "stale",
        "superseded",
        "archived",
        "unknown",
    }
)


VISIBILITY_LABELS: frozenset[str] = frozenset(
    {
        "internal_only",
        "shared_internal",
        "external_audit",
    }
)


# v1.19.3 hard naming boundary on payload + metadata. Tests scan
# dataclass field names, payload keys, and metadata keys for any
# of the forbidden names below. The set composes the v1.18.0
# forbidden-token set with the Japan-real-data / real-release-date
# tokens that a release calendar might be tempted to carry.
FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES: frozenset[str] = frozenset(
    {
        # v1.18.0 actor-decision / canonical-judgment tokens.
        "firm_decision",
        "investor_action",
        "bank_approval",
        "trading_decision",
        "optimal_capital_structure",
        "buy",
        "sell",
        "order",
        "trade",
        "execution",
        "price",
        "market_price",
        "predicted_index",
        "forecast_path",
        "expected_return",
        "target_price",
        "recommendation",
        "investment_advice",
        "real_data_value",
        "japan_calibration",
        "llm_output",
        "llm_prose",
        "prompt_text",
        # v1.19.3 Japan-real-data tokens — a release calendar
        # must not smuggle real values or real release dates.
        "real_indicator_value",
        "cpi_value",
        "gdp_value",
        "policy_rate",
        "real_release_date",
        "boj",
        "fomc",
        "ecb",
    }
)


# v1.19.0 default reasoning-mode binding.
DEFAULT_REASONING_MODE: str = "rule_based_fallback"
DEFAULT_REASONING_SLOT: str = "future_llm_compatible"
DEFAULT_REASONING_POLICY_ID: str = (
    "v1.19.3:information_release:rule_based_fallback"
)


# v1.19.0 default boundary-flag set carried on every emitted
# information arrival record. Mirrors the v1.19.1
# ``run_export.py`` default boundary-flag set verbatim.
DEFAULT_BOUNDARY_FLAGS: Mapping[str, bool] = {
    "synthetic_only": True,
    "no_price_formation": True,
    "no_trading": True,
    "no_investment_advice": True,
    "no_real_data": True,
    "no_japan_calibration": True,
    "no_llm_execution": True,
    "display_or_export_only": True,
}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InformationReleaseError(Exception):
    """Base class for information-release storage errors."""


class DuplicateInformationReleaseCalendarError(InformationReleaseError):
    """Raised when a calendar_id is added twice."""


class DuplicateScheduledIndicatorReleaseError(InformationReleaseError):
    """Raised when a scheduled_release_id is added twice."""


class DuplicateInformationArrivalError(InformationReleaseError):
    """Raised when an information_arrival_id is added twice."""


class UnknownInformationReleaseCalendarError(
    InformationReleaseError, KeyError
):
    """Raised when a calendar_id is not found."""


class UnknownScheduledIndicatorReleaseError(
    InformationReleaseError, KeyError
):
    """Raised when a scheduled_release_id is not found."""


class UnknownInformationArrivalError(
    InformationReleaseError, KeyError
):
    """Raised when an information_arrival_id is not found."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_label(
    value: Any, allowed: frozenset[str], *, field_name: str
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if value not in allowed:
        raise ValueError(
            f"{field_name} must be one of {sorted(allowed)!r}; "
            f"got {value!r}"
        )
    return value


def _validate_required_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(
            f"{field_name} is required and must be a non-empty string"
        )
    return value


def _validate_string_tuple(
    value: Iterable[str], *, field_name: str
) -> tuple[str, ...]:
    if isinstance(value, str):
        raise TypeError(
            f"{field_name} must be a tuple/list of strings, not a string"
        )
    normalized = tuple(value)
    for entry in normalized:
        if not isinstance(entry, str) or not entry:
            raise ValueError(
                f"{field_name} entries must be non-empty strings; "
                f"got {entry!r}"
            )
    return normalized


def _scan_for_forbidden_keys(
    mapping: Mapping[str, Any], *, field_name: str
) -> None:
    """Reject any v1.19.3 forbidden field name appearing in a
    metadata, payload, or boundary-flag mapping."""
    if not isinstance(mapping, Mapping):
        raise TypeError(
            f"{field_name} must be a mapping; got {type(mapping).__name__}"
        )
    for key in mapping.keys():
        if not isinstance(key, str):
            continue
        if key in FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES:
            raise ValueError(
                f"{field_name} contains forbidden key {key!r} "
                "(v1.19.3 hard naming boundary — information-release "
                "records do not carry actor-decision / price / "
                "forecast / advice / real-value / Japan-calibration "
                "/ LLM fields)"
            )


def _validate_boundary_flags(
    value: Mapping[str, bool], *, field_name: str
) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{field_name} must be a mapping; got {type(value).__name__}"
        )
    out: dict[str, bool] = {}
    for k, v in value.items():
        if not isinstance(k, str) or not k:
            raise ValueError(
                f"{field_name} keys must be non-empty strings"
            )
        if not isinstance(v, bool):
            raise ValueError(
                f"{field_name} values must be booleans; "
                f"got {type(v).__name__} for {k!r}"
            )
        out[k] = v
    _scan_for_forbidden_keys(out, field_name=field_name)
    return out


def _validate_metadata(
    value: Mapping[str, Any], *, field_name: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(
            f"{field_name} must be a mapping; got {type(value).__name__}"
        )
    out = dict(value)
    _scan_for_forbidden_keys(out, field_name=field_name)
    return out


def _reject_bool_int(value: Any, *, field_name: str) -> int:
    """Reject ``bool`` (which is a subclass of ``int``) and
    return a non-negative ``int`` otherwise."""
    if isinstance(value, bool):
        raise TypeError(
            f"{field_name} must be a non-negative int, not a bool"
        )
    if not isinstance(value, int):
        raise TypeError(
            f"{field_name} must be a non-negative int; "
            f"got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0; got {value!r}")
    return value


# ---------------------------------------------------------------------------
# InformationReleaseCalendar dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InformationReleaseCalendar:
    """Immutable record describing one synthetic
    information-release calendar (e.g. the default monthly
    fixture used by the v1.19.3 ``monthly_reference`` profile).

    The dataclass:

    - has **no** real-value field;
    - has **no** real-release-date field — calendars name
      months and cadence categories, never specific calendar
      dates;
    - has **no** institutional identifier — calendars reference
      indicator *families*, never named institutions;
    - has **no** actor-decision field.
    """

    calendar_id: str
    calendar_label: str
    jurisdiction_scope_label: str = "jurisdiction_neutral"
    release_cadence_labels: tuple[str, ...] = field(default_factory=tuple)
    indicator_family_labels: tuple[str, ...] = field(default_factory=tuple)
    status: str = "active"
    visibility: str = "internal_only"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "calendar_id",
        "calendar_label",
        "jurisdiction_scope_label",
        "status",
        "visibility",
    )

    LABEL_FIELDS: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = (
        ("jurisdiction_scope_label", JURISDICTION_SCOPE_LABELS),
        ("status", STATUS_LABELS),
        ("visibility", VISIBILITY_LABELS),
    )

    def __post_init__(self) -> None:
        for fname in self.REQUIRED_STRING_FIELDS:
            _validate_required_string(
                getattr(self, fname), field_name=fname
            )
        for fname, allowed in self.LABEL_FIELDS:
            _validate_label(
                getattr(self, fname), allowed, field_name=fname
            )
        cadence_tuple = _validate_string_tuple(
            self.release_cadence_labels,
            field_name="release_cadence_labels",
        )
        for entry in cadence_tuple:
            if entry not in RELEASE_CADENCE_LABELS:
                raise ValueError(
                    f"release_cadence_labels entry {entry!r} not in "
                    f"RELEASE_CADENCE_LABELS"
                )
        object.__setattr__(self, "release_cadence_labels", cadence_tuple)

        family_tuple = _validate_string_tuple(
            self.indicator_family_labels,
            field_name="indicator_family_labels",
        )
        for entry in family_tuple:
            if entry not in INDICATOR_FAMILY_LABELS:
                raise ValueError(
                    f"indicator_family_labels entry {entry!r} not in "
                    f"INDICATOR_FAMILY_LABELS"
                )
        object.__setattr__(self, "indicator_family_labels", family_tuple)

        # Field-name guard against any future field rename.
        for fname in self.__dataclass_fields__.keys():
            if fname in FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES:
                raise ValueError(
                    f"dataclass field {fname!r} is in the v1.19.3 "
                    "forbidden field-name set"
                )

        object.__setattr__(
            self,
            "metadata",
            _validate_metadata(self.metadata, field_name="metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "calendar_id": self.calendar_id,
            "calendar_label": self.calendar_label,
            "jurisdiction_scope_label": self.jurisdiction_scope_label,
            "release_cadence_labels": list(self.release_cadence_labels),
            "indicator_family_labels": list(self.indicator_family_labels),
            "status": self.status,
            "visibility": self.visibility,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# ScheduledIndicatorRelease dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledIndicatorRelease:
    """Immutable record describing one scheduled synthetic
    indicator release on an :class:`InformationReleaseCalendar`.

    A scheduled release is a *category* announcement — "the
    inflation indicator family is scheduled to release in
    period_03". It carries no value, no real date, no
    institutional identifier, no actor decision.
    """

    scheduled_release_id: str
    calendar_id: str
    indicator_family_label: str
    release_cadence_label: str
    release_importance_label: str
    scheduled_month_label: str
    scheduled_period_index: int
    expected_attention_surface_labels: tuple[str, ...] = field(
        default_factory=tuple
    )
    status: str = "active"
    visibility: str = "internal_only"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "scheduled_release_id",
        "calendar_id",
        "indicator_family_label",
        "release_cadence_label",
        "release_importance_label",
        "scheduled_month_label",
        "status",
        "visibility",
    )

    LABEL_FIELDS: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = (
        ("indicator_family_label", INDICATOR_FAMILY_LABELS),
        ("release_cadence_label", RELEASE_CADENCE_LABELS),
        ("release_importance_label", RELEASE_IMPORTANCE_LABELS),
        ("status", STATUS_LABELS),
        ("visibility", VISIBILITY_LABELS),
    )

    def __post_init__(self) -> None:
        for fname in self.REQUIRED_STRING_FIELDS:
            _validate_required_string(
                getattr(self, fname), field_name=fname
            )
        for fname, allowed in self.LABEL_FIELDS:
            _validate_label(
                getattr(self, fname), allowed, field_name=fname
            )
        object.__setattr__(
            self,
            "scheduled_period_index",
            _reject_bool_int(
                self.scheduled_period_index,
                field_name="scheduled_period_index",
            ),
        )
        object.__setattr__(
            self,
            "expected_attention_surface_labels",
            _validate_string_tuple(
                self.expected_attention_surface_labels,
                field_name="expected_attention_surface_labels",
            ),
        )
        for fname in self.__dataclass_fields__.keys():
            if fname in FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES:
                raise ValueError(
                    f"dataclass field {fname!r} is in the v1.19.3 "
                    "forbidden field-name set"
                )
        object.__setattr__(
            self,
            "metadata",
            _validate_metadata(self.metadata, field_name="metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduled_release_id": self.scheduled_release_id,
            "calendar_id": self.calendar_id,
            "indicator_family_label": self.indicator_family_label,
            "release_cadence_label": self.release_cadence_label,
            "release_importance_label": self.release_importance_label,
            "scheduled_month_label": self.scheduled_month_label,
            "scheduled_period_index": self.scheduled_period_index,
            "expected_attention_surface_labels": list(
                self.expected_attention_surface_labels
            ),
            "status": self.status,
            "visibility": self.visibility,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# InformationArrivalRecord dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InformationArrivalRecord:
    """Immutable record describing one synthetic information
    arrival — i.e. that a scheduled indicator family released
    information in a given synthetic month.

    The record:

    - cites the scheduled release via plain id;
    - never mutates the cited release;
    - carries the v1.18.0 audit-metadata block verbatim
      (``reasoning_mode`` / ``reasoning_policy_id`` /
      ``reasoning_slot``);
    - carries the v1.19.0 default boundary-flag set;
    - never decides actor behaviour.
    """

    information_arrival_id: str
    calendar_id: str
    scheduled_release_id: str
    as_of_date: str
    indicator_family_label: str
    release_cadence_label: str
    release_importance_label: str
    arrival_status_label: str = "arrived"
    affected_context_surface_labels: tuple[str, ...] = field(
        default_factory=tuple
    )
    expected_attention_surface_labels: tuple[str, ...] = field(
        default_factory=tuple
    )
    reasoning_mode: str = DEFAULT_REASONING_MODE
    reasoning_policy_id: str = DEFAULT_REASONING_POLICY_ID
    reasoning_slot: str = DEFAULT_REASONING_SLOT
    boundary_flags: Mapping[str, bool] = field(
        default_factory=lambda: dict(DEFAULT_BOUNDARY_FLAGS)
    )
    status: str = "active"
    visibility: str = "internal_only"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    REQUIRED_STRING_FIELDS: ClassVar[tuple[str, ...]] = (
        "information_arrival_id",
        "calendar_id",
        "scheduled_release_id",
        "as_of_date",
        "indicator_family_label",
        "release_cadence_label",
        "release_importance_label",
        "arrival_status_label",
        "reasoning_mode",
        "reasoning_policy_id",
        "reasoning_slot",
        "status",
        "visibility",
    )

    LABEL_FIELDS: ClassVar[tuple[tuple[str, frozenset[str]], ...]] = (
        ("indicator_family_label", INDICATOR_FAMILY_LABELS),
        ("release_cadence_label", RELEASE_CADENCE_LABELS),
        ("release_importance_label", RELEASE_IMPORTANCE_LABELS),
        ("arrival_status_label", ARRIVAL_STATUS_LABELS),
        ("reasoning_mode", REASONING_MODE_LABELS),
        ("reasoning_slot", REASONING_SLOT_LABELS),
        ("status", STATUS_LABELS),
        ("visibility", VISIBILITY_LABELS),
    )

    def __post_init__(self) -> None:
        for fname in self.REQUIRED_STRING_FIELDS:
            _validate_required_string(
                getattr(self, fname), field_name=fname
            )
        for fname, allowed in self.LABEL_FIELDS:
            _validate_label(
                getattr(self, fname), allowed, field_name=fname
            )
        object.__setattr__(
            self,
            "affected_context_surface_labels",
            _validate_string_tuple(
                self.affected_context_surface_labels,
                field_name="affected_context_surface_labels",
            ),
        )
        object.__setattr__(
            self,
            "expected_attention_surface_labels",
            _validate_string_tuple(
                self.expected_attention_surface_labels,
                field_name="expected_attention_surface_labels",
            ),
        )
        object.__setattr__(
            self,
            "boundary_flags",
            _validate_boundary_flags(
                self.boundary_flags, field_name="boundary_flags"
            ),
        )
        for fname in self.__dataclass_fields__.keys():
            if fname in FORBIDDEN_INFORMATION_RELEASE_FIELD_NAMES:
                raise ValueError(
                    f"dataclass field {fname!r} is in the v1.19.3 "
                    "forbidden field-name set"
                )
        object.__setattr__(
            self,
            "metadata",
            _validate_metadata(self.metadata, field_name="metadata"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "information_arrival_id": self.information_arrival_id,
            "calendar_id": self.calendar_id,
            "scheduled_release_id": self.scheduled_release_id,
            "as_of_date": self.as_of_date,
            "indicator_family_label": self.indicator_family_label,
            "release_cadence_label": self.release_cadence_label,
            "release_importance_label": self.release_importance_label,
            "arrival_status_label": self.arrival_status_label,
            "affected_context_surface_labels": list(
                self.affected_context_surface_labels
            ),
            "expected_attention_surface_labels": list(
                self.expected_attention_surface_labels
            ),
            "reasoning_mode": self.reasoning_mode,
            "reasoning_policy_id": self.reasoning_policy_id,
            "reasoning_slot": self.reasoning_slot,
            "boundary_flags": dict(self.boundary_flags),
            "status": self.status,
            "visibility": self.visibility,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# InformationReleaseBook
# ---------------------------------------------------------------------------


@dataclass
class InformationReleaseBook:
    """Append-only storage for v1.19.3 information-release
    records. Mirrors the v1.18.1 / v1.18.2 storage-book
    convention: emits exactly one ledger record per
    :meth:`add_calendar` / :meth:`add_scheduled_release` /
    :meth:`add_arrival` call. The book mutates no other
    source-of-truth book, including the ``PriceBook``.

    Idempotency: re-adding a record with the same id raises a
    ``Duplicate*Error`` and emits **no** additional ledger
    record.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _calendars: dict[str, InformationReleaseCalendar] = field(
        default_factory=dict
    )
    _scheduled_releases: dict[str, ScheduledIndicatorRelease] = field(
        default_factory=dict
    )
    _arrivals: dict[str, InformationArrivalRecord] = field(
        default_factory=dict
    )

    def _now(self) -> datetime:
        if self.clock is not None:
            try:
                return self.clock.current_datetime()
            except Exception:
                pass
        return datetime.now(timezone.utc)

    # ---- Calendars ---------------------------------------------------------

    def add_calendar(
        self,
        calendar: InformationReleaseCalendar,
        *,
        simulation_date: str | None = None,
    ) -> InformationReleaseCalendar:
        if calendar.calendar_id in self._calendars:
            raise DuplicateInformationReleaseCalendarError(
                f"Duplicate calendar_id: {calendar.calendar_id}"
            )
        self._calendars[calendar.calendar_id] = calendar

        if self.ledger is not None:
            payload = calendar.to_dict()
            _scan_for_forbidden_keys(
                payload, field_name="ledger payload"
            )
            sim_date: Any = (
                simulation_date
                if simulation_date is not None
                else self._now()
            )
            self.ledger.append(
                RecordType.INFORMATION_RELEASE_CALENDAR_RECORDED,
                simulation_date=sim_date,
                object_id=calendar.calendar_id,
                source=calendar.jurisdiction_scope_label,
                payload=payload,
                space_id="information_release",
                visibility=calendar.visibility,
            )
        return calendar

    def get_calendar(
        self, calendar_id: str
    ) -> InformationReleaseCalendar:
        try:
            return self._calendars[calendar_id]
        except KeyError as exc:
            raise UnknownInformationReleaseCalendarError(
                f"InformationReleaseCalendar not found: {calendar_id!r}"
            ) from exc

    def list_calendars(
        self,
    ) -> tuple[InformationReleaseCalendar, ...]:
        return tuple(self._calendars.values())

    # ---- Scheduled releases -----------------------------------------------

    def add_scheduled_release(
        self,
        release: ScheduledIndicatorRelease,
        *,
        simulation_date: str | None = None,
    ) -> ScheduledIndicatorRelease:
        if release.scheduled_release_id in self._scheduled_releases:
            raise DuplicateScheduledIndicatorReleaseError(
                f"Duplicate scheduled_release_id: "
                f"{release.scheduled_release_id}"
            )
        self._scheduled_releases[release.scheduled_release_id] = release

        if self.ledger is not None:
            payload = release.to_dict()
            _scan_for_forbidden_keys(
                payload, field_name="ledger payload"
            )
            sim_date: Any = (
                simulation_date
                if simulation_date is not None
                else self._now()
            )
            self.ledger.append(
                RecordType.SCHEDULED_INDICATOR_RELEASE_RECORDED,
                simulation_date=sim_date,
                object_id=release.scheduled_release_id,
                source=release.indicator_family_label,
                payload=payload,
                space_id="information_release",
                visibility=release.visibility,
            )
        return release

    def get_scheduled_release(
        self, scheduled_release_id: str
    ) -> ScheduledIndicatorRelease:
        try:
            return self._scheduled_releases[scheduled_release_id]
        except KeyError as exc:
            raise UnknownScheduledIndicatorReleaseError(
                f"ScheduledIndicatorRelease not found: "
                f"{scheduled_release_id!r}"
            ) from exc

    def list_scheduled_releases(
        self,
    ) -> tuple[ScheduledIndicatorRelease, ...]:
        return tuple(self._scheduled_releases.values())

    def list_releases_by_calendar(
        self, calendar_id: str
    ) -> tuple[ScheduledIndicatorRelease, ...]:
        return tuple(
            r
            for r in self._scheduled_releases.values()
            if r.calendar_id == calendar_id
        )

    def list_releases_by_indicator_family(
        self, indicator_family_label: str
    ) -> tuple[ScheduledIndicatorRelease, ...]:
        return tuple(
            r
            for r in self._scheduled_releases.values()
            if r.indicator_family_label == indicator_family_label
        )

    def list_releases_by_cadence(
        self, release_cadence_label: str
    ) -> tuple[ScheduledIndicatorRelease, ...]:
        return tuple(
            r
            for r in self._scheduled_releases.values()
            if r.release_cadence_label == release_cadence_label
        )

    def list_releases_by_importance(
        self, release_importance_label: str
    ) -> tuple[ScheduledIndicatorRelease, ...]:
        return tuple(
            r
            for r in self._scheduled_releases.values()
            if r.release_importance_label == release_importance_label
        )

    # ---- Arrivals ----------------------------------------------------------

    def add_arrival(
        self, arrival: InformationArrivalRecord
    ) -> InformationArrivalRecord:
        if arrival.information_arrival_id in self._arrivals:
            raise DuplicateInformationArrivalError(
                f"Duplicate information_arrival_id: "
                f"{arrival.information_arrival_id}"
            )
        self._arrivals[arrival.information_arrival_id] = arrival

        if self.ledger is not None:
            payload = arrival.to_dict()
            _scan_for_forbidden_keys(
                payload, field_name="ledger payload"
            )
            # Use the arrival's own ``as_of_date`` as the
            # simulation date so the recorded ledger event is
            # deterministic across runs (otherwise
            # ``self._now()`` would emit a wall-clock timestamp).
            self.ledger.append(
                RecordType.INFORMATION_ARRIVAL_RECORDED,
                simulation_date=arrival.as_of_date,
                object_id=arrival.information_arrival_id,
                source=arrival.indicator_family_label,
                payload=payload,
                space_id="information_release",
                visibility=arrival.visibility,
            )
        return arrival

    def get_arrival(
        self, information_arrival_id: str
    ) -> InformationArrivalRecord:
        try:
            return self._arrivals[information_arrival_id]
        except KeyError as exc:
            raise UnknownInformationArrivalError(
                f"InformationArrivalRecord not found: "
                f"{information_arrival_id!r}"
            ) from exc

    def list_arrivals(
        self,
    ) -> tuple[InformationArrivalRecord, ...]:
        return tuple(self._arrivals.values())

    def list_arrivals_by_calendar(
        self, calendar_id: str
    ) -> tuple[InformationArrivalRecord, ...]:
        return tuple(
            a
            for a in self._arrivals.values()
            if a.calendar_id == calendar_id
        )

    def list_arrivals_by_indicator_family(
        self, indicator_family_label: str
    ) -> tuple[InformationArrivalRecord, ...]:
        return tuple(
            a
            for a in self._arrivals.values()
            if a.indicator_family_label == indicator_family_label
        )

    def list_arrivals_by_date(
        self, as_of_date: str
    ) -> tuple[InformationArrivalRecord, ...]:
        return tuple(
            a
            for a in self._arrivals.values()
            if a.as_of_date == as_of_date
        )

    def list_arrivals_by_importance(
        self, release_importance_label: str
    ) -> tuple[InformationArrivalRecord, ...]:
        return tuple(
            a
            for a in self._arrivals.values()
            if a.release_importance_label == release_importance_label
        )

    # ---- Snapshot ----------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "calendars": [
                c.to_dict() for c in self._calendars.values()
            ],
            "scheduled_releases": [
                r.to_dict() for r in self._scheduled_releases.values()
            ],
            "arrivals": [
                a.to_dict() for a in self._arrivals.values()
            ],
        }
