# Power BI — Fabric SQL-endpoint connection swap

This folder turns an existing FinOps toolkit report into one that reads from the Fabric
Lakehouse **SQL analytics endpoint** instead of storage. It is a **connection swap**, not
a redesign: every visual, measure, relationship, and page is reused verbatim. Only the
data source of the `Costs` table changes (Decision 4: SQL endpoint first, DirectLake later).

## What's here

| File | Purpose |
|---|---|
| `queries/ftk_FabricSql.pq` | Drop-in data-source query — the Fabric equivalent of `ftk_Storage`. Returns the same FOCUS-shaped `Costs` table. |
| `expressions.fabric.tmdl` | The `SQL Endpoint` and `SQL Database` parameters plus a `START HERE` validation, mirroring the storage report's setup parameters. |
| `Costs.partition.fabric.tmdl` | The swapped `Costs` partition source (`ftk_FabricSql("focuscost")`). |

These fragments intentionally are **not** a full duplicate report. Duplicating the entire
`CostSummary.Report` and `Shared.Dataset` would bloat the pilot and drift from the
maintained toolkit report over time. Instead, apply the fragments to a copy of the report
you already have — the mapping below makes that a mechanical, low-risk change.

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

   Keep every other step. The SQL endpoint already serves FOCUS-normalized rows, so the
   downstream tag-promotion and normalization steps pass through harmlessly.
4. **Close & Apply**, then **Refresh**. All existing visuals should render with no rebuild.

## Field-mapping reference (whole-partition swap)

If you prefer to replace the whole `Costs` partition rather than the one line, map the
shipped fragments to the report's semantic model as follows:

| Fragment | Destination in the report's `Shared.Dataset` |
|---|---|
| `expressions.fabric.tmdl` parameters | `definition/expressions.tmdl` (add the `SQL Endpoint` / `SQL Database` parameters) |
| `queries/ftk_FabricSql.pq` | a new shared expression named `ftk_FabricSql` |
| `Costs.partition.fabric.tmdl` | replaces the `Costs` partition in `definition/tables/Costs.tmdl` |

The whole-partition swap uses `mode: directQuery` and drops the client-side tag promotion,
because the Lakehouse already serves normalized rows. Prefer the one-line swap above first —
it keeps `tag_*` columns available for any visual that references them.

## Notes

- **Sovereign clouds:** the `START HERE` validation accepts the commercial and msit SQL
  endpoint suffixes. For a sovereign cloud, extend the suffix check in
  `expressions.fabric.tmdl`. See the pilot [README](../README.md#endpoints-by-cloud).
- **DirectLake:** this swap targets the SQL endpoint only. DirectLake is authorized
  separately by the readiness gate (`notebooks/04_directlake_readiness.py`), not here.
- **Table name casing:** Fabric lowercases Lakehouse table names at the SQL analytics
  endpoint (a table created as `Costs` is queried as `dbo.costs`), and the endpoint is
  case-sensitive. `ftk_FabricSql.pq` already uses lowercase names to match; if you add
  tables, use their lowercase endpoint names.
