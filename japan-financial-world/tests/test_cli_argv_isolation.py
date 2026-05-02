"""
Regression pin: CLI smoke tests must be isolated from pytest's argv.

The bug this test set guards against
-------------------------------------

Several reference-world CLIs use ``argparse`` to read flags
(``--markdown``, ``--manifest``, ...). Their ``main()`` signatures
look like::

    def main(argv: list[str] | None = None) -> None:
        args = _parse_args(argv)

If a test calls ``cli.main()`` with no argument, ``argv`` defaults
to ``None``, and ``argparse.ArgumentParser.parse_args(None)`` falls
through to ``sys.argv[1:]``. Under ``pytest -q`` (the gate CI runs),
``sys.argv`` is ``["pytest", "-q"]`` (or similar), so the demo CLI
sees ``-q`` as one of its own flags and exits with::

    error: unrecognized arguments: -q

That failure mode actually shipped at v1.9.0 in
``test_living_reference_world.py::test_cli_smoke_prints_per_period_trace``
and was caught by GitHub Actions on a clean ``main`` push. The
fix is two-line — pass ``argv=[]`` explicitly — but this regression
pin makes the contract permanent:

- *every* reference-world CLI ``main()`` accepts ``argv: list[str] |
  None``;
- under a hostile ``sys.argv``, calling ``cli.main([])`` does not
  crash;
- the default behavior when running the script directly (``python
  -m examples.reference_world.<cli>``) is preserved — that path
  uses ``argv=None`` and the OS-supplied ``sys.argv``.

Tests below use ``monkeypatch.setattr(sys, "argv", ...)`` to
simulate a hostile invocation and then call ``cli.main([])``. If a
future CLI accidentally drops the ``argv`` parameter or starts
ignoring the explicit list, the test fails loudly.
"""

from __future__ import annotations

import inspect
import io
import sys
from contextlib import redirect_stdout

import pytest


# ---------------------------------------------------------------------------
# Per-CLI signature audit
# ---------------------------------------------------------------------------


def test_run_endogenous_chain_main_accepts_argv():
    from examples.reference_world import run_endogenous_chain as cli

    sig = inspect.signature(cli.main)
    assert "argv" in sig.parameters


def test_run_living_reference_world_main_accepts_argv():
    from examples.reference_world import run_living_reference_world as cli

    sig = inspect.signature(cli.main)
    assert "argv" in sig.parameters


# ---------------------------------------------------------------------------
# Hostile-argv smoke (the actual CI-reproduction)
# ---------------------------------------------------------------------------


_HOSTILE_ARGV = ["pytest", "-q", "tests/test_living_reference_world.py"]


def test_run_endogenous_chain_cli_ignores_pytest_argv(monkeypatch):
    """Reproduce the original CI failure mode: pytest's own argv
    contains -q. Calling cli.main([]) must not let argparse fall
    through to sys.argv."""
    from examples.reference_world import run_endogenous_chain as cli

    monkeypatch.setattr(sys, "argv", list(_HOSTILE_ARGV))
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main([])
    out = buf.getvalue()
    # Default mode prints the operational trace; without --markdown
    # the report sections must not appear.
    assert "[corporate]" in out
    assert "[review]" in out


def test_run_endogenous_chain_cli_with_markdown_under_hostile_argv(monkeypatch):
    from examples.reference_world import run_endogenous_chain as cli

    monkeypatch.setattr(sys, "argv", list(_HOSTILE_ARGV))
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["--markdown"])
    out = buf.getvalue()
    # --markdown mode appends the v1.8.15 ledger trace report.
    assert "# reference_endogenous_chain" in out


def test_run_living_reference_world_cli_ignores_pytest_argv(monkeypatch):
    """The exact failure mode that surfaced in CI for
    test_cli_smoke_prints_per_period_trace."""
    from examples.reference_world import run_living_reference_world as cli

    monkeypatch.setattr(sys, "argv", list(_HOSTILE_ARGV))
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main([])
    out = buf.getvalue()
    assert "[setup]" in out
    assert "[period 1]" in out
    assert "[ledger]" in out


def test_run_living_reference_world_cli_with_markdown_under_hostile_argv(
    monkeypatch,
):
    from examples.reference_world import run_living_reference_world as cli

    monkeypatch.setattr(sys, "argv", list(_HOSTILE_ARGV))
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["--markdown"])
    out = buf.getvalue()
    # The v1.9.1 report appends after the trace.
    assert "# living_reference_world" in out


def test_run_living_reference_world_cli_with_manifest_under_hostile_argv(
    monkeypatch, tmp_path
):
    from examples.reference_world import run_living_reference_world as cli

    monkeypatch.setattr(sys, "argv", list(_HOSTILE_ARGV))
    target = tmp_path / "manifest.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        cli.main(["--manifest", str(target)])
    assert target.is_file()
    out = buf.getvalue()
    assert "[manifest]" in out


# ---------------------------------------------------------------------------
# Negative pin: the original bug must crash if reproduced today
# ---------------------------------------------------------------------------


def test_calling_cli_main_with_no_argv_under_hostile_argv_raises(monkeypatch):
    """Sanity check that the failure mode is real. With argv=None
    and a hostile sys.argv containing '-q', the demo CLI's argparse
    rejects the unrecognized flag with SystemExit. This is the
    exact behavior that surfaced in CI before the fix.

    Tests in this repository must therefore *always* pass an
    explicit argv list to cli.main() — typically `[]` for the
    default path or `["--markdown"]` / `["--manifest", path]`
    for flagged paths.
    """
    from examples.reference_world import run_living_reference_world as cli

    monkeypatch.setattr(sys, "argv", list(_HOSTILE_ARGV))
    with pytest.raises(SystemExit):
        # No argv -> argparse falls through to sys.argv[1:] -> sees
        # "-q" and exits.
        cli.main()
