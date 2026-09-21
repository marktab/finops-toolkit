# Power BI — Fabric SQL-endpoint connection swap

This folder provides **source-swap fragments**, not a complete new report variant.
They adapt the `Costs` source in a copy of an existing storage-based toolkit report to
the Lakehouse **SQL analytics endpoint**; they do not automatically convert a KQL report.
The preferred minimal swap retains the existing **Import** partition. The optional
whole-partition fragment is **DirectQuery**. Neither implements Direct Lake.

SQL/report compatibility is an experiment to validate, not a demonstrated result.
A successful Import swap does not remove Import refresh, memory, or model-size limits
or prove TB-scale performance or favorable economics. Evaluate supported RTI reporting
and Eventhouse OneLake availability first; preserve existing consumers.
Actual source schema and SQL/report numeric representation are not yet verified.
Report changes and live validation require separate authorization.

## What's here

| File | Purpose |
|---|---|
| `queries/ftk_FabricSql.pq` | Candidate SQL source query; compatibility must be reconciled against the accepted normalized data and target report. |
| `expressions.fabric.tmdl` | The `SQL Endpoint` and `SQL Database` parameters plus a `START HERE` validation, mirroring the storage report's setup parameters. |
| `Costs.partition.fabric.tmdl` | The swapped `Costs` partition source (`ftk_FabricSql("focuscost")`). |

These fragments intentionally are **not** a full duplicate report. Duplicating the entire
`CostSummary.Report` and `Shared.Dataset` would bloat the pilot and drift from the
maintained toolkit report over time. Instead, apply the fragments to a copy of the report
you already have and validate before opting in a consumer.

## Apply the swap (recommended: minimal one-line source change)

Work against a copy of an existing report, for example `CostSummary.storage.pbip`.

1. **Add the parameters.** In Power BI Desktop, **Transform data > Manage Parameters >
   New**, add two `Text` parameters and set their values from your Lakehouse:
   - `SQL Endpoint` — the SQL analytics endpoint host (no `https://`, no database suffix).
   - `SQL Database` — the Lakehouse name.

   These correspond to the parameters defined in `expressions.fabric.tmdl`.
2. **Add the `ftk_FabricSql` query.** **New Source > Blank Query > Advanced Editor**, paste
   the contents of `queries/ftk_FabricSql.pq`, and name the query exactly `ftk_FabricSql`.
3. **Swap the `Costs` source.** Edit the `Costs` query and change the single line:

   ```powerquery-m
   RawData = ftk_Storage("focuscost")
   ```

   to:

   ```powerquery-m
   RawData = ftk_FabricSql("focuscost")
   ```

   Keep every other step, including tag promotion. Verify that the actual normalized
   input and downstream transformations agree; do not assume that every step is an
   identity operation or that any Parquet export contains the expected enrichment.
4. **Close & Apply**, then **Refresh**. Verify the actual partition remains Import,
   relevant measures/visuals render, and grouped totals by currency/month/scope agree
   with independent expected results. Record refresh and representative visual evidence.

## Field-mapping reference (whole-partition swap)

If you prefer to replace the whole `Costs` partition rather than the one line, map the
shipped fragments to the report's semantic model as follows:

| Fragment | Destination in the report's `Shared.Dataset` |
|---|---|
| `expressions.fabric.tmdl` parameters | `definition/expressions.tmdl` (add the `SQL Endpoint` / `SQL Database` parameters) |
| `queries/ftk_FabricSql.pq` | a new shared expression named `ftk_FabricSql` |
| `Costs.partition.fabric.tmdl` | replaces the `Costs` partition in `definition/tables/Costs.tmdl` |

The whole-partition swap uses `mode: directQuery` and drops client-side tag promotion.
Normalized rows do not automatically include the report's promoted `tag_*` columns.
Prefer the one-line swap; if testing the optional fragment, validate those columns,
relationships, query support, permissions, measures, and performance separately.
Do not report the DirectQuery fragment as tested based on an Import refresh.

## Acceptance, evidence, and rollback

- Use the accepted full-month/scope input and single-writer procedure in the
  [pilot README](../README.md#input-acceptance-and-coexistence-boundary).
  All canonical logical Decimal fields target exact `decimal(38,18)`, accepting only
  decimal inputs that fit without rounding/overflow and rejecting double, float,
  string, and integer inputs for those fields. The complete Decimal field set comes
  from pinned canonical metadata and uses zero storage-acceptance tolerance.
  Logical Number remains finite `double`.
  Existing incompatible `Costs` types fail before writing; no destructive migration
  is authorized. Verify actual SQL endpoint and Power BI representation rather than
  assuming they expose identical precision. Reconcile fractions and credits with
  justified explicit tolerances at the consumer boundary; those tolerances do not
  permit rounding during storage acceptance. Actual upstream schema and live
  SQL/report execution remain unverified.
- [Microsoft Learn documents Delta DECIMAL → SQL `decimal(p,s)`](https://learn.microsoft.com/fabric/data-warehouse/data-types#autogenerated-data-types-in-the-sql-analytics-endpoint).
  This platform mapping does not verify this endpoint's synchronized schema or the
  model's numeric behavior; retain the required live reconciliation.
- Wait for bounded, observed SQL synchronization; stale rows or schema cannot pass.
  Check actual schema/table names in this endpoint. The query currently selects
  lowercase `dbo.costs`; casing behavior must be verified in the chosen environment.
- Record exact revision, runtime/capacity, permissions/licenses, refresh mode, counts,
  grouped financial totals, and a relevant measure/visual. No blanket license or
  latency guarantee is made. Capacity throttling does not prove the query is correct.
- Other model tables may still use storage and need existing credentials. Do not
  remove credentials or cancel required authentication as a general workaround.
- Review independent storage-model `SkuMeter` fix `e98d4016` before validating this swap,
  with its own regression evidence; it is a dependency, not a pilot feature.
- Isolate the report copy. Rollback restores its original source and verifies refresh;
  it is not automated failover. Never union RTI costs with duplicate costs from the copy.

Mandatory manual Fabric/SQL/Import report validation is pending separate authorization;
no successful live refresh or visual is claimed here.

## Notes

- **Cloud examples:** suffix acceptance in `START HERE` is not proof of live support.
  `msit` and sovereign examples are untested; verify current availability and actual
  endpoints before separately approving configuration changes.
- **Direct Lake:** notebook 04 reports only listed point-in-time layout checks. It
  does not validate or authorize a semantic model. Mode choice, security, relationships,
  framing, memory, latency and mode-specific fallback need independent validation;
  V-Order verification is not performed.
