---
name: automation-mechanism
description: Use this skill when Codex needs to design, select, size, review, compare, or document mechanical mechanisms for non-standard automation equipment (非标自动化设备机构方案). Covers process/action decomposition; mechanism selection for feeding, separation, pick-and-place, conveying, indexing, locating/clamping, pressing, measuring and sorting; sizing of cylinders, vacuum cups, ball-screw and belt modules, servo motors, rotary tables, cam indexers, linear guides and light-curtain safety distance; cycle time/UPH and bottleneck analysis; quick 3D concept layouts (interactive HTML viewer + STEP assembly for SolidWorks/Creo/NX) with clash and motion-envelope checks; risk and error-proofing review; weighted scheme comparison; BOM/cost estimates; and scheme documents for full-inspection, assembly and test machines such as magnetic ring inspection or mouse wheel module assembly equipment.
---

# Automation Mechanism Skill

Turn a product + process requirement into a buildable mechanism scheme: every action has a mechanism, every key component has a sizing calculation, the cycle time is proven, risks are explicit, and a manager can read the recommendation in 30 seconds.

## When to use

- 新设备/新工站机构方案构思: 全检机、组装机、测试机、上下料机、分拣/包装机.
- 现有机构方案的评审、问题分析、提速或降本.
- 元件选型计算: 气缸、真空吸盘、丝杠/同步带模组、伺服电机、转盘、凸轮分割器、直线导轨、安全光栅.
- 节拍/UPH 核算、时序甘特图、瓶颈分析.
- 快速出 3D 概念方案: 交互式 3D 预览 + STEP 装配体 (可在 SolidWorks 等 CAD 中打开作设计参考) + 干涉检查.
- 多方案对比与推荐, BOM 与成本估算, 方案说明书/评审 PPT 的技术内容.

Not for: detailed part drawings and GD&T, PLC programs, electrical schematics. For those, provide interface data (key dimensions, IO list, sensor list) and stop there.

## Bundled resources

| Path | Use |
|---|---|
| `references/requirements-checklist.md` | 需求清单、阻塞项、缺省假设、提问模板. Read in Step 1. |
| `references/mechanism-library.md` | 布局形式和功能→候选机构库 (适用/优缺点/精度/节拍/成本), 磁性产品专项. Read in Steps 3–4. |
| `references/actuator-sizing.md` | 选型公式与经验系数, one section per `mech_calc.py` subcommand, plus what the script does not check. |
| `references/cycle-time.md` | 节拍公式、同步/异步、动作分解、典型动作时间、CSV 语法、提速手段. |
| `references/design-review-checklist.md` | 评审检查表 (精度链、安全、防错、维护、成本、磁性) 和简化 FMEA 表. |
| `references/scheme-document-template.md` | 方案说明书结构、机构说明模板、BOM 表、一页纸汇报、评审 PPT、布局草图. |
| `references/layout-3d.md` | 3D 概念布局: JSON 格式、坐标约定、组件库 (参数/锚点)、检查项、布置技巧、CAD 中的用法. Read before Step 6. |
| `scripts/mech_calc.py` | 选型计算: `cylinder vacuum screw belt rotary indexer guide move safety`. |
| `scripts/cycle_time.py` | 动作表 CSV → CT、关键路径、机构负荷、UPH、余量、ASCII/SVG 甘特图. |
| `scripts/scheme_score.py` | 加权评分 CSV → 排名、一票否决、权重敏感性. |
| `scripts/layout3d.py` | 布局 JSON → 交互式 3D 预览 HTML、STEP 装配体、STL、组件清单, 并做静态/取放运动干涉检查. `--types` 列出组件库. |
| `assets/cycle_example_magnet_ring.csv` | 6 工位磁环表磁全检机动作表样例. |
| `assets/scoring_example.csv` | 磁环上料方案加权评分样例. |
| `assets/layout_example_magnet_ring.json` | 6 工位转盘磁环表磁全检机 3D 布局样例 (与上面的节拍样例对应). |
| `assets/layout_example_wheel_test.json` | 直线式滚轮模组手感测试工作站 3D 布局样例 (穿梭模组、模组取放、皮带线). |
| `assets/vendor/three.min.js` | three.js r149 (MIT, `three.LICENSE`), 内嵌到 3D 预览中以便离线打开. |

