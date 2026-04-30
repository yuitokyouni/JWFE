from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from spaces.domain import DomainSpace
from spaces.information.state import (
    DuplicateInformationChannelStateError,
    DuplicateInformationSourceStateError,
    InformationChannelState,
    InformationSourceState,
)
from world.scheduler import Frequency
from world.signals import InformationSignal


@dataclass
class InformationSpace(DomainSpace):
    """
    Information Space — minimum internal state for sources and channels.

    v0.13 scope:
        - hold a mapping of source_id -> InformationSourceState
          (who produces information)
        - hold a mapping of channel_id -> InformationChannelState
          (through what medium information is distributed)
        - read SignalBook (canonical signal store) by source, by type,
          or by visibility
        - log information_source_state_added and
          information_channel_state_added when those records enter
          the space

    v0.13 explicitly does NOT implement:
        - news generation, narrative formation, or rumor creation
        - analyst report writing, signal interpretation, or
          recommendation logic
        - source credibility dynamics, accuracy tracking, or bias
          modeling
        - rumor propagation, leak diffusion, or audience targeting
        - investor reactions to signals (handled by InvestorSpace, but
          v0.10 doesn't implement reactions either)
        - price impact from signals
        - any mutation of SignalBook or other source books
        - any mutation of other spaces (CorporateSpace, BankSpace,
          InvestorSpace, ExchangeSpace, RealEstateSpace, etc.)

    Pattern note: this is the sixth concrete domain space. The
    bind() / kernel-ref / read-only pattern from §27–§32 is reused
    unchanged. Information is special only in that it has no
    domain-specific kernel ref of its own (it relies entirely on
    inherited DomainSpace refs, in particular ``signals``).

    Architectural note: SignalBook (§26) remains the canonical store.
    InformationSpace classifies sources and channels, but does not own
    or mutate signals. The same separation as elsewhere in the world
    model: domain spaces classify; the kernel books value, store, and
    record.
    """

    space_id: str = "information"
    frequencies: tuple[Frequency, ...] = (Frequency.DAILY,)
    _sources: dict[str, InformationSourceState] = field(default_factory=dict)
    _channels: dict[str, InformationChannelState] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Lifecycle hook
    #
    # InformationSpace has no domain-specific kernel ref to add — it
    # uses ``self.signals`` and ``self.registry`` from DomainSpace.
    # No bind() override is needed.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Source CRUD
    # ------------------------------------------------------------------

    def add_source_state(
        self,
        source_state: InformationSourceState,
    ) -> InformationSourceState:
        if source_state.source_id in self._sources:
            raise DuplicateInformationSourceStateError(
                f"Duplicate source_id: {source_state.source_id}"
            )
        self._sources[source_state.source_id] = source_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="information_source_state_added",
                simulation_date=simulation_date,
                object_id=source_state.source_id,
                payload={
                    "source_id": source_state.source_id,
                    "source_type": source_state.source_type,
                    "tier": source_state.tier,
                    "status": source_state.status,
                },
                space_id=self.space_id,
            )
        return source_state

    def get_source_state(
        self,
        source_id: str,
    ) -> InformationSourceState | None:
        return self._sources.get(source_id)

    def list_sources(self) -> tuple[InformationSourceState, ...]:
        """Return all registered information sources in insertion order."""
        return tuple(self._sources.values())

    # ------------------------------------------------------------------
    # Channel CRUD
    # ------------------------------------------------------------------

    def add_channel_state(
        self,
        channel_state: InformationChannelState,
    ) -> InformationChannelState:
        if channel_state.channel_id in self._channels:
            raise DuplicateInformationChannelStateError(
                f"Duplicate channel_id: {channel_state.channel_id}"
            )
        self._channels[channel_state.channel_id] = channel_state

        if self.ledger is not None:
            simulation_date = (
                self.clock.current_date if self.clock is not None else None
            )
            self.ledger.append(
                event_type="information_channel_state_added",
                simulation_date=simulation_date,
                object_id=channel_state.channel_id,
                payload={
                    "channel_id": channel_state.channel_id,
                    "channel_type": channel_state.channel_type,
                    "visibility": channel_state.visibility,
                    "status": channel_state.status,
                },
                space_id=self.space_id,
            )
        return channel_state

    def get_channel_state(
        self,
        channel_id: str,
    ) -> InformationChannelState | None:
        return self._channels.get(channel_id)

    def list_channels(self) -> tuple[InformationChannelState, ...]:
        """Return all registered information channels in insertion order."""
        return tuple(self._channels.values())

    # ------------------------------------------------------------------
    # Signal-derived views (read-only access to SignalBook)
    # ------------------------------------------------------------------

    def list_signals_by_source(
        self,
        source_id: str,
    ) -> tuple[InformationSignal, ...]:
        """
        Return signals produced by ``source_id``.

        Wraps :meth:`SignalBook.list_by_source`. v0.13 does not require
        the source to be registered in this space — the signal book is
        the canonical source-of-truth for which signals exist; the
        space only classifies sources for organization.

        Returns ``()`` when no SignalBook is bound.
        """
        if self.signals is None:
            return ()
        return self.signals.list_by_source(source_id)

    def list_signals_by_type(
        self,
        signal_type: str,
    ) -> tuple[InformationSignal, ...]:
        """
        Return signals with the given ``signal_type``.

        Wraps :meth:`SignalBook.list_by_type`.

        Returns ``()`` when no SignalBook is bound.
        """
        if self.signals is None:
            return ()
        return self.signals.list_by_type(signal_type)

    def list_visible_signals(
        self,
        observer_id: str,
        *,
        as_of_date: date | str | None = None,
    ) -> tuple[InformationSignal, ...]:
        """
        Return signals visible to ``observer_id``.

        InformationSpace exposes this name alongside the inherited
        :meth:`get_visible_signals` (from DomainSpace) for clarity in
        information-flavored call sites. Both delegate to
        :meth:`SignalBook.list_visible_to`.
        """
        return self.get_visible_signals(observer_id, as_of_date=as_of_date)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """
        Return a deterministic, JSON-friendly view of the space.

        Sources are sorted by ``source_id``. Channels are sorted by
        ``channel_id``. Both are stable across runs.
        """
        sources = sorted(
            (source.to_dict() for source in self._sources.values()),
            key=lambda item: item["source_id"],
        )
        channels = sorted(
            (channel.to_dict() for channel in self._channels.values()),
            key=lambda item: item["channel_id"],
        )
        return {
            "space_id": self.space_id,
            "source_count": len(sources),
            "channel_count": len(channels),
            "sources": sources,
            "channels": channels,
        }
