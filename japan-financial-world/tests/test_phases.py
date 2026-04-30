import pytest

from world.phases import (
    IntradayPhaseSpec,
    PhaseSequence,
    UnknownPhaseError,
)


# ---------------------------------------------------------------------------
# IntradayPhaseSpec
# ---------------------------------------------------------------------------


def test_phase_spec_carries_required_fields():
    spec = IntradayPhaseSpec(
        phase_id="opening_auction", order=2, label="Opening auction"
    )
    assert spec.phase_id == "opening_auction"
    assert spec.order == 2
    assert spec.label == "Opening auction"
    assert spec.metadata == {}


def test_phase_spec_rejects_empty_phase_id():
    with pytest.raises(ValueError):
        IntradayPhaseSpec(phase_id="", order=0)


def test_phase_spec_to_dict_is_serializable():
    spec = IntradayPhaseSpec(
        phase_id="overnight",
        order=0,
        label="Overnight",
        metadata={"timezone_anchor": "utc"},
    )
    assert spec.to_dict() == {
        "phase_id": "overnight",
        "order": 0,
        "label": "Overnight",
        "metadata": {"timezone_anchor": "utc"},
    }


def test_phase_spec_is_immutable():
    spec = IntradayPhaseSpec(phase_id="overnight", order=0)
    with pytest.raises(Exception):
        spec.order = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PhaseSequence — default
# ---------------------------------------------------------------------------


def test_default_phase_order_is_deterministic():
    seq = PhaseSequence.default_phases()
    phase_ids = [p.phase_id for p in seq.list_phases()]
    assert phase_ids == [
        "overnight",
        "pre_open",
        "opening_auction",
        "continuous_session",
        "closing_auction",
        "post_close",
    ]


def test_default_phase_orders_are_strictly_increasing():
    seq = PhaseSequence.default_phases()
    orders = [p.order for p in seq.list_phases()]
    assert orders == sorted(orders)
    assert len(set(orders)) == len(orders)  # all distinct


def test_default_phases_have_human_readable_labels():
    seq = PhaseSequence.default_phases()
    for spec in seq.list_phases():
        assert spec.label  # non-empty


# ---------------------------------------------------------------------------
# PhaseSequence — navigation helpers
# ---------------------------------------------------------------------------


def test_get_phase_returns_spec_by_id():
    seq = PhaseSequence.default_phases()
    spec = seq.get_phase("opening_auction")
    assert spec.phase_id == "opening_auction"
    assert spec.order == 2


def test_get_phase_raises_for_unknown_id():
    seq = PhaseSequence.default_phases()
    with pytest.raises(UnknownPhaseError):
        seq.get_phase("phase:does_not_exist")


def test_next_phase_returns_following_spec():
    seq = PhaseSequence.default_phases()
    nxt = seq.next_phase("pre_open")
    assert nxt is not None
    assert nxt.phase_id == "opening_auction"


def test_next_phase_returns_none_at_last_phase():
    seq = PhaseSequence.default_phases()
    assert seq.next_phase("post_close") is None


def test_next_phase_raises_for_unknown_id():
    seq = PhaseSequence.default_phases()
    with pytest.raises(UnknownPhaseError):
        seq.next_phase("phase:does_not_exist")


def test_is_first_phase_detects_first():
    seq = PhaseSequence.default_phases()
    assert seq.is_first_phase("overnight") is True
    assert seq.is_first_phase("pre_open") is False
    assert seq.is_first_phase("post_close") is False


def test_is_last_phase_detects_last():
    seq = PhaseSequence.default_phases()
    assert seq.is_last_phase("post_close") is True
    assert seq.is_last_phase("closing_auction") is False
    assert seq.is_last_phase("overnight") is False


# ---------------------------------------------------------------------------
# PhaseSequence — empty + custom
# ---------------------------------------------------------------------------


def test_empty_sequence_first_and_last_are_false():
    seq = PhaseSequence(phases=())
    assert seq.is_first_phase("anything") is False
    assert seq.is_last_phase("anything") is False
    assert seq.list_phases() == ()


def test_custom_sequence_with_two_phases():
    seq = PhaseSequence(
        phases=(
            IntradayPhaseSpec(phase_id="phase_a", order=0, label="A"),
            IntradayPhaseSpec(phase_id="phase_b", order=1, label="B"),
        )
    )
    assert seq.is_first_phase("phase_a") is True
    assert seq.is_last_phase("phase_b") is True
    assert seq.next_phase("phase_a").phase_id == "phase_b"
    assert seq.next_phase("phase_b") is None


def test_sequence_rejects_duplicate_phase_ids():
    with pytest.raises(ValueError):
        PhaseSequence(
            phases=(
                IntradayPhaseSpec(phase_id="dup", order=0),
                IntradayPhaseSpec(phase_id="dup", order=1),
            )
        )


def test_sequence_to_dict_is_serializable():
    seq = PhaseSequence.default_phases()
    payload = seq.to_dict()
    assert payload["count"] == 6
    assert len(payload["phases"]) == 6
    assert payload["phases"][0]["phase_id"] == "overnight"
    assert payload["phases"][-1]["phase_id"] == "post_close"
