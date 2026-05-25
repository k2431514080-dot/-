---
name: office-documents
description: Use this skill when the user asks Codex to create, read, modify, format, repair, convert, summarize, or verify Microsoft Office files, including Word .docx, Excel .xlsx/.xls, and PowerPoint .pptx files.
---

# Office Documents Skill for Word, Excel, and PowerPoint

This skill is for reliable handling of Office documents in Codex workspaces.

Use it whenever the task involves:
- Word reports, proposals, SOPs, meeting minutes, technical documents, templates, comments, tracked changes, tables, headers/footers, page layout, or conversion to PDF.
- Excel workbooks, formulas, charts, dashboards, data cleaning, tables, pivot-style summaries, cost analysis, test data, SPC/CPK calculations, or report exports.
- PowerPoint presentations, report decks, customer-facing slides, technical review slides, charts, diagrams, layout polishing, or visual consistency.

## General rules

1. Do not only change text blindly. First identify the user's target file type and the expected final output.
2. Preserve the original content and formatting unless the user explicitly asks for redesign.
3. Create a backup or work on a copy before major edits.
4. Prefer native Office formats for delivery: `.docx`, `.xlsx`, `.pptx`.
5. When modifying existing files, verify the output before final delivery.
6. Never claim the file is complete until it has been opened, inspected, or rendered in a reasonable way.
7. For Chinese business or engineering reports, use clear, concise, conclusion-first wording. Avoid empty phrases.
8. For technical/company reports, keep tables aligned, units explicit, conclusions traceable to data, and wording suitable for manager review.

## Word / DOCX workflow

Use for `.docx` tasks.

Recommended tools:
- `python-docx` for normal editing, tables, headings, styles, paragraphs, and images.
- Direct OOXML editing only when necessary for comments, tracked changes, fields, bookmarks, or advanced layout.
- LibreOffice headless export/render for layout verification when available.

Workflow:
1. Inspect document structure: headings, sections, tables, images, page breaks, headers/footers.
2. Understand the user's requested chapter, paragraph, table, or style change.
3. Edit with minimal disturbance to the rest of the document.
4. Check formatting: title hierarchy, table width, alignment, spacing, font consistency, numbering, and page breaks.
5. Render or export to PDF/PNG when layout matters.
6. If layout is broken, fix and verify again.

Word quality checklist:
- Headings are consistent.
- Tables do not overflow the page.
- Numbering is correct.
- No random font changes.
- No missing images or captions.
- Final wording is natural and suitable for business/engineering reports.

## Excel / XLSX workflow

Use for `.xlsx` or `.xls` tasks.

Recommended tools:
- `openpyxl` for workbook creation/editing, formulas, cell styles, charts, conditional formatting, merged cells, and page setup.
- `pandas` only for data analysis; do not use it as the final formatting tool.
- LibreOffice or Excel-compatible recalculation when formulas need verification.

Workflow:
1. Inspect workbook sheets, used ranges, formulas, charts, merged cells, and existing formatting.
2. Preserve formulas unless the user wants them changed.
3. For analysis tasks, separate raw data, calculation area, and summary/dashboard area.
4. Use formulas for derived values where possible instead of hardcoding.
5. Apply readable formatting: headers, borders, number formats, units, column widths, frozen panes, filters.
6. Check formulas for common errors: `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`.
7. Save as `.xlsx` unless the user requests another format.

Excel quality checklist:
- Units are visible.
- Formula ranges are correct.
- Summary values match source data.
- Charts have titles, axes, and units where needed.
- Tables are readable and not over-formatted.
- Cost comparison, test-data comparison, and SPC-style sheets should include clear conclusions.

## PowerPoint / PPTX workflow

Use for `.pptx` tasks.

Recommended tools:
- `python-pptx` for slide creation/editing, text boxes, shapes, images, charts, and tables.
- Use a consistent theme: title, subtitle, content, conclusion, and appendix pages.
- Export to PDF or render slides for visual verification when available.

Workflow:
1. Identify the audience: manager review, customer presentation, internal archive, technical meeting, or training.
2. Determine the core message of each slide before designing the layout.
3. Keep one slide focused on one point.
4. Use consistent margins, fonts, title placement, table styles, and visual hierarchy.
5. Prefer charts/tables/flow diagrams over long text when explaining comparisons or process.
6. Verify slide readability and avoid text overflow.

PowerPoint quality checklist:
- Each slide has a clear title and purpose.
- Important conclusions are easy to find.
- Tables and charts are readable.
- Layout is aligned and not crowded.
- Technical terms, units, and comparison objects are clear.

## Common prompt patterns

When the user says:
- “帮我修改这份报告” → inspect the document, improve structure/wording/format, and return an edited `.docx`.
- “帮我加一个对比表格” → add a clean table and explain assumptions.
- “帮我做成PPT” → extract key conclusions, build a slide outline, then create a concise `.pptx`.
- “帮我整理Excel数据” → preserve raw data, create analysis/calculation sheets, add summary and charts.
- “帮我看看第五章” → focus only on that chapter, but verify numbering and surrounding formatting.

## Output rules

Final response should include:
- What was changed.
- The output file path or download link.
- Any assumptions or items that still need manual confirmation.

Do not include long implementation details unless the user asks.
