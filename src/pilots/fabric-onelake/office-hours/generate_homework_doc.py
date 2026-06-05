# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Generate the homework / execution-steps Word document for the Fabric pilot.

Audience: a Fabric-trained engineer who is NEW to the finops-toolkit repo and
needs (a) to determine whether they already have a usable internal Fabric
environment, and (b) concrete steps to validate the pilot. Re-run to regenerate:

    python generate_homework_doc.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor, Inches
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = Path(__file__).resolve().parent / "FinOps-Fabric-Pilot-Homework.docx"

BLUE = RGBColor(0x0F, 0x6C, 0xBD)
GREEN = RGBColor(0x10, 0x7C, 0x10)
INK = RGBColor(0x20, 0x20, 0x20)
GRAY = RGBColor(0x60, 0x60, 0x60)

doc = Document()

# Base style
normal = doc.styles["Normal"]
normal.font.name = "Segoe UI"
normal.font.size = Pt(10.5)
normal.font.color.rgb = INK


def _shade(paragraph, hex_fill):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hex_fill)
    pPr.append(shd)


def title(txt, sub=None):
    p = doc.add_paragraph()
    r = p.add_run(txt)
    r.font.size = Pt(22)
    r.font.bold = True
    r.font.color.rgb = BLUE
    if sub:
        ps = doc.add_paragraph()
        rs = ps.add_run(sub)
        rs.font.size = Pt(11)
        rs.font.color.rgb = GRAY


def h1(txt):
    p = doc.add_paragraph()
    p.space_before = Pt(14)
    r = p.add_run(txt)
    r.font.size = Pt(15)
    r.font.bold = True
    r.font.color.rgb = BLUE


def h2(txt):
    p = doc.add_paragraph()
    r = p.add_run(txt)
    r.font.size = Pt(12)
    r.font.bold = True
    r.font.color.rgb = INK


def body(txt, italic=False):
    p = doc.add_paragraph()
    r = p.add_run(txt)
    r.font.italic = italic
    return p


def bullet(txt, bold_lead=None):
    p = doc.add_paragraph(style="List Bullet")
    if bold_lead:
        rb = p.add_run(bold_lead)
        rb.font.bold = True
    p.add_run(txt)
    return p


def numbered(txt, bold_lead=None):
    p = doc.add_paragraph(style="List Number")
    if bold_lead:
        rb = p.add_run(bold_lead)
        rb.font.bold = True
    p.add_run(txt)
    return p


def code(lines):
    if isinstance(lines, str):
        lines = [lines]
    for ln in lines:
        p = doc.add_paragraph()
        _shade(p, "F2F2F2")
        p.paragraph_format.left_indent = Inches(0.2)
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(ln if ln else " ")
        r.font.name = "Consolas"
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(0x10, 0x3A, 0x5A)
        # ensure east-asian font mapping too
        r._element.rPr.rFonts.set(qn("w:cs"), "Consolas")
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def callout(txt):
    p = doc.add_paragraph()
    _shade(p, "E7F2E7")
    p.paragraph_format.left_indent = Inches(0.1)
    r = p.add_run(txt)
    r.font.size = Pt(10)
    r.font.color.rgb = GREEN
    r.font.bold = True


# ============================================================== Title
title("FinOps Fabric / OneLake pilot — validation homework",
      "How to test the pilot, starting with: do I already have a usable Fabric environment? • 2026-06-05")

body("This guide is written for someone comfortable with Microsoft Fabric but new to the "
     "finops-toolkit repository. Work top to bottom. Part A tells you whether you already have "
     "what you need; Parts B–C need no cloud resources; Parts D–F need a Fabric capacity.")

callout("Bottom line: the 33 Python + 10 Pester unit tests already run green and are sufficient "
        "evidence for an office-hours design discussion. The steps below are only needed to advance "
        "the pilot toward a live proof.")

# ============================================================== Part A
h1("Part A — Do I already have a usable Fabric environment?")
body("You need three things to run the live parts: (1) a Fabric capacity, (2) permission to create "
     "a workspace on it, and (3) the ability to create a Lakehouse. Check them in order; stop as soon "
     "as one fails and note it.")

