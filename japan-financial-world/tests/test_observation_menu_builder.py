"""
Tests for v1.8.11 ObservationMenuBuilder.

Covers ``ObservationMenu`` extension acceptance (the two new
``available_variable_observation_ids`` and ``available_exposure_ids``
fields, plus their counts in the existing
``OBSERVATION_MENU_CREATED`` ledger payload), the builder's
``ObservationMenuBuildRequest`` validation, the
``ObservationMenuBuildResult`` shape, the end-to-end
``build_menu`` / ``preview_menu`` flow (date defaulting,
exposure→variable join semantics, no-exposure→empty-variable
default, visibility filtering, inactive-exposure exclusion,
signal collection via ``SignalBook.list_visible_to``,
``available_interaction_ids`` collection from
``carried_by_interaction_id``, status semantics, single ledger
emission via ``AttentionBook.add_menu``, no double-write,
preview-does-not-write), the read-only collectors, kernel wiring
(builder is exposed as ``kernel.observation_menu_builder`` and is
NOT auto-fired by ``tick()`` / ``run()``), and the no-mutation
guarantee against the other v0/v1 source-of-truth books.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.attention import (
    AttentionBook,
    DuplicateObservationMenuError,
    ObservationMenu,
)
from world.clock import Clock
from world.exposures import ExposureBook, ExposureRecord
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.observation_menu_builder import (
    ObservationMenuBuilder,
    ObservationMenuBuildMissingDateError,
    ObservationMenuBuildRequest,
    ObservationMenuBuildResult,
)
from world.registry import Registry
from world.scheduler import Scheduler
from world.signals import InformationSignal, SignalBook
from world.state import State
from world.variables import (
    ReferenceVariableSpec,
    VariableObservation,
    WorldVariableBook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


ACTOR = "investor:reference_pension_a"


def _spec(
    *,
    variable_id: str = "variable:cpi_yoy",
    variable_name: str = "Japan CPI yoy",
    variable_group: str = "inflation",
    variable_type: str = "rate",
    source_space_id: str = "external",
    canonical_unit: str = "percent",
    frequency: str = "QUARTERLY",
    observation_kind: str = "released",
    related_space_ids: tuple[str, ...] = ("investors", "corporates"),
) -> ReferenceVariableSpec:
    return ReferenceVariableSpec(
        variable_id=variable_id,
        variable_name=variable_name,
        variable_group=variable_group,
        variable_type=variable_type,
        source_space_id=source_space_id,
        canonical_unit=canonical_unit,
        frequency=frequency,
        observation_kind=observation_kind,
        related_space_ids=related_space_ids,
    )


def _obs(
    *,
    observation_id: str = "obs:cpi:2026Q1",
    variable_id: str = "variable:cpi_yoy",
    as_of_date: str = "2026-04-15",
    visible_from_date: str | None = None,
    value: float = 2.3,
    unit: str = "percent",
    vintage_id: str = "2026Q1_initial",
    carried_by_interaction_id: str | None = "interaction:macro_data_release",
) -> VariableObservation:
    return VariableObservation(
        observation_id=observation_id,
        variable_id=variable_id,
        as_of_date=as_of_date,
        value=value,
        unit=unit,
        vintage_id=vintage_id,
        visible_from_date=visible_from_date,
        carried_by_interaction_id=carried_by_interaction_id,
    )


def _exposure(
    *,
    exposure_id: str = "exposure:investor_a:cpi",
    subject_id: str = ACTOR,
    subject_type: str = "investor",
    variable_id: str = "variable:cpi_yoy",
    exposure_type: str = "translation",
    metric: str = "portfolio_translation_exposure",
    direction: str = "mixed",
    magnitude: float = 0.4,
    effective_from: str | None = None,
    effective_to: str | None = None,
) -> ExposureRecord:
    return ExposureRecord(
        exposure_id=exposure_id,
        subject_id=subject_id,
        subject_type=subject_type,
        variable_id=variable_id,
        exposure_type=exposure_type,
        metric=metric,
        direction=direction,
        magnitude=magnitude,
        effective_from=effective_from,
        effective_to=effective_to,
    )


def _signal(
    *,
    signal_id: str = "signal:cpi_release:2026Q1",
    signal_type: str = "macro_release",
    subject_id: str = "variable:cpi_yoy",
    source_id: str = "stat:moj",
    published_date: str = "2026-04-15",
    visibility: str = "public",
    metadata: dict | None = None,
) -> InformationSignal:
    return InformationSignal(
        signal_id=signal_id,
        signal_type=signal_type,
        subject_id=subject_id,
        source_id=source_id,
        published_date=published_date,
        visibility=visibility,
        metadata=metadata or {},
    )


def _builder(
    *,
    with_clock: bool = True,
    seed_variable: bool = True,
    seed_observation: bool = True,
    seed_exposure: bool = True,
    seed_signal: bool = True,
    ledger: Ledger | None = None,
) -> ObservationMenuBuilder:
    clk = Clock(current_date=date(2026, 4, 30)) if with_clock else None
    ab = AttentionBook(ledger=ledger, clock=clk)
    sb = SignalBook(ledger=ledger, clock=clk)
    vb = WorldVariableBook(ledger=ledger, clock=clk)
    eb = ExposureBook(ledger=ledger, clock=clk)
    if seed_variable:
        vb.add_variable(_spec())
    if seed_observation:
        vb.add_observation(_obs())
    if seed_exposure:
        eb.add_exposure(_exposure())
    if seed_signal:
        sb.add_signal(_signal())
    return ObservationMenuBuilder(
        attention=ab, signals=sb, variables=vb, exposures=eb, clock=clk
    )


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 4, 30)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# ObservationMenu extension acceptance
# ---------------------------------------------------------------------------


def test_observation_menu_accepts_new_fields():
    menu = ObservationMenu(
        menu_id="m:1",
        actor_id=ACTOR,
        as_of_date="2026-04-30",
        available_variable_observation_ids=("o:1", "o:2"),
        available_exposure_ids=("e:1",),
    )
    assert menu.available_variable_observation_ids == ("o:1", "o:2")
    assert menu.available_exposure_ids == ("e:1",)


def test_observation_menu_total_available_count_includes_new_fields():
    menu = ObservationMenu(
        menu_id="m:1",
        actor_id=ACTOR,
        as_of_date="2026-04-30",
        available_signal_ids=("s:1",),
        available_variable_observation_ids=("o:1", "o:2"),
        available_exposure_ids=("e:1",),
    )
    assert menu.total_available_count() == 4


def test_observation_menu_to_dict_includes_new_fields():
    menu = ObservationMenu(
        menu_id="m:1",
        actor_id=ACTOR,
        as_of_date="2026-04-30",
        available_variable_observation_ids=("o:1",),
        available_exposure_ids=("e:1",),
    )
    d = menu.to_dict()
    assert d["available_variable_observation_ids"] == ["o:1"]
    assert d["available_exposure_ids"] == ["e:1"]


def test_observation_menu_rejects_empty_strings_in_new_fields():
    with pytest.raises(ValueError):
        ObservationMenu(
            menu_id="m:1",
            actor_id=ACTOR,
            as_of_date="2026-04-30",
            available_variable_observation_ids=("",),
        )
    with pytest.raises(ValueError):
        ObservationMenu(
            menu_id="m:1",
            actor_id=ACTOR,
            as_of_date="2026-04-30",
            available_exposure_ids=("",),
        )


def test_add_menu_emits_new_counts_in_ledger_payload():
    ledger = Ledger()
    book = AttentionBook(ledger=ledger)
    book.add_menu(
        ObservationMenu(
            menu_id="m:1",
            actor_id=ACTOR,
            as_of_date="2026-04-30",
            available_variable_observation_ids=("o:1", "o:2"),
            available_exposure_ids=("e:1",),
        )
    )
    records = ledger.filter(event_type="observation_menu_created")
    assert len(records) == 1
    payload = records[0].payload
    assert payload["available_variable_observation_count"] == 2
    assert payload["available_exposure_count"] == 1
    assert payload["total_available_count"] == 3


# ---------------------------------------------------------------------------
# ObservationMenuBuildRequest validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_id": ""},
        {"actor_id": ""},
        {"as_of_date": ""},
        {"phase_id": ""},
    ],
)
def test_request_rejects_empty_required_strings(kwargs):
    base = {"request_id": "req:1", "actor_id": ACTOR}
    base.update(kwargs)
    with pytest.raises(ValueError):
        ObservationMenuBuildRequest(**base)


@pytest.mark.parametrize(
    "flag",
    ["include_signals", "include_variables", "include_exposures"],
)
def test_request_rejects_non_bool_flags(flag):
    with pytest.raises(ValueError):
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, **{flag: "yes"}
        )


def test_request_is_frozen():
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    with pytest.raises(Exception):
        req.request_id = "tampered"  # type: ignore[misc]


def test_request_to_dict_round_trips_fields():
    req = ObservationMenuBuildRequest(
        request_id="req:1",
        actor_id=ACTOR,
        as_of_date="2026-04-30",
        phase_id="phase:open",
        include_signals=False,
    )
    d = req.to_dict()
    assert d["request_id"] == "req:1"
    assert d["actor_id"] == ACTOR
    assert d["as_of_date"] == "2026-04-30"
    assert d["phase_id"] == "phase:open"
    assert d["include_signals"] is False


# ---------------------------------------------------------------------------
# build_menu: happy path
# ---------------------------------------------------------------------------


def test_build_menu_writes_one_observation_menu():
    builder = _builder()
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    result = builder.build_menu(req)
    assert isinstance(result, ObservationMenuBuildResult)
    menus = builder.attention.list_menus_by_actor(ACTOR)
    assert len(menus) == 1
    assert menus[0].menu_id == result.menu_id


def test_build_menu_result_mirrors_persisted_menu():
    builder = _builder()
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    result = builder.build_menu(req)
    stored = builder.attention.get_menu(result.menu_id)
    assert stored.actor_id == result.actor_id
    assert stored.as_of_date == result.as_of_date
    assert stored.available_signal_ids == result.available_signal_ids
    assert (
        stored.available_variable_observation_ids
        == result.available_variable_observation_ids
    )
    assert stored.available_exposure_ids == result.available_exposure_ids
    assert (
        stored.available_interaction_ids
        == result.available_interaction_ids
    )


def test_build_menu_default_id_links_to_request():
    builder = _builder()
    req = ObservationMenuBuildRequest(request_id="req:link", actor_id=ACTOR)
    result = builder.build_menu(req)
    assert result.menu_id == "menu:req:link"


def test_build_menu_metadata_id_override_honored():
    builder = _builder()
    req = ObservationMenuBuildRequest(
        request_id="req:1",
        actor_id=ACTOR,
        metadata={"menu_id": "menu:custom"},
    )
    result = builder.build_menu(req)
    assert result.menu_id == "menu:custom"


# ---------------------------------------------------------------------------
# Date semantics
# ---------------------------------------------------------------------------


def test_request_as_of_date_overrides_clock():
    builder = _builder()  # clock at 2026-04-30
    req = ObservationMenuBuildRequest(
        request_id="req:1", actor_id=ACTOR, as_of_date="2026-06-30"
    )
    result = builder.build_menu(req)
    assert result.as_of_date == "2026-06-30"


def test_date_defaults_to_clock_when_request_omits_it():
    builder = _builder()  # clock at 2026-04-30
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    result = builder.build_menu(req)
    assert result.as_of_date == "2026-04-30"


def test_missing_date_without_clock_raises_controlled_error():
    builder = _builder(with_clock=False)
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    with pytest.raises(ObservationMenuBuildMissingDateError):
        builder.build_menu(req)


# ---------------------------------------------------------------------------
# Exposure / variable join semantics
# ---------------------------------------------------------------------------


def test_variables_filtered_by_actor_exposures():
    """Only observations on variables the actor is exposed to are surfaced."""
    builder = _builder(seed_observation=False, seed_exposure=False)
    # Two variables exist; actor exposed only to one.
    builder.variables.add_variable(_spec(variable_id="variable:wage_growth"))
    builder.variables.add_observation(_obs(observation_id="obs:cpi:2026Q1"))
    builder.variables.add_observation(
        _obs(
            observation_id="obs:wage:2026Q1",
            variable_id="variable:wage_growth",
        )
    )
    builder.exposures.add_exposure(_exposure())  # cpi only

    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert result.available_variable_observation_ids == ("obs:cpi:2026Q1",)


def test_no_exposures_yields_empty_variable_list():
    """v1.8.11 default: don't dump every world variable on every actor."""
    builder = _builder(seed_exposure=False)
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert result.available_variable_observation_ids == ()
    # Sanity: signals are still surfaced (independent of exposures).
    assert result.available_signal_ids == ("signal:cpi_release:2026Q1",)


