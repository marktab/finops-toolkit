# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.
"""Generate the superseding FinOps Fabric/OneLake decisions deck.

Supersedes the original FinOps-Fabric-Decisions.pptx: the four decisions are now
ratified AND implemented on the pilot/fabric-onelake branch. Re-run to regenerate:

    python generate_deck.py
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent / "FinOps-Fabric-Decisions-v2.pptx"

# Palette
INK = RGBColor(0x1F, 0x1F, 0x1F)
BLUE = RGBColor(0x0F, 0x6C, 0xBD)
GREEN = RGBColor(0x10, 0x7C, 0x10)
GRAY = RGBColor(0x60, 0x60, 0x60)
LIGHT = RGBColor(0xF2, 0xF6, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
SW, SH = prs.slide_width, prs.slide_height


def _set(frame, size, bold=False, color=INK, align=PP_ALIGN.LEFT, italic=False):
    for p in frame.paragraphs:
        p.alignment = align
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.italic = italic
            r.font.color.rgb = color
            r.font.name = "Segoe UI"


def box(slide, l, t, w, h, fill=None, line=None):
    shp = slide.shapes.add_shape(1, l, t, w, h)  # rectangle
    shp.shadow.inherit = False
    if fill is None:
        shp.fill.background()
    else:
        shp.fill.solid()
        shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    return shp


def text(slide, l, t, w, h, lines, size=18, bold=False, color=INK,
         align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, space=6):
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    if isinstance(lines, str):
        lines = [lines]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = ln
        p.alignment = align
        p.space_after = Pt(space)
        for r in p.runs:
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            r.font.name = "Segoe UI"
    return tb


def bullets(slide, l, t, w, h, items, size=16, color=INK, space=8):
    tb = slide.shapes.add_textbox(l, t, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, (txt, lvl) in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = lvl
        p.text = ("• " if lvl == 0 else "– ") + txt
        p.space_after = Pt(space)
        for r in p.runs:
            r.font.size = Pt(size - lvl * 2)
            r.font.color.rgb = color
            r.font.name = "Segoe UI"
    return tb


def header(slide, kicker, title):
    box(slide, 0, 0, SW, Inches(1.15), fill=BLUE)
    text(slide, Inches(0.6), Inches(0.12), Inches(12), Inches(0.4),
         kicker, size=13, bold=True, color=RGBColor(0xCF, 0xE4, 0xF7))
    text(slide, Inches(0.6), Inches(0.42), Inches(12), Inches(0.6),
         title, size=26, bold=True, color=WHITE)


# ---------------------------------------------------------------- Slide 1 title
s = prs.slides.add_slide(BLANK)
box(s, 0, 0, SW, SH, fill=BLUE)
box(s, 0, Inches(4.7), SW, Inches(2.8), fill=RGBColor(0x0B, 0x53, 0x94))
text(s, Inches(0.8), Inches(1.5), Inches(11.7), Inches(1.2),
     "FinOps Hubs on Microsoft Fabric / OneLake", size=40, bold=True, color=WHITE)
text(s, Inches(0.8), Inches(2.7), Inches(11.7), Inches(0.8),
     "Four architectural decisions — ratified and implemented", size=22, color=RGBColor(0xCF, 0xE4, 0xF7))
text(s, Inches(0.8), Inches(5.0), Inches(11.7), Inches(1.6),
     ["Supersedes: FinOps-Fabric-Decisions.pptx",
      "Status: pilot built on branch pilot/fabric-onelake — additive, no existing files changed",
      "Evidence: 33 Python + 10 Pester unit tests passing; Bicep compiles clean",
      "For discussion at FinOps toolkit office hours • 2026-06-05"],
     size=15, color=WHITE, space=8)

# ---------------------------------------------------------------- Slide 2 problem
s = prs.slides.add_slide(BLANK)
header(s, "WHY", "The problem this pilot solves")
text(s, Inches(0.6), Inches(1.5), Inches(12), Inches(0.8),
     "The storage-based Power BI path slows down past ~$2–5M/month of spend.",
     size=20, bold=True, color=INK)
bullets(s, Inches(0.6), Inches(2.4), Inches(12), Inches(3.6), [
    ("Cost data lands as many small Parquet files that cannot be compacted or reorganized.", 0),
    ("Query performance degrades as volume grows — the small-file problem.", 0),
    ("There is no Microsoft Fabric / OneLake path that removes that ceiling today.", 0),
    ("Goal: materialize the already-normalized FOCUS data as a managed Delta table in OneLake,", 0),
    ("so it can be compacted daily and served fast to Power BI — without rewriting the toolkit.", 1),
], size=18)
box(s, Inches(0.6), Inches(6.1), Inches(12.1), Inches(0.9), fill=LIGHT)
text(s, Inches(0.8), Inches(6.25), Inches(11.7), Inches(0.6),
     "Governing principle: every \u201cif this breaks\u201d case is a SILENT failure — so each contract is enforced by code that stops loudly, never asserted in a doc.",
     size=15, bold=True, color=BLUE, anchor=MSO_ANCHOR.MIDDLE)

# ---------------------------------------------------------------- Slide 3 overview
s = prs.slides.add_slide(BLANK)
header(s, "AT A GLANCE", "The four decisions")
cards = [
    ("1  Schema ownership", "KQL stays the single transform owner. The pilot validates FOCUS output against a contract — it does not re-implement normalization in Spark.", GREEN),
    ("2  Data into OneLake", "Managed Delta tables, not shortcuts. Only managed Delta can be compacted + Z-ordered to remove the cost ceiling.", GREEN),
    ("3  Orchestration", "Keep ADF (deploys via Bicep/ARM, works in locked-down tenants); it calls a Fabric notebook. Manual path proven first.", GREEN),
    ("4  Power BI", "SQL endpoint first; DirectLake is gated behind measurable checks over a full billing cycle — earned, not promised.", GREEN),
]
x0, y0, cw, ch, gap = Inches(0.6), Inches(1.5), Inches(6.0), Inches(2.5), Inches(0.3)
for i, (title, body, accent) in enumerate(cards):
    col, row = i % 2, i // 2
    l = x0 + col * (cw + gap)
    t = y0 + row * (ch + gap)
    box(s, l, t, cw, ch, fill=LIGHT, line=RGBColor(0xD0, 0xD7, 0xDE))
    box(s, l, t, Inches(0.12), ch, fill=accent)
    text(s, l + Inches(0.35), t + Inches(0.2), cw - Inches(0.6), Inches(0.5),
         title, size=18, bold=True, color=BLUE)
    text(s, l + Inches(0.35), t + Inches(0.85), cw - Inches(0.6), Inches(1.5),
         body, size=14, color=INK)

# ------------------------------------------------- Slides 4-7: one per decision
decision_slides = [
    ("DECISION 1", "Schema ownership — KQL stays the transform owner",
     [("Why", "FOCUS is still moving from 1.0 to 1.2. Re-implementing normalization in Spark would mean maintaining the same logic in two languages — guaranteed drift.", 0),
      ("How it works", "The pilot reads the FOCUS data the toolkit already produces and only CHECKS it.", 0),
      ("", "The schema contract references the existing open-data metadata file rather than copying columns (copying would create the drift it avoids).", 1),
      ("", "Notebook 01 fails the run on FOCUS-version drift, missing required columns, wrong types, or nulls in non-nullable columns.", 1)],
     "Enforced by: focus-schema.contract.json + contract_validator.py (10 tests)"),
    ("DECISION 2", "Data into OneLake — managed Delta, not shortcuts",
     [("Why", "Shortcuts inherit the same small-file problem and can't be compacted or Z-ordered — they don't remove the ceiling.", 0),
      ("How it works", "Notebook 02 writes a managed Delta table partitioned by charge-month; notebook 03 compacts daily.", 0),
      ("", "Compaction is treated as a MONITORED SLA: it emits before/after file counts and sizes for alerting.", 1),
      ("", "A stale or fragmented table fails loudly instead of silently slowing queries.", 1)],
     "Enforced by: storage-layout.contract.json + compaction SLA checks"),
    ("DECISION 3", "Orchestration — ADF stays, calls a Fabric notebook",
     [("Why", "ADF deploys via Bicep/ARM and runs in restricted / air-gapped tenants where Fabric pipelines cannot. Replacing it would exclude the tenants that care most.", 0),
      ("How it works", "A new ADF pipeline hands off to a Fabric Spark notebook via the Fabric REST API and waits, failing loudly on any non-success.", 0),
      ("", "The MANUAL setup path was built and tested first; the REST provisioner is an idempotent convenience on top of a known-good path.", 1)],
     "Enforced by: notebook-activity.bicep (compiles) + Initialize-PilotFabric.ps1 (-WhatIf)"),
    ("DECISION 4", "Power BI — SQL endpoint first, DirectLake earned",
     [("Why", "DirectLake can silently fall back to DirectQuery (10–50× slower, no error) — discovered by end users in production.", 0),
      ("How it works", "Power BI starts on the plain SQL endpoint: immediate value, any license, layout-insensitive.", 0),
      ("", "It is a one-line source swap — every existing visual, measure, and relationship is reused verbatim.", 1),
      ("", "A readiness gate + a full-billing-cycle promotion check are the ONLY things that authorize DirectLake.", 1)],
     "Enforced by: readiness gate (notebook 04) + promotion check (notebook 05)"),
]
for kicker, title, items, footer in decision_slides:
    s = prs.slides.add_slide(BLANK)
    header(s, kicker, title)
    y = Inches(1.55)
    for label, body, lvl in items:
        if lvl == 0:
            text(s, Inches(0.6), y, Inches(2.2), Inches(0.5), label, size=16, bold=True, color=BLUE)
            text(s, Inches(2.9), y, Inches(9.8), Inches(0.9), body, size=16, color=INK)
            y += Inches(0.95) if len(body) > 95 else Inches(0.72)
        else:
            text(s, Inches(2.9), y, Inches(9.8), Inches(0.8), "– " + body, size=14, color=GRAY)
            y += Inches(0.72) if len(body) > 95 else Inches(0.55)
    box(s, Inches(0.6), Inches(6.35), Inches(12.1), Inches(0.7), fill=RGBColor(0xE7, 0xF2, 0xE7))
    text(s, Inches(0.8), Inches(6.48), Inches(11.7), Inches(0.5), "\u2713  " + footer,
         size=14, bold=True, color=GREEN, anchor=MSO_ANCHOR.MIDDLE)

# ---------------------------------------------------------------- Slide 8 build
s = prs.slides.add_slide(BLANK)
header(s, "WHAT WAS BUILT", "End-to-end flow (all additive, in src/pilots/fabric-onelake/)")
steps = [
    "Cost Mgmt\nexport", "ADF\norchestrator", "Fabric notebook\n01 validate", "02 write\nDelta",
    "03 compact\n+ metrics", "04 readiness\ngate", "Power BI\nSQL endpoint",
]
n = len(steps)
cw = Inches(1.55)
gap = Inches(0.18)
total = n * cw + (n - 1) * gap
x = (SW - total) / 2
y = Inches(2.6)
for i, st in enumerate(steps):
    accent = GREEN if i >= 2 else BLUE
    box(s, x, y, cw, Inches(1.2), fill=LIGHT, line=accent)
    text(s, x, y, cw, Inches(1.2), st.split("\n"), size=12, bold=True,
         color=INK, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, space=2)
    if i < n - 1:
        text(s, x + cw - Inches(0.02), y + Inches(0.35), gap + Inches(0.1), Inches(0.5),
             "→", size=20, bold=True, color=GRAY, align=PP_ALIGN.CENTER)
    x += cw + gap
text(s, Inches(0.6), Inches(4.3), Inches(12.1), Inches(0.6),
     "Then 05 promotion: after a full billing cycle, the accumulated readiness history — not a judgment call — authorizes DirectLake.",
     size=15, color=GRAY)
bullets(s, Inches(0.6), Inches(5.1), Inches(12.1), Inches(1.8), [
    ("Blue = unchanged existing toolkit surface.   Green = new pilot code.", 0),
    ("Nothing in the existing hub, template, or report is modified — the pilot lives beside them.", 0),
], size=15)

# ---------------------------------------------------------------- Slide 9 evidence
s = prs.slides.add_slide(BLANK)
header(s, "EVIDENCE", "How it's validated today — and what's left")
text(s, Inches(0.6), Inches(1.45), Inches(6), Inches(0.5), "Proven now (logic)", size=18, bold=True, color=GREEN)
bullets(s, Inches(0.6), Inches(2.0), Inches(6), Inches(4), [
    ("33 Python unit tests: schema/null/version enforcement, compaction-SLA math, readiness + promotion logic.", 0),
    ("10 Pester tests: deployment-parameter validation + fail-loud preflight.", 0),
    ("az bicep build: the ADF→Fabric pipeline compiles.", 0),
    ("Sufficient for an office-hours design discussion.", 0),
], size=15)
text(s, Inches(6.9), Inches(1.45), Inches(6), Inches(0.5), "Homework (needs live capacity)", size=18, bold=True, color=BLUE)
bullets(s, Inches(6.9), Inches(2.0), Inches(5.9), Inches(4), [
    ("Run the repo lint task for house-style parity.", 0),
    ("One small live end-to-end run on a Fabric Lakehouse.", 0),
    ("Before/after query-time proof at $2–5M scale (the headline claim).", 0),
    ("Confirm/revise provisional Z-order from real query filters.", 0),
], size=15)

# ---------------------------------------------------------------- Slide 10 ask
s = prs.slides.add_slide(BLANK)
box(s, 0, 0, SW, SH, fill=BLUE)
text(s, Inches(0.8), Inches(0.9), Inches(11.7), Inches(0.8),
     "Discussion / asks for the team", size=30, bold=True, color=WHITE)
bullets(s, Inches(0.9), Inches(2.0), Inches(11.5), Inches(4.5), [
    ("Is src/pilots/ an acceptable home for exploratory work, or do you prefer a Microsoft.Fabric namespace module from the start?", 0),
    ("Is there a sanctioned Fabric test capacity a pilot could use for the live end-to-end run?", 0),
    ("Does \u201cKQL stays the single transform owner\u201d align with your Fabric roadmap, or is a Spark-native transform planned (which would change Decision 1)?", 0),
    ("Should the schema contract point at the open-data metadata (as built) or a future published schema artifact?", 0),
], size=18, color=WHITE, space=16)

prs.save(OUT)
print(f"Saved {OUT}")
