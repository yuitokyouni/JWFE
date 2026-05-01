"""
Tests for v1.8.3 InteractionBook + Tensor View.

Covers ``InteractionSpec`` field validation, ``InteractionBook``
CRUD + filter listings, deterministic tensor / matrix views, the
self-loop and channel-multiplicity cases that the v1.8.2 design
called out, ledger emission, snapshot determinism, and the no-
mutation guarantee against every other v0/v1 source-of-truth book.
"""

from __future__ import annotations

from datetime import date

import pytest

from world.clock import Clock
from world.interactions import (
    DuplicateInteractionError,
    InteractionBook,
    InteractionSpec,
    UnknownInteractionError,
)
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _spec(
    *,
    interaction_id: str = "interaction:corporate.earnings_to_information",
    source_space_id: str = "corporate",
    target_space_id: str = "information",
    interaction_type: str = "earnings_disclosure",
    channel_type: str = "scheduled_filing",
    direction: str = "directed",
    frequency: str | None = "QUARTERLY",
    phase_id: str | None = "post_close",
    visibility: str = "public",
    enabled: bool = True,
    required_input_ref_types: tuple[str, ...] = ("FundamentalsRecord",),
    optional_input_ref_types: tuple[str, ...] = (),
    output_ref_types: tuple[str, ...] = ("InformationSignal",),
    routine_types_that_may_use_this_channel: tuple[str, ...] = (
        "corporate_quarterly_reporting",
    ),
    source_id: str | None = None,
    target_id: str | None = None,
    metadata: dict | None = None,
) -> InteractionSpec:
    return InteractionSpec(
        interaction_id=interaction_id,
        source_space_id=source_space_id,
        target_space_id=target_space_id,
        interaction_type=interaction_type,
        channel_type=channel_type,
        direction=direction,
        frequency=frequency,
        phase_id=phase_id,
        visibility=visibility,
        enabled=enabled,
        required_input_ref_types=required_input_ref_types,
        optional_input_ref_types=optional_input_ref_types,
        output_ref_types=output_ref_types,
        routine_types_that_may_use_this_channel=(
            routine_types_that_may_use_this_channel
        ),
        source_id=source_id,
        target_id=target_id,
        metadata=metadata or {},
    )


def _kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


# ---------------------------------------------------------------------------
# InteractionSpec validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"interaction_id": ""},
        {"source_space_id": ""},
        {"target_space_id": ""},
        {"interaction_type": ""},
        {"channel_type": ""},
        {"direction": ""},
        {"visibility": ""},
        {"source_id": ""},
        {"target_id": ""},
    ],
)
def test_interaction_spec_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _spec(**kwargs)


def test_interaction_spec_rejects_non_bool_enabled():
    with pytest.raises(ValueError):
        _spec(enabled="yes")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "tuple_field",
    [
        "required_input_ref_types",
        "optional_input_ref_types",
        "output_ref_types",
        "routine_types_that_may_use_this_channel",
    ],
)
def test_interaction_spec_rejects_empty_strings_in_tuple_fields(tuple_field):
    bad = {tuple_field: ("", "valid")}
    with pytest.raises(ValueError):
        _spec(**bad)


def test_interaction_spec_normalizes_tuple_fields_to_tuples():
    spec = _spec(
        required_input_ref_types=["FundamentalsRecord", "ValuationRecord"],
        output_ref_types=("InformationSignal",),
    )
    assert isinstance(spec.required_input_ref_types, tuple)
    assert isinstance(spec.output_ref_types, tuple)


def test_interaction_spec_is_frozen():
    spec = _spec()
    with pytest.raises(Exception):
        spec.interaction_id = "tampered"  # type: ignore[misc]


def test_interaction_spec_to_dict_is_serializable():
    spec = _spec()
    d = spec.to_dict()
    assert d["interaction_id"] == spec.interaction_id
    assert d["source_space_id"] == spec.source_space_id
    assert d["target_space_id"] == spec.target_space_id
    assert d["enabled"] is True
    assert d["required_input_ref_types"] == ["FundamentalsRecord"]
    assert d["routine_types_that_may_use_this_channel"] == [
        "corporate_quarterly_reporting"
    ]


# ---------------------------------------------------------------------------
# add_interaction / get_interaction / duplicate
# ---------------------------------------------------------------------------


def test_add_and_get_interaction():
    book = InteractionBook()
    spec = _spec()
    book.add_interaction(spec)
    fetched = book.get_interaction(spec.interaction_id)
    assert fetched is spec


