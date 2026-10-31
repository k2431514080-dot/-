# 3D 概念布局 — `scripts/layout3d.py`

Use when the user wants a quick 3D scheme of the machine, or when a mechanism scheme needs a 3D layout to review, screenshot, or open in CAD. The agent writes a layout JSON (a list of standard components), runs the script, fixes every reported clash, and delivers the files.

```bash
python3 scripts/layout3d.py layout.json --html layout.html --step layout.step --png layout --bom layout_bom.csv
python3 scripts/layout3d.py --types          # 组件类型、参数、锚点速查
```

Samples: `assets/layout_example_magnet_ring.json` (6 工位转盘全检机), `assets/layout_example_wheel_test.json` (直线式测试工作站). Copy the closer one as the starting point.

## 1. 输出

| 输出 | 用途 |
|---|---|
| `--html` | 交互式 3D 预览, 双击用浏览器打开. 旋转/平移/缩放, 点选组件看参数 (行程、缸径、位置), 俯视 + 平行投影 = 平面布局图, "截图" 按钮导出带标签的 PNG 放进 PPT/Word. 默认内嵌 three.js (约 650 KB, 可离线、可发邮件); `--cdn` 改为在线加载. |
| `--step` | STEP AP214 装配体: 每个组件一个零件, 零件名 = `组件名 (id)`, 带颜色. 装配体原点 = 台面中心; 每个零件原点 = 该组件安装基准, 朝向随组件. 默认 `--up y` (Y 向上): 在 SolidWorks/Creo/Inventor 中正视图 = 操作者正面、上视图 = 俯视; NX/中望 3D 等 Z 向上软件用 `--up z`. `--step-flat` 输出单零件多实体. |
| `--png 前缀` | 静态视图 PNG (默认 `--views iso,top` → `前缀_iso.png`、`前缀_top.png`), 纯 Python 渲染, 不需要浏览器, 可直接插入 Word/PPT. 默认只取景台面工作区 (`--png-fit all` 为整机), 不画防护罩/光栅/触摸屏/三色灯 (`--png-all` 全画). 图中气泡数字 = 报告 "图号对照" 表和 BOM 的图号. 1600 px 每张约 2~3 s. |
| `--stl` | 整机网格, 给不读 STEP 的软件或渲染用. |
| `--bom` | 组件清单 CSV: 图号、参数、位置、包络尺寸、DI/DO/伺服轴/安全输入/通讯、主要外购件, 可交给 xlsx 技能整理成成本表. |
| 终端报告 | 整机外形、组件关键参数 (取放机构含 X/Z 单程和取放循环时间估算, 可填进节拍表)、锚点坐标、布局检查结果、IO/轴数/主要外购件估算和控制器初选、图号对照, 以及每个运动组件的建议校核命令 (`mech_calc.py ...`, 把 `<>` 换成实际值后运行). |
| 预览中的 "测距" | 依次点两个表面点, 显示距离和 ΔX/ΔY/ΔZ (机器坐标), 用于评审时量间隙、行程和操作距离; Esc 退出. |

在 SolidWorks 中使用: 文件 → 打开 → 选 `.step` → 打开后为装配体 (各组件为独立零件). 可直接测量行程和间距, 在装配体中新建零件参照布局建模, 或把概念零件替换成正式设计. Creo / NX / 中望 / CAXA 均可按 STEP 装配体打开. STEP 里的零件是无特征历史的实体, 圆柱为 24 棱柱 (`--segments` 可调).

## 2. 坐标约定

- 原点 = 工作台面中心; X 向右, Y 向后 (操作者站在 −Y 侧, 即正面), Z 向上; 单位 mm.
- 角度单位为 °, 从 +X 起逆时针为正. 组件 `rot` 是绕 Z 轴的转角.
- 台面以上 z ≥ 0; 机架在 z < 0 (`frame.size[2]` 为台面离地高度).

## 3. JSON 结构

```json
{
  "title": "磁环表磁全检机 3D 概念布局",
  "uph": 1800,
  "product": {"shape": "ring", "od": 12, "id": 6, "h": 3},
  "components": [
    {"id": "frame", "type": "frame", "size": [1000, 800, 850]},
    {"id": "tt", "type": "turntable", "at": [0, 60], "dia": 400, "stations": 6, "fixture_radius": 160,
     "product": {"shape": "ring", "od": 12, "id": 6, "h": 3}},
    {"id": "load", "type": "pick_place", "name": "S1 上料取放", "from": "feeder.out", "to": "tt.S1"}
  ]
}
```

顶层字段: `title`; `components`; 可选 `uph` (目标产能 pcs/h, 用于补料/倒料间隔检查)、`product` (产品, 用于计算料盒能装多少)、`refill_min` (可接受的最短补料/倒料间隔, 默认 30 min).

