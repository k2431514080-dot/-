#!/usr/bin/env python3
"""自动化机构选型计算工具 (仅依赖 Python 标准库)

子命令
  cylinder  气缸: 缸径、推/拉力、负载率、耗气量、动能、动作时间
  vacuum    真空吸盘: 直径/数量、真空响应时间
  screw     滚珠丝杠模组 + 伺服电机
  belt      同步带模组 + 伺服电机
  rotary    伺服+减速机 / DD 马达转盘
  indexer   凸轮分割器
  guide     直线导轨额定寿命
  move      单段点到点运动时间 (梯形/三角速度)
  safety    安全光栅安全距离 (ISO 13855 / GB/T 19876)

用法: python3 mech_calc.py <子命令> -h
结果为方案阶段初选值, 定型前须用厂家样本复核。
--json 输出机器可读结果; --out 文件名 以 UTF-8 写入文件。
"""

import argparse
import json
import math
import sys

G = 9.80665
DENSITY = {"al": 2700.0, "steel": 7850.0, "sus": 7930.0, "pom": 1410.0}

CYL_BORES = [6, 8, 10, 12, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125, 160, 200]
# 活塞杆直径典型值 (>=32 按 ISO 15552, 小缸径按常见笔形/薄型缸), 以样本为准
CYL_RODS = {6: 3, 8: 4, 10: 4, 12: 6, 16: 6, 20: 8, 25: 10, 32: 12, 40: 16,
            50: 20, 63: 20, 80: 25, 100: 25, 125: 32, 160: 40, 200: 40}
CUP_SIZES = [2, 3.5, 4, 6, 8, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80]

# 通用中惯量伺服电机典型参数 (额定 3000 rpm, 最高 6000 rpm, 瞬时最大扭矩约 3 倍额定)
# (额定功率 W, 额定扭矩 N·m, 转子惯量 kg·cm²); 仅用于初选, 定型时用 --motor-* 按样本复核
SERVOS = [
    (50, 0.159, 0.040),
    (100, 0.318, 0.066),
    (200, 0.637, 0.26),
    (400, 1.27, 0.49),
    (750, 2.39, 1.6),
    (1000, 3.18, 2.0),
]
SERVO_PEAK = 3.0
SERVO_RATED_RPM = 3000
SERVO_MAX_RPM = 6000

# 丝杠危险转速支撑系数 λ (轴径单位 mm, 支撑间距 mm, 结果 rpm)
SCREW_SUPPORT = {"fixed-free": 3.4, "supported-supported": 9.7,
                 "fixed-supported": 15.1, "fixed-fixed": 21.9}
SCREW_ROOT_RATIO = 0.83  # 未给牙底径时按公称直径 x 0.83 近似


# ---------------------------------------------------------------- output

def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v == 0:
            return "0"
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:.4g}"
    return str(v)


class Report:
    def __init__(self, title):
        self.title = title
        self.inputs = []
        self.results = []
        self.tables = []
        self.checks = []
        self.notes = []

    def inp(self, name, value, unit=""):
        self.inputs.append((name, value, unit))

    def res(self, name, value, unit=""):
        self.results.append((name, value, unit))

    def table(self, caption, headers, rows):
        self.tables.append((caption, headers, rows))

    def check(self, level, msg):
        self.checks.append((level, msg))

    def note(self, msg):
        self.notes.append(msg)

    def markdown(self):
        out = [f"## {self.title}", ""]
        for caption, rows in (("输入条件", self.inputs), ("计算结果", self.results)):
            if rows:
                out += [f"**{caption}**", "", "| 项目 | 数值 | 单位 |", "|---|---:|---|"]
                out += [f"| {n} | {fmt(v)} | {u} |" for n, v, u in rows]
                out.append("")
        for caption, headers, rows in self.tables:
            out += [f"**{caption}**", "", "| " + " | ".join(headers) + " |",
                    "|" + "---|" * len(headers)]
            out += ["| " + " | ".join(fmt(c) for c in row) + " |" for row in rows]
            out.append("")
        if self.checks:
            out += ["**校核**", ""] + [f"- [{lv}] {m}" for lv, m in self.checks] + [""]
        if self.notes:
            out += ["**说明**", ""] + [f"- {m}" for m in self.notes] + [""]
        return "\n".join(out)

    def as_dict(self):
        row = lambda n, v, u: {"name": n, "value": v, "unit": u}
        return {
            "title": self.title,
            "inputs": [row(*x) for x in self.inputs],
            "results": [row(*x) for x in self.results],
            "tables": [{"caption": c, "headers": h, "rows": r} for c, h, r in self.tables],
            "checks": [{"level": lv, "message": m} for lv, m in self.checks],
            "notes": self.notes,
        }


# ---------------------------------------------------------------- motion helpers

def _shape(name):
    """各运动曲线的加速度形状 A(τ), τ∈[0,1], 未归一化."""
    if name == "tri":
        return lambda t: 1.0 if t < 0.5 else -1.0
    if name == "trap":
        return lambda t: 1.0 if t < 1 / 3 else (0.0 if t < 2 / 3 else -1.0)
    if name == "cyc":
        return lambda t: math.sin(2 * math.pi * t)
    if name == "ms":
        def ms(t):
            if t < 1 / 8 or t >= 7 / 8:
                return math.sin(4 * math.pi * t)
            return math.cos(4 * math.pi / 3 * (t - 1 / 8))
        return ms
    if name == "mt":
        def mt(t):
            if t < 1 / 8 or t >= 7 / 8:
                return math.sin(4 * math.pi * t)
            if t < 3 / 8:
                return 1.0
            if t < 5 / 8:
                return math.cos(4 * math.pi * (t - 3 / 8))
            return -1.0
        return mt
    raise ValueError(name)


PROFILE_NAMES = {
    "ms": "修正正弦 MS",
    "mt": "修正梯形 MT",
    "cyc": "摆线 Cycloid",
    "trap": "梯形速度 (1/3 加速-1/3 匀速-1/3 减速)",
    "tri": "三角速度 (1/2 加速-1/2 减速)",
}
_PROFILE_CACHE = {}


def profile(name, n=4000):
    """数值积分得到无量纲特性值: 位移归一化为 1, 时间归一化为 1.

    Vm: 最大速度系数, Am: 最大加速度系数, AVm: max(A·V);
    A/V: 按峰值归一化后的加速度/速度形状 (用于 RMS 与输入扭矩计算).
    """
    if name in _PROFILE_CACHE:
        return _PROFILE_CACHE[name]
    f = _shape(name)
    dt = 1.0 / n
    acc = [f((k + 0.5) * dt) for k in range(n)]
    vel, v, s = [], 0.0, 0.0
    for x in acc:
        v_next = v + x * dt
        vel.append((v + v_next) / 2)
        s += (v + v_next) / 2 * dt
        v = v_next
    acc = [x / s for x in acc]
    vel = [x / s for x in vel]
    am = max(abs(x) for x in acc)
    vm = max(vel)
    avm = max(x * y for x, y in zip(acc, vel))
    p = {"name": PROFILE_NAMES[name], "Am": am, "Vm": vm, "AVm": avm,
         "A": [x / am for x in acc], "V": [x / vm for x in vel]}
    _PROFILE_CACHE[name] = p
    return p


