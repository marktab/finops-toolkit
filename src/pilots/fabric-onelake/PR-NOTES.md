# FinOps Fabric/OneLake pilot — PR description & office-hours prep

> Working notes for discussing the `pilot/fabric-onelake` extension at FinOps toolkit
> office hours. Not a committed doc — delete or relocate before any real PR.

---

## 1. Plain-language summary (what changed and how it works)

**The problem.** Today a FinOps hub lands cost data either in Azure Data Explorer
(KQL) or in storage as Parquet. The Parquet/Power BI path hits a wall around
$2–5M/month of spend because the data is split across many small files that can't
be compacted, so reports slow down. There's no Microsoft Fabric/OneLake path that
removes that ceiling.

**What this pilot adds.** An optional, self-contained pilot under
`src/pilots/fabric-onelake/` that takes the *already-normalized* FOCUS cost data and
materializes it as a managed Delta table in OneLake, so it can be compacted and
served fast to Power BI. Nothing in the existing toolkit changes — this lives beside
it and can be removed without impact.

**The four design choices, in basic terms:**

1. **KQL still owns the data shape.** We did *not* rewrite the cost-normalization
   logic in Spark. The pilot reads the FOCUS data the toolkit already produces and
   only *checks* it against a contract. This avoids maintaining the same complex
   logic in two languages as FOCUS evolves from 1.0 to 1.2.

2. **Real Delta tables, not shortcuts.** Shortcuts would inherit the same small-file
   problem. Managed Delta tables can be compacted daily and reorganized, which is
   what actually removes the cost ceiling.

3. **Keep Azure Data Factory as the orchestrator; have it call a Fabric notebook.**
   ADF deploys via Bicep/ARM and works in locked-down/air-gapped tenants where Fabric
   pipelines can't be deployed that way. We add one new step where ADF hands off to a
   Fabric Spark notebook and waits for it. We built and tested the *manual* setup path
   first, so the automation is a convenience on top of something that already works.

4. **Power BI connects to the SQL endpoint first; DirectLake is earned, not promised.**
   DirectLake can silently fall back to a 10–50× slower mode with no error. So Power BI
   starts on the plain SQL endpoint (works immediately, any license), and a separate
   check has to pass — over a full billing cycle — before anyone flips on DirectLake.

**The one principle behind all of it:** every one of those "if this breaks" cases is a
*silent* failure. So each contract is enforced by code that **stops loudly** when
reality drifts, instead of being written down in a doc that nobody re-checks.

**What's actually in the folder:**

- `contracts/` — two machine-readable contracts (the expected data schema, and the
  physical Delta/compaction layout) that the code loads and enforces.
- `validation/` + `notebooks/lib/` — small, tested Python helpers (no Spark needed to
  run the tests).
- `notebooks/01..05` — Fabric notebooks: validate → write Delta → compact (with
  metrics) → DirectLake readiness gate → promotion decision.
- `deploy/manual/` — the proven-first manual setup + a fail-loud preflight check.
- `deploy/automation/` — idempotent Fabric REST provisioning (get-or-create).
- `deploy/orchestration/` — the ADF→Fabric notebook handoff (Bicep).
- `power-bi/` — the SQL-endpoint report variant as a one-line source swap.

---

## 2. Filled-in PR template (draft)

### 🛠️ Description

Adds an **optional, isolated Microsoft Fabric / OneLake pilot** under
`src/pilots/fabric-onelake/` that materializes already-normalized FOCUS cost data as a
**managed Delta table in OneLake** to remove the ~$2–5M/month small-file query ceiling
on the storage-based Power BI path.

The pilot is additive and self-contained — no existing hub, template, or report is
modified. It is organized so it can later merge into a namespace module if accepted.

Design decisions (each enforced by tested, fail-loud code, not documentation):

- **Schema ownership stays in KQL.** The pilot validates FOCUS output against a
  machine-readable contract that *references* the existing
  `src/open-data/dataset-metadata/FocusCost_1.2-preview.json` rather than duplicating it.
- **Managed Delta + monitored compaction SLA** (not OneLake shortcuts), with
  before/after file metrics emitted for alerting.
- **Hybrid orchestration:** ADF stays the orchestrator and calls a Fabric Spark
  notebook via the Fabric REST API; manual deployment path built and proven first, with
  an idempotent REST provisioner layered on top.
- **Power BI on the SQL endpoint first;** a readiness gate plus a full-billing-cycle
  promotion check are the only things that authorize a DirectLake upgrade.

