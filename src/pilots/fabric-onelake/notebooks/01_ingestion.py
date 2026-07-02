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
_PILOT_ROOT = Path("/lakehouse/default/Files")  # adjust to deployed path
for _p in (_PILOT_ROOT / "notebooks" / "lib", _PILOT_ROOT / "validation"):
    sys.path.insert(0, str(_p))

from focus_pilot.schema_bridge import spark_schema_to_logical  # noqa: E402
from contract_validator import (  # noqa: E402
    validate_focus_schema,
    validate_non_null,
)

_CONTRACTS = _PILOT_ROOT / "contracts"
_SCHEMA_CONTRACT = _CONTRACTS / "focus-schema.contract.json"

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

null_counts = {
    field.name: df.filter(F.col(field.name).isNull()).count()
    for field in df.schema
}
validate_non_null(null_counts, str(_SCHEMA_CONTRACT))

print(f"Ingestion validated: {df.count()} rows, FOCUS {focus_version}, ingestion_id={ingestion_id}")

# CELL ********************

# Hand the validated DataFrame to the next notebook via a temp view / path.
# In the ADF pipeline this is chained; here we persist a validated staging copy.
_staging = f"{oneLakeEndpoint}/Files/_staging/{ingestion_id}"
df.write.mode("overwrite").parquet(_staging)
print(f"Validated data staged at {_staging}")