def test_get_interaction_unknown_raises():
    book = InteractionBook()
    with pytest.raises(UnknownInteractionError):
        book.get_interaction("interaction:does_not_exist")


def test_duplicate_interaction_id_rejected():
    book = InteractionBook()
    book.add_interaction(_spec())
    with pytest.raises(DuplicateInteractionError):
        book.add_interaction(_spec())


# ---------------------------------------------------------------------------
# Filter listings
# ---------------------------------------------------------------------------


def _seed_typical_topology(book: InteractionBook) -> None:
    """A small but realistic set of interactions across spaces."""
    book.add_interaction(
        _spec(
            interaction_id="interaction:corporate.earnings_to_information",
            source_space_id="corporate",
            target_space_id="information",
            interaction_type="earnings_disclosure",
            channel_type="scheduled_filing",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:corporate.guidance_to_information",
            source_space_id="corporate",
            target_space_id="information",
            interaction_type="guidance_revision",
            channel_type="scheduled_filing",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:banking.review_to_corporate",
            source_space_id="banking",
            target_space_id="corporate",
            interaction_type="credit_review",
            channel_type="private_communication",
            routine_types_that_may_use_this_channel=("bank_review",),
            output_ref_types=("InstitutionalActionRecord",),
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:investors.engagement_to_corporate",
            source_space_id="investors",
            target_space_id="corporate",
            interaction_type="engagement",
            channel_type="private_communication",
            routine_types_that_may_use_this_channel=("investor_review",),
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:policy.guidance_to_information",
            source_space_id="policy",
            target_space_id="information",
            interaction_type="policy_guidance",
            channel_type="public_broadcast",
            routine_types_that_may_use_this_channel=(),  # any routine
        )
    )


def test_list_interactions_returns_all_enabled():
    book = InteractionBook()
    _seed_typical_topology(book)
    results = book.list_interactions()
    assert len(results) == 5
    assert all(spec.enabled for spec in results)


def test_list_by_source_space():
    book = InteractionBook()
    _seed_typical_topology(book)
    corporate_out = book.list_by_source_space("corporate")
    assert len(corporate_out) == 2
    assert {spec.interaction_id for spec in corporate_out} == {
        "interaction:corporate.earnings_to_information",
        "interaction:corporate.guidance_to_information",
    }
    assert book.list_by_source_space("real_estate") == ()


def test_list_by_target_space():
    book = InteractionBook()
    _seed_typical_topology(book)
    targets_corporate = book.list_by_target_space("corporate")
    assert {spec.interaction_id for spec in targets_corporate} == {
        "interaction:banking.review_to_corporate",
        "interaction:investors.engagement_to_corporate",
    }


def test_list_between_spaces():
    book = InteractionBook()
    _seed_typical_topology(book)
    corp_to_info = book.list_between_spaces("corporate", "information")
    assert len(corp_to_info) == 2
    assert book.list_between_spaces("information", "corporate") == ()


def test_list_by_type():
    book = InteractionBook()
    _seed_typical_topology(book)
    earnings = book.list_by_type("earnings_disclosure")
    assert len(earnings) == 1
    assert earnings[0].interaction_id.endswith("earnings_to_information")
    assert book.list_by_type("rumor") == ()


def test_list_by_channel():
    book = InteractionBook()
    _seed_typical_topology(book)
    scheduled = book.list_by_channel("scheduled_filing")
    assert len(scheduled) == 2
    private = book.list_by_channel("private_communication")
    assert len(private) == 2


# ---------------------------------------------------------------------------
# list_for_routine_type
# ---------------------------------------------------------------------------


def test_list_for_routine_type_explicit_match():
    book = InteractionBook()
    _seed_typical_topology(book)
    results = book.list_for_routine_type("bank_review")
    # bank_review explicitly listed on banking.review_to_corporate;
    # plus the policy.guidance interaction whose allowed-set is empty
    # (any routine type).
    assert {spec.interaction_id for spec in results} == {
        "interaction:banking.review_to_corporate",
        "interaction:policy.guidance_to_information",
    }


def test_list_for_routine_type_empty_allowed_means_any():
    book = InteractionBook()
    _seed_typical_topology(book)
    arbitrary = book.list_for_routine_type("some_brand_new_routine_type")
    # Only the policy.guidance entry has an empty allowed-set; that is
    # the only one that opts in to "any routine type" semantics.
    assert {spec.interaction_id for spec in arbitrary} == {
        "interaction:policy.guidance_to_information"
    }


