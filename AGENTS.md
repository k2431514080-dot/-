# Codex Instructions

This repository contains Codex skills for Office document work and automation mechanism design. When a user asks Codex to create, read, modify, polish, analyze, format, validate, or export Office files, or to design, size, review, or document mechanisms for automation equipment, use the matching skill under `.codex/skills/`.

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

- `.codex/skills/automation-mechanism/SKILL.md`  
  Use for non-standard automation equipment mechanism schemes (非标自动化机构方案): process/action decomposition, mechanism selection, cylinder/vacuum/ball-screw/belt/servo/rotary table/cam indexer/linear guide sizing, cycle time and UPH, quick 3D concept layouts (interactive HTML viewer + STEP assembly for CAD), risk review, scheme comparison, BOM/cost, and full-inspection/assembly/test machine proposals. Combine with docx/xlsx/pptx/office-report when the scheme must be delivered as an Office file.

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

## Automation mechanism rules

1. Size every load-bearing or cycle-critical component with `.codex/skills/automation-mechanism/scripts/mech_calc.py`; do not size by feel.
2. Prove cycle time with `scripts/cycle_time.py` and keep at least 10% margin against the target UPH.
3. Build 3D concept layouts with `scripts/layout3d.py` and fix every reported clash before delivering the HTML viewer and STEP file.
4. State assumptions explicitly and separate confirmed data from estimates; script results are preliminary until checked against vendor catalogs.
5. Before delivering any mechanism scheme, run `scripts/feasibility.py` on a project file and state its verdict word for word (可行 / 有条件可行 / 评估未完成 / 不可行). Never present an infeasible or unverified scheme as feasible, and never state an estimate or supplier figure as fact.
6. After changing any script under `.codex/skills/automation-mechanism/scripts/`, run `python3 .codex/skills/automation-mechanism/scripts/selftest.py`; all checks must pass.

## User style preference

The user often works on mechanical/product structure, magnetic rings, magnetic damping mouse wheel modules, full-inspection equipment, cost comparison, and technical reports. Prefer practical wording, clear tables, manager-facing conclusions, and explicit assumptions.
