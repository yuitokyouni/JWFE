"""
v1.19.2 — CLI run exporter.

This module is the **CLI exporter** for the v1.19 local-run-
bridge sequence. It composes:

- the v1.17.2 living-reference-world regime driver
  (``examples.reference_world.regime_comparison_report``) — the
  read-only path that already runs the v1.16 closed loop on a
  fresh kernel for a chosen regime preset; and
- the v1.19.1 export infrastructure (``world.run_export``) —
  the immutable :class:`world.run_export.RunExportBundle`
  dataclass + its deterministic JSON writer.

It produces a deterministic ``RunExportBundle`` JSON artifact
under a caller-supplied ``--out`` path. The same CLI arguments
on the same codebase produce a byte-identical JSON file
regardless of the destination path or the wall-clock at the
time of invocation. The dataclass carries no wall-clock
timestamp field, the ``--out`` path is **not** embedded in the
bundle, and no ``$USER`` / ``$HOSTNAME`` / ``os.getlogin()``
is captured.

Hard-boundary recap (binding at v1.19.2):

- v1.19.2 is **CLI export only**. It does not implement the
  ``monthly_reference``, ``scenario_monthly``,
  ``daily_display_only``, or ``future_daily_full_simulation``
  run profiles — those are designed-but-not-executable. The CLI
  rejects them with a stderr message and a non-zero exit code.
- v1.19.2 does not yet wire scenario application into the CLI.
  Only ``--scenario none_baseline`` is executable; every other
  v1.18.4 scenario selector label is rejected at the CLI
  boundary.
- The module imports no web-framework / browser-automation
  names (the v1.19.0 design names them explicitly under
  ``§5.2`` as a v1.19.4+ deferred affordance, never the v1.19.2
  default path). There is no backend, no browser-to-Python
  execution, no HTTP server. Pinned by a module-text scan in
  ``tests/test_run_export_cli.py``.
- The exporter does not mutate the kernel's ``PriceBook`` or
  any other source-of-truth book. Pinned by a snapshot trip
  wire on a separately seeded kernel.
- The default-fixture ``living_world_digest`` of a separately
  seeded default sweep is unchanged after running the CLI.

Usage::

    cd japan-financial-world
    python -m examples.reference_world.export_run_bundle \\
        --profile quarterly_default \\
        --regime constrained \\
        --scenario none_baseline \\
        --out /tmp/fwe_run_bundle.json

The default scenario value is ``none_baseline``. ``--indent``
defaults to 2; pass ``--quiet`` to suppress the success line.

The CLI is also runnable as a script via
``python examples/reference_world/export_run_bundle.py …`` —
the module's ``__main__`` guard re-routes the bare-script
invocation through :func:`main`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# --- v1.19.2 boundary list ---------------------------------------------------
#
# These constants are referenced by ``tests/test_run_export_cli.py`` so a
# drift in either copy fails loudly. v1.19.2 keeps them as module-level
# tuples (not enums) because they are CLI-facing label strings, not
# closed-set vocabularies (those live in ``world.run_export``).
SUPPORTED_PROFILE: str = "quarterly_default"
# v1.19.3.1 reconciliation: extended ``EXECUTABLE_PROFILES`` to
# include ``monthly_reference``. The earlier v1.19.2 ship listed
# ``monthly_reference`` under ``DESIGNED_BUT_NOT_EXECUTABLE_PROFILES``;
# v1.19.3 landed the runtime profile in ``world.reference_living_world``,
# and v1.19.3.1 is the explicit follow-up commit that wires it
# into the CLI. The other three profile labels remain
# designed-but-not-executable (no scenario application from the
# CLI; no display-only run; no daily full simulation).
EXECUTABLE_PROFILES: tuple[str, ...] = (
    "quarterly_default",
    "monthly_reference",
)
DESIGNED_BUT_NOT_EXECUTABLE_PROFILES: tuple[str, ...] = (
    "scenario_monthly",
    "daily_display_only",
    "future_daily_full_simulation",
)
SUPPORTED_REGIMES: tuple[str, ...] = (
    "constructive",
    "mixed",
    "constrained",
    "tightening",
)
SUPPORTED_SCENARIO: str = "none_baseline"

# v1.19.2 caps the ledger excerpt at 20 records. The CLI reads
# the FIRST 20 records of the kernel ledger (``records[:N]``) so
# the excerpt covers the start-of-run setup chain — the most
# stable region of the ledger across regime presets — rather
# than the trailing review-phase records, which differ per
# regime by design.
LEDGER_EXCERPT_LIMIT: int = 20

# Fields on ``LedgerRecord.to_dict()`` that drift across
# wall-clock invocations and must NEVER appear in the bundle's
# ``ledger_excerpt``. ``record_id`` is hash-derived from
# ``timestamp``; ``timestamp`` is wall-clock. Mirrors the v1.9.2
# canonical-form rule in ``examples/reference_world/living_world_replay.py``.
_VOLATILE_LEDGER_RECORD_FIELDS: frozenset[str] = frozenset(
    {"record_id", "timestamp"}
)


# Module-level success-line template (deterministic — one line).
_SUCCESS_LINE_TEMPLATE: str = (
    "exported run bundle: {path} · profile={profile} · "
    "regime={regime} · digest={digest12}"
)


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="export_run_bundle",
        description=(
            "v1.19.2 CLI run exporter — writes a deterministic "
            "RunExportBundle JSON artifact for the quarterly_default "
            "living reference world."
        ),
    )
    parser.add_argument(
        "--profile",
        required=True,
        help=(
            "Run profile label. v1.19.2 executable: "
            "'quarterly_default'. Designed-but-not-executable: "
            + ", ".join(repr(p) for p in DESIGNED_BUT_NOT_EXECUTABLE_PROFILES)
            + "."
        ),
    )
    parser.add_argument(
        "--regime",
        required=True,
        help=(
            "Market regime preset. One of: "
            + ", ".join(SUPPORTED_REGIMES)
            + "."
        ),
    )
    parser.add_argument(
        "--scenario",
        default=SUPPORTED_SCENARIO,
        help=(
            "Scenario selector label. v1.19.2 executable: "
            "'none_baseline' (default). Other v1.18.4 selector "
            "labels exit non-zero."
        ),
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Output JSON path (the file is written verbatim; "
        "the path is NOT embedded in the bundle).",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="JSON indentation (default 2).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the success line on stdout.",
    )
    return parser


def _validate_profile(profile: str) -> None:
    """Reject any profile not in ``EXECUTABLE_PROFILES``.

    Designed-but-not-executable profiles get a specific message
    making the design intent visible; anything outside the
    closed v1.19.1 RUN_PROFILE_LABELS gets a generic rejection.
    """
    if profile in EXECUTABLE_PROFILES:
        return
    if profile in DESIGNED_BUT_NOT_EXECUTABLE_PROFILES:
        raise SystemExit(
            f"profile {profile!r} is designed but not "
            f"executable in v1.19.2"
        )
    raise SystemExit(
        f"profile {profile!r} is not a recognized run profile; "
        f"executable: " + ", ".join(repr(p) for p in EXECUTABLE_PROFILES)
        + "; designed-but-not-executable: "
        + ", ".join(repr(p) for p in DESIGNED_BUT_NOT_EXECUTABLE_PROFILES)
    )


def _validate_regime(regime: str) -> None:
    if regime in SUPPORTED_REGIMES:
        return
    raise SystemExit(
        f"regime {regime!r} is not a recognized v1.11.2 preset; "
        f"supported: " + ", ".join(SUPPORTED_REGIMES)
    )


def _validate_scenario(scenario: str) -> None:
    if scenario == SUPPORTED_SCENARIO:
        return
    raise SystemExit(
        f"scenario {scenario!r} is not yet wired into the "
        f"CLI in v1.19.2"
    )


# ---------------------------------------------------------------------------
# Bundle section builders
# ---------------------------------------------------------------------------


def _build_manifest(
    *, profile: str, regime: str, scenario: str, period_count: int
) -> dict[str, Any]:
    """Manifest section. No absolute paths, no wall-clock, no
    ``$USER`` / ``$HOSTNAME``."""
    return {
        "schema_version": "run_export_bundle.v1",
        "profile": profile,
        "regime": regime,
        "scenario": scenario,
        "period_count": period_count,
        "generated_at_policy_label": "stable_for_replay",
        "fwe_version_label": "v1.19.2",
    }


def _build_overview(
    *, regime: str, snapshot: Any
) -> dict[str, Any]:
    """Compact overview drawn from the v1.17.2 regime snapshot.

    Keys are intentionally label-only — the snapshot's tuples
    of label strings are summarised down to a few entries.
    """
    attention_labels = snapshot.attention_focus_labels
    pressure_labels = snapshot.indicative_market_pressure_labels
    intent_labels = snapshot.market_intent_direction_labels
    return {
        "active_regime": regime,
        "record_count": snapshot.record_count,
        "unresolved_refs_count": snapshot.unresolved_refs_count,
        "top_attention_focus_label": (
            attention_labels[0] if attention_labels else "unknown"
        ),
        "top_market_pressure_label": (
            pressure_labels[0] if pressure_labels else "unknown"
        ),
        "top_market_intent_direction_label": (
            intent_labels[0] if intent_labels else "unknown"
        ),
    }


def _build_timeline(*, snapshot: Any) -> dict[str, Any]:
    """Timeline section. Uses the v1.17 disclaimer string;
    records / events arrays are populated from the snapshot's
    deterministic event / causal annotation tuples."""
    return {
        "calendar": "quarterly",
        "display_path_kind": "indicative_pressure_path",
        "boundary_note": (
            "synthetic context only — no price formation, "
            "no forecast, no investment advice"
        ),
        "event_annotation_count": len(snapshot.event_annotations),
        "causal_annotation_count": len(snapshot.causal_annotations),
    }


def _build_scenario_trace(*, scenario: str) -> dict[str, Any]:
    """v1.19.2 only supports ``none_baseline``. Any other scenario
    is rejected at the CLI boundary, so this helper is only
    called with ``none_baseline``."""
    return {
        "selected_scenario_label": scenario,
        "summary": "no scenario applied",
    }


def _build_ledger_excerpt(*, kernel: Any) -> dict[str, Any]:
    """Bounded excerpt of the kernel's ledger. v1.19.2 walks the
    FIRST :data:`LEDGER_EXCERPT_LIMIT` records (``records[:N]``)
    so the excerpt covers the start-of-run setup chain — the
    most stable region of the ledger across regime presets.

    Volatile fields (``record_id`` / ``timestamp``) are stripped
    to keep the bundle byte-identical across wall-clock
    invocations. The deterministic ``simulation_date`` field is
    preserved.
    """
    records: list[dict[str, Any]] = []
    for rec in list(kernel.ledger.records)[:LEDGER_EXCERPT_LIMIT]:
        d = dict(rec.to_dict())
        for vol in _VOLATILE_LEDGER_RECORD_FIELDS:
            d.pop(vol, None)
        records.append(d)
    return {
        "records": records,
        "selection_window": "first_n",
        "limit": LEDGER_EXCERPT_LIMIT,
        "total_record_count": len(kernel.ledger.records),
    }


def _build_metadata(*, indent: int) -> dict[str, Any]:
    return {
        "export_module": "v1.19.2",
        "indent": indent,
    }


# v1.19.3.1 — information arrival summary builder for the
# ``monthly_reference`` profile. Reads only label fields from the
# kernel's append-only ``information_releases`` book; carries no
# real values, no real institutional names, no real dates beyond
# the synthetic month-end fixture produced by v1.19.3.
def _build_information_arrival_summary(*, kernel: Any) -> dict[str, Any]:
    """Compact summary of the information arrivals emitted under
    the ``monthly_reference`` profile.

    Output:

    - ``calendar_count``: number of registered calendars
      (``1`` for the default fixture).
    - ``scheduled_release_count``: total scheduled releases.
    - ``arrival_count``: total information arrivals across all
      months.
    - ``per_indicator_family``: mapping from
      :class:`IndicatorFamilyLabel` value to arrival count.
    - ``per_release_importance``: mapping from
      :class:`ReleaseImportanceLabel` value to arrival count.
    - ``per_arrival_status``: mapping from
      :class:`ArrivalStatusLabel` value to arrival count.

    No real value, no real date, no real institutional identifier.
    Mirrors the v1.19.0 / v1.19.3 jurisdiction-neutral discipline.
    """
    book = getattr(kernel, "information_releases", None)
    if book is None:
        return {
            "calendar_count": 0,
            "scheduled_release_count": 0,
            "arrival_count": 0,
            "per_indicator_family": {},
            "per_release_importance": {},
            "per_arrival_status": {},
        }
    arrivals = list(book.list_arrivals())
    by_family: dict[str, int] = {}
    by_importance: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for a in arrivals:
        by_family[a.indicator_family_label] = (
            by_family.get(a.indicator_family_label, 0) + 1
        )
        by_importance[a.release_importance_label] = (
            by_importance.get(a.release_importance_label, 0) + 1
        )
        by_status[a.arrival_status_label] = (
            by_status.get(a.arrival_status_label, 0) + 1
        )
    return {
        "calendar_count": len(book.list_calendars()),
        "scheduled_release_count": len(book.list_scheduled_releases()),
        "arrival_count": len(arrivals),
        # Sort the per-* mappings to keep the rendered JSON
        # byte-identical irrespective of arrival insertion order.
        "per_indicator_family": dict(sorted(by_family.items())),
        "per_release_importance": dict(sorted(by_importance.items())),
        "per_arrival_status": dict(sorted(by_status.items())),
    }


# ---------------------------------------------------------------------------
# Top-level CLI driver
# ---------------------------------------------------------------------------


def _build_bundle_for_quarterly_default(
    *, regime: str, scenario: str, indent: int
) -> tuple[Any, str]:
    """Run the v1.17.2 regime driver on a fresh kernel and build
    the bundle. Returns ``(bundle, digest)``."""
    # Local imports keep the module text free of any direct
    # ``from world.kernel`` / ``from world.ledger`` reference at
    # the top level — the CLI delegates kernel ownership to the
    # v1.17.2 driver, which is the documented read-only entry
    # point.
    from examples.reference_world.regime_comparison_report import (
        _DEFAULT_BANK_IDS,
        _DEFAULT_FIRM_IDS,
        _DEFAULT_INVESTOR_IDS,
        _DEFAULT_PERIOD_DATES,
        _seed_kernel,
        extract_regime_run_snapshot,
    )
    from world.reference_living_world import run_living_reference_world
    from world.run_export import build_run_export_bundle

    kernel = _seed_kernel()
    result = run_living_reference_world(
        kernel,
        firm_ids=_DEFAULT_FIRM_IDS,
        investor_ids=_DEFAULT_INVESTOR_IDS,
        bank_ids=_DEFAULT_BANK_IDS,
        period_dates=_DEFAULT_PERIOD_DATES,
        market_regime=regime,
    )
    snapshot = extract_regime_run_snapshot(
        regime_id=regime, kernel=kernel, result=result
    )

    period_count = len(_DEFAULT_PERIOD_DATES)
    bundle_id = (
        f"run_bundle:cli:{SUPPORTED_PROFILE}:{regime}:{scenario}"
    )

    bundle = build_run_export_bundle(
        bundle_id=bundle_id,
        run_profile_label=SUPPORTED_PROFILE,
        regime_label=regime,
        selected_scenario_label=scenario,
        period_count=period_count,
        digest=snapshot.digest,
        manifest=_build_manifest(
            profile=SUPPORTED_PROFILE,
            regime=regime,
            scenario=scenario,
            period_count=period_count,
        ),
        overview=_build_overview(regime=regime, snapshot=snapshot),
        timeline=_build_timeline(snapshot=snapshot),
        regime_compare={},
        scenario_trace=_build_scenario_trace(scenario=scenario),
        attention_diff={},
        market_intent={},
        financing={},
        ledger_excerpt=_build_ledger_excerpt(kernel=kernel),
        metadata=_build_metadata(indent=indent),
    )
    return bundle, snapshot.digest


# v1.19.3.1 — monthly_reference bundle builder. Mirrors the
# quarterly_default builder shape but runs the v1.19.3
# ``run_living_reference_world(profile="monthly_reference")``
# path and pulls a deterministic digest from
# ``examples.reference_world.living_world_replay.living_world_digest``.
# The bundle adds an ``information_arrival_summary`` section so a
# reader can see the v1.19.3 release-calendar coverage without
# crawling the ledger excerpt.
def _build_bundle_for_monthly_reference(
    *, regime: str, scenario: str, indent: int
) -> tuple[Any, str]:
    """Run the v1.19.3 monthly_reference profile on a fresh kernel
    and build the bundle. Returns ``(bundle, digest)``."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from examples.reference_world.regime_comparison_report import (
        _DEFAULT_BANK_IDS,
        _DEFAULT_FIRM_IDS,
        _DEFAULT_INVESTOR_IDS,
        _seed_kernel,
        extract_regime_run_snapshot,
    )
    from world.reference_living_world import (
        _DEFAULT_MONTHLY_PERIOD_DATES,
        run_living_reference_world,
    )
    from world.run_export import build_run_export_bundle

    kernel = _seed_kernel()
    result = run_living_reference_world(
        kernel,
        firm_ids=_DEFAULT_FIRM_IDS,
        investor_ids=_DEFAULT_INVESTOR_IDS,
        bank_ids=_DEFAULT_BANK_IDS,
        period_dates=_DEFAULT_MONTHLY_PERIOD_DATES,
        market_regime=regime,
        profile="monthly_reference",
    )
    snapshot = extract_regime_run_snapshot(
        regime_id=regime, kernel=kernel, result=result
    )
    digest = living_world_digest(kernel, result)

    period_count = len(_DEFAULT_MONTHLY_PERIOD_DATES)
    bundle_id = (
        f"run_bundle:cli:monthly_reference:{regime}:{scenario}"
    )

    bundle = build_run_export_bundle(
        bundle_id=bundle_id,
        run_profile_label="monthly_reference",
        regime_label=regime,
        selected_scenario_label=scenario,
        period_count=period_count,
        digest=digest,
        manifest=_build_manifest(
            profile="monthly_reference",
            regime=regime,
            scenario=scenario,
            period_count=period_count,
        ),
        overview=_build_overview(regime=regime, snapshot=snapshot),
        timeline={
            "calendar": "monthly",
            "display_path_kind": "indicative_pressure_path",
            "boundary_note": (
                "synthetic context only — no price formation, "
                "no forecast, no investment advice"
            ),
            "event_annotation_count": len(snapshot.event_annotations),
            "causal_annotation_count": len(snapshot.causal_annotations),
        },
        regime_compare={},
        scenario_trace=_build_scenario_trace(scenario=scenario),
        attention_diff={},
        market_intent={},
        financing={},
        ledger_excerpt=_build_ledger_excerpt(kernel=kernel),
        metadata={
            **_build_metadata(indent=indent),
            "information_arrival_summary": (
                _build_information_arrival_summary(kernel=kernel)
            ),
        },
    )
    return bundle, digest


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point.

    Returns 0 on success. Validation failures raise
    :class:`SystemExit` with a non-zero code via the helper
    validators; argparse failures exit with code 2 by default.
    """
    parser = _build_argument_parser()
    args = parser.parse_args(argv)

    _validate_profile(args.profile)
    _validate_regime(args.regime)
    _validate_scenario(args.scenario)

    if args.profile == "monthly_reference":
        bundle, digest = _build_bundle_for_monthly_reference(
            regime=args.regime,
            scenario=args.scenario,
            indent=args.indent,
        )
    else:
        bundle, digest = _build_bundle_for_quarterly_default(
            regime=args.regime,
            scenario=args.scenario,
            indent=args.indent,
        )

    out_path = Path(args.out)
    # Local import keeps ``write_run_export_bundle`` invocation
    # close to the bundle build site; deferred imports also
    # keep the module's top-level import surface compact.
    from world.run_export import write_run_export_bundle

    write_run_export_bundle(bundle, out_path, indent=args.indent)

    if not args.quiet:
        success_line = _SUCCESS_LINE_TEMPLATE.format(
            path=str(out_path),
            profile=args.profile,
            regime=args.regime,
            digest12=digest[:12],
        )
        print(success_line)
    return 0


# ---------------------------------------------------------------------------
# Module-level introspection helpers (used by tests)
# ---------------------------------------------------------------------------


def _module_text() -> str:
    """Return this module's source text. Used by tests to scan
    for forbidden imports / tokens."""
    return Path(__file__).read_text(encoding="utf-8")


# Public surface for tests / callers that need to inspect the
# CLI bound. Keep stable; tests pin the names.
__all__ = [
    "DESIGNED_BUT_NOT_EXECUTABLE_PROFILES",
    "EXECUTABLE_PROFILES",
    "LEDGER_EXCERPT_LIMIT",
    "SUPPORTED_PROFILE",
    "SUPPORTED_REGIMES",
    "SUPPORTED_SCENARIO",
    "main",
]


# ``Mapping`` is imported above so callers reading the type
# hints stay aligned with the v1.19.1 builder signature; keep
# it referenced to silence linting if otherwise unused.
_ = Mapping


if __name__ == "__main__":
    sys.exit(main())
