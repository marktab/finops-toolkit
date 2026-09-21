# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 02 - FOCUS Delta write (Decision 2)
#
# Writes the validated FOCUS data to a managed Delta table in OneLake per the D2
# physical storage contract: managed Delta (not a shortcut), partitioned by a
# derived charge-month column, with JSON columns stored as strings to keep the
# consumer representation flat. Independent layout control is experimental,
# not evidence of a performance advantage over supported RTI/managed OneLake.
#
# Each batch is treated as a FULL SNAPSHOT of every charge month it covers, so
# the write replaces those months atomically instead of appending to them.

# PARAMETERS CELL ********************

oneLakeEndpoint = ""   # validated OneLake Lakehouse endpoint (from preflight)
ingestion_id = ""      # correlation id from the orchestrator
table_name = "Costs"   # target managed Delta table
ledger_table = "_pilot_ingestion_metrics"  # append-only record of every restatement
acceptance_record_id = ""  # operator's independent coverage/order/exclusive-writer acceptance

# Fail if a restatement replaces a month with less than this fraction of the rows
# it removed. This heuristic cannot prove completeness; missing scopes/months
# may pass. Re-scoping requires a separately approved procedure.
min_restatement_row_ratio = 0.5

# CELL ********************

import json
import sys
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files")
sys.path.insert(0, str(_PILOT_ROOT / "notebooks" / "lib"))
sys.path.insert(0, str(_PILOT_ROOT / "validation"))

from focus_pilot.restatement import (  # noqa: E402
    charge_month_predicate,
    check_restatement_ratio,
    write_month_snapshot,
)
from contract_validator import (  # noqa: E402
    ContractViolation,
    validate_batch_completeness,
    validate_focus_schema,
    validate_non_null,
    validate_row_conservation,
)
from focus_pilot.schema_bridge import prepare_numeric_frame, spark_schema_to_logical  # noqa: E402

_CONTRACTS = _PILOT_ROOT / "contracts"
_STORAGE_CONTRACT = _CONTRACTS / "storage-layout.contract.json"
_SCHEMA_CONTRACT = _CONTRACTS / "focus-schema.contract.json"
with _STORAGE_CONTRACT.open(encoding="utf-8") as handle:
    storage_contract = json.load(handle)

partition_cols = storage_contract["partitioning"]["columns"]

# CELL ********************

from datetime import datetime, timezone  # noqa: E402

from pyspark.sql import functions as F  # noqa: E402

# Charge-month replacement uses UTC, not the notebook session's local timezone.
spark.conf.set("spark.sql.session.timeZone", "UTC")

# Read the validated staging copy written by notebook 01.
if not oneLakeEndpoint.strip() or not ingestion_id.strip() or not acceptance_record_id.strip():
    raise ValueError(
        "oneLakeEndpoint, ingestion_id, and acceptance_record_id are required. "
        "Before writing, independently accept intended full month/scope coverage and "
        "batch order, and exclude every other manual/orchestrated writer until completion. "
        "An ID records the operator decision; it does not automatically verify it."
    )
df = spark.read.parquet(f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}")

# Derive the partition column: month-truncated ChargePeriodStart, stored as date.
df = df.withColumn(
    "x_ChargeMonth",
    F.to_date(F.date_trunc("month", F.col("ChargePeriodStart"))),
).cache()

# CELL ********************

input_count = df.count()

# Batch completeness (staging read): assert we are about to write the COMPLETE
# batch notebook 01 staged, not a partial/lagging OneLake listing. This is the
# cross-boundary guard — 02's own conservation check below would still pass on a
# subset, hiding the loss (the #1625 / #2173 trap).
_manifest_dir = f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}_manifest"
manifest_rows = spark.read.json(_manifest_dir).collect()
if len(manifest_rows) != 1:
    raise ContractViolation("Expected exactly one staging manifest; target unchanged.")
manifest = manifest_rows[0].asDict()
if manifest.get("ingestionId") != ingestion_id:
    raise ContractViolation("Staging manifest ingestionId mismatch; target unchanged.")
