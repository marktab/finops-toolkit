"""Unit tests for the restatement (replace-on-write) logic.

Run: python -m pytest src/pilots/fabric-onelake/notebooks/tests/test_restatement.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from focus_pilot.restatement import (
    ImplausibleRestatement,
    charge_month_predicate,
    check_restatement_ratio,
)


# --- predicate ------------------------------------------------------------- #


def test_predicate_covers_every_month_in_the_batch() -> None:
    predicate = charge_month_predicate([date(2025, 6, 1), date(2025, 5, 1)])
    assert predicate == "x_ChargeMonth in (DATE'2025-05-01', DATE'2025-06-01')"


def test_predicate_honours_custom_column() -> None:
    predicate = charge_month_predicate([date(2025, 5, 1)], column="x_Month")
    assert predicate.startswith("x_Month in (")


def test_predicate_rejects_empty_month_list() -> None:
    # An empty predicate would either replace nothing or match everything.
    try:
        charge_month_predicate([])
    except ValueError:
        return
    raise AssertionError("Expected ValueError for an empty month list")


# --- shrink guard ---------------------------------------------------------- #


def test_ratio_accepts_a_normal_restatement() -> None:
    check_restatement_ratio(rows_removed=1000, rows_written=1010, min_ratio=0.5)


def test_ratio_accepts_a_modest_reduction() -> None:
    check_restatement_ratio(rows_removed=1000, rows_written=700, min_ratio=0.5)


def test_ratio_rejects_a_truncated_export() -> None:
    # replaceWhere cannot tell a real correction from a truncated export, and a
    # truncated export silently deletes good months.
    try:
        check_restatement_ratio(
            rows_removed=4_000_000,
            rows_written=400,
            min_ratio=0.5,
            months=[date(2025, 5, 1)],
        )
    except ImplausibleRestatement as exc:
        assert "2025-05" in str(exc)
        return
    raise AssertionError("Expected ImplausibleRestatement")


def test_ratio_skipped_on_first_load() -> None:
    check_restatement_ratio(rows_removed=0, rows_written=0, min_ratio=0.5)


def test_ratio_disabled_when_none() -> None:
    check_restatement_ratio(rows_removed=4_000_000, rows_written=1, min_ratio=None)


def _run_all() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()