def trapezoid(dist, vmax, t_acc):
    """点到点运动, 加减速时间相同. 返回 (加速时间, 匀速时间, 峰值速度)."""
    acc = vmax / t_acc
    if dist >= vmax * t_acc:
        return t_acc, (dist - vmax * t_acc) / vmax, vmax
    v_pk = math.sqrt(dist * acc)
    return v_pk / acc, 0.0, v_pk


# ---------------------------------------------------------------- servo selection

def servo_candidates(a):
    if a.motor_rated_torque or a.motor_inertia:
        if not (a.motor_rated_torque and a.motor_inertia):
            sys.exit("指定电机时需同时给出 --motor-rated-torque 和 --motor-inertia")
        tmax = a.motor_max_torque or a.motor_rated_torque * SERVO_PEAK
        return [("指定电机", a.motor_rated_torque, a.motor_inertia, tmax,
                 a.motor_rated_speed, a.motor_max_speed)]
    return [(f"{w} W", t, j, t * SERVO_PEAK, SERVO_RATED_RPM, SERVO_MAX_RPM)
            for w, t, j in SERVOS]


def select_servo(r, a, J_L, n_motor, torque_fn):
    """逐个校核候选电机. torque_fn(J_M[kg·m²]) -> (峰值扭矩, 连续扭矩, 连续扭矩是否为RMS)."""
    rows, chosen, is_rms = [], None, False
    for name, rated, jm, tmax, n_rated, n_max in servo_candidates(a):
        t_pk, t_cont, is_rms = torque_fn(jm * 1e-4)
        ratio = J_L / (jm * 1e-4)
        fails = []
        if t_cont * a.sf > rated:
            fails.append("连续扭矩")
        if t_pk > 0.8 * tmax:
            fails.append("峰值扭矩")
        if n_motor > n_max:
            fails.append("转速")
        if ratio > a.inertia_limit:
            fails.append("惯量比")
        rows.append([name, rated, jm, ratio, t_pk, t_cont,
                     "OK" if not fails else "NG: " + "、".join(fails)])
        if not fails and chosen is None:
            chosen = (name, rated, ratio, t_pk, t_cont, n_rated)
    r.table("伺服电机校核 (判据: 连续扭矩×安全系数 ≤ 额定, 峰值 ≤ 0.8×最大扭矩, "
            f"转速 ≤ 最高转速, 惯量比 ≤ {a.inertia_limit:g})",
            ["电机", "额定扭矩 N·m", "转子惯量 kg·cm²", "惯量比",
             "峰值扭矩 N·m", "RMS扭矩 N·m" if is_rms else "恒速扭矩 N·m", "结论"], rows)
    if chosen:
        name, rated, ratio, t_pk, t_cont, n_rated = chosen
        r.check("OK", f"初选 {name} 伺服: 峰值 {fmt(t_pk)} N·m, "
                      f"{'RMS' if is_rms else '恒速'} {fmt(t_cont)} N·m, 惯量比 {fmt(ratio)}")
        if n_motor > n_rated:
            r.check("注意", f"电机转速 {fmt(n_motor)} rpm 高于额定 {n_rated} rpm, "
                          "需按样本 T-N 曲线核对高速区扭矩")
    else:
        r.check("NG", "候选电机均不满足. 可选: 增大减速比/改变导程以降低惯量比和扭矩, "
                      "延长加速时间, 或选更大功率/高惯量电机后用 --motor-* 复核")
    if not is_rms:
        r.note("未给 --stroke/--cycle-time, 连续扭矩按恒速负载扭矩估算, 未计启停占空比; "
               "频繁启停时请补充行程或节拍以计算 RMS 扭矩")
    r.note("电机参数为通用中惯量系列典型值, 仅用于定功率等级; 定型时按选定品牌样本用 "
           "--motor-rated-torque/--motor-inertia 复核")


def add_motor_args(p, inertia_limit=10.0):
    g = p.add_argument_group("电机校核")
    g.add_argument("--sf", type=float, default=1.5, help="连续扭矩安全系数 (默认 1.5)")
    g.add_argument("--inertia-limit", type=float, default=inertia_limit,
                   help=f"允许惯量比 (默认 {inertia_limit:g}; 高响应取 5)")
    g.add_argument("--motor-rated-torque", type=pos, help="指定电机额定扭矩 N·m")
    g.add_argument("--motor-inertia", type=pos, help="指定电机转子惯量 kg·cm² (=×10⁻⁴ kg·m²)")
    g.add_argument("--motor-max-torque", type=float, help="指定电机瞬时最大扭矩 N·m (默认 3×额定)")
    g.add_argument("--motor-rated-speed", type=float, default=SERVO_RATED_RPM, help="额定转速 rpm")
    g.add_argument("--motor-max-speed", type=float, default=SERVO_MAX_RPM, help="最高转速 rpm")


# ---------------------------------------------------------------- cylinder

