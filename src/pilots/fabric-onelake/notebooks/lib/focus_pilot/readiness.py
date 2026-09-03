"""Direct Lake layout precondition (Decision 4).

Direct Lake on SQL silently falls back to DirectQuery (10-50x slower, no error)
when a table is not in a supported state. That is the worst failure mode:
discovered by end users in production.

This module evaluates the measurable *table-layout* conditions that must hold
before a Direct Lake semantic model is worth building. It is deliberately named
a precondition, not a readiness verdict: it never deploys or queries a semantic
model, so it cannot observe relationships, one-side uniqueness, RLS/OLS and
fixed identity, framing behaviour, cold-query latency, memory pressure, or an
actual fallback. Passing here means "the table layout no longer disqualifies
Direct Lake", not "Direct Lake will perform". Promotion still requires a
model-level proof against real data - see the pilot README graduation criteria.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


class GuardrailsNotConfigured(Exception):
    """The storage contract does not carry usable Direct Lake guardrails."""


_REQUIRED_GUARDRAILS = ("maxRows", "maxFiles", "minAvgFileSizeMB")


@dataclass
class LayoutPreconditionResult:
    """Outcome of the layout evaluation."""

    meets_precondition: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "meets_precondition": self.meets_precondition,
            "checks": self.checks,
            "reasons": self.reasons,
        }


def evaluate_directlake_layout_precondition(
    *,
    compaction_healthy: bool,
    unsupported_type_columns: list[str],
    row_count: int,
    max_rows: int,
    file_count: int,
    max_files: int,
    avg_file_size_mb: float,
    min_avg_file_size_mb: float,
) -> LayoutPreconditionResult:
    """Evaluate the four measurable Direct Lake layout conditions.

    Conditions (all must pass):
      1. Compaction SLA is currently healthy (table is not fragmented/stale).
      2. No Direct Lake-incompatible (complex/nested) column types are present.
      3. Table volume is within the capacity's guardrails (row and file counts).
      4. Average file size meets the floor, so Direct Lake can memory-map
         efficiently rather than falling back.

    Args:
        compaction_healthy: Result of the D2 compaction SLA check.
        unsupported_type_columns: Columns with complex/nested types, if any.
        row_count / max_rows: Observed rows and the capacity's guardrail.
        file_count / max_files: Observed files and the guardrail.
        avg_file_size_mb / min_avg_file_size_mb: Observed and required minimum.

    Returns:
        LayoutPreconditionResult with per-check booleans and readable reasons.
    """
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    checks["compaction_healthy"] = bool(compaction_healthy)
    if not checks["compaction_healthy"]:
        reasons.append("Compaction SLA is not healthy; table is fragmented or stale.")

    checks["no_unsupported_types"] = len(unsupported_type_columns) == 0
    if not checks["no_unsupported_types"]:
        reasons.append(
            "Unsupported (complex/nested) column type(s) present: "
            f"{sorted(unsupported_type_columns)}."
        )

    within_rows = row_count <= max_rows
    within_files = file_count <= max_files
    checks["within_volume_guardrails"] = within_rows and within_files
    if not within_rows:
        reasons.append(f"Row count {row_count} exceeds the capacity guardrail {max_rows}.")
    if not within_files:
        reasons.append(f"File count {file_count} exceeds the capacity guardrail {max_files}.")

    checks["avg_file_size_ok"] = avg_file_size_mb >= min_avg_file_size_mb
    if not checks["avg_file_size_ok"]:
        reasons.append(
            f"Average file size {avg_file_size_mb}MB is below the "
            f"{min_avg_file_size_mb}MB floor for efficient Direct Lake."
        )

    meets = all(checks.values())
    return LayoutPreconditionResult(meets_precondition=meets, checks=checks, reasons=reasons)


def directlake_guardrails(contract: Mapping) -> dict:
    """Read the Direct Lake guardrails from the storage contract.

    There are deliberately NO defaults. Direct Lake row, file, and size limits
    vary by Fabric capacity SKU, and a built-in default is wrong for most
    capacities in both directions - a permissive one produces a false pass on a
    small SKU, which is exactly the silent failure this gate exists to prevent.
    The operator must record the limits published for their own SKU.

    Raises:
        GuardrailsNotConfigured: if the contract has no ``directLake`` block or
            any required limit is unset.
    """
    directlake = contract.get("directLake") if isinstance(contract, Mapping) else None
    if not isinstance(directlake, Mapping):
        raise GuardrailsNotConfigured(
            "The storage contract has no 'directLake' block. Direct Lake limits are "
            "per-capacity-SKU and are not defaulted; record the limits published for "
            "your Fabric SKU before running the layout precondition."
        )

    missing = [key for key in _REQUIRED_GUARDRAILS if directlake.get(key) is None]
    if missing:
        raise GuardrailsNotConfigured(
            f"Direct Lake guardrail(s) not configured: {sorted(missing)}. These are "
            "per-capacity-SKU limits with no safe default; look up the values published "
            "for your Fabric SKU and set them in the storage contract."
        )

    return {
        "max_rows": directlake["maxRows"],
        "max_files": directlake["maxFiles"],
        "min_avg_file_size_mb": directlake["minAvgFileSizeMB"],
    }
