---
name: pptx
description: Use this skill when Codex needs to create, read, summarize, redesign, edit, split, combine, format, validate, or export PowerPoint .pptx files. This includes technical review decks, manager reports, customer presentations, project summaries, cost comparison slides, process slides, and engineering diagrams.
---

# PPTX Skill

This skill is for PowerPoint work in Codex. The goal is to create slide decks that are readable, structured, and suitable for business or engineering presentation.

## When to use

Use this skill for:
- Creating a new `.pptx` deck.
- Editing an existing `.pptx` file.
- Turning a Word report or Excel analysis into slides.
- Building manager review slides.
- Creating customer-facing technical presentation materials.
- Making process flow, comparison, cost, validation, or conclusion slides.
- Checking slide layout and readability.

Do not use this skill when the final output is only a Word document or Excel workbook.

## Preferred tools

Use available tools in this order:
1. `python-pptx` for normal creation and editing.
2. Direct OOXML editing only when placeholders, notes, master layouts, or embedded objects require it.
3. LibreOffice headless export to PDF for layout checking when available.
4. Slide rendering or thumbnail generation when visual validation is important.

## Slide planning workflow

Before creating slides, decide:
- Audience: manager, customer, supplier, internal engineer, IT, production, or quality team.
- Purpose: report progress, compare options, explain problem, request decision, archive results, or guide development.
- Core conclusion: what the viewer should remember after reading the deck.

Then create the deck with:
1. Title page.
2. Background or objective.
3. Key findings or current status.
4. Data/comparison/process slides.
5. Problem points and cause analysis if needed.
6. Conclusion and next steps.
7. Appendix only when detailed data is necessary.

## Layout rules

- One slide should explain one main idea.
- Use short titles that communicate the conclusion, not generic titles.
- Avoid dense paragraphs.
- Prefer tables, diagrams, and charts over long text.
- Keep margins consistent.
- Align all objects cleanly.
- Do not crowd the slide.
- Use consistent fonts, title positions, and color logic.
- Use icons or shapes only when they clarify the message.

## Engineering presentation style

For Chinese engineering decks, prefer:
- 标题直接写结论。
- 正文少字，多用表格/流程/对比。
- 每页保留“结论/说明/下一步”之一。
- 成本、尺寸、测试数据必须带单位。
- 方案对比页要有推荐结论。
- 问题分析页要区分现象、原因、影响、下一步。

Recommended slide structures:

### Project progress slide
- 本周完成事项
- 关键问题
- 当前结论
- 下周计划

### Scheme comparison slide
- 对比维度
- 方案一
- 方案二
- 方案三
- 结论/推荐

### Cost analysis slide
- 成本组成
- 对标方案
- 自研方案
- 差异来源
- 降本空间

### Test result slide
- 测试目的
- 测试条件
- 结果数据
- 结论
- 后续验证

### Problem analysis slide
- 现象
- 初步判断
- 影响
- 临时对策
- 后续验证

## Visual hierarchy

Use this order of importance:
1. Slide title / conclusion.
2. Main chart, table, or diagram.
3. Key note or callout.
4. Supporting details.

Avoid:
- Full-page bullet lists.
- Too many colors.
- Tiny tables copied directly from Excel.
- Using screenshots without labels.
- Writing “情况说明” as a title when a conclusion title is possible.

## Chart and table rules

For charts:
- Add title, axis labels, units, and legend.
- Simplify data to the message needed for the slide.
- Do not overload one chart with too many series.

For tables:
- Limit columns when possible.
- Use short phrases.
- Highlight the conclusion or recommended option.
- Keep numeric precision appropriate.

## Validation checklist

Before final delivery, check:
- File opens.
- Text does not overflow boxes.
- Titles are aligned.
- Tables and charts are readable.
- Images are not distorted.
- Slide order tells a complete story.
- The final conclusion is clear.

## Final response format

When finished, report:
- Output file name.
- Number of slides.
- Main slide sections.
- Any assumptions or items requiring confirmation.

Keep the response brief unless the user asks for details.