h2("A1. Quick visual check (2 minutes, no tooling)")
numbered("Open https://app.fabric.microsoft.com and sign in with your work account.", "Fabric portal: ")
numbered("Bottom-left, confirm your account/tenant is the one you expect.")
numbered("Click Workspaces (left rail). If you can click \u201cNew workspace\u201d, you have create rights.")
numbered("In a workspace, click \u201cNew item\u201d and look for \u201cLakehouse\u201d. If present, Lakehouse creation is enabled.")
body("If you see a banner offering a \u201cStart trial\u201d for Fabric, you likely do NOT have a paid "
     "capacity yet — a trial capacity is fine for the pilot's small test.", italic=True)

h2("A2. Is there a paid capacity assigned? (Azure portal)")
numbered("Open https://portal.azure.com and search the top bar for \u201cMicrosoft Fabric\u201d.", "Azure portal: ")
numbered("Open \u201cMicrosoft Fabric\u201d (capacities). Any row listed is an F-SKU capacity you may be able to use.")
numbered("Note the capacity name and its resource group; you'll use the resource id later as capacityId.")

h2("A3. Programmatic check (PowerShell — definitive)")
body("This confirms capacity AND that your token works against the Fabric REST API the pilot uses.")
code([
    "# One-time: install the Az modules if you don't have them",
    "Install-Module Az.Accounts, Az.Resources -Scope CurrentUser -Force",
    "",
    "Connect-AzAccount    # sign in (use -Tenant <id> if you have multiple tenants)",
    "",
    "# 1) List any Fabric capacities you can see in Azure",
    "Get-AzResource -ResourceType 'Microsoft.Fabric/capacities' |",
    "    Select-Object Name, ResourceGroupName, Location, Sku",
    "",
    "# 2) Get a Fabric API token and list workspaces + capacities you can reach",
    "$token = (Get-AzAccessToken -ResourceUrl 'https://api.fabric.microsoft.com').Token",
    "$h = @{ Authorization = \"Bearer $token\" }",
    "Invoke-RestMethod -Uri 'https://api.fabric.microsoft.com/v1/capacities' -Headers $h |",
    "    Select-Object -ExpandProperty value | Format-Table displayName, sku, state",
    "Invoke-RestMethod -Uri 'https://api.fabric.microsoft.com/v1/workspaces' -Headers $h |",
    "    Select-Object -ExpandProperty value | Format-Table displayName, id",
])
body("Interpreting the results:")
bullet("a capacity with state = Active under your account — you can run the live parts.", "If you see ")
bullet("workspaces but no capacity — ask the team to assign one, or start a Fabric trial.", "If you see ")
bullet("a 401/403 on the REST calls — your account can't reach the Fabric API; that's a permissions ask for the team.", "If you get ")

h2("A4. Environment readiness checklist")
for item in [
    "Can sign in to app.fabric.microsoft.com",
    "Can create a workspace (or have one I can use)",
    "Can create a Lakehouse in that workspace",
    "A Fabric capacity (paid F-SKU or trial) is assigned to the workspace",
    "Get-AzAccessToken for https://api.fabric.microsoft.com succeeds",
    "I noted the capacity resource id (for capacityId)",
]:
    p = doc.add_paragraph(style="List Bullet")
    p.add_run("\u2610  " + item)
callout("If every box is checked, skip to Part D for the live run. If not, Parts B–C still work today "
        "with zero cloud resources and are worth doing before office hours.")

# ============================================================== Part B
h1("Part B — Get oriented in the repo (no cloud needed)")
body("The repo is new to you, so this part just gets the code and runs the tests locally. "
     "Everything for the pilot is under src/pilots/fabric-onelake/.")

h2("B1. Get the branch")
code([
    "git clone https://github.com/microsoft/finops-toolkit.git   # or your fork",
    "cd finops-toolkit",
    "git fetch origin",
    "git switch pilot/fabric-onelake   # or your fork's branch",
])

