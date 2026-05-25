---
name: office-report
description: Use this skill when Codex needs to help with Chinese engineering/business reports, weekly reports, monthly reports, project closing reports, cost analysis reports, technical review materials, supplier/customer communication documents, or manager-facing summaries. This skill can work together with docx, xlsx, and pptx skills.
---

# Office Report Skill

This skill is for Chinese engineering and business reporting. It is optimized for mechanical design, product structure, magnetic component projects, test equipment, cost comparison, supplier communication, and manager review documents.

## When to use

Use this skill for:
- 周报、月报、年度总结。
- 项目阶段结案报告。
- 技术方案对比报告。
- 成本分析报告。
- 客户/供应商沟通资料。
- 测试验证报告。
- 设备软件界面说明。
- 工程问题分析与改善计划。

Use together with:
- `docx` when the output is Word.
- `xlsx` when the output includes data, cost, SPC, or charts.
- `pptx` when the output is a presentation.

## Core writing principles

1. 结论先行：先说结果，再说原因。
2. 面向领导：让读者快速知道当前状态、问题、风险和下一步。
3. 少用空话：每句话尽量有对象、动作、结果。
4. 数据支撑：成本、测试、尺寸、表磁、角度、时间必须有单位。
5. 责任清晰：区分自家问题、客户样品问题、供应商问题、设备问题、待验证问题。
6. 可执行：下一步动作要明确做什么、为什么做、输出什么结果。

## Recommended report structure

### Project review / closing report
1. 项目背景与目标
2. 方案设计说明
3. 样品制作与测试验证
4. 方案对比与问题分析
5. 成本分析
6. 阶段结论
7. 后续建议

### Weekly report
1. 本周完成事项
2. 关键进展
3. 当前问题
4. 下周计划
5. 需协调事项

### Technical issue report
1. 问题现象
2. 测试条件
3. 数据表现
4. 初步原因分析
5. 影响评估
6. 改善方向
7. 下一步验证计划

### Cost analysis report
1. 成本分析目的
2. 对比对象与假设条件
3. 成本组成
4. 差异来源
5. 结论与建议

## Manager-facing wording

Good wording examples:
- “从当前验证结果看，方案二综合表现最好，可作为优先推荐方案。”
- “方案一表现接近方案二，可作为备选方案保留。”
- “方案三当前噪音与顺滑性表现不佳，暂不建议作为推荐方案。”
- “本阶段已完成结构设计、样品制作及初步验证，达到阶段性评估目标。”
- “后续如进入客户验证阶段，建议补充扭矩曲线、噪音分贝、寿命及可靠性测试。”
- “本次成本差异主要来自磁阻尼结构件，其他通用零件暂按相同成本估算。”

Avoid:
- “为后续提供依据” unless the decision is stated.
- “相关问题” without naming the problem.
- “进一步优化” without naming the optimization direction.
- “基本满足要求” without saying which requirement.
- Long sentences with many commas.

## 5W thinking for reports

When writing a progress item, make sure it answers:
- What was done?
- Why was it done?
- What result was obtained?
- What problem remains?
- What will be done next?

Example:
Bad:
“完成样品测试，为后续优化提供参考。”

Better:
“完成三种磁阻尼滚轮模组样品测试。结果显示方案二转动手感和顺滑性表现最好，可作为优先推荐方案；方案三噪音偏大，暂不建议继续推进。”

## Table patterns

### Scheme comparison table
Columns:
- 对比项目
- 方案一
- 方案二
- 方案三
- 结论/建议

### Cost comparison table
Columns:
- 成本项目
- 对标方案
- 磁亿方案一
- 磁亿方案二
- 差异说明

### Problem and action table
Columns:
- 问题点
- 现象描述
- 初步原因
- 影响
- 下一步动作

### Weekly plan table
Columns:
- 项目
- 本周进展
- 当前状态
- 下周计划
- 需协助事项

## Engineering-specific guidance

### Magnetic ring / magnet testing
Use precise terms:
- 表磁(Gs)
- 24极
- N/S极
- 峰值
- 极间差
- 绝对值平均值
- 上下限
- 相关性补偿
- 基准设备
- 自制设备
- 随机取放
- 固定位置重复测试

### Equipment/software interface documents
Explain:
- 页面入口
- 操作流程
- 参数设置
- 权限设置
- 历史记录
- 测试详细数据
- OK/NG判定逻辑
- 基准补偿/相关性设置

Use wording such as:
“相关性设置完成前，生产线全检界面不可进入，避免未完成基准对齐时产生误判数据。”

### Cost assumptions
Always state assumptions:
- 哪些价格为供应商报价。
- 哪些价格为估算。
- 哪些零件暂按相同成本处理。
- 成本差异主要来自哪些零件。

## Final quality checklist

Before final output, check:
- Is the conclusion clear?
- Can a manager understand the status in 30 seconds?
- Are assumptions visible?
- Are units included?
- Are responsibilities and problem sources clearly separated?
- Is the next step actionable?
- Are tables easier to read than paragraphs?

## Final response format

When finished, report:
- What was improved.
- What file was produced or modified.
- Any assumptions or points requiring user confirmation.

Keep the response concise.