def test_visibility_filters_observation_after_as_of_date():
    builder = _builder(seed_observation=False)
    # Observation visible only from 2027-01-01.
    builder.variables.add_observation(
        _obs(visible_from_date="2027-01-01")
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, as_of_date="2026-04-30"
        )
    )
    assert result.available_variable_observation_ids == ()


def test_visibility_admits_observation_at_or_before_as_of_date():
    builder = _builder(seed_observation=False)
    builder.variables.add_observation(
        _obs(visible_from_date="2026-04-30")
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, as_of_date="2026-04-30"
        )
    )
    assert result.available_variable_observation_ids == ("obs:cpi:2026Q1",)


def test_inactive_exposure_excluded():
    """An exposure with effective_to in the past must not gate a variable."""
    builder = _builder(seed_exposure=False)
    builder.exposures.add_exposure(
        _exposure(effective_to="2025-12-31")
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, as_of_date="2026-04-30"
        )
    )
    assert result.available_exposure_ids == ()
    assert result.available_variable_observation_ids == ()


def test_only_exposures_belonging_to_actor_are_surfaced():
    builder = _builder(seed_exposure=False)
    builder.exposures.add_exposure(_exposure())
    builder.exposures.add_exposure(
        _exposure(
            exposure_id="exposure:other:cpi",
            subject_id="investor:other_investor",
        )
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert result.available_exposure_ids == ("exposure:investor_a:cpi",)


# ---------------------------------------------------------------------------
# Signal collection
# ---------------------------------------------------------------------------


def test_signals_use_list_visible_to_for_visibility():
    builder = _builder(seed_signal=False)
    builder.signals.add_signal(
        _signal(signal_id="s:public", visibility="public")
    )
    builder.signals.add_signal(
        _signal(
            signal_id="s:private",
            visibility="private",
            metadata={"allowed_viewers": ("investor:other",)},
        )
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert "s:public" in result.available_signal_ids
    assert "s:private" not in result.available_signal_ids


# ---------------------------------------------------------------------------
# Interaction-id collection
# ---------------------------------------------------------------------------


def test_available_interaction_ids_include_carried_by_interaction_id():
    builder = _builder()
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert (
        "interaction:macro_data_release"
        in result.available_interaction_ids
    )


def test_available_interaction_ids_include_signal_metadata_link():
    builder = _builder(seed_signal=False)
    builder.signals.add_signal(
        _signal(
            signal_id="s:with_iid",
            metadata={"interaction_id": "interaction:from_signal"},
        )
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert "interaction:from_signal" in result.available_interaction_ids


def test_available_interaction_ids_deduplicated():
    builder = _builder(seed_observation=False)
    # Two observations sharing the same carried_by_interaction_id.
    builder.variables.add_observation(_obs(observation_id="o:a"))
    builder.variables.add_observation(_obs(observation_id="o:b"))
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert result.available_interaction_ids.count(
        "interaction:macro_data_release"
    ) == 1


# ---------------------------------------------------------------------------
# Status semantics
# ---------------------------------------------------------------------------


def test_status_completed_when_any_candidate_present():
    builder = _builder()
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert result.status == "completed"


def test_status_empty_when_no_candidates():
    builder = _builder(
        seed_observation=False, seed_exposure=False, seed_signal=False
    )
    result = builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    assert result.status == "empty"


def test_status_metadata_override_honored():
    builder = _builder()
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1",
            actor_id=ACTOR,
            metadata={"status": "partial"},
        )
    )
    assert result.status == "partial"


# ---------------------------------------------------------------------------
# Include flags
# ---------------------------------------------------------------------------


def test_include_signals_false_skips_signal_collection():
    builder = _builder()
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, include_signals=False
        )
    )
    assert result.available_signal_ids == ()


