# FinOps Fabric / OneLake pilot developer documentation

This document explains what the Fabric / OneLake pilot does, why each design choice
was made, and how the pilot guards against the failure patterns that recur across the
toolkit's backlog. It is developer-facing rationale; for setup and run instructions see
the pilot [README](../README.md).

On this page:

- [Overview](#overview)
- [Design decisions](#design-decisions)
- [Backlog-informed hardening](#backlog-informed-hardening)
- [Component layout](#component-layout)
- [Testing](#testing)

---

## Overview

The toolkit's storage-based Power BI path serves cost data well until an organization's
spend grows large — around $2–5M/month — at which point the data is split across many
small Parquet files that cannot be compacted, and reports slow down. There has not been
a Microsoft Fabric / OneLake path that removes that ceiling.

This pilot adds an optional, self-contained path that takes the *already-normalized*
FOCUS cost data the hub produces and materializes it as a managed Delta table in OneLake,
so it can be compacted and served quickly to Power BI. It is additive — nothing in the
existing hub, templates, or reports changes, and it can be removed without impact.

The principle behind every design choice below: each "if this breaks" case is a *silent*
failure, so each contract is enforced by code that **stops loudly** when reality drifts,
rather than a convention written in a doc that no one re-checks.

## Design decisions

Each decision is enforced by tested, fail-loud code, not documentation.

1. **Schema ownership stays in KQL.** The pilot does not re-implement FOCUS
   normalization in Spark. It validates the FOCUS output the toolkit already produces
   against a machine-readable schema contract that *references* the existing
   `src/open-data/dataset-metadata/FocusCost_1.2-preview.json` rather than duplicating
   it. This avoids maintaining the same complex logic in two languages as FOCUS evolves.

2. **Managed Delta, not shortcuts.** Shortcuts inherit the source small-file problem and
   cannot be compacted or Z-ordered, so they cannot remove the query ceiling. The pilot
   writes a managed Delta table compacted daily (OPTIMIZE + Z-ORDER) with before/after
   file metrics emitted for alerting, treating compaction as a monitored SLA.

3. **Keep Azure Data Factory as the orchestrator; have it call a Fabric notebook.** ADF
   deploys via Bicep/ARM and runs in locked-down/air-gapped tenants where Fabric
   pipelines cannot be ARM-provisioned. The pilot adds one step where ADF hands off to a
   Fabric Spark notebook and waits for it. The manual deployment path is built and proven
   first, so the automated REST provisioner is a convenience over a known-good path
   rather than a single point of failure.

4. **Power BI connects to the SQL endpoint first; DirectLake is earned, not promised.**
   DirectLake can silently fall back to a 10–50× slower mode with no error. Power BI
   starts on the plain SQL analytics endpoint (works immediately, any license), and a
   readiness gate must pass — over a full billing cycle — before DirectLake is enabled.

## Backlog-informed hardening

Each guard below maps to a recurring failure pattern in the toolkit's open issues —
silent failures that show up in real practitioner deployments rather than in limited
tests — and each is enforced by a tested, fail-loud check.

- **Row-count conservation** (issues #2180, #2173, #1736). Every materialization hop
  (source → staging, staging → Delta) asserts input rows == output rows via
  `validate_row_conservation`; the Delta hop compares against the commit's
  `numOutputRows`, not a recount. A silent extent loss or row duplication stops the
  pipeline instead of corrupting cost totals.

- **Batch completeness across the notebook boundary** (issues #1625, #2173). Notebooks
  01 and 02 run as separate executions and hand off via staging files in OneLake, whose
  listing can lag. Notebook 01 writes an authoritative batch manifest (expected row
  count) and notebook 02 asserts, via `validate_batch_completeness`, that it consumed
  exactly that many rows before writing — closing the "processed a subset, assumed the
  whole" hole that a per-hop count check alone would miss.

- **Private-networking preflight** (issue #2061). Fabric ingests via impersonation, not
  `managed_identity=system`, so the storage "trusted Microsoft services" bypass that
  works for Azure Data Explorer does not apply. A `privateNetworking` parameter makes the
  preflight fail loudly at deploy time (referencing #2061) instead of hanging deep in a
  notebook run.

- **Timezone / whole-table audit** (issues #2157, #1995, #1625). The ADF→Fabric Bicep was
  audited for schedule-trigger `startTime` / `recurrence` UTC-designator bugs, and the
  notebooks for per-file joins that assume whole-table visibility. Both are clean — there
  are no schedule triggers, and KQL owns all transforms — so no change was made. Recorded
  here as evidence rather than an invented fix.

## Component layout

| Path | Contents |
| ---- | -------- |
| [contracts/](../contracts) | Machine-readable schema and physical Delta/compaction contracts (including the row-conservation and batch-handoff invariants) that the code loads and enforces. |
| [validation/](../validation) | The contract validator the notebooks import (unit-tested, no Spark required). |
| [notebooks/](../notebooks) | Fabric notebooks 01–05: validate → write Delta → compact (with metrics) → DirectLake readiness gate → promotion decision, plus the shared `lib/` helpers. |
| [deploy/manual/](../deploy/manual) | The proven-first manual setup and a fail-loud preflight check (including the private-networking guard). |
| [deploy/automation/](../deploy/automation) | Idempotent Fabric REST provisioning (get-or-create) over the manual path. |
| [deploy/orchestration/](../deploy/orchestration) | The ADF→Fabric notebook handoff (Bicep). |
| [power-bi/](../power-bi) | The SQL-endpoint report variant, applied as a one-line source swap. |

## Testing

The pilot's logic is validated without live Azure resources:

- **42 Python unit tests** — schema/null/version enforcement, row-count conservation,
  batch completeness, compaction-SLA math, DirectLake readiness conditions, and
  promotion + Z-order logic.
- **12 Pester tests** — deployment-parameter validation and the fail-loud preflight,
  including the private-networking guard.
- **`az bicep build`** — the ADF→Fabric orchestration pipeline compiles clean.

These prove the logic and contract enforcement. They intentionally do not prove an
end-to-end run against a live Fabric Lakehouse, which requires a Fabric capacity and a
full billing cycle to validate the DirectLake promotion gate and the cost-ceiling claim.