def cmd_cylinder(a):
    r = Report("气缸选型")
    if a.mode == "clamp" and a.force is None:
        sys.exit("clamp 模式需给出 --force (所需夹紧/压装力 N)")
    if a.mode != "clamp" and a.mass is None and a.force is None:
        sys.exit("需给出 --mass 或 --force")
    m = a.mass or 0.0
    ext = a.force or 0.0
    P = a.pressure

    r.inp("工况", {"horizontal": "水平推送", "vertical": "垂直举升", "clamp": "夹紧/压装 (静负载)"}[a.mode])
    if a.mass is not None:
        r.inp("负载质量", m, "kg")
    if a.force is not None:
        r.inp("外力/所需夹紧力", ext, "N")
    r.inp("设计压力", P, "MPa")
    r.inp("出力方向", "推 (伸出)" if a.direction == "push" else "拉 (缩回)")

    if a.mode == "horizontal":
        F = a.mu * m * G + ext
        r.inp("摩擦系数 μ", a.mu)
    elif a.mode == "vertical":
        F = m * G + ext
    else:
        F = ext

    if a.load_ratio:
        eta = a.load_ratio
    elif a.mode == "clamp":
        eta = 0.7
    elif a.speed and a.speed > 500:
        eta = 0.3
    elif a.speed and a.speed < 100:
        eta = 0.65
    else:
        eta = 0.5
    F_req = F / eta
    d_min = math.sqrt(4 * F_req / (math.pi * P))

    bore = None
    for D in CYL_BORES:
        d = CYL_RODS[D]
        area = math.pi / 4 * (D * D if a.direction == "push" else D * D - d * d)
        if P * area >= F_req:
            bore = D
            break

    r.res("负载力", F, "N")
    r.res("负载率 η", eta)
    r.res("所需理论出力 F/η", F_req, "N")
    r.res("理论最小缸径 (按推力)", d_min, "mm")
    if bore is None:
        r.check("NG", "所需出力超出 Φ200 气缸, 考虑气液增压缸、伺服电缸或增力机构 (肘节/杠杆)")
        return r
    d = CYL_RODS[bore]
    f_push = P * math.pi / 4 * bore ** 2
    f_pull = P * math.pi / 4 * (bore ** 2 - d ** 2)
    f_out = f_push if a.direction == "push" else f_pull
    r.res("推荐标准缸径", bore, "mm")
    r.res("活塞杆直径 (典型)", d, "mm")
    r.res("推力 @设计压力", f_push, "N")
    r.res("拉力 @设计压力", f_pull, "N")
    r.res("实际负载率", F / f_out if f_out else 0.0)
    r.check("OK", f"Φ{bore} 气缸在 {P:g} MPa 下{'推' if a.direction == 'push' else '拉'}力 "
                  f"{fmt(f_out)} N ≥ 所需 {fmt(F_req)} N")

    if a.stroke:
        v_cycle = math.pi / 4 * (bore ** 2 + bore ** 2 - d ** 2) * a.stroke \
            * (P + 0.1013) / 0.1013 * 1e-6
        r.res("单次往返耗气量 (ANR)", v_cycle, "L")
        if a.cycles:
            r.res("耗气量 (ANR)", v_cycle * a.cycles, "L/min")
        r.note("耗气量未含管路容积, 管路较长时另加 10%~30%")
    if a.speed and a.mass:
        v_imp = 1.4 * a.speed / 1000
        r.res("撞击速度估算 (1.4×平均速度)", v_imp * 1000, "mm/s")
        r.res("撞击动能", 0.5 * m * v_imp ** 2, "J")
        r.note("撞击动能须 ≤ 样本允许动能 (橡胶缓冲 < 气缓冲 < 液压缓冲器), 超出时加液压缓冲器或降速")
    if a.stroke and a.speed:
        r.res("单程动作时间估算", 0.03 + a.stroke / a.speed + 0.02, "s")
        r.note("动作时间 = 阀响应约 0.03 s + 行程/平均速度 + 到位确认约 0.02 s, 调试后以实测为准")

    if a.mode == "vertical":
        r.check("注意", "垂直负载: 断气/急停时须防下落 (先导式单向阀、锁紧气缸或弹簧), "
                      "下降方向用排气节流控制速度")
    if a.mode == "horizontal" and m > 0:
        r.check("注意", "活塞杆不宜承受横向负载/偏载: 用导杆气缸、滑台气缸或外置直线导轨")
    if a.mode == "clamp":
        r.check("注意", "夹紧力应指向定位基准面; 断气时夹紧保持方式需明确 (单向阀/弹簧/肘节自锁)")
    r.note("负载率经验值: 静负载 ≤0.7; 动负载 v<100 mm/s ≤0.65, 100~500 mm/s ≤0.5, >500 mm/s ≤0.3")
    r.note("设计压力建议取 0.4 MPa (供气 0.5~0.6 MPa), 为管路压降和气源波动留余量")
    return r


# ---------------------------------------------------------------- vacuum

def cmd_vacuum(a):
    r = Report("真空吸盘选型")
    sf = a.safety or (4.0 if a.mode == "horizontal" else 8.0)
    p = abs(a.vacuum)
    r.inp("工件质量", a.mass, "kg")
    r.inp("吸附方式", "水平吸吊 (吸盘朝下)" if a.mode == "horizontal" else "垂直吸吊 (侧吸, 剪切方向受力)")
    r.inp("真空度", -p, "kPa")
    r.inp("吸盘数量", a.cups, "个")
    r.inp("搬运加速度", a.accel, "m/s²")
    r.inp("安全系数", sf)

    W = a.mass * (G + a.accel) * sf
    area = W / (p * 0.001 * a.cups)
    d_min = math.sqrt(4 * area / math.pi)
    cup = next((c for c in CUP_SIZES if c >= d_min), None)
    r.res("所需理论吸力 (合计)", W, "N")
    r.res("单个吸盘最小直径", d_min, "mm")
    if cup is None:
        r.check("NG", "超出 Φ80 吸盘范围, 增加吸盘数量或改用夹爪")
        return r
    f_each = p * 0.001 * math.pi / 4 * cup ** 2
    r.res("推荐吸盘直径", cup, "mm")
    r.res("单个吸盘理论吸力", f_each, "N")
    r.res("实际安全系数", f_each * a.cups / (a.mass * (G + a.accel)))

    if a.max_cup:
        r.inp("工件可用吸附平面宽度", a.max_cup, "mm")
        if cup > a.max_cup:
            f_max = p * 0.001 * math.pi / 4 * a.max_cup ** 2
            need = math.ceil(W / f_max)
            r.check("NG", f"推荐吸盘 Φ{cup:g} 大于可用平面 {a.max_cup:g} mm; 若用 Φ{a.max_cup:g} 需 "
                          f"{need} 个, 或提高真空度, 或改用夹爪/内撑")
        else:
            r.check("OK", f"吸盘 Φ{cup:g} ≤ 可用吸附平面 {a.max_cup:g} mm")

    if a.tube_id and a.tube_len and a.flow:
        vol = math.pi / 4 * a.tube_id ** 2 * a.tube_len * 1e-6 * a.cups
        t1 = vol * 60 / a.flow
        r.res("吸附侧管路容积", vol, "L")
        r.res("真空到达 63% 时间", t1, "s")
        r.res("真空到达 95% 时间", 3 * t1, "s")
        r.note("响应时间按 T1 = V×60/Q 估算 (Q 为真空发生器平均吸入流量 L/min ANR), "
               "发生器尽量靠近吸盘以缩短管路")

    r.check("注意", "必须用真空压力开关做吸附确认和掉件检测; 断电/断气时工件会掉落, 需评估是否可接受")
    r.note("安全系数: 水平吸吊 ≥4, 垂直吸吊 ≥8; 高速搬运时输入 --accel 或加大安全系数")
    r.note("透气/粗糙/曲面工件需实测泄漏并选大流量发生器或波纹吸盘; 带中孔的环形件吸盘须落在环面上, "
           "否则用内撑或气爪")
    return r


# ---------------------------------------------------------------- linear axes

