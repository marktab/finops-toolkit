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
- **Direct Lake is earned, not assumed**<br>_Power BI connects to the SQL analytics endpoint first; a layout precondition must hold over a full billing cycle, and a semantic model must be measured, before Direct Lake is enabled._

Behind all four is one idea: each of these is a *silent* failure if it goes wrong, so
every contract is enforced by code that stops loudly the moment reality drifts, rather
than a convention written in a doc that no one re-checks.

## Why this pilot?

The toolkit's storage-based Power BI path serves cost data well until an organization's
spend grows large, at which point the data is split across many small Parquet files that
can't be compacted, and reports slow down. (The toolkit's own guidance puts the storage
path's practical limit at roughly \$1M/month in monitored spend; where exactly reports
become unusable is workload-dependent and this pilot has not yet measured it on real data.)

The toolkit already has a Microsoft Fabric path: FinOps hubs can use **Fabric Real-Time
Intelligence (RTI)** — an eventhouse — as a primary or secondary data store, and that is
the recommended option today for the best performance and functionality. What has not
existed is a **OneLake Delta** path: cost data materialized as a managed Delta table that
can be compacted, served through the SQL analytics endpoint, and eventually carry a Direct
Lake semantic model. This pilot adds one, without re-owning the data transform or
disrupting anything already deployed.

