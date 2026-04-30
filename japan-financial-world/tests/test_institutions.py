from datetime import date

import pytest

from world.clock import Clock
from world.institutions import (
    DuplicateInstitutionalActionError,
    DuplicateInstitutionProfileError,
    DuplicateInstrumentProfileError,
    DuplicateMandateError,
    InstitutionBook,
    InstitutionProfile,
    InstitutionalActionRecord,
    MandateRecord,
    PolicyInstrumentProfile,
    UnknownInstitutionalActionError,
    UnknownInstitutionProfileError,
)
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


def _profile(
    institution_id: str = "institution:reference_central_bank",
    *,
    institution_type: str = "central_bank",
    jurisdiction_label: str = "neutral_jurisdiction",
    mandate_summary: str = "price stability and financial stability",
    authority_scope: tuple[str, ...] = ("monetary_policy",),
    status: str = "active",
    metadata: dict | None = None,
) -> InstitutionProfile:
    return InstitutionProfile(
        institution_id=institution_id,
        institution_type=institution_type,
        jurisdiction_label=jurisdiction_label,
        mandate_summary=mandate_summary,
        authority_scope=authority_scope,
        status=status,
        metadata=metadata or {},
    )


def _mandate(
    mandate_id: str = "mandate:price_stability",
    *,
    institution_id: str = "institution:reference_central_bank",
    mandate_type: str = "price_stability",
    description: str = "maintain low and stable inflation",
    priority: int = 1,
    status: str = "active",
    metadata: dict | None = None,
) -> MandateRecord:
    return MandateRecord(
        mandate_id=mandate_id,
        institution_id=institution_id,
        mandate_type=mandate_type,
        description=description,
        priority=priority,
        status=status,
        metadata=metadata or {},
    )


def _instrument(
    instrument_id: str = "instrument:reference_policy_rate",
    *,
    institution_id: str = "institution:reference_central_bank",
    instrument_type: str = "policy_rate",
    target_domain: str = "short_rate",
    status: str = "active",
    metadata: dict | None = None,
) -> PolicyInstrumentProfile:
    return PolicyInstrumentProfile(
        instrument_id=instrument_id,
        institution_id=institution_id,
        instrument_type=instrument_type,
        target_domain=target_domain,
        status=status,
        metadata=metadata or {},
    )


