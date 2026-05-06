"""
v1.23.2b — UI staleness cleanup pin tests.

Pins the v1.23.2b minimal UI cleanup surface in
``examples/ui/fwe_workbench_mockup.html``:

- the inline sample manifest is explicitly labelled LEGACY
  (so a reviewer cannot mistake a v1.16-era snapshot for a
  current-engine demo);
- the Run button + data-source substatus + load-status text
  surface the legacy nature of the inline fixture;
- the Active Stresses strip reads ``bundle.stress_readout``
  and falls back to the neutral empty state when absent (no
  hand-rolled stress data);
- the Meta milestone trail extends from v1.20.last to cover
  v1.21.x stress composition, v1.22.x stress readout
  reflection, and v1.23.x substrate hardening + validation
  foundation;
- no new tab was added (11-tab ↔ 11-sheet bijection
  preserved);
- no v1.21.0a / v1.22.0 / v1.23.x forbidden token leaks into
  the new UI surface.

The pins are read-only over the static HTML; they do not
execute JavaScript. v1.23.2b adds no new dataclass, ledger
event, label vocabulary, or runtime behaviour.
"""

from __future__ import annotations

import re
from pathlib import Path


_UI_MOCKUP_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples"
    / "ui"
    / "fwe_workbench_mockup.html"
)


def _read_ui_html() -> str:
    assert _UI_MOCKUP_PATH.is_file(), (
        f"UI mockup missing at {_UI_MOCKUP_PATH}"
    )
    return _UI_MOCKUP_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. Inline sample manifest is explicitly labelled LEGACY.
# ---------------------------------------------------------------------------


def test_v1_23_2b_inline_manifest_marked_legacy() -> None:
    """The inline ``fwe-sample-manifest`` JSON carries
    ``is_legacy_sample: true`` and a fixture_note that names
    the v1.22.last public-FWE runtime as the canonical
    demo path. A reviewer that opens the workbench under
    ``file://`` cannot mistake the v1.16-era snapshot for
    a current-engine demo."""
    text = _read_ui_html()
    assert '"is_legacy_sample": true' in text, (
        "inline manifest missing is_legacy_sample flag"
    )
    assert (
        '"fixture_kind": "legacy_sample_fixture"' in text
    ), (
        'inline manifest fixture_kind must be '
        '"legacy_sample_fixture"'
    )
    assert "LEGACY inline sample fixture" in text, (
        "fixture_note must surface LEGACY status"
    )
    assert "v1.22.last" in text, (
        "fixture_note must name the v1.22.last current "
        "runtime so reviewers know what the legacy snapshot "
        "is being compared against"
    )


def test_v1_23_2b_run_tooltip_does_not_claim_current_engine() -> None:
    """The Run button tooltip surfaces the legacy nature of
    the inline fixture so a reviewer is steered toward
    Load local bundle for current-engine demos."""
    text = _read_ui_html()
    # Find the run button tag.
    m = re.search(
        r'<button id="btn-run"[^>]*>',
        text,
    )
    assert m is not None, "btn-run not found"
    tag = m.group(0)
    assert (
        "LEGACY inline sample fixture" in tag
        or "LEGACY" in tag
    ), (
        "Run tooltip must mark the inline fixture as legacy"
    )
    assert "Load local bundle" in tag, (
        "Run tooltip must steer reviewers toward Load local "
        "bundle for an accurate demo"
    )


def test_v1_23_2b_load_local_bundle_tooltip_mentions_stress_readout() -> None:
    """The Load local bundle tooltip mentions v1.22.1
    stress_readout support so a reviewer reading the tooltip
    knows the canonical demo path supports the v1.22.x
    stress reflection layer."""
    text = _read_ui_html()
    m = re.search(
        r'<button id="btn-load-local-bundle"[^>]*>',
        text,
    )
    assert m is not None, "btn-load-local-bundle not found"
    tag = m.group(0)
    assert "stress_readout" in tag, (
        "Load local bundle tooltip must mention "
        "stress_readout (v1.22.1 payload section support)"
    )
    assert "v1.22.1" in tag, (
        "Load local bundle tooltip must mention v1.22.1 "
        "explicitly"
    )