def test_include_variables_false_skips_variable_collection():
    builder = _builder()
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, include_variables=False
        )
    )
    assert result.available_variable_observation_ids == ()


def test_include_exposures_false_skips_exposure_collection():
    builder = _builder()
    result = builder.build_menu(
        ObservationMenuBuildRequest(
            request_id="req:1", actor_id=ACTOR, include_exposures=False
        )
    )
    assert result.available_exposure_ids == ()


# ---------------------------------------------------------------------------
# Ledger emission contract
# ---------------------------------------------------------------------------


def test_build_menu_emits_exactly_one_observation_menu_created_record():
    ledger = Ledger()
    builder = _builder(ledger=ledger)
    builder.build_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    records = ledger.filter(event_type="observation_menu_created")
    assert len(records) == 1


def test_duplicate_menu_id_raises_through_attention_book():
    builder = _builder()
    req = ObservationMenuBuildRequest(
        request_id="req:1",
        actor_id=ACTOR,
        metadata={"menu_id": "menu:dup"},
    )
    builder.build_menu(req)
    with pytest.raises(DuplicateObservationMenuError):
        builder.build_menu(req)


# ---------------------------------------------------------------------------
# preview_menu
# ---------------------------------------------------------------------------


def test_preview_menu_does_not_persist():
    builder = _builder()
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    result = builder.preview_menu(req)
    assert builder.attention.list_menus_by_actor(ACTOR) == ()
    assert result.menu_id.startswith("menu:preview:")