# ---------------------------------------------------------------------------
# Disabled interactions
# ---------------------------------------------------------------------------


def test_disabled_interactions_excluded_by_default():
    book = InteractionBook()
    book.add_interaction(_spec(interaction_id="interaction:enabled_one"))
    book.add_interaction(
        _spec(interaction_id="interaction:disabled_one", enabled=False)
    )
    listed = book.list_interactions()
    ids = {s.interaction_id for s in listed}
    assert ids == {"interaction:enabled_one"}


def test_disabled_interactions_included_with_flag():
    book = InteractionBook()
    book.add_interaction(_spec(interaction_id="interaction:enabled_one"))
    book.add_interaction(
        _spec(interaction_id="interaction:disabled_one", enabled=False)
    )
    listed = book.list_interactions(include_disabled=True)
    ids = {s.interaction_id for s in listed}
    assert ids == {"interaction:enabled_one", "interaction:disabled_one"}


def test_disabled_excluded_from_filter_listings_too():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:a",
            source_space_id="corporate",
            channel_type="scheduled_filing",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:b",
            source_space_id="corporate",
            channel_type="scheduled_filing",
            enabled=False,
        )
    )
    assert {s.interaction_id for s in book.list_by_source_space("corporate")} == {
        "interaction:a"
    }
    assert {
        s.interaction_id
        for s in book.list_by_source_space("corporate", include_disabled=True)
    } == {"interaction:a", "interaction:b"}
    assert {s.interaction_id for s in book.list_by_channel("scheduled_filing")} == {
        "interaction:a"
    }


# ---------------------------------------------------------------------------
# Self-loops
# ---------------------------------------------------------------------------


def test_self_loop_corporate_reporting_preparation():
    book = InteractionBook()
    spec = _spec(
        interaction_id="interaction:corporate.reporting_preparation",
        source_space_id="corporate",
        target_space_id="corporate",
        interaction_type="reporting_preparation",
        channel_type="internal_workflow",
        direction="self_loop",
        routine_types_that_may_use_this_channel=("corporate_quarterly_reporting",),
    )
    book.add_interaction(spec)
    fetched = book.get_interaction(spec.interaction_id)
    assert fetched.source_space_id == fetched.target_space_id == "corporate"
    assert fetched.direction == "self_loop"
    diag = book.list_between_spaces("corporate", "corporate")
    assert len(diag) == 1


def test_self_loop_investors_crowding_or_peer_pressure():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:investors.crowding_or_peer_pressure",
            source_space_id="investors",
            target_space_id="investors",
            interaction_type="crowding_or_peer_pressure",
            channel_type="market_visibility",
            direction="self_loop",
        )
    )
    diag = book.list_between_spaces("investors", "investors")
    assert len(diag) == 1


def test_self_loop_information_analyst_revision_chain():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:information.analyst_revision_chain",
            source_space_id="information",
            target_space_id="information",
            interaction_type="analyst_revision_chain",
            channel_type="public_broadcast",
            direction="self_loop",
        )
    )
    diag = book.list_between_spaces("information", "information")
    assert len(diag) == 1


def test_tensor_view_includes_diagonal_for_self_loops():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:corporate.self_loop",
            source_space_id="corporate",
            target_space_id="corporate",
            channel_type="internal_workflow",
            direction="self_loop",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:corporate.cross_to_information",
            source_space_id="corporate",
            target_space_id="information",
            channel_type="scheduled_filing",
        )
    )
    tensor = book.build_space_interaction_tensor()
    # Diagonal cell is present.
    assert "corporate" in tensor["corporate"]
    assert "information" in tensor["corporate"]
    assert tensor["corporate"]["corporate"]["internal_workflow"] == [
        "interaction:corporate.self_loop"
    ]


# ---------------------------------------------------------------------------
# Channel multiplicity
# ---------------------------------------------------------------------------


def test_one_pair_can_have_multiple_channels():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:investors.engagement_letter",
            source_space_id="investors",
            target_space_id="corporate",
            interaction_type="engagement",
            channel_type="private_communication",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:investors.agm_vote",
            source_space_id="investors",
            target_space_id="corporate",
            interaction_type="agm_vote",
            channel_type="formal_governance",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:investors.public_disclosure",
            source_space_id="investors",
            target_space_id="corporate",
            interaction_type="activist_disclosure",
            channel_type="public_broadcast",
        )
    )
    cell = book.list_between_spaces("investors", "corporate")
    assert len(cell) == 3
    matrix = book.build_space_interaction_matrix()
    cell_view = matrix["investors"]["corporate"]
    assert cell_view["count"] == 3
    assert cell_view["enabled_count"] == 3
    assert cell_view["channel_types"] == [
        "formal_governance",
        "private_communication",
        "public_broadcast",
    ]


