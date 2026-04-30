from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


class InformationStateError(Exception):
    """Base class for information-space state errors."""


class DuplicateInformationSourceStateError(InformationStateError):
    """Raised when a source_id is added twice."""


class DuplicateInformationChannelStateError(InformationStateError):
    """Raised when a channel_id is added twice."""


@dataclass(frozen=True)
class InformationSourceState:
    """
    Identity-level record for an information source.

    A source is *who or what produces information*: a rating agency, a
    wire service, a regulator, an analyst, an internal disclosure desk,
    a leaker, an automated data feed. v0.13 stores classification only:
    which source, what type, what tier, what status. It does NOT store
    credibility scores, accuracy history, bias estimates, or topical
    specialty — because those would be the foundation of narrative /
    credibility behavior, and v0.13 does not implement that behavior.

    The intent is to give InformationSpace just enough native
    classification to organize sources without introducing
    interpretation logic. Reasoning about *what a source means* is
    deferred. Right now we only record *that the source exists*.
    """

    source_id: str
    source_type: str = "unspecified"
    tier: str = "unspecified"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "tier": self.tier,
            "status": self.status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class InformationChannelState:
    """
    Identity-level record for an information channel.

    A channel is *the medium through which information is distributed*:
    a wire service, a press release, social media, an internal memo
    distribution list, a regulatory filing system. Each channel has an
    inherent reach pattern, captured here as ``visibility``.

    v0.13 stores ``visibility`` as a free-form string label. It is
    intentionally NOT validated against ``SignalBook``'s visibility
    enum — channel reach and signal visibility are related but distinct
    concepts, and coupling them would mean every channel must declare
    a visibility that is also a valid signal visibility. v0.13 keeps
    them independent: the channel records what kind of medium it is,
    and the signal records who can see it. Future milestones may
    introduce a propagation rule that uses both.

    There is no ``audience_size``, ``read_rate``, ``decay``, or
    ``noise_level`` field. v0.13 does not implement narrative dynamics.
    """

    channel_id: str
    channel_type: str = "unspecified"
    visibility: str = "public"
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.channel_id:
            raise ValueError("channel_id is required")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "channel_type": self.channel_type,
            "visibility": self.visibility,
            "status": self.status,
            "metadata": dict(self.metadata),
        }