def add_linear_args(p):
    p.add_argument("--mass", type=pos, required=True, help="移动部分总质量 kg (滑台+治具+产品)")
    p.add_argument("--speed", type=pos, required=True, help="最高速度 mm/s")
    p.add_argument("--accel-time", type=pos, default=0.1, help="加速时间 s (默认 0.1, 减速相同)")
    p.add_argument("--stroke", type=pos, help="单程行程 mm (给出则计算动作时间和 RMS 扭矩)")
    p.add_argument("--dwell", type=float, default=0.2, help="每个单程后的停留时间 s (默认 0.2)")
    p.add_argument("--angle", type=float, default=0.0, help="安装倾角 °, 0=水平, 90=垂直")
    p.add_argument("--vertical", action="store_true", help="垂直安装 (等同 --angle 90)")
    p.add_argument("--mu", type=float, default=0.01, help="导轨摩擦系数 (直线导轨 0.003~0.01, 默认 0.01)")
    p.add_argument("--force", type=float, default=0.0, help="运动方向外力 N (如压装力, 按全程作用保守计算)")
    p.add_argument("--ratio", type=pos, default=1.0, help="电机到驱动轴减速比 (默认 1 直连)")
    p.add_argument("--ratio-eff", type=pos, default=0.95, help="减速机构效率 (默认 0.95)")
    p.add_argument("--coupling-inertia", type=float, default=0.0, help="联轴器等电机侧惯量 kg·cm²")


def linear_common(r, a, kind):
    if a.vertical:
        a.angle = 90.0
    th = math.radians(a.angle)
    r.inp("移动质量", a.mass, "kg")
    r.inp("最高速度", a.speed, "mm/s")
    r.inp("加速时间", a.accel_time, "s")
    r.inp("安装倾角", a.angle, "°")
    if a.force:
        r.inp("外力", a.force, "N")
    if a.ratio != 1:
        r.inp("减速比", a.ratio)
    v = a.speed / 1000
    acc = v / a.accel_time
    if a.stroke:
        r.inp("单程行程", a.stroke, "mm")
        t_a, t_c, v_pk = trapezoid(a.stroke / 1000, v, a.accel_time)
    else:
        t_a, t_c, v_pk = a.accel_time, None, v
    F = a.mass * G * (a.mu * math.cos(th) + math.sin(th)) + a.force
    F_hold = a.mass * G * math.sin(th)
    return th, acc, t_a, t_c, v_pk, F, F_hold


def linear_motor(r, a, J_L, T_L, T_hold, alpha, n_motor, t_a, t_c, eta):
    def torque_fn(jm):
        t_acc = (jm + J_L / eta) * alpha
        t1 = t_acc + T_L
        if t_c is None:
            return t1, T_L, False
        t3 = abs(T_L - t_acc)
        num = t1 ** 2 * t_a + T_L ** 2 * t_c + t3 ** 2 * t_a + T_hold ** 2 * a.dwell
        return t1, math.sqrt(num / (2 * t_a + t_c + a.dwell)), True

    select_servo(r, a, J_L, n_motor, torque_fn)
    if t_c is not None:
        r.note("RMS 扭矩按 加速-匀速-减速-停留 单程循环计算, 垂直轴按上行工况近似")


def linear_checks(r, a, acc, F_hold, T_hold, kind):
    if acc > 0.5 * G:
        r.check("注意", f"加速度 {fmt(acc / G)} G 偏大, 核对负载固定、悬臂力矩和导轨静力矩")
    if a.angle >= 45:
        r.check("注意", f"垂直/倾斜轴: 电机须带抱闸, 抱闸扭矩建议 ≥ 2×保持扭矩 ({fmt(2 * T_hold)} N·m)")
        if kind == "belt":
            r.check("注意", "同步带垂直轴存在断带坠落风险: 加防坠/配重, 或改用丝杠模组")


def cmd_screw(a):
    r = Report("滚珠丝杠模组 + 伺服电机初选")
    th, acc, t_a, t_c, v_pk, F, F_hold = linear_common(r, a, "screw")
    r.inp("丝杠导程", a.lead, "mm")
    r.inp("丝杠公称直径", a.screw_dia, "mm")
    lead = a.lead / 1000
    i = a.ratio
    eta = a.eff * (a.ratio_eff if i != 1 else 1.0)
    Ls = a.screw_length or ((a.stroke or 300) + 150)
    r.inp("丝杠长度/支撑间距", Ls, "mm")
    r.inp("支撑方式", a.support)

    r.inp("丝杠预压/密封拖动扭矩", a.drag_torque, "N·m")
    n_screw = v_pk / lead * 60
    n_motor = n_screw * i
    T_L = F * lead / (2 * math.pi * eta * i) + a.drag_torque / i
    T_hold = F_hold * lead / (2 * math.pi * eta * i)
    d = a.screw_dia / 1000
    J_screw = math.pi * DENSITY["steel"] * (Ls / 1000) * d ** 4 / 32
    J_lin = a.mass * (lead / (2 * math.pi)) ** 2
    J_L = (J_screw + J_lin) / i ** 2 + a.coupling_inertia * 1e-4
    alpha = 2 * math.pi * i * acc / lead

    r.res("丝杠最高转速", n_screw, "rpm")
    r.res("电机最高转速", n_motor, "rpm")
    r.res("加速度", acc, "m/s²")
    r.res("恒速轴向负载", F, "N")
    r.res("加速时轴向负载", F + a.mass * acc, "N")
    r.res("恒速负载扭矩 (电机侧)", T_L, "N·m")
    r.res("丝杠惯量", J_screw * 1e4, "kg·cm²")
    r.res("移动质量换算惯量", J_lin * 1e4, "kg·cm²")
    r.res("负载总惯量 (电机侧)", J_L * 1e4, "kg·cm²")
    if t_c is not None:
        r.res("单程时间 (加速+匀速+减速)", 2 * t_a + t_c, "s")
        if t_c == 0:
            r.check("注意", f"行程短, 为三角速度, 实际峰值速度仅 {fmt(v_pk * 1000)} mm/s")

    dr = a.root_dia or SCREW_ROOT_RATIO * a.screw_dia
    Nc = SCREW_SUPPORT[a.support] * dr / Ls ** 2 * 1e7 * 0.8
    dn = a.screw_dia * n_screw
    r.res("危险转速许用值 (×0.8)", Nc, "rpm")
    r.res("DN 值 (公称直径×转速)", dn)
    if n_screw <= Nc:
        r.check("OK", f"丝杠转速 {fmt(n_screw)} rpm ≤ 危险转速许用值 {fmt(Nc)} rpm")
    else:
        r.check("NG", "超过危险转速: 加大丝杠直径/导程, 缩短支撑间距, 或改固定-固定支撑")
    if dn > 70000:
        r.check("注意", f"DN 值 {fmt(dn)} > 70,000 (常用参考上限), 核对样本允许 DN 值或加大导程")
    linear_checks(r, a, acc, F_hold, T_hold, "screw")
    linear_motor(r, a, J_L, T_L, T_hold, alpha, n_motor, t_a, t_c, eta)
    if not a.root_dia:
        r.note(f"危险转速用牙底径 ≈ {SCREW_ROOT_RATIO}×公称直径近似, 可用 --root-dia 输入样本值")
    r.note("未校核屈曲载荷和额定寿命; 推力大 (压装) 或长行程时按样本补充校核")
    return r


