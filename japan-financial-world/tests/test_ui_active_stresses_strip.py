"""
Tests for v1.22.2 — Active Stresses strip in the static
workbench UI.

The v1.22.2 UI surface is the read-only reflection of the
v1.21.3 stress readout via the v1.22.1 ``bundle.stress_readout``
payload section. v1.22.2 ships:

- HTML markup inside the existing v1.20.5 Universe sheet
  (above the existing sector heatmap),
- CSS for the strip (no magnitude / score / red-green
  encoding),
- a ``renderActiveStressesFromBundle(bundle)`` JS function
  that reads ``bundle.stress_readout`` and renders the strip.

Binding (v1.22.2 brief, mirrored from v1.22.0 design pin §4
/ §5):

- **No new tab.** The v1.20.5 11-tab ↔ 11-sheet bijection is
  preserved.
- The strip lives in the existing Universe sheet, above the
  sector heatmap. Existing widgets (heatmap, firm table,
  scenario causal trace) are not displaced or resized.
- The strip renders an empty-state placeholder when the
  bundle carries no ``stress_readout`` (the v1.22.1 omission
  rule keeps pre-v1.22 bundles byte-identical and means most
  bundles will hit this branch).
- Required wording is verbatim: ``Active stresses`` /
  ``Read-only stress readout`` / ``Context surfaces`` /
  ``Shift directions`` / ``Cited records`` / ``Downstream
  citations`` / ``Partial application`` / ``Multiset
  projection`` / ``Resolved steps`` / ``Unresolved steps``.
- Forbidden wording absent: no ``impact`` / ``outcome`` /
  ``risk score`` / ``forecast`` / ``prediction`` /
  ``recommendation`` / ``expected return`` / ``target
  price`` / ``buy`` / ``sell`` / ``trade`` / ``order`` /
  ``execution`` / ``amplification`` / ``dampening`` /
  ``offset effect`` / ``dominant stress`` / ``net pressure``
  / ``composite risk`` / ``expected response`` (case-
  insensitive whole-word match).
- The browser executes static JSON only — no ``fetch(`` /
  ``XMLHttpRequest`` / ``eval(`` / ``new Function(`` is
  introduced by v1.22.2.
- Raw canonical labels (e.g. ``attention_amplify``) live
  only inside the technical-details ``Raw canonical
  labels`` block; they never become primary UI prose, and
  they never become interaction-language phrasing.

These tests parse the static HTML directly using regex /
substring matching (the v1.20.5 / v1.19.4 UI-test convention)
since the project does not ship a headless-browser
dependency. The tests pin the *static surface* — selectors,
wording, function names, and absence of forbidden tokens —
which is the contract the v1.22.0 design pin §6.2 enumerates.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from _canonical_digests import (
    MONTHLY_REFERENCE_LIVING_WORLD_DIGEST,
    QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST,
    SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST,
)


_UI_MOCKUP_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "ui"
    / "fwe_workbench_mockup.html"
)


def _read_ui_html() -> str:
    assert _UI_MOCKUP_PATH.exists(), (
        f"UI mockup missing at {_UI_MOCKUP_PATH}"
    )
    return _UI_MOCKUP_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return _read_ui_html()


# ---------------------------------------------------------------------------
# 1. test_universe_tab_count_unchanged
# ---------------------------------------------------------------------------


def test_universe_tab_count_unchanged(html: str) -> None:
    """v1.20.5 11-tab ↔ 11-sheet bijection MUST be preserved.
    v1.22.2 adds **no new tab**; the Active Stresses surface
    lands inside the existing Universe sheet."""
    sheet_tab_buttons = re.findall(
        r'class="sheet-tab[^"]*"\s+data-sheet="([^"]+)"',
        html,
    )
    assert len(sheet_tab_buttons) == 11, (
        "expected exactly 11 sheet-tab buttons "
        "(v1.20.5 bijection); got "
        f"{len(sheet_tab_buttons)}: {sheet_tab_buttons}"
    )
    # The data-sheet labels include "universe" (the existing
    # Universe sheet — v1.22.2 reuses it).
    assert "universe" in sheet_tab_buttons
    # 11 sheets in the document. Cover sheet uses
    # ``class="sheet active"`` so the regex tolerates extra
    # class tokens after ``sheet``.
    sheets = re.findall(
        r'<article id="sheet-([a-z\-]+)"\s+class="sheet[^"]*"',
        html,
    )
    assert len(sheets) == 11, (
        f"expected 11 sheet articles; got "
        f"{len(sheets)}: {sheets}"
    )


# ---------------------------------------------------------------------------
# 2. test_active_stresses_strip_renders_when_stress_readout_present
# ---------------------------------------------------------------------------


def test_active_stresses_strip_renders_when_stress_readout_present(
    html: str,
) -> None:
    """The Active Stresses strip selector exists exactly once
    in the document and lives **inside the Universe sheet**.
    The renderer reads ``bundle.stress_readout`` and populates
    the strip when the section is present."""
    # The strip selector exists exactly once.
    assert html.count('data-section="active-stresses"') == 1
    # Selector lives inside <article id="sheet-universe">.
    universe_match = re.search(
        r'<article id="sheet-universe"\s+class="sheet">'
        r'(.*?)</article>',
        html,
        re.DOTALL,
    )
    assert universe_match is not None
    universe_html = universe_match.group(1)
    assert (
        'data-section="active-stresses"' in universe_html
    )
    # The renderer reads bundle.stress_readout.
    assert "bundle.stress_readout" in html
    # The renderer is wired into renderBundle.
    assert (
        "renderActiveStressesFromBundle(bundle)" in html
    )


# ---------------------------------------------------------------------------
# 3. test_neutral_empty_state_renders_when_stress_readout_absent
# ---------------------------------------------------------------------------


def test_neutral_empty_state_renders_when_stress_readout_absent(
    html: str,
) -> None:
    """When ``bundle.stress_readout`` is absent or empty, the
    strip renders a neutral empty-state placeholder."""
    assert (
        "No active stress readout in this bundle." in html
    )
    # The empty-state slot exists with a stable id.
    assert 'id="active-stresses-empty"' in html
    assert 'id="active-stresses-content"' in html
    # The renderer toggles the empty-state when section length
    # is zero (length-zero short-circuit visible in JS).
    assert "section.length === 0" in html


# ---------------------------------------------------------------------------
# 4. test_partial_application_badge_renders_when_is_partial
# ---------------------------------------------------------------------------


def test_partial_application_badge_renders_when_is_partial(
    html: str,
) -> None:
    """The Partial application badge selector + wording exist
    in the JS render path. The badge fires on ``is_partial ===
    true`` OR ``unresolved_step_count > 0`` (defensive: the
    v1.22.1 entry validator pins ``is_partial`` ==
    ``unresolved_step_count > 0`` already, but the UI guards
    both)."""
    assert "data-active-stresses-partial-badge" in html
    assert (
        "active-stresses-partial-badge" in html
    )  # CSS class
    # Badge text is exactly "Partial application".
    assert "badge.textContent = 'Partial application'" in html
    # Badge fires for is_partial OR unresolved > 0.
    assert "entry.is_partial === true" in html
    assert "unresolvedCount > 0" in html


# ---------------------------------------------------------------------------
# 5. test_unresolved_step_ids_and_reasons_visible_for_partial
# ---------------------------------------------------------------------------


def test_unresolved_step_ids_and_reasons_visible_for_partial(
    html: str,
) -> None:
    """When ``is_partial`` is true, the strip surfaces the
    unresolved step ids AND the closed-set
    ``unresolved_reason_labels`` parallel array."""
    # Both unresolved-block + unresolved-reasons selectors
    # exist.
    assert "data-active-stresses-unresolved-block" in html
    assert (
        "data-active-stresses-unresolved-reasons" in html
    )
    # Block headers exist.
    assert "Unresolved steps" in html
    assert "Unresolved reason labels" in html
    # The renderer reads both arrays from the entry.
    assert "entry.unresolved_step_ids" in html
    assert "entry.unresolved_reason_labels" in html
    # The unresolved counter is rendered with explicit text.
    assert "Unresolved steps: ' + String(unresolvedCount)" in html


# ---------------------------------------------------------------------------
# 6. test_ui_reads_static_json_only
# ---------------------------------------------------------------------------


def test_ui_reads_static_json_only(html: str) -> None:
    """The UI loads the bundle via ``<input type="file">`` +
    ``FileReader`` + ``JSON.parse`` (existing v1.19.4
    discipline). v1.22.2 introduces no new network / backend
    code path."""
    assert "FileReader" in html
    assert "JSON.parse" in html
    # No fetch / XHR introduced by v1.22.2 (or pre-existing
    # for that matter — the v1.19.4 discipline already pins
    # this; v1.22.2 re-pins it).
    lower = html.lower()
    assert "fetch(" not in lower
    assert "xmlhttprequest" not in lower
    # No <script src="http..."> external load.
    assert '<script src="http' not in lower
    assert '<script src="https' not in lower


# ---------------------------------------------------------------------------
# 7. test_ui_does_not_execute_python
# ---------------------------------------------------------------------------


def test_ui_does_not_execute_python(html: str) -> None:
    """The browser does not execute Python (no embedded
    interpreter, no Pyodide load, no shell-out). This is the
    foundational v1.19.4 discipline; v1.22.2 re-pins it on the
    new Active Stresses strip."""
    lower = html.lower()
    forbidden = (
        "pyodide",
        "skulpt",
        "brython",
        "transcrypt",
        "child_process",
        "spawn(",
        "exec(",
        "eval(",
        "new function(",
    )
    for tok in forbidden:
        assert tok not in lower, (
            f"forbidden Python-or-eval token {tok!r} appears "
            "in the UI mockup"
        )


# ---------------------------------------------------------------------------
# 8. test_ui_contains_no_forbidden_wording_in_user_facing_strings
# ---------------------------------------------------------------------------


def _strip_for_user_text(html: str) -> str:
    """Approximate user-visible text by stripping HTML and JS
    comment blocks. The user does not see HTML comments,
    JS ``//`` line comments, or JS / CSS ``/* ... */`` block
    comments in the rendered UI; comments that *negate*
    forbidden tokens (e.g. ``// no impact / outcome / ...``)
    are documentation, not UI claims, and must be excluded
    from the forbidden-wording scan."""
    # Remove <!-- ... --> HTML comments.
    out = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
    # Remove /* ... */ CSS / JS block comments.
    out = re.sub(r"/\*.*?\*/", "", out, flags=re.DOTALL)
    # Remove // line comments inside JS / CSS contexts.
    out = re.sub(r"//[^\n]*", "", out)
    return out


def _extract_v1_22_2_surface(html: str) -> str:
    """Concatenate the v1.22.2-specific UI surface for
    forbidden-wording scanning:

    1. The ``<section ... data-section="active-stresses">``
       HTML block (the strip's markup).
    2. The CSS block headed by ``v1.22.2 — Active Stresses
       strip.``
    3. The JS block headed by ``v1.22.2 — Active Stresses
       strip renderer.`` through to and including
       ``renderActiveStressesFromBundle`` and its helper
       functions.

    Forbidden-wording assertions then run against this
    concatenation, *not* against the entire HTML file —
    pre-existing v1.20.5 boundary disclaimers (like
    ``no trade, no order, no execution``) are explicitly
    *negation* statements and are not v1.22.2 wording.
    Scoping the scan to the v1.22.2 surface is the right
    semantics for the brief."""
    pieces: list[str] = []

    # 1) HTML strip section
    strip = re.search(
        r"<section\b[^>]*data-section=\"active-stresses\""
        r"[^>]*>.*?</section>",
        html,
        re.DOTALL,
    )
    if strip is not None:
        pieces.append(strip.group(0))

    # 2) CSS block
    css = re.search(
        r"v1\.22\.2 — Active Stresses\s*\n.*?(?:\n\s+/\*"
        r" =====| Causal trace block:)",
        html,
        re.DOTALL,
    )
    if css is not None:
        pieces.append(css.group(0))

    # 3) JS renderer block — starts at the comment header and
    # ends just before the next outer function declaration
    # (``loadLocalBundleFromText``).
    js = re.search(
        r"v1\.22\.2 — Active Stresses strip renderer\..*?"
        r"(?=\n\s+function loadLocalBundleFromText\()",
        html,
        re.DOTALL,
    )
    if js is not None:
        pieces.append(js.group(0))

    return "\n".join(pieces)


def test_ui_contains_no_forbidden_wording_in_user_facing_strings(
    html: str,
) -> None:
    """v1.22.2 surface MUST NOT contain the forbidden-wording
    set. Whole-word, case-insensitive match — so legitimate
    closed-set tokens like ``attention_amplify`` (rendered in
    the technical Raw canonical labels block) do **not** match
    the forbidden ``amplify`` token (underscore is a word
    character so the boundary holds).

    Pre-existing v1.20.5 boundary disclaimers
    (``no trade, no order, no execution, no forecast``) live
    outside the v1.22.2 strip and are explicitly *negation*
    statements — they are not v1.22.2 wording and are not
    covered by this test. We extract the v1.22.2-specific
    HTML / CSS / JS surface (see ``_extract_v1_22_2_surface``)
    and scan only that."""
    surface = _extract_v1_22_2_surface(html)
    assert len(surface) > 500, (
        "v1.22.2 surface extraction returned too little — "
        "the markers may have moved"
    )
    user_text = _strip_for_user_text(surface)
    # Forbidden vocabulary from the v1.22.2 brief
    # ("Forbidden UI wording"). Multi-word phrases match
    # literally; single-word tokens use whole-word matching so
    # canonical labels like ``attention_amplify`` (a single
    # underscore-bounded identifier) do not trigger.
    forbidden_tokens_whole_word = [
        "impact",
        "outcome",
        "amplification",
        "dampening",
        "forecast",
        "prediction",
        "recommendation",
        "buy",
        "sell",
        "trade",
        "order",
        "execution",
    ]
    for tok in forbidden_tokens_whole_word:
        # Whole-word, case-insensitive. Word boundaries on
        # both sides (\b in Python regex; underscore counts
        # as a word char so ``attention_amplify`` is one
        # word and does NOT match the bare ``amplify``).
        pattern = re.compile(
            r"\b" + re.escape(tok) + r"\b",
            re.IGNORECASE,
        )
        match = pattern.search(user_text)
        assert match is None, (
            f"forbidden v1.22.2-surface token {tok!r} "
            f"appears at offset "
            f"{match.start() if match else -1}: "
            f"{user_text[max(0, (match.start() if match else 0) - 40):(match.end() + 40) if match else 0]!r}"
        )

    # Multi-word forbidden phrases (case-insensitive
    # substring; whole-word boundaries naturally hold).
    forbidden_phrases = [
        "risk score",
        "offset effect",
        "dominant stress",
        "net pressure",
        "composite risk",
        "expected response",
        "expected return",
        "target price",
    ]
    user_text_lower = user_text.lower()
    for phrase in forbidden_phrases:
        assert phrase.lower() not in user_text_lower, (
            f"forbidden v1.22.2-surface phrase {phrase!r} "
            "appears in the UI mockup"
        )


# ---------------------------------------------------------------------------
# 9. test_existing_universe_heatmap_still_renders
# ---------------------------------------------------------------------------


def test_existing_universe_heatmap_still_renders(
    html: str,
) -> None:
    """The v1.20.5 sector sensitivity heatmap selector / shape
    is unchanged. v1.22.2 adds the Active Stresses strip
    *above* the heatmap; it does not modify or displace the
    heatmap."""
    # Sector heatmap title still present.
    assert "Sector sensitivity heatmap" in html
    # Heatmap tbody selector unchanged.
    assert 'id="tbody-universe-sectors"' in html
    # Heatmap table tag unchanged: 9 columns.
    sensitivity_table = re.search(
        r'<table class="sensitivity-table">(.*?)</table>',
        html,
        re.DOTALL,
    )
    assert sensitivity_table is not None
    table_html = sensitivity_table.group(1)
    cols = re.findall(
        r'<col\s+style="width:[^"]+"\s*/>', table_html
    )
    assert len(cols) == 9, (
        f"expected 9 colgroup cols; got {len(cols)}"
    )
    # Heatmap renderer is still called.
    assert "renderUniverseFromBundle(bundle)" in html


# ---------------------------------------------------------------------------
# 10. test_existing_firm_profile_table_still_renders
# ---------------------------------------------------------------------------


def test_existing_firm_profile_table_still_renders(
    html: str,
) -> None:
    """The v1.20.5 firm-profile table selector / shape is
    unchanged."""
    assert "Firm profiles · 11 representative firms" in html
    assert 'id="tbody-universe-firms"' in html
    firm_table = re.search(
        r'<table class="universe-firm-table">(.*?)</table>',
        html,
        re.DOTALL,
    )
    assert firm_table is not None
    table_html = firm_table.group(1)
    cols = re.findall(
        r'<col\s+style="width:[^"]+"\s*/>', table_html
    )
    assert len(cols) == 6, (
        f"expected 6 colgroup cols; got {len(cols)}"
    )


# ---------------------------------------------------------------------------
# 11. test_existing_no_stress_local_bundle_still_loads
# ---------------------------------------------------------------------------


def test_existing_no_stress_local_bundle_still_loads(
    html: str,
) -> None:
    """The v1.19.4 local-bundle loader path is unchanged. A
    pre-v1.22 / no-stress bundle (no ``stress_readout`` key)
    still loads cleanly: the renderer iterates an empty
    section and shows the empty-state placeholder.

    The renderer must defensively handle three cases:
      1. ``bundle.stress_readout`` is undefined (pre-v1.22
         bundle) — Array.isArray check returns false →
         empty section.
      2. ``bundle.stress_readout`` is an empty array — length
         zero → empty-state branch.
      3. ``bundle.stress_readout`` has one or more entries —
         live branch.
    """
    # The Array.isArray defensive check covers the undefined
    # path. The length-zero check covers the empty-array path.
    assert "Array.isArray(" in html
    assert "bundle.stress_readout" in html
    assert "section.length === 0" in html
    # The bundle loader's existing FileReader path is intact.
    assert "loadLocalBundleFromText" in html
    # validateBundleSchema (v1.19.x) is still called in the
    # load path.
    assert "validateBundleSchema(bundle)" in html


# ---------------------------------------------------------------------------
# 12. test_stress_readout_raw_labels_are_not_converted_to_interaction_claims
# ---------------------------------------------------------------------------


def test_stress_readout_raw_labels_are_not_converted_to_interaction_claims(
    html: str,
) -> None:
    """Raw canonical labels (e.g. ``attention_amplify``,
    ``tighten``) appear ONLY inside the technical-details
    ``Raw canonical labels`` block. They are rendered as code-
    style tokens via ``textContent`` on a list element — never
    re-labelled as ``amplified stress`` / ``offset effect`` /
    ``dominant stress`` / ``net pressure`` / ``composite risk``
    / ``amplification`` / ``dampening``."""
    user_text = _strip_for_user_text(html)
    # The technical-details slot exists.
    assert (
        'data-active-stresses-raw-labels' in html
    )
    assert "Raw canonical labels" in html
    # The interaction-language phrases listed in the brief
    # MUST NOT appear anywhere in user-facing text.
    forbidden_interaction_phrases = [
        "amplified stress",
        "stress amplification",
        "stress dampening",
        "offset effect",
        "dominant stress",
        "net pressure",
        "composite risk",
        "interaction label",
    ]
    user_text_lower = user_text.lower()
    for phrase in forbidden_interaction_phrases:
        assert phrase.lower() not in user_text_lower, (
            f"interaction-language phrase {phrase!r} appears "
            "in user-facing text"
        )
    # The CSS class for the raw-labels slot is dashed
    # (technical-details styling), not a primary label.
    assert "active-stresses-raw-labels" in html


# ---------------------------------------------------------------------------
# 13. test_no_new_tab_is_added
# ---------------------------------------------------------------------------


def test_no_new_tab_is_added(html: str) -> None:
    """v1.22.2 MUST NOT introduce a new tab. The 11-tab ↔
    11-sheet bijection is preserved. (Mirrors test 1 from a
    different angle — pins the absence of any 12th sheet
    button.)"""
    # No 12-or-more sheet-tab buttons.
    sheet_tab_buttons = re.findall(
        r'class="sheet-tab[^"]*"', html
    )
    assert len(sheet_tab_buttons) == 11
    # No new <article id="sheet-...">. Cover sheet uses
    # ``class="sheet active"`` so we accept extra class
    # tokens.
    sheets = re.findall(
        r'<article id="sheet-([a-z\-]+)"\s+class="sheet[^"]*"',
        html,
    )
    assert len(sheets) == 11
    # The 11 known sheet ids are unchanged.
    expected_sheet_ids = {
        "cover",
        "settings",
        "overview",
        "universe",
        "timeline",
        "regime-compare",
        "attention",
        "market-intent",
        "financing",
        "ledger",
        "appendix",
    }
    assert set(sheets) == expected_sheet_ids


# ---------------------------------------------------------------------------
# 14. test_no_export_schema_changes_are_introduced
# ---------------------------------------------------------------------------


def test_no_export_schema_changes_are_introduced() -> None:
    """v1.22.2 introduces no export-schema changes. The 19
    keys pinned by v1.22.0 §3.4 + v1.22.1
    :data:`STRESS_READOUT_ENTRY_REQUIRED_KEYS` are unchanged.
    The forbidden-token frozenset is unchanged. The bundle's
    ``to_dict`` shape is unchanged.

    This is an export-side cross-pin: v1.22.2 is a UI-only
    milestone; any new export key would belong to v1.22.3+ or
    a v1.22.2a correction, not to v1.22.2 itself.
    """
    from world.run_export import (
        FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS,
        STRESS_READOUT_ENTRY_REQUIRED_KEYS,
        RunExportBundle,
    )

    expected_keys = {
        "stress_program_application_id",
        "stress_program_template_id",
        "as_of_date",
        "total_step_count",
        "resolved_step_count",
        "unresolved_step_count",
        "active_step_ids",
        "unresolved_step_ids",
        "unresolved_reason_labels",
        "is_partial",
        "scenario_driver_template_ids",
        "scenario_application_ids",
        "scenario_context_shift_ids",
        "context_surface_labels",
        "shift_direction_labels",
        "scenario_family_labels",
        "source_context_record_ids",
        "downstream_citation_ids",
        "warnings",
    }
    assert STRESS_READOUT_ENTRY_REQUIRED_KEYS == expected_keys

    expected_forbidden = {
        "impact",
        "outcome",
        "risk_score",
        "amplification",
        "dampening",
        "offset_effect",
        "dominant_stress",
        "net_pressure",
        "composite_risk",
        "forecast",
        "expected_response",
        "prediction",
        "recommendation",
        "expected_return",
        "target_price",
        "buy",
        "sell",
        "order",
        "trade",
        "execution",
        "real_data",
        "japan_calibration",
        "llm_output",
        "aggregate",
        "combined",
        "net",
        "dominant",
        "composite",
        "amplify",
        "dampen",
        "offset",
        "coexist",
    }
    assert (
        expected_forbidden
        <= FORBIDDEN_STRESS_READOUT_EXPORT_TOKENS
    )

    # An empty bundle still omits stress_readout from to_dict.
    bundle = RunExportBundle(
        bundle_id="run_bundle:test:v1_22_2",
        run_profile_label="quarterly_default",
        regime_label="constrained",
        selected_scenario_label="none_baseline",
        period_count=0,
        digest="x" * 64,
    )
    assert "stress_readout" not in bundle.to_dict()


# ---------------------------------------------------------------------------
# 15. test_no_runtime_modules_are_modified
# ---------------------------------------------------------------------------


def test_no_runtime_modules_are_modified() -> None:
    """v1.22.2 modifies no runtime module. The v1.21.last
    canonical living-world digests stay byte-identical
    (already pinned in
    ``tests/test_run_export_stress_readout.py::test_existing_no_stress_bundle_digest_unchanged``);
    this test re-pins the digests as a v1.22.2 cross-check so
    a future regression that inadvertently moves the
    runtime path is caught at the UI test layer too."""
    from examples.reference_world.living_world_replay import (
        living_world_digest,
    )
    from test_living_reference_world import (  # type: ignore[import-not-found]
        _run_default,
        _run_monthly_reference,
        _seed_kernel as _canonical_seed_kernel,
    )
    from test_living_reference_world_performance_boundary import (  # type: ignore[import-not-found]
        _seed_v1_20_3_kernel,
    )
    from world.reference_living_world import (
        _DEFAULT_MONTHLY_PERIOD_DATES,
        _DEFAULT_SCENARIO_UNIVERSE_BANK_IDS,
        _DEFAULT_SCENARIO_UNIVERSE_FIRM_IDS,
        _DEFAULT_SCENARIO_UNIVERSE_INVESTOR_IDS,
        run_living_reference_world,
    )

    # quarterly_default
    k1 = _canonical_seed_kernel()
    r1 = _run_default(k1)
    assert (
        living_world_digest(k1, r1)
        == QUARTERLY_DEFAULT_LIVING_WORLD_DIGEST
    )

    # monthly_reference
    k2 = _canonical_seed_kernel()
    r2 = _run_monthly_reference(k2)
    assert (
        living_world_digest(k2, r2)
        == MONTHLY_REFERENCE_LIVING_WORLD_DIGEST
    )

    # scenario_monthly_reference_universe (v1.20.3 fixture)
    k3 = _seed_v1_20_3_kernel()
    r3 = run_living_reference_world(
        k3,
        firm_ids=_DEFAULT_SCENARIO_UNIVERSE_FIRM_IDS,
        investor_ids=_DEFAULT_SCENARIO_UNIVERSE_INVESTOR_IDS,
        bank_ids=_DEFAULT_SCENARIO_UNIVERSE_BANK_IDS,
        period_dates=_DEFAULT_MONTHLY_PERIOD_DATES,
        profile="scenario_monthly_reference_universe",
    )
    assert (
        living_world_digest(k3, r3)
        == SCENARIO_MONTHLY_REFERENCE_UNIVERSE_DIGEST
    )
