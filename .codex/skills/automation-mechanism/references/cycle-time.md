# 节拍分析方法

Use in Step 7. Goal: prove the scheme reaches the target UPH with margin, and name the bottleneck.

## 1. 节拍公式

- 理论 UPH = 3600 / CT × 每节拍产出数
- 实际 UPH = 理论 UPH × OEE (综合效率 = 稼动率 × 性能 × 良率, 缺省 0.85)
- 要求节拍 CT_req = 3600 × 每节拍产出数 × OEE / 目标 UPH
- 余量 = (CT_req − CT) / CT_req; 方案阶段要求 ≥ 10%

示例: 目标 1800 UPH, 单件, OEE 0.85 → CT_req = 3600 × 0.85 / 1800 = 1.70 s.

## 2. 同步 vs 异步

| 模式 | 设备 | CT |
|---|---|---|
| sync (同步) | 转盘机、同步搬运线: 所有工位等最慢工位完成后一起移动 | 一个节拍内动作网络的关键路径长度 |
| async (异步) | 带缓存的直线线体: 工位独立循环 | 最慢工位的循环时间 |

Two lower bounds always hold and are reported by the script:
- 关键路径长度 (动作先后约束);
- 任一执行机构的动作时间之和 (一个机构同一时间只能做一件事).
If the critical path is clearly longer than the resource bound, there is waiting time that overlap or pre-fetch can remove.

## 3. 动作分解

Break every station into atomic actions with one executing mechanism each:

| 原动作 | 分解 |
|---|---|
| "取料" | Z 下降 → 真空吸附+确认 → Z 上升 |
| "搬运到转盘" | X 平移 (可与 Z 上升末段重叠) |
| "放料" | 等分度完成 → Z 下降 → 破真空 → Z 上升 |
| "测量" | 探头进给 → 采样 → 探头退回 ‖ 数据计算 |

For an arm whose X and Z axes can move at the same time (门型轨迹), give X and Z separate `resource` names; otherwise the script flags their overlap as a conflict.

## 4. 典型动作时间 (方案阶段估算)

| 动作 | 时间 s | 备注 |
|---|---|---|
| 电磁阀响应 | 0.01~0.03 | |
| 小气缸单程 (缸径 ≤ 20, 行程 10~30 mm) | 0.15~0.30 | 含阀响应与磁性开关确认 |
| 气缸单程 (行程 50~100 mm) | 0.30~0.60 | 带缓冲; `mech_calc.py cylinder --stroke --speed` |
| 气爪开/合 | 0.10~0.20 | |
| 旋转气缸 90°/180° | 0.20~0.50 | 惯量大时需降速 |
| 真空建立 + 压力确认 | 0.05~0.15 | 发生器靠近吸嘴 |
| 破真空释放 | 0.05~0.15 | 带破坏阀 |
| 伺服模组短行程 (≤ 50 mm) | 0.15~0.30 | `mech_calc.py move` |
| 伺服模组 200~300 mm | 0.35~0.60 | |
| 转盘分度 (分割器/DD, 4~12 工位) | 0.20~0.60 | `mech_calc.py rotary/indexer` |
| SCARA 门型取放单程 | 0.3~0.6 | 含吸放约 0.8~1.5 s/件 |
| 视觉拍照 + 处理 | 0.10~0.30 | 依算法复杂度 |
| 扫码 | 0.10~0.30 | |
| 传感器到位确认/滤波 | 0.02~0.10 | |
| 伺服压装 (含保压) | 0.5~2.0 | |
| 锁螺丝 M2~M3 | 1.0~2.0 | 含取钉 |
| 人工上料 (单件) | 2~4 | |

When a 3D layout exists, take pick-and-place X/Z times from the `layout3d.py` report (X/Z 单程估算) so the cycle table matches the geometry. Replace estimates with measured values after prototype debugging, and re-run the analysis.

## 5. 动作表 CSV

Fragment showing the syntax (not runnable on its own; the complete sample is in `assets/`):

```csv
id,station,action,duration,after,resource,note
T1,转盘,转盘分度,0.40,,转盘,
L1,S1上料,吸嘴Z下降,0.20,,上料手Z,与分度并行
L4,S1上料,X平移,0.30,L3-0.05,上料手X,Z上升末段即开始平移
L5,S1上料,放料Z下降,0.20,T1;L4,上料手Z,须等分度完成
M4,S3表磁,数据计算,0.10,^M3,控制器,与探头退回同时开始
```

`after` syntax: `A3` 结束后开始; `A3+0.05` 结束后再等; `A3-0.10` 提前开始 (重叠); `^A3` 与 A3 同时开始; `^A3+0.2` A3 开始后 0.2 s. Multiple predecessors are separated by `;`.

Run:

    python3 scripts/cycle_time.py actions.csv --target-uph 1800 --oee 0.85 --svg gantt.svg --csv-out schedule.csv

Full sample: `assets/cycle_example_magnet_ring.csv` (6 工位磁环表磁全检机, CT 1.6 s, 瓶颈 = 上料手).

## 6. 提速手段 (按代价从低到高)

1. 动作重叠: Z 上升末段开始 X 平移, 分度期间预取料, 数据计算与机构复位并行.
2. 缩短行程与等待: 降低 Z 行程, 缩短确认滤波, 真空发生器靠近吸嘴.
3. 提高速度: 气缸加大口径/快排阀, 伺服提高加速度 (先校核电机与负载固定).
4. 拆分瓶颈动作: 一取一放两套机构, 双吸嘴一次取放两件, 测量拆成两个工位.
5. 并行化: 双工位/双头测量, 多穴治具 (每节拍产出 2 件).
6. 换结构: 气缸取放 → 凸轮取放; 伺服+减速机转盘 → 凸轮分割器/DD; 同步 → 异步加缓存.

After each change, re-run the script and report before/after CT and UPH.
