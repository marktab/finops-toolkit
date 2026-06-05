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

# CELL ********************

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files/pilot/fabric-onelake")
for _p in (_PILOT_ROOT / "notebooks" / "lib", _PILOT_ROOT / "validation"):
    sys.path.insert(0, str(_p))

from focus_pilot.metrics import compute_file_metrics  # noqa: E402
from contract_validator import validate_compaction_sla  # noqa: E402

_CONTRACTS = _PILOT_ROOT / "contracts"
_STORAGE_CONTRACT = _CONTRACTS / "storage-layout.contract.json"
with _STORAGE_CONTRACT.open(encoding="utf-8") as handle:
    storage_contract = json.load(handle)

zorder_cols = storage_contract["zorder"]["columns"]
small_file_threshold_mb = storage_contract["compaction"]["sla"]["smallFileThresholdMB"]

# CELL ********************


def _data_file_sizes(table: str) -> list[int]:
    """Return the size in bytes of each active parquet file in the Delta table."""
    detail = spark.sql(f"DESCRIBE DETAIL {table}").collect()[0]
    location = detail["location"]
    files = (
        spark.read.format("binaryFile")
        .load(f"{location}/**/*.parquet")
        .select("path", "length")
        .collect()
    )
    return [row["length"] for row in files]


# CELL ********************

before = compute_file_metrics(_data_file_sizes(table_name), small_file_threshold_mb)

# Compact. Z-order columns are provisional until validated against real query
# patterns (Phase 6); re-running with different columns is non-destructive.
zorder_clause = ", ".join(zorder_cols)
spark.sql(f"OPTIMIZE {table_name} ZORDER BY ({zorder_clause})")

after = compute_file_metrics(_data_file_sizes(table_name), small_file_threshold_mb)

# CELL ********************

run_ts = datetime.now(timezone.utc)
metrics_row = {
    "tableName": table_name,
    "fileCountBefore": before.file_count,
    "fileCountAfter": after.file_count,
    "avgFileSizeMBBefore": before.avg_file_size_mb,
    "avgFileSizeMBAfter": after.avg_file_size_mb,
    "smallFileFractionAfter": after.small_file_fraction,
    "bytesRewritten": after.total_bytes,
    "lastRunTimestampUtc": run_ts.isoformat(),
    "lastRunStatus": "success",
}

# Append one row per run to the operational metrics table (watchable by alerts).
spark.createDataFrame([metrics_row]).write.format("delta").mode("append").saveAsTable(metrics_table)
print(f"Compaction metrics: {metrics_row}")

# CELL ********************

# Enforce the D2 compaction SLA. A stale or fragmented table fails here so it
# pages someone instead of silently degrading queries and the DirectLake gate.
result = validate_compaction_sla(metrics_row, str(_STORAGE_CONTRACT), now=run_ts)
for warning in result.warnings:
    print(f"WARN: {warning}")

print("Compaction SLA satisfied.")