expected_count = manifest.get("expectedRowCount")
validate_batch_completeness(expected_count, input_count, str(_STORAGE_CONTRACT), stage="staging-read")
if input_count == 0:
    raise ContractViolation("Zero-row replacements are unsupported; target unchanged.")
schema_result = validate_focus_schema(
    spark_schema_to_logical({f.name: f.dataType.simpleString() for f in df.schema}),
    manifest.get("focusVersion"),
    _SCHEMA_CONTRACT,
)
for warning in schema_result.warnings:
    print(f"WARN: {warning}")
null_counts = df.agg(*[
    F.sum(F.col(c).isNull().cast("long")).alias(c) for c in df.columns
]).first().asDict()
validate_non_null(null_counts, _SCHEMA_CONTRACT)
df = prepare_numeric_frame(df, _SCHEMA_CONTRACT, _STORAGE_CONTRACT)

# CELL ********************

# Cost Management restates: the open month is re-exported every day, and closed
# months receive later credit and amortization corrections. Appending would
# multiply BilledCost on the second run while every per-hop count check still
# balanced, because each hop conserves whatever it was handed. Replacing the
# batch's charge months atomically is correct for both cases and is idempotent
# on retry.
months = sorted(row["x_ChargeMonth"] for row in df.select("x_ChargeMonth").distinct().collect())
month_predicate = charge_month_predicate(months)

table_exists = spark.catalog.tableExists(table_name)
rows_removed = spark.table(table_name).where(month_predicate).count() if table_exists else 0
version_before = (
    int(spark.sql(f"DESCRIBE HISTORY {table_name} LIMIT 1").collect()[0]["version"])
    if table_exists
    else -1
)

# A shrink-floor breach is rejected before mutation. Passing does not establish
# source completeness: independent operator acceptance is still required.
check_restatement_ratio(rows_removed, input_count, min_restatement_row_ratio, months)

# CELL ********************

write_month_snapshot(
    df,
    table_name,
    partition_columns=partition_cols,
    table_exists=table_exists,
    predicate=month_predicate,
    schema_contract_path=_SCHEMA_CONTRACT,
    storage_contract_path=_STORAGE_CONTRACT,
)

# CELL ********************

# Version attribution requires exclusive writer ownership across manual and
# automated entry points. This arithmetic does not detect overlapping writers.
version_after = version_before + 1
commit_rows = (
    spark.sql(f"DESCRIBE HISTORY {table_name}")
    .where(F.col("version") == version_after)
    .collect()
)
if not commit_rows:
    raise RuntimeError(
        f"Expected Delta version {version_after} after the write but it is absent; "
        "another writer may have committed concurrently."
    )

# Row-count conservation (staging -> Delta): the write must land exactly the rows
# we read. numOutputRows comes from the Delta commit itself (not a recount), so a
# mismatch means rows were silently dropped or duplicated during the write — the
# #2180 (extents lost) class of failure.
output_count = int(commit_rows[0]["operationMetrics"]["numOutputRows"])
validate_row_conservation(input_count, output_count, str(_STORAGE_CONTRACT), stage="staging->delta")

# CELL ********************

# Record every restatement so a destructive replace stays auditable afterwards.
ledger_row = {
    "ingestionId": ingestion_id,
    "tableName": table_name,
    "chargeMonths": ", ".join(f"{m:%Y-%m}" for m in months),
    "rowsRemoved": rows_removed,
    "rowsWritten": output_count,
    "deltaVersion": version_after,
    "writeMode": "replaceWhere" if table_exists else "create",
    "committedAtUtc": datetime.now(timezone.utc).isoformat(),
}
spark.createDataFrame([ledger_row]).write.format("delta").mode("append").saveAsTable(ledger_table)

print(
    f"Replaced {rows_removed} row(s) with {output_count} row(s) across "
    f"{len(months)} charge month(s) in '{table_name}' (Delta v{version_after})."
)
print(f"Operator acceptance record: {acceptance_record_id}")
