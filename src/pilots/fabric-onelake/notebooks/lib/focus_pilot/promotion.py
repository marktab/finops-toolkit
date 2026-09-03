"""DirectLake promotion decision and Z-order validation (Phase 6).

After one full billing cycle on the SQL endpoint, the accumulated
layout-precondition history - not a one-off "looks fast enough" judgment -
clears (or withholds) the DirectLake migration. This module turns that into
tested logic:

  * evaluate_directlake_promotion: aggregates the per-run gate history and only
    authorizes DirectLake when the table has continuously met the layout
    precondition across a window spanning at least one billing cycle.
  * recommend_zorder: compares the provisional Z-order columns against the
    pilot customer's ACTUAL dominant query filters and recommends keeping,
    revising, or - absent telemetry - explicitly leaving them unvalidated.

This is a layout-level authorization only. It does not exercise a Direct Lake
semantic model, so it cannot be the sole basis for a production migration.
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
            ``meetsLayoutPrecondition`` (bool) and ``evaluatedAtUtc`` (ISO 8601
            or datetime). When multiple evaluations occur on one day, the
            latest wins.
        cycle_days: Minimum observation span in days (one billing cycle).
        min_consecutive_ready_days: Required trailing run of passing days.
        now: Override for current time (testing).

    Returns:
        PromotionDecision with the verdict and human-readable reasons. Note that
        authorization here clears the *layout* history only; a Direct Lake
        migration additionally requires the model-level proof described in the
        pilot README.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []

    if not gate_rows:
        return PromotionDecision(False, 0, 0, ["No layout-precondition history; run the gate across a billing cycle first."])

    # Latest evaluation per UTC date.
    latest_by_day: dict[object, tuple[datetime, bool]] = {}
    for row in gate_rows:
        ts = _parse_iso(row["evaluatedAtUtc"])
        day = ts.date()
        ready = bool(row["meetsLayoutPrecondition"])
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
    """Recommended Z-order columns vs. the provisional contract value.

    ``status`` is the authoritative field. ``matches_current`` is None when no
    telemetry was available, because "we have no evidence" is not "the current
    columns are correct" - recording the latter would let the provisional
    Z-order be locked in on the strength of a missing table.
    """

    recommended: list[str]
    current: list[str]
    matches_current: bool | None
    status: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "current": self.current,
            "matches_current": self.matches_current,
            "status": self.status,
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
        ZorderRecommendation with ``status`` one of:
          * ``"validated"``  - telemetry confirms the current columns; lock in.
          * ``"revise"``     - telemetry disagrees with the current columns.
          * ``"unvalidated"`` - no telemetry; the Z-order remains provisional.
    """
    if not filter_column_counts:
        return ZorderRecommendation(
            recommended=list(current_zorder),
            current=list(current_zorder),
            matches_current=None,
            status="unvalidated",
            reasons=[
                "No query-filter telemetry available, so the provisional Z-order is "
                "UNVALIDATED - not confirmed. Populate the query-filter statistics "
                "table over a full billing cycle before locking these columns in."
            ],
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
        status="validated" if matches else "revise",
        reasons=reasons,
    )