def test_v1_23_2b_data_source_default_is_none_until_run() -> None:
    """The data-source substatus default is ``none`` so a
    reviewer that has not pressed Run sees no implication
    that any fixture is loaded. After Run, the data-source
    becomes ``legacy_inline_fixture`` (see the loadSample +
    runMock handlers)."""
    text = _read_ui_html()
    m = re.search(
        r'<span id="current-data-source"[^>]*>'
        r'(?P<inner>[^<]*)</span>',
        text,
    )
    assert m is not None, "current-data-source span not found"
    # Default text is "none" or starts with "none".
    inner = m.group("inner").strip()
    assert inner.lower() == "none", (
        "current-data-source default must be 'none' "
        f"(got {inner!r})"
    )
    # And the data-source attribute is also "none".
    m2 = re.search(
        r'<span id="current-data-source"\s+data-source="(?P<src>[^"]*)"',
        text,
    )
    assert m2 is not None, "current-data-source data-source missing"
    assert m2.group("src") == "none", (
        "current-data-source data-source default must be "
        f"'none' (got {m2.group('src')!r})"
    )


# ---------------------------------------------------------------------------
# 2. Active Stresses strip reads ``bundle.stress_readout`` and
#    falls back to neutral empty state when absent.
# ---------------------------------------------------------------------------


def test_v1_23_2b_active_stresses_strip_reads_bundle_stress_readout() -> None:
    """The ``renderActiveStressesFromBundle`` JS function
    reads ``bundle.stress_readout`` (the v1.22.1 descriptive-
    only payload section) — not a hand-rolled fixture."""
    text = _read_ui_html()
    # Locate the function body.
    m = re.search(
        r'function\s+renderActiveStressesFromBundle\s*\([^)]*\)\s*\{',
        text,
    )
    assert m is not None, (
        "renderActiveStressesFromBundle function not found"
    )
    # Snip the next ~40 lines after the function start.
    start = m.end()
    body = text[start:start + 2000]
    assert "bundle.stress_readout" in body, (
        "renderActiveStressesFromBundle must read "
        "bundle.stress_readout (the v1.22.1 payload "
        "section); a hand-rolled fixture is forbidden"
    )
    # Empty-section fallback must restore the neutral empty
    # state.
    assert "section.length === 0" in body, (
        "renderActiveStressesFromBundle must check for "
        "empty stress_readout and switch to the empty "
        "state"
    )
    # The neutral empty-state slot must exist in the DOM.
    assert 'id="active-stresses-empty"' in text, (
        "active-stresses-empty slot missing from DOM"
    )


def test_v1_23_2b_load_sample_resets_active_stresses_strip() -> None:
    """``loadSample`` (the legacy inline path) calls
    ``renderActiveStressesFromBundle({})`` to reset the
    strip. Without this, a reviewer that first loaded a
    local bundle with stress data and then clicked Run
    would see stale strip entries from the prior load."""
    text = _read_ui_html()
    m = re.search(
        r'function\s+loadSample\s*\(\s*\)\s*\{',
        text,
    )
    assert m is not None, "loadSample function not found"
    start = m.end()
    # Find the matching closing brace by depth-balanced walk.
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    body = text[start:i]
    assert "renderActiveStressesFromBundle" in body, (
        "loadSample must reset the Active Stresses strip "
        "(call renderActiveStressesFromBundle) so a stale "
        "local-bundle render does not bleed into the next "
        "Run click"
    )


# ---------------------------------------------------------------------------
# 3. Meta milestone trail extends through v1.23.x.
# ---------------------------------------------------------------------------


_MILESTONE_TRAIL_REQUIRED_ROWS: tuple[str, ...] = (
    "v1.16.last",
    "v1.17.4",
    "v1.18.last",
    "v1.19.last",
    "v1.20.last",
    "v1.21.x",
    "v1.22.x",
    "v1.23.x",
)


def test_v1_23_2b_meta_milestone_trail_extends_through_v1_23_x() -> None:
    """The Meta sheet's milestone trail covers every public
    milestone from v1.16.last through v1.23.x. Pre-v1.23.2b
    the table stopped at v1.20.last, leaving a multi-
    milestone gap a reviewer would notice."""
    text = _read_ui_html()
    # Locate the milestone-trail section.
    title_idx = text.find(
        "<h3 class=\"card-title\">v1.16 → v1.23 milestone trail</h3>"
    )
    assert title_idx >= 0, (
        "milestone trail card title must be updated to "
        "'v1.16 → v1.23 milestone trail'"
    )
    # Find the table body that follows.
    tbody_open = text.find("<tbody>", title_idx)
    tbody_close = text.find("</tbody>", tbody_open)
    assert tbody_open > 0 and tbody_close > tbody_open
    body = text[tbody_open:tbody_close]
    for milestone in _MILESTONE_TRAIL_REQUIRED_ROWS:
        assert milestone in body, (
            f"milestone trail missing required row "
            f"{milestone!r}"
        )


