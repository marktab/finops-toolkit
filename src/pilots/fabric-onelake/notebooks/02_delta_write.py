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

_PILOT_ROOT = Path("/lakehouse/default/Files/pilot/fabric-onelake")
sys.path.insert(0, str(_PILOT_ROOT / "notebooks" / "lib"))

_CONTRACTS = _PILOT_ROOT / "contracts"
with (_CONTRACTS / "storage-layout.contract.json").open(encoding="utf-8") as handle:
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
(
    df.write.format("delta")
    .mode("append")
    .partitionBy(*partition_cols)
    .option("mergeSchema", "true")
    .saveAsTable(table_name)
)

print(f"Wrote {df.count()} rows to managed Delta table '{table_name}' partitioned by {partition_cols}.")