def cmd_belt(a):
    r = Report("同步带模组 + 伺服电机初选")
    th, acc, t_a, t_c, v_pk, F, F_hold = linear_common(r, a, "belt")
    if a.pulley_dia:
        D = a.pulley_dia
    elif a.teeth and a.pitch:
        D = a.teeth * a.pitch / math.pi
    else:
        sys.exit("需给出 --pulley-dia 或 --teeth 与 --pitch")
    r.inp("带轮节圆直径", D, "mm")
    r.inp("同步带质量", a.belt_mass, "kg")
    rp = D / 2000
    i = a.ratio
    eta = a.eff * (a.ratio_eff if i != 1 else 1.0)
    m_move = a.mass + a.belt_mass

    n_pulley = v_pk / (math.pi * D / 1000) * 60
    n_motor = n_pulley * i
    T_L = F * rp / (eta * i)
    T_hold = F_hold * rp / (eta * i)
    if a.pulley_inertia is not None:
        J_pulley = a.pulley_inertia * 1e-4
    else:
        J_pulley = 2 * 0.5 * DENSITY["al"] * math.pi * rp ** 4 * (a.pulley_width / 1000)
    J_lin = m_move * rp ** 2
    J_L = (J_lin + J_pulley) / i ** 2 + a.coupling_inertia * 1e-4
    alpha = acc / rp * i

    r.res("每转移动量", math.pi * D, "mm/rev")
    r.res("带轮最高转速", n_pulley, "rpm")
    r.res("电机最高转速", n_motor, "rpm")
    r.res("加速度", acc, "m/s²")
    r.res("恒速负载力", F, "N")
    r.res("有效张力 (加速时)", F + m_move * acc, "N")
    r.res("恒速负载扭矩 (电机侧)", T_L, "N·m")
    r.res("带轮惯量 (2 个)", J_pulley * 1e4, "kg·cm²")
    r.res("移动质量换算惯量", J_lin * 1e4, "kg·cm²")
    r.res("负载总惯量 (电机侧)", J_L * 1e4, "kg·cm²")
    if t_c is not None:
        r.res("单程时间 (加速+匀速+减速)", 2 * t_a + t_c, "s")
        if t_c == 0:
            r.check("注意", f"行程短, 为三角速度, 实际峰值速度仅 {fmt(v_pk * 1000)} mm/s")
    r.check("注意", f"有效张力 {fmt(F + m_move * acc)} N 须 ≤ 所选带型/带宽的许用张力 (查样本)")
    linear_checks(r, a, acc, F_hold, T_hold, "belt")
    linear_motor(r, a, J_L, T_L, T_hold, alpha, n_motor, t_a, t_c, eta)
    if a.pulley_inertia is None:
        r.note(f"带轮惯量按 2 个铝合金实心轮 (宽 {a.pulley_width:g} mm) 估算, 可用 --pulley-inertia 输入样本值")
    if i == 1 and J_L / (SERVOS[2][2] * 1e-4) > 10:
        r.note("同步带模组惯量比常偏大, 可加 1:3~1:5 行星减速机降低惯量比")
    return r


# ---------------------------------------------------------------- rotary tables

def add_table_args(p):
    g = p.add_argument_group("转盘与治具 (用于计算惯量)")
    g.add_argument("--table-dia", type=pos, help="转盘直径 mm")
    g.add_argument("--table-thk", type=pos, help="转盘厚度 mm")
    g.add_argument("--material", choices=sorted(DENSITY), default="al", help="转盘材料 (默认 al)")
    g.add_argument("--table-mass", type=float, help="转盘质量 kg (给出则不按尺寸计算)")
    g.add_argument("--fixture-mass", type=float, default=0.0, help="单个治具(含产品)质量 kg")
    g.add_argument("--fixtures", type=pos_int, help="治具数量 (默认 = 工位数)")
    g.add_argument("--fixture-radius", type=pos, help="治具重心回转半径 mm (默认 0.8×转盘半径)")
    g.add_argument("--extra-inertia", type=float, default=0.0, help="其他附加惯量 kg·cm²")
    g.add_argument("--friction-torque", type=float, default=0.0, help="输出侧摩擦扭矩 N·m")
    g.add_argument("--work-torque", type=float, default=0.0, help="分度过程中的作业扭矩 N·m")


def table_inertia(r, a, stations):
    J = 0.0
    R_fix = None
    if a.table_mass or (a.table_dia and a.table_thk):
        if not a.table_dia:
            sys.exit("需给出 --table-dia")
        m_t = a.table_mass or DENSITY[a.material] * math.pi * (a.table_dia / 2000) ** 2 * a.table_thk / 1000
        J_t = 0.5 * m_t * (a.table_dia / 2000) ** 2
        r.inp("转盘直径", a.table_dia, "mm")
        if not a.table_mass:
            r.inp("转盘厚度/材料", f"{a.table_thk:g} mm / {a.material}")
        r.res("转盘质量", m_t, "kg")
        r.res("转盘惯量", J_t * 1e4, "kg·cm²")
        J += J_t
    if a.fixture_mass:
        n = a.fixtures or stations
        R_fix = a.fixture_radius or (0.8 * a.table_dia / 2 if a.table_dia else None)
        if not R_fix:
            sys.exit("需给出 --fixture-radius")
        J_f = n * a.fixture_mass * (R_fix / 1000) ** 2
        r.inp("治具数量 × 质量", f"{n} × {a.fixture_mass:g} kg")
        r.inp("治具回转半径", R_fix, "mm")
        r.res("治具惯量 (按质点)", J_f * 1e4, "kg·cm²")
        J += J_f
    if a.extra_inertia:
        r.inp("附加惯量", a.extra_inertia, "kg·cm²")
        J += a.extra_inertia * 1e-4
    if J <= 0:
        sys.exit("需给出转盘尺寸/质量、治具参数或 --extra-inertia")
    r.res("输出轴总惯量", J * 1e4, "kg·cm²")
    if R_fix is None and a.table_dia:
        R_fix = a.table_dia / 2
    return J, R_fix


def accuracy_checks(r, R, backlash_arcmin=None, accuracy_arcsec=None):
    if not R:
        return
    if backlash_arcmin:
        r.res(f"回程间隙引起的位置误差 @R{R:g}", R * math.radians(backlash_arcmin / 60), "mm")
    if accuracy_arcsec:
        r.res(f"分度精度对应位置误差 @R{R:g}", R * math.radians(accuracy_arcsec / 3600), "mm")