h2("B2. What's in the pilot folder")
bullet("the two machine-readable contracts (schema + storage layout).", "contracts/ — ")
bullet("the fail-loud validator + its tests (pure Python, no Spark).", "validation/ — ")
bullet("the five Fabric notebooks (01 validate \u2192 05 promotion) and a tested helper library.", "notebooks/ — ")
bullet("the manual setup runbook + preflight, the REST provisioner, and the ADF\u2192Fabric Bicep.", "deploy/ — ")
bullet("the SQL-endpoint Power BI connection swap.", "power-bi/ — ")
bullet("this document, the deck, and the PR notes.", "office-hours/ + PR-NOTES.md — ")

# ============================================================== Part C
h1("Part C — Validate the logic locally (no Fabric capacity)")
body("These reproduce the evidence cited at office hours. They should all pass on any machine with "
     "Python, PowerShell 7, Pester 5, and the Azure CLI/Bicep.")

h2("C1. Run the Python unit tests")
code([
    "python src/pilots/fabric-onelake/validation/test_contract_validator.py",
    "python src/pilots/fabric-onelake/notebooks/tests/test_focus_pilot.py",
    "python src/pilots/fabric-onelake/notebooks/tests/test_promotion.py",
])
body("Expected: \u201c10/10 passed\u201d, \u201c14/14 passed\u201d, \u201c9/9 passed\u201d.")

h2("C2. Run the PowerShell (Pester) tests")
code([
    "Install-Module Pester -MinimumVersion 5.0.0 -Scope CurrentUser -Force  # once",
    "Import-Module Pester -MinimumVersion 5.0.0 -Force",
    "Invoke-Pester -Path src/pilots/fabric-onelake/deploy/manual/Test-PilotDeployment.Tests.ps1 -Output Detailed",
])
body("Expected: Tests Passed: 10, Failed: 0.")

h2("C3. Compile the orchestration Bicep")
code([
    "az bicep build --file src/pilots/fabric-onelake/deploy/orchestration/notebook-activity.bicep --stdout",
])
body("Expected: exits 0 with no warnings.")

h2("C4. Dry-run the deployment surface (still no capacity)")
body("The manual runbook prints the portal steps and validates a parameters file; the provisioner "
     "shows its plan with -WhatIf.")
code([
    "cd src/pilots/fabric-onelake/deploy/manual",
    ". ./Invoke-PilotManualSetup.ps1",
    "Invoke-PilotManualSetup -ParametersPath ./deploy-parameters.sample.json",
    "",
    "cd ../automation",
    ". ./Initialize-PilotFabric.ps1",
    "Initialize-PilotFabric -WorkspaceName 'FinOps Pilot' -LakehouseName 'FinOpsHub' `",
    "    -AccessToken 'dummy' -WhatIf",
])
callout("If Parts C1–C4 pass, you have independently reproduced the office-hours evidence.")

# ============================================================== Part D
h1("Part D — One small live end-to-end run (needs a capacity)")
body("This is the real validation: prove the code runs against an actual Fabric Lakehouse. "
     "Use a SMALL slice of FOCUS data (e.g., one month, one subscription).")

numbered("In Fabric, create a workspace on your capacity, then create a Lakehouse (note the name).",
         "Provision: ")
numbered("Open the Lakehouse > Properties, copy the ABFSS OneLake path. Open the SQL analytics endpoint "
         "> Settings, copy the connection host.", "Collect endpoints: ")
numbered("Copy deploy/manual/deploy-parameters.sample.json, fill in your real workspaceName, lakehouseName, "
         "oneLakeEndpoint, and sqlEndpoint.", "Fill parameters: ")
numbered("Run the preflight — it must pass before you proceed:", "Preflight: ")
code([
    ". ./src/pilots/fabric-onelake/deploy/manual/Test-PilotDeployment.ps1",
    "Test-PilotDeployment -ParametersPath ./my-deployment.json -Verbose",
])
numbered("Upload the pilot folder to the Lakehouse Files area (or use the REST provisioner), import the "
         "five notebooks, and set each notebook's _PILOT_ROOT to where you uploaded it.", "Load notebooks: ")
