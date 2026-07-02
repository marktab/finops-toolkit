"""Contract enforcement for the Fabric/OneLake FinOps pilot.

This module is the executable form of the pilot's governing principle: every
contract is *enforced by code that fails loudly*, never merely asserted in
documentation. It loads the D1 logical schema contract and the D2 physical
storage contract and validates real inputs against them.

The functions are intentionally Spark-agnostic so they can be unit-tested
without a cluster. The Phase 3 ingestion / compaction notebooks adapt their
Spark DataFrame schema and run metrics into the plain inputs these functions
take (a column->type mapping, a FOCUS version string, a metrics dict).

Raises ContractViolation on any hard-fail rule defined in the contract.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


class ContractViolation(Exception):
    """A hard-fail rule in a contract was violated. Stops the pipeline."""


@dataclass
class ValidationResult:
    """Outcome of a validation pass. Warnings do not stop the pipeline."""

    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# D1 — logical FOCUS schema contract
# --------------------------------------------------------------------------- #


def load_schema_contract(contract_path: str | Path) -> dict:
    """Load the D1 schema contract from disk."""
    return _load_json(Path(contract_path))


def resolve_column_source(contract_path: str | Path, contract: dict) -> dict:
    """Load the canonical column-source file the D1 contract references.

    Enforces the source-integrity rule when an expected hash is pinned: a
    changed upstream schema source must fail before the pilot consumes it.
    """
    base = Path(contract_path).parent
    source_rel = contract["columnSource"]["path"]
    source_path = (base / source_rel).resolve()

    integrity = contract["columnSource"].get("integrity", {})
    expected = (integrity.get("expected") or "").strip()
    if expected and contract["enforcement"].get("failOnColumnSourceIntegrityMismatch", True):
        actual = _sha256(source_path)
        if actual != expected:
            raise ContractViolation(
                f"Column source integrity mismatch for {source_path.name}: "
                f"expected {expected}, got {actual}. The upstream schema source "
                "changed; re-review the contract before consuming."
            )

    return _load_json(source_path)


def validate_focus_schema(
    actual_columns: Mapping[str, str],
    actual_focus_version: str,
    contract_path: str | Path,
) -> ValidationResult:
    """Validate observed data against the D1 logical schema contract.

    Args:
        actual_columns: Mapping of column name -> logical type for the data
            being ingested. Logical types must be the contract's mapped types
            (e.g. "string", "timestamp", "decimal", "boolean").
        actual_focus_version: FOCUS version reported by the upstream transform.
        contract_path: Path to focus-schema.contract.json.

    Returns:
        ValidationResult with any non-fatal warnings.

    Raises:
        ContractViolation: on any hard-fail rule.
    """
    contract = load_schema_contract(contract_path)
    enforcement = contract["enforcement"]
    result = ValidationResult()

    # FOCUS version pin.
    pinned_version = contract["focus"]["version"]
    if enforcement.get("failOnFocusVersionMismatch", True):
        if str(actual_focus_version) != str(pinned_version):
            raise ContractViolation(
                f"FOCUS version mismatch: contract pins {pinned_version}, "
                f"upstream produced {actual_focus_version}."
            )

    # Column source (and integrity) — establishes the universe of known columns.
    source = resolve_column_source(contract_path, contract)
    name_field = contract["columnSource"]["columnNameField"]
    type_field = contract["columnSource"]["dataTypeField"]
    type_map = contract["typeMapping"]

    expected_types: dict[str, str] = {}
    for column in source["Columns"]:
        focus_type = column[type_field]
        if focus_type not in type_map:
            raise ContractViolation(
                f"Column '{column[name_field]}' has FOCUS type '{focus_type}' "
                "with no entry in the contract typeMapping."
            )
        expected_types[column[name_field]] = type_map[focus_type]

    known_columns = set(expected_types)

    # Required columns must be present.
    if enforcement.get("failOnMissingRequiredColumn", True):
        missing = [c for c in contract["requiredColumns"]["columns"] if c not in actual_columns]
        if missing:
            raise ContractViolation(
                f"Required column(s) missing from upstream output: {sorted(missing)}."
            )

    # Type checks for known columns that are present.
    if enforcement.get("failOnTypeMismatch", True):
        mismatches = []
        for name, actual_type in actual_columns.items():
            expected = expected_types.get(name)
            if expected is not None and actual_type != expected:
                mismatches.append(f"{name}: expected {expected}, got {actual_type}")
        if mismatches:
            raise ContractViolation("Type mismatch(es): " + "; ".join(sorted(mismatches)))

    # Unexpected extra columns: tolerated (additive growth) but surfaced.
    if contract["enforcement"].get("onUnexpectedExtraColumn") == "warn":
        extras = sorted(set(actual_columns) - known_columns)
        if extras:
            result.warn(f"Unexpected extra column(s) (tolerated): {extras}")

    return result


def validate_non_null(
    null_counts: Mapping[str, int],
    contract_path: str | Path,
) -> ValidationResult:
    """Validate that non-nullable columns contain no nulls.

    Args:
        null_counts: Mapping of column name -> count of null values observed.
        contract_path: Path to focus-schema.contract.json.

    Raises:
        ContractViolation: if any non-nullable column has a null.
    """
    contract = load_schema_contract(contract_path)
    result = ValidationResult()
    if not contract["enforcement"].get("failOnNullInNonNullableColumn", True):
        return result

    offenders = {
        name: null_counts.get(name, 0)
        for name in contract["nonNullableColumns"]["columns"]
        if null_counts.get(name, 0) > 0
    }
    if offenders:
        raise ContractViolation(
            "Null value(s) found in non-nullable column(s): "
            + ", ".join(f"{k}={v}" for k, v in sorted(offenders.items()))
        )
    return result


# --------------------------------------------------------------------------- #
# D2 — physical storage / compaction contract
# --------------------------------------------------------------------------- #


def load_storage_contract(contract_path: str | Path) -> dict:
    """Load the D2 storage-layout contract from disk."""
    return _load_json(Path(contract_path))


def validate_compaction_sla(
    metrics: Mapping[str, object],
    contract_path: str | Path,
    now: datetime | None = None,
    sla_overrides: Mapping[str, object] | None = None,
) -> ValidationResult:
    """Validate the latest compaction run against the D2 SLA.

    A missed run or a fragmented table is a hard fail so it pages someone
    instead of silently degrading queries and the DirectLake gate.

    Args:
        metrics: Latest compaction metrics. Recognized keys:
            lastRunTimestampUtc (ISO 8601 str or datetime),
            avgFileSizeMBAfter (number),
            smallFileFractionAfter (number, 0..1).
        contract_path: Path to storage-layout.contract.json.
        now: Override for the current time (testing). Defaults to UTC now.
        sla_overrides: Optional per-run overrides merged over the contract SLA
            thresholds. Intended for small pilot/test datasets that cannot reach
            the production file-size floor; production runs pass nothing here so
            the contract's real thresholds apply.

    Raises:
        ContractViolation: on any breached SLA threshold.
    """
    contract = load_storage_contract(contract_path)
    compaction = contract["compaction"]
    sla = compaction["sla"]
    if sla_overrides:
        sla = {**sla, **sla_overrides}
    enforcement = contract["enforcement"]
    now = now or datetime.now(timezone.utc)
    result = ValidationResult()

    # Staleness — has compaction run within the allowed window?
    if enforcement.get("failOnStaleCompaction", True):
        raw_ts = metrics.get("lastRunTimestampUtc")
        if raw_ts is None:
            raise ContractViolation(
                "Compaction has no recorded last-run timestamp; treat as never run."
            )
        last_run = raw_ts if isinstance(raw_ts, datetime) else _parse_iso(str(raw_ts))
        if last_run.tzinfo is None:
            last_run = last_run.replace(tzinfo=timezone.utc)
        hours_since = (now - last_run).total_seconds() / 3600.0
        if hours_since > sla["maxHoursSinceLastSuccessfulRun"]:
            raise ContractViolation(
                f"Compaction is stale: {hours_since:.1f}h since last run exceeds "
                f"SLA of {sla['maxHoursSinceLastSuccessfulRun']}h."
            )

    # Average file size floor.
    if enforcement.get("failOnAvgFileSizeBelowMin", True):
        avg_size = metrics.get("avgFileSizeMBAfter")
        if avg_size is not None and avg_size < sla["minAvgFileSizeMB"]:
            raise ContractViolation(
                f"Average file size {avg_size}MB is below SLA floor "
                f"{sla['minAvgFileSizeMB']}MB; table is fragmented."
            )

    # Small-file fraction ceiling.
    if enforcement.get("failOnSmallFileFractionExceeded", True):
        fraction = metrics.get("smallFileFractionAfter")
        if fraction is not None and fraction > sla["maxSmallFileFraction"]:
            raise ContractViolation(
                f"Small-file fraction {fraction:.2%} exceeds SLA ceiling "
                f"{sla['maxSmallFileFraction']:.2%}."
            )

    # Provisional Z-order reminder — surfaced, not fatal.
    if contract["zorder"].get("status") == "provisional" and enforcement.get(
        "warnOnProvisionalZorderUnvalidated", True
    ):
        result.warn(
            "Z-order columns are still provisional "
            f"({contract['zorder']['columns']}); validate against real query "
            "filters before locking in (Phase 6)."
        )

    return result


def validate_row_conservation(
    input_count: int,
    output_count: int,
    contract_path: str | Path,
    stage: str = "write",
) -> ValidationResult:
    """Validate that a single materialization hop conserves row count.

    The pilot copies/appends already-normalized FOCUS data; it does not
    transform it (KQL stays the single transform owner, Decision 1). A hop that
    changes the row count is therefore a silent corruption, not a valid result.
    Real hub failures show up exactly this way with no error surfaced: extents
    lost during multi-file ingestion, or rows dropped when a manifest row count
    is null. This asserts input rows in == output rows out, within the contract's
    (default zero) tolerance, and fails loudly on any drift so the pipeline stops
    instead of feeding wrong totals downstream.

    Args:
        input_count: Rows read into the hop (e.g. source parquet, or staging).
        output_count: Rows written out of the hop (e.g. staged copy, or the
            Delta append's numOutputRows).
        contract_path: Path to storage-layout.contract.json.
        stage: Human-readable label for the hop, used in the error message.

    Raises:
        ContractViolation: on a negative count or on drift beyond the tolerance.
    """
    contract = load_storage_contract(contract_path)
    result = ValidationResult()
    if not contract["enforcement"].get("failOnRowCountDrift", True):
        return result

    if input_count < 0 or output_count < 0:
        raise ContractViolation(
            f"Row conservation at '{stage}' hop received a negative count: "
            f"in={input_count}, out={output_count}."
        )

    tolerance_fraction = float(
        contract.get("rowConservation", {}).get("maxRowCountDriftFraction", 0.0)
    )
    drift = abs(output_count - input_count)
    allowed = input_count * tolerance_fraction
    if drift > allowed:
        raise ContractViolation(
            f"Row count drift at '{stage}' hop: {input_count} row(s) in, "
            f"{output_count} out (drift {drift}, allowed {allowed:g}). The pilot "
            "only copies/appends FOCUS data, so a changed count is a silent loss "
            "or duplication — stopping before it corrupts cost totals."
        )
    return result


def validate_batch_completeness(
    expected_count: int,
    observed_count: int,
    contract_path: str | Path,
    stage: str = "read",
) -> ValidationResult:
    """Validate that a hop consumed the COMPLETE batch, not a partial listing.

    Notebook 01 and notebook 02 run as separate executions connected only by
    staging files in OneLake, whose listing can lag. If notebook 02 reads a
    subset, its own row-conservation check still balances (it conserves whatever
    it read), so the loss is silent — the cross-boundary form of the #1625 /
    #2173 "processed a subset, assumed the whole" trap. This compares the count
    actually observed against the authoritative expected count handed across the
    boundary (the batch manifest) and fails loudly on any mismatch before a
    partial batch reaches the Delta table.

    Args:
        expected_count: Authoritative row count from the upstream batch manifest.
        observed_count: Rows actually read at this hop.
        contract_path: Path to storage-layout.contract.json.
        stage: Human-readable label for the hop, used in the error message.

    Raises:
        ContractViolation: on a negative count or any shortfall/excess.
    """
    contract = load_storage_contract(contract_path)
    result = ValidationResult()
    if not contract["enforcement"].get("failOnIncompleteBatch", True):
        return result

    if expected_count < 0 or observed_count < 0:
        raise ContractViolation(
            f"Batch completeness at '{stage}' hop received a negative count: "
            f"expected={expected_count}, observed={observed_count}."
        )

    if observed_count != expected_count:
        raise ContractViolation(
            f"Incomplete batch at '{stage}' hop: upstream manifest expected "
            f"{expected_count} row(s) but observed {observed_count}. A hop that "
            "processes a subset while assuming it has the whole set (the #1625 / "
            "#2173 trap) balances its own local counts and hides the loss — "
            "stopping before a partial batch reaches the Delta table."
        )
    return result


def _parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp, tolerating a trailing 'Z'."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))