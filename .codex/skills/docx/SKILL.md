---
name: docx
description: Use this skill when Codex needs to create, read, inspect, revise, polish, format, repair, convert, or validate Microsoft Word .docx documents. This includes reports, SOPs, meeting minutes, technical documents, project closing reports, tables, headings, page layout, comments, tracked-change style editing, and Chinese engineering/business documents.
---

# DOCX Skill

This skill is for Word document work in Codex. The goal is not only to edit text, but to preserve document structure and deliver a file that can be opened and reviewed directly.

## When to use

Use this skill for:
- Creating a new Word report or template.
- Modifying an existing `.docx` file.
- Reviewing a specific chapter, paragraph, table, or conclusion section.
- Adding comparison tables, cost tables, test result tables, or project summaries.
- Improving wording for managers, customers, suppliers, or internal archive.
- Converting a document to PDF for layout checking.

Do not use this skill for spreadsheets, slide decks, or plain code tasks.

## Preferred tools

Use available tools in this order:
1. `python-docx` for normal paragraphs, headings, tables, styles, page sections, and pictures.
2. Direct OOXML editing only when `python-docx` cannot handle the required feature.
3. LibreOffice headless export to PDF for final layout checking when available.
4. XML inspection by unzipping `.docx` when formatting, comments, numbering, or embedded objects are unclear.

## Standard workflow

1. Make a working copy before editing.
2. Inspect the document structure:
   - headings and numbering
   - tables
   - images and captions
   - headers/footers
   - page breaks and section breaks
   - fonts, spacing, and alignment
3. Identify the user’s exact target:
   - full document polish
   - specific chapter modification
   - table insertion
   - conclusion rewriting
   - format cleanup
4. Edit with minimum disturbance to unrelated content.
5. Keep the wording natural, concise, and suitable for the audience.
6. Verify the edited file opens successfully.
7. If layout matters, export or render to check whether tables overflow or text is misplaced.
8. Return the edited `.docx` file and summarize key changes.

## Chinese engineering report style

For Chinese technical/business reports, prefer:
- 结论先行。
- 句子短一点，避免空话。
- 明确对象、动作、结果、下一步。
- 表格比长段落更适合比较方案。
- 成本、尺寸、测试数据必须带单位。
- 问题描述要避免责任误判，尤其是客户样品、供应商样品、内部设备问题之间要区分清楚。

Recommended wording patterns:
- “从当前验证结果看，方案二综合表现较优，可作为优先推荐方案。”
- “方案一表现接近方案二，可作为备选方案保留。”
- “方案三当前表现相对较差，暂不作为优先推荐方案。”
- “本阶段评估主要基于样品实测体验，后续客户验证阶段建议补充扭矩曲线、噪音、寿命及可靠性测试。”

Avoid weak phrases:
- “提供依据” without saying what decision it supports.
- “进一步优化” without saying what to optimize.
- “相关问题” without naming the actual problem.
- Overly broad phrases such as “具有重要意义”.

## Tables

When adding or modifying tables:
- Add a clear table title or lead-in sentence.
- Use consistent column names.
- Keep units in headers, not repeated in every cell.
- Align numbers consistently.
- Keep assumptions visible, especially cost assumptions.
- For comparison tables, include a conclusion row or recommendation column when helpful.

Common table types:
- 方案对比表
- 成本对比表
- 测试结果汇总表
- 问题点与改善方向表
- 阶段结论与后续计划表

## Validation checklist

Before final delivery, check:
- The file opens.
- Headings and numbering are not broken.
- Tables fit the page width.
- Fonts do not randomly change.
- Important conclusions are visible.
- No accidental deletion of original content.
- Any assumptions are clearly marked.
- The final file name is clear.

## Final response format

When finished, report:
- Output file name.
- Main modifications.
- Any assumptions or items requiring confirmation.

Keep the response brief unless the user asks for details.