def test_preview_menu_does_not_emit_ledger():
    ledger = Ledger()
    builder = _builder(ledger=ledger)
    builder.preview_menu(
        ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    )
    records = ledger.filter(event_type="observation_menu_created")
    assert records == []


def test_preview_menu_returns_same_content_as_build():
    builder_b = _builder()
    builder_p = _builder()
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)
    built = builder_b.build_menu(req)
    previewed = builder_p.preview_menu(req)
    assert (
        built.available_variable_observation_ids
        == previewed.available_variable_observation_ids
    )
    assert built.available_exposure_ids == previewed.available_exposure_ids
    assert built.available_signal_ids == previewed.available_signal_ids
    assert (
        built.available_interaction_ids
        == previewed.available_interaction_ids
    )


# ---------------------------------------------------------------------------
# Read-only collectors
# ---------------------------------------------------------------------------


def test_collect_visible_signals_returns_visible_ids():
    builder = _builder()
    ids = builder.collect_visible_signals(ACTOR, "2026-04-30")
    assert ids == ("signal:cpi_release:2026Q1",)


def test_collect_active_exposures_returns_actor_only():
    builder = _builder(seed_exposure=False)
    builder.exposures.add_exposure(_exposure())
    builder.exposures.add_exposure(
        _exposure(
            exposure_id="exposure:other:cpi",
            subject_id="investor:other",
        )
    )
    ids = builder.collect_active_exposures(ACTOR, "2026-04-30")
    assert ids == ("exposure:investor_a:cpi",)