Scripts need Python 3.8+ and no third-party packages. Paths below are relative to this skill folder; from the repository root use `.codex/skills/automation-mechanism/scripts/...`. Every script supports `-h` and `--out <file>` (UTF-8); the calculation scripts also support `--json`. Input CSVs may be UTF-8 or GBK (Excel default on Chinese Windows).

## Workflow

### 1. Lock the requirement (需求冻结)
Read `references/requirements-checklist.md`. Extract what the user already gave.
- Ask only for blockers (产品尺寸/重量/材料, 目标产能, 工序/检测项, 来料与出料方式), in one short list.
- For everything else, continue with the checklist defaults and list them in a `假设条件` table. Never hide an assumption inside a calculation.

### 2. Decompose process → actions (工艺分解)
Write the process flow, then break each step into atomic actions with 执行机构、行程 (mm)、负载 (kg)、精度 (mm)、时间 (s)、前置条件. This action table drives both mechanism selection and the cycle-time proof.

### 3. Choose the layout (总体布局)
Pick 转盘式 / 直线同步 / 直线异步+缓存 / 机器人工作站 / 环形线 using the rules in `mechanism-library.md` §0, and state why. Sketch the top view (ASCII or Mermaid, see template §F) with material flow, operator side and OK/NG exits.

### 4. Select a mechanism for each action (机构选型)
Use `mechanism-library.md`. Where the choice is not obvious, list 2–3 candidates, pick one, and justify it by 节拍、精度、成本、可靠性、换型. Prefer standard purchased modules over custom parts and proven structures over new ones; any new structure needs a validation plan. For magnetic products apply §11 of the library.

### 5. Size key components (选型计算)
Run `mech_calc.py` for every load-bearing or cycle-critical component; do not size by feel.

```bash
python3 scripts/mech_calc.py cylinder --mass 1.5 --mode vertical --stroke 50 --speed 200
python3 scripts/mech_calc.py cylinder --mode clamp --force 800
python3 scripts/mech_calc.py vacuum --mass 0.02 --accel 10 --max-cup 3
python3 scripts/mech_calc.py screw --mass 8 --lead 10 --speed 500 --accel-time 0.1 --stroke 300
python3 scripts/mech_calc.py belt --mass 3 --pulley-dia 30.6 --speed 1500 --accel-time 0.15 --stroke 800 --ratio 3
python3 scripts/mech_calc.py rotary --stations 6 --index-time 0.4 --cycle-time 1.6 --table-dia 400 --table-thk 15 --fixture-mass 0.3 --fixture-radius 160 --ratio 10 --backlash-arcmin 5
python3 scripts/mech_calc.py indexer --stations 8 --cycle-time 1.2 --index-angle 120 --table-dia 500 --table-thk 15 --fixture-mass 0.8 --fixture-radius 210
python3 scripts/mech_calc.py guide --C 11.4 --load 600 --stroke 300 --cycles 30
python3 scripts/mech_calc.py move --dist 150 --speed 800 --accel 5
python3 scripts/mech_calc.py safety --curtain-ms 15 --control-ms 20 --stop-ms 120 --resolution 30
```

Put the result tables in the scheme. Resolve every `[NG]`, and either resolve or carry forward every `[注意]`. Results are preliminary: say so, and name what must be confirmed with the vendor catalog (额定推力/扭矩、允许动能、允许惯量比、T-N 曲线、许用张力). Once a brand and model are chosen, re-run with `--motor-rated-torque/--motor-inertia`.

### 6. Build the 3D concept layout (3D 概念布局)
Read `references/layout-3d.md`, copy the closer sample from `assets/`, and describe the machine as standard components connected by anchors (取放 `from/to` → 供料出口和工位, 探头/相机 `target` → 工位). Use the sizes from Step 5 so the 3D matches the calculations, then:

```bash
python3 scripts/layout3d.py layout.json --html layout.html --step layout.step --bom layout_bom.csv
```

Fix every `[注意]` clash (static or motion envelope) by moving components or changing `side`/`post_side`/`post_at`/`post_dir`/`arm`; add `touch` only for intended contact. Re-run until the check is clean, then feed the reported strokes (取放 X/Z 行程) back into Step 5. Deliver the HTML (offline viewer, screenshots for PPT) and the STEP assembly (opens in SolidWorks/Creo/NX as one part per component).

### 7. Prove the cycle time (节拍核算)
Write the action table as CSV (syntax in `references/cycle-time.md`, full sample in `assets/`), then:

```bash
python3 scripts/cycle_time.py actions.csv --target-uph 1800 --oee 0.85 --svg gantt.svg
```