# ---------------------------------------------------------------------------
# Tensor view shape S × S × C
# ---------------------------------------------------------------------------


def test_tensor_view_shape_s_x_s_x_c():
    book = InteractionBook()
    _seed_typical_topology(book)
    tensor = book.build_space_interaction_tensor()
    # Top-level keys = source spaces present.
    assert set(tensor.keys()) == {"corporate", "banking", "investors", "policy"}
    # Sources -> targets -> channels -> interaction_id list.
    assert set(tensor["corporate"].keys()) == {"information"}
    assert set(tensor["corporate"]["information"].keys()) == {"scheduled_filing"}
    assert tensor["corporate"]["information"]["scheduled_filing"] == [
        "interaction:corporate.earnings_to_information",
        "interaction:corporate.guidance_to_information",
    ]
    # Banking row has one cell, one channel.
    assert tensor["banking"]["corporate"]["private_communication"] == [
        "interaction:banking.review_to_corporate"
    ]


def test_tensor_view_excludes_disabled_by_default():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:enabled_x",
            source_space_id="corporate",
            target_space_id="information",
            channel_type="scheduled_filing",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:disabled_y",
            source_space_id="corporate",
            target_space_id="information",
            channel_type="scheduled_filing",
            enabled=False,
        )
    )
    tensor = book.build_space_interaction_tensor()
    assert tensor["corporate"]["information"]["scheduled_filing"] == [
        "interaction:enabled_x"
    ]
    tensor_all = book.build_space_interaction_tensor(include_disabled=True)
    assert tensor_all["corporate"]["information"]["scheduled_filing"] == [
        "interaction:disabled_y",
        "interaction:enabled_x",
    ]


def test_tensor_view_is_deterministic():
    """Two calls return equal nested dicts with sorted keys + ids."""
    book = InteractionBook()
    _seed_typical_topology(book)
    a = book.build_space_interaction_tensor()
    b = book.build_space_interaction_tensor()
    assert a == b
    # Sorted check at every level.
    for src in a:
        assert list(a[src].keys()) == sorted(a[src].keys())
        for tgt in a[src]:
            assert list(a[src][tgt].keys()) == sorted(a[src][tgt].keys())
            for chan, ids in a[src][tgt].items():
                assert ids == sorted(ids)


# ---------------------------------------------------------------------------
# Matrix view
# ---------------------------------------------------------------------------


def test_matrix_view_has_count_and_channel_types():
    book = InteractionBook()
    _seed_typical_topology(book)
    matrix = book.build_space_interaction_matrix()
    cell = matrix["corporate"]["information"]
    assert cell["count"] == 2
    assert cell["enabled_count"] == 2
    assert cell["channel_types"] == ["scheduled_filing"]
    assert cell["interaction_ids"] == [
        "interaction:corporate.earnings_to_information",
        "interaction:corporate.guidance_to_information",
    ]


def test_matrix_view_count_vs_enabled_count_with_disabled():
    book = InteractionBook()
    book.add_interaction(
        _spec(
            interaction_id="interaction:e1",
            source_space_id="corporate",
            target_space_id="information",
            channel_type="scheduled_filing",
        )
    )
    book.add_interaction(
        _spec(
            interaction_id="interaction:d1",
            source_space_id="corporate",
            target_space_id="information",
            channel_type="scheduled_filing",
            enabled=False,
        )
    )
    matrix_default = book.build_space_interaction_matrix()
    cell_default = matrix_default["corporate"]["information"]
    # Default excludes disabled: count == enabled_count == 1.
    assert cell_default["count"] == 1
    assert cell_default["enabled_count"] == 1

    matrix_all = book.build_space_interaction_matrix(include_disabled=True)
    cell_all = matrix_all["corporate"]["information"]
    assert cell_all["count"] == 2
    assert cell_all["enabled_count"] == 1


