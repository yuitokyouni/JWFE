"""
v1.8.3 InteractionBook + Tensor View.

Implements the kernel-level book that stores **possible** directed
interaction channels between spaces (and optionally between specific
world objects), per the v1.8.2 design
(``docs/v1_interaction_topology_design.md``).

Scope discipline (v1.8.3):

- ``InteractionBook`` stores the topology. It does **not** execute
  any channel, fire any routine, decide any behavior, or mutate any
  other book.
- The Routine engine, ``AttentionProfile``, ``ObservationMenu``, and
  ``SelectedObservationSet`` are later milestones (v1.8.4+) that
  consume this book; v1.8.3 ships only the storage and the
  deterministic tensor / matrix views.
- Cross-references (``source_space_id``, ``target_space_id``,
  ``source_id``, ``target_id``) are recorded as data and **not**
  validated for resolution against the registry, per the v0/v1
  cross-reference rule.
- v1.8.3 ships zero economic behavior: no price formation, no
  trading, no lending decisions, no corporate actions, no policy
  reaction functions, no Japan calibration.

Tensor / matrix views are read-only projections. They are rebuilt
on each call from the underlying append-only store; they are not
canonical state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from world.clock import Clock
from world.ledger import Ledger


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InteractionError(Exception):
    """Base class for interaction-topology layer errors."""


class DuplicateInteractionError(InteractionError):
    """Raised when an interaction_id is added twice."""


class UnknownInteractionError(InteractionError, KeyError):
    """Raised when an interaction_id is not found."""


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InteractionSpec:
    """
    A directed interaction channel between two spaces (and optionally
    between two specific world objects).

    Field semantics
    ---------------
    - ``interaction_id`` is the stable id of the channel; it must be
      unique within an ``InteractionBook``.
    - ``source_space_id`` and ``target_space_id`` are required, free-
      form strings naming spaces. Equal source / target is permitted
      and is the *self-loop* case (e.g., a corporate self-space
      reporting-preparation channel).
    - ``source_id`` and ``target_id`` are optional WorldIDs that scope
      the channel to specific actors / assets / contracts. ``None``
      means "any participant within the named space."
    - ``interaction_type`` names the *semantic* category of the
      channel (e.g., ``"earnings_disclosure"``, ``"credit_review"``,
      ``"policy_guidance"``). Free-form string; v1.8.3 enumerates
      none.
    - ``channel_type`` names the *delivery medium* category of the
      channel (e.g., ``"scheduled_filing"``, ``"private_communication"``,
      ``"public_broadcast"``, ``"market_action"``). Free-form string.
    - ``direction`` is a free-form label hinting at the channel's
      orientation. Suggested values: ``"directed"`` (asymmetric),
      ``"reciprocal"`` (mutual but produces records in either
      direction at the routine layer), ``"self_loop"`` (when
      source == target).
    - ``frequency`` and ``phase_id`` are *labels only*. v1.8.3 does
      not register tasks against the scheduler from interactions.
    - ``visibility`` mirrors the v0/v1 `SignalBook` vocabulary
      (``"public"`` / ``"restricted"`` / ``"private"``); the book
      does not enforce visibility filtering on reads — that is a
      consumer concern.
    - ``enabled`` is a flag (default ``True``). Disabled interactions
      remain in the book but are excluded from list / tensor / matrix
      views unless ``include_disabled=True`` is passed.
    - ``required_input_ref_types`` and ``optional_input_ref_types``
      name record-type strings a routine *should* / *may* read to use
      this channel. Tuples of strings; v1.8.3 enumerates none.
    - ``output_ref_types`` names record-type strings the channel
      *produces* (e.g., ``("InformationSignal",)``). Tuple of
      strings.
    - ``routine_types_that_may_use_this_channel`` is the **load-
      bearing** field that names which v1.8.4+ routine types are
      permitted to publish on this channel. The empty tuple means
      "any routine type" — rare and should be justified.
    - ``metadata`` is a free-form mapping for provenance, parameters,
      and owner notes.

    Cross-references are stored as data. v1.8.3 does **not** validate
    that ``source_space_id`` / ``target_space_id`` / ``source_id`` /
    ``target_id`` resolve to registered objects. The cross-reference
    rule from v0 / v1 holds.
    """

    interaction_id: str
    source_space_id: str
    target_space_id: str
    interaction_type: str
    channel_type: str
    direction: str = "directed"
    frequency: str | None = None
    phase_id: str | None = None
    visibility: str = "public"
    enabled: bool = True
    required_input_ref_types: tuple[str, ...] = field(default_factory=tuple)
    optional_input_ref_types: tuple[str, ...] = field(default_factory=tuple)
    output_ref_types: tuple[str, ...] = field(default_factory=tuple)
    routine_types_that_may_use_this_channel: tuple[str, ...] = field(
        default_factory=tuple
    )
    source_id: str | None = None
    target_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.interaction_id, str) or not self.interaction_id:
            raise ValueError("interaction_id is required")
        if not isinstance(self.source_space_id, str) or not self.source_space_id:
            raise ValueError("source_space_id is required")
        if not isinstance(self.target_space_id, str) or not self.target_space_id:
            raise ValueError("target_space_id is required")
        if not isinstance(self.interaction_type, str) or not self.interaction_type:
            raise ValueError("interaction_type is required")
        if not isinstance(self.channel_type, str) or not self.channel_type:
            raise ValueError("channel_type is required")
        if not isinstance(self.direction, str) or not self.direction:
            raise ValueError("direction is required")
        if not isinstance(self.visibility, str) or not self.visibility:
            raise ValueError("visibility is required")
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a bool")
        if self.source_id is not None and not (
            isinstance(self.source_id, str) and self.source_id
        ):
            raise ValueError(
                "source_id must be a non-empty string or None"
            )
        if self.target_id is not None and not (
            isinstance(self.target_id, str) and self.target_id
        ):
            raise ValueError(
                "target_id must be a non-empty string or None"
            )

        # Normalize tuples deterministically: keep declaration order
        # but ensure each entry is a non-empty string. Duplicate
        # entries are preserved (callers may declare them
        # intentionally; the book does not silently dedupe).
        for tuple_field_name in (
            "required_input_ref_types",
            "optional_input_ref_types",
            "output_ref_types",
            "routine_types_that_may_use_this_channel",
        ):
            value = getattr(self, tuple_field_name)
            normalized = tuple(value)
            for entry in normalized:
                if not isinstance(entry, str) or not entry:
                    raise ValueError(
                        f"{tuple_field_name} entries must be non-empty strings; "
                        f"got {entry!r}"
                    )
            object.__setattr__(self, tuple_field_name, normalized)

        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "interaction_id": self.interaction_id,
            "source_space_id": self.source_space_id,
            "target_space_id": self.target_space_id,
            "interaction_type": self.interaction_type,
            "channel_type": self.channel_type,
            "direction": self.direction,
            "frequency": self.frequency,
            "phase_id": self.phase_id,
            "visibility": self.visibility,
            "enabled": self.enabled,
            "required_input_ref_types": list(self.required_input_ref_types),
            "optional_input_ref_types": list(self.optional_input_ref_types),
            "output_ref_types": list(self.output_ref_types),
            "routine_types_that_may_use_this_channel": list(
                self.routine_types_that_may_use_this_channel
            ),
            "source_id": self.source_id,
            "target_id": self.target_id,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# Book
# ---------------------------------------------------------------------------


@dataclass
class InteractionBook:
    """
    Storage for ``InteractionSpec`` records.

    The book is append-only, emits a ledger record on each insert,
    and refuses to mutate any other source-of-truth book. It is the
    v1.8.3 implementation of the v1.8.2 design's ``InteractionBook``.

    The book treats spaces as nodes in a directed multigraph. The
    natural data structure is a third-rank tensor ``T ∈ S × S × C``
    where ``S`` is the (small, finite) set of space ids that appear
    in any stored spec and ``C`` is the (open-ended, controlled-
    vocabulary) set of channel types. ``build_space_interaction_tensor``
    materializes that tensor as a sparse nested mapping;
    ``build_space_interaction_matrix`` collapses the channel axis
    for diagram / overview consumers.

    Cross-references are stored as data; the book does not validate
    that any space / actor id resolves to a registered object.
    """

    ledger: Ledger | None = None
    clock: Clock | None = None
    _interactions: dict[str, InteractionSpec] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def add_interaction(self, spec: InteractionSpec) -> InteractionSpec:
        if spec.interaction_id in self._interactions:
            raise DuplicateInteractionError(
                f"Duplicate interaction_id: {spec.interaction_id}"
            )
        self._interactions[spec.interaction_id] = spec

        if self.ledger is not None:
            self.ledger.append(
                event_type="interaction_added",
                simulation_date=self._now(),
                object_id=spec.interaction_id,
                source=spec.source_space_id,
                target=spec.target_space_id,
                payload={
                    "interaction_id": spec.interaction_id,
                    "source_space_id": spec.source_space_id,
                    "target_space_id": spec.target_space_id,
                    "interaction_type": spec.interaction_type,
                    "channel_type": spec.channel_type,
                    "direction": spec.direction,
                    "visibility": spec.visibility,
                    "enabled": spec.enabled,
                    "frequency": spec.frequency,
                    "phase_id": spec.phase_id,
                    "source_id": spec.source_id,
                    "target_id": spec.target_id,
                    "required_input_ref_types": list(
                        spec.required_input_ref_types
                    ),
                    "optional_input_ref_types": list(
                        spec.optional_input_ref_types
                    ),
                    "output_ref_types": list(spec.output_ref_types),
                    "routine_types_that_may_use_this_channel": list(
                        spec.routine_types_that_may_use_this_channel
                    ),
                },
                space_id="interactions",
                visibility=spec.visibility,
            )
        return spec

    def get_interaction(self, interaction_id: str) -> InteractionSpec:
        try:
            return self._interactions[interaction_id]
        except KeyError as exc:
            raise UnknownInteractionError(
                f"Interaction not found: {interaction_id!r}"
            ) from exc

    # ------------------------------------------------------------------
    # Bulk listing
    # ------------------------------------------------------------------

    def list_interactions(
        self, *, include_disabled: bool = False
    ) -> tuple[InteractionSpec, ...]:
        return tuple(self._filter(self._interactions.values(), include_disabled))

    def list_by_source_space(
        self,
        source_space_id: str,
        *,
        include_disabled: bool = False,
    ) -> tuple[InteractionSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._interactions.values()
                    if spec.source_space_id == source_space_id
                ),
                include_disabled,
            )
        )

    def list_by_target_space(
        self,
        target_space_id: str,
        *,
        include_disabled: bool = False,
    ) -> tuple[InteractionSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._interactions.values()
                    if spec.target_space_id == target_space_id
                ),
                include_disabled,
            )
        )

    def list_between_spaces(
        self,
        source_space_id: str,
        target_space_id: str,
        *,
        include_disabled: bool = False,
    ) -> tuple[InteractionSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._interactions.values()
                    if spec.source_space_id == source_space_id
                    and spec.target_space_id == target_space_id
                ),
                include_disabled,
            )
        )

    def list_by_type(
        self,
        interaction_type: str,
        *,
        include_disabled: bool = False,
    ) -> tuple[InteractionSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._interactions.values()
                    if spec.interaction_type == interaction_type
                ),
                include_disabled,
            )
        )

    def list_by_channel(
        self,
        channel_type: str,
        *,
        include_disabled: bool = False,
    ) -> tuple[InteractionSpec, ...]:
        return tuple(
            self._filter(
                (
                    spec
                    for spec in self._interactions.values()
                    if spec.channel_type == channel_type
                ),
                include_disabled,
            )
        )

    def list_for_routine_type(
        self,
        routine_type: str,
        *,
        include_disabled: bool = False,
    ) -> tuple[InteractionSpec, ...]:
        """
        Return every interaction whose
        ``routine_types_that_may_use_this_channel`` either lists the
        given routine type explicitly or is empty (the "any routine
        type" case).
        """
        result: list[InteractionSpec] = []
        for spec in self._interactions.values():
            allowed = spec.routine_types_that_may_use_this_channel
            if not allowed or routine_type in allowed:
                result.append(spec)
        return tuple(self._filter(result, include_disabled))

    # ------------------------------------------------------------------
    # Tensor / matrix views
    # ------------------------------------------------------------------

    def build_space_interaction_tensor(
        self, *, include_disabled: bool = False
    ) -> dict[str, dict[str, dict[str, list[str]]]]:
        """
        Sparse tensor view ``T ∈ S × S × C`` keyed by
        ``source_space_id → target_space_id → channel_type →
        [interaction_id, ...]``.

        - Channel type lists are sorted by ``interaction_id`` for
          deterministic replay.
        - Disabled interactions are excluded by default; pass
          ``include_disabled=True`` to include them.
        - All dict levels are sorted by key on construction.
        """
        bucket: dict[str, dict[str, dict[str, list[str]]]] = {}
        for spec in self._filter(
            self._interactions.values(), include_disabled
        ):
            bucket.setdefault(spec.source_space_id, {}).setdefault(
                spec.target_space_id, {}
            ).setdefault(spec.channel_type, []).append(spec.interaction_id)

        out: dict[str, dict[str, dict[str, list[str]]]] = {}
        for src in sorted(bucket):
            inner_src: dict[str, dict[str, list[str]]] = {}
            for tgt in sorted(bucket[src]):
                inner_tgt: dict[str, list[str]] = {}
                for chan in sorted(bucket[src][tgt]):
                    inner_tgt[chan] = sorted(bucket[src][tgt][chan])
                inner_src[tgt] = inner_tgt
            out[src] = inner_src
        return out

    def build_space_interaction_matrix(
        self, *, include_disabled: bool = False
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """
        Sparse 2-D matrix view ``M ∈ S × S`` keyed by
        ``source_space_id → target_space_id → cell``, where each
        cell carries:

        - ``count``: total interactions (after filtering).
        - ``enabled_count``: interactions with ``enabled=True``.
        - ``channel_types``: sorted unique channel types in the
          cell.
        - ``interaction_ids``: sorted interaction ids in the cell.

        The matrix is the channel-axis collapse of
        ``build_space_interaction_tensor``. When
        ``include_disabled=False`` (default), ``count`` and
        ``enabled_count`` agree (because disabled rows are filtered
        out). When ``include_disabled=True``, ``count`` is the
        unfiltered total and ``enabled_count`` is the live subset.
        """
        cell_specs: dict[str, dict[str, list[InteractionSpec]]] = {}
        for spec in self._filter(
            self._interactions.values(), include_disabled
        ):
            cell_specs.setdefault(spec.source_space_id, {}).setdefault(
                spec.target_space_id, []
            ).append(spec)

        out: dict[str, dict[str, dict[str, Any]]] = {}
        for src in sorted(cell_specs):
            row: dict[str, dict[str, Any]] = {}
            for tgt in sorted(cell_specs[src]):
                specs = cell_specs[src][tgt]
                interaction_ids = sorted(s.interaction_id for s in specs)
                channel_types = sorted({s.channel_type for s in specs})
                enabled_count = sum(1 for s in specs if s.enabled)
                row[tgt] = {
                    "count": len(specs),
                    "enabled_count": enabled_count,
                    "channel_types": channel_types,
                    "interaction_ids": interaction_ids,
                }
            out[src] = row
        return out

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        interactions = sorted(
            (spec.to_dict() for spec in self._interactions.values()),
            key=lambda item: item["interaction_id"],
        )
        return {
            "interaction_count": len(interactions),
            "enabled_count": sum(
                1 for spec in self._interactions.values() if spec.enabled
            ),
            "interactions": interactions,
        }

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _filter(
        specs, include_disabled: bool
    ):
        for spec in specs:
            if include_disabled or spec.enabled:
                yield spec

    def _now(self) -> str | None:
        if self.clock is None or self.clock.current_date is None:
            return None
        return self.clock.current_date.isoformat()
