# Deploy the FinOps Fabric / OneLake pilot

These are instructions for a **future, separately authorized manual validation**.
The current experiment authorizes local implementation only, with zero authorized
cloud spend and no deployment permission. Manual capacity validation is mandatory
before technical PR-readiness but has not been established here. A trial or an
existing capacity still needs explicit access, usage, owner, and cleanup approval.

| Folder | Scope and evidence boundary |
| --- | --- |
| `manual/` | Setup helpers and parameter/preflight checks; not proof of live connectivity or deployment. |
| `automation/` | Optional Fabric REST get-or-create provisioner; live idempotency and tenant behavior remain unvalidated. |
| `orchestration/` | Optional ADF runner for one notebook ID; not a complete 01–04 chain, schedule, or core hub integration. Live execution remains unvalidated. |

**Manual-only** is the selected validation scope. Optional live provisioning and ADF
validation are not selected. Applicable existing Pester/Bicep checks still apply to
retained artifacts, including unchanged ones; static/mocked tests are not live evidence.

### Local validation prerequisites

Use PowerShell with Pester and a Bicep compiler available on `PATH` before running
`Invoke-Pester -Path .\src\pilots\fabric-onelake\deploy -Output Detailed` from the
repository root. The orchestration tests also accept `BICEP_CLI_PATH` as an absolute
compiler path. Set the compiler prerequisite in the same process as the test run;
an installed compiler outside `PATH` is not automatically discoverable.
The reported validation toolchain is PowerShell 7.6.6, Pester 5.8.0, and Bicep 0.47.16.
Compilation and mocked tests validate local artifacts, not live Fabric/ADF API behavior.

## Manual setup after authorization

1. Record the tested revision, approved capacity/SKU and supported runtime, owners,
   budget, execution window, and cleanup scope. Use isolated non-production resources;
   do not alter existing RTI resources or shared capacity configuration.
2. Create a workspace on that capacity and a Lakehouse. Copy actual OneLake ABFSS and
   SQL endpoint values from Lakehouse properties/settings; record names and IDs.
3. Copy and fill in `manual/deploy-parameters.sample.json`. Commercial values are
   defaults, not evidence of support in every tenant. The `msit` and sovereign samples
   are **untested configuration examples**; sovereign hosts are placeholders and
   require current service availability and endpoint validation. Do not infer support
   merely because a host matches a regex.
4. Run `Test-PilotDeployment` from `manual/Test-PilotDeployment.ps1` with
   `-ParametersPath` pointing at the filled-in file. Resolve explicit failures before
   continuing. The current private-networking rejection is a pilot limitation, not
   a statement that Fabric has no private networking capabilities.
5. Upload `notebooks/`, `contracts/`, and `validation/` to Lakehouse **Files**. Separately
   import optional 00 and functional notebooks 01–04 as workspace Notebook items.
   Uploading source files alone does not make them runnable. Attach and set the
   default Lakehouse in every notebook. See [notebook setup](../README.md#running-the-notebooks-in-fabric).
6. Set actual notebook parameters and diagnostic thresholds. Record inherited/explicit
   runtime/table settings, unknowns, provisional layout choices and test overrides.
   Do not treat a size tuning threshold as a universal platform guardrail.
   If using 00, set `ABFSS_ROOT` and `numeric_variant`; `OUTPUT_PATH` defaults to
   `Files/sample-focus` and receives `-decimal` or `-double`. Point 01 at the generated
   Parquet path. Use decimal for accepted input and double as a deliberate rejection
   test. Retain the independent exact-tolerance-zero producer expectations at
   `source_path + "_producer_expected"`; see [generator details](../README.md#synthetic-generator-parameters-and-expected-results).
7. Complete the [pre-write acceptance procedure](../README.md#input-acceptance-and-coexistence-boundary):
   record independent complete month/scope evidence and batch ordering; refuse stale,
   missing/ambiguous or intentional zero-row replacements; serialize all manual and
   orchestrated writers. A report-filtered small slice is not a safe full-month batch.
   Set notebook 02's required nonempty `acceptance_record_id` alongside `ingestion_id`
   and endpoint parameters. It references the independent coverage/order/all-entry-point
   exclusive-writer decision. The notebook prints the reference but neither verifies
   the record nor adds a ledger field; retain durable acceptance evidence separately.
   A nonempty reference is not an automated completeness check or lock.
8. Run optional 00, then 01 → 02 → 03 → 04 with accepted complete synthetic snapshots.
   A passing 04 means only listed checks passed; it is not Direct Lake authorization.
9. Complete the [mandatory synthetic validation](../README.md#required-validation-and-evidence),
   including replay/corrections, negative cases, SQL synchronization/reconciliation,
   representative Import report refresh/visual checks and rollback. Keep independent
   expected results and sanitized evidence tied to the exact tested revision.
10. Remove only explicitly owned test resources, or record the continuing owner and
    retention decision. Do not delete shared capacity, RTI data, or old operational
    tables as cleanup.

## Optional automation is not a proven fallback

`Initialize-PilotFabric` offers `-WhatIf` and get-or-create logic. A dry run previews
intended actions and may perform reads; it does **not** establish provisioning,
write permissions, full connectivity, or successful job execution. Before claiming
live validation, separately authorize and verify reruns preserve workspace/Lakehouse
identities and output meaning.

Manual workspace/Lakehouse creation bypasses the provisioner, **not** the Fabric API
access needed by the ADF runner. If that API is blocked, this folder does not provide
an automated workaround. Live ADF evidence would need identity/permissions, parameter
transfer, 202/Location handling versus Web Activity's default asynchronous behavior,
job lifecycle, bounded timeout, failure/cancellation, and safe retry checks. Distinguish
pipeline cancellation from remote-job cancellation and record cleanup of running jobs.
A single notebook success
does not establish an operational chain.

Daily scheduling for 03, any diagnostic cadence for 04, alerts and recovery are
operator-owned and **unprovisioned**. The retained 26-hour check means one daily
interval plus two hours lateness; a threshold does not create a schedule.
Do not schedule the retired notebook 05. Preserve legacy operational data without
treating it as automatically trustworthy historical evidence.
