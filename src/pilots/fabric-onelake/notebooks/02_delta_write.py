# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 02 - FOCUS Delta write (Decision 2)
#
# Writes the validated FOCUS data to a managed Delta table in OneLake per the D2
# physical storage contract: managed Delta (not a shortcut), partitioned by a
# derived charge-month column, with JSON columns stored as strings to keep the
# DirectLake path open. Managed Delta is the only option that can later be
# compacted and Z-ordered to remove the small-file query ceiling.

# PARAMETERS CELL ********************

oneLakeEndpoint = ""   # validated OneLake Lakehouse endpoint (from preflight)
ingestion_id = ""      # correlation id from the orchestrator
table_name = "Costs"   # target managed Delta table

# CELL ********************

import json
import sys
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files")
sys.path.insert(0, str(_PILOT_ROOT / "notebooks" / "lib"))
sys.path.insert(0, str(_PILOT_ROOT / "validation"))

from contract_validator import (  # noqa: E402
    validate_batch_completeness,
    validate_row_conservation,
)

_CONTRACTS = _PILOT_ROOT / "contracts"
_STORAGE_CONTRACT = _CONTRACTS / "storage-layout.contract.json"
with _STORAGE_CONTRACT.open(encoding="utf-8") as handle:
    storage_contract = json.load(handle)

partition_cols = storage_contract["partitioning"]["columns"]

# CELL ********************

from pyspark.sql import functions as F  # noqa: E402

# Read the validated staging copy written by notebook 01.
df = spark.read.parquet(f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}")

# Derive the partition column: month-truncated ChargePeriodStart, stored as date.
df = df.withColumn(
    "x_ChargeMonth",
    F.to_date(F.date_trunc("month", F.col("ChargePeriodStart"))),
)

# CELL ********************

# Write as a managed Delta table, partitioned per the D2 contract.
# mergeSchema tolerates additive FOCUS growth; overwrite is by ingestion in the
# pipeline (this sample uses append for incremental ingestion).
input_count = df.count()

# Batch completeness (staging read): assert we are about to write the COMPLETE
# batch notebook 01 staged, not a partial/lagging OneLake listing. This is the
# cross-boundary guard — 02's own conservation check below would still pass on a
# subset, hiding the loss (the #1625 / #2173 trap).
_manifest_dir = f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}_manifest"
expected_count = int(spark.read.json(_manifest_dir).collect()[0]["expectedRowCount"])
validate_batch_completeness(expected_count, input_count, str(_STORAGE_CONTRACT), stage="staging-read")

(
    df.write.format("delta")
    .mode("append")
    .partitionBy(*partition_cols)
    .option("mergeSchema", "true")
    .saveAsTable(table_name)
)

# Row-count conservation (staging -> Delta): the append must land exactly the
# rows we read. numOutputRows comes from the Delta commit itself (not a recount),
# so a mismatch means rows were silently dropped or duplicated during the write —
# the #2180 (extents lost) class of failure. Fail loudly rather than serve wrong
# totals to Power BI.
last_commit = spark.sql(f"DESCRIBE HISTORY {table_name} LIMIT 1").collect()[0]
output_count = int(last_commit["operationMetrics"]["numOutputRows"])
validate_row_conservation(input_count, output_count, str(_STORAGE_CONTRACT), stage="staging->delta")

print(f"Wrote {output_count} rows to managed Delta table '{table_name}' partitioned by {partition_cols}.")
