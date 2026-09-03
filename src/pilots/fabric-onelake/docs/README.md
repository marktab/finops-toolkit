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
- [For roadmap consideration](#for-roadmap-consideration)

---

## Overview

The toolkit's storage-based Power BI path serves cost data well until an organization's
spend grows large, at which point the data is split across many small Parquet files that
cannot be compacted, and reports slow down. The toolkit's own guidance puts the storage
path's practical limit at roughly $1M/month in monitored spend; where reports actually
become unusable is workload-dependent and this pilot has not measured it on real data.
Treat any specific dollar figure as an estimate until it is.

The toolkit already has a Microsoft Fabric path — FinOps hubs can use Fabric Real-Time
Intelligence (an eventhouse) as a primary or secondary store, and that is the current
recommendation for best performance. What has not existed is a **OneLake Delta** path:
cost data materialized as a managed Delta table that can be compacted, served through the
SQL analytics endpoint, and eventually carry a Direct Lake semantic model.

This pilot adds that path, taking the *already-normalized* FOCUS cost data the hub
produces and materializing it as a managed Delta table in OneLake. It is additive —
nothing in the existing hub, templates, or reports changes, and it can be removed without
impact.

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

2. **Managed Delta, not shortcuts — written as a monthly snapshot.** Shortcuts inherit
   the source small-file problem and cannot be compacted or Z-ordered, so they cannot
   remove the query ceiling. The pilot writes a managed Delta table compacted daily
   (OPTIMIZE + Z-ORDER) with before/after file metrics emitted for alerting, treating
   compaction as a monitored SLA.

   Each batch is treated as a **full snapshot of the charge months it covers**, and those
   months are replaced atomically rather than appended. Cost Management restates: the open
   month is re-exported every day and closed months receive later credit and amortization
   corrections, so an append-only write multiplies `BilledCost` from the second run onward.
   Critically, that duplication is invisible to per-hop row-count checks — each hop
   faithfully conserves whatever it was handed — which is why the guard has to be in the
   write semantics rather than in another count assertion. Replacing is also idempotent on
   retry, so it covers the orchestration-retry case without a separate transaction id.

   `replaceWhere` cannot distinguish a genuine correction from a truncated source export,
   so the write additionally rejects a restatement that lands less than half the rows it
   removed, and records every restatement (months, rows removed, rows written, Delta
   version) to an append-only ingestion ledger.

3. **Keep Azure Data Factory as the orchestrator; have it call a Fabric notebook.** ADF
   deploys via Bicep/ARM and runs in locked-down/air-gapped tenants where Fabric
   pipelines cannot be ARM-provisioned. The pilot adds one step where ADF hands off to a
   Fabric Spark notebook and waits for it. The manual deployment path is built and proven
   first, so the automated REST provisioner is a convenience over a known-good path
   rather than a single point of failure.

4. **Power BI connects to the SQL endpoint; Direct Lake is earned, not promised.**
   Direct Lake on SQL can silently fall back to a 10–50x slower mode with no error. Power
   BI starts on the plain SQL analytics endpoint (works immediately, any license), and
   notebook 04 evaluates a **layout precondition** over a full billing cycle before Direct
   Lake is considered.

   That notebook is deliberately named a precondition rather than a readiness verdict. It
   measures table layout only — compaction health, column types, row and file counts
   against the capacity's guardrails, average file size. It never builds or queries a
   semantic model, so it cannot observe relationships, one-side uniqueness, RLS/OLS and
   fixed identity, framing, cold-query latency, memory pressure, or an actual fallback.
   Passing means the layout no longer disqualifies Direct Lake, not that Direct Lake will
   perform. The guardrail values are unset in the contract on purpose: they vary by Fabric
   capacity SKU, and a built-in default is wrong for most capacities in both directions —
   a permissive one produces a false pass on a small SKU, which is precisely the silent
   failure the gate exists to prevent.

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

- **Compaction measured over the active snapshot.** `OPTIMIZE` does not delete the files
  it supersedes; they stay on disk until `VACUUM`. Listing the table location therefore
  counts both generations and reports a freshly compacted table as fragmented — which
  would fail the SLA the compaction exists to satisfy and feed a wrong answer to the
  layout precondition. The listing is intersected with the Delta log's active file set,
  and a total path mismatch raises rather than reporting zero files, because a fabricated
  "0 files" would read as a healthy empty table. `bytesRewritten` likewise comes from the
  operation's own `filesAdded` metrics rather than the table's total size; the two differ
  by orders of magnitude on an incremental compaction.

- **Absent evidence is not confirming evidence.** The Z-order validation returns
  `unvalidated` when no query-filter telemetry exists, not "matches current". Reporting a
  match would let the provisional Z-order be locked in on the strength of a table that was
  never populated — the same class of silent pass the pilot guards against elsewhere. The
  column-source integrity hash is pinned for the same reason: an empty `expected` value
  made the one check against upstream FOCUS drift inert.

## Component layout

| Path | Contents |
| ---- | -------- |
| [contracts/](../contracts) | Machine-readable schema and physical Delta/compaction contracts (including the write/restatement, row-conservation, and batch-handoff invariants) that the code loads and enforces. |
| [validation/](../validation) | The contract validator the notebooks import (unit-tested, no Spark required). |
| [notebooks/](../notebooks) | Fabric notebooks 01–05: validate → write Delta → compact (with metrics) → layout precondition → promotion decision, plus the shared `lib/` helpers (`restatement`, `metrics`, `readiness`, `promotion`, `schema_bridge`). |
| [deploy/manual/](../deploy/manual) | The proven-first manual setup and a fail-loud preflight check (including the private-networking guard). |
| [deploy/automation/](../deploy/automation) | Idempotent Fabric REST provisioning (get-or-create) over the manual path. |
| [deploy/orchestration/](../deploy/orchestration) | The ADF→Fabric notebook handoff (Bicep). |
| [power-bi/](../power-bi) | The SQL-endpoint report variant, applied as a one-line source swap. |

### Operational tables

| Table | Written by | Purpose |
| ----- | ---------- | ------- |
| `_pilot_ingestion_metrics` | 02 | Append-only ledger of every restatement: months, rows removed, rows written, Delta version. Makes a destructive replace auditable after the fact. |
| `_pilot_compaction_metrics` | 03 | One row per compaction run; the input to both the SLA check and the layout precondition. |
| `_pilot_directlake_gate` | 04 | One row per layout evaluation, with per-check results and reasons. |
| `_pilot_directlake_promotion` | 05 | The promotion verdict and Z-order validation status. |
| `_pilot_query_filter_stats` | *nothing yet* | Intended input for Z-order validation. Until a producer exists, 05 correctly reports the Z-order as `unvalidated`. |

## Testing

The pilot's logic is validated without live Azure resources:

- **57 Python unit tests** — schema/null/version enforcement, column-source integrity and
  open-data parity, row-count conservation, batch completeness, restatement predicate and
  shrink guard, active-file selection, compaction-SLA math, layout-precondition conditions,
  and promotion + Z-order logic.
- **1 behavioural test module against a real Delta engine** — proves a re-run does not
  duplicate cost data and that a restated month replaces rather than accumulates. Skipped
  unless `pyspark` and `delta-spark` are installed. This one needed a real engine: the
  duplication it guards against balanced every per-hop row count, so no pure-logic test
  could have caught it.
- **12 Pester tests** — deployment-parameter validation and the fail-loud preflight,
  including the private-networking guard.
- **`az bicep build`** — the ADF→Fabric orchestration pipeline compiles clean.

These prove the logic and contract enforcement. They intentionally do not prove an
end-to-end run against a live Fabric Lakehouse, which requires a Fabric capacity and a
full billing cycle to validate the promotion gate and the cost-ceiling claim.

Two limits are worth naming rather than leaving implied. First, the behavioural tests run
on the `pyspark` / `delta-spark` pair pinned in `requirements-dev.txt`, which is a newer
Spark and Delta than the Fabric runtime ships; `replaceWhere` is long-stable API, but the
combination the pilot depends on has not been exercised on a Fabric runtime. Second,
nothing in the suite touches OneLake, the SQL analytics endpoint, or a semantic model, so
a green run says the logic is right, not that the platform integration works.

## For roadmap consideration

The pilot deliberately targets the common case: a standard, reliable, high-volume
reporting path for people who should not have to reason about Delta internals or Fabric
SKU mechanics. Several stronger or more specialized options were evaluated and set aside.
None were rejected on merit — each is recorded here with the condition that would make it
worth adopting, either as a future growth of this pilot or as a separate solution.

### Eventhouse OneLake availability instead of a Spark pipeline

FinOps hubs already support Fabric Real-Time Intelligence, and an eventhouse KQL database
can mirror its tables into OneLake as Delta with a toggle. For a hub already on RTI, that
would deliver FOCUS-normalized Delta in OneLake with no ingestion notebooks, no
restatement handling, no compaction job, and no VACUUM — collapsing notebooks 01–03 and
most of this pilot's operational surface.

**Not adopted because** mirrored tables are read-only with a file layout determined by KQL
extents, so they cannot be compacted, Z-ordered, or V-Ordered. That is precisely the lever
this pilot exists to pull, and it is also load-bearing for Direct Lake. It also makes the
pilot depend on a deployed hub, so it would no longer be self-contained.

**Adopt it when** the mirrored layout is measured against the Direct Lake guardrails on
real data and either meets them, or the SQL-endpoint path alone proves fast enough at the
target volume. If so, this pilot reduces to the layout precondition and promotion
notebooks over a hub-owned table — a materially smaller and better-factored solution.

### Liquid clustering instead of partitioning plus Z-ORDER

Liquid clustering supersedes Hive partitioning plus `ZORDER` in current Delta guidance,
and its clustering keys can be changed without rewriting the table. That would dissolve
the `zorder.status: provisional` problem outright: the columns could be revised once real
query telemetry exists, instead of being locked in by the initial layout.

**Not adopted because** it is mutually exclusive with the current partition + Z-ORDER
design rather than additive, it is less proven on Fabric runtimes than the conservative
layout, and it would invalidate parts of the D2 contract and the tests that enforce them.

**Adopt it when** the Fabric runtime in use documents liquid clustering as supported for
Lakehouse Delta tables alongside V-Order, and the pilot has a real query-telemetry
producer — clustering still needs evidence for its keys, so it removes the cost of being
wrong, not the need to be right.

### A Direct Lake semantic model as part of the pilot

Notebook 04 clears table layout only. A complete answer would ship a Direct Lake semantic
model and measure it: relationships and one-side uniqueness, RLS/OLS with fixed identity,
framing behaviour after each `OPTIMIZE`, cold-query latency, memory pressure at the target
volume, and observed fallback. On Direct Lake on SQL, setting `DirectLakeBehavior` to
`DirectLakeOnly` during validation turns the silent fallback into an error — which is more
in keeping with this pilot's philosophy than any gate. Direct Lake on OneLake has no
DirectQuery fallback at all, making it a different design choice rather than a setting.

**Not adopted because** it requires a Fabric capacity, real data volume, and a billing
cycle to mean anything, and the DirectQuery path already delivers the reporting value.

**Adopt it when** the layout precondition has held over a full cycle on real data. This is
a graduation criterion, not an optional extra: without it the pilot cannot claim Direct
Lake at all. Note also that daily `OPTIMIZE` invalidates in-memory column segments, so the
maintenance cadence and Direct Lake framing need to be designed together rather than
separately.

### Per-SKU Direct Lake guardrail lookup

The contract requires the operator to record their capacity's row, file, and size limits.
A built-in SKU lookup table would remove that step.

**Not adopted because** those published limits have changed repeatedly, there are several
distinct limits (rows per table, files per table, row groups, model memory), and Direct
Lake on OneLake and on SQL do not share semantics. Shipping numbers that cannot be verified
at authoring time is what produced the flat, permissive default this replaced.

**Adopt it when** the limits can be sourced programmatically — from the capacity itself or
a maintained reference — rather than transcribed into a file that ages silently.

### Fabric-native deployment and packaging

The pilot uploads `.py` files into Lakehouse Files and extends `sys.path` to import them.
Fabric Git integration, deployment pipelines, Fabric Environments with a packaged `.whl`,
the Fabric Terraform provider, and the Fabric CLI now cover this lifecycle properly.

**Not adopted because** selecting among them is its own evaluation, and the manual path is
deliberately the proven one (Decision 3).

**Adopt it when** the pilot enters the build/packaging system. At that point `focus_pilot`
should ship as a wheel attached to a Fabric Environment rather than as loose files, and
the ADF handoff should orchestrate the full 01–05 sequence rather than a single notebook id.

### Private networking via workspace identity

The preflight currently rejects `privateNetworking` outright, on the grounds that Fabric
ingests via impersonation and so cannot use the storage "trusted Microsoft services"
bypass that Azure Data Explorer relies on. Fabric workspace identity with trusted workspace
access, and managed private endpoints, now address this directly.

**Not adopted because** the supported capacity floor and configuration steps need to be
confirmed against current documentation before the pilot promises the scenario works;
trial capacities remain excluded.

**Adopt it when** those prerequisites are confirmed. The rejection should then become a
validated configuration path — workspace identity, RBAC, and a storage resource-instance
rule — rather than a hard failure.

### Measuring the pilot's own economics

A materialization path in a FinOps toolkit should report its own cost: Spark CU
consumption for ingestion and compaction, SQL endpoint and semantic-model load, OneLake
storage growth including files awaiting `VACUUM`, and a cost-per-million-rows figure
comparable against the storage and hubs+RTI paths. Autoscale Billing for Spark is worth
evaluating alongside this, since it moves notebook jobs off the F-capacity and would
address the capacity-throttling symptoms documented in the pilot README.

**Not adopted because** it needs a capacity and a billing cycle to produce real numbers.

**Adopt it when** the pilot runs on real data. This is a graduation criterion — the
cost-ceiling claim that motivates the whole pilot is currently an estimate, and a FinOps
artifact should not ship an unmeasured economic argument.