def test_v1_23_2b_meta_milestone_trail_v1_21_through_v1_23_descriptive() -> None:
    """The new v1.21.x / v1.22.x / v1.23.x rows describe
    surface, not predictive content. No outcome / forecast /
    impact / recommendation token may leak into the new
    rows."""
    text = _read_ui_html()
    # Find each new row and check for forbidden wording.
    forbidden_in_descriptions = (
        "forecast",
        "prediction",
        "expected return",
        "target price",
        "recommendation",
        "investment advice",
        "buy signal",
        "sell signal",
        "risk score",
        "expected response",
    )
    for milestone in ("v1.21.x", "v1.22.x", "v1.23.x"):
        row_idx = text.find(milestone)
        assert row_idx >= 0
        # Read the next 800 chars (the row's <td> cell).
        snippet = text[row_idx:row_idx + 1200].lower()
        for token in forbidden_in_descriptions:
            assert token not in snippet, (
                f"milestone trail {milestone!r} row contains "
                f"forbidden wording {token!r}"
            )


# ---------------------------------------------------------------------------
# 4. No new tab. 11-tab ↔ 11-sheet bijection preserved.
# ---------------------------------------------------------------------------


def test_v1_23_2b_no_new_tab_added() -> None:
    """v1.23.2b must not introduce a new tab. The pre-v1.23.2b
    11-tab ↔ 11-sheet bijection is preserved; the cleanup is
    pure tooltip / wording / data-source naming."""
    text = _read_ui_html()
    tabs = re.findall(r'<button class="sheet-tab[^"]*"[^>]*data-sheet="([^"]+)"', text)
    sheets = re.findall(r'<article id="sheet-([^"]+)"', text)
    assert len(tabs) == len(sheets), (
        f"tab count ({len(tabs)}) != sheet count "
        f"({len(sheets)})"
    )
    assert sorted(tabs) == sorted(sheets), (
        "tab data-sheet values do not match article id "
        "stems (1:1 bijection broken)"
    )
    # And the count is the v1.20.5 11-tab pin.
    assert len(tabs) == 11, (
        f"expected 11-tab strip; got {len(tabs)}"
    )


# ---------------------------------------------------------------------------
# 5. No forbidden v1.21.0a / v1.22.0 / v1.23.x token leaked
#    into the new UI surface (Status block + milestone rows
#    + tooltips).
# ---------------------------------------------------------------------------


_FORBIDDEN_NEW_UI_TOKENS: tuple[str, ...] = (
    # v1.22.0 outcome / impact / amplification language
    "impact",
    "outcome",
    "risk_score",
    "amplification",
    "dampening",
    "offset effect",
    "dominant stress",
    "net pressure",
    "composite risk",
    # forecast / prediction / advice
    "forecast",
    "expected response",
    "prediction",
    "recommendation",
    "investment advice",
    "expected return",
    "target price",
    # v1.21.0a interaction-label vocabulary
    "amplify",
    "dampen",
    "coexist",
)


def test_v1_23_2b_status_block_carries_no_forbidden_tokens() -> None:
    """The new ``Status of this UI`` rows (Latest UI delta /
    Latest substrate delta / Inline sample fixture) carry
    no v1.22.0 outcome / impact / amplification token and
    no v1.21.0a interaction token. Boundary scan."""
    text = _read_ui_html()
    title_idx = text.find(
        "<h3 class=\"card-title\">Status of this UI</h3>"
    )
    assert title_idx >= 0
    section_close = text.find("</section>", title_idx)
    assert section_close > title_idx
    body = text[title_idx:section_close].lower()
    offenders: list[str] = []
    for token in _FORBIDDEN_NEW_UI_TOKENS:
        # Whole-word boundary scan.
        pattern = rf"\b{re.escape(token.lower())}\b"
        if re.search(pattern, body):
            offenders.append(token)
    assert offenders == [], (
        "Status of this UI block contains forbidden tokens: "
        f"{sorted(offenders)!r}"
    )
