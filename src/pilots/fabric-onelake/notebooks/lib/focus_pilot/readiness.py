"""DirectLake readiness gate (Decision 4).

DirectLake silently falls back to DirectQuery (10-50x slower, no error) when a
table is not in a supported state. That is the worst failure mode: discovered by
end users in production. This module turns the go/no-go into an artifact by
evaluating four measurable conditions. Its output is the ONLY thing that
authorizes a DirectLake migration; until all four pass, Power BI stays on the
SQL endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass
class ReadinessResult:
    """Outcome of the readiness evaluation."""

    is_ready: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "is_ready": self.is_ready,
            "checks": self.checks,
            "reasons": self.reasons,
        }


def evaluate_directlake_readiness(
    *,
    compaction_healthy: bool,
    unsupported_type_columns: list[str],
    row_count: int,
    max_rows: int,
    file_count: int,
    max_files: int,
    avg_file_size_mb: float,
    min_avg_file_size_mb: float,
) -> ReadinessResult:
    """Evaluate the four measurable DirectLake readiness conditions.

    Conditions (all must pass):
      1. Compaction SLA is currently healthy (table is not fragmented/stale).
      2. No DirectLake-incompatible (complex/nested) column types are present.
      3. Table volume is within DirectLake guardrails (row and file counts).
      4. Average file size meets the floor, so DirectLake can memory-map
         efficiently rather than falling back.

    Args:
        compaction_healthy: Result of the D2 compaction SLA check.
        unsupported_type_columns: Columns with complex/nested types, if any.
        row_count / max_rows: Observed rows and the DirectLake guardrail.
        file_count / max_files: Observed files and the guardrail.
        avg_file_size_mb / min_avg_file_size_mb: Observed and required minimum.

    Returns:
        ReadinessResult with per-check booleans and human-readable reasons.
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
        reasons.append(f"Row count {row_count} exceeds DirectLake guardrail {max_rows}.")
    if not within_files:
        reasons.append(f"File count {file_count} exceeds DirectLake guardrail {max_files}.")

    checks["avg_file_size_ok"] = avg_file_size_mb >= min_avg_file_size_mb
    if not checks["avg_file_size_ok"]:
        reasons.append(
            f"Average file size {avg_file_size_mb}MB is below the "
            f"{min_avg_file_size_mb}MB floor for efficient DirectLake."
        )

    is_ready = all(checks.values())
    return ReadinessResult(is_ready=is_ready, checks=checks, reasons=reasons)


def directlake_guardrails(contract: Mapping) -> dict:
    """Read optional DirectLake guardrails from the storage contract.

    Falls back to conservative SKU-agnostic defaults when not specified.
    """
    directlake = contract.get("directLake", {}) if isinstance(contract, Mapping) else {}
    return {
        "max_rows": directlake.get("maxRows", 1_500_000_000),
        "max_files": directlake.get("maxFiles", 10_000),
        "min_avg_file_size_mb": directlake.get("minAvgFileSizeMB", 64),
    }
