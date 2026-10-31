# 可行性判定 — `scripts/feasibility.py`

Use in Step 11, before any scheme is delivered. The user builds from the scheme, so the verdict must be honest: the gate collects every check the tools can compute, plus the assumptions and the test plan for what they cannot compute, and returns one verdict.

```bash
python3 scripts/feasibility.py project.json --out 可行性判定.md
```

## 1. 四档结论

| 结论 | 条件 | 交付时怎么写 | 退出码 |
|---|---|---|--:|
| 可行 | 所有检查通过, 假设全部已确认, 验证项全部已通过 | 可以写 "可行 (在本工具校核范围内)" | 0 |
| 有条件可行 | 没有不可行项, 但有假设待确认、验证待完成或需要样本复核 | 结论里写 "有条件可行", 并列出关键条件; 全部条件放进待确认事项 | 1 |
| 评估未完成 | 有本工具无法计算、又没有验证计划的项目 | 不能说可行; 先补验证计划 | 2 |
| 不可行 | 干涉、运动干涉、遮挡光栅、选型不足、节拍不够、光栅距离不够、SCARA 够不着、布局与计算不一致等 | 不能作为推荐方案出图; 修改后重跑 | 3 |

`accepted` 只能把 "条件" 改成 "已接受", 永远不能放行 "不可行"。

## 2. 项目文件

路径相对于项目文件所在目录。

```json
{
  "title": "磁环表磁全检机",
  "target_uph": 1800, "oee": 0.85, "pcs": 1, "margin_min": 0.10,
  "layout": "layout.json",
  "cycle": "actions.csv", "cycle_mode": "sync",
  "links": [
    {"layout": "unload", "resource": "下料手", "note": "抬起位放料, 省去两次 Z 动作"}
  ],
  "calcs": [
    {"name": "S5 Z 滑台气缸", "cmd": "cylinder --mass 0.6 --mode vertical --stroke 55 --speed 400", "selected_bore": 10},
    {"name": "磁环吸盘", "cmd": "vacuum --mass 0.002 --accel 10 --max-cup 3", "selected_cup": 2},
    {"name": "前侧安全光栅", "cmd": "safety --curtain-ms 10 --stop-ms 40 --resolution 14"}
  ],
  "assumptions": [
    {"item": "目标产能 1,800 UPH", "status": "已确认"},
    {"item": "磁环重量约 2 g", "status": "假设", "verify": "样品称重"}
  ],
  "accepted": [
    {"match": "需人工补料/倒料的位置在防护区内", "reason": "每 35 min 暂停约 1 min, 已计入 OEE"}
  ],
  "tests": [
    {"item": "表磁 GR&R ≤ 10%", "covers": ["测量能力"], "when": "样机阶段"},
    {"item": "定位方案评审", "covers": ["定位方案"], "when": "详细设计评审", "status": "已通过"}
  ]
}
```

| 字段 | 作用 |
|---|---|
| `target_uph`, `oee`, `pcs`, `margin_min` | 节拍判定: 余量 ≥ margin_min (默认 10%) 为通过, 0~10% 为条件, < 0 为不可行 |
| `layout` | 3D 布局 JSON: 干涉/运动干涉/遮挡光栅/SCARA 够不着 → 不可行; 补料间隔、人工操作、光栅距离等 → 条件或通过 |
| `cycle`, `cycle_mode` | 节拍表 CSV |
| `links` | 把布局中的 `pick_place` 与节拍表的执行机构对应; 节拍表比布局几何估算快 20% 以上时列为条件, `note` 写依据 |
| `calcs` | `mech_calc.py` 的参数 (不含脚本名); `[NG]` → 不可行; `selected_bore` / `selected_cup` 小于计算值 → 不可行; `[注意]` 合并为 "外购件按厂家样本复核", 复核后加 `"confirmed": true` |
| `assumptions` | `status`: 已确认 / 假设 / 待确认 / 待实测; 非 "已确认" 的都是条件, 必须有 `verify` |
| `accepted` | 已评审接受的条件 (按文字匹配), 写清理由 |
| `tests` | 验证计划; `covers` 对应无法计算项, `status: "已通过"` 后才算通过 |

一致性检查还包括: 布局光栅 `min_distance` 小于 `safety` 计算的安全距离 → 不可行; 布局中有 `pick_place` 但没有在 `links` 中关联 → 条件。

## 3. 本工具无法计算的项目 (必须有验证计划)

| 类别 | 内容 | 常见验证方式 |
|---|---|---|
| 测量能力 (有探头/相机时) | 重复性、GR&R、与基准设备的相关性 | 样机 GR&R、固定位置/随机取放重复测试 |
| 定位方案 | 过定位/欠定位、基准统一、取放方式与治具是否匹配 | 设计评审 (按 `design-review-checklist.md` 精度链一节) |
| 产品损伤 | 划伤、崩边、变形、静电、互吸 | 简易工装试验 (落料、夹持、推料) |
| 结构刚性 | 立柱、悬臂、转盘、压装支撑的变形和振动 | 经验校核或 FEA |
| 供应商数据 | 凸轮/机器人/DD/模组的节拍、精度、负载 | 规格书、询价确认 |
| 线缆与维护 | 气管线缆、拖链、易损件更换和调试空间 | 详细设计 3D 检查 |

## 4. 使用要点

- 先跑判定再写结论; 结论第一句写判定原文, 不要自己改写成 "可行"。
- "不可行" 的处理: 按清单逐条修改布局/选型/节拍, 重新跑, 直到不再出现不可行项。
- "有条件可行" 是方案阶段的正常结论: 条件清单就是下一步计划 (询价、试验、样机测试)。
- 样机阶段: 把实测动作时间回填节拍表、把通过的试验 `status` 改为 "已通过"、把确认的假设改为 "已确认", 再跑一次, 直到结论变为 "可行"。
