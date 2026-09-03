"""Unit tests for the Phase 6 promotion + Z-order validation logic.

Run: python src/pilots/fabric-onelake/notebooks/tests/test_promotion.py
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from focus_pilot.promotion import (
    evaluate_directlake_promotion,
    recommend_zorder,
)

_BASE = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _gate_history(days: int, ready_flags=None):
    """One gate row per day for `days` days ending at _BASE + days."""
    rows = []
    for i in range(days):
        ready = True if ready_flags is None else ready_flags[i]
        rows.append(
            {
                "meetsLayoutPrecondition": ready,
                "evaluatedAtUtc": (_BASE + timedelta(days=i)).isoformat(),
            }
        )
    return rows


# --- promotion ------------------------------------------------------------- #


def test_promotion_authorized_after_full_cycle_all_ready() -> None:
    rows = _gate_history(30)  # 30-day span, all ready
    decision = evaluate_directlake_promotion(rows, cycle_days=28, min_consecutive_ready_days=7)
    assert decision.authorized is True
    assert decision.consecutive_ready_days == 30


def test_promotion_blocked_when_window_too_short() -> None:
    rows = _gate_history(10)  # only 10-day span
    decision = evaluate_directlake_promotion(rows, cycle_days=28, min_consecutive_ready_days=7)
    assert decision.authorized is False
    assert any("billing cycle" in r for r in decision.reasons)

def test_promotion_blocked_on_recent_regression() -> None:
    flags = [True] * 30
    flags[-1] = False  # most recent day failed
    rows = _gate_history(30, flags)
    decision = evaluate_directlake_promotion(rows, cycle_days=28, min_consecutive_ready_days=7)
    assert decision.authorized is False
    assert decision.consecutive_ready_days == 0


def test_promotion_blocked_when_not_enough_consecutive() -> None:
    flags = [True] * 30
    flags[-3] = False  # break 5 days before the end -> only 2 trailing ready
    rows = _gate_history(30, flags)
    decision = evaluate_directlake_promotion(rows, cycle_days=28, min_consecutive_ready_days=7)
    assert decision.authorized is False
    assert decision.consecutive_ready_days == 2


def test_promotion_empty_history() -> None:
    decision = evaluate_directlake_promotion([], cycle_days=28)
    assert decision.authorized is False
    assert decision.observed_days == 0


def test_promotion_latest_per_day_wins() -> None:
    # Two evaluations on the same final day: a later passing one supersedes an earlier block.
    rows = _gate_history(30)
    last_day = _BASE + timedelta(days=29)
    rows.append({"meetsLayoutPrecondition": False, "evaluatedAtUtc": last_day.replace(hour=1).isoformat()})
    rows.append({"meetsLayoutPrecondition": True, "evaluatedAtUtc": last_day.replace(hour=23).isoformat()})
    decision = evaluate_directlake_promotion(rows, cycle_days=28, min_consecutive_ready_days=7)
    assert decision.authorized is True


# --- Z-order --------------------------------------------------------------- #


def test_zorder_matches_provisional() -> None:
    counts = {"BillingAccountId": 100, "SubAccountId": 80, "ServiceName": 10}
    rec = recommend_zorder(counts, ["BillingAccountId", "SubAccountId"])
    assert rec.status == "validated"
    assert rec.matches_current is True
    assert set(rec.recommended) == {"BillingAccountId", "SubAccountId"}


def test_zorder_recommends_revision() -> None:
    counts = {"ResourceId": 200, "ServiceName": 150, "BillingAccountId": 5}
    rec = recommend_zorder(counts, ["BillingAccountId", "SubAccountId"])
    assert rec.status == "revise"
    assert rec.matches_current is False
    assert rec.recommended == ["ResourceId", "ServiceName"]


def test_zorder_without_telemetry_is_unvalidated_not_a_match() -> None:
    # Absent evidence is not confirming evidence. Reporting a match here would let
    # the provisional Z-order be locked in on the strength of a missing table.
    rec = recommend_zorder({}, ["BillingAccountId", "SubAccountId"])
    assert rec.status == "unvalidated"
    assert rec.matches_current is None
    assert rec.recommended == ["BillingAccountId", "SubAccountId"]


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