通用字段:

| 字段 | 说明 |
|---|---|
| `id` | 唯一, 不含 `.`; 用于锚点引用 `id.锚点` |
| `type` | 组件类型, 见第 5 节 |
| `name` | 显示名称 (STEP 零件名、标签), 建议带工位号, 如 `S3 霍尔探头` |
| `at` | 安装位置 (点位写法见下), 默认 [0, 0] |
| `rot` | 绕 Z 转角 °, 默认 0 |
| `touch` | 允许接触的组件 id 列表 (如料盒在滑道出口下方), 这些组件对之间不报干涉 |

参数名写错或不属于该类型时报告 `[注意] 未知参数 ... 已忽略` (不会静默使用默认值); 枚举参数 (drive、head、post_side 等) 写错直接报错. 生成后先看这两类提示.

点位写法 (用于 `at`, `from`, `to`, `tip`, `toward`, `target`):

| 写法 | 含义 |
|---|---|
| `[x, y]` / `[x, y, z]` | 绝对坐标, 省略 z 时 z = 0 (台面) |
| `"tt.S2"` | 锚点 (组件 `tt` 的 `S2`); 顺序无关, 脚本自动按依赖求解 |
| `{"ref": "tt.S2", "out": 6, "up": -1.5, "offset": [dx, dy, dz]}` | 以锚点为基准: `out` = 沿该组件 `center` 锚点向外的水平距离 (无 center 时相对原点), `up` = 抬高, `offset` = 平移 |

## 4. 快速出 3D 方案的步骤

1. 定布局形式和工位 (SKILL.md Step 1–4); 信息不足时按缺省假设, 列入假设表.
2. 先放 `frame` (+ `enclosure`), 再放核心运动件 (转盘 / 治具 / 输送线), 再放供料、取放、检测、下料, 最后放安全件和人机件.
3. 用锚点连接, 不手算坐标: 取放 `from/to` 指向供料出口和工位, 探头/推料 `tip` 用 `{"ref","out","up"}` 定位到产品边缘, 相机/压头 `target` 指向工位, 料盒放在滑道 `out` 下方.
4. 尺寸取自选型计算 (缸径/行程、模组行程、转盘直径、吸盘), 让 3D 和计算一致; 取放机构报告的 X/Z 行程回填到选型计算.
5. 运行脚本, 逐条处理 `[注意]`: 干涉 → 调整 `at`、`side`、`post_side`、`post_at`、`post_dir`、`arm`; 设计上确实接触 → 加 `touch`. 重复直到 `[OK] 未发现组件间静态干涉和取放运动干涉`.
6. 交付: 关键视角截图 (轴测 + 俯视平行投影) + HTML + STEP + 组件清单表 + 假设条件 + 待确认事项.

## 5. 组件库

`python3 scripts/layout3d.py --types` prints the same list. Defaults in parentheses.

### 结构
| type | 参数 | 锚点 | 说明 |
|---|---|---|---|
| `frame` 机架 | `size` [长, 宽, 台面离地高] ([1200, 900, 850]), `plate` (20), `style` cabinet / legs | top, FL, FR, BL, BR (台面四角) | 台面中心为原点 |
| `enclosure` 防护罩 | `size` [长, 宽, 高] ([1200, 900, 1000]), `profile` (40), `open_front` (false) | top | 型材进 STEP; 透明板只在预览中显示 |
| `box` 方块 | `size` [x, y, z], `color` | top | `at` 为底面中心; 治具、电箱、自定义结构 |
| `cylinder` 圆柱 | `d`, `h`, `axis` z / x, `color` | top | `axis: x` 时水平放置 (配合 `rot`) |

