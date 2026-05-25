---
name: xlsx
description: Use this skill when Codex needs to create, read, analyze, clean, format, calculate, chart, repair, validate, or export spreadsheet files such as .xlsx, .xlsm, .xls, .csv, or .tsv. This includes cost analysis, test data, SPC/CPK, peak/valley statistics, charts, dashboards, formulas, and engineering data reports.
---

# XLSX Skill

This skill is for spreadsheet work in Codex. The goal is to produce reliable, readable, formula-safe Excel files.

## When to use

Use this skill for:
- Editing or creating `.xlsx` files.
- Cleaning raw test data.
- Building cost comparison tables.
- Calculating averages, absolute-value averages, max/min, range, standard deviation, CV, CA, CP, CPK, or other quality metrics.
- Creating charts for angle-data curves, peak/valley data, per-pole comparison, trend analysis, and cost comparison.
- Creating summary sheets or dashboards.
- Checking formulas and formatting.

Do not use this skill when the final deliverable is mainly Word or PowerPoint, unless an Excel file is also required.

## Preferred tools

Use available tools in this order:
1. `openpyxl` for final `.xlsx` creation/editing, formulas, styles, charts, merged cells, filters, frozen panes, page setup, and workbook structure.
2. `pandas` for data cleaning and analysis only. Do not rely on pandas alone for final formatting.
3. LibreOffice headless recalculation when formula results must be refreshed.
4. CSV/TSV parsing only as an intermediate step when needed.

## Workbook structure

For engineering workbooks, prefer a clear structure:
- `Raw_Data` or `原始数据`: untouched source data.
- `Calc` or `计算`: formulas and intermediate calculations.
- `Summary` or `汇总`: final results and conclusions.
- `Charts` or `图表`: charts and visual comparison.
- `Settings` or `参数`: tolerance limits, specification values, assumptions.

Never overwrite raw data unless the user explicitly asks.

## Formula rules

- Use formulas where users may need to adjust inputs later.
- Avoid hardcoding calculated results unless the file is intended as a static report.
- Check for common Excel errors: `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, circular references, wrong ranges.
- Use absolute references when fixed parameters are used in repeated formulas.
- Keep assumptions in visible cells.
- For engineering data, always show units.

## Formatting rules

- Use clear headers.
- Freeze the header row for long tables.
- Apply filters for data tables.
- Use borders lightly; avoid over-decorating.
- Set column widths so values are readable.
- Use number formats consistently:
  - angles: `0.0°` or `0.00°`
  - magnetic field: `0` or `0.0 Gs`
  - percentage: `0.0%`
  - cost: `¥0.0000` or `¥0.00` depending on precision
  - standard deviation: match source precision
- Put units in headers, for example `表磁(Gs)`, `角度(°)`, `成本(RMB/pcs)`.

## Engineering data patterns

For multi-pole magnet testing:
- Separate N and S poles when the user asks for polarity-based statistics.
- Use absolute values when evaluating overall field strength regardless of polarity.
- For 24-pole rings, clearly state whether statistics are based on:
  - all raw sampling points
  - 24 peak values
  - N-pole peaks only
  - S-pole peaks only
  - absolute average of all sampled values
- For equipment correlation, keep both baseline equipment data and target equipment data visible.
- If compensation is calculated, show before/after results.

For repeated measurement validation:
- Use fixed-position repeat tests and random-load repeat tests separately if both exist.
- Recommended indicators: mean, max, min, range, standard deviation, CV, maximum error.
- Highlight whether the issue is repeatability, fixture positioning, sampling, or data processing.

For cost analysis:
- Separate confirmed prices from estimated prices.
- Clearly mark assumptions.
- Include comparison columns such as current solution, option 1, option 2, benchmark solution, difference, and conclusion.
- Do not hide the logic behind estimated costs.

## Chart rules

Use charts when they help explain the conclusion:
- Line chart: angle-data curve, waveform, trend over angle/time.
- Column chart: per-pole peak comparison, cost comparison, scheme comparison.
- Scatter chart: correlation between baseline equipment and target equipment.
- Control/tolerance chart: upper/lower limit comparison.

Every chart should have:
- title
- axis labels
- units
- readable legend
- source data nearby or traceable

## Validation checklist

Before final delivery, check:
- Workbook opens.
- Formulas are preserved and ranges are correct.
- No visible formula errors.
- Important assumptions are visible.
- Charts reference the correct ranges.
- Units are clear.
- Raw data is not accidentally changed.
- Final summary matches the calculation sheets.

## Final response format

When finished, report:
- Output file name.
- Sheets created or modified.
- Main calculations or charts added.
- Any assumptions or manual checks still needed.

Keep the response brief unless the user asks for details.
