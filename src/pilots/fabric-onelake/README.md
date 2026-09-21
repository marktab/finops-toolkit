# FinOps Fabric / OneLake pilot

An optional, isolated **supplied normalized Parquet → managed Delta → SQL analytics
endpoint → existing-report source compatibility** experiment. It does not connect to
Eventhouse, perform upstream FOCUS normalization, or change existing hubs and reports.
The supplier must provide and accept complete monthly snapshots before replacement.

## Purpose and authorization

On September 21, 2026, the requesting operator authorized local implementation as a
bounded engineering experiment. The hypothesis is that supplied normalized Parquet can
support safe managed Delta month replacement, SQL reconciliation, and an existing-report
source swap. No named customer, RTI deficiency, performance advantage, or economic benefit
has been demonstrated. The **pilot author/requesting operator** owns source acceptance,
maintenance of this experiment, evidence, and stop decisions.

The current budget is **local-only, zero authorized cloud spend**. Capacity use,
deployment, report changes, commits, pushes, and publication need separate authorization.
The selected future validation path is **manual-only**; optional REST provisioning and
ADF execution are **live-unvalidated**. Local preparation is not technical PR-readiness.
Stop on correctness failures; do not run capacity validation without explicit access,
budget, ownership, and cleanup approval.

Success requires fresh regression evidence, actual Spark/Delta execution, and the
[mandatory synthetic Fabric/SQL/report protocol](#required-validation-and-evidence)
on the final code/configuration. Missing authorization or mandatory evidence blocks
readiness. It does not justify manufacturing a customer need or declaring tests passed.

## Evaluate supported paths first

Azure Data Explorer and Fabric Real-Time Intelligence (RTI) are established supported
toolkit reporting paths. Existing RTI deployments are investments to preserve, not
presumed bottlenecks. Consult the [current report support matrix][report-support].

| Situation | Guidance |
| --- | --- |
| RTI meets the requirement | Keep RTI; Delta maintenance controls alone do not justify another copy. |
| Storage reports struggle | Evaluate supported ADX/RTI; a storage bottleneck does not establish an RTI problem. |
| An RTI user wants lake/SQL/notebook consumption | Evaluate [Eventhouse OneLake availability][eventhouse] and the relevant consumer first. SQL access requires the applicable availability and schema-synchronization setup. |
| Managed OneLake access meets the need | Prefer it over maintaining a separate Spark copy. Lack of manual OPTIMIZE is not evidence of poor managed performance. |
| Independent serving-table lifecycle or layout control is needed | Evaluate this isolated copy with explicit ownership and measured incremental value. |
| Lower costs or faster reports are the motivation | Treat them as unproven hypotheses, not adoption recommendations. |

Issue [#1009](https://github.com/microsoft/finops-toolkit/issues/1009) records the RTI
direction and removal of Lakehouse-report work from scope; merged
[PR #1523](https://github.com/microsoft/finops-toolkit/pull/1523) delivered RTI support.
Issue [#1246](https://github.com/microsoft/finops-toolkit/issues/1246) describes an
integration/data-layer use case, not a requirement for this Delta copy. On September 21,
2026, read-only GitHub API inspection found #1009 closed, #1246 open with no comments,
and #1523 merged. Issue checkboxes are not independent implementation evidence.
This experiment does not claim to close either issue.
The linked Microsoft Learn support, Eventhouse availability, and table-maintenance
guidance was also inspected on September 21, 2026; recheck it before publication.

## Input, acceptance, and coexistence boundary

Notebook 01 reads a configured Parquet path. **The actual upstream export artifact,
producer stage, schema, extraction/casts, remaining KQL enrichment, and ADX/Eventhouse
dependencies are not yet verified.** Canonical metadata defines the standalone contract,
not proof that any ingestion-container file satisfies it. KQL retains upstream business
semantics; the pilot must not duplicate normalization or infer exported types from a
Kusto declaration. Do not automatically re-pin canonical metadata.

The operator must complete this **pre-write acceptance procedure** before every run of
01/02, including manual, retry, backfill, and orchestrated entry points:

1. Identify the immutable source artifact/batch and its producing stage, schema evidence,
   applied transformations, and any remaining enrichment/engine dependency. Refuse the
   write if the normalized contract cannot be established.
2. Record the target table identity, agreed scope set, every intended replacement charge
   month, and independent evidence that each month covers every intended scope. Use the
   producer's expected results or another independently established acceptance record,
   not counts generated from the same suspect input.
3. Record source version/order and compare it with the last accepted batch for every
   affected month. Refuse older corrections after newer accepted data and refuse
   ambiguous ordering. A replay must be the same accepted complete snapshot.
4. Refuse missing/ambiguous coverage, report-filtered partial months, increments,
   asynchronous subsets, and intentional zero-row replacements. An empty DataFrame
   cannot convey intended deletion months. Re-scoping/deletion requires a separately
   designed and approved procedure, not an override treated as routine success.
5. Establish one writer across **all** entry points: prevent new manual/ADF runs, verify
   no ingestion, replacement, or maintenance run is in flight for this table/staging
   location, and hold the operator's exclusive run window through completion and
   reconciliation. If isolation cannot be established, stop. One ADF pipeline's
   concurrency setting is not a global lock.
6. Retain the operator acceptance record with batch identity, coverage, independent
   expected counts/totals, ordering decision, isolation window, and resulting target
   version. Resume other entry points only after reconciliation or recorded recovery.

Set notebook 02's required nonempty `acceptance_record_id` to the reference for this
independent coverage, ordering, and all-entry-point exclusive-writer decision, alongside
`ingestion_id` and the endpoint parameters. The notebook prints the reference but does
not verify the record or add it as a ledger field. The operator must retain the durable
acceptance evidence; supplying an identifier alone does not establish acceptance.

These are **operator controls, not automated upstream-completeness, stale-batch, or
global-lock detection**. The ingestion-generated staging manifest establishes
source-to-staging and staging-to-writer conservation only. The restatement row-count
floor is a heuristic: missing scopes can exceed it, omitted months cannot be inferred
from observed rows, and aggregate counts can hide per-month loss.

Accepted complete months replace existing months atomically, rather than append.
Notebook 02 explicitly sets the Spark session time zone to **UTC** before deriving
`x_ChargeMonth` from `ChargePeriodStart`. Replacement months therefore use UTC calendar
boundaries; a local time zone must not move a midnight-UTC charge into the prior month.
Replay safety is bounded by the accepted snapshot and single-writer restriction.
Reconcile open-month updates, closed-month corrections, and unchanged other months.
Do not union duplicate costs from RTI and the copy. Leave RTI tables, retention,
reports, and managed OneLake files unchanged; OPTIMIZE only the pilot-owned Delta table.

Extraction and copy/SQL/report access need independent authorization. RTI permissions
do not automatically protect the copy. Record additional extraction, Spark, storage,
query/refresh, support, contention, latency, and recovery costs. Source/backfill
retention, serving-copy retention, query/report date windows, and Delta time travel are
different controls; a wider filter cannot recover missing history. Rollback is an
explicit source reversion for the opted-in report, not automatic failover.

### Numeric acceptance and target compatibility

The requesting operator selected **exact `decimal(38,18)`** storage for **every
canonical logical Decimal field**, not just `BilledCost` or a selected set of costs.
Only decimal-typed inputs whose values fit exactly without rounding or overflow are
accepted for those fields. Double, float, string, and integer inputs are explicitly
unsupported for Decimal fields; do not silently cast them into acceptance. Canonical
logical Number fields remain finite `double`. Derive every applicable Decimal field
from the pinned canonical metadata; preserve its nullability rules and integrity pin.

The numeric helper casts accepted exact values to `decimal(38,18)` before staging
and revalidates them before writing. The existing-target guard rejects incompatible
canonical numeric columns; it does not rebuild the target.

The target can hold 20 integral digits and 18 fractional digits. A source decimal's
declared precision/scale alone does not establish that its actual values fit; no
rounding tolerance is allowed at this storage boundary: tolerance is **zero**.
Required regression must
exercise fitting decimal variants and rejected types/values across all applicable
fields, then verify persisted types and exact values through ingestion, staging,
and replacement.

Existing incompatible `Costs` types must fail **before writing** with the existing
data intact. No automatic conversion, dropping/recreating the table, or other
destructive target migration is authorized. This is a standalone input/target policy,
not evidence that the actual upstream export satisfies it.
[Microsoft Learn documents Delta DECIMAL mapping to SQL `decimal(p,s)`](https://learn.microsoft.com/fabric/data-warehouse/data-types#autogenerated-data-types-in-the-sql-analytics-endpoint)
(inspected September 21, 2026). That documented mapping is not verification of this
endpoint or Power BI model. Live SQL/report type representation and reconciliation
remain unverified and mandatory before readiness.

## What's included

| Path | Scope |
| --- | --- |
| `contracts/` and `validation/` | Canonical schema bridge, integrity pin, declared acceptance/type and layout checks. |
| `notebooks/01_ingestion.py` | Validate supplied normalized Parquet and stage with a self-derived manifest. |
| `notebooks/02_delta_write.py` | Replace accepted complete charge months in the pilot-managed Delta table. |
| `notebooks/03_compaction.py` | OPTIMIZE and active-snapshot metrics under provisional policy. |
| `notebooks/04_directlake_precondition.py` | Point-in-time listed layout checks, not Direct Lake authorization. |
| `notebooks/00_generate_sample_focus.py` | Optional deterministic synthetic input and independent expected-results generator. |
| `deploy/` | Manual setup/preflight plus optional, live-unvalidated provisioning and single-notebook ADF runner. |
| `power-bi/` | Source-swap fragments, not a complete report variant or Direct Lake model. |

There are **four functional notebooks (01–04), plus optional 00**. Notebook 05 and its
promotion/history, query-filter-reader, and telemetry recommendation APIs are retired,
with no replacement reporter. Keep old operational tables/data; do not use legacy or
mixed diagnostic logs as trustworthy billing-cycle history without independent review.
See [developer compatibility notes](docs/README.md#diagnostic-compatibility).

## Layout and runtime policy

Logical month replacement is distinct from physical `x_ChargeMonth` partitioning and
from aggregation. This pilot does not implement monthly summary tables. Current
partitioning, Z-order columns, daily OPTIMIZE, 128 MB target / 64–256 MB range, average
file-size and small-file thresholds are **provisional workload settings**, not platform
eligibility rules or demonstrated optima. The historical 256 MB–1 GB proposal was also
unproven. Small partitions and tail files can legitimately miss a size target.

The 26-hour freshness threshold means **a daily interval plus two hours of lateness**,
not permission to miss an entire daily run. Scheduling of 03, diagnostic cadence for
04, alert routing, and recovery are operator-owned and unprovisioned.

Consult [current cross-workload maintenance guidance][maintenance] for the selected
supported runtime: adaptive sizing, auto-compaction, justified partitioning, and
measured clustering predicates matter; runtime 2.0 defaults differ from runtime 1.3
opt-ins. Record actual inherited/explicit settings and unknowns. This correction does
not upgrade runtimes, introduce liquid clustering/deletion vectors, or retrofit files.
V-Order configuration and file-level verification are deferred; **not verified does
not mean disabled or incompatible**.

Notebook 04 passing means only **the listed layout checks passed**. It does not validate
a semantic model, all platform guardrails, framing, relationships, security, memory,
query performance, fallback behavior, or billing-cycle stability. Configure its unset
thresholds using current capacity/mode documentation and explicit workload tuning
choices; an average-size floor is not a universal Direct Lake guardrail.

## Running the notebooks in Fabric

These are future, separately authorized manual validation instructions, not evidence
of a completed deployment:

1. Follow [manual deployment and preflight](deploy/README.md) in an isolated approved
   workspace/Lakehouse. Record runtime and capacity; do not reuse production RTI tables.
2. Upload `notebooks/` (including `lib/`), `contracts/`, and `validation/` directly
   under the Lakehouse **Files** area. `_PILOT_ROOT` assumes
   `/lakehouse/default/Files`; adjust it if the upload location differs.
3. Separately import each selected `.py` as a workspace **Notebook item**. A file
   uploaded to Files is not a runnable Notebook.
4. Attach and set the default Lakehouse in **every** notebook so support imports resolve.
   Use a supported runtime with the `notebookutils.notebook.exit` API used by 04.
5. Fill in notebook parameter cells, manual preflight parameters, the sample generator's
   `ABFSS_ROOT` if used, and the diagnostic thresholds. Notebook 02 requires
   `ingestion_id`, a nonempty `acceptance_record_id` referencing the independent
   operator decision, and endpoint parameters. Endpoints have no safe generic tenant
   value; copy them from your Lakehouse properties/settings.
6. Generate input with optional 00 if needed, complete the pre-write acceptance
   procedure, then run 01 → 02 → 03 → 04. A tiny fixture may fail provisional size checks legitimately. Record
   explicit test-scale overrides to exercise positive paths and test negative paths;
   do not weaken committed defaults to turn a policy failure into a pass.
7. Reconcile the SQL endpoint after bounded observed synchronization, then validate a
   copy of a representative report using [the source-swap instructions](power-bi/README.md).
   Import source compatibility does not remove Import refresh, memory, or model-size limits.

### Synthetic generator parameters and expected results

Optional notebook 00 produces **36 deterministic records** spanning April, May, and
June 2025, two scopes, and two currencies. The fixture includes positive charges,
credits, `1e-18` fractions, nullable optional fields, and every canonical Decimal
field. This is synthetic input only, not a verified upstream export.

Set `ABFSS_ROOT` to the approved Lakehouse root. `OUTPUT_PATH` defaults to
`Files/sample-focus`; the generator adds `-decimal` or `-double` according to
`numeric_variant`. Use the decimal variant for the accepted path. The double variant
is deliberately unsupported for canonical Decimal fields: ingestion must reject it
before target mutation. Do not change the contract to make this negative case pass.
Configure notebook 01's source path to the chosen generated Parquet location.

The generator emits independent Python `Decimal` grouped expected totals as JSON at
`source_path + "_producer_expected"`, with exact comparison tolerance **0**.
Retain that producer evidence, the variant/configuration, and the operator acceptance
record separately from the ingestion-generated staging manifest. Compare observed
counts and totals by month, scope, and currency against the producer expectations;
do not replace expectations with values calculated from suspect staging/target rows.
These fixtures do not establish actual upstream schema compatibility or a real
billing-cycle correction.

### Endpoints by cloud

Copy actual OneLake ABFSS and SQL endpoint values from the selected tenant's portal;
do not construct them from a cloud label. Commercial samples are defaults, not proof of
a tested deployment. The `msit` and sovereign samples are **untested configuration
examples**, not cloud-support claims. Sovereign placeholders and endpoint validation
must be reviewed against current service availability before any attempt. Manual
workspace creation bypasses provisioning automation, not APIs required by ADF.

For missing helper imports, first check Files placement and the default Lakehouse.
For SQL object errors, inspect the actual synchronized schema/table name rather than
assuming casing or successful synchronization. For capacity errors, investigate the
actual capacity/load; throttling does not prove that the query or schema is correct.
Other report tables may still require their original storage credentials.

## Required validation and evidence

**Local evidence status (September 21, 2026):** the coordinating validation owner
reported these final runs against the corrected **uncommitted working tree**, based
on unchanged HEAD `230f27a23f74ef434c806027f0da2179a21fafe7`, not HEAD alone:

| Validation | Result |
| --- | --- |
| System Python 3.13.14 / pytest 9.1.1 | 106 passed; two engine modules skipped because Spark was absent. |
| Restored Python 3.13.14 / pytest 8.3.4 / Spark 4.2.0 / Delta 4.4.0 / JDK 17.0.18 | 126 tests: 106 passed, **20 setup errors**, 0 failed assertions, 0 skips; strict suite exit code **1**. |
| Pester (PowerShell 7.6.6 / Pester 5.8.0) | 45 passed, 0 failed, 0 skipped; offline/mocked/static. |
| Bicep 0.47.16 | Compilation passed without warnings; not live API validation. |
| Python compileall, diff checks, editor diagnostics | Passed; not substitutes for engine execution. |

All 20 engine cases (six diagnostic and 14 numeric/restatement) are blocked by missing
native Windows Hadoop setup (`HADOOP_HOME` / `winutils`). Zero failed assertions does
not make a run with setup errors successful. **The complete regression is not passing
and this branch is not technically PR-ready.** The validation owner retained XML
evidence in local session files; no evidence is published or tied to a newly committed
revision. See [scope and reproduction](docs/README.md#review-order-and-evidence).

Synthetic capacity execution, SQL reconciliation, and representative report
refresh/visual validation remain pending.
The mandatory live run is blocked by the current zero-spend/no-deployment authorization.
Optional live REST provisioning and ADF validation are not selected and remain unvalidated.
See [review order and evidence requirements](docs/README.md#review-order-and-evidence).

After local regression passes and capacity use is separately approved:

1. Record exact tested revision, runtime, capacity SKU, owners, budget, safe window,
   actual endpoints, cleanup scope, runtime/table settings, overrides, and unknowns.
   Prove manual setup/preflight independently of optional automation.
2. Use only reproducible multi-month/multi-scope synthetic data, with independent
   producer expectations by currency/month/scope, charges, credits, small fractions,
   nulls, and numeric acceptance/rejection variants. Record the acceptance procedure.
3. Run 01/02; verify staging conservation, persisted target types, counts and financial
   totals. Replay; apply separate full open-month and synthetic closed-month corrections;
   verify no duplication and unchanged other months.
4. Exercise incomplete/missing scope or month, staging truncation, zero rows, stale
   corrections, and writer isolation on disposable targets. Attribute refusal to the
   real automated check or operator control and verify target preservation. Also prove
   that missing coverage can pass the shrink heuristic; it is not a completeness test.
5. Run 03/04, capturing active-file metrics, target identity, scope/V-Order metadata,
   positive/negative cases, and legacy/additive metadata compatibility. Exercise the
   real adapter's cross-table and fresh/legacy cases using disposable operational
   tables; negative cases must produce the intended error, not just any exception.
   Do not borrow another table's newer evidence. Tiny-fixture overrides are not
   production validation.
6. Reconcile the intended SQL Costs table after a bounded synchronization wait, failing
   on stale/missing state. Compare grouped counts and totals with independent expectations.
7. Run the preferred Import source swap against a representative existing report;
   capture refresh and a relevant visual/measure. Test optional DirectQuery separately
   if claiming it works. Record actual licenses, permissions, and remaining data sources.
8. Exercise failure/recovery and consumer rollback without modifying production RTI.
   Retain sanitized evidence and remove only explicitly owned test resources.

Fix failures and rerun affected cases, then finish with full passing regression and
applicable Fabric scenarios on final code/configuration. Record commands, toolchain,
pass/fail/skip counts, exact revision, and evidence locations; skipped mandatory Spark
or live checks are not passes. Small synthetic runs do not establish actual upstream
integration, real billing-cycle correctness, TB-scale performance, security across all
access paths, favorable economics, Direct Lake behavior, or operational readiness.

## Non-goals and graduation

The first contribution does not provide a core hub Lakehouse deployment switch,
export-pipeline integration, automatic RTI connector, complete report, Direct Lake model,
monthly aggregation engine, MACC solution, universal retention default, allocation/
finance engine, Copilot release, or new network/export provisioning modes.

Graduation remains substantive and separate from technical PR-readiness:

1. Validate actual upstream handoff and real billing data over at least a full billing
   cycle, including a closed-month restatement and verified history/retention coverage.
2. Sustain relevant layout checks and independently build/measure the selected Direct
   Lake model: relationships/uniqueness, RLS/OLS/identity, framing, cold-query latency,
   memory pressure, and mode-specific fallback behavior.
3. Sustain approved production maintenance policy without synthetic overrides. Establish
   schedules, alert owners, failure recovery, retention/cleanup, and support ownership
   before sustained operation; verify them for graduation.
4. Prove intended endpoints on at least commercial and one non-commercial environment,
   with actual service availability and access evidence, not configuration samples.
5. Measure total economics and operational burden: extraction, Spark, SQL/report load,
   storage including retained files, support, and contention, compared with matched
   storage/RTI and managed OneLake alternatives. Retain, revise, or retire the copy
   based on incremental value.
6. Complete build/packaging/versioning/CI integration and obtain an explicit ownership,
   support, and inclusion decision.

These criteria do not promise automatic upstream merge or relocation out of `pilots/`.
See [conditional follow-on work](docs/README.md#for-roadmap-consideration).

[report-support]: https://learn.microsoft.com/cloud-computing/finops/toolkit/power-bi/help-me-choose
[eventhouse]: https://learn.microsoft.com/fabric/real-time-intelligence/event-house-onelake-availability
[maintenance]: https://learn.microsoft.com/fabric/fundamentals/table-maintenance-optimization