Fixes # _(none — exploratory pilot; no linked issue)_

### 📷 Screenshots

N/A — no UI changes. (For office hours: can demo the passing test runs and the
`Invoke-PilotManualSetup` runbook output.)

### 📋 Checklist

#### 🔬 How did you test this change?

- [x] 💪 Unit tests — 33 Python (contract validator, library, promotion/Z-order) +
      10 Pester (deployment preflight); all passing.
- [x] 🤞 PS -WhatIf / az validate — Bicep module compiles clean (`az bicep build`);
      provisioning script supports `-WhatIf` via `ShouldProcess`.
- [ ] 🤏 Lint tests — _not yet run through the repo's PSScriptAnalyzer/Bicep lint task._
- [ ] 👍 Manually deployed + verified — _not yet; needs a live Fabric capacity._
- [ ] 🙌 Integration tests — _not yet; needs a live tenant + billing cycle._

#### 📦 Deploy to test?

- [ ] Hubs + ADX (managed)
- [ ] Hubs + Fabric (manual) — URI: _pending live capacity_
- [ ] Hubs (manual)
- [ ] Hubs (no data)
- [ ] Workbooks
- [ ] Alerts

_(None deployed live yet — see homework below.)_

#### 🙋‍♀️ Do any of the following apply?

- [ ] 🚨 This is a breaking change. — **No.** Purely additive; no existing files changed.
- [ ] 🤏 The change is less than 20 lines of code. — No.

#### 📑 Did you update `docs/changelog.md`?

- [x] ➡️ Will add log in a future PR (feature branch PRs only).

#### 📖 Did you update documentation?

- [x] ➡️ Will add docs in a future PR (feature branch PRs only).

---

## 3. Technical-validation homework

### Are the tests I ran sufficient evidence *for now*?

**For an office-hours design discussion: yes.** They prove the *logic* is correct and
the contracts are enforced:

- 33 Python unit tests — schema/null/version enforcement, compaction-SLA math,
  DirectLake readiness conditions, promotion + Z-order logic.
- 10 Pester tests — deployment-parameter validation and the fail-loud preflight.
- `az bicep build` — the ADF→Fabric pipeline compiles.

What they intentionally do **not** prove yet (and shouldn't, without live resources):
the code actually runs against a real Fabric Lakehouse end-to-end.

### Homework, only if/when the team wants to advance past "interesting idea"

Ordered cheapest-first; none required before the office-hours conversation.

1. **Repo lint parity (cheap, do before a real PR).** Run the toolkit's own lint task
   over the pilot so it matches house style:
   - `pwsh -Command ./src/scripts/Test-PowerShell -Lint`
   - confirm `az bicep build` is clean (already is).

2. **Dry-run the deployment surface without a tenant.**
   - `Initialize-PilotFabric ... -WhatIf` to show the get-or-create plan.
   - `Invoke-PilotManualSetup -ParametersPath <sample>` to show the runbook + preflight.

3. **One small live end-to-end run (needs a Fabric capacity — the real validation).**
   - Manually create a workspace + Lakehouse; fill in the parameters file; run the
     preflight; run notebooks 01→04 over a *small* slice of FOCUS data.
   - Confirm: schema validation passes, a managed Delta `Costs` table appears,
     compaction reduces file count and writes a metrics row, and the readiness gate
     returns a clear go/no-go.
   - Point the SQL-endpoint Power BI variant at it and confirm visuals render.

4. **Cost-ceiling proof point (the headline claim).** Load a dataset comparable to the
   $2–5M/month case on both the storage path and the Delta+SQL path and capture a
   before/after query-time comparison. This is the evidence that the pilot solves the
   stated problem.

5. **Z-order confirmation (Phase 6).** Collect real query-filter frequencies and run
   notebook 05 to confirm or revise the provisional Z-order columns
   (`BillingAccountId`, `SubscriptionId`).

### Open questions worth raising at office hours

- Is `src/pilots/` an acceptable home for exploratory work, or do they prefer a
  specific namespace (e.g. a `Microsoft.Fabric` module) from the start?
- Does the team already have a sanctioned Fabric test capacity a pilot could use?
- Is the "KQL stays the single transform owner" stance aligned with their Fabric
  roadmap, or are they planning a Spark-native transform path that would change D1?
- Would they want the schema contract's `columnSource` to point at the open-data file
  (as built) or at a future published schema artifact?