numbered("Run notebooks in order against your small slice: 01 ingestion \u2192 02 delta write \u2192 "
         "03 compaction \u2192 04 readiness.", "Execute: ")

h2("D1. What success looks like")
bullet("01 reports the row count and prints no schema/version/null violation (it would throw if it did).")
bullet("02 creates a managed Delta table named Costs, partitioned by x_ChargeMonth.")
bullet("03 reduces file count, and writes a row to _pilot_compaction_metrics; the SLA check passes.")
bullet("04 prints a clear GO or NO-GO and appends to _pilot_directlake_gate.")
body("If 04 says NO-GO on a tiny dataset, that is expected and correct — small test data won't meet the "
     "DirectLake guardrails. The point is that the gate returns a clear, reasoned verdict.", italic=True)

h2("D2. Point Power BI at it")
numbered("Open one existing report (e.g. CostSummary) and replace the source query with "
         "ftk_FabricSql(\"focuscost\"); add the SQL Endpoint / SQL Database parameters from "
         "expressions.fabric.tmdl.", "Connection swap: ")
numbered("Refresh and confirm the existing visuals render against the SQL endpoint. No visual should need "
         "rebuilding — it's a source swap.", "Verify: ")

# ============================================================== Part E
h1("Part E — Prove the headline claim (the $2–5M ceiling)")
body("This is the evidence that the pilot solves the stated problem, and the most persuasive thing to "
     "bring back to the team.")
numbered("Load a dataset comparable to the $2–5M/month case into BOTH the existing storage path and the "
         "new Delta + SQL-endpoint path.")
numbered("Run the same handful of report queries against each and capture response times.")
numbered("Record a simple before/after table. Expect the Delta path (compacted) to hold up where the "
         "small-file storage path degrades.")
callout("Keep this measurement simple and reproducible — a few representative queries, timed, is more "
        "convincing than a synthetic benchmark.")

# ============================================================== Part F
h1("Part F — Confirm the provisional Z-order (Phase 6)")
body("The pilot ships with a provisional Z-order of BillingAccountId + SubscriptionId. After a real "
     "workload exists, confirm or revise it.")
numbered("Collect how often each column is used as a query filter (column name \u2192 count) and load it "
         "into a _pilot_query_filter_stats table.")
numbered("Run notebook 05_promotion. It recommends keeping or changing the Z-order and only authorizes "
         "DirectLake after a full billing cycle of healthy gate results.")
numbered("If it recommends a change, edit zorder.columns in storage-layout.contract.json and re-run "
         "notebook 03 (OPTIMIZE is non-destructive).")

# ============================================================== Decision summary
h1("Quick decision guide")
table = doc.add_table(rows=1, cols=2)
table.style = "Light Grid Accent 1"
hdr = table.rows[0].cells
hdr[0].paragraphs[0].add_run("Your situation").bold = True
hdr[1].paragraphs[0].add_run("Do this").bold = True
rows = [
    ("No Fabric capacity yet", "Do Parts B–C now (no cloud needed). Ask the team for a capacity or trial. Bring the green test results to office hours."),
    ("Have a trial/capacity", "Do Parts B–C, then a small Part D live run before office hours if time allows."),
    ("Just need talking points", "Parts C1–C3 give you reproducible evidence in ~10 minutes."),
    ("Want to make the business case", "Do Part E — the before/after query-time comparison."),
]
for a, b in rows:
    cells = table.add_row().cells
    cells[0].paragraphs[0].add_run(a)
    cells[1].paragraphs[0].add_run(b)

doc.add_paragraph()
foot = doc.add_paragraph()
fr = foot.add_run("Reference: see PR-NOTES.md (same folder) for the plain-language summary and the draft PR description.")
fr.font.size = Pt(9)
fr.font.italic = True
fr.font.color.rgb = GRAY

doc.save(OUT)
print(f"Saved {OUT}")
