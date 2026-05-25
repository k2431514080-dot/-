# Codex Instructions

This repository contains Codex skills for Office document work. When a user asks Codex to create, read, modify, polish, analyze, format, validate, or export Office files, use the matching skill under `.codex/skills/`.

## Skill selection

Use these skills by file type and task:

- `.codex/skills/docx/SKILL.md`  
  Use for Word `.docx` documents, reports, SOPs, meeting minutes, project closing reports, tables, headings, page layout, comments, and Chinese engineering/business document polishing.

- `.codex/skills/xlsx/SKILL.md`  
  Use for Excel `.xlsx/.xlsm/.xls`, CSV, TSV, formulas, charts, cost analysis, test data, SPC/CPK, peak/valley statistics, dashboards, and data validation.

- `.codex/skills/pptx/SKILL.md`  
  Use for PowerPoint `.pptx`, slide decks, technical review slides, manager reports, customer presentations, scheme comparison slides, cost slides, and process slides.

- `.codex/skills/office-report/SKILL.md`  
  Use together with docx/xlsx/pptx when the task is a Chinese engineering/business report, weekly report, cost analysis report, project closing report, supplier/customer communication document, or manager-facing summary.

- `.codex/skills/office-documents/SKILL.md`  
  Legacy combined Office skill. Use only as a fallback if a task spans Word, Excel, and PowerPoint and no more specific skill is enough.

## General Office file handling rules

1. Preserve the original file structure and formatting unless the user explicitly asks for redesign.
2. Work on a copy for major edits.
3. Prefer native Office outputs: `.docx`, `.xlsx`, `.pptx`.
4. Verify files before final delivery whenever possible.
5. For Word: check headings, numbering, tables, page layout, fonts, and overflow.
6. For Excel: preserve raw data, preserve formulas unless asked to change them, check formula ranges, units, charts, and common formula errors.
7. For PowerPoint: keep one slide focused on one idea, use consistent layout, and check text overflow/readability.
8. For Chinese engineering/business reports: use concise, conclusion-first wording suitable for manager review.

## User style preference

The user often works on mechanical/product structure, magnetic rings, magnetic damping mouse wheel modules, full-inspection equipment, cost comparison, and technical reports. Prefer practical wording, clear tables, manager-facing conclusions, and explicit assumptions.
