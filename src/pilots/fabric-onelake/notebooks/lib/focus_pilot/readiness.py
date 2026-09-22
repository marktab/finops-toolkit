"""Direct Lake layout precondition (Decision 4).

Passing means only that the listed layout checks passed. This diagnostic does
not deploy or query a semantic model, verify V-Order coverage, or establish
Direct Lake eligibility or performance. Direct Lake on OneLake does not fall
back through the SQL analytics endpoint. Direct Lake on SQL fallback depends
on source constructs, security, limits, and DirectLakeBehavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
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
    assessment_metadata: dict[str, str] = field(default_factory=lambda: {
        "assessmentScope": "listedChecksOnly",
        "vOrderVerification": "notPerformed",
    })

    def as_dict(self) -> dict:
        return {
            "meets_precondition": self.meets_precondition,
            "checks": self.checks,
            "reasons": self.reasons,
            "assessmentMetadata": self.assessment_metadata,
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
      4. Average file size meets the operator's workload tuning target.

    These checks are not a sufficient platform eligibility gate. V-Order
    verification is not performed (inherited settings may already apply it).

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
            f"{min_avg_file_size_mb}MB workload tuning target."
        )

    meets = all(checks.values())
    return LayoutPreconditionResult(meets_precondition=meets, checks=checks, reasons=reasons)


def directlake_guardrails(contract: Mapping) -> dict:
    """Read the Direct Lake guardrails from the storage contract.

    There are deliberately no defaults. Row and file limits must be selected
    for the intended capacity and Direct Lake mode. The average-file-size
    target is workload tuning, not a published platform eligibility guardrail.

    Raises:
        GuardrailsNotConfigured: if the contract has no ``directLake`` block or
            any required limit is unset.
    """
    directlake = contract.get("directLake") if isinstance(contract, Mapping) else None
    if not isinstance(directlake, Mapping):
        raise GuardrailsNotConfigured(
            "The storage contract has no 'directLake' block. Direct Lake limits are "
            "per-capacity-SKU and are not defaulted; record the limits published for "
            "your Fabric SKU and the workload file-size target before this diagnostic."
        )

    missing = [key for key in _REQUIRED_GUARDRAILS if directlake.get(key) is None]
    if missing:
        raise GuardrailsNotConfigured(
            f"Direct Lake guardrail(s) not configured: {sorted(missing)}. These are "
            "required settings with no default; select row/file limits for your "
            "Fabric SKU and mode, and a workload file-size target."
        )

    return {
        "max_rows": directlake["maxRows"],
        "max_files": directlake["maxFiles"],
        "min_avg_file_size_mb": directlake["minAvgFileSizeMB"],
    }


def latest_compaction_evidence(rows, *, now: datetime) -> dict:
    """Select scoped evidence deterministically; naive timestamps mean UTC."""
    from contract_validator import ContractViolation, normalize_timestamp_utc

    clock = normalize_timestamp_utc(now, "evaluation clock")
    candidates = []
    for row in rows:
        record = row.asDict() if hasattr(row, "asDict") else dict(row)
        timestamp = normalize_timestamp_utc(
            record.get("lastRunTimestampUtc"), "compaction timestamp"
        )
        if timestamp > clock:
            raise ContractViolation("Compaction evidence is future-dated.")
        record["lastRunTimestampUtc"] = timestamp
        candidates.append(record)
    if not candidates:
        raise ContractViolation("No compaction evidence for the target table.")
    latest_time = max(row["lastRunTimestampUtc"] for row in candidates)
    latest = [row for row in candidates if row["lastRunTimestampUtc"] == latest_time]
    relevant = ("avgFileSizeMBAfter", "smallFileFractionAfter", "lastRunStatus")
    values = [tuple(row.get(key) for key in relevant) for row in latest]
    if any(value != values[0] for value in values[1:]):
        raise ContractViolation("Conflicting latest compaction evidence at the same UTC timestamp.")
    if latest[0].get("lastRunStatus") != "success":
        raise ContractViolation("Latest compaction evidence does not record a successful run.")
    return {key: latest[0].get(key) for key in (*relevant, "lastRunTimestampUtc")}


def read_latest_compaction_evidence(spark, table_name: str, metrics_table: str, *, now: datetime) -> dict:
    """Filter in Spark before collecting evidence in the current Lakehouse.

    Only simple, unqualified identifiers are supported. Catalog resolution must
    agree with the active Spark analyzer's case semantics; ambiguous catalog
    matches and cross-Lakehouse identifiers are not supported.
    """
    from contract_validator import ContractViolation

    for name in (table_name, metrics_table):
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ContractViolation("Use an unqualified Lakehouse-local table identifier.")
    sensitive = spark.conf.get("spark.sql.caseSensitive").lower() == "true"
    def equivalent(left, right):
        return left == right if sensitive else left.lower() == right.lower()

    matches = [table for table in spark.catalog.listTables() if equivalent(table.name, table_name)]
    if len(matches) != 1 or matches[0].isTemporary:
        raise ContractViolation("Target table identity is missing, temporary, or ambiguous in the current catalog.")
    resolved = spark.catalog.getTable(table_name)
    if resolved.isTemporary or not equivalent(resolved.name, matches[0].name):
        raise ContractViolation("Catalog resolution disagrees with Spark case semantics.")
    identity = resolved.name
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identity):
        raise ContractViolation("Resolved table identity is not a supported local identifier.")
    alternate = identity.swapcase()
    if alternate != identity:
        alias_exists = spark.catalog.tableExists(alternate)
        alias_is_target = alias_exists and spark.catalog.getTable(alternate).name == identity
        if alias_is_target == sensitive:
            raise ContractViolation("Catalog case resolution disagrees with Spark case semantics.")
    predicate = (
        f"tableName = '{identity}'" if sensitive
        else f"lower(tableName) = '{identity.lower()}'"
    )
    rows = spark.read.table(metrics_table).where(predicate).collect()
    return latest_compaction_evidence(rows, now=now)


def append_layout_assessment(spark, gate_table: str, row: Mapping) -> None:
    """Append metadata with checked, per-write additive Delta schema evolution.

    Legacy rows remain unchanged with unknown (null) scope provenance.
    Permission and storage errors propagate rather than becoming a pass.
    """
    from contract_validator import ContractViolation

    expected = {
        "tableName": "string",
        "meetsLayoutPrecondition": "boolean",
        "checks": "string",
        "reasons": "string",
        "evaluatedAtUtc": "string",
        "assessmentMetadata": "string",
    }
    if set(row) != set(expected):
        raise ContractViolation("Assessment append must contain exactly the expected gate fields.")
    metadata = json.loads(row["assessmentMetadata"])
    if metadata != {"assessmentScope": "listedChecksOnly", "vOrderVerification": "notPerformed"}:
        raise ContractViolation("Assessment metadata does not describe the listed-check diagnostic.")
    if spark.catalog.tableExists(gate_table):
        fields = spark.table(gate_table).schema.fields
        actual = {field.name: field.dataType.simpleString() for field in fields}
        legacy = {key: value for key, value in expected.items() if key != "assessmentMetadata"}
        if len(fields) != len(actual) or actual not in (legacy, expected):
            raise ContractViolation("Existing gate table has an incompatible schema; no append performed.")
        if any(field.name == "assessmentMetadata" and not field.nullable for field in fields):
            raise ContractViolation("Gate assessmentMetadata must be nullable STRING.")
    schema = ", ".join(f"{name} {kind}" for name, kind in expected.items())
    spark.createDataFrame([dict(row)], schema=schema).write.format("delta").mode("append").option(
        "mergeSchema", "true"
    ).saveAsTable(gate_table)
