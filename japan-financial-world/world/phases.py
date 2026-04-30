from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class PhaseError(Exception):
    """Base class for intraday phase errors."""


class UnknownPhaseError(PhaseError, KeyError):
    """Raised when a phase_id is not found in the sequence."""


# ---------------------------------------------------------------------------
# Default v1.2 phase sequence
# ---------------------------------------------------------------------------
#
# These six phases form the jurisdiction-neutral default. They are *names*,
# not trading rules. v1.2 does not assume a specific exchange's hours, does
# not implement order matching at any phase, and does not impose phase-
# specific market behavior. A future v2 (Japan public calibration) may
# define additional phases or adjust ordering for a specific exchange.

_DEFAULT_PHASE_SPECS: tuple[tuple[str, str], ...] = (
    ("overnight", "Overnight"),
    ("pre_open", "Pre-open"),
    ("opening_auction", "Opening auction"),
    ("continuous_session", "Continuous session"),
    ("closing_auction", "Closing auction"),
    ("post_close", "Post-close"),
)


@dataclass(frozen=True)
class IntradayPhaseSpec:
    """
    Specification for one intraday phase.

    A phase is a named, ordered slot inside a calendar day. v1.2 uses
    phases purely as a scheduling axis — they answer "in what order do
    things happen within a day?" — and not as a market microstructure
    construct. There is no auction matching, no quote feed, no halt
    logic attached to any phase by default.

    Fields:
        phase_id  : stable string id (e.g. "overnight", "opening_auction").
                    Should match a value in the scheduler's Phase enum
                    when the phase is used for task dispatch.
        order     : integer ordering within the day. Lower is earlier.
        label     : human-readable label, used in logs / docs.
        metadata  : free-form bag for non-standard attributes.
    """

    phase_id: str
    order: int
    label: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.phase_id:
            raise ValueError("phase_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "order": self.order,
            "label": self.label,
            "metadata": dict(self.metadata),
        }


@dataclass
class PhaseSequence:
    """
    An ordered sequence of intraday phases.

    PhaseSequence is a thin container with a few navigation helpers. It
    does not run anything itself. The kernel decides when to iterate
    through the sequence (see ``WorldKernel.run_day_with_phases``); the
    sequence only knows what comes next.

    The default sequence (``PhaseSequence.default_phases()``) is the v1.2
    canonical six-phase day. Custom sequences can be constructed for
    tests or for future jurisdiction-specific calendars, but v1.2 itself
    ships only the default.
    """

    phases: tuple[IntradayPhaseSpec, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for spec in self.phases:
            if spec.phase_id in seen:
                raise ValueError(
                    f"Duplicate phase_id in sequence: {spec.phase_id!r}"
                )
            seen.add(spec.phase_id)

    @classmethod
    def default_phases(cls) -> "PhaseSequence":
        """
        Return the v1.2 default 6-phase sequence:

            overnight → pre_open → opening_auction →
            continuous_session → closing_auction → post_close

        This sequence is jurisdiction-neutral. v2 may extend or override
        it; v1.2 does not.
        """
        specs = tuple(
            IntradayPhaseSpec(phase_id=phase_id, order=index, label=label)
            for index, (phase_id, label) in enumerate(_DEFAULT_PHASE_SPECS)
        )
        return cls(phases=specs)

    def list_phases(self) -> tuple[IntradayPhaseSpec, ...]:
        return self.phases

    def get_phase(self, phase_id: str) -> IntradayPhaseSpec:
        for spec in self.phases:
            if spec.phase_id == phase_id:
                return spec
        raise UnknownPhaseError(f"Unknown phase_id: {phase_id!r}")

    def next_phase(self, current_phase_id: str) -> IntradayPhaseSpec | None:
        """Return the next phase after ``current_phase_id``, or ``None`` if it is the last."""
        for index, spec in enumerate(self.phases):
            if spec.phase_id == current_phase_id:
                if index + 1 < len(self.phases):
                    return self.phases[index + 1]
                return None
        raise UnknownPhaseError(f"Unknown phase_id: {current_phase_id!r}")

    def is_first_phase(self, phase_id: str) -> bool:
        if not self.phases:
            return False
        return self.phases[0].phase_id == phase_id

    def is_last_phase(self, phase_id: str) -> bool:
        if not self.phases:
            return False
        return self.phases[-1].phase_id == phase_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": len(self.phases),
            "phases": [spec.to_dict() for spec in self.phases],
        }
