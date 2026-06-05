# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 04 - DirectLake readiness gate (Decision 4)
#
# DirectLake silently falls back to DirectQuery (10-50x slower, no error) when a
# table is not in a supported state - a failure discovered by end users in
# production. This notebook turns the go/no-go into an artifact by evaluating
# four measurable conditions and writing the decision to a gate table. Its
# output is the ONLY thing that authorizes a DirectLake migration; until it
# returns go, Power BI stays on the SQL endpoint.

# PARAMETERS CELL ********************

table_name = "Costs"
metrics_table = "_pilot_compaction_metrics"
gate_table = "_pilot_directlake_gate"

# CELL ********************

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files/pilot/fabric-onelake")
for _p in (_PILOT_ROOT / "notebooks" / "lib", _PILOT_ROOT / "validation"):
    sys.path.insert(0, str(_p))

from focus_pilot.readiness import (  # noqa: E402
    directlake_guardrails,
    evaluate_directlake_readiness,
)
from focus_pilot.schema_bridge import find_unsupported_directlake_types  # noqa: E402
from contract_validator import validate_compaction_sla, ContractViolation  # noqa: E402

_CONTRACTS = _PILOT_ROOT / "contracts"
_STORAGE_CONTRACT = _CONTRACTS / "storage-layout.contract.json"
with _STORAGE_CONTRACT.open(encoding="utf-8") as handle:
    storage_contract = json.load(handle)

guardrails = directlake_guardrails(storage_contract)

# CELL ********************

# Condition 1: is compaction currently healthy? Reuse the D2 SLA check against
# the latest metrics row rather than re-deriving the logic.
latest = (
    spark.read.table(metrics_table)
    .orderBy("lastRunTimestampUtc", ascending=False)
    .limit(1)
    .collect()
)
compaction_healthy = False
if latest:
    row = latest[0].asDict()
    try:
        validate_compaction_sla(row, str(_STORAGE_CONTRACT))
        compaction_healthy = True
    except ContractViolation as exc:
        print(f"Compaction not healthy: {exc}")

# CELL ********************

# Condition 2: no DirectLake-incompatible (complex/nested) column types.
observed = {field.name: field.dataType.simpleString() for field in spark.table(table_name).schema}
unsupported = find_unsupported_directlake_types(observed)

# Conditions 3 & 4: volume guardrails and average file size.
detail = spark.sql(f"DESCRIBE DETAIL {table_name}").collect()[0]
row_count = spark.table(table_name).count()
file_count = detail["numFiles"]
size_bytes = detail["sizeInBytes"]
avg_file_size_mb = round((size_bytes / file_count) / (1024 * 1024), 3) if file_count else 0.0

# CELL ********************

result = evaluate_directlake_readiness(
    compaction_healthy=compaction_healthy,
    unsupported_type_columns=unsupported,
    row_count=row_count,
    max_rows=guardrails["max_rows"],
    file_count=file_count,
    max_files=guardrails["max_files"],
    avg_file_size_mb=avg_file_size_mb,
    min_avg_file_size_mb=guardrails["min_avg_file_size_mb"],
)

decision_ts = datetime.now(timezone.utc)
gate_row = {
    "tableName": table_name,
    "isReady": result.is_ready,
    "checks": json.dumps(result.checks),
    "reasons": json.dumps(result.reasons),
    "evaluatedAtUtc": decision_ts.isoformat(),
}
spark.createDataFrame([gate_row]).write.format("delta").mode("append").saveAsTable(gate_table)

# CELL ********************

if result.is_ready:
    print("GO: table is DirectLake-ready. A DirectLake migration is authorized.")
else:
    print("NO-GO: stay on the SQL endpoint. Reasons:")
    for reason in result.reasons:
        print(f"  - {reason}")

# Expose the decision as the notebook's exit value for the orchestrator.
mssparkutils.notebook.exit(json.dumps(result.as_dict()))  # noqa: F821