def _action(
    action_id: str = "action:reference_announcement_001",
    *,
    institution_id: str = "institution:reference_central_bank",
    action_type: str = "policy_announcement",
    as_of_date: str = "2026-01-15",
    phase_id: str | None = "post_close",
    input_refs: tuple[str, ...] = (),
    output_refs: tuple[str, ...] = (),
    target_ids: tuple[str, ...] = (),
    instrument_ids: tuple[str, ...] = (),
    payload: dict | None = None,
    parent_record_ids: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> InstitutionalActionRecord:
    return InstitutionalActionRecord(
        action_id=action_id,
        institution_id=institution_id,
        action_type=action_type,
        as_of_date=as_of_date,
        phase_id=phase_id,
        input_refs=input_refs,
        output_refs=output_refs,
        target_ids=target_ids,
        instrument_ids=instrument_ids,
        payload=payload or {},
        parent_record_ids=parent_record_ids,
        metadata=metadata or {},
    )


def _book(with_ledger: bool = False) -> InstitutionBook:
    if with_ledger:
        return InstitutionBook(
            ledger=Ledger(),
            clock=Clock(current_date=date(2026, 1, 1)),
        )
    return InstitutionBook()


# ---------------------------------------------------------------------------
# InstitutionProfile dataclass
# ---------------------------------------------------------------------------


def test_institution_profile_carries_required_fields():
    p = _profile()
    assert p.institution_id == "institution:reference_central_bank"
    assert p.institution_type == "central_bank"
    assert p.jurisdiction_label == "neutral_jurisdiction"
    assert p.authority_scope == ("monetary_policy",)
    assert p.status == "active"


def test_institution_profile_rejects_missing_required():
    with pytest.raises(ValueError):
        InstitutionProfile(institution_id="", institution_type="central_bank")
    with pytest.raises(ValueError):
        InstitutionProfile(institution_id="institution:x", institution_type="")


def test_institution_profile_is_immutable():
    p = _profile()
    with pytest.raises(Exception):
        p.status = "dissolved"  # type: ignore[misc]


def test_jurisdiction_label_is_label_only_not_calibration():
    """
    v1.3 jurisdiction_label is a free-form string. v1 uses neutral
    labels; v2 will populate it with real jurisdictions. The field
    must accept any string without coupling to calibration.
    """
    for label in (
        "neutral_jurisdiction",
        "reference_jurisdiction_a",
        "reference_jurisdiction_b",
        "any_free_form_label",
        "",  # also allowed; v1.3 does not validate
    ):
        p = InstitutionProfile(
            institution_id="institution:any",
            institution_type="any_type",
            jurisdiction_label=label,
        )
        assert p.jurisdiction_label == label


def test_institution_profile_to_dict_is_serializable():
    p = _profile(authority_scope=("monetary_policy", "lender_of_last_resort"))
    payload = p.to_dict()
    assert payload["authority_scope"] == [
        "monetary_policy",
        "lender_of_last_resort",
    ]


# ---------------------------------------------------------------------------
# MandateRecord dataclass
# ---------------------------------------------------------------------------


def test_mandate_record_carries_required_fields():
    m = _mandate()
    assert m.mandate_id == "mandate:price_stability"
    assert m.institution_id == "institution:reference_central_bank"
    assert m.mandate_type == "price_stability"
    assert m.priority == 1


def test_mandate_record_rejects_missing_required():
    with pytest.raises(ValueError):
        MandateRecord(mandate_id="", institution_id="i", mandate_type="t")
    with pytest.raises(ValueError):
        MandateRecord(mandate_id="m", institution_id="", mandate_type="t")
    with pytest.raises(ValueError):
        MandateRecord(mandate_id="m", institution_id="i", mandate_type="")


# ---------------------------------------------------------------------------
# PolicyInstrumentProfile dataclass
# ---------------------------------------------------------------------------


def test_instrument_profile_carries_required_fields():
    i = _instrument()
    assert i.instrument_id == "instrument:reference_policy_rate"
    assert i.institution_id == "institution:reference_central_bank"
    assert i.instrument_type == "policy_rate"
    assert i.target_domain == "short_rate"


def test_instrument_profile_rejects_missing_required():
    with pytest.raises(ValueError):
        PolicyInstrumentProfile(
            instrument_id="", institution_id="i", instrument_type="t"
        )
    with pytest.raises(ValueError):
        PolicyInstrumentProfile(
            instrument_id="i", institution_id="", instrument_type="t"
        )
    with pytest.raises(ValueError):
        PolicyInstrumentProfile(
            instrument_id="i", institution_id="i2", instrument_type=""
        )


# ---------------------------------------------------------------------------
# InstitutionalActionRecord dataclass
# ---------------------------------------------------------------------------


def test_action_record_carries_required_fields():
    a = _action(
        input_refs=("price:asset_a",),
        output_refs=("signal:announcement_a",),
        target_ids=("asset_a",),
        instrument_ids=("instrument:reference_policy_rate",),
        parent_record_ids=("rec_abc",),
    )
    assert a.action_id == "action:reference_announcement_001"
    assert a.input_refs == ("price:asset_a",)
    assert a.output_refs == ("signal:announcement_a",)
    assert a.target_ids == ("asset_a",)
    assert a.instrument_ids == ("instrument:reference_policy_rate",)
    assert a.parent_record_ids == ("rec_abc",)


def test_action_record_rejects_missing_required():
    with pytest.raises(ValueError):
        InstitutionalActionRecord(
            action_id="",
            institution_id="i",
            action_type="t",
            as_of_date="2026-01-01",
        )
    with pytest.raises(ValueError):
        InstitutionalActionRecord(
            action_id="a",
            institution_id="",
            action_type="t",
            as_of_date="2026-01-01",
        )
    with pytest.raises(ValueError):
        InstitutionalActionRecord(
            action_id="a",
            institution_id="i",
            action_type="",
            as_of_date="2026-01-01",
        )
    with pytest.raises(ValueError):
        InstitutionalActionRecord(
            action_id="a", institution_id="i", action_type="t", as_of_date=""
        )


def test_action_record_phase_id_is_optional():
    a = _action(phase_id=None)
    assert a.phase_id is None


def test_action_record_is_immutable():
    a = _action()
    with pytest.raises(Exception):
        a.action_type = "different"  # type: ignore[misc]


def test_action_record_default_collections_are_empty():
    a = InstitutionalActionRecord(
        action_id="a",
        institution_id="i",
        action_type="t",
        as_of_date="2026-01-01",
    )
    assert a.input_refs == ()
    assert a.output_refs == ()
    assert a.target_ids == ()
    assert a.instrument_ids == ()
    assert a.parent_record_ids == ()
    assert a.payload == {}
    assert a.metadata == {}


# ---------------------------------------------------------------------------
# InstitutionBook — institution profile CRUD
# ---------------------------------------------------------------------------


def test_add_and_get_institution_profile():
    book = _book()
    p = _profile()
    book.add_institution_profile(p)
    assert book.get_institution_profile(p.institution_id) is p


def test_get_institution_profile_raises_for_unknown():
    book = _book()
    with pytest.raises(UnknownInstitutionProfileError):
        book.get_institution_profile("institution:nope")


def test_duplicate_institution_profile_rejected():
    book = _book()
    book.add_institution_profile(_profile())
    with pytest.raises(DuplicateInstitutionProfileError):
        book.add_institution_profile(_profile())


def test_list_by_type_filters_correctly():
    book = _book()
    book.add_institution_profile(
        _profile(institution_id="institution:cb_a", institution_type="central_bank")
    )
    book.add_institution_profile(
        _profile(institution_id="institution:cb_b", institution_type="central_bank")
    )
    book.add_institution_profile(
        _profile(institution_id="institution:reg_a", institution_type="regulator")
    )

    central_banks = book.list_by_type("central_bank")
    regulators = book.list_by_type("regulator")

    assert {p.institution_id for p in central_banks} == {
        "institution:cb_a",
        "institution:cb_b",
    }
    assert {p.institution_id for p in regulators} == {"institution:reg_a"}


# ---------------------------------------------------------------------------
# InstitutionBook — mandate CRUD
# ---------------------------------------------------------------------------


def test_add_and_list_mandates_by_institution():
    book = _book()
    book.add_mandate(_mandate(mandate_id="mandate:price_stability"))
    book.add_mandate(_mandate(mandate_id="mandate:financial_stability"))
    book.add_mandate(
        _mandate(
            mandate_id="mandate:other",
            institution_id="institution:other",
        )
    )

    cb = book.list_mandates_by_institution("institution:reference_central_bank")
    other = book.list_mandates_by_institution("institution:other")
    none = book.list_mandates_by_institution("institution:nope")

    assert {m.mandate_id for m in cb} == {
        "mandate:price_stability",
        "mandate:financial_stability",
    }
    assert {m.mandate_id for m in other} == {"mandate:other"}
    assert none == ()


def test_duplicate_mandate_id_rejected():
    book = _book()
    book.add_mandate(_mandate())
    with pytest.raises(DuplicateMandateError):
        book.add_mandate(_mandate())


# ---------------------------------------------------------------------------
# InstitutionBook — instrument CRUD
# ---------------------------------------------------------------------------


def test_add_and_list_instruments_by_institution():
    book = _book()
    book.add_instrument_profile(_instrument(instrument_id="instrument:rate"))
    book.add_instrument_profile(_instrument(instrument_id="instrument:rrr"))
    book.add_instrument_profile(
        _instrument(
            instrument_id="instrument:capital_ratio",
            institution_id="institution:other",
        )
    )

    cb = book.list_instruments_by_institution("institution:reference_central_bank")
    other = book.list_instruments_by_institution("institution:other")

    assert {i.instrument_id for i in cb} == {"instrument:rate", "instrument:rrr"}
    assert {i.instrument_id for i in other} == {"instrument:capital_ratio"}


def test_duplicate_instrument_profile_rejected():
    book = _book()
    book.add_instrument_profile(_instrument())
    with pytest.raises(DuplicateInstrumentProfileError):
        book.add_instrument_profile(_instrument())


# ---------------------------------------------------------------------------
# InstitutionBook — action CRUD
# ---------------------------------------------------------------------------


def test_add_get_and_list_actions_by_institution():
    book = _book()
    book.add_action_record(_action(action_id="action:a"))
    book.add_action_record(_action(action_id="action:b"))
    book.add_action_record(
        _action(action_id="action:c", institution_id="institution:other")
    )

    cb = book.list_actions_by_institution("institution:reference_central_bank")
    other = book.list_actions_by_institution("institution:other")

    assert {a.action_id for a in cb} == {"action:a", "action:b"}
    assert {a.action_id for a in other} == {"action:c"}

    assert book.get_action_record("action:a").action_id == "action:a"


def test_get_action_record_raises_for_unknown():
    book = _book()
    with pytest.raises(UnknownInstitutionalActionError):
        book.get_action_record("action:nope")


def test_duplicate_action_id_rejected():
    book = _book()
    book.add_action_record(_action())
    with pytest.raises(DuplicateInstitutionalActionError):
        book.add_action_record(_action())


def test_action_record_preserves_input_output_refs_and_parents():
    book = _book()
    a = _action(
        input_refs=("price:p1", "valuation:v1"),
        output_refs=("signal:s1",),
        target_ids=("agent:a1",),
        instrument_ids=("instrument:i1",),
        parent_record_ids=("rec_parent_1", "rec_parent_2"),
        payload={"rationale": "reference"},
    )
    book.add_action_record(a)

    fetched = book.get_action_record("action:reference_announcement_001")
    assert fetched.input_refs == ("price:p1", "valuation:v1")
    assert fetched.output_refs == ("signal:s1",)
    assert fetched.target_ids == ("agent:a1",)
    assert fetched.instrument_ids == ("instrument:i1",)
    assert fetched.parent_record_ids == ("rec_parent_1", "rec_parent_2")
    assert fetched.payload == {"rationale": "reference"}


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def test_snapshot_lists_all_categories_sorted():
    book = _book()
    book.add_institution_profile(_profile(institution_id="institution:b"))
    book.add_institution_profile(_profile(institution_id="institution:a"))
    book.add_mandate(_mandate(mandate_id="mandate:b", institution_id="institution:a"))
    book.add_mandate(_mandate(mandate_id="mandate:a", institution_id="institution:a"))
    book.add_instrument_profile(
        _instrument(instrument_id="instrument:b", institution_id="institution:a")
    )
    book.add_instrument_profile(
        _instrument(instrument_id="instrument:a", institution_id="institution:a")
    )
    book.add_action_record(
        _action(action_id="action:b", institution_id="institution:a")
    )
    book.add_action_record(
        _action(action_id="action:a", institution_id="institution:a")
    )

    snap = book.snapshot()
    assert snap["institution_count"] == 2
    assert snap["mandate_count"] == 2
    assert snap["instrument_count"] == 2
    assert snap["action_count"] == 2
    assert [p["institution_id"] for p in snap["institutions"]] == [
        "institution:a",
        "institution:b",
    ]
    assert [m["mandate_id"] for m in snap["mandates"]] == [
        "mandate:a",
        "mandate:b",
    ]
    assert [i["instrument_id"] for i in snap["instruments"]] == [
        "instrument:a",
        "instrument:b",
    ]
    assert [a["action_id"] for a in snap["actions"]] == [
        "action:a",
        "action:b",
    ]


def test_snapshot_returns_empty_structure_for_empty_book():
    snap = InstitutionBook().snapshot()
    assert snap == {
        "institution_count": 0,
        "mandate_count": 0,
        "instrument_count": 0,
        "action_count": 0,
        "institutions": [],
        "mandates": [],
        "instruments": [],
        "actions": [],
    }


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_add_institution_profile_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_institution_profile(_profile())

    records = book.ledger.filter(event_type="institution_profile_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "institution:reference_central_bank"
    assert record.payload["institution_type"] == "central_bank"
    assert record.payload["jurisdiction_label"] == "neutral_jurisdiction"
    assert record.simulation_date == "2026-01-01"
    assert record.space_id == "institutions"


def test_add_mandate_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_mandate(_mandate())

    records = book.ledger.filter(event_type="institution_mandate_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "mandate:price_stability"
    assert record.target == "institution:reference_central_bank"
    assert record.payload["mandate_type"] == "price_stability"


def test_add_instrument_profile_records_to_ledger():
    book = _book(with_ledger=True)
    book.add_instrument_profile(_instrument())

    records = book.ledger.filter(event_type="institution_instrument_added")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "instrument:reference_policy_rate"
    assert record.target == "institution:reference_central_bank"
    assert record.payload["target_domain"] == "short_rate"


def test_add_action_record_emits_ledger_with_parent_record_ids():
    book = _book(with_ledger=True)
    book.add_action_record(
        _action(
            input_refs=("price:p1",),
            output_refs=("signal:s1",),
            parent_record_ids=("rec_parent_1", "rec_parent_2"),
        )
    )

    records = book.ledger.filter(event_type="institution_action_recorded")
    assert len(records) == 1
    record = records[0]
    assert record.object_id == "action:reference_announcement_001"
    assert record.source == "institution:reference_central_bank"
    assert record.simulation_date == "2026-01-15"
    # parent_record_ids on the action record are preserved on the
    # ledger record for causal-graph reconstruction.
    assert record.parent_record_ids == ("rec_parent_1", "rec_parent_2")
    # Input/output refs are preserved in payload. Ledger payloads
    # are frozen, so list-typed values come back as tuples.
    assert tuple(record.payload["input_refs"]) == ("price:p1",)
    assert tuple(record.payload["output_refs"]) == ("signal:s1",)


def test_add_does_not_record_when_no_ledger():
    book = InstitutionBook()
    book.add_institution_profile(_profile())
    book.add_action_record(_action())
    assert (
        book.get_institution_profile("institution:reference_central_bank")
        is not None
    )


# ---------------------------------------------------------------------------
# Action contract: no mutation of other books or spaces
# ---------------------------------------------------------------------------


def test_action_record_does_not_mutate_other_books():
    """
    Recording an action must not touch any source-of-truth book. The
    action record may *reference* other records via input_refs /
    output_refs / target_ids / parent_record_ids, but it never drives
    a mutation of those records itself. Consumers of action records
    are responsible for any actual world changes.
    """
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.ownership.add_position("agent:alice", "asset:x", 100)
    kernel.prices.set_price("asset:x", 50.0, "2026-01-01", "exchange")

    ownership_before = kernel.ownership.snapshot()
    contracts_before = kernel.contracts.snapshot()
    prices_before = kernel.prices.snapshot()
    constraints_before = kernel.constraints.snapshot()
    signals_before = kernel.signals.snapshot()
    valuations_before = kernel.valuations.snapshot()

    # Record an action that *references* prices, signals, ownership,
    # and instruments — but the action record itself only writes to
    # InstitutionBook (and the ledger).
    kernel.institutions.add_institution_profile(_profile())
    kernel.institutions.add_instrument_profile(_instrument())
    kernel.institutions.add_mandate(_mandate())
    kernel.institutions.add_action_record(
        _action(
            input_refs=("price:asset:x", "ownership:agent:alice"),
            output_refs=("signal:hypothetical",),
            target_ids=("asset:x", "agent:alice"),
            instrument_ids=("instrument:reference_policy_rate",),
            parent_record_ids=("rec_some_parent",),
        )
    )

    # Every other book is byte-identical to its pre-action state.
    assert kernel.ownership.snapshot() == ownership_before
    assert kernel.contracts.snapshot() == contracts_before
    assert kernel.prices.snapshot() == prices_before
    assert kernel.constraints.snapshot() == constraints_before
    assert kernel.signals.snapshot() == signals_before
    assert kernel.valuations.snapshot() == valuations_before


# ---------------------------------------------------------------------------
# Kernel wiring
# ---------------------------------------------------------------------------


def test_kernel_exposes_institutions_with_default_wiring():
    kernel = WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )

    kernel.institutions.add_institution_profile(_profile())

    assert kernel.institutions.ledger is kernel.ledger
    assert kernel.institutions.clock is kernel.clock
    assert (
        len(kernel.ledger.filter(event_type="institution_profile_added")) == 1
    )
