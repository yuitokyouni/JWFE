"""
FWE Reference Demo — runnable script.

Builds a small synthetic, jurisdiction-neutral demo world from
`entities.yaml`, walks the v1.6 reference loop end-to-end, advances
the clock past the next-tick delivery boundary, and prints a summary
of the resulting ledger trace.

This script uses ONLY existing v0 + v1 public APIs. It does not
extend, subclass, or monkey-patch any kernel component. It does not
implement new behavior. See ``docs/fwe_reference_demo_design.md``
for design rationale and ``examples/reference_world/expected_story.md``
for the per-step ledger narrative.

Run from the ``japan-financial-world/`` directory:

    python examples/reference_world/run_reference_loop.py
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping


# Make this script runnable from the ``japan-financial-world/``
# directory without needing PYTHONPATH set explicitly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


from spaces.banking.space import BankSpace
from spaces.banking.state import BankState
from spaces.corporate.space import CorporateSpace
from spaces.corporate.state import FirmState
from spaces.exchange.space import ExchangeSpace
from spaces.exchange.state import MarketState
from spaces.external.space import ExternalSpace
from spaces.external.state import ExternalFactorState
from spaces.information.space import InformationSpace
from spaces.information.state import InformationSourceState
from spaces.investors.space import InvestorSpace
from spaces.investors.state import InvestorState
from spaces.policy.space import PolicySpace
from spaces.policy.state import PolicyAuthorityState
from spaces.real_estate.space import RealEstateSpace
from spaces.real_estate.state import PropertyMarketState
from world.clock import Clock
from world.external_processes import ExternalFactorProcess
from world.institutions import InstitutionProfile
from world.kernel import WorldKernel
from world.ledger import Ledger
from world.loader import load_yaml_file_raw
from world.reference_loop import ReferenceLoopRunner
from world.registry import Registry
from world.scheduler import Scheduler
from world.state import State


_ENTITIES_FILE = Path(__file__).resolve().parent / "entities.yaml"


@dataclass
class DemoSummary:
    """Lightweight summary returned by ``run()`` for inspection."""

    setup_record_count: int
    loop_record_ids: dict[str, str]
    delivery_targets: tuple[str, ...]
    record_type_counts: dict[str, int]


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def _build_kernel() -> WorldKernel:
    return WorldKernel(
        registry=Registry(),
        clock=Clock(current_date=date(2026, 1, 1)),
        scheduler=Scheduler(),
        ledger=Ledger(),
        state=State(),
    )


def _register_eight_spaces(kernel: WorldKernel) -> dict[str, Any]:
    """
    Register all eight v0 spaces. Returns a mapping
    space_name -> space_instance for population in the next step.
    """
    spaces = {
        "corporate": CorporateSpace(),
        "banking": BankSpace(),
        "investors": InvestorSpace(),
        "exchange": ExchangeSpace(),
        "real_estate": RealEstateSpace(),
        "information": InformationSpace(),
        "policy": PolicySpace(),
        "external": ExternalSpace(),
    }
    for sp in spaces.values():
        kernel.register_space(sp)
    return spaces


def _populate_world(
    kernel: WorldKernel,
    spaces: dict[str, Any],
    catalog: Mapping[str, Any],
) -> None:
    """
    Add every entity in the catalog to its corresponding space and
    seed the supporting state (external process, institution profile,
    seed price, seed ownership).
    """
    for entry in catalog["firms"]:
        spaces["corporate"].add_firm_state(
            FirmState(
                firm_id=entry["id"],
                sector=entry.get("sector", "unspecified"),
                tier=entry.get("tier", "unspecified"),
                metadata=entry.get("metadata", {}),
            )
        )

    for entry in catalog["banks"]:
        spaces["banking"].add_bank_state(
            BankState(
                bank_id=entry["id"],
                bank_type=entry.get("bank_type", "unspecified"),
                tier=entry.get("tier", "unspecified"),
            )
        )

    for entry in catalog["investors"]:
        spaces["investors"].add_investor_state(
            InvestorState(
                investor_id=entry["id"],
                investor_type=entry.get("investor_type", "unspecified"),
                tier=entry.get("tier", "unspecified"),
            )
        )

    for entry in catalog["exchanges"]:
        spaces["exchange"].add_market_state(
            MarketState(
                market_id=entry["id"],
                market_type=entry.get("market_type", "unspecified"),
                tier=entry.get("tier", "unspecified"),
            )
        )

    for entry in catalog["real_estate_markets"]:
        spaces["real_estate"].add_property_market_state(
            PropertyMarketState(
                property_market_id=entry["id"],
                region=entry.get("region", "unspecified"),
                property_type=entry.get("property_type", "unspecified"),
                tier=entry.get("tier", "unspecified"),
            )
        )

    for entry in catalog["information_sources"]:
        spaces["information"].add_source_state(
            InformationSourceState(
                source_id=entry["id"],
                source_type=entry.get("source_type", "unspecified"),
                tier=entry.get("tier", "unspecified"),
            )
        )

    for entry in catalog["policy_authorities"]:
        spaces["policy"].add_authority_state(
            PolicyAuthorityState(
                authority_id=entry["id"],
                authority_type=entry.get("authority_type", "unspecified"),
                tier=entry.get("tier", "unspecified"),
            )
        )

    for entry in catalog["external_factors"]:
        # Identity-level state for the factor.
        spaces["external"].add_factor_state(
            ExternalFactorState(
                factor_id=entry["id"],
                factor_type=entry.get("factor_type", "unspecified"),
                unit=entry.get("unit", "unspecified"),
            )
        )
        # Process spec lives in the v1.4 ExternalProcessBook.
        kernel.external_processes.add_process(
            ExternalFactorProcess(
                process_id=entry["process_id"],
                factor_id=entry["id"],
                factor_type=entry.get("factor_type", "unspecified"),
                process_type=entry.get("process_type", "constant"),
                unit=entry.get("unit", "unspecified"),
                base_value=entry.get("base_value"),
            )
        )

    for entry in catalog["institutions"]:
        kernel.institutions.add_institution_profile(
            InstitutionProfile(
                institution_id=entry["id"],
                institution_type=entry.get("institution_type", "unspecified"),
                jurisdiction_label=entry.get(
                    "jurisdiction_label", "neutral_jurisdiction"
                ),
                mandate_summary=entry.get("mandate_summary", ""),
            )
        )

    for entry in catalog["seed_prices"]:
        kernel.prices.set_price(
            entry["asset_id"],
            float(entry["price"]),
            entry["as_of_date"],
            entry.get("source", "exchange"),
        )

    for entry in catalog["seed_ownership"]:
        kernel.ownership.add_position(
            entry["owner_id"],
            entry["asset_id"],
            int(entry["quantity"]),
        )


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def run() -> tuple[WorldKernel, DemoSummary]:
    """
    Build the demo kernel, run the seven-step reference loop, advance
    two ticks, and return the kernel + a summary for inspection.
    """
    catalog = load_yaml_file_raw(_ENTITIES_FILE)

    kernel = _build_kernel()
    spaces = _register_eight_spaces(kernel)
    _populate_world(kernel, spaces, catalog)

    setup_record_count = len(kernel.ledger.records)

    runner = ReferenceLoopRunner(kernel=kernel)
    loop_cfg = catalog["loop"]

    # Step 1: external observation.
    obs = runner.record_external_observation(
        process_id=catalog["external_factors"][0]["process_id"],
        as_of_date=loop_cfg["as_of_date"],
        phase_id=loop_cfg["observation_phase_id"],
        source_id="source:reference_news_outlet",
    )

    # Step 2: signal from observation.
    signal_obs = runner.emit_signal_from_observation(
        observation=obs,
        signal_id=loop_cfg["signal_id_observation"],
        signal_type="macro_indicator",
        source_id="source:reference_news_outlet",
        subject_id=loop_cfg["observed_factor"],
    )

    # Step 3: valuation referencing the signal.
    valuation = runner.record_valuation_from_signal(
        signal=signal_obs,
        valuation_id=loop_cfg["valuation_id"],
        subject_id=loop_cfg["valuation_subject_id"],
        valuer_id=loop_cfg["valuer_id"],
        valuation_type="equity",
        purpose="reference_research",
        method=loop_cfg["valuation_method"],
        as_of_date=loop_cfg["as_of_date"],
        estimated_value=float(loop_cfg["valuation_estimated_value"]),
        currency=loop_cfg["valuation_currency"],
        confidence=0.7,
    )

    # Step 4: comparator → ValuationGap.
    gap = runner.compare_valuation_to_price(valuation.valuation_id)

    # Step 5: institutional action.
    action = runner.record_institutional_action(
        action_id=loop_cfg["action_id"],
        institution_id=loop_cfg["action_institution_id"],
        action_type=loop_cfg["action_type"],
        as_of_date=loop_cfg["as_of_date"],
        valuation=valuation,
        gap=gap,
        phase_id=loop_cfg["action_phase_id"],
        planned_output_signal_id=loop_cfg["signal_id_followup"],
    )

    # Step 6: follow-up signal.
    signal_followup = runner.emit_signal_from_action(
        action=action,
        signal_id=loop_cfg["signal_id_followup"],
        signal_type="reference_macro_statement",
        source_id=loop_cfg["action_institution_id"],
        subject_id=loop_cfg["valuation_subject_id"],
    )

    # Step 7: publish a WorldEvent that carries the follow-up signal.
    runner.publish_signal_event(
        signal=signal_followup,
        event_id=loop_cfg["event_id"],
        source_space=loop_cfg["event_source_space"],
        target_spaces=tuple(loop_cfg["event_target_spaces"]),
    )

    # Day 1: same-tick → no delivery.
    kernel.run(days=1)
    delivered_after_day_1 = kernel.ledger.filter(event_type="event_delivered")
    assert len(delivered_after_day_1) == 0, (
        "next-tick rule violated: delivery happened on the publish day"
    )

    # Day 2: next-tick boundary crossed → both targets receive.
    kernel.run(days=1)
    delivered = kernel.ledger.filter(event_type="event_delivered")
    delivery_targets = tuple(sorted({r.target for r in delivered}))

    record_type_counts = dict(
        Counter(r.event_type for r in kernel.ledger.records)
    )

    # Pull the seven loop record ids for the summary.
    def _last(event_type: str, *, object_id: str | None = None) -> str:
        recs = kernel.ledger.filter(event_type=event_type)
        if object_id is not None:
            recs = [r for r in recs if r.object_id == object_id]
        return recs[-1].record_id

    loop_record_ids = {
        "step_1_external_observation_added": _last(
            "external_observation_added"
        ),
        "step_2_signal_added_observation": _last(
            "signal_added", object_id=signal_obs.signal_id
        ),
        "step_3_valuation_added": _last("valuation_added"),
        "step_4_valuation_compared": _last("valuation_compared"),
        "step_5_institution_action_recorded": _last(
            "institution_action_recorded"
        ),
        "step_6_signal_added_followup": _last(
            "signal_added", object_id=signal_followup.signal_id
        ),
        "step_7_event_published": _last("event_published"),
    }

    summary = DemoSummary(
        setup_record_count=setup_record_count,
        loop_record_ids=loop_record_ids,
        delivery_targets=delivery_targets,
        record_type_counts=record_type_counts,
    )
    return kernel, summary


def _print_summary(summary: DemoSummary) -> None:
    print(
        f"[setup] ledger has {summary.setup_record_count} baseline records"
    )
    for name, record_id in summary.loop_record_ids.items():
        print(f"[loop ] {name:<40s}: {record_id}")
    print(
        f"[tick ] day-2 delivery targets: "
        f"{', '.join(summary.delivery_targets) or '(none)'}"
    )
    total = sum(summary.record_type_counts.values())
    print(f"[ledger] total records: {total}; record types:")
    for event_type in sorted(summary.record_type_counts):
        print(
            f"  {event_type:<32s}: "
            f"{summary.record_type_counts[event_type]}"
        )


def main() -> int:
    _, summary = run()
    _print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
