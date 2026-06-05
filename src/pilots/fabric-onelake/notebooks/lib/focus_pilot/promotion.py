"""DirectLake promotion decision and Z-order validation (Phase 6).

After one full billing cycle on the SQL endpoint, the accumulated readiness-gate
history - not a one-off "looks fast enough" judgment - authorizes (or withholds)
the DirectLake migration. This module turns that into tested logic:

  * evaluate_directlake_promotion: aggregates the per-run gate history and only
    authorizes DirectLake when the table has been continuously ready across a
    sustained window that spans at least one billing cycle.
  * recommend_zorder: compares the provisional Z-order columns against the
    pilot customer's ACTUAL dominant query filters and recommends keeping or
    revising them (the deck's explicit Phase 6 follow-up).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _parse_iso(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class PromotionDecision:
    """Whether a DirectLake migration is authorized, and why."""

    authorized: bool
    observed_days: int
    consecutive_ready_days: int
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "authorized": self.authorized,
            "observed_days": self.observed_days,
            "consecutive_ready_days": self.consecutive_ready_days,
            "reasons": self.reasons,
        }


def evaluate_directlake_promotion(
    gate_rows: list[dict],
    *,
    cycle_days: int = 28,
    min_consecutive_ready_days: int = 7,
    now: datetime | None = None,
) -> PromotionDecision:
    """Decide whether to promote to DirectLake from the gate history.

    Authorization requires ALL of:
      1. The observation window (earliest to latest gate evaluation) spans at
         least ``cycle_days`` - i.e. at least one billing cycle was observed on
         the SQL endpoint before promoting.
      2. The most recent ``min_consecutive_ready_days`` distinct days each ended
         in a ready state (no recent regressions).

    Args:
        gate_rows: Rows from the _pilot_directlake_gate table, each with
            ``isReady`` (bool) and ``evaluatedAtUtc`` (ISO 8601 or datetime).
            When multiple evaluations occur on one day, the latest wins.
        cycle_days: Minimum observation span in days (one billing cycle).
        min_consecutive_ready_days: Required trailing run of ready days.
        now: Override for current time (testing).

    Returns:
        PromotionDecision with the verdict and human-readable reasons.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    if not gate_rows:
        return PromotionDecision(False, 0, 0, ["No readiness-gate history; run the gate across a billing cycle first."])

    # Latest evaluation per UTC date.
    latest_by_day: dict[object, tuple[datetime, bool]] = {}
    for row in gate_rows:
        ts = _parse_iso(row["evaluatedAtUtc"])
        day = ts.date()
        ready = bool(row["isReady"])
        if day not in latest_by_day or ts > latest_by_day[day][0]:
            latest_by_day[day] = (ts, ready)

    days_sorted = sorted(latest_by_day.keys())
    observed_days = len(days_sorted)
    span_days = (days_sorted[-1] - days_sorted[0]).days

    # Condition 1: observed at least one billing cycle.
    spans_cycle = span_days >= cycle_days
    if not spans_cycle:
        reasons.append(
            f"Observation window spans {span_days} day(s); need at least {cycle_days} "
            "(one billing cycle) on the SQL endpoint before promoting."
        )

    # Condition 2: trailing run of ready days (most recent first).
    consecutive = 0
    for day in reversed(days_sorted):
        if latest_by_day[day][1]:
            consecutive += 1
        else:
            break
    enough_ready = consecutive >= min_consecutive_ready_days
    if not enough_ready:
        reasons.append(
            f"Only {consecutive} consecutive ready day(s); need {min_consecutive_ready_days}."
        )

    authorized = spans_cycle and enough_ready
    if authorized:
        reasons.append(
            f"DirectLake authorized: {consecutive} consecutive ready days over a "
            f"{span_days}-day window."
        )

    return PromotionDecision(
        authorized=authorized,
        observed_days=observed_days,
        consecutive_ready_days=consecutive,
        reasons=reasons,
    )


@dataclass
class ZorderRecommendation:
    """Recommended Z-order columns vs. the provisional contract value."""

    recommended: list[str]
    current: list[str]
    matches_current: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "current": self.current,
            "matches_current": self.matches_current,
            "reasons": self.reasons,
        }


def recommend_zorder(
    filter_column_counts: dict[str, int],
    current_zorder: list[str],
    *,
    top_n: int = 2,
) -> ZorderRecommendation:
    """Recommend Z-order columns from observed query filter frequencies.

    The provisional Z-order (BillingAccountId, SubscriptionId) is a reasonable
    default but must be validated against the pilot customer's actual dominant
    query filters before being locked in. This compares the top filtered columns
    by frequency to the current contract value.

    Args:
        filter_column_counts: Column name -> number of queries that filtered on
            it during the observation window.
        current_zorder: The Z-order columns currently set in the D2 contract.
        top_n: How many columns to recommend (Z-order is most effective on a
            small number of high-cardinality filter columns).

    Returns:
        ZorderRecommendation. ``matches_current`` is True when the recommended
        set equals the current set (order-insensitive), meaning the provisional
        choice is validated and can be locked in.
    """
    if not filter_column_counts:
        return ZorderRecommendation(
            recommended=list(current_zorder),
            current=list(current_zorder),
            matches_current=True,
            reasons=["No query-filter telemetry; cannot validate. Keeping provisional Z-order."],
        )

    ranked = [col for col, _ in Counter(filter_column_counts).most_common(top_n)]
    matches = set(ranked) == set(current_zorder)
    reasons: list[str] = []
    if matches:
        reasons.append("Provisional Z-order matches the dominant query filters; safe to lock in.")
    else:
        reasons.append(
            f"Dominant query filters {ranked} differ from current {list(current_zorder)}; "
            "revise the storage contract Z-order and re-run OPTIMIZE (non-destructive)."
        )
    return ZorderRecommendation(
        recommended=ranked,
        current=list(current_zorder),
        matches_current=matches,
        reasons=reasons,
    )
