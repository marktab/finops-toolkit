# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 01 - Schema-validated ingestion (Decision 1)
#
# Reads FOCUS cost data produced by the toolkit's KQL transform layer (which
# remains the single transform owner) and validates it against the D1 logical
# schema contract BEFORE anything downstream consumes it. Fails loudly on FOCUS
# version drift, missing required columns, type mismatches, or nulls in
# non-nullable columns. KQL stays the transform owner; this notebook is the gate.

# PARAMETERS CELL ********************

# Parameters (overridden by the ADF notebook activity / pipeline).
source_path = ""          # abfss path to the FOCUS parquet exported from the hub
oneLakeEndpoint = ""      # validated OneLake Lakehouse endpoint (from preflight)
focus_version = "1.2"     # FOCUS version reported by the upstream transform
ingestion_id = ""         # correlation id passed by the orchestrator

# CELL ********************

import sys
from pathlib import Path

# Make the pilot library and the Phase 1 validator importable.
# REQUIRES a default Lakehouse attached to this notebook (Explorer > Add data items >
# your Lakehouse > Set as default lakehouse) or /lakehouse/default will not resolve.
# _PILOT_ROOT assumes notebooks/, contracts/, and validation/ were uploaded directly
# under the Lakehouse Files area. Adjust if you uploaded them elsewhere. See README.md.
_PILOT_ROOT = Path("/lakehouse/default/Files")  # adjust to deployed path
for _p in (_PILOT_ROOT / "notebooks" / "lib", _PILOT_ROOT / "validation"):
    sys.path.insert(0, str(_p))

from focus_pilot.schema_bridge import spark_schema_to_logical  # noqa: E402
from contract_validator import (  # noqa: E402
    validate_focus_schema,
    validate_non_null,
    validate_row_conservation,
)

_CONTRACTS = _PILOT_ROOT / "contracts"
_SCHEMA_CONTRACT = _CONTRACTS / "focus-schema.contract.json"
_STORAGE_CONTRACT = _CONTRACTS / "storage-layout.contract.json"

# CELL ********************

# Read the FOCUS data as produced by the KQL transform (parquet).
df = spark.read.parquet(source_path)

# CELL ********************

# Translate the observed Spark schema into the contract's logical types, then
# enforce the D1 contract. Any violation raises and stops the pipeline.
observed = {field.name: field.dataType.simpleString() for field in df.schema}
logical = spark_schema_to_logical(observed)

schema_result = validate_focus_schema(logical, focus_version, str(_SCHEMA_CONTRACT))
for warning in schema_result.warnings:
    print(f"WARN: {warning}")

# CELL ********************

# Enforce non-nullability on the contract's non-nullable columns.
from pyspark.sql import functions as F  # noqa: E402

# One aggregation covers every column. Filtering and counting per column instead
# would scan the whole table once per FOCUS column (50+ passes) for the same answer.
df.cache()
source_count = df.count()
null_counts = (
    df.agg(*[F.sum(F.col(c).isNull().cast("long")).alias(c) for c in df.columns])
    .collect()[0]
    .asDict()
)
validate_non_null(null_counts, str(_SCHEMA_CONTRACT))

print(f"Ingestion validated: {source_count} rows, FOCUS {focus_version}, ingestion_id={ingestion_id}")

# CELL ********************

# Hand the validated DataFrame to the next notebook via a temp view / path.
# In the ADF pipeline this is chained; here we persist a validated staging copy.
_staging = f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}"
df.write.mode("overwrite").parquet(_staging)

# Row-count conservation (source -> staging): staging must contain exactly the
# rows we just validated. A drift here is a silent ingestion loss (the #2173 /
# #2180 class of hub bug), so fail loudly before notebook 02 consumes it.
staged_count = spark.read.parquet(_staging).count()
validate_row_conservation(source_count, staged_count, str(_STORAGE_CONTRACT), stage="ingestion->staging")

# Write an authoritative batch manifest alongside the staging copy so the next
# notebook can assert it consumed the COMPLETE batch (not a partial, lagging
# OneLake listing) before writing to Delta — the cross-boundary #1625 / #2173
# trap. Mirrors the toolkit hub's manifest.json row-count mechanism.
_manifest_dir = f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}_manifest"
_manifest = {
    "ingestionId": ingestion_id,
    "expectedRowCount": staged_count,
    "focusVersion": focus_version,
}
spark.createDataFrame([_manifest]).coalesce(1).write.mode("overwrite").json(_manifest_dir)

print(f"Validated data staged at {_staging} ({staged_count} rows); manifest at {_manifest_dir}.")
