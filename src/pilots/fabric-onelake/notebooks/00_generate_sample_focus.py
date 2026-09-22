# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 00 - Deterministic multi-month, multi-scope synthetic FOCUS input
#
# Synthetic values only. Expected grouped decimal totals are computed in Python
# before Spark reads the fixture, independently of the ingestion staging count.
# This is not an actual RTI export or a scale/performance test.

# PARAMETERS CELL ********************

ABFSS_ROOT = ""  # copy the actual isolated Lakehouse ABFSS path
OUTPUT_PATH = "Files/sample-focus"
numeric_variant = "decimal"  # "double" deliberately exercises input rejection

# CELL ********************

import json
import sys
from pathlib import Path

from pyspark.sql import types as T

_PILOT_ROOT = Path("/lakehouse/default/Files")
sys.path.insert(0, str(_PILOT_ROOT / "notebooks" / "lib"))
sys.path.insert(0, str(_PILOT_ROOT / "validation"))

from focus_pilot.synthetic import sample_fixture

if not ABFSS_ROOT.strip():
    raise ValueError("Set ABFSS_ROOT to the authorized isolated Lakehouse ABFSS path.")
if numeric_variant not in ("decimal", "double"):
    raise ValueError("numeric_variant must be decimal or double.")

rows, logical_types, expected = sample_fixture(
    _PILOT_ROOT / "contracts" / "focus-schema.contract.json"
)
types = {
    "decimal": T.DecimalType(38, 18),
    "double": T.DoubleType(),
    "string": T.StringType(),
    "timestamp": T.TimestampType(),
    "boolean": T.BooleanType(),
}
if numeric_variant == "double":
    types["decimal"] = T.DoubleType()
    rows = [
        {name: float(value) if logical_types[name] == "decimal" and value is not None else value
         for name, value in row.items()}
        for row in rows
    ]

schema = T.StructType([
    T.StructField(name, types[dtype], nullable=True)
    for name, dtype in logical_types.items()
])
out = f"{ABFSS_ROOT}/{OUTPUT_PATH}-{numeric_variant}"
spark.createDataFrame(rows, schema).write.mode("overwrite").parquet(out)
producer_manifest = {
    "fixture": "deterministic-three-month-two-scope-two-currency-v1",
    "numericVariant": numeric_variant,
    "expectedRowCount": len(rows),
    "decimalTolerance": "0",
    "groupedExpected": expected,
}
spark.createDataFrame([(json.dumps(producer_manifest),)], ["value"]).coalesce(1).write.mode(
    "overwrite"
).text(out + "_producer_expected")
print(f"Written {len(rows)} synthetic rows; source_path = {out!r}")
print(f"Independent expected results: {out}_producer_expected")
print("Accept only decimal input. Double variant must fail before target mutation.")
