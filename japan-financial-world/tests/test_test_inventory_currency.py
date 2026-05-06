"""
v1.23.1 — Test inventory freshness pin tests.

``docs/test_inventory.md`` was pinned at v1.20.last (4764
tests) and drifted ~ 130 tests behind the current corpus
through the v1.21.x / v1.22.x / v1.23.0 design pins. v1.23.1
adds:

- a v1.23.1 entry in ``docs/test_inventory.md`` carrying the
  current total;
- a generator script
  ``examples/tools/refresh_test_inventory.py`` that updates
  the v1.23.1 line based on ``pytest --collect-only``;
- this freshness-pin module.

The pins:

- ``test_test_inventory_mentions_current_test_count`` — the
  doc has a v1.23.1 entry containing a plausible current
  test total (>= 4900);
- ``test_test_inventory_not_stale_against_pytest_collection_count``
  — a lightweight approximation: count ``def test_`` in
  ``tests/*.py`` and assert the doc's v1.23.1 total is
  >= the def-count (since pytest collection always
  expands at least 1:1 from def-count, with
  ``@pytest.mark.parametrize`` fan-out adding more).

Limitations: the lightweight check does not detect a doc
total that is *too high* — only too low. A future
contributor that runs ``examples/tools/refresh_test_inventory.py``
as part of the milestone freeze checklist will keep the
total aligned with full ``pytest --collect-only`` output.
"""

from __future__ import annotations

import re
from pathlib import Path


_DOC_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "test_inventory.md"
)


_TESTS_DIR = Path(__file__).resolve().parent


# Minimum-plausible test count after v1.23.1. Below this,
# the inventory is clearly stale (v1.23.0 was at 4893).
_V1_23_1_MIN_PLAUSIBLE_TEST_COUNT: int = 4900


# Regex matching a v1.23.1 inventory line of the shape
# ``v1.23.1 test count: NNNN`` (case-insensitive). The
# refresh script writes this verbatim.
_V1_23_1_COUNT_RE = re.compile(
    r"v1\.23\.1\s*[-–]?\s*test\s+count\s*[:=]\s*(\d+)",
    re.IGNORECASE,
)


def _read_doc_text() -> str:
    return _DOC_PATH.read_text(encoding="utf-8")


def _doc_v1_23_1_count() -> int | None:
    text = _read_doc_text()
    m = _V1_23_1_COUNT_RE.search(text)
    if m is None:
        return None
    return int(m.group(1))


def _count_def_test_functions() -> int:
    """Lightweight approximation: count top-level / nested
    ``def test_`` definitions in ``tests/*.py``. Does not
    expand ``@pytest.mark.parametrize`` fan-out — pytest
    collection is always >= this count."""
    pat = re.compile(r"^\s*def\s+test_\w+\(", re.MULTILINE)
    total = 0
    for path in sorted(_TESTS_DIR.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        total += len(pat.findall(text))
    return total


def test_test_inventory_mentions_current_test_count() -> None:
    """``docs/test_inventory.md`` must include a v1.23.1
    entry with a plausible current test total (>= 4900)."""
    count = _doc_v1_23_1_count()
    assert count is not None, (
        "docs/test_inventory.md is missing a 'v1.23.1 test "
        "count: NNNN' entry — run "
        "examples/tools/refresh_test_inventory.py to "
        "regenerate"
    )
    assert count >= _V1_23_1_MIN_PLAUSIBLE_TEST_COUNT, (
        f"docs/test_inventory.md v1.23.1 test count = "
        f"{count}; expected >= "
        f"{_V1_23_1_MIN_PLAUSIBLE_TEST_COUNT}. The doc is "
        "stale — run "
        "examples/tools/refresh_test_inventory.py."
    )


def test_test_inventory_not_stale_against_pytest_collection_count() -> None:
    """Lightweight freshness pin: the doc's v1.23.1 total
    must be >= the count of ``def test_`` definitions in
    ``tests/*.py``. A ``pytest --collect-only`` total is
    always >= this count (parametrize fan-out only adds);
    therefore a doc total below the def-count is necessarily
    stale.

    Limitation: this approximation does not catch a doc
    total that is *too high* — only too low. The freeze
    checklist regenerates the count via the refresh
    script."""
    doc_count = _doc_v1_23_1_count()
    assert doc_count is not None, (
        "docs/test_inventory.md missing v1.23.1 entry — "
        "run examples/tools/refresh_test_inventory.py"
    )
    def_count = _count_def_test_functions()
    assert doc_count >= def_count, (
        "docs/test_inventory.md v1.23.1 total "
        f"({doc_count}) is < the lightweight def-count "
        f"({def_count}); the doc is stale. Regenerate "
        "via examples/tools/refresh_test_inventory.py."
    )