### 运动与执行
| type | 参数 | 锚点 | 说明 |
|---|---|---|---|
| `turntable` 转盘 | `dia` (400), `thk` (15), `height` 盘面高 (150), `stations` (6), `fixture_radius` (0.4×dia), `fixture` {d, h} ({40, 20}), `drive` dd / indexer / servo, `start_angle` S1 角度 (−90 = 正前方), `direction` ccw / cw, `product`, `center_plate` {d, z} | S1…Sn (产品顶面中心, 无产品时为治具顶面), center, plate | 中心固定盘用于安装伸向工位的推料/探头 (配合 `support: none`) |
| `linear_module` 直线模组 | `stroke` (300), `width` (80), `height` (60), `pos` 0~1 滑台位置 (0), `vertical`, `payload` [长, 宽, 高] 滑台负载包络 | carriage, start, end (滑台顶面) | 本体沿局部 +X; 料盘、治具放在 `id.carriage`; 给 `payload` 时检查负载在整个行程内的干涉 (装在滑台上的组件自动豁免) |
| `pick_place` 取放机构 | `from`, `to` (工作点 = 产品顶面), `z_stroke` 抬起高度 (30), `drive` cylinder / module, `side` 横梁偏置 (90), `post_side` auto / left / right, `post_at` auto / start / end, `margin` (60), `nozzle_len` (50), `pos` 0~1, `center` (判断"外侧"的中心, 默认原点), `x_speed` / `z_speed` 时间估算用速度 mm/s (气缸 300/200, 模组 800/400) | pick, place, up | 自动生成立柱、横梁、滑块、Z 轴、吸嘴和运动包络; 报告 X 行程、所需 Z 行程、单程和循环时间估算. 估算按取放两端都下降; 抬起位直接放料时在节拍表中减掉 |
| `cylinder_actuator` 气缸 | `tip` 伸出到位时推块前端, `toward` 推向的点 或 `dir` 方向°, `bore` (16), `stroke` (20), `head` block / probe / none, `head_size` [长, 宽, 高] ([10, 20, 15]), `support` down / none | tip, retracted | 侧推定位、NG 剔除、挡停; 推块须高于治具顶面 |
| `probe` 检测探头 | 同上, 默认 `head: probe`, `bore` 10, `stroke` 10 | tip, retracted | 霍尔探头、接触式测头 |
| `camera` 相机 | `target`, `wd` 工作距离 (100), `arm` 立柱到目标 (120), `post_dir` 立柱方向° 或 `center`, `fov` (仅显示) | target, post | 含环形光源, 立柱默认在目标外侧 |
| `spindle` 旋转/下压头 | `target`, `gap` (15), `z_stroke` (gap+10), `chuck_d` (20), `arm`, `post_dir` | target, post | 伺服 + 主轴 + Z 滑台, 用于旋转测量、拧紧 |
| `press` 压装 | `target`, `gap` (20), `bore` (50), `stroke`, `arm`, `post_dir` | target, post | 力大时报告提示改 C 型架/四柱 |
| `tool` 顶置工具 | `target`, `size` [x, y, z], `gap`, `arm`, `post_dir` | target, post | 点胶阀、扫码枪、打标头等 |
| `scara` SCARA 机器人 | `at` 底座, `targets` 工作点列表 (必填), `reach` (400) 或 `a1`/`a2`, `z_stroke` (150), `tool_len` (60), `clear` 抬起高度 (30), `elbow` right / left, `pose` 画在第几个目标 (1), `sweep` (true) | base, tool, T1…Tn | 校核每个目标是否在臂展内、Z 行程是否够; 运动包络 = 手臂整圈旋转 + 目标间工具路径 + 下降柱 |

### 供料与出料
| type | 参数 | 锚点 | 说明 |
|---|---|---|---|
| `magazine` 料管上料 | `product` (必填), `height` 推料面高 (100), `tube_h` (250), `tubes` 料管数 (1), `stroke` 推料行程 (产品外径+30), `bore` (10) | out (取料点), refill | 料管叠放 + 底部推片, 磁环类首选; `tubes` > 1 时料管沿局部 +Y 排列并带换管气缸; 容量 = 料管数 × 管高 / 产品厚 |
| `bowl_feeder` 振动盘 | `bowl_d` (300), `bowl_h` (120), `base_h` (150), `track_len` (250), `track_z`, `product` | out | 沿局部 +X 出料; 自动提示磁性件互吸风险 |
| `conveyor` 皮带线 | `length` (600), `width` 带宽 (100), `height` 输送面高 (80) | start, mid, end | 沿局部 +X 输送, 电机在 +Y 侧末端 |
| `chute` 滑道 | `from`, `to` (滑道底面), `width` (30), `wall_h` (15) | in, out | 倾角 < 15° 时提示 |
| `bin` 料盒 | `size` [宽, 深, 高] ([150, 120, 100]), `color` (红), `share` 流入本盒的产量比例 (1; NG 盒如 0.02) | top | OK 盒可设绿色; 有 `uph` + `product` 时计算倒料间隔 (堆积系数 0.4) |
| `tray` 料盘 | `size` [宽, 深, 高] ([300, 200, 20]) | center, corner | |
| `product` 产品 | `product` {shape: ring (od, id, h) / disc (d, h) / box (size)} | top | 也用于转盘、料管、振动盘的 `product` 参数 |

### 安全与人机
| type | 参数 | 说明 |
|---|---|---|
| `light_curtain` 安全光栅 | `span` (800), `height` (600), `z0` 下沿高度 (50), `min_distance` 安全距离 S | 沿局部 X 布置两根光栅, 保护区只在预览中显示; 报告到最近运动包络的水平距离, 给 `min_distance` (取 `mech_calc.py safety` 的 S) 时自动判 OK/NG |
| `hmi` 触摸屏 | `at` [x, y, z], `arm` (100) | 屏幕朝 −Y (操作者) |
| `tower_light` 三色灯 | `at` [x, y, z], `pole` (250) | 一般放在防护罩顶 |