def cmd_rotary(a):
    r = Report("伺服/DD 转盘初选")
    if not (a.stations or a.angle):
        sys.exit("需给出 --stations 或 --angle")
    theta = 2 * math.pi / a.stations if a.stations else math.radians(a.angle)
    p = profile(a.profile)
    if a.stations:
        r.inp("分度数", a.stations)
    r.inp("单次分度角", math.degrees(theta), "°")
    r.inp("分度时间", a.index_time, "s")
    r.inp("运动曲线", p["name"])
    J, R = table_inertia(r, a, a.stations or 1)

    t = a.index_time
    alpha = p["Am"] * theta / t ** 2
    omega = p["Vm"] * theta / t
    Tc = a.friction_torque + a.work_torque
    i = a.ratio
    eta = a.ratio_eff if i != 1 else 1.0
    duty = math.sqrt(t / a.cycle_time) if a.cycle_time else 1.0

    def stats(ka, kc):
        vals = [ka * x + kc for x in p["A"]]
        return max(abs(v) for v in vals), math.sqrt(sum(v * v for v in vals) / len(vals))

    t_pk_out, t_rms_out = stats(J * alpha, Tc)
    r.res("最大角速度 (输出)", omega * 60 / (2 * math.pi), "rpm")
    r.res("最大角加速度 (输出)", alpha, "rad/s²")
    r.res("输出侧峰值扭矩", t_pk_out, "N·m")
    r.res("输出侧 RMS 扭矩" + (" (整周期)" if a.cycle_time else " (连续分度)"), t_rms_out * duty, "N·m")
    accuracy_checks(r, R, a.backlash_arcmin, a.accuracy_arcsec)

    if i == 1 and not a.motor_rated_torque:
        r.inp("驱动", "DD 马达直驱")
        r.check("注意", f"DD 马达按样本选型: 最大扭矩 ≥ {fmt(t_pk_out / 0.8)} N·m, 额定扭矩 ≥ "
                      f"{fmt(t_rms_out * duty * a.sf)} N·m, 最高转速 ≥ {fmt(omega * 60 / (2 * math.pi))} rpm, "
                      f"允许负载惯量 ≥ {fmt(J * 1e4)} kg·cm²; 用 --motor-* 复核具体型号")
    else:
        r.inp("驱动", f"伺服 + 减速机 i={i:g}" if i != 1 else "指定电机直驱")
        n_motor = omega * i * 60 / (2 * math.pi)
        J_L = J / i ** 2
        r.res("电机最高转速", n_motor, "rpm")
        r.res("负载惯量 (电机侧)", J_L * 1e4, "kg·cm²")

        def torque_fn(jm):
            pk, rms = stats(jm * alpha * i + J * alpha / (i * eta), Tc / (i * eta))
            return pk, rms * duty, True
        select_servo(r, a, J_L, n_motor, torque_fn)
        if i != 1:
            r.check("注意", "减速机输出扭矩须 ≥ 输出侧峰值扭矩, 并核对急停扭矩和允许径向/轴向负载")
            r.note("伺服+减速机转盘的定位精度受回程间隙影响, 精定位工位建议加定位销或选 DD/凸轮分割器")
    if not a.cycle_time:
        r.note("未给 --cycle-time, RMS 按连续分度计算 (偏保守)")
    r.note("转盘按实心圆盘、治具按质点计算惯量; 中心孔/减重孔会降低惯量, 偏保守")
    return r


def cmd_indexer(a):
    r = Report("凸轮分割器初选")
    S = a.stations
    if a.cycle_time:
        T = a.cycle_time
    elif a.input_rpm:
        T = 60 / a.input_rpm
    else:
        sys.exit("需给出 --cycle-time 或 --input-rpm")
    p = profile(a.profile)
    r.inp("分度数 S", S)
    r.inp("节拍 (输入轴一转)", T, "s")
    r.inp("分度角 θh", a.index_angle, "°")
    r.inp("凸轮曲线", p["name"])
    r.inp("负载系数 fc", a.fc)
    J, R = table_inertia(r, a, S)

    def calc(theta_h):
        th = T * theta_h / 360
        alpha = p["Am"] * (2 * math.pi / S) / th ** 2
        Ti = J * alpha
        Tw = a.friction_torque + a.work_torque
        Te = (Ti + Tw) * a.fc
        Tin = 360 / (S * theta_h) * (p["AVm"] / p["Am"] * Ti + p["Vm"] * Tw) * a.fc
        return th, T - th, alpha, Ti, Te, Tin

    th, t_dw, alpha, Ti, Te, Tin = calc(a.index_angle)
    n_in = 60 / T
    P_kw = Tin * n_in / 9550 / a.drive_eff
    r.res("输入轴转速", n_in, "rpm")
    r.res("分度时间 th", th, "s")
    r.res("停留时间 (工位作业窗口)", t_dw, "s")
    r.res("输出最大角加速度", alpha, "rad/s²")
    r.res("惯性扭矩 Ti", Ti, "N·m")
    r.res("输出轴所需扭矩 Te", Te, "N·m")
    r.res("输入轴所需扭矩 Tc", Tin, "N·m")
    r.res(f"所需电机功率 (传动效率 {a.drive_eff:g})", P_kw * 1000, "W")
    accuracy_checks(r, R, None, a.accuracy_arcsec)

    rows = []
    for ang in (90, 120, 150, 180, 210, 240, 270):
        c = calc(ang)
        rows.append([ang, c[0], c[1], c[2], c[4], c[5]])
    r.table("分度角对比 (分度角越大越平稳, 但停留时间越短)",
            ["θh °", "分度时间 s", "停留时间 s", "角加速度 rad/s²", "输出扭矩 Te N·m", "输入扭矩 Tc N·m"], rows)

    r.check("注意", f"各工位作业 (含气缸往返和到位确认) 须在停留时间 {fmt(t_dw)} s 内完成, "
                  "否则加大节拍或减小分度角")
    r.check("注意", f"按样本在输入转速 {fmt(n_in)} rpm 下选 输出额定扭矩 ≥ {fmt(Te)} N·m 的型号, "
                  "并核对输出法兰允许轴向/径向负载与倾覆力矩")
    r.note("输入扭矩 Tc = 360/(S·θh) × [ (AVm/Am)·Ti + Vm·(Tf+Tw) ] × fc, 运动曲线系数: "
           f"Vm={p['Vm']:.2f}, Am={p['Am']:.2f}, AVm/Am={p['AVm'] / p['Am']:.2f}")
    r.note("负载系数 fc 经验值: 平稳无冲击 1.0~1.5, 中等冲击/频繁启停 1.5~2.0, 重冲击 2.0~3.0")
    r.note("急停时凸轮分割器靠电机刹车停止, 输入侧建议配刹车电机或扭矩限制器保护")
    return r


# ---------------------------------------------------------------- guide / move / safety

