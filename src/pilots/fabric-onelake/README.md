# FinOps Fabric / OneLake pilot

The FinOps Fabric / OneLake pilot is an optional, self-contained path that takes the
cost data your FinOps hub already produces and materializes it as a managed Delta table
in Microsoft OneLake, so it can be compacted and served quickly to Power BI. It lives
beside the existing toolkit and can be removed without impact — nothing in your current
hub changes.

The pilot follows four design principles:

- **KQL stays the single transform owner**<br>_The pilot validates the FOCUS data the toolkit already produces; it does not re-implement normalization in Spark._
- **Managed Delta, not shortcuts**<br>_Only managed Delta tables can be compacted and Z-ordered to remove the small-file query ceiling._
- **Prove the manual path first**<br>_The manual deployment is built and proven before automation, so the automation is a convenience over a known-good path — not a single point of failure._
- **DirectLake is earned, not assumed**<br>_Power BI connects to the SQL analytics endpoint first; a readiness gate must pass over a full billing cycle before DirectLake is enabled._

Behind all four is one idea: each of these is a *silent* failure if it goes wrong, so
every contract is enforced by code that stops loudly the moment reality drifts, rather
than a convention written in a doc that no one re-checks.

## Why this pilot?

The toolkit's storage-based Power BI path serves cost data well until an organization's
spend grows large — around \$2–5M/month — at which point the data is split across many
small Parquet files that can't be compacted, and reports slow down. There has not been a
Microsoft Fabric / OneLake path that removes that ceiling. This pilot adds one, without
re-owning the data transform or disrupting anything already deployed.

## What's different from the storage path

If you already know the storage-based hub and reports, here is what changes:

| | Storage path (Parquet / KQL) | This pilot (Fabric / OneLake) |
|---|---|---|
| **Where cost data lands** | Azure Data Explorer (KQL) or Parquet in storage | Managed Delta table in OneLake |
| **Who owns the data shape** | KQL transform | **Still KQL** — the pilot only *validates* the output against a contract; it does not re-implement normalization in Spark |
| **Small-file ceiling** | Reports slow near \$2–5M/month because many small files can't be compacted | Managed Delta is compacted daily (OPTIMIZE + Z-ORDER), removing the ceiling |
| **Power BI connection** | Import / DirectQuery over storage | SQL analytics endpoint first; **DirectLake is earned**, gated by a readiness check, not assumed |
| **How contracts are enforced** | Documented conventions | Machine-readable contracts (`contracts/`) that **fail loudly** in code when reality drifts |

## What's included

- `contracts/` — the machine-readable schema and storage-layout contracts the notebooks enforce.
- `notebooks/` — the ingestion → Delta write → compaction → readiness → promotion notebooks, plus a sample-data generator and the shared `lib/` helpers.
- `validation/` — the contract validator the notebooks import (unit-tested, no Spark required).
- `deploy/manual/` — the proven-first manual setup and a fail-loud preflight check.
- `deploy/automation/` — idempotent Fabric REST provisioning (get-or-create) over the manual path.
- `power-bi/` — the SQL-endpoint report variant, applied as a one-line source swap.

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

## Running the notebooks in Fabric

A few setup facts that are easy to miss the first time:

1. **Upload the support folders to the Lakehouse Files area.** The notebooks import
   their helpers and load their contracts from `/lakehouse/default/Files` (the
   `_PILOT_ROOT` at the top of each notebook). Upload `notebooks/` (which includes
   `lib/`), `contracts/`, and `validation/` into **Files** so those imports resolve.
   In the portal: Lakehouse **> Files > Upload > Upload folder**.
2. **Import each `.py` as a Notebook item — separately from the Files copy.** The `.py`
   file you upload to Files is just source on disk; it is not runnable. Import each one
   as a workspace Notebook (**Import > Notebook > From this computer**) to get a
   runnable item with a **Run all** button. Having the file in both places is normal.
3. **Attach and set the default Lakehouse in EVERY notebook.** Without a default
   Lakehouse, `/lakehouse/default/Files` does not resolve and the imports fail. In each
   notebook: **Add data items** (Explorer pane) **> FinOpsLakehouse >** right-click **>
   Set as default lakehouse**. This is per-notebook, not once per workspace.