Anything outside the library: build it from `box` and `cylinder` (they accept `rot` and 3D `at`).

## 6. 布局检查

| 检查 | 方法 | 处理 |
|---|---|---|
| 静态干涉 | 各零件按凸体 (圆柱按 16 棱柱) 做分离轴检测, 容差 `--tol` (0.5 mm) | 改位置/朝向/立柱方向; 设计上接触的加 `touch` |
| 运动干涉 | 运动包络 (预览中半透明橙色, "路径/包络" 按钮开关): 取放机构 X 扫掠 + 两端下降柱; 转盘治具和产品的旋转环带; 气缸推块/探头行程; 压头/旋转头下压行程; 模组 `payload` 行程; SCARA 手臂旋转与工具路径. 推块和压头碰到产品属于正常动作, 不报 | 抬高 `z_stroke`、换 `side`、移开障碍、缩小 `reach` 或关 `sweep` 后说明软限位 |
| 光栅距离 | 光栅平面到最近运动包络的水平距离 | 小于安全距离 S 时: 光栅外移、缩短停止时间、加护栏 |
| 遮挡光栅 | 任何零件伸进光栅保护区 (光栅会一直被触发) | 光栅外移或移开该零件 |
| 补料/倒料间隔 | 需要顶层 `uph`: 料管容量 ÷ UPH; 料盒 (另需 `product`) 可装数量 ÷ (UPH × share) | 小于 `refill_min`: 加长料管、增加 `tubes`、改料仓/振动盘、加大料盒 |
| 人工操作 | 补料口、料盒、料盘在防护罩内 (操作会触发停机); 距台面前沿 > 600 mm 或离地 > 1500 mm | 改外置抽屉/门外补料口, 或在风险表中说明停机损失 |
| 超出台面 | 组件包络超出 `frame` 台面 (机架、防护罩、光栅、触摸屏、三色灯除外) | 调整位置或加大台面 |
| 高于防护罩 | 组件顶部高于 `enclosure` | 加高防护罩或降低结构 |
| 组件提示 | 振动盘 + 磁性件、气缸取放 X 行程 > 300 mm、滑道倾角 < 15°、治具超出转盘、压装立柱刚性、光栅距离 | 按提示处理或在方案中说明 |

Not checked: cables and air hoses, maintenance access, linear modules without `payload`, the inside of hollow parts (a ring/tube is checked as a solid cylinder, so something inside a ring's hole is reported as a clash), and motion that is not in the library (e.g. flip/rotary cylinders built from `box`). Mention these in the risk table when relevant.

## 7. 布置技巧

- 转盘机: `start_angle: -90` 让 S1 在操作者正前方, 工位逆时针编号; 转盘略向后放 (`at: [0, 60]`) 给前侧上料留空间.
- 径向布置的推料/探头: `tip: {"ref": "tt.S2", "out": 产品半径, "up": -产品高/2}`, `toward: "tt.center"`.
- 表磁、外径检测: 治具 (芯轴) 直径要小于产品外径, 否则径向探头会碰治具.
- 推出式剔除: 推块高度要高于治具顶面, 用 `head_size` [长, 宽, 产品高] 做成薄推片; 推料气缸装在中心固定盘上 (`center_plate` + `support: none`).
- 取放机构: 立柱默认在离中心较远的一端、远离中心的一侧; 冲突时依次试 `post_side`、`post_at`、加大 `side`; 两个取放机构的 X 轴同高时注意交叉.
- 顶置设备 (相机/压头) 的立柱默认沿 "中心 → 目标" 方向向外; 同一工位有两个设备时, 用 `post_dir` 错开.
- 报告配图: 用 `--png` 自动出轴测 + 俯视图, 正文附图号表; 需要标签的截图在 HTML 预览中按 "截图".
- 料管/料盘类供料: 先按 `uph` 算补料间隔, 再定料管数和高度; 料管排在远离转盘的方向 (见磁环样例 `rot: 90`).
- 光栅装在机架前沿 (`at: [0, 台面前沿 y]`), 先确认没有零件伸进保护区, 再填 `min_distance`.

## 8. 限制

- 方块级概念模型: 不含螺丝、线缆、气管、钣金细节; 尺寸按典型比例生成, 只保证关键尺寸 (行程、高度、间距) 来自输入.
- 不能代替详细设计和强度/刚性校核; 选型仍以 `mech_calc.py` 和厂家样本为准.