Use `--mode async` for buffered lines and `--pcs 2` for multi-cavity fixtures. Report CT, UPH, margin, critical path and bottleneck mechanism. Target margin ≥ 10%; if short, apply the speed-up methods in `cycle-time.md` §6, re-run, and show before/after.

### 8. Review risks and error-proofing (风险评审)
Walk `references/design-review-checklist.md` and output a `风险与对策` table for the open items only. For measuring/inspection machines always cover measurement repeatability (GR&R), the 基准设备相关性 method, and fail-safe NG handling.

### 9. Compare schemes and recommend (方案对比)
When there are 2+ viable schemes, build a scoring CSV (sample in `assets/`) and run:

```bash
python3 scripts/scheme_score.py scoring.csv
```

Use `veto` rows for hard requirements. Justify each score with data from steps 5–8, not preference. Report the winner, the point gap, and whether the ranking is weight-sensitive.

### 10. BOM and cost (BOM 与成本)
List key purchased parts by module (型号规格、品牌、数量、单价) plus machined parts, electrical and a 10%–15% contingency, using template §C. Mark every price as 报价 / 估算 / 历史价, and flag long-lead items.

### 11. Deliver (输出)
Follow `references/scheme-document-template.md`. The default in chat is a Markdown scheme. When the user wants files, combine with:
- `docx` + `office-report` for 方案说明书;
- `xlsx` for 选型计算书 / 节拍表 / BOM (inputs on a `参数` sheet, formulas kept live);
- `pptx` for 方案评审 PPT (布局、节拍甘特、对比、风险、结论).

## Quick 3D path (快速 3D 方案)

When the user mainly wants a 3D scheme fast ("帮我快速出个 3D 方案"), do a compressed pass instead of the full workflow:
1. Step 1 with defaults: ask at most the blockers, otherwise assume and list assumptions.
2. Steps 3–4 briefly: layout form + one mechanism per station, as a short table.
3. Step 5 only for the parts that set geometry (转盘直径, 气缸缸径/行程, 模组行程, 吸盘).
4. Step 6: build the layout JSON, run `layout3d.py`, iterate until no clash.
5. Step 7 if a target UPH is given.
6. Deliver: 轴测 + 俯视 screenshots (or the HTML), STEP, component table with key parameters, assumptions, and 待确认事项. State that it is a block-level concept for layout and space checks, not a detailed design.

## Engineering rules of thumb

- 两点动作、负载小、精度 ≥ ±0.05 mm → 气缸 + 硬限位 + 缓冲; 多点/可调/≤ ±0.02 mm → 伺服丝杠模组; 行程 > 1 m 或高速 → 同步带模组/直线电机.
- 精度由定位元件 (销、V 块、硬限位、芯轴) 保证, 驱动元件只负责送到位.
- 气缸按 0.4 MPa 计算, 负载率: 静 ≤ 0.7, 动 ≤ 0.5, 高速 (> 500 mm/s) ≤ 0.3.
- 伺服: 连续扭矩安全系数 1.5, 惯量比 ≤ 10 (高响应 ≤ 5), 常用转速不超过额定转速.
- 垂直轴和夹紧: 写明断电/断气后的状态 (抱闸、单向阀、锁紧气缸、弹簧).
- 未判定、数据异常、通信超时一律按 NG 处理.
- 节拍余量 ≥ 10%; 样机调试前所有动作时间都是估算值.
- 磁性产品: 测量区附近不用导磁材料和磁源; 磁性件互吸时不用振动盘直接排序, 优先料管/料盘.

## Output format (chat)

Conclusion first, then:
1. 结论: 推荐方案 + CT/UPH 及余量 + 关键精度 + 预算区间 (if known).
2. 假设条件表.
3. 工艺流程 + 布局草图 (有 3D 时附截图和 HTML/STEP 文件).
4. 机构方案表: 工位 | 功能 | 机构/驱动 | 关键参数 | 选型依据.
5. 关键选型计算 (script result tables, condensed).
6. 节拍分析 (CT, critical path, Gantt).
7. 方案对比 (if multiple schemes).
8. 风险与对策.
9. BOM / 成本估算 (if requested).
10. 待确认事项与下一步.

Use practical wording; put units on every number; keep 已确认 and 估算 visibly separate. Keep the answer short when the user asked a narrow question (e.g. one cylinder size): answer with the calculation table, the recommendation, and the 注意 items only.