4. **`_PILOT_ROOT` matches an upload directly under `Files`** (so `Files/notebooks/lib`,
   `Files/contracts`, `Files/validation`). If you upload the folders somewhere else,
   update `_PILOT_ROOT` at the top of each notebook to match.
5. **The DirectLake gate (04) returns NO-GO on small datasets by design.** That is a
   correct, reasoned verdict — tiny test data cannot meet the DirectLake guardrails.
   The SQL endpoint path still works; DirectLake is earned over a full billing cycle.

## Endpoints by cloud

The two endpoints you supply — the OneLake ABFSS path and the SQL analytics endpoint —
have the same shape everywhere; **only the host segment changes by cloud**. Defaults
throughout this pilot target the **public commercial cloud**.

| Cloud | OneLake DFS host | SQL endpoint suffix |
|---|---|---|
| **Commercial** (default) | `onelake.dfs.fabric.microsoft.com` | `.datawarehouse.fabric.microsoft.com` |
| **Microsoft internal (msit)** | `msit-onelake.dfs.fabric.microsoft.com` | `.msit-datawarehouse.fabric.microsoft.com` |
| **Sovereign** (Gov / China) | *placeholder — supply your host* | *placeholder — supply your suffix* |

> **Sovereign clouds:** Microsoft Fabric is generally available in the commercial cloud
> today; its availability and endpoint hosts in Azure Government and Azure China are still
> emerging. The pilot ships **placeholders** for those clouds rather than guessing hosts —
> supply the real values (from the portal) when Fabric is available in your cloud.

### Where to find your values (authoritative source)

- **OneLake ABFSS path** — Lakehouse **> Properties**. Form:
  `abfss://{workspace}@{onelake-host}/{lakehouse}.Lakehouse`
- **SQL analytics endpoint** — Lakehouse **> SQL analytics endpoint > Settings**
  (host only, no `https://`, no database suffix).

Always copy these from the portal for your tenant rather than assuming — the portal is
authoritative and immediately tells you which host your cloud uses.

### Sovereign cloud

The pilot **defaults to commercial** and also accepts the Microsoft-internal (msit)
hosts out of the box. It follows the toolkit's existing `-AzureEnvironment` convention
(the same names the optimization engine uses: `AzureCloud`, `AzureUSGovernment`,
`AzureChinaCloud`) and a Bicep-style lookup map with explicit overrides — sovereign
entries are placeholders until Fabric publishes those endpoints. To target a sovereign
cloud, keep the same shape and substitute your cloud's host in these places:

1. `deploy/manual/deploy-parameters.schema.json` — widen the `oneLakeEndpoint` and
   `sqlEndpoint` regex patterns to include your suffix.
2. `deploy/automation/Initialize-PilotFabric.ps1` — pass `-AzureEnvironment` for your
   cloud plus `-OneLakeHost` and `-ApiBaseUrl` with your cloud's hosts (the lookup-map
   entries for sovereign clouds are empty placeholders and will fail loudly until you
   supply them). The SQL endpoint is read back from the Fabric API, so it needs no config.
3. `power-bi/expressions.fabric.tmdl` — extend the `START HERE` suffix check with your
   cloud's SQL endpoint suffix.

This mirrors how the rest of the toolkit handles sovereign clouds: Bicep hubs use ARM's
built-in `environment().suffixes` and, where a service isn't covered, a lookup map keyed
by `environment().name` (see `Analytics/app.bicep`); the storage Power BI report takes the
full storage URL as a parameter. The pilot's manual endpoints work the same way — you
paste the full host — so the manual path is already sovereign-friendly.

## Troubleshooting

A quick symptom → cause → fix reference for the issues most likely to appear on first run:

| Symptom | Cause | Fix |
|---|---|---|
| OneLake File Explorer reports *"not in sync" / "Location is not available"* | Desktop app targets commercial OneLake; fails on msit/sovereign | Upload through the Fabric portal (**Files > Upload > Upload folder**) |
| Notebook write to `/lakehouse/default/...` fails | Local mount not writable on msit | Write via the ABFSS endpoint (see `notebooks/00_generate_sample_focus.py`) |
| `ModuleNotFoundError` importing `focus_pilot` or `contract_validator` | No default Lakehouse attached, or support folders not uploaded | Attach + set default Lakehouse; upload `notebooks/`, `contracts/`, `validation/` to Files |
| `FileNotFoundError` on `FocusCost_1.2-preview.json` | Column-source file not uploaded with the contracts | Re-upload the `contracts/` folder |
| `ContractViolation: ... expected json, got string` | Older contract mapped JSON columns to `json` | Re-upload the current `contracts/` (JSON maps to `string`) |
| `ContractViolation: average file size below floor` on tiny data | Production SLA thresholds vs. synthetic test data | Expected on small data; contract ships pilot-scale thresholds — restore production values before real data |
| `DirectLake NO-GO` on small data | Dataset too small to meet DirectLake guardrails | Expected and correct; the SQL endpoint path still works |
| `DataSource.CapacityExceeded` in Power BI | Trial Spark sessions still consuming capacity | Stop notebook sessions (**Monitor** hub) and retry after a few minutes |
| Power BI refresh prompts for an Azure Blob storage account | Other report tables still point to storage | Expected — only `Costs` is swapped; cancel the prompt |
| SQL endpoint: `Invalid object name 'Costs'` | Fabric lowercases Lakehouse table names at the SQL analytics endpoint | Query the lowercase name (`dbo.costs`); the shipped `ftk_FabricSql.pq` already uses lowercase |

## Known issues on Microsoft-internal (msit) and sovereign tenants

These are environment quirks, not pilot bugs — you will hit them on msit and possibly on
sovereign/air-gapped tenants, and the fix is operational:

- **OneLake File Explorer (desktop app) may not sync** — it can report *"not in sync with
  the cloud" / "Location is not available"* on msit even when signed in with the correct
  account, because it targets the commercial OneLake. **Upload through the Fabric portal
  instead** (Lakehouse **> Files > Upload > Upload folder**).
- **The local `/lakehouse/default` mount can fail for writes** on msit. Read/import via the
  mount works once a default Lakehouse is attached, but write via the **ABFSS endpoint**
  instead (see `notebooks/00_generate_sample_focus.py`, which writes to `ABFSS_ROOT`).
- **Trial and low-SKU capacities throttle** after Spark notebook runs. Symptoms:
  `DataSource.CapacityExceeded` in Power BI, or *"your organization's Fabric compute
  capacity has exceeded its limits"*. **Stop notebook Spark sessions** (each notebook's
  **Stop session**, or the **Monitor** hub) and retry after a few minutes. This is a
  capacity limit, not a connection or schema error — the swap/query is already correct.

## Running the tests

The contract validator and library logic are unit-tested and require no Spark cluster, so
they run anywhere Python is available:

```bash
python -m pytest src/pilots/fabric-onelake/notebooks/tests/test_focus_pilot.py
python -m pytest src/pilots/fabric-onelake/validation/test_contract_validator.py
```

These cover the schema/type/non-null contract rules and the compaction SLA logic — the
same checks the notebooks enforce at runtime — so a contract regression is caught without
deploying to Fabric.

## Pilot status and graduation

This is a **pilot**, and the folder name is a lifecycle stage — not a verdict on quality.
It lives under `pilots/` because a few things are true only at pilot scale today, and the
`pilots/` location keeps the promise that it is self-contained and removable while those
prove out. "Pilot" here means *staged with a known graduation path*, not *demo*.

**What "pilot" means right now**

- Contracts, validation, the fail-loud preflight, and the unit tests are production-grade
  and run without a cluster.
- The compaction SLA thresholds are set to **pilot-scale** values so synthetic test data
  passes (`contracts/storage-layout.contract.json` notes the production values to restore).
- DirectLake is gated: the readiness check returns NO-GO until real data volume is present,
  so the SQL-endpoint path is the supported connection today.

**Graduation criteria — what has to be true to leave `pilots/`**

1. Runs against **real billing data** for at least one full billing cycle.
2. The **DirectLake readiness gate passes** on that real data.
3. Compaction SLA thresholds are **restored to production values** and hold over that cycle.
4. Endpoints are proven on at least the commercial and one non-commercial cloud.
5. The component is wired into the **build/packaging system** (versioning, tests in CI).

**Where it graduates to**

When those hold, this becomes a first-class **Fabric / OneLake materialization path** for
the toolkit — a peer to the storage and KQL paths, moved out of `pilots/` into the main
`src/` structure and packaged like the other components. Until then, it stays here,
reversible and clearly labeled.
