"""
Tests for v1.10.2 PortfolioCompanyDialogueRecord + DialogueBook.

Covers field validation, immutability, ``add_dialogue`` deduplication,
unknown lookup, every list / filter method, deterministic snapshots,
ledger emission with the new
``RecordType.PORTFOLIO_COMPANY_DIALOGUE_RECORDED``, kernel wiring of
the new ``DialogueBook``, the no-mutation guarantee against every
other v0/v1 source-of-truth book in the kernel, and the v1.10.2 scope
discipline that the record carries dialogue *metadata only* and
never a transcript / content / notes / attendees field.

Identifier and tag strings used in this test suite are
jurisdiction-neutral and synthetic; no Japan-specific institution
name, regulator, code, or threshold appears anywhere in the test
body.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from datetime import date

import pytest

from world.clock import Clock
from world.engagement import (
    DialogueBook,
    DuplicateDialogueError,
    PortfolioCompanyDialogueRecord,
    UnknownDialogueError,
)
from world.kernel import WorldKernel
from world.ledger import Ledger, RecordType
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dialogue(
    *,
    dialogue_id: str = "dialogue:reference_pension_a:reference_manufacturer_a:2026Q1:001",
    initiator_id: str = "investor:reference_pension_a",
    counterparty_id: str = "firm:reference_manufacturer_a",
    initiator_type: str = "investor",
    counterparty_type: str = "firm",
    as_of_date: str = "2026-02-15",
    dialogue_type: str = "private_meeting",
    status: str = "logged",
    outcome_label: str = "acknowledged",
    next_step_label: str = "continue_monitoring",
    visibility: str = "internal_only",
    theme_ids: tuple[str, ...] = (),
    related_signal_ids: tuple[str, ...] = (),
    related_valuation_ids: tuple[str, ...] = (),
    related_pressure_signal_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> PortfolioCompanyDialogueRecord:
    return PortfolioCompanyDialogueRecord(
        dialogue_id=dialogue_id,
        initiator_id=initiator_id,
        counterparty_id=counterparty_id,
        initiator_type=initiator_type,
        counterparty_type=counterparty_type,
        as_of_date=as_of_date,
        dialogue_type=dialogue_type,
        status=status,
        outcome_label=outcome_label,
        next_step_label=next_step_label,
        visibility=visibility,
        theme_ids=theme_ids,
        related_signal_ids=related_signal_ids,
        related_valuation_ids=related_valuation_ids,
        related_pressure_signal_ids=related_pressure_signal_ids,
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
# PortfolioCompanyDialogueRecord — field validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"dialogue_id": ""},
        {"initiator_id": ""},
        {"counterparty_id": ""},
        {"initiator_type": ""},
        {"counterparty_type": ""},
        {"as_of_date": ""},
        {"dialogue_type": ""},
        {"status": ""},
        {"outcome_label": ""},
        {"next_step_label": ""},
        {"visibility": ""},
    ],
)
def test_dialogue_rejects_empty_required_strings(kwargs):
    with pytest.raises(ValueError):
        _dialogue(**kwargs)


@pytest.mark.parametrize(
    "tuple_field",
    [
        "theme_ids",
        "related_signal_ids",
        "related_valuation_ids",
        "related_pressure_signal_ids",
    ],
)
def test_dialogue_rejects_empty_strings_in_tuple_fields(tuple_field):
    bad = {tuple_field: ("valid", "")}
    with pytest.raises(ValueError):
        _dialogue(**bad)


def test_dialogue_coerces_as_of_date_to_iso_string():
    d = _dialogue(as_of_date=date(2026, 2, 15))
    assert d.as_of_date == "2026-02-15"


def test_dialogue_rejects_non_date_as_of_date():
    with pytest.raises((TypeError, ValueError)):
        _dialogue(as_of_date=12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# PortfolioCompanyDialogueRecord — immutability & round-trip
# ---------------------------------------------------------------------------


def test_dialogue_is_frozen():
    d = _dialogue()
    with pytest.raises(Exception):
        d.dialogue_id = "tampered"  # type: ignore[misc]


def test_dialogue_to_dict_round_trips_fields():
    d = _dialogue(
        theme_ids=(
            "theme:reference_pension_a:capital_allocation:2026Q1",
        ),
        related_signal_ids=("signal:reference_signal_a",),
        related_valuation_ids=("valuation:reference_demo_001",),
        related_pressure_signal_ids=(
            "signal:reference_firm_pressure_001",
        ),
        metadata={"note": "synthetic"},
    )
    out = d.to_dict()
    assert out["dialogue_id"] == d.dialogue_id
    assert out["initiator_id"] == d.initiator_id
    assert out["counterparty_id"] == d.counterparty_id
    assert out["initiator_type"] == d.initiator_type
    assert out["counterparty_type"] == d.counterparty_type
    assert out["as_of_date"] == d.as_of_date
    assert out["dialogue_type"] == d.dialogue_type
    assert out["status"] == d.status
    assert out["outcome_label"] == d.outcome_label
    assert out["next_step_label"] == d.next_step_label
    assert out["visibility"] == d.visibility
    assert out["theme_ids"] == [
        "theme:reference_pension_a:capital_allocation:2026Q1"
    ]
    assert out["related_signal_ids"] == ["signal:reference_signal_a"]
    assert out["related_valuation_ids"] == ["valuation:reference_demo_001"]
    assert out["related_pressure_signal_ids"] == [
        "signal:reference_firm_pressure_001"
    ]
    assert out["metadata"] == {"note": "synthetic"}


def test_dialogue_metadata_is_independent_copy():
    """Mutating the input metadata after construction must not leak in."""
    src = {"note": "synthetic"}
    d = _dialogue(metadata=src)
    src["note"] = "tampered"
    assert d.metadata["note"] == "synthetic"


# ---------------------------------------------------------------------------
# Anti-fields — no transcript / content / notes / attendees fields
# ---------------------------------------------------------------------------


def test_dialogue_record_has_no_transcript_or_content_field():
    """
    v1.10.2 record must store metadata only — never verbatim or
    paraphrased dialogue contents.
    """
    field_names = {f.name for f in dataclass_fields(
        PortfolioCompanyDialogueRecord
    )}
    forbidden = {
        "transcript",
        "content",
        "contents",
        "notes",
        "minutes",
        "attendees",
        "attendee_list",
        "verbatim",
        "paraphrase",
        "paraphrased",
        "body",
    }
    leaked = field_names & forbidden
    assert not leaked, (
        f"v1.10.2 dialogue record must not carry verbatim/paraphrased "
        f"dialogue content fields; found: {sorted(leaked)}"
    )


# ---------------------------------------------------------------------------
# DialogueBook — add / get / dedup / unknown
# ---------------------------------------------------------------------------


def test_add_and_get_dialogue():
    book = DialogueBook()
    d = _dialogue()
    book.add_dialogue(d)
    assert book.get_dialogue(d.dialogue_id) is d


def test_get_dialogue_unknown_raises():
    book = DialogueBook()
    with pytest.raises(UnknownDialogueError):
        book.get_dialogue("does-not-exist")


def test_unknown_dialogue_error_is_keyerror():
    """``UnknownDialogueError`` should also be a ``KeyError``."""
    err = UnknownDialogueError("missing")
    assert isinstance(err, KeyError)


def test_duplicate_dialogue_id_rejected():
    book = DialogueBook()
    book.add_dialogue(_dialogue(dialogue_id="dialogue:dup"))
    with pytest.raises(DuplicateDialogueError):
        book.add_dialogue(_dialogue(dialogue_id="dialogue:dup"))


def test_add_dialogue_returns_record():
    book = DialogueBook()
    d = _dialogue()
    returned = book.add_dialogue(d)
    assert returned is d


# ---------------------------------------------------------------------------
# Listings & filters
# ---------------------------------------------------------------------------


def test_list_dialogues_returns_all_in_insertion_order():
    book = DialogueBook()
    a = _dialogue(dialogue_id="dialogue:a")
    b = _dialogue(dialogue_id="dialogue:b")
    c = _dialogue(dialogue_id="dialogue:c")
    book.add_dialogue(a)
    book.add_dialogue(b)
    book.add_dialogue(c)
    listed = book.list_dialogues()
    assert tuple(d.dialogue_id for d in listed) == (
        "dialogue:a",
        "dialogue:b",
        "dialogue:c",
    )


def test_list_dialogues_empty_book():
    assert DialogueBook().list_dialogues() == ()


def test_list_by_initiator():
    book = DialogueBook()
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:1",
            initiator_id="investor:reference_pension_a",
        )
    )
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:2",
            initiator_id="investor:reference_pension_b",
        )
    )
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:3",
            initiator_id="investor:reference_pension_a",
        )
    )
    matched = book.list_by_initiator("investor:reference_pension_a")
    assert tuple(d.dialogue_id for d in matched) == (
        "dialogue:1",
        "dialogue:3",
    )


def test_list_by_initiator_no_match():
    book = DialogueBook()
    book.add_dialogue(_dialogue(initiator_id="investor:a"))
    assert book.list_by_initiator("investor:other") == ()


def test_list_by_counterparty():
    book = DialogueBook()
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:m",
            counterparty_id="firm:reference_manufacturer_a",
        )
    )
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:r",
            counterparty_id="firm:reference_retailer_a",
        )
    )
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:m2",
            counterparty_id="firm:reference_manufacturer_a",
        )
    )
    matched = book.list_by_counterparty("firm:reference_manufacturer_a")
    assert tuple(d.dialogue_id for d in matched) == (
        "dialogue:m",
        "dialogue:m2",
    )


def test_list_by_theme_includes_when_theme_id_present():
    book = DialogueBook()
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:cap",
            theme_ids=("theme:cap", "theme:gov"),
        )
    )
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:gov_only",
            theme_ids=("theme:gov",),
        )
    )
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:none",
            theme_ids=(),
        )
    )
    cap = book.list_by_theme("theme:cap")
    gov = book.list_by_theme("theme:gov")
    miss = book.list_by_theme("theme:missing")
    assert tuple(d.dialogue_id for d in cap) == ("dialogue:cap",)
    assert sorted(d.dialogue_id for d in gov) == [
        "dialogue:cap",
        "dialogue:gov_only",
    ]
    assert miss == ()


def test_list_by_status():
    book = DialogueBook()
    book.add_dialogue(_dialogue(dialogue_id="dialogue:logged", status="logged"))
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:awaiting", status="awaiting_response")
    )
    book.add_dialogue(_dialogue(dialogue_id="dialogue:closed", status="closed"))
    assert tuple(d.dialogue_id for d in book.list_by_status("logged")) == (
        "dialogue:logged",
    )
    assert tuple(
        d.dialogue_id for d in book.list_by_status("awaiting_response")
    ) == ("dialogue:awaiting",)
    assert tuple(d.dialogue_id for d in book.list_by_status("closed")) == (
        "dialogue:closed",
    )


def test_list_by_dialogue_type():
    book = DialogueBook()
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:meet", dialogue_type="private_meeting")
    )
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:letter", dialogue_type="private_letter")
    )
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:meet2", dialogue_type="private_meeting")
    )
    meets = book.list_by_dialogue_type("private_meeting")
    letters = book.list_by_dialogue_type("private_letter")
    assert tuple(d.dialogue_id for d in meets) == (
        "dialogue:meet",
        "dialogue:meet2",
    )
    assert tuple(d.dialogue_id for d in letters) == ("dialogue:letter",)


def test_list_by_date_filters_exactly():
    book = DialogueBook()
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:feb", as_of_date="2026-02-15")
    )
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:mar", as_of_date="2026-03-15")
    )
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:feb2", as_of_date="2026-02-15")
    )
    feb = book.list_by_date("2026-02-15")
    mar = book.list_by_date("2026-03-15")
    miss = book.list_by_date("2026-04-15")
    assert tuple(d.dialogue_id for d in feb) == (
        "dialogue:feb",
        "dialogue:feb2",
    )
    assert tuple(d.dialogue_id for d in mar) == ("dialogue:mar",)
    assert miss == ()


def test_list_by_date_accepts_date_object():
    book = DialogueBook()
    book.add_dialogue(
        _dialogue(dialogue_id="dialogue:feb", as_of_date="2026-02-15")
    )
    matched = book.list_by_date(date(2026, 2, 15))
    assert tuple(d.dialogue_id for d in matched) == ("dialogue:feb",)


# ---------------------------------------------------------------------------
# Plain-id cross-references — no validation against any other book
# ---------------------------------------------------------------------------


def test_dialogue_can_reference_unresolved_theme_signal_valuation_pressure_ids():
    """
    Cross-references are stored as data and never validated against
    StewardshipBook / SignalBook / ValuationBook / pressure-signal
    sources, mirroring the v0/v1 cross-reference rule.
    """
    book = DialogueBook()
    d = _dialogue(
        theme_ids=("theme:not-in-stewardship-book",),
        related_signal_ids=("signal:not-in-signal-book",),
        related_valuation_ids=("valuation:not-in-valuation-book",),
        related_pressure_signal_ids=("signal:not-in-pressure-source",),
    )
    book.add_dialogue(d)
    assert book.get_dialogue(d.dialogue_id) is d


# ---------------------------------------------------------------------------
# Snapshot determinism
# ---------------------------------------------------------------------------


def test_snapshot_is_deterministic_and_sorted():
    book = DialogueBook()
    book.add_dialogue(_dialogue(dialogue_id="dialogue:z"))
    book.add_dialogue(_dialogue(dialogue_id="dialogue:a"))
    book.add_dialogue(_dialogue(dialogue_id="dialogue:m"))

    snap1 = book.snapshot()
    snap2 = book.snapshot()
    assert snap1 == snap2
    assert snap1["dialogue_count"] == 3
    assert [d["dialogue_id"] for d in snap1["dialogues"]] == [
        "dialogue:a",
        "dialogue:m",
        "dialogue:z",
    ]


def test_snapshot_empty_book():
    snap = DialogueBook().snapshot()
    assert snap == {"dialogue_count": 0, "dialogues": []}


# ---------------------------------------------------------------------------
# Ledger emission
# ---------------------------------------------------------------------------


def test_record_type_exists():
    """The new RecordType must be registered on the enum."""
    assert (
        RecordType("portfolio_company_dialogue_recorded")
        is RecordType.PORTFOLIO_COMPANY_DIALOGUE_RECORDED
    )
    assert (
        RecordType.PORTFOLIO_COMPANY_DIALOGUE_RECORDED.value
        == "portfolio_company_dialogue_recorded"
    )


def test_add_dialogue_writes_exactly_one_ledger_record():
    ledger = Ledger()
    book = DialogueBook(ledger=ledger)
    book.add_dialogue(_dialogue(dialogue_id="dialogue:emit"))
    records = ledger.filter(event_type="portfolio_company_dialogue_recorded")
    assert len(records) == 1
    record = records[0]
    assert (
        record.record_type
        is RecordType.PORTFOLIO_COMPANY_DIALOGUE_RECORDED
    )
    assert record.object_id == "dialogue:emit"
    assert record.source == "investor:reference_pension_a"
    assert record.target == "firm:reference_manufacturer_a"
    assert record.space_id == "engagement"
    assert record.agent_id == "investor:reference_pension_a"
    assert record.visibility == "internal_only"


def test_add_dialogue_ledger_payload_carries_full_field_set():
    ledger = Ledger()
    book = DialogueBook(ledger=ledger)
    book.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:payload",
            theme_ids=("theme:cap",),
            related_signal_ids=("signal:reference_signal_a",),
            related_valuation_ids=("valuation:reference_demo_001",),
            related_pressure_signal_ids=(
                "signal:reference_firm_pressure_001",
            ),
        )
    )
    records = ledger.filter(event_type="portfolio_company_dialogue_recorded")
    payload = records[-1].payload
    assert payload["dialogue_id"] == "dialogue:payload"
    assert payload["initiator_id"] == "investor:reference_pension_a"
    assert payload["counterparty_id"] == "firm:reference_manufacturer_a"
    assert payload["initiator_type"] == "investor"
    assert payload["counterparty_type"] == "firm"
    assert payload["as_of_date"] == "2026-02-15"
    assert payload["dialogue_type"] == "private_meeting"
    assert payload["status"] == "logged"
    assert payload["outcome_label"] == "acknowledged"
    assert payload["next_step_label"] == "continue_monitoring"
    assert payload["visibility"] == "internal_only"
    assert tuple(payload["theme_ids"]) == ("theme:cap",)
    assert tuple(payload["related_signal_ids"]) == (
        "signal:reference_signal_a",
    )
    assert tuple(payload["related_valuation_ids"]) == (
        "valuation:reference_demo_001",
    )
    assert tuple(payload["related_pressure_signal_ids"]) == (
        "signal:reference_firm_pressure_001",
    )


def test_add_dialogue_ledger_payload_carries_no_transcript_or_content_keys():
    """The ledger payload mirrors the record fields — never adds a
    transcript / content / notes / attendees key."""
    ledger = Ledger()
    book = DialogueBook(ledger=ledger)
    book.add_dialogue(_dialogue(dialogue_id="dialogue:audit"))
    records = ledger.filter(event_type="portfolio_company_dialogue_recorded")
    payload_keys = set(records[-1].payload.keys())
    forbidden = {
        "transcript",
        "content",
        "contents",
        "notes",
        "minutes",
        "attendees",
        "verbatim",
        "paraphrase",
        "paraphrased",
        "body",
    }
    leaked = payload_keys & forbidden
    assert not leaked, (
        f"v1.10.2 ledger payload must not carry verbatim/paraphrased "
        f"dialogue content keys; found: {sorted(leaked)}"
    )


def test_add_dialogue_without_ledger_does_not_raise():
    """A book without a ledger must still accept adds (it is just silent)."""
    book = DialogueBook()
    book.add_dialogue(_dialogue())


def test_duplicate_add_emits_no_extra_ledger_record():
    ledger = Ledger()
    book = DialogueBook(ledger=ledger)
    book.add_dialogue(_dialogue(dialogue_id="dialogue:once"))
    with pytest.raises(DuplicateDialogueError):
        book.add_dialogue(_dialogue(dialogue_id="dialogue:once"))
    records = ledger.filter(event_type="portfolio_company_dialogue_recorded")
    assert len(records) == 1


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_engagement_book():
    kernel = _kernel()
    assert isinstance(kernel.engagement, DialogueBook)
    assert kernel.engagement.ledger is kernel.ledger
    assert kernel.engagement.clock is kernel.clock


def test_kernel_add_dialogue_emits_to_kernel_ledger():
    kernel = _kernel()
    kernel.engagement.add_dialogue(_dialogue())
    records = kernel.ledger.filter(
        event_type="portfolio_company_dialogue_recorded"
    )
    assert len(records) == 1


def test_kernel_engagement_simulation_date_uses_clock():
    """
    With the kernel's clock current_date set, the ledger record's
    simulation_date should reflect that date (the book's ``_now``
    helper reads the clock).
    """
    kernel = _kernel()
    kernel.engagement.add_dialogue(_dialogue(dialogue_id="dialogue:wired"))
    records = kernel.ledger.filter(
        event_type="portfolio_company_dialogue_recorded"
    )
    assert records[-1].simulation_date == "2026-01-01"


# ---------------------------------------------------------------------------
# No-mutation guarantee against every other source-of-truth book
# ---------------------------------------------------------------------------


def test_engagement_book_does_not_mutate_other_kernel_books():
    """
    Adding dialogues, filtering, and building snapshots must not
    mutate any other source-of-truth book — including the v1.10.1
    StewardshipBook.
    """
    kernel = _kernel()

    # Seed unrelated books with one entry each so snapshot equality
    # is meaningful.
    kernel.ownership.add_position("agent:alice", "asset:cash", 100)
    kernel.prices.set_price("asset:cash", 1.0, "2026-01-01", "exchange")

    snaps_before = {
        "ownership": kernel.ownership.snapshot(),
        "contracts": kernel.contracts.snapshot(),
        "prices": kernel.prices.snapshot(),
        "constraints": kernel.constraints.snapshot(),
        "signals": kernel.signals.snapshot(),
        "valuations": kernel.valuations.snapshot(),
        "institutions": kernel.institutions.snapshot(),
        "external_processes": kernel.external_processes.snapshot(),
        "relationships": kernel.relationships.snapshot(),
        "interactions": kernel.interactions.snapshot(),
        "routines": kernel.routines.snapshot(),
        "attention": kernel.attention.snapshot(),
        "variables": kernel.variables.snapshot(),
        "exposures": kernel.exposures.snapshot(),
        "stewardship": kernel.stewardship.snapshot(),
    }

    # Exercise every engagement-layer write + read.
    kernel.engagement.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:k:a",
            theme_ids=("theme:cap",),
            related_signal_ids=("signal:reference_signal_a",),
            related_valuation_ids=("valuation:reference_demo_001",),
            related_pressure_signal_ids=(
                "signal:reference_firm_pressure_001",
            ),
        )
    )
    kernel.engagement.add_dialogue(
        _dialogue(
            dialogue_id="dialogue:k:b",
            initiator_id="investor:reference_pension_b",
            counterparty_id="firm:reference_retailer_a",
            initiator_type="asset_owner",
            counterparty_type="firm",
            dialogue_type="private_letter",
            status="awaiting_response",
            outcome_label="partial_response",
            next_step_label="follow_up_meeting",
            visibility="public",
            as_of_date="2026-03-15",
        )
    )
    kernel.engagement.list_dialogues()
    kernel.engagement.list_by_initiator("investor:reference_pension_a")
    kernel.engagement.list_by_counterparty("firm:reference_manufacturer_a")
    kernel.engagement.list_by_theme("theme:cap")
    kernel.engagement.list_by_status("logged")
    kernel.engagement.list_by_dialogue_type("private_meeting")
    kernel.engagement.list_by_date("2026-02-15")
    kernel.engagement.snapshot()

    assert kernel.ownership.snapshot() == snaps_before["ownership"]
    assert kernel.contracts.snapshot() == snaps_before["contracts"]
    assert kernel.prices.snapshot() == snaps_before["prices"]
    assert kernel.constraints.snapshot() == snaps_before["constraints"]
    assert kernel.signals.snapshot() == snaps_before["signals"]
    assert kernel.valuations.snapshot() == snaps_before["valuations"]
    assert kernel.institutions.snapshot() == snaps_before["institutions"]
    assert (
        kernel.external_processes.snapshot()
        == snaps_before["external_processes"]
    )
    assert kernel.relationships.snapshot() == snaps_before["relationships"]
    assert kernel.interactions.snapshot() == snaps_before["interactions"]
    assert kernel.routines.snapshot() == snaps_before["routines"]
    assert kernel.attention.snapshot() == snaps_before["attention"]
    assert kernel.variables.snapshot() == snaps_before["variables"]
    assert kernel.exposures.snapshot() == snaps_before["exposures"]
    assert kernel.stewardship.snapshot() == snaps_before["stewardship"]


# ---------------------------------------------------------------------------
# No-action invariant
# ---------------------------------------------------------------------------


def test_engagement_emits_only_dialogue_recorded_records():
    """
    A bare ``add_dialogue`` call must emit exactly one ledger record
    of type ``PORTFOLIO_COMPANY_DIALOGUE_RECORDED`` and no other
    record type. The book is dialogue-metadata storage only — it
    must not incidentally emit any signal, valuation, contract,
    ownership, interaction, escalation, voting, trading, or
    corporate-response record.
    """
    ledger = Ledger()
    book = DialogueBook(ledger=ledger)
    book.add_dialogue(_dialogue(dialogue_id="dialogue:audit"))
    assert len(ledger.records) == 1
    record = ledger.records[0]
    assert (
        record.record_type
        is RecordType.PORTFOLIO_COMPANY_DIALOGUE_RECORDED
    )


def test_engagement_does_not_emit_voting_trading_or_escalation_records():
    """
    Independent assertion that v1.10.2 has not silently introduced any
    voting, trading, escalation, or corporate-response record type.
    The forbidden record-type names are the v1.0–v1.9 set known to
    represent action-class behavior; if any of these appears in the
    ledger after a bare ``add_dialogue``, v1.10.2 has crossed its
    no-behavior boundary.
    """
    forbidden_event_types = {
        "order_submitted",
        "price_updated",
        "contract_created",
        "contract_status_updated",
        "contract_covenant_breached",
        "ownership_position_added",
        "ownership_transferred",
        "institution_action_recorded",
    }
    ledger = Ledger()
    book = DialogueBook(ledger=ledger)
    book.add_dialogue(_dialogue(dialogue_id="dialogue:no_action"))
    seen = {r.event_type for r in ledger.records}
    assert seen.isdisjoint(forbidden_event_types), (
        f"v1.10.2 add_dialogue must not emit any action-class record; "
        f"saw forbidden event types: {sorted(seen & forbidden_event_types)}"
    )


# ---------------------------------------------------------------------------
# Jurisdiction-neutral identifier scan
#
# This test reads its own source file and confirms that every test
# string is jurisdiction-neutral. The forbidden token list mirrors
# ``world/experiment.py::_FORBIDDEN_TOKENS``; this duplication is
# intentional so that the test fails locally even when the
# experiment-config scan does not run.
# ---------------------------------------------------------------------------


_FORBIDDEN_TOKENS = (
    "toyota", "mufg", "smbc", "mizuho", "boj", "fsa", "jpx",
    "gpif", "tse", "nikkei", "topix", "sony", "jgb", "nyse",
)


def test_test_file_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    text = Path(__file__).read_text(encoding="utf-8").lower()
    table_start = text.find("_forbidden_tokens = (")
    table_end = text.find(")", table_start) + 1
    if table_start != -1 and table_end > 0:
        text = text[:table_start] + text[table_end:]

    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"jurisdiction-specific token {token!r} appeared in test file"
        )


def test_engagement_module_contains_no_jurisdiction_specific_identifiers():
    import re
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parent.parent / "world" / "engagement.py"
    )
    text = module_path.read_text(encoding="utf-8").lower()
    for token in _FORBIDDEN_TOKENS:
        pattern = rf"\b{re.escape(token)}\b"
        assert re.search(pattern, text) is None, (
            f"jurisdiction-specific token {token!r} appeared in "
            f"world/engagement.py"
        )
