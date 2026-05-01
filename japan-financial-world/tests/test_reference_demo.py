"""
Tests for the FWE Reference Demo (``examples/reference_world/``).

The demo script lives outside the ``world/`` and ``spaces/`` packages
and is loaded here via ``importlib`` because ``examples/`` is not a
Python package. The tests verify that the demo runs end-to-end and
produces the expected ledger trace, without exercising any new
behavior beyond what v0 + v1 already provide.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


_DEMO_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "reference_world"
    / "run_reference_loop.py"
)


def _load_demo_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fwe_reference_demo_run", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# The demo runs and returns a populated kernel + summary
# ---------------------------------------------------------------------------


def test_demo_script_runs_and_returns_kernel():
    demo = _load_demo_module()
    kernel, summary = demo.run()
    assert kernel is not None
    assert summary is not None
    assert summary.setup_record_count > 0
    assert len(kernel.ledger.records) > summary.setup_record_count


def test_demo_populates_eight_spaces():
    """All eight v0 domain spaces are registered and populated."""
    demo = _load_demo_module()
    kernel, _ = demo.run()
    counts = {
        r.event_type: sum(
            1 for x in kernel.ledger.records if x.event_type == r.event_type
        )
        for r in kernel.ledger.records
    }
    # Every per-space identity-level state record type must appear at
    # least once.
    for state_type in (
        "firm_state_added",
        "bank_state_added",
        "investor_state_added",
        "market_state_added",
        "property_market_state_added",
        "information_source_state_added",
        "policy_authority_state_added",
        "external_factor_state_added",
    ):
        assert state_type in counts, f"missing space population: {state_type}"


def test_demo_entity_counts_match_catalog():
    """The catalog declares 5 firms, 2 banks, 3 investors, etc."""
    demo = _load_demo_module()
    kernel, _ = demo.run()
    by_type: dict[str, int] = {}
    for r in kernel.ledger.records:
        by_type[r.event_type] = by_type.get(r.event_type, 0) + 1
    assert by_type["firm_state_added"] == 5
    assert by_type["bank_state_added"] == 2
    assert by_type["investor_state_added"] == 3
    assert by_type["market_state_added"] == 1
    assert by_type["property_market_state_added"] == 1
    assert by_type["information_source_state_added"] == 1
    assert by_type["policy_authority_state_added"] == 1
    assert by_type["external_factor_state_added"] == 2


# ---------------------------------------------------------------------------
# All seven loop record types appear in the ledger
# ---------------------------------------------------------------------------


def test_demo_emits_all_seven_loop_record_types():
    demo = _load_demo_module()
    kernel, _ = demo.run()
    actual = {r.event_type for r in kernel.ledger.records}
    expected = {
        "external_observation_added",
        "signal_added",
        "valuation_added",
        "valuation_compared",
        "institution_action_recorded",
        "event_published",
        "event_delivered",
    }
    missing = expected - actual
    assert missing == set(), f"loop record types missing: {missing}"


def test_demo_signal_added_appears_twice():
    """Step 2 (observation -> signal) and step 6 (action -> signal)."""
    demo = _load_demo_module()
    kernel, _ = demo.run()
    signal_records = kernel.ledger.filter(event_type="signal_added")
    assert len(signal_records) == 2


def test_demo_event_delivered_to_two_targets():
    """Banking + Investors each receive exactly one delivery on day 2."""
    demo = _load_demo_module()
    kernel, summary = demo.run()
    assert summary.delivery_targets == ("banking", "investors")
    delivered = kernel.ledger.filter(event_type="event_delivered")
    targets = {r.target for r in delivered}
    assert targets == {"banking", "investors"}
    assert len(delivered) == 2


# ---------------------------------------------------------------------------
# Causal-graph closure: parent_record_ids + cross-references
# ---------------------------------------------------------------------------


def test_demo_action_links_to_valuation_and_compared():
    """
    The institutional action record must list both the valuation_added
    and valuation_compared ledger record_ids in its parent_record_ids.
    """
    demo = _load_demo_module()
    kernel, _ = demo.run()
    action_records = kernel.ledger.filter(
        event_type="institution_action_recorded"
    )
    assert len(action_records) == 1
    valuation_added_ids = {
        r.record_id
        for r in kernel.ledger.filter(event_type="valuation_added")
    }
    valuation_compared_ids = {
        r.record_id
        for r in kernel.ledger.filter(event_type="valuation_compared")
    }

    # The runner records the action via InstitutionBook, which writes
    # the parent ids onto the InstitutionalActionRecord. The ledger
    # record's metadata carries the same parent_record_ids tuple, but
    # we read it via the institution book to be unambiguous.
    actions = list(kernel.institutions.all_actions())
    assert len(actions) == 1
    parents = set(actions[0].parent_record_ids)
    assert parents & valuation_added_ids
    assert parents & valuation_compared_ids


def test_demo_followup_signal_referenced_in_action_output_refs():
    demo = _load_demo_module()
    kernel, _ = demo.run()
    actions = list(kernel.institutions.all_actions())
    signals = list(kernel.signals.all_signals())
    followup_ids = {
        s.signal_id
        for s in signals
        if s.signal_id.startswith("signal:reference_followup_")
    }
    assert len(actions) == 1
    action_outputs = set(actions[0].output_refs)
    assert action_outputs & followup_ids


# ---------------------------------------------------------------------------
# No-mutation: prices and ownership are unchanged after the loop
# ---------------------------------------------------------------------------


def test_demo_loop_does_not_mutate_prices_or_ownership():
    """
    The reference loop writes only to external_processes, signals,
    valuations, institutions, ledger, and event_bus. Prices and
    ownership are seeded during setup but the loop itself does not
    change them.
    """
    demo = _load_demo_module()
    kernel, _ = demo.run()
    # Seeded subject's price was 95.0; loop should not have changed it.
    latest = kernel.prices.get_latest_price(
        "firm:reference_manufacturer_a"
    )
    assert latest is not None
    assert latest.price == 95.0
    # Ownership totals match the seeded portfolios.
    pension_a_position = kernel.ownership.get_position(
        "investor:reference_pension_a", "firm:reference_manufacturer_a"
    )
    assert pension_a_position is not None
    assert pension_a_position.quantity == 1000


# ---------------------------------------------------------------------------
# Entity catalog uses neutral identifiers only
# ---------------------------------------------------------------------------


def test_demo_uses_only_reference_identifiers():
    """
    The demo must not introduce any non-neutral identifiers. Every
    state-record object_id should start with a synthetic
    reference / institution / source prefix.
    """
    demo = _load_demo_module()
    kernel, _ = demo.run()
    forbidden = {
        "toyota",
        "mufg",
        "smbc",
        "mizuho",
        "boj",
        "fsa",
        "jpx",
        "gpif",
        "tse",
    }
    for record in kernel.ledger.records:
        if record.object_id is None:
            continue
        lowered = record.object_id.lower()
        for token in forbidden:
            assert token not in lowered, (
                f"forbidden token {token!r} found in object_id "
                f"{record.object_id!r}"
            )