def cmd_guide(a):
    r = Report("直线导轨额定寿命")
    ball = a.type == "ball"
    pw, base = (3.0, 50.0) if ball else (10 / 3, 100.0)
    r.inp("类型", "滚珠" if ball else "滚柱")
    r.inp("基本额定动负荷 C", a.C, "kN")
    r.inp("单滑块等效负荷 P", a.load, "N")
    r.inp("负荷系数 fw", a.fw)
    L = (a.C * 1000 / (a.fw * a.load)) ** pw * base
    r.res("额定寿命", L, "km")
    if a.stroke and a.cycles:
        hours = L * 1e6 / (2 * a.stroke * a.cycles * 60)
        years = hours / (a.hours_per_day * a.days_per_year)
        r.inp("行程 × 往返频率", f"{a.stroke:g} mm × {a.cycles:g} 次/min")
        r.res("寿命时间", hours, "h")
        r.res(f"寿命年限 ({a.hours_per_day:g} h/天, {a.days_per_year:g} 天/年)", years, "年")
        r.check("OK" if years >= a.target_years else "注意",
                f"寿命 {fmt(years)} 年 {'≥' if years >= a.target_years else '<'} 目标 {a.target_years:g} 年")
    if a.C0:
        fs = a.C0 * 1000 / (a.max_load or a.load)
        r.res("静安全系数 fs", fs)
        r.check("OK" if fs >= a.fs_min else "NG", f"fs={fmt(fs)} (要求 ≥ {a.fs_min:g}; 有冲击振动取 3~5)")
    r.note("负荷系数 fw: 低速无冲击 1.0~1.5, 中速一般工况 1.5~2.0, 高速有冲击 2.0~3.5")
    r.note("等效负荷 P 需由悬臂/偏载力矩分配到各滑块后计算; 本命令只做寿命换算")
    return r


def cmd_move(a):
    r = Report("点到点运动时间")
    if a.accel:
        acc = a.accel * 1000
    elif a.accel_time:
        acc = a.speed / a.accel_time
    else:
        sys.exit("需给出 --accel (m/s²) 或 --accel-time (s)")
    t_a, t_c, v_pk = trapezoid(a.dist, a.speed, a.speed / acc)
    r.inp("移动距离", a.dist, "mm")
    r.inp("最高速度", a.speed, "mm/s")
    r.inp("加速度", acc / 1000, "m/s²")
    r.inp("整定时间", a.settle, "s")
    r.res("速度曲线", "梯形" if t_c > 0 else "三角 (未达最高速度)")
    r.res("峰值速度", v_pk, "mm/s")
    r.res("加速时间 = 减速时间", t_a, "s")
    r.res("匀速时间", t_c, "s")
    r.res("单程总时间 (含整定)", 2 * t_a + t_c + a.settle, "s")
    r.note("伺服定位整定时间一般 0.02~0.1 s, 与刚性、负载和到位宽度有关")
    return r


def cmd_safety(a):
    r = Report("安全光栅安全距离 (ISO 13855, 手/手指检测, 垂直接近)")
    T = (a.curtain_ms + a.control_ms + a.stop_ms) / 1000
    d = a.resolution
    if d > 40:
        sys.exit("本命令仅适用于分辨率 d ≤ 40 mm 的手/手指检测光栅")
    C = max(0.0, 8 * (d - 14))
    r.inp("光栅响应时间", a.curtain_ms, "ms")
    r.inp("控制系统响应时间", a.control_ms, "ms")
    r.inp("机器停止时间 (实测)", a.stop_ms, "ms")
    r.inp("光栅分辨率 d", d, "mm")
    S = 2000 * T + C
    k = 2000
    if S > 500:
        S2 = 1600 * T + C
        S, k = max(S2, 500.0), 1600
    S = max(S, 100.0)
    r.res("总停止时间 T", T * 1000, "ms")
    r.res("附加距离 C = 8(d-14)", C, "mm")
    r.res("接近速度 K", k, "mm/s")
    r.res("最小安全距离 S", S, "mm")
    r.check("注意", "停止时间须在设备上实测 (含伺服制动/气缸排气), 并定期复测")
    r.note("S = K×T + C, K=2000 mm/s; S>500 mm 时以 K=1600 重算且不小于 500 mm; S 最小 100 mm")
    r.note("还需防止从光栅上方/下方/侧面绕过和人员站入危险区 (加护栏或水平光栅)")
    return r


# ---------------------------------------------------------------- CLI

def pos(text):
    """argparse 类型: 正数."""
    v = float(text)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"须 > 0: {text}")
    return v


