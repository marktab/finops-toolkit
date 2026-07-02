# FinOps Fabric / OneLake pilot

An **optional, self-contained** path that materializes the FinOps toolkit's
already-normalized FOCUS cost data as a **managed Delta table in OneLake**, so it
can be compacted and served fast to Power BI. It lives beside the existing toolkit
and can be removed without impact — nothing in the current hub changes.

## If you know the legacy solution, here's what's different

| | Legacy hub (Parquet / KQL) | This pilot (Fabric / OneLake) |
|---|---|---|
| **Where cost data lands** | Azure Data Explorer (KQL) or Parquet in storage | Managed Delta table in OneLake |
| **Who owns the data shape** | KQL transform | **Still KQL** — this pilot only *validates* the output against a contract; it does not re-implement normalization in Spark |
| **Small-file ceiling** | Parquet/Power BI path slows near $2–5M/month because many small files can't be compacted | Managed Delta is compacted daily (OPTIMIZE + Z-ORDER), removing the ceiling |
| **Power BI connection** | Import/DirectQuery over storage | SQL analytics endpoint first; **DirectLake is earned**, gated by a readiness check, not assumed |
| **How contracts are enforced** | Documented conventions | Machine-readable contracts (`contracts/`) that **fail loudly** in code when reality drifts |

The guiding principle: every "if this breaks" case here is a *silent* failure, so each
contract is enforced by code that **stops loudly** rather than a doc nobody re-checks.

## Run order

1. `notebooks/00_generate_sample_focus.py` — optional: generates a small synthetic
   FOCUS 1.2 dataset so you can prove the pipeline end-to-end without real data.
2. `notebooks/01_ingestion.py` — schema-validated ingestion (Decision 1).
3. `notebooks/02_delta_write.py` — managed Delta write, partitioned by `x_ChargeMonth` (Decision 2).
4. `notebooks/03_compaction.py` — compaction with monitored SLA metrics (Decision 2).
5. `notebooks/04_directlake_readiness.py` — GO / NO-GO DirectLake gate (Decision 4).
6. `notebooks/05_promotion.py` — promotion decision.

Before any of that, run the fail-loud preflight in `deploy/manual/` against your
filled-in parameters (`deploy/manual/deploy-parameters.sample.json` is the template).

## Endpoints by cloud

The two endpoints you supply — the OneLake ABFSS path and the SQL analytics endpoint —
have the same shape everywhere; **only the host segment changes by cloud**. Defaults
throughout this pilot target the **public commercial cloud**.

| Cloud | OneLake DFS host | SQL endpoint suffix |
|---|---|---|
| **Commercial** (default) | `onelake.dfs.fabric.microsoft.com` | `.datawarehouse.fabric.microsoft.com` |
| **Microsoft internal (msit)** | `msit-onelake.dfs.fabric.microsoft.com` | `.msit-datawarehouse.fabric.microsoft.com` |
| **Sovereign** (Gov / air-gapped) | your cloud's OneLake DFS host | your cloud's SQL endpoint suffix |

### Where to find your values (authoritative source)

- **OneLake ABFSS path** — Lakehouse **> Properties**. Form:
  `abfss://{workspace}@{onelake-host}/{lakehouse}.Lakehouse`
- **SQL analytics endpoint** — Lakehouse **> SQL analytics endpoint > Settings**
  (host only, no `https://`, no database suffix).

Always copy these from the portal for your tenant rather than assuming — the portal is
authoritative and immediately tells you which host your cloud uses.

### Sovereign cloud

The pilot **defaults to commercial** and also accepts the Microsoft-internal (msit)
hosts out of the box. For a sovereign cloud, keep the same shape and substitute your
cloud's host in these three places:

1. `deploy/manual/deploy-parameters.schema.json` — widen the `oneLakeEndpoint` and
   `sqlEndpoint` regex patterns to include your suffix.
2. `deploy/automation/Initialize-PilotFabric.ps1` — pass `-OneLakeHost` with your
   cloud's OneLake DFS host (the SQL endpoint is read back from the Fabric API, so it
   is already correct). You may also need `-ApiBaseUrl` for your cloud's Fabric API.
3. `power-bi/expressions.fabric.tmdl` — extend the `START HERE` suffix check with your
   cloud's SQL endpoint suffix.
