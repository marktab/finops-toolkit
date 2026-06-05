# Fabric notebook source
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

# MARKDOWN ********************

# # 05 - DirectLake promotion decision (Phase 6)
#
# After one full billing cycle on the SQL endpoint, this notebook lets the
# accumulated readiness-gate history decide whether to promote to DirectLake -
# not a one-off "looks fast enough" judgment. It also validates the provisional
# Z-order columns against the pilot customer's actual dominant query filters and
# recommends keeping or revising them. Both decisions are written to tables so
# they are artifacts, not assertions.

# PARAMETERS CELL ********************

gate_table = "_pilot_directlake_gate"
promotion_table = "_pilot_directlake_promotion"
query_filter_table = "_pilot_query_filter_stats"  # column -> filter count over the cycle
cycle_days = 28
min_consecutive_ready_days = 7

# CELL ********************

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_PILOT_ROOT = Path("/lakehouse/default/Files/pilot/fabric-onelake")
sys.path.insert(0, str(_PILOT_ROOT / "notebooks" / "lib"))

from focus_pilot.promotion import (  # noqa: E402
    evaluate_directlake_promotion,
    recommend_zorder,
)

_CONTRACTS = _PILOT_ROOT / "contracts"
with (_CONTRACTS / "storage-layout.contract.json").open(encoding="utf-8") as handle:
    storage_contract = json.load(handle)
current_zorder = storage_contract["zorder"]["columns"]

# CELL ********************

# Promotion decision from the full gate history.
gate_rows = [row.asDict() for row in spark.read.table(gate_table).collect()]
decision = evaluate_directlake_promotion(
    gate_rows,
    cycle_days=cycle_days,
    min_consecutive_ready_days=min_consecutive_ready_days,
)

# CELL ********************

# Z-order validation from observed query filters (if telemetry was collected).
try:
    filter_counts = {
        row["columnName"]: row["filterCount"]
        for row in spark.read.table(query_filter_table).collect()
    }
except Exception:  # noqa: BLE001 - telemetry table may not exist yet
    filter_counts = {}

zorder = recommend_zorder(filter_counts, current_zorder)

# CELL ********************

decision_ts = datetime.now(timezone.utc)
promotion_row = {
    "authorized": decision.authorized,
    "observedDays": decision.observed_days,
    "consecutiveReadyDays": decision.consecutive_ready_days,
    "reasons": json.dumps(decision.reasons),
    "zorderRecommended": json.dumps(zorder.recommended),
    "zorderMatchesCurrent": zorder.matches_current,
    "zorderReasons": json.dumps(zorder.reasons),
    "evaluatedAtUtc": decision_ts.isoformat(),
}
spark.createDataFrame([promotion_row]).write.format("delta").mode("append").saveAsTable(promotion_table)

# CELL ********************

print("DirectLake promotion:", "AUTHORIZED" if decision.authorized else "NOT AUTHORIZED")
for reason in decision.reasons:
    print(f"  - {reason}")

print("\nZ-order validation:")
for reason in zorder.reasons:
    print(f"  - {reason}")
if not zorder.matches_current:
    print(f"  Action: update storage-layout.contract.json zorder.columns to {zorder.recommended} and re-run OPTIMIZE.")

mssparkutils.notebook.exit(json.dumps({"promotion": decision.as_dict(), "zorder": zorder.as_dict()}))  # noqa: F821