def pos_int(text):
    v = int(text)
    if v <= 0:
        raise argparse.ArgumentTypeError(f"须为正整数: {text}")
    return v

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", help="输出 JSON")
    common.add_argument("--out", help="写入文件 (UTF-8)")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("cylinder", parents=[common], help="气缸缸径选型")
    p.add_argument("--mass", type=pos, help="负载质量 kg")
    p.add_argument("--force", type=float, help="外力或所需夹紧/压装力 N")
    p.add_argument("--mode", choices=["horizontal", "vertical", "clamp"], default="horizontal",
                   help="horizontal 水平推送 / vertical 垂直举升 / clamp 夹紧压装 (默认 horizontal)")
    p.add_argument("--direction", choices=["push", "pull"], default="push", help="做功方向 (默认 push)")
    p.add_argument("--pressure", type=pos, default=0.4, help="设计压力 MPa (默认 0.4)")
    p.add_argument("--mu", type=float, default=0.2, help="水平摩擦系数 (默认 0.2; 直线导轨 0.01~0.05)")
    p.add_argument("--load-ratio", type=float, help="负载率 η (默认按工况和速度自动取值)")
    p.add_argument("--speed", type=pos, help="平均速度 mm/s")
    p.add_argument("--stroke", type=pos, help="行程 mm")
    p.add_argument("--cycles", type=float, help="往返次数 /min (用于耗气量)")
    p.set_defaults(func=cmd_cylinder)

    p = sub.add_parser("vacuum", parents=[common], help="真空吸盘选型")
    p.add_argument("--mass", type=pos, required=True, help="工件质量 kg")
    p.add_argument("--vacuum", type=pos, default=60, help="真空度 kPa (按绝对值输入, 默认 60 即 -60 kPa)")
    p.add_argument("--cups", type=pos_int, default=1, help="吸盘数量 (默认 1)")
    p.add_argument("--mode", choices=["horizontal", "vertical"], default="horizontal",
                   help="horizontal 水平吸吊 / vertical 侧吸 (默认 horizontal)")
    p.add_argument("--accel", type=float, default=0.0, help="搬运加速度 m/s² (默认 0)")
    p.add_argument("--safety", type=float, help="安全系数 (默认 水平 4 / 垂直 8)")
    p.add_argument("--max-cup", type=float, help="工件可用吸附平面宽度 mm (校核吸盘是否放得下)")
    p.add_argument("--tube-id", type=float, help="吸附侧管内径 mm")
    p.add_argument("--tube-len", type=float, help="吸附侧管长 mm (每个吸盘)")
    p.add_argument("--flow", type=float, help="真空发生器平均吸入流量 L/min (ANR)")
    p.set_defaults(func=cmd_vacuum)

    p = sub.add_parser("screw", parents=[common], help="滚珠丝杠模组 + 伺服")
    add_linear_args(p)
    p.add_argument("--lead", type=pos, required=True, help="丝杠导程 mm")
    p.add_argument("--screw-dia", type=pos, default=16, help="丝杠公称直径 mm (默认 16)")
    p.add_argument("--root-dia", type=pos, help="丝杠牙底径 mm (默认 0.83×公称直径)")
    p.add_argument("--screw-length", type=pos, help="丝杠长度/支撑间距 mm (默认 行程+150)")
    p.add_argument("--support", choices=list(SCREW_SUPPORT), default="fixed-supported",
                   help="支撑方式 (默认 fixed-supported)")
    p.add_argument("--eff", type=pos, default=0.9, help="丝杠效率 (默认 0.9)")
    p.add_argument("--drag-torque", type=float, default=0.02,
                   help="丝杠预压+密封拖动扭矩 N·m (默认 0.02, 以样本为准)")
    add_motor_args(p)
    p.set_defaults(func=cmd_screw)

    p = sub.add_parser("belt", parents=[common], help="同步带模组 + 伺服")
    add_linear_args(p)
    p.add_argument("--pulley-dia", type=pos, help="带轮节圆直径 mm")
    p.add_argument("--teeth", type=pos_int, help="带轮齿数 (与 --pitch 一起代替 --pulley-dia)")
    p.add_argument("--pitch", type=pos, help="带节距 mm (如 HTD3M=3, HTD5M=5)")
    p.add_argument("--belt-mass", type=float, default=0.0, help="同步带质量 kg")
    p.add_argument("--pulley-width", type=float, default=20, help="带轮宽度 mm, 用于估算惯量 (默认 20)")
    p.add_argument("--pulley-inertia", type=float, help="两个带轮总惯量 kg·cm² (给出则不估算)")
    p.add_argument("--eff", type=pos, default=0.95, help="同步带传动效率 (默认 0.95)")
    add_motor_args(p)
    p.set_defaults(func=cmd_belt)

    p = sub.add_parser("rotary", parents=[common], help="伺服+减速机 / DD 转盘")
    p.add_argument("--stations", type=pos_int, help="分度数 (工位数)")
    p.add_argument("--angle", type=pos, help="单次转动角度 ° (代替 --stations)")
    p.add_argument("--index-time", type=pos, required=True, help="分度时间 s")
    p.add_argument("--cycle-time", type=pos, help="整机节拍 s (用于 RMS 占空比)")
    p.add_argument("--profile", choices=list(PROFILE_NAMES), default="trap", help="运动曲线 (默认 trap)")
    p.add_argument("--ratio", type=pos, default=1.0, help="减速比 (1 = DD 直驱)")
    p.add_argument("--ratio-eff", type=pos, default=0.9, help="减速机效率 (默认 0.9)")
    p.add_argument("--backlash-arcmin", type=float, help="减速机回程间隙 arcmin")
    p.add_argument("--accuracy-arcsec", type=float, help="分度精度 arcsec")
    add_table_args(p)
    add_motor_args(p)
    p.set_defaults(func=cmd_rotary)

    p = sub.add_parser("indexer", parents=[common], help="凸轮分割器")
    p.add_argument("--stations", type=pos_int, required=True, help="分度数 S")
    p.add_argument("--cycle-time", type=pos, help="节拍 s (输入轴每转一次)")
    p.add_argument("--input-rpm", type=pos, help="输入轴转速 rpm (代替 --cycle-time)")
    p.add_argument("--index-angle", type=pos, default=120, help="凸轮分度角 θh ° (默认 120)")
    p.add_argument("--profile", choices=list(PROFILE_NAMES), default="ms", help="凸轮曲线 (默认 ms)")
    p.add_argument("--fc", type=pos, default=1.5, help="负载系数 (默认 1.5)")
    p.add_argument("--drive-eff", type=pos, default=0.6, help="电机到输入轴传动效率 (默认 0.6, 蜗轮减速电机)")
    p.add_argument("--accuracy-arcsec", type=float, help="分度精度 arcsec (如 30)")
    add_table_args(p)
    p.set_defaults(func=cmd_indexer)

    p = sub.add_parser("guide", parents=[common], help="直线导轨寿命")
    p.add_argument("--C", type=pos, required=True, help="基本额定动负荷 kN (样本值)")
    p.add_argument("--load", type=pos, required=True, help="单滑块等效负荷 N")
    p.add_argument("--fw", type=pos, default=1.5, help="负荷系数 (默认 1.5)")
    p.add_argument("--type", choices=["ball", "roller"], default="ball", help="滚动体类型")
    p.add_argument("--stroke", type=pos, help="行程 mm")
    p.add_argument("--cycles", type=float, help="往返次数 /min")
    p.add_argument("--hours-per-day", type=float, default=20, help="每天运行小时 (默认 20)")
    p.add_argument("--days-per-year", type=float, default=300, help="每年运行天数 (默认 300)")
    p.add_argument("--target-years", type=float, default=5, help="目标寿命 年 (默认 5)")
    p.add_argument("--C0", type=float, help="基本额定静负荷 kN")
    p.add_argument("--max-load", type=float, help="最大静负荷 N (默认 = --load)")
    p.add_argument("--fs-min", type=float, default=2.0, help="静安全系数要求 (默认 2)")
    p.set_defaults(func=cmd_guide)

    p = sub.add_parser("move", parents=[common], help="点到点运动时间")
    p.add_argument("--dist", type=pos, required=True, help="距离 mm")
    p.add_argument("--speed", type=pos, required=True, help="最高速度 mm/s")
    p.add_argument("--accel", type=float, help="加速度 m/s²")
    p.add_argument("--accel-time", type=pos, help="加速时间 s (代替 --accel)")
    p.add_argument("--settle", type=float, default=0.05, help="整定/到位确认时间 s (默认 0.05)")
    p.set_defaults(func=cmd_move)

    p = sub.add_parser("safety", parents=[common], help="安全光栅安全距离")
    p.add_argument("--curtain-ms", type=float, required=True, help="光栅响应时间 ms")
    p.add_argument("--control-ms", type=float, default=20, help="安全控制器/继电器响应 ms (默认 20)")
    p.add_argument("--stop-ms", type=float, required=True, help="机器停止时间 ms (实测)")
    p.add_argument("--resolution", type=pos, required=True, help="光栅分辨率 mm (≤40)")
    p.set_defaults(func=cmd_safety)
    return ap


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    a = build_parser().parse_args(argv)
    report = a.func(a)
    text = json.dumps(report.as_dict(), ensure_ascii=False, indent=2) if a.json else report.markdown()
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写入 {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
