# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 03 - Compaction with metrics (Decision 2)
#
# Runs OPTIMIZE (+ Z-ORDER) on the managed Delta table and treats compaction as
# a MONITORED SLA, not a fire-and-forget job. It captures before/after file
# metrics, appends them to an operational metrics table a watcher can alert on,
# and then validates the result against the D2 compaction SLA - failing loudly
# if the table is stale or fragmented. This notebook is load-bearing for both
# query performance and the DirectLake-readiness gate.

# PARAMETERS CELL ********************

table_name = "Costs"
metrics_table = "_pilot_compaction_metrics"

# Pilot-scale SLA relaxations for synthetic data that cannot reach the contract's
# production file-size floor. Production is the DEFAULT: leave this empty for real
# billing data. Example for a tiny test dataset:
#   sla_overrides = {"minAvgFileSizeMB": 0.01, "maxSmallFileFraction": 1.0, "smallFileThresholdMB": 0.01}
sla_overrides = {}

# CELL ********************

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files")
for _p in (_PILOT_ROOT / "notebooks" / "lib", _PILOT_ROOT / "validation"):
    sys.path.insert(0, str(_p))

from focus_pilot.metrics import compute_file_metrics, select_active_file_sizes  # noqa: E402
from contract_validator import validate_compaction_sla  # noqa: E402

_CONTRACTS = _PILOT_ROOT / "contracts"
_STORAGE_CONTRACT = _CONTRACTS / "storage-layout.contract.json"
with _STORAGE_CONTRACT.open(encoding="utf-8") as handle:
    storage_contract = json.load(handle)

zorder_cols = storage_contract["zorder"]["columns"]
small_file_threshold_mb = storage_contract["compaction"]["sla"]["smallFileThresholdMB"]

# CELL ********************


def _active_file_metrics(table: str):
    """File-layout metrics over the Delta log's ACTIVE files only.

    OPTIMIZE does not delete the files it supersedes - they stay on disk until
    VACUUM. Listing the table location alone therefore counts both generations
    and reports a freshly compacted table as fragmented, so the listing is
    intersected with the active set the Delta log reports.
    """
    location = spark.sql(f"DESCRIBE DETAIL {table}").collect()[0]["location"]
    listed = [
        (row["path"], row["length"])
        for row in spark.read.format("binaryFile")
        .load(f"{location}/**/*.parquet")
        .select("path", "length")
        .collect()
    ]
    active = spark.table(table).inputFiles()
    return compute_file_metrics(
        select_active_file_sizes(listed, active), small_file_threshold_mb
    )


def _bytes_rewritten(optimize_rows) -> int | None:
    """Bytes OPTIMIZE actually wrote, from the operation's own metrics."""
    try:
        return int(optimize_rows[0]["metrics"]["filesAdded"]["totalSize"])
    except (IndexError, KeyError, TypeError, ValueError):
        return None


# CELL ********************

before = _active_file_metrics(table_name)

# Compact. Z-order columns are provisional until validated against real query
# patterns (Phase 6); re-running with different columns is non-destructive.
zorder_clause = ", ".join(zorder_cols)
optimize_result = spark.sql(f"OPTIMIZE {table_name} ZORDER BY ({zorder_clause})").collect()

after = _active_file_metrics(table_name)
bytes_rewritten = _bytes_rewritten(optimize_result)
if bytes_rewritten is None:
    print("WARN: OPTIMIZE returned no recognizable filesAdded metrics; bytesRewritten recorded as null.")

# CELL ********************

run_ts = datetime.now(timezone.utc)
metrics_row = {
    "tableName": table_name,
    "fileCountBefore": before.file_count,
    "fileCountAfter": after.file_count,
    "avgFileSizeMBBefore": before.avg_file_size_mb,
    "avgFileSizeMBAfter": after.avg_file_size_mb,
    "smallFileFractionAfter": after.small_file_fraction,
    "bytesRewritten": bytes_rewritten,
    "lastRunTimestampUtc": run_ts.isoformat(),
    "lastRunStatus": "success",
}

# Append one row per run to the operational metrics table (watchable by alerts).
spark.createDataFrame([metrics_row]).write.format("delta").mode("append").saveAsTable(metrics_table)
print(f"Compaction metrics: {metrics_row}")

# CELL ********************

# Enforce the D2 compaction SLA. A stale or fragmented table fails here so it
# pages someone instead of silently degrading queries and the layout gate.
# The contract's PRODUCTION thresholds apply unless sla_overrides is set in the
# parameters cell (pilot-scale synthetic data only).
result = validate_compaction_sla(
    metrics_row, str(_STORAGE_CONTRACT), now=run_ts, sla_overrides=sla_overrides or None
)
if sla_overrides:
    print(f"WARN: pilot-scale SLA overrides in effect: {sla_overrides}")
for warning in result.warnings:
    print(f"WARN: {warning}")

print("Compaction SLA satisfied.")
