# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 04 - Direct Lake layout precondition (Decision 4)
#
# This notebook records four listed layout checks, not platform eligibility.
# Direct Lake on OneLake does not fall back through the SQL analytics endpoint.
# Direct Lake on SQL fallback depends on source constructs, security, limits,
# and DirectLakeBehavior. File-size targets are workload tuning, not guardrails.
#
# It is a precondition, not a readiness verdict. It never builds or queries a
# Direct Lake semantic model, so it cannot observe relationships, one-side
# uniqueness, RLS/OLS and fixed identity, framing, cold-query latency, memory
# pressure, or an actual fallback. Passing means the listed layout checks passed.
# V-Order verification is not performed; inherited settings may already apply it.
# Model validation remains separate. Gate history is diagnostic, not approval.

# PARAMETERS CELL ********************

table_name = "Costs"
metrics_table = "_pilot_compaction_metrics"
gate_table = "_pilot_directlake_gate"

# CELL ********************

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files")
for _p in (_PILOT_ROOT / "notebooks" / "lib", _PILOT_ROOT / "validation"):
    sys.path.insert(0, str(_p))

from focus_pilot.readiness import (  # noqa: E402
    directlake_guardrails,
    evaluate_directlake_layout_precondition,
    read_latest_compaction_evidence,
    append_layout_assessment,
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
decision_ts = datetime.now(timezone.utc)
compaction_healthy = False
try:
    row = read_latest_compaction_evidence(spark, table_name, metrics_table, now=decision_ts)
    validate_compaction_sla(row, str(_STORAGE_CONTRACT), now=decision_ts)
    compaction_healthy = True
except ContractViolation as exc:
    print(f"Compaction not healthy: {exc}")

# CELL ********************

# Condition 2: no DirectLake-incompatible (complex/nested) column types.
observed = {field.name: field.dataType.simpleString() for field in spark.table(table_name).schema}
unsupported = find_unsupported_directlake_types(observed)

# Conditions 3 & 4: volume guardrails and average file size. numFiles and
# sizeInBytes come from the Delta log, so they describe the active snapshot
# rather than files OPTIMIZE has superseded but not yet vacuumed.
detail = spark.sql(f"DESCRIBE DETAIL {table_name}").collect()[0]
row_count = spark.table(table_name).count()
file_count = detail["numFiles"]
size_bytes = detail["sizeInBytes"]
avg_file_size_mb = round((size_bytes / file_count) / (1024 * 1024), 3) if file_count else 0.0

# CELL ********************

result = evaluate_directlake_layout_precondition(
    compaction_healthy=compaction_healthy,
    unsupported_type_columns=unsupported,
    row_count=row_count,
    max_rows=guardrails["max_rows"],
    file_count=file_count,
    max_files=guardrails["max_files"],
    avg_file_size_mb=avg_file_size_mb,
    min_avg_file_size_mb=guardrails["min_avg_file_size_mb"],
)

gate_row = {
    "tableName": table_name,
    "meetsLayoutPrecondition": result.meets_precondition,
    "checks": json.dumps(result.checks),
    "reasons": json.dumps(result.reasons),
    "evaluatedAtUtc": decision_ts.isoformat(),
    "assessmentMetadata": json.dumps(result.assessment_metadata),
}
append_layout_assessment(spark, gate_table, gate_row)

# CELL ********************

if result.meets_precondition:
    print(
        "PASS: the listed layout checks passed. This is not Direct Lake eligibility "
        "or model validation; build and measure a semantic model before migrating."
    )
else:
    print("BLOCKED: stay on the SQL endpoint. Reasons:")
    for reason in result.reasons:
        print(f"  - {reason}")

print(f"Assessment scope: {json.dumps(result.assessment_metadata)}")
# Expose the diagnostic as the notebook's exit value, not authorization.
notebookutils.notebook.exit(json.dumps(result.as_dict()))  # noqa: F821
