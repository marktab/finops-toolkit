# Deploy the FinOps Fabric / OneLake pilot

This folder contains everything needed to stand up the pilot, in the order the toolkit
recommends: prove the **manual** path first, then optionally layer the **automation** on
top of it. This mirrors the "Create a new hub" flow in the FinOps hubs documentation.

- `manual/` — the proven-first manual setup and the fail-loud preflight (`Test-PilotDeployment`).
- `automation/` — idempotent Fabric REST provisioning (`Initialize-PilotFabric`) over the manual path.
- `orchestration/` — the Azure Data Factory → Fabric notebook handoff (Bicep).

## Create a pilot

Follow these steps to go from nothing to a validated end-to-end run:

1. **Create or choose a Microsoft Fabric capacity** in a non-production tenant. A Fabric
   trial capacity is sufficient for validation.
2. **Create a workspace** on that capacity, then **create a Lakehouse** in it. Note the
   workspace and Lakehouse names.
3. **Collect endpoints.** From the Lakehouse **> Properties**, copy the ABFSS OneLake
   path; from the Lakehouse **> SQL analytics endpoint > Settings**, copy the connection
   host. See the [endpoints-by-cloud table](../README.md#endpoints-by-cloud) for the
   commercial, msit, and sovereign host forms.
4. **Fill in parameters.** Copy the sample that matches your cloud from `manual/`:
   - `deploy-parameters.sample.json` — commercial (default)
   - `deploy-parameters.msit.sample.json` — Microsoft-internal (msit)
   - `deploy-parameters.sovereign.sample.json` — sovereign (placeholders to replace)
5. **Run the preflight (fail-loud gate).** It must pass before you proceed:

   ```powershell
   . ./manual/Test-PilotDeployment.ps1
   Test-PilotDeployment -ParametersPath ./my-deployment.json -Verbose
   ```

6. **Upload and import the notebooks.** Upload `notebooks/`, `contracts/`, and
   `validation/` to the Lakehouse **Files** area, then import each `.py` as a Notebook
   item. See [Running the notebooks in Fabric](../README.md#running-the-notebooks-in-fabric).
7. **Run the notebooks in order** (`00` → `01` → `02` → `03` → `04`) against a small slice
   of FOCUS data.
8. **Interpret the DirectLake gate** from `04`, then **swap the Power BI connection** to
   the SQL endpoint. See [power-bi/README.md](../power-bi/README.md).

## Step 0: dry-run the automation first (recommended)

If you plan to use the automated provisioning, run it with `-WhatIf` before anything is
created. This confirms your parameters and connectivity without making changes:

```powershell
. ./automation/Initialize-PilotFabric.ps1
Initialize-PilotFabric -WorkspaceName '<workspace>' -LakehouseName '<lakehouse>' `
    -AccessToken (Get-AzAccessToken -ResourceUrl 'https://api.fabric.microsoft.com').Token `
    -WhatIf
```

For a non-commercial cloud, add `-AzureEnvironment` and, for sovereign clouds, the
`-OneLakeHost` / `-ApiBaseUrl` overrides (the sovereign lookup-map entries are
placeholders that fail loudly until you supply them). See the automation script's
comment-based help for details.