def test_collect_visible_variable_observations_uses_exposure_join():
    builder = _builder()
    ids = builder.collect_visible_variable_observations(ACTOR, "2026-04-30")
    assert ids == ("obs:cpi:2026Q1",)


def test_collect_visible_variable_observations_empty_without_exposures():
    builder = _builder(seed_exposure=False)
    ids = builder.collect_visible_variable_observations(ACTOR, "2026-04-30")
    assert ids == ()


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_observation_menu_builder():
    k = _kernel()
    assert k.observation_menu_builder is not None
    assert isinstance(k.observation_menu_builder, ObservationMenuBuilder)
    assert k.observation_menu_builder.attention is k.attention
    assert k.observation_menu_builder.signals is k.signals
    assert k.observation_menu_builder.variables is k.variables
    assert k.observation_menu_builder.exposures is k.exposures
    assert k.observation_menu_builder.clock is k.clock


def test_kernel_tick_does_not_auto_build_menu():
    k = _kernel()
    k.tick()
    assert k.attention.list_menus_by_actor(ACTOR) == ()


def test_kernel_run_does_not_auto_build_menu():
    k = _kernel()
    k.run(days=3)
    assert k.attention.list_menus_by_actor(ACTOR) == ()


# ---------------------------------------------------------------------------
# No-mutation guarantees against other v0/v1 books
# ---------------------------------------------------------------------------


def test_build_menu_does_not_mutate_other_books():
    builder = _builder()
    req = ObservationMenuBuildRequest(request_id="req:1", actor_id=ACTOR)

    signals_before = tuple(builder.signals._signals.keys())  # type: ignore[attr-defined]
    variables_before = tuple(builder.variables._variables.keys())  # type: ignore[attr-defined]
    observations_before = tuple(
        builder.variables._observations.keys()  # type: ignore[attr-defined]
    )
    exposures_before = tuple(builder.exposures._exposures.keys())  # type: ignore[attr-defined]

    builder.build_menu(req)

    assert tuple(builder.signals._signals.keys()) == signals_before  # type: ignore[attr-defined]
    assert tuple(builder.variables._variables.keys()) == variables_before  # type: ignore[attr-defined]
    assert (
        tuple(builder.variables._observations.keys())  # type: ignore[attr-defined]
        == observations_before
    )
    assert tuple(builder.exposures._exposures.keys()) == exposures_before  # type: ignore[attr-defined]