def test_matrix_view_is_deterministic():
    book = InteractionBook()
    _seed_typical_topology(book)
    a = book.build_space_interaction_matrix()
    b = book.build_space_interaction_matrix()
    assert a == b
    for src in a:
        assert list(a[src].keys()) == sorted(a[src].keys())
        for tgt in a[src]:
            assert a[src][tgt]["interaction_ids"] == sorted(
                a[src][tgt]["interaction_ids"]
            )
            assert a[src][tgt]["channel_types"] == sorted(
                a[src][tgt]["channel_types"]
            )


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_and_sorted():
    book = InteractionBook()
    _seed_typical_topology(book)
    snap_a = book.snapshot()
    snap_b = book.snapshot()
    assert snap_a == snap_b
    assert snap_a["interaction_count"] == 5
    assert snap_a["enabled_count"] == 5
    ids = [i["interaction_id"] for i in snap_a["interactions"]]
    assert ids == sorted(ids)


def test_snapshot_counts_disabled_separately():
    book = InteractionBook()
    book.add_interaction(_spec(interaction_id="interaction:e", enabled=True))
    book.add_interaction(_spec(interaction_id="interaction:d", enabled=False))
    snap = book.snapshot()
    assert snap["interaction_count"] == 2
    assert snap["enabled_count"] == 1


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_add_interaction_writes_ledger_record_when_ledger_present():
    ledger = Ledger()
    clock = Clock(current_date=date(2026, 1, 1))
    book = InteractionBook(ledger=ledger, clock=clock)
    spec = _spec()
    book.add_interaction(spec)
    records = ledger.filter(event_type="interaction_added")
    assert len(records) == 1
    rec = records[0]
    assert rec.object_id == spec.interaction_id
    assert rec.source == spec.source_space_id
    assert rec.target == spec.target_space_id
    assert rec.payload["interaction_type"] == spec.interaction_type
    assert rec.payload["channel_type"] == spec.channel_type


def test_add_interaction_without_ledger_does_not_raise():
    book = InteractionBook()  # no ledger
    book.add_interaction(_spec())
    # No assertion needed — it just must not raise.


def test_record_type_interaction_added_exists():
    assert RecordType.INTERACTION_ADDED.value == "interaction_added"


# ---------------------------------------------------------------------------
# Kernel wiring + no-mutation guarantee
# ---------------------------------------------------------------------------


def test_kernel_exposes_interactions_book():
    kernel = _kernel()
    assert isinstance(kernel.interactions, InteractionBook)
    # Wired with the kernel's ledger and clock.
    assert kernel.interactions.ledger is kernel.ledger
    assert kernel.interactions.clock is kernel.clock


def test_kernel_add_interaction_emits_to_kernel_ledger():
    kernel = _kernel()
    kernel.interactions.add_interaction(_spec())
    records = kernel.ledger.filter(event_type="interaction_added")
    assert len(records) == 1


def test_interaction_book_does_not_mutate_other_kernel_books():
    """
    Adding interactions, building tensor / matrix views, and walking
    snapshot must not mutate any other source-of-truth book or any
    space's identity-level state.
    """
    kernel = _kernel()

    # Seed unrelated books with one entry each so snapshot equality
    # is meaningful.
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-01-01", "exchange")

    ownership_before = kernel.ownership.snapshot()
    contracts_before = kernel.contracts.snapshot()
    prices_before = kernel.prices.snapshot()
    constraints_before = kernel.constraints.snapshot()
    signals_before = kernel.signals.snapshot()
    valuations_before = kernel.valuations.snapshot()
    institutions_before = kernel.institutions.snapshot()
    external_processes_before = kernel.external_processes.snapshot()
    relationships_before = kernel.relationships.snapshot()

    # Add a few interactions and exercise every read API.
    _seed_typical_topology(kernel.interactions)
    kernel.interactions.list_interactions()
    kernel.interactions.list_by_source_space("corporate")
    kernel.interactions.list_by_target_space("corporate")
    kernel.interactions.list_between_spaces("corporate", "information")
    kernel.interactions.list_by_type("earnings_disclosure")
    kernel.interactions.list_by_channel("scheduled_filing")
    kernel.interactions.list_for_routine_type("bank_review")
    kernel.interactions.build_space_interaction_tensor()
    kernel.interactions.build_space_interaction_matrix()
    kernel.interactions.snapshot()

    # Unrelated books are unchanged.
    assert kernel.ownership.snapshot() == ownership_before
    assert kernel.contracts.snapshot() == contracts_before
    assert kernel.prices.snapshot() == prices_before
    assert kernel.constraints.snapshot() == constraints_before
    assert kernel.signals.snapshot() == signals_before
    assert kernel.valuations.snapshot() == valuations_before
    assert kernel.institutions.snapshot() == institutions_before
    assert kernel.external_processes.snapshot() == external_processes_before
    assert kernel.relationships.snapshot() == relationships_before