> **If you already run FinOps hubs on Fabric RTI**, evaluate the eventhouse's OneLake
> availability feature before adopting this pilot: it mirrors KQL tables into OneLake as
> Delta with no Spark pipeline to operate. The trade-off is that mirrored tables are
> read-only, so you cannot compact or Z-order them — which is exactly what this pilot
> exists to do. See [For roadmap consideration](docs/README.md#for-roadmap-consideration).

## What's different from the storage path

If you already know the storage-based hub and reports, here is what changes:

| | Storage path (Parquet / KQL) | This pilot (Fabric / OneLake) |
|---|---|---|
| **Where cost data lands** | Azure Data Explorer (KQL) or Parquet in storage | Managed Delta table in OneLake |
| **Who owns the data shape** | KQL transform | **Still KQL** — the pilot only *validates* the output against a contract; it does not re-implement normalization in Spark |
| **Small-file ceiling** | Reports slow as monitored spend grows, because many small files can't be compacted | Managed Delta is compacted daily (OPTIMIZE + Z-ORDER), removing the ceiling |
| **How restatements land** | Handled upstream by the hub | Each batch is a full snapshot of the charge months it covers, and those months are **replaced** atomically — never appended |
| **Power BI connection** | Import / DirectQuery over storage | SQL analytics endpoint; **Direct Lake is earned**, gated by a layout precondition plus a measured semantic model, not assumed |
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
   Set `ABFSS_ROOT` to your Lakehouse path first; it has no default.
2. `notebooks/01_ingestion.py` — schema-validated ingestion (Decision 1).
3. `notebooks/02_delta_write.py` — managed Delta write, partitioned by `x_ChargeMonth`,
   replacing the batch's charge months rather than appending (Decision 2).
4. `notebooks/03_compaction.py` — compaction with monitored SLA metrics (Decision 2).
5. `notebooks/04_directlake_precondition.py` — Direct Lake layout precondition (Decision 4).
6. `notebooks/05_promotion.py` — promotion decision.

Before any of that, run the fail-loud preflight in `deploy/manual/` against your
filled-in parameters (`deploy/manual/deploy-parameters.sample.json` is the template).

## Before your first run

Three values have no defaults, on purpose — a wrong default here fails silently:

| What | Where | Why there is no default |
|---|---|---|
| `ABFSS_ROOT` | `notebooks/00_generate_sample_focus.py` | The OneLake host differs by cloud; copy it from Lakehouse **> Properties**. |
| `directLake.maxRows` / `maxFiles` / `minAvgFileSizeMB` | `contracts/storage-layout.contract.json` | Direct Lake limits vary by Fabric capacity SKU. A permissive default would let the layout precondition pass on a capacity that cannot serve the table — the exact silent failure the gate exists to catch. Look up the limits published for your SKU and record them. |
| `sla_overrides` | `notebooks/03_compaction.py` parameters cell | Empty means the contract's production thresholds apply. Only set it for synthetic test data that cannot reach the 64MB floor. |

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
5. **The layout precondition (04) is blocked on small datasets by design.** That is a
   correct, reasoned verdict — tiny test data cannot meet the Direct Lake guardrails.
   The SQL endpoint path still works; Direct Lake is earned over a full billing cycle.

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
| `ContractViolation: average file size below floor` on tiny data | Production SLA thresholds vs. synthetic test data | Set `sla_overrides` in the 03 parameters cell for pilot data; leave it empty for real billing data |
| `GuardrailsNotConfigured` in notebook 04 | `directLake` limits are unset in the storage contract | Expected on a fresh clone — record the limits published for your Fabric capacity SKU |
| `ImplausibleRestatement` in notebook 02 | The batch wrote far fewer rows than it replaced | Usually a truncated source export. Verify the export before overriding `min_restatement_row_ratio` |
| `ActiveFileMismatch` in notebook 03 | Listing paths and Delta-log paths could not be reconciled | Report it — the metrics would otherwise be fabricated. Do not work around it by ignoring the listing |
| Layout precondition blocked on small data | Dataset too small to meet the guardrails | Expected and correct; the SQL endpoint path still works |
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
python -m pytest src/pilots/fabric-onelake
```

These cover the schema/type/non-null contract rules, the column-source integrity pin, the
restatement predicate and shrink guard, the active-file selection that keeps compaction
metrics honest, the compaction SLA logic, and the promotion decisions — the same checks
the notebooks enforce at runtime — so a contract regression is caught without deploying
to Fabric.

One test module needs a real Delta engine and is **skipped unless it is installed**:

```bash
pip install -r src/pilots/fabric-onelake/requirements-dev.txt
python -m pytest src/pilots/fabric-onelake/notebooks/tests/test_restatement_spark.py
```

It proves that re-running a batch does not duplicate cost data and that restating a month
replaces rather than accumulates. That failure mode balanced every per-hop row count, so
only a behavioural test can catch it.

Running it locally needs a JDK 17 and a Python version within PySpark's supported range,
and on Windows also `winutils.exe` with `HADOOP_HOME` set. Rather than ask every
contributor for that, CI runs it on every change to this folder
(`.github/workflows/pilot-fabric-onelake.yml`) — so the module is expected to show as
skipped locally and to actually execute in the pipeline.

## Pilot status and graduation

This is a **pilot**, and the folder name is a lifecycle stage — not a verdict on quality.
It lives under `pilots/` because a few things are true only at pilot scale today, and the
`pilots/` location keeps the promise that it is self-contained and removable while those
prove out. "Pilot" here means *staged with a known graduation path*, not *demo*.

**What "pilot" means right now**

- Contracts, validation, the fail-loud preflight, and the unit tests are production-grade
  and run without a cluster.
- The compaction SLA thresholds in the contract are the **production** values; synthetic
  test data opts into pilot-scale thresholds per run via `sla_overrides`.
- Direct Lake guardrails are **unset by design** — they are per-capacity-SKU and you must
  record your own.
- Direct Lake is gated: notebook 04 evaluates table layout only, so the SQL-endpoint path
  is the supported connection today.

**Graduation criteria — what has to be true to leave `pilots/`**

1. Runs against **real billing data** for at least one full billing cycle, including at
   least one closed-month restatement.
2. The **layout precondition holds** on that real data, and a **Direct Lake semantic model
   is built and measured** — framing, cold-query latency, memory pressure, and observed
   fallback — against the capacity SKU in use.
3. Compaction SLA thresholds hold at production values over that cycle, with no
   `sla_overrides` in effect.
4. Endpoints are proven on at least the commercial and one non-commercial cloud.
5. **Cost effectiveness is measured**, not assumed: Fabric CU consumption for the notebooks
   and SQL endpoint, plus OneLake storage growth, compared against the storage and hubs+RTI
   paths. A materialization path in a FinOps toolkit has to show its own economics.
6. The component is wired into the **build/packaging system** (versioning, tests in CI).

**Where it graduates to**

When those hold, this becomes a first-class **Fabric / OneLake materialization path** for
the toolkit — a peer to the storage and KQL paths, moved out of `pilots/` into the main
`src/` structure and packaged like the other components. Until then, it stays here,
reversible and clearly labeled.
