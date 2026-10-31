#!/usr/bin/env python3
"""3D 概念布局生成器 — 仅依赖 Python 标准库.

把机构方案的组件清单 (JSON) 生成为:
  --html  交互式 3D 预览 (浏览器打开: 旋转/缩放/点选组件看参数/截图, 默认内嵌 three.js 可离线)
  --step  STEP AP214 装配体: 每个组件一个零件, 可在 SolidWorks/Creo/NX 中打开作布局参考
  --stl   STL 网格 (整机)
  --bom   组件清单 CSV
终端输出: 整机外形、组件关键参数 (行程等)、锚点坐标、干涉/超出台面检查.

坐标系: 原点 = 工作台面中心; X 向右, Y 向后 (操作者站在 -Y 侧), Z 向上; 单位 mm; 角度 °, 逆时针为正.
组件类型与参数见 references/layout-3d.md, 样例 assets/layout_example_magnet_ring.json.

示例:
  python3 layout3d.py layout.json --html layout.html --step layout.step
"""

import argparse
import csv
import datetime
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
THREE_JS = os.path.join(HERE, "..", "assets", "vendor", "three.min.js")
THREE_CDN = ["https://cdn.jsdelivr.net/npm/three@0.149.0/build/three.min.js",
             "https://unpkg.com/three@0.149.0/build/three.min.js"]

C = {
    "frame": "#5f6b7a", "plate": "#b9c1ca", "alu": "#c8ced6", "steel": "#8b97a5",
    "dark": "#4a5361", "motor": "#2b2f36", "pneu": "#3d7cc9", "product": "#e8590c",
    "fixture": "#eef0f2", "sensor": "#2f9e44", "safety": "#f2c200", "red": "#d63c3c",
    "glass": "#9fd3ff", "belt": "#30343b", "rubber": "#222222", "white": "#f4f5f7",
    "green": "#37b24d", "yellow": "#fab005",
}


class SpecError(Exception):
    pass


class Unresolved(Exception):
    pass


# ---------------------------------------------------------------- vector math

I3 = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vmul(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def unit(a):
    n = math.sqrt(dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n)


def mmul(A, B):
    return tuple(tuple(sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)) for i in range(3))


def mvec(A, v):
    return tuple(A[i][0] * v[0] + A[i][1] * v[1] + A[i][2] * v[2] for i in range(3))


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def rot_z(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


AXIS = {"z": I3, "x": rot_y(90), "y": rot_x(-90)}


# ---------------------------------------------------------------- parts and builder

class Part:
    """几何体: box(sx,sy,sz) / cyl(r,h) / tube(ro,ri,h) / cone(r1,r2,h), 中心在 c, 局部轴 Z 经 R 旋转."""

    def __init__(self, name, geo, dims, c, color, R=I3, viewer_only=False, opacity=1.0, sweep=False, tag=""):
        if any(d <= 0 for d in dims) or (geo == "tube" and dims[1] >= dims[0]):
            raise SpecError(f"零件 '{name}' 尺寸无效: {dims}")
        self.name, self.geo, self.dims, self.c, self.color = name, geo, tuple(dims), tuple(c), color
        self.R, self.viewer_only, self.opacity, self.sweep = R, viewer_only or sweep, opacity, sweep
        self.tag = tag  # "product" 产品; "push" 允许接触产品的执行件运动包络

    def moved(self, R, t):
        return Part(self.name, self.geo, self.dims, vadd(mvec(R, self.c), t), self.color,
                    mmul(R, self.R), self.viewer_only, self.opacity, self.sweep, self.tag)

    def half(self):
        g, d = self.geo, self.dims
        if g == "box":
            return (d[0] / 2, d[1] / 2, d[2] / 2)
        r = d[0] if g in ("cyl", "tube") else max(d[0], d[1])
        return (r, r, d[-1] / 2)

    def aabb(self):
        h = self.half()
        ext = [sum(abs(self.R[i][j]) * h[j] for j in range(3)) for i in range(3)]
        return [self.c[i] - ext[i] for i in range(3)], [self.c[i] + ext[i] for i in range(3)]


class Builder:
    def __init__(self):
        self.parts, self.anchors, self.lines, self.params, self.notes, self.calc = [], {}, [], [], [], []
        self.meta = {}  # 容量、人工操作点等, 供整机检查使用
        self.main = C["alu"]

    def add(self, part):
        self.parts.append(part)

    def box(self, name, x0, x1, y0, y1, z0, z1, color, **kw):
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        z0, z1 = sorted((z0, z1))
        self.add(Part(name, "box", (x1 - x0, y1 - y0, z1 - z0),
                      ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), color, **kw))

    def boxc(self, name, c, size, color, R=I3, **kw):
        self.add(Part(name, "box", size, c, color, R, **kw))

    def cyl(self, name, c, r, h, color, axis="z", **kw):
        self.add(Part(name, "cyl", (r, h), c, color, AXIS[axis], **kw))

    def cylz(self, name, x, y, z0, z1, r, color, **kw):
        self.add(Part(name, "cyl", (r, z1 - z0), (x, y, (z0 + z1) / 2), color, **kw))

    def tubez(self, name, x, y, z0, z1, ro, ri, color, **kw):
        self.add(Part(name, "tube", (ro, ri, z1 - z0), (x, y, (z0 + z1) / 2), color, **kw))

    def conez(self, name, x, y, z0, z1, r1, r2, color, **kw):
        self.add(Part(name, "cone", (r1, r2, z1 - z0), (x, y, (z0 + z1) / 2), color, **kw))

    def transform(self, R, t=(0.0, 0.0, 0.0)):
        self.parts = [p.moved(R, t) for p in self.parts]
        self.anchors = {k: vadd(mvec(R, v), t) for k, v in self.anchors.items()}
        self.lines = [[vadd(mvec(R, v), t) for v in ln] for ln in self.lines]


def num(c, key, default=None, lo=0.0):
    v = c.get(key, default)
    if v is None:
        raise SpecError(f"组件 {c['id']}: 缺少参数 {key}")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise SpecError(f"组件 {c['id']}: 参数 {key} 应为数字")
    if lo is not None and v <= lo:
        raise SpecError(f"组件 {c['id']}: 参数 {key} 须 > {lo:g}")
    return float(v)


def enum(c, key, choices, default):
    v = c.get(key, default)
    if v not in choices:
        raise SpecError(f"组件 {c['id']}: {key} 应为 {' / '.join(map(str, choices))}, 当前 {v!r}")
    return v


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def product_parts(b, prod, x, y, z, name):
    """在 (x, y, z) 放产品 (底面中心), 返回 (高度, 外接半径)."""
    shape = prod.get("shape", "ring")
    try:
        if shape == "ring":
            od, id_, h = float(prod["od"]), float(prod["id"]), float(prod["h"])
            b.tubez(name, x, y, z, z + h, od / 2, id_ / 2, C["product"], tag="product")
            return h, od / 2
        if shape == "disc":
            d, h = float(prod["d"]), float(prod["h"])
            b.cylz(name, x, y, z, z + h, d / 2, C["product"], tag="product")
            return h, d / 2
        if shape == "box":
            sx, sy, h = (float(v) for v in prod["size"])
            b.box(name, x - sx / 2, x + sx / 2, y - sy / 2, y + sy / 2, z, z + h, C["product"], tag="product")
            return h, math.hypot(sx, sy) / 2
    except (KeyError, TypeError, ValueError):
        pass
    raise SpecError(f"产品参数无效: {prod} (ring 需 od/id/h, disc 需 d/h, box 需 size)")


def product_fmt(prod):
    s = prod.get("shape", "ring")
    if s == "ring":
        return f"环 Φ{prod['od']:g}/Φ{prod['id']:g}×{prod['h']:g}"
    if s == "disc":
        return f"圆片 Φ{prod['d']:g}×{prod['h']:g}"
    return "块 " + "×".join(f"{v:g}" for v in prod["size"])


def move_time(dist, vmax, acc):
    """梯形速度点到点时间 (mm, mm/s, mm/s²)."""
    if dist <= 0:
        return 0.0
    if dist >= vmax * vmax / acc:
        return dist / vmax + vmax / acc
    return 2 * math.sqrt(dist / acc)


def at_pose(c, P, default=(0, 0)):
    p = P(c.get("at", list(default)))
    return (p[0], p[1], p[2], float(c.get("rot", 0)))


# ---------------------------------------------------------------- component builders
# 每个 builder 在组件局部坐标系建模 (原点=安装基准, X=组件主方向), 返回位姿 (x, y, z, 绕Z转角°)

def b_frame(c, P, b):
    L, W, H = (float(v) for v in c.get("size", [1200, 900, 850]))
    t = num(c, "plate", 20)
    foot = 100.0
    b.main = C["frame"]
    b.box("台板", -L / 2, L / 2, -W / 2, W / 2, -t, 0, C["plate"])
    if enum(c, "style", ("cabinet", "legs"), "cabinet") == "legs":
        for sx in (-1, 1):
            for sy in (-1, 1):
                b.box("立柱", sx * (L / 2 - 20), sx * (L / 2 - 80), sy * (W / 2 - 20), sy * (W / 2 - 80),
                      -(H - foot), -t, C["frame"])
        for sy in (-1, 1):
            b.box("横梁", -L / 2 + 20, L / 2 - 20, sy * (W / 2 - 20), sy * (W / 2 - 80),
                  -(H - foot), -(H - foot) + 60, C["frame"])
    else:
        b.box("机柜", -L / 2 + 20, L / 2 - 20, -W / 2 + 20, W / 2 - 20, -(H - foot), -t, C["frame"])
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.cylz("地脚", sx * (L / 2 - 70), sy * (W / 2 - 70), -H, -(H - foot), 30, C["dark"])
    b.anchors.update({"top": (0, 0, 0), "FL": (-L / 2, -W / 2, 0), "FR": (L / 2, -W / 2, 0),
                      "BL": (-L / 2, W / 2, 0), "BR": (L / 2, W / 2, 0)})
    b.params += [("台面尺寸", f"{L:g} × {W:g} mm"), ("台面高度", f"{H:g} mm"),
                 ("结构", "铝型材/钢架" if c.get("style") == "legs" else "钣金机柜")]
    c["_plate"] = (-L / 2, L / 2, -W / 2, W / 2)
    return at_pose(c, P)


def b_enclosure(c, P, b):
    L, W, h = (float(v) for v in c.get("size", [1200, 900, 1000]))
    p = num(c, "profile", 40)
    b.main = C["steel"]
    for sx in (-1, 1):
        for sy in (-1, 1):
            b.box("立柱型材", sx * L / 2, sx * (L / 2 - p), sy * W / 2, sy * (W / 2 - p), 0, h, C["steel"])
    for sy in (-1, 1):
        b.box("顶梁", -L / 2 + p, L / 2 - p, sy * W / 2, sy * (W / 2 - p), h - p, h, C["steel"])
    for sx in (-1, 1):
        b.box("顶梁", sx * L / 2, sx * (L / 2 - p), -W / 2 + p, W / 2 - p, h - p, h, C["steel"])
    kw = {"viewer_only": True, "opacity": 0.08}
    t = 4
    b.box("后板", -L / 2 + p, L / 2 - p, W / 2 - p / 2 - t / 2, W / 2 - p / 2 + t / 2, 0, h - p, C["glass"], **kw)
    for sx in (-1, 1):
        b.box("侧板", sx * (L / 2 - p / 2 - t / 2), sx * (L / 2 - p / 2 + t / 2), -W / 2 + p, W / 2 - p,
              0, h - p, C["glass"], **kw)
    b.box("顶板", -L / 2 + p, L / 2 - p, -W / 2 + p, W / 2 - p, h - p / 2 - t / 2, h - p / 2 + t / 2, C["glass"], **kw)
    if not c.get("open_front", False):
        b.box("前门", -L / 2 + p, L / 2 - p, -W / 2 + p / 2 - t / 2, -W / 2 + p / 2 + t / 2, 0, h - p,
              C["glass"], **kw)
    b.anchors["top"] = (0, 0, h)
    b.params += [("外形", f"{L:g} × {W:g} × {h:g} mm"), ("型材", f"{p:g} mm"),
                 ("前侧", "开口 (配光栅)" if c.get("open_front") else "门")]
    c["_height"] = h
    return at_pose(c, P)


def b_box(c, P, b):
    sx, sy, sz = (float(v) for v in c.get("size", [100, 100, 100]))
    col = c.get("color", C["alu"])
    b.main = col
    b.box(c.get("name", "方块"), -sx / 2, sx / 2, -sy / 2, sy / 2, 0, sz, col)
    b.anchors["top"] = (0, 0, sz)
    b.params.append(("尺寸", f"{sx:g} × {sy:g} × {sz:g} mm"))
    return at_pose(c, P)


def b_cylinder(c, P, b):
    d, h = num(c, "d", 50), num(c, "h", 100)
    axis = enum(c, "axis", ("z", "x"), "z")
    col = c.get("color", C["alu"])
    b.main = col
    if axis == "z":
        b.cylz(c.get("name", "圆柱"), 0, 0, 0, h, d / 2, col)
        b.anchors["top"] = (0, 0, h)
    else:
        b.cyl(c.get("name", "圆柱"), (0, 0, d / 2), d / 2, h, col, axis="x")
        b.anchors["top"] = (0, 0, d)
    b.params.append(("尺寸", f"Φ{d:g} × {h:g} mm"))
    return at_pose(c, P)


def b_turntable(c, P, b):
    dia, thk, H = num(c, "dia", 400), num(c, "thk", 15), num(c, "height", 150)
    n = int(num(c, "stations", 6))
    R = num(c, "fixture_radius", 0.4 * dia)
    fx = c.get("fixture", {})
    fd, fh = float(fx.get("d", 40)), float(fx.get("h", 20))
    start = float(c.get("start_angle", -90))
    sgn = -1 if enum(c, "direction", ("ccw", "cw"), "ccw") == "cw" else 1
    drive = enum(c, "drive", ("dd", "indexer", "servo"), "dd")
    z0 = H - thk
    hub = 25.0
    if z0 - hub < 30:
        raise SpecError(f"组件 {c['id']}: height 过小, 驱动安装空间不足")
    b.main = C["alu"]
    if drive == "dd":
        dd = clamp(0.45 * dia, 120, 300)
        b.cylz("DD马达", 0, 0, 0, z0 - hub, dd / 2, C["motor"])
        b.cylz("连接法兰", 0, 0, z0 - hub, z0, dd * 0.3, C["steel"])
        drive_cn = "DD 马达直驱"
    elif drive == "indexer":
        w = clamp(0.45 * dia, 120, 300)
        b.box("凸轮分割器", -w / 2, w / 2, -w / 2, w / 2, 0, z0 - hub, C["steel"])
        b.cylz("输出法兰", 0, 0, z0 - hub, z0, w * 0.3, C["steel"])
        b.box("减速电机", w / 2, w / 2 + 200, -55, 55, 10, min(120, z0 - hub), C["motor"])
        drive_cn = "凸轮分割器 + 减速电机"
    elif drive == "servo":
        w = clamp(0.3 * dia, 90, 220)
        b.box("精密减速机", -w / 2, w / 2, -w / 2, w / 2, 0, z0 - hub, C["steel"])
        b.cylz("输出法兰", 0, 0, z0 - hub, z0, w * 0.35, C["steel"])
        b.box("伺服电机", w / 2 + 10, w / 2 + 90, -40, 40, 0, z0 - hub, C["motor"])
        drive_cn = "伺服 + 精密减速机"
    else:
        raise SpecError(f"组件 {c['id']}: drive 应为 dd/indexer/servo")
    b.cylz("转盘", 0, 0, z0, H, dia / 2, C["alu"])
    prod = c.get("product")
    ztop_max = H + fh
    for i in range(n):
        a = math.radians(start + sgn * 360.0 * i / n)
        x, y = R * math.cos(a), R * math.sin(a)
        b.cylz(f"治具S{i + 1}", x, y, H, H + fh, fd / 2, C["fixture"])
        zt = H + fh
        if prod:
            ph, _ = product_parts(b, prod, x, y, zt, f"产品S{i + 1}")
            zt += ph
        ztop_max = max(ztop_max, zt)
        b.anchors[f"S{i + 1}"] = (x, y, zt)
    b.anchors["center"] = (0, 0, H)
    rr = fd / 2
    if prod:
        rr = max(rr, product_parts(Builder(), prod, 0, 0, 0, "x")[1])
    nseg, ro, ri = 24, R + rr, max(R - rr, 1.0)
    for k in range(nseg):
        a = 2 * math.pi * k / nseg
        b.boxc("旋转包络", ((ro + ri) / 2 * math.cos(a), (ro + ri) / 2 * math.sin(a), (H + ztop_max) / 2),
               (ro - ri, 2 * ro * math.tan(math.pi / nseg), ztop_max - H), C["product"],
               R=rot_z(math.degrees(a)), sweep=True, opacity=0.06)
    if drive == "indexer":
        b.calc.append(f"mech_calc.py indexer --stations {n} --cycle-time <节拍s> --table-dia {dia:g} "
                      f"--table-thk {thk:g} --fixture-mass <治具+产品kg> --fixture-radius {R:g}")
    else:
        b.calc.append(f"mech_calc.py rotary --stations {n} --index-time <分度s> --cycle-time <节拍s> "
                      f"--table-dia {dia:g} --table-thk {thk:g} --fixture-mass <治具+产品kg> --fixture-radius {R:g}"
                      + (" --ratio <减速比> --backlash-arcmin <回程间隙>" if drive == "servo" else ""))
    cp = c.get("center_plate")
    if cp:
        cpd = float(cp.get("d", 2 * (R - fd / 2 - 15)))
        cpz = float(cp.get("z", ztop_max + 25))
        b.cylz("中心固定柱", 0, 0, H, cpz, 20, C["steel"])
        b.cylz("中心固定盘", 0, 0, cpz, cpz + 10, cpd / 2, C["alu"])
        b.anchors["plate"] = (0, 0, cpz + 10)
    if R + fd / 2 > dia / 2 - 5:
        b.notes.append(("注意", f"治具外缘超出转盘边缘 (R{R:g} + Φ{fd:g}/2 > Φ{dia:g}/2 - 5)"))
    b.params += [("转盘", f"Φ{dia:g} × {thk:g} mm"), ("工位数", f"{n}"), ("治具回转半径", f"R{R:g} mm"),
                 ("台面高度", f"{H:g} mm"), ("驱动", drive_cn)]
    if prod:
        b.params.append(("产品", product_fmt(prod)))
    return at_pose(c, P)


def b_magazine(c, P, b):
    prod = c.get("product")
    if not prod:
        raise SpecError(f"组件 {c['id']}: magazine 需要 product")
    tmp = Builder()
    ph, pr = product_parts(tmp, prod, 0, 0, 0, "x")
    od = 2 * pr
    H = num(c, "height", 100)
    tube_h = num(c, "tube_h", 250)
    s = num(c, "stroke", od + 30)
    bore = num(c, "bore", 10)
    sq = bore + 12
    x_blade = -od / 2 - 25
    x_body1 = x_blade - 15
    x_body0 = x_body1 - (s + 40)
    tubes = int(num(c, "tubes", 1))
    pitch = od + 14
    b.main = C["glass"]
    y_end = (tubes - 1) * pitch + od / 2 + 25
    b.box("底座", x_body0 - 10, s + od / 2 + 25, -od / 2 - 25, y_end + (60 if tubes > 1 else 0), 0, H, C["alu"])
    stack = Builder()
    product_parts(stack, prod, 0, 0, 0, "x")
    sp = stack.parts[0]
    stack_h = min(tube_h * 0.7, 40 * ph)
    dims = sp.dims[:-1] + (stack_h,) if sp.geo != "box" else sp.dims[:2] + (stack_h,)
    for k in range(tubes):
        y = k * pitch
        b.tubez("料管" if k == 0 else "备用料管", 0, y, H + ph + 0.5, H + ph + 0.5 + tube_h, od / 2 + 4, od / 2 + 1,
                C["glass"], opacity=0.4)
        b.add(Part("料柱", sp.geo, dims, (0, y, H + ph + 1 + stack_h / 2), C["product"], tag="product"))
    if tubes > 1:
        b.box("换管气缸", -od / 2 - 20, od / 2 + 20, y_end, y_end + 60, H, H + 30, C["pneu"])
    product_parts(b, prod, s, 0, H, "待取产品")
    b.box("推片", x_blade, -od / 2 - 1, -od * 0.35, od * 0.35, H + 0.3, H + ph * 0.8, C["steel"])
    b.cyl("活塞杆", (x_blade - 7.5, 0, H + sq / 2), max(2.0, bore * 0.2), 15, C["steel"], axis="x")
    b.box("推料气缸", x_body0, x_body1, -sq / 2, sq / 2, H, H + sq, C["pneu"])
    b.box("挡块", s + od / 2 + 1, s + od / 2 + 11, -od / 2 - 5, od / 2 + 5, H, H + ph + 5, C["alu"])
    b.anchors["out"] = (s, 0, H + ph)
    b.anchors["refill"] = (0, 0, H + ph + tube_h)
    cap = tubes * int(tube_h / ph)
    b.meta.update({"capacity": cap, "manual": (0, (tubes - 1) * pitch / 2, H + ph + tube_h), "tubes": tubes})
    b.params += [("产品", product_fmt(prod)), ("料管", f"{tubes} 根 × {tube_h:g} mm"),
                 ("料管容量", f"约 {cap} pcs"), ("推料行程", f"{s:g} mm"),
                 ("取料面高度", f"{H + ph:g} mm"), ("推料气缸", f"Φ{bore:g} × {s:g}")]
    return at_pose(c, P)


def b_bowl(c, P, b):
    D, bh = num(c, "bowl_d", 300), num(c, "bowl_h", 120)
    base_h, L = num(c, "base_h", 150), num(c, "track_len", 250)
    zt = num(c, "track_z", base_h + bh - 30)
    b.main = C["steel"]
    b.cylz("振动盘底座", 0, 0, 0, base_h, D * 0.35, C["dark"])
    b.cylz("盘底", 0, 0, base_h, base_h + 6, D / 2, C["steel"])
    b.tubez("料盘", 0, 0, base_h + 6, base_h + bh, D / 2, D / 2 - 4, C["steel"])
    b.conez("中心锥", 0, 0, base_h + 6, base_h + 6 + bh * 0.5, D * 0.3, D * 0.08, C["steel"])
    x1 = D / 2 + L
    b.box("直振", D / 2 + 5, x1, -40, 40, 0, zt - 25, C["dark"])
    b.box("直振轨道", D / 2 - 20, x1, -12, 12, zt - 25, zt, C["alu"])
    b.box("分料气缸", x1 - 45, x1 - 15, 14, 44, zt - 15, zt + 10, C["pneu"])
    out = (x1 - 15, 0, zt)
    prod = c.get("product")
    if prod:
        ph, _ = product_parts(b, prod, out[0], 0, zt, "待取产品")
        out = (out[0], 0, zt + ph)
        b.params.append(("产品", product_fmt(prod)))
    b.anchors["out"] = out
    b.params += [("振动盘", f"Φ{D:g} mm"), ("直振长度", f"{L:g} mm"), ("出料高度", f"{zt:g} mm")]
    b.notes.append(("注意", "振动盘对磁性件易互吸卡料, 磁环类优先料管/料盘"))
    return at_pose(c, P)


def b_pick_place(c, P, b):
    pf, pt = P(c.get("from"), "from"), P(c.get("to"), "to")
    dx, dy = pt[0] - pf[0], pt[1] - pf[1]
    L = math.hypot(dx, dy)
    if L < 20:
        raise SpecError(f"组件 {c['id']}: from 与 to 水平距离 < 20 mm")
    yaw = math.degrees(math.atan2(dy, dx))
    zf, zt = pf[2], pt[2]
    zs = num(c, "z_stroke", 30)
    side = num(c, "side", 90)
    m = num(c, "margin", 60)
    nl = num(c, "nozzle_len", 50)
    drive = enum(c, "drive", ("cylinder", "module"), "cylinder")
    pos = clamp(float(c.get("pos", 0)), 0.0, 1.0)
    center = P(c.get("center", [0, 0]))
    post_at = enum(c, "post_at", ("auto", "start", "end"), "auto")
    if post_at == "auto":
        post_at = "start" if math.dist(pf[:2], center[:2]) >= math.dist(pt[:2], center[:2]) else "end"
    nx, ny = -dy / L, dx / L
    ps = enum(c, "post_side", ("auto", "left", "right"), "auto")
    if ps == "auto":
        mx, my = (pf[0] + pt[0]) / 2, (pf[1] + pt[1]) / 2
        dl = math.hypot(mx + nx * side - center[0], my + ny * side - center[1])
        dr = math.hypot(mx - nx * side - center[0], my - ny * side - center[1])
        ps = "left" if dl >= dr - 1e-6 else "right"
    s = 1 if ps == "left" else -1
    z_up = max(zf, zt) + zs
    xc = pos * L
    zn1 = z_up + nl
    hz = zs + 70
    zb0 = zn1 + hz - 60
    mod = drive == "module"
    b.main = C["steel"] if mod else C["pneu"]
    b.cylz("吸盘", xc, 0, z_up, z_up + 4, 5, C["rubber"])
    b.cylz("吸嘴", xc, 0, z_up + 4, zn1, 3, C["steel"])
    b.box("Z轴模组" if mod else "Z轴滑台气缸", xc - 15, xc + 15, -20, 20, zn1, zn1 + hz,
          C["steel"] if mod else C["pneu"])
    b.box("连接板", xc - 25, xc + 25, s * 20, s * (side - 45), zb0, zb0 + 60, C["alu"])
    b.box("滑块", xc - 40, xc + 40, s * (side - 45), s * (side - 30), zb0 - 5, zb0 + 65, C["steel"])
    b.box("X轴模组" if mod else "X轴无杆气缸", -m, L + m, s * side - 30, s * side + 30, zb0, zb0 + 60,
          C["steel"] if mod else C["pneu"])
    px0 = -m if post_at == "start" else L + m - 60
    if mod:
        mx0 = -m - 110 if post_at == "start" else L + m
        b.box("X轴电机", mx0, mx0 + 110, s * side - 30, s * side + 30, zb0 + 5, zb0 + 55, C["motor"])
    b.box("立柱", px0, px0 + 60, s * side - 30, s * side + 30, 12, zb0, C["alu"])
    b.box("立柱底板", px0 - 30, px0 + 90, s * side - 60, s * side + 60, 0, 12, C["alu"])
    b.lines.append([(0, 0, zf), (0, 0, z_up), (L, 0, z_up), (L, 0, zt)])
    sw = {"sweep": True, "opacity": 0.1}
    b.box("运动包络 (X 行程)", -25, L + 25, min(-20, s * (side - 45)), max(20, s * (side - 45)),
          z_up, zb0 + 65, C["product"], **sw)
    for x, zw in ((0, zf), (L, zt)):
        if z_up - zw > 1.5:
            b.box("运动包络 (Z 下降)", x - 6, x + 6, -6, 6, zw + 1, z_up, C["product"], **sw)
    b.anchors.update({"pick": (0, 0, zf), "place": (L, 0, zt), "up": (xc, 0, z_up)})
    z_need = zs + abs(zf - zt)
    vx = num(c, "x_speed", 800 if mod else 300)
    vz = num(c, "z_speed", 400 if mod else 200)
    if mod:
        tx, tz = move_time(L, vx, 5000) + 0.05, move_time(z_need, vz, 3000) + 0.05
    else:
        tx, tz = 0.05 + L / vx, 0.05 + z_need / vz
    b.calc.append(f"mech_calc.py {'belt' if L > 600 else 'screw'} --mass <X轴移动质量kg> "
                  + ("--pulley-dia 30 " if L > 600 else "--lead 10 ") + f"--speed 800 --stroke {L:.0f}"
                  if mod else f"mech_calc.py cylinder --mass <X轴移动质量kg> --stroke {L:.0f} --speed 300")
    b.calc.append(f"mech_calc.py screw --mass <Z轴移动质量kg> --lead 5 --speed 400 --stroke {z_need:.0f} --vertical"
                  if mod else f"mech_calc.py cylinder --mass <Z轴移动质量kg> --mode vertical --stroke {z_need:.0f} --speed 200")
    b.params += [("X 行程", f"{L:.1f} mm"), ("Z 行程", f"≥ {z_need:.1f} mm"),
                 ("取/放高度差", f"{zt - zf:+.1f} mm"), ("驱动", "伺服模组" if mod else "气缸"),
                 ("X/Z 单程估算", f"{tx:.2f} / {tz:.2f} s (按 {vx:g} / {vz:g} mm/s)"),
                 ("取放循环估算", f"{4 * tz + 2 * tx + 0.2:.2f} s (含吸/放各 0.1 s)"),
                 ("立柱位置", ("取料端" if post_at == "start" else "放料端") + ("左侧" if s > 0 else "右侧"))]
    if not mod and L > 300:
        b.notes.append(("注意", f"X 行程 {L:.0f} mm > 300 mm, 气缸取放冲击大, 建议用伺服模组"))
    return (pf[0], pf[1], 0.0, yaw)


def b_actuator(c, P, b, probe=False):
    tip = P(c.get("tip"), "tip")
    if "toward" in c:
        tw = P(c["toward"], "toward")
        if math.hypot(tw[0] - tip[0], tw[1] - tip[1]) < 1e-6:
            raise SpecError(f"组件 {c['id']}: toward 与 tip 重合")
        yaw = math.degrees(math.atan2(tw[1] - tip[1], tw[0] - tip[0]))
    elif "dir" in c:
        yaw = float(c["dir"])
    else:
        raise SpecError(f"组件 {c['id']}: 需要 toward (推向的点) 或 dir (推动方向°)")
    bore = num(c, "bore", 10 if probe else 16)
    stroke = num(c, "stroke", 10 if probe else 20)
    head = enum(c, "head", ("block", "probe", "none"), "probe" if probe else "block")
    zt = tip[2]
    sq = bore + 14
    b.main = C["sensor"] if head == "probe" else C["pneu"]
    if head == "block":
        hd, hw, hh = (float(v) for v in c.get("head_size", [10, 20, 15]))
        b.box("推块", -stroke - hd, -stroke, -hw / 2, hw / 2, zt - hh / 2, zt + hh / 2, C["alu"])
        x_back = -stroke - hd
    elif head == "probe":
        b.cyl("探头", (-stroke - 20, 0, zt), 3, 40, C["sensor"], axis="x")
        b.box("探头座", -stroke - 60, -stroke - 40, -12, 12, zt - 12, zt + 12, C["alu"])
        x_back = -stroke - 60
    else:
        x_back = -stroke
    b.cyl("活塞杆", (x_back - 7.5, 0, zt), max(2.0, bore * 0.2), 15, C["steel"], axis="x")
    bx1 = x_back - 15
    bx0 = bx1 - (stroke + 40)
    b.box("气缸本体", bx0, bx1, -sq / 2, sq / 2, zt - sq / 2, zt + sq / 2, C["pneu"])
    if enum(c, "support", ("down", "none"), "down") == "down" and zt - sq / 2 > 1:
        b.box("支架", bx0 + 5, bx1 - 5, -sq / 2, sq / 2, 0, zt - sq / 2, C["alu"])
    sw = {"sweep": True, "opacity": 0.1, "tag": "push"}
    if head == "block":
        b.box("运动包络 (推出)", -stroke - hd, 0, -hw / 2, hw / 2, zt - hh / 2, zt + hh / 2, C["product"], **sw)
    elif head == "probe":
        b.box("运动包络 (探头进给)", -stroke - 60, 0, -12, 12, zt - 12, zt + 12, C["product"], **sw)
    b.calc.append(f"mech_calc.py cylinder --mass <探头组件kg> --stroke {stroke:g} --speed 100" if head == "probe"
                  else f"mech_calc.py cylinder --mode clamp --force <所需推/夹紧力N> --stroke {stroke:g}")
    b.anchors.update({"tip": (0, 0, zt), "retracted": (-stroke, 0, zt)})
    b.params += [("气缸", f"Φ{bore:g} × {stroke:g} mm"), ("动作方向", f"{yaw:.0f}°"),
                 ("末端", {"block": "推块", "probe": "探头", "none": "无"}.get(head, head))]
    return (tip[0], tip[1], 0.0, yaw)


def b_probe(c, P, b):
    return b_actuator(c, P, b, probe=True)


def overhead(c, P, b, kind):
    tgt = P(c.get("target"), "target")
    arm = num(c, "arm", 120)
    if "post_dir" in c:
        ang = float(c["post_dir"])
    else:
        cen = P(c.get("center", [0, 0]))
        vx, vy = tgt[0] - cen[0], tgt[1] - cen[1]
        ang = math.degrees(math.atan2(vy, vx)) if math.hypot(vx, vy) > 1 else 90.0
    zt = tgt[2]
    if kind == "camera":
        wd = num(c, "wd", 100)
        b.main = C["sensor"]
        b.tubez("环形光源", 0, 0, zt + wd * 0.45, zt + wd * 0.45 + 12, 35, 22, C["white"])
        b.cylz("镜头", 0, 0, zt + wd, zt + wd + 45, 14, C["steel"])
        b.box("相机", -22, 22, -22, 22, zt + wd + 45, zt + wd + 105, C["motor"])
        top, back = zt + wd + 105, 22
        b.params += [("工作距离", f"{wd:g} mm")]
        if "fov" in c:
            b.params.append(("视野", str(c["fov"])))
    elif kind == "spindle":
        gap = num(c, "gap", 15)
        zs = num(c, "z_stroke", gap + 10)
        cd = num(c, "chuck_d", 20)
        z = zt + gap
        b.main = C["motor"]
        b.cylz("压头/夹头", 0, 0, z, z + 25, cd / 2, C["steel"])
        if gap > 1:
            b.cylz("运动包络 (下压)", 0, 0, zt + 0.5, z, cd / 2, C["product"], sweep=True, opacity=0.1, tag="push")
        b.cylz("主轴", 0, 0, z + 25, z + 65, 8, C["steel"])
        b.box("伺服电机", -30, 30, -30, 30, z + 65, z + 165, C["motor"])
        b.box("Z轴滑台", -65, -30, -25, 25, z + 65, z + 165 + zs, C["pneu"])
        top, back = z + 165 + zs, 65
        b.params += [("下压间隙", f"{gap:g} mm"), ("Z 行程", f"≥ {zs:g} mm"), ("夹头", f"Φ{cd:g}")]
    elif kind == "press":
        gap = num(c, "gap", 20)
        bore = num(c, "bore", 50)
        st = num(c, "stroke", gap + 10)
        sq = bore + 20
        z = zt + gap
        b.main = C["pneu"]
        b.cylz("压头", 0, 0, z, z + 20, bore * 0.3, C["steel"])
        if gap > 1:
            b.cylz("运动包络 (下压)", 0, 0, zt + 0.5, z, bore * 0.3, C["product"], sweep=True, opacity=0.1, tag="push")
        b.calc.append(f"mech_calc.py cylinder --mode clamp --force <压装力N> --stroke {st:g}")
        b.cylz("活塞杆", 0, 0, z + 20, z + 60, bore * 0.2, C["steel"])
        b.box("压装气缸", -sq / 2, sq / 2, -sq / 2, sq / 2, z + 60, z + 60 + st + 80, C["pneu"])
        top, back = z + 60 + st + 80, sq / 2
        b.params += [("压装缸", f"Φ{bore:g} × {st:g} mm"), ("压头间隙", f"{gap:g} mm")]
        b.notes.append(("注意", "压装力大时立柱悬臂刚性不足, 定型时改 C 型架或四柱结构"))
    else:
        gap = num(c, "gap", 10)
        sx, sy, sz = (float(v) for v in c.get("size", [60, 60, 120]))
        b.main = C["dark"]
        b.box(c.get("name", "执行单元"), -sx / 2, sx / 2, -sy / 2, sy / 2, zt + gap, zt + gap + sz, C["dark"])
        top, back = zt + gap + sz, sx / 2
        b.params += [("尺寸", f"{sx:g} × {sy:g} × {sz:g} mm"), ("间隙", f"{gap:g} mm")]
    b.box("安装臂", -arm - 30, -back, -25, 25, top - 40, top, C["alu"])
    b.box("立柱", -arm - 30, -arm + 30, -30, 30, 12, top - 40, C["alu"])
    b.box("立柱底板", -arm - 60, -arm + 60, -60, 60, 0, 12, C["alu"])
    b.anchors.update({"target": (0, 0, zt), "post": (-arm, 0, 0)})
    b.params.append(("立柱距目标", f"{arm:g} mm"))
    return (tgt[0], tgt[1], 0.0, ang + 180.0)


def b_camera(c, P, b):
    return overhead(c, P, b, "camera")


def b_spindle(c, P, b):
    return overhead(c, P, b, "spindle")


def b_press(c, P, b):
    return overhead(c, P, b, "press")


def b_tool(c, P, b):
    return overhead(c, P, b, "tool")


def b_module(c, P, b):
    stroke, w, h = num(c, "stroke", 300), num(c, "width", 80), num(c, "height", 60)
    pos = clamp(float(c.get("pos", 0)), 0.0, 1.0)
    vertical = bool(c.get("vertical", False))
    xc = pos * stroke
    b.main = C["steel"]
    b.box("模组本体", -90, stroke + 90, -w / 2, w / 2, 0, h, C["steel"])
    b.box("滑台", xc - 50, xc + 50, -w / 2 + 5, w / 2 - 5, h, h + 15, C["alu"])
    mx0 = stroke + 90 if vertical else -200
    b.box("伺服电机", mx0, mx0 + 110, -30, 30, h / 2 - 30, h / 2 + 30, C["motor"])
    b.anchors.update({"carriage": (xc, 0, h + 15), "start": (0, 0, h + 15), "end": (stroke, 0, h + 15)})
    pl = c.get("payload")
    if pl:
        try:
            lx, wy, hz = (float(v) for v in pl)
        except (TypeError, ValueError):
            raise SpecError(f"组件 {c['id']}: payload 应为 [长, 宽, 高]")
        b.box("运动包络 (滑台负载)", -lx / 2, stroke + lx / 2, -wy / 2, wy / 2, h + 15, h + 15 + hz,
              C["product"], sweep=True, opacity=0.1)
    b.calc.append(f"mech_calc.py screw --mass <移动质量kg> --lead <导程mm> --speed <mm/s> --stroke {stroke:g}"
                  + (" --vertical" if vertical else ""))
    if vertical:
        b.transform(rot_y(-90))
    b.params += [("有效行程", f"{stroke:g} mm"), ("截面", f"{w:g} × {h:g} mm"),
                 ("姿态", "竖直" if vertical else "水平")]
    return at_pose(c, P)


def b_conveyor(c, P, b):
    L, w, H = num(c, "length", 600), num(c, "width", 100), num(c, "height", 80)
    if H < 60:
        raise SpecError(f"组件 {c['id']}: height (输送面高度) 须 ≥ 60")
    b.main = C["belt"]
    for sy in (-1, 1):
        b.box("侧板", 0, L, sy * (w / 2 + 2), sy * (w / 2 + 14), H - 50, H + 8, C["alu"])
    b.box("皮带", 0, L, -w / 2, w / 2, H - 8, H, C["belt"])
    for x in (0, L):
        b.cyl("滚筒", (x, 0, H - 25), 20, w, C["steel"], axis="y")
    for x in (40, L - 40):
        b.box("支腿", x - 20, x + 20, -w / 2, w / 2, 0, H - 50, C["alu"])
    b.box("驱动电机", L - 100, L - 20, w / 2 + 14, w / 2 + 84, H - 70, H - 10, C["motor"])
    b.anchors.update({"start": (30, 0, H), "end": (L - 30, 0, H), "mid": (L / 2, 0, H)})
    b.params += [("长度 × 带宽", f"{L:g} × {w:g} mm"), ("输送面高度", f"{H:g} mm")]
    b.calc.append("mech_calc.py conveyor --load <在线总质量kg> --speed <m/min>")
    return at_pose(c, P)


def b_chute(c, P, b):
    pf, pt = P(c.get("from"), "from"), P(c.get("to"), "to")
    dx, dy = pt[0] - pf[0], pt[1] - pf[1]
    L = math.hypot(dx, dy)
    if L < 10:
        raise SpecError(f"组件 {c['id']}: from 与 to 水平距离过小")
    dz = pt[2] - pf[2]
    D = math.hypot(L, dz)
    phi = math.degrees(math.atan2(-dz, L))
    w = num(c, "width", 30)
    wall = num(c, "wall_h", 15)
    b.main = C["alu"]
    sub = Builder()
    sub.box("滑道底板", 0, D, -w / 2 - 3, w / 2 + 3, -3, 0, C["alu"])
    for sy in (-1, 1):
        sub.box("滑道侧板", 0, D, sy * w / 2, sy * (w / 2 + 3), 0, wall, C["alu"])
    sub.transform(rot_y(phi), (0, 0, pf[2]))
    b.parts += sub.parts
    for x, z in ((25, pf[2] + 25 * dz / L), (L - 25, pt[2] - 25 * dz / L)):
        top = z - 3 - 10
        if top > 15:
            b.box("支撑", x - 10, x + 10, -10, 10, 0, top, C["alu"])
    b.anchors.update({"in": (0, 0, pf[2]), "out": (L, 0, pt[2])})
    ang = math.degrees(math.atan2(-dz, L))
    b.params += [("长度", f"{D:.0f} mm"), ("倾角", f"{ang:.1f}°"), ("宽度", f"{w:g} mm")]
    if ang < 15:
        b.notes.append(("注意", f"滑道倾角 {ang:.1f}° < 15°, 产品可能滑不动"))
    return (pf[0], pf[1], 0.0, math.degrees(math.atan2(dy, dx)))


def b_bin(c, P, b):
    w, d, h = (float(v) for v in c.get("size", [150, 120, 100]))
    col = c.get("color", C["red"])
    t = 4.0
    b.main = col
    b.box("底板", -w / 2, w / 2, -d / 2, d / 2, 0, t, col)
    for sy in (-1, 1):
        b.box("侧板", -w / 2, w / 2, sy * d / 2, sy * (d / 2 - t), t, h, col)
    for sx in (-1, 1):
        b.box("侧板", sx * w / 2, sx * (w / 2 - t), -d / 2 + t, d / 2 - t, t, h, col)
    b.anchors["top"] = (0, 0, h)
    share = float(c.get("share", 1.0))
    if not 0 < share <= 1:
        raise SpecError(f"组件 {c['id']}: share (流入本料盒的产量比例) 应在 0~1 之间, 如 NG 料盒 0.02")
    b.meta.update({"volume": (w - 8) * (d - 8) * (h - 4), "share": share, "manual": (0, 0, h)})
    b.params += [("尺寸", f"{w:g} × {d:g} × {h:g} mm"), ("容积", f"{(w - 8) * (d - 8) * (h - 4) / 1e6:.2f} L")]
    if "share" in c:
        b.params.append(("流入比例", f"{share:.0%}"))
    return at_pose(c, P)


def b_tray(c, P, b):
    w, d, h = (float(v) for v in c.get("size", [300, 200, 20]))
    col = c.get("color", C["dark"])
    b.main = col
    b.box("料盘", -w / 2, w / 2, -d / 2, d / 2, 0, h, col)
    b.anchors.update({"center": (0, 0, h), "corner": (-w / 2, -d / 2, h)})
    b.meta["manual"] = (0, 0, h)
    b.params.append(("料盘", f"{w:g} × {d:g} × {h:g} mm"))
    return at_pose(c, P)


def b_product(c, P, b):
    prod = c.get("product") or c
    h, _ = product_parts(b, prod, 0, 0, 0, c.get("name", "产品"))
    b.main = C["product"]
    b.anchors["top"] = (0, 0, h)
    b.params.append(("产品", product_fmt(prod)))
    return at_pose(c, P)


def b_light_curtain(c, P, b):
    span, hgt = num(c, "span", 800), num(c, "height", 600)
    z0 = num(c, "z0", 50, lo=None)
    b.main = C["safety"]
    for sx in (-1, 1):
        b.box("光栅" + ("发射端" if sx < 0 else "接收端"), sx * span / 2, sx * (span / 2 + 30), -15, 15,
              0, z0 + hgt + 20, C["safety"])
    b.box("保护区域", -span / 2, span / 2, -1, 1, z0, z0 + hgt, C["red"], sweep=True, opacity=0.07, tag="field")
    b.params += [("保护宽度", f"{span:g} mm"), ("保护高度", f"{hgt:g} mm"), ("下沿高度", f"{z0:g} mm")]
    b.calc.append("mech_calc.py safety --curtain-ms <光栅响应ms> --stop-ms <实测停止ms> --resolution <分辨率mm>")
    return at_pose(c, P)


def b_hmi(c, P, b):
    arm = num(c, "arm", 100)
    b.main = C["motor"]
    b.box("安装座", -25, 25, -10, 30, -30, 30, C["steel"])
    b.box("悬臂", -15, 15, -arm, -10, -10, 10, C["steel"])
    b.boxc("触摸屏", (0, -arm - 20, 0), (320, 45, 240), C["motor"], R=rot_x(-15))
    b.params.append(("触摸屏", "约 12 寸"))
    return at_pose(c, P)


def b_tower_light(c, P, b):
    pole = num(c, "pole", 250)
    b.main = C["yellow"]
    b.cylz("底座", 0, 0, 0, 15, 30, C["dark"])
    b.cylz("灯杆", 0, 0, 15, 15 + pole, 10, C["steel"])
    z = 15 + pole
    for name, col in (("绿灯", C["green"]), ("黄灯", C["yellow"]), ("红灯", C["red"])):
        b.cylz(name, 0, 0, z, z + 40, 30, col)
        z += 40
    b.cylz("顶盖", 0, 0, z, z + 15, 30, C["dark"])
    b.params.append(("三色灯", "红/黄/绿 + 蜂鸣"))
    return at_pose(c, P)


def b_scara(c, P, b):
    base = P(c.get("at", [0, 0]))
    tg = c.get("targets")
    if not isinstance(tg, list) or not tg:
        raise SpecError(f"组件 {c['id']}: scara 需要 targets (工作点列表, 如取料点和放料点)")
    pts = [P(x, "targets") for x in tg]
    reach = num(c, "reach", 400)
    a1 = num(c, "a1", reach * 0.55)
    a2 = num(c, "a2", reach - a1)
    reach = a1 + a2
    zs, tool, clear = num(c, "z_stroke", 150), num(c, "tool_len", 60), num(c, "clear", 30)
    elbow = enum(c, "elbow", ("right", "left"), "right")
    k = int(num(c, "pose", 1)) - 1
    if k >= len(pts):
        raise SpecError(f"组件 {c['id']}: pose 超出 targets 数量")
    loc = [(p[0] - base[0], p[1] - base[1], p[2] - base[2]) for p in pts]
    zmax, zmin = max(p[2] for p in loc), min(p[2] for p in loc)
    f = zmax + tool + clear
    zl2, zl1, top = f + 20, f + 70, f + 130
    rmin = abs(a1 - a2) + 30
    far = 0.0
    for i, (x, y, _) in enumerate(loc, start=1):
        d = math.hypot(x, y)
        far = max(far, d)
        if d > reach - 5:
            b.notes.append(("NG", f"目标 T{i} 距离 {d:.0f} mm 超出臂展 {reach:g} mm"))
        elif d < rmin:
            b.notes.append(("NG", f"目标 T{i} 距离 {d:.0f} mm 小于最小工作半径 {rmin:.0f} mm"))
    if zmax - zmin + clear > zs:
        b.notes.append(("注意", f"目标高度差 {zmax - zmin:.0f} mm + 抬起 {clear:g} mm 超出 Z 行程 {zs:g} mm"))
    b.main = C["white"]
    b.box("底座", -100, 100, -100, 100, 0, 20, C["steel"])
    b.cylz("机身", 0, 0, 20, zl1, 75, C["white"])
    x, y = loc[k][0], loc[k][1]
    d = clamp(math.hypot(x, y), rmin, reach - 1)
    c2 = clamp((d * d - a1 * a1 - a2 * a2) / (2 * a1 * a2), -1.0, 1.0)
    th2 = math.acos(c2) * (1 if elbow == "right" else -1)
    th1 = math.atan2(y, x) - math.atan2(a2 * math.sin(th2), a1 + a2 * math.cos(th2))
    ex, ey = a1 * math.cos(th1), a1 * math.sin(th1)
    wx, wy = ex + a2 * math.cos(th1 + th2), ey + a2 * math.sin(th1 + th2)
    b.boxc("第一臂", (ex / 2, ey / 2, (zl1 + top) / 2), (a1 + 120, 120, top - zl1), C["white"],
           R=rot_z(math.degrees(th1)))
    b.boxc("第二臂", ((ex + wx) / 2, (ey + wy) / 2, (zl2 + zl1) / 2), (a2 + 90, 90, zl1 - zl2), C["white"],
           R=rot_z(math.degrees(th1 + th2)))
    b.cylz("肘关节", ex, ey, zl2, top + 3, 50, C["steel"])
    b.cylz("丝杆花键轴", wx, wy, f, top + 60, 10, C["steel"])
    b.cylz("末端工具", wx, wy, f - tool, f, 8, C["dark"])
    if c.get("sweep", True):
        sw = {"sweep": True, "opacity": 0.05}
        b.cylz("运动包络 (手臂旋转)", 0, 0, zl2, top, reach + 45, C["product"], **sw)
        for i in range(len(loc)):
            (x0, y0, z0), (x1, y1, _) = loc[i], loc[(i + 1) % len(loc)]
            seg = math.hypot(x1 - x0, y1 - y0)
            if seg > 1 and (i + 1 < len(loc) or len(loc) > 2):
                b.boxc("运动包络 (工具移动)", ((x0 + x1) / 2, (y0 + y1) / 2, (f - tool + zl2) / 2),
                       (seg + 30, 30, zl2 - f + tool), C["product"], R=rot_z(math.degrees(math.atan2(y1 - y0, x1 - x0))),
                       sweep=True, opacity=0.1)
            if f - tool - z0 > 1.5:
                b.cylz("运动包络 (Z 下降)", x0, y0, z0 + 1, f - tool, 10, C["product"], sweep=True, opacity=0.1)
    b.anchors.update({"base": (0, 0, 0), "tool": (wx, wy, f - tool)})
    b.anchors.update({f"T{i}": p for i, p in enumerate(loc, start=1)})
    b.params += [("臂展", f"{reach:g} mm (一臂 {a1:g} / 二臂 {a2:g})"), ("Z 行程", f"{zs:g} mm"),
                 ("最远目标", f"{far:.0f} mm (臂展利用 {far / reach:.0%})"),
                 ("目标高度差", f"{zmax - zmin:.0f} mm"), ("目标数", f"{len(loc)}")]
    b.notes.append(("注意", "SCARA 按厂家样本核对负载、惯量和标准循环时间; 运动包络按整圈旋转, 实际可用软限位缩小"))
    return (base[0], base[1], base[2], 0.0)


TYPES = {
    "frame": (b_frame, "机架"), "enclosure": (b_enclosure, "防护罩"),
    "box": (b_box, "方块"), "cylinder": (b_cylinder, "圆柱"),
    "turntable": (b_turntable, "转盘"), "linear_module": (b_module, "直线模组"),
    "pick_place": (b_pick_place, "取放机构"), "cylinder_actuator": (b_actuator, "气缸"),
    "probe": (b_probe, "检测探头"), "camera": (b_camera, "相机"), "spindle": (b_spindle, "旋转/下压头"),
    "press": (b_press, "压装"), "tool": (b_tool, "顶置工具"),
    "bowl_feeder": (b_bowl, "振动盘"), "magazine": (b_magazine, "料管上料"),
    "conveyor": (b_conveyor, "皮带线"), "chute": (b_chute, "滑道"), "bin": (b_bin, "料盒"),
    "tray": (b_tray, "料盘"), "product": (b_product, "产品"),
    "light_curtain": (b_light_curtain, "安全光栅"), "hmi": (b_hmi, "触摸屏"), "tower_light": (b_tower_light, "三色灯"),
    "scara": (b_scara, "SCARA 机器人"),
}
NO_PLATE_CHECK = {"frame", "enclosure", "light_curtain", "hmi", "tower_light"}

# 类型: (主要参数, 锚点). 通用参数: id, type, name, at, rot, touch. 详见 references/layout-3d.md
CATALOG = {
    "frame": ("size [长,宽,台面离地高], plate, style cabinet|legs", "top FL FR BL BR"),
    "enclosure": ("size [长,宽,高], profile, open_front", "top"),
    "box": ("size [x,y,z], color", "top"),
    "cylinder": ("d, h, axis z|x, color", "top"),
    "turntable": ("dia, thk, height, stations, fixture_radius, fixture {d,h}, drive dd|indexer|servo, "
                  "start_angle, direction ccw|cw, product, center_plate {d,z}", "S1..Sn center plate"),
    "linear_module": ("stroke, width, height, pos 0~1, vertical, payload [长,宽,高]", "carriage start end"),
    "pick_place": ("from, to, z_stroke, drive cylinder|module, side, post_side auto|left|right, "
                   "post_at auto|start|end, margin, nozzle_len, pos, center, x_speed, z_speed (时间估算用 mm/s)", "pick place up"),
    "cylinder_actuator": ("tip, toward|dir, bore, stroke, head block|probe|none, head_size [长,宽,高], "
                          "support down|none", "tip retracted"),
    "probe": ("同 cylinder_actuator, 默认 head=probe, bore 10, stroke 10", "tip retracted"),
    "camera": ("target, wd, arm, post_dir|center, fov", "target post"),
    "spindle": ("target, gap, z_stroke, chuck_d, arm, post_dir|center", "target post"),
    "press": ("target, gap, bore, stroke, arm, post_dir|center", "target post"),
    "tool": ("target, size [x,y,z], gap, arm, post_dir|center", "target post"),
    "bowl_feeder": ("bowl_d, bowl_h, base_h, track_len, track_z, product", "out"),
    "magazine": ("product, height, tube_h, stroke, bore, tubes 料管数", "out refill"),
    "conveyor": ("length, width, height", "start mid end"),
    "chute": ("from, to, width, wall_h", "in out"),
    "bin": ("size [宽,深,高], color, share 流入比例 (NG 盒如 0.02)", "top"),
    "tray": ("size [宽,深,高], color", "center corner"),
    "product": ("shape ring|disc|box + od/id/h | d/h | size", "top"),
    "light_curtain": ("span, height, z0, min_distance", "-"),
    "hmi": ("at [x,y,z], arm", "-"),
    "tower_light": ("at [x,y,z], pole", "-"),
    "scara": ("at, targets [点...], reach | a1, a2, z_stroke, tool_len, clear, elbow right|left, pose, sweep",
              "base tool T1..Tn"),
}

COMMON_KEYS = {"id", "type", "name", "touch", "note"}
PLACED = {"at", "rot"}
ACT = {"tip", "toward", "dir", "bore", "stroke", "head", "head_size", "support"}
OVER = {"target", "arm", "post_dir", "center"}
ALLOWED = {
    "frame": {"size", "plate", "style"} | PLACED, "enclosure": {"size", "profile", "open_front"} | PLACED,
    "box": {"size", "color"} | PLACED, "cylinder": {"d", "h", "axis", "color"} | PLACED,
    "turntable": {"dia", "thk", "height", "stations", "fixture_radius", "fixture", "start_angle", "direction",
                  "drive", "product", "center_plate"} | PLACED,
    "linear_module": {"stroke", "width", "height", "pos", "vertical", "payload"} | PLACED,
    "pick_place": {"from", "to", "z_stroke", "side", "margin", "nozzle_len", "drive", "pos", "center",
                   "post_at", "post_side", "x_speed", "z_speed"},
    "cylinder_actuator": ACT, "probe": ACT,
    "camera": OVER | {"wd", "fov"}, "spindle": OVER | {"gap", "z_stroke", "chuck_d"},
    "press": OVER | {"gap", "bore", "stroke"}, "tool": OVER | {"gap", "size"},
    "bowl_feeder": {"bowl_d", "bowl_h", "base_h", "track_len", "track_z", "product"} | PLACED,
    "magazine": {"product", "height", "tube_h", "stroke", "bore", "tubes"} | PLACED,
    "conveyor": {"length", "width", "height"} | PLACED, "chute": {"from", "to", "width", "wall_h"},
    "bin": {"size", "color", "share"} | PLACED, "tray": {"size", "color"} | PLACED,
    "product": {"product", "shape", "od", "id", "h", "d", "size"} | PLACED,
    "light_curtain": {"span", "height", "z0", "min_distance"} | PLACED, "hmi": {"arm"} | PLACED,
    "tower_light": {"pole"} | PLACED,
    "scara": {"at", "targets", "reach", "a1", "a2", "z_stroke", "tool_len", "clear", "elbow", "pose", "sweep"},
}


def print_types():
    print("| 类型 | 中文 | 主要参数 | 锚点 |\n|---|---|---|---|")
    for t, (params, anchors) in CATALOG.items():
        print(f"| {t} | {TYPES[t][1]} | {params.replace('|', '\\|')} | {anchors} |")
    print("\n点位写法: [x,y] / [x,y,z] / \"组件ID.锚点\" / {\"ref\": \"tt.S2\", \"out\": 6, \"up\": -1.5, "
          "\"offset\": [dx,dy,dz]}  (out = 沿组件中心向外的水平距离)")


# ---------------------------------------------------------------- layout build

class Comp:
    def __init__(self, spec, b, pose):
        self.id, self.type, self.spec = spec["id"], spec["type"], spec
        self.name = spec.get("name") or TYPES[self.type][1]
        self.type_cn = TYPES[self.type][1]
        self.pose = pose
        R, t = rot_z(pose[3]), pose[:3]
        self.local_parts = b.parts
        self.parts = [p.moved(R, t) for p in b.parts]
        self.anchors = {k: vadd(mvec(R, v), t) for k, v in b.anchors.items()}
        self.lines = [[vadd(mvec(R, v), t) for v in ln] for ln in b.lines]
        self.params, self.notes, self.color, self.calc, self.meta = b.params, b.notes, b.main, b.calc, b.meta
        self.touch = set(spec.get("touch", []))
        self.riders = set()  # 装在本组件滑台上、随之运动的组件
        boxes = [p.aabb() for p in self.parts if not p.viewer_only] or [p.aabb() for p in self.parts]
        self.lo = [min(bx[0][i] for bx in boxes) for i in range(3)]
        self.hi = [max(bx[1][i] for bx in boxes) for i in range(3)]


def make_resolver(anchors, cid):
    def P(spec, what="at"):
        if spec is None:
            raise SpecError(f"组件 {cid}: 缺少 {what}")
        if isinstance(spec, str):
            if spec in anchors:
                return anchors[spec]
            if "." not in spec:
                raise SpecError(f"组件 {cid}: 锚点 '{spec}' 应写成 组件ID.锚点名")
            raise Unresolved(spec)
        if isinstance(spec, (list, tuple)) and len(spec) in (2, 3) and \
                all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in spec):
            return (float(spec[0]), float(spec[1]), float(spec[2]) if len(spec) == 3 else 0.0)
        if isinstance(spec, dict) and "ref" in spec:
            x, y, z = P(spec["ref"], what)
            if "out" in spec:
                if "center" in spec:
                    cen = P(spec["center"], what)
                else:
                    ref = spec["ref"]
                    cen = anchors.get(ref.split(".")[0] + ".center", (0, 0, 0)) if isinstance(ref, str) else (0, 0, 0)
                vx, vy = x - cen[0], y - cen[1]
                d = math.hypot(vx, vy)
                if d < 1e-6:
                    raise SpecError(f"组件 {cid}: {what} 的 out 需要点不在中心")
                x, y = x + vx / d * float(spec["out"]), y + vy / d * float(spec["out"])
            z += float(spec.get("up", 0))
            off = spec.get("offset") or [0, 0, 0]
            return (x + off[0], y + off[1], z + (off[2] if len(off) > 2 else 0))
        raise SpecError(f"组件 {cid}: {what} 格式错误: {spec!r} (应为 [x,y]、[x,y,z]、'组件.锚点' 或 {{ref,out,up,offset}})")
    return P


def build_layout(spec):
    comps_spec = spec.get("components")
    if not isinstance(comps_spec, list) or not comps_spec:
        raise SpecError("JSON 需要非空的 components 列表")
    seen = set()
    for cs in comps_spec:
        if not isinstance(cs, dict) or "id" not in cs or "type" not in cs:
            raise SpecError(f"组件缺少 id 或 type: {cs}")
        if cs["id"] in seen:
            raise SpecError(f"组件 id 重复: {cs['id']}")
        if cs["type"] not in TYPES:
            raise SpecError(f"组件 {cs['id']}: 未知类型 {cs['type']} (可用: {', '.join(TYPES)})")
        if "." in str(cs["id"]):
            raise SpecError(f"组件 id 不能含 '.': {cs['id']}")
        seen.add(cs["id"])
    anchors, built, pending = {}, {}, list(comps_spec)
    while pending:
        nxt, missing = [], {}
        for cs in pending:
            b = Builder()
            try:
                pose = TYPES[cs["type"]][0](cs, make_resolver(anchors, cs["id"]), b)
            except Unresolved as e:
                nxt.append(cs)
                missing[cs["id"]] = str(e)
                continue
            comp = Comp(cs, b, pose)
            built[cs["id"]] = comp
            anchors.update({f"{comp.id}.{k}": v for k, v in comp.anchors.items()})
        if len(nxt) == len(pending):
            raise SpecError("无法解析的锚点: " + "; ".join(f"{k} → {v}" for k, v in missing.items()))
        pending = nxt
    ids = {cs["id"] for cs in comps_spec}
    specs = {cs["id"]: cs for cs in comps_spec}

    def mount(cid):
        v = specs[cid].get("at")
        v = v.get("ref") if isinstance(v, dict) else v
        return tuple(v.split(".", 1)) if isinstance(v, str) and "." in v else None
    for cid in ids:
        cur, seen = cid, set()
        while cur in specs and cur not in seen:
            seen.add(cur)
            m = mount(cur)
            if m is None:
                break
            if m[1] == "carriage" and m[0] in built:
                built[m[0]].riders.add(cid)
            cur = m[0]
    for cs in comps_spec:
        comp = built[cs["id"]]
        allowed = COMMON_KEYS | ALLOWED[cs["type"]]
        bad = [k for k in cs if not k.startswith("_") and k not in allowed]
        if bad:
            hint = "; at/rot 对该类型无效, 位置由 from/to/tip/target 决定" if {"at", "rot"} & set(bad) else ""
            comp.notes.insert(0, ("注意", f"未知参数 {', '.join(bad)} 已忽略 (可用: "
                                         f"{', '.join(sorted(ALLOWED[cs['type']]))}){hint}"))
        missing = [x for x in cs.get("touch", []) if x not in ids]
        if missing:
            comp.notes.insert(0, ("注意", f"touch 中的组件不存在: {', '.join(map(str, missing))}"))
    return [built[cs["id"]] for cs in comps_spec], anchors


# ---------------------------------------------------------------- checks

def hull(p, n=16):
    """凸包近似: (顶点, 面法向, 棱方向). 圆柱/圆锥/圆管按 16 棱柱 (管忽略内孔)."""
    cols = [tuple(p.R[i][j] for i in range(3)) for j in range(3)]
    if p.geo == "box":
        return mesh(p, 4)[0], cols, cols
    g, d = p.geo, p.dims
    r1, r2, h = (d[0], d[0], d[1]) if g == "cyl" else ((d[0], d[0], d[2]) if g == "tube" else d)
    V = [vadd(mvec(p.R, v), p.c) for v in ring(r1, -h / 2, n) + ring(r2, h / 2, n)]
    side = [mvec(p.R, (math.cos(2 * math.pi * (k + 0.5) / n), math.sin(2 * math.pi * (k + 0.5) / n), 0.0))
            for k in range(n // 2)]
    tang = [mvec(p.R, (-math.sin(2 * math.pi * (k + 0.5) / n), math.cos(2 * math.pi * (k + 0.5) / n), 0.0))
            for k in range(n // 2)]
    return V, side + [cols[2]], tang + [cols[2]]


def sat_depth(A, B):
    """凸体分离轴检测, 返回最小重叠深度 (<0 表示分离)."""
    va, na, ea = A
    vb, nb, eb = B
    axes = list(na) + list(nb)
    for u in ea:
        for v in eb:
            w = cross(u, v)
            n = math.sqrt(dot(w, w))
            if n > 1e-6:
                axes.append((w[0] / n, w[1] / n, w[2] / n))
    best = float("inf")
    for L in axes:
        pa = [dot(v, L) for v in va]
        pb = [dot(v, L) for v in vb]
        ov = min(max(pa), max(pb)) - max(min(pa), min(pb))
        if ov < best:
            best = ov
            if best < 0:
                return best
    return best


def check_layout(comps, tol, machine=None):
    issues, ok_notes = [], []
    solid = {c.id: [(p, hull(p), p.aabb()) for p in c.parts if p.sweep or not p.viewer_only] for c in comps}
    box = {}
    for c in comps:
        bs = [x[2] for x in solid[c.id]] or [(c.lo, c.hi)]
        box[c.id] = ([min(b[0][i] for b in bs) for i in range(3)], [max(b[1][i] for b in bs) for i in range(3)])
    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            if b.id in a.touch or a.id in b.touch:
                continue
            (alo, ahi), (blo, bhi) = box[a.id], box[b.id]
            if any(ahi[k] < blo[k] - tol or bhi[k] < alo[k] - tol for k in range(3)):
                continue
            worst = None
            for pa, oa, ba in solid[a.id]:
                for pb, ob, bb in solid[b.id]:
                    if pa.sweep and pb.sweep:
                        continue
                    if {pa.tag, pb.tag} == {"push", "product"}:
                        continue
                    if (pa.sweep and b.id in a.riders) or (pb.sweep and a.id in b.riders):
                        continue
                    if any(ba[1][k] < bb[0][k] + tol or bb[1][k] < ba[0][k] + tol for k in range(3)):
                        continue
                    d = sat_depth(oa, ob)
                    if d > tol and (worst is None or d > worst[0]):
                        worst = (d, pa.name, pb.name, pa.sweep or pb.sweep)
            if worst:
                kind = ("遮挡光栅保护区 (光栅会一直被触发)" if "保护区域" in (worst[1], worst[2]) else
                        "运动干涉 (动作过程中会碰)" if worst[3] else "可能干涉")
                issues.append(("注意", f"{kind}: {a.name} ({a.id}) 的「{worst[1]}」与 {b.name} ({b.id}) 的"
                                       f"「{worst[2]}」重叠约 {worst[0]:.1f} mm"))
    frame = next((c for c in comps if c.type == "frame"), None)
    if frame:
        x0, x1, y0, y1 = frame.spec["_plate"]
        fx, fy = frame.pose[0], frame.pose[1]
        for c in comps:
            if c.type in NO_PLATE_CHECK:
                continue
            if c.lo[0] < fx + x0 - 1 or c.hi[0] > fx + x1 + 1 or c.lo[1] < fy + y0 - 1 or c.hi[1] > fy + y1 + 1:
                issues.append(("注意", f"{c.name} ({c.id}) 超出台面范围"))
    enc = next((c for c in comps if c.type == "enclosure"), None)
    if enc:
        hz = enc.pose[2] + enc.spec["_height"]
        for c in comps:
            if c.type not in NO_PLATE_CHECK and c.hi[2] > hz:
                issues.append(("注意", f"{c.name} ({c.id}) 顶部 {c.hi[2]:.0f} mm 高于防护罩 {hz:.0f} mm"))
    for lc in (c for c in comps if c.type == "light_curtain"):
        Ri, span, best = rot_z(-lc.pose[3]), float(lc.spec.get("span", 800)), None
        for c in comps:
            for p in c.parts:
                if not p.sweep or p.tag == "field":
                    continue
                loc = [mvec(Ri, vsub(v, lc.pose[:3])) for v in hull(p)[0]]
                if max(v[0] for v in loc) < -span / 2 - 300 or min(v[0] for v in loc) > span / 2 + 300:
                    continue
                d = min(v[1] for v in loc)
                if best is None or d < best[0]:
                    best = (d, c, p)
        if best is None:
            continue
        d, c, p = best
        need = lc.spec.get("min_distance")
        where = f"{lc.name}: 到最近运动件 {c.name} ({c.id})「{p.name}」水平距离 {d:.0f} mm"
        if d < 0:
            issues.append(("NG", f"{lc.name}: 运动件 {c.name} ({c.id})「{p.name}」伸到光栅外侧 {-d:.0f} mm"))
        elif need:
            issues.append(("OK" if d >= need else "NG", f"{where} {'≥' if d >= need else '<'} 安全距离 {need:g} mm"))
        else:
            issues.append(("注意", f"{where}; 须 ≥ mech_calc.py safety 算出的安全距离 S (填 min_distance 可自动比对)"))
    issues += machine_checks(comps, machine or {})
    for c in comps:
        issues += [(lv, f"{c.name} ({c.id}): {m}") for lv, m in c.notes]
    if not any("干涉" in m or "遮挡光栅" in m for _, m in issues):
        ok_notes.append(("OK", f"未发现组件间静态干涉和取放运动干涉 (容差 {tol:g} mm, 圆柱按 16 棱柱近似)"))
    return ok_notes + issues


TOP_KEYS = {"title", "components", "uph", "product", "refill_min", "note"}


def product_volume(prod):
    s = prod.get("shape", "ring")
    if s == "ring":
        return math.pi / 4 * (prod["od"] ** 2 - prod["id"] ** 2) * prod["h"]
    if s == "disc":
        return math.pi / 4 * prod["d"] ** 2 * prod["h"]
    sx, sy, sz = prod["size"]
    return sx * sy * sz


def machine_checks(comps, machine):
    """整机级检查: 补料/倒料间隔 (需要 uph), 人工操作点是否在防护区内、是否便于操作."""
    out = []
    uph = machine.get("uph")
    refill = float(machine.get("refill_min", 30))
    prod = machine.get("product")
    if uph:
        for c in comps:
            if c.type == "magazine":
                cap = c.meta["capacity"]
                m = cap / uph * 60
                ok = m >= refill
                out.append(("OK" if ok else "注意", f"{c.name} ({c.id}): 容量约 {cap} pcs, 按 {uph:g} UPH 每 {m:.1f} min 补料一次"
                            + ("" if ok else f" (< {refill:g} min: 加长料管、增加料管数 tubes、或改料仓/振动盘)")))
            elif c.type == "bin":
                if not prod:
                    out.append(("注意", f"{c.name} ({c.id}): 顶层未填 product, 无法计算倒料间隔"))
                    continue
                cap = int(c.meta["volume"] * 0.4 / product_volume(prod))
                share = c.meta["share"]
                m = cap / (uph * share) * 60
                ok = m >= refill
                hint = "" if ok else (" (加大料盒、改料箱/皮带出料)" if share < 1 else
                                      " (若为 NG 料盒请填 share, 如 0.02)")
                out.append(("OK" if ok else "注意", f"{c.name} ({c.id}): 约装 {cap} pcs (堆积系数 0.4), 流入 {share:.0%}, "
                                                    f"每 {m:.0f} min 倒料一次" + ("" if ok else f" < {refill:g} min") + hint))
    enc = next((c for c in comps if c.type == "enclosure"), None)
    frame = next((c for c in comps if c.type == "frame"), None)
    inside, far = [], []
    for c in comps:
        pt = c.meta.get("manual")
        if pt is None:
            continue
        w = vadd(mvec(rot_z(c.pose[3]), pt), c.pose[:3])
        if enc and enc.lo[0] < w[0] < enc.hi[0] and enc.lo[1] < w[1] < enc.hi[1] and w[2] < enc.hi[2]:
            inside.append(c.name)
        if frame:
            depth = w[1] - frame.lo[1]
            height = frame.spec.get("size", [0, 0, 850])[2] + w[2]
            if depth > 600 or height > 1500:
                far.append(f"{c.name} (距台面前沿 {depth:.0f} mm, 离地 {height:.0f} mm)")
    if inside:
        out.append(("注意", "需人工补料/倒料的位置在防护区内: " + "、".join(inside)
                    + " — 操作时会触发光栅/门禁停机; 按补料间隔评估停机损失, 或改外置抽屉/门外补料口/不停机换料"))
    if far:
        out.append(("注意", "人工操作点不便操作 (建议距前沿 ≤ 600 mm、离地 ≤ 1500 mm): " + "、".join(far)))
    return out


def io_estimate(c):
    """按组件类型估算 IO、轴数和主要外购件 (方案阶段, 用于控制器选型和成本)."""
    s, t = c.spec, c.type
    di = do = sv = sf = com = 0
    parts = []
    if t == "frame":
        sf, di, parts = 2, 3, ["急停按钮 ×2", "启动/停止/复位按钮"]
    elif t == "enclosure":
        sf, parts = 2, ["安全门开关 ×2", "铝型材+亚克力/钢化玻璃"]
    elif t == "turntable":
        drive = s.get("drive", "dd")
        if drive == "indexer":
            do, di, parts = 1, 2, ["凸轮分割器", "刹车减速电机", "分度到位/原点传感器"]
        else:
            sv, di = 1, 1
            parts = ["DD 马达+驱动器"] if drive == "dd" else ["伺服电机+精密减速机"]
        di += int(s.get("stations", 6))
        parts.append(f"治具有无料传感器 ×{int(s.get('stations', 6))}")
    elif t == "linear_module":
        sv, di, parts = 1, 3, [f"直线模组 行程 {s.get('stroke', 300):g} + 伺服", "原点/限位传感器 ×3"]
    elif t == "pick_place":
        if s.get("drive", "cylinder") == "module":
            sv, di, do = 2, 4 + 1, 2
            parts = ["X/Z 伺服模组", "吸盘+真空发生器+真空开关"]
        else:
            di, do = 5, 4
            parts = ["X 无杆/滑台气缸", "Z 滑台气缸", "电磁阀 ×2", "磁性开关 ×4", "吸盘+真空发生器+真空开关"]
    elif t in ("cylinder_actuator", "probe"):
        do, di = 1, 2
        parts = [f"气缸 Φ{s.get('bore', 10 if t == 'probe' else 16):g}×{s.get('stroke', 10 if t == 'probe' else 20):g}",
                 "电磁阀", "磁性开关 ×2"]
        if t == "probe" or s.get("head") == "probe":
            com, parts = 1, parts + ["测头/霍尔探头 + 采集 (高斯计/采集卡)"]
    elif t == "camera":
        com, do, parts = 1, 1, ["工业相机+镜头", "环形光源+光源控制器"]
    elif t == "spindle":
        sv, do, di, parts = 1, 1, 2, ["旋转伺服+主轴", "Z 滑台气缸+电磁阀", "磁性开关 ×2"]
    elif t == "press":
        do, di, com, parts = 1, 2, 1, ["压装气缸/伺服压机", "压力传感器"]
    elif t == "tool":
        do, di, parts = 1, 1, ["执行单元 (点胶/扫码/打标)"]
    elif t == "bowl_feeder":
        do, di, parts = 3, 4, ["振动盘+直振+控制器", "分料气缸", "满料/缺料光纤 ×2"]
    elif t == "magazine":
        do, di, parts = 1, 4, ["推料气缸+电磁阀", "磁性开关 ×2", "有料/缺料传感器 ×2"]
        if c.meta.get("tubes", 1) > 1:
            do, di, parts = do + 1, di + 2, parts + ["换管机构 (气缸)"]
    elif t == "conveyor":
        do, di, parts = 1, 2, ["皮带线", "调速/减速电机", "入口/出口光电 ×2"]
    elif t == "chute":
        di, parts = 1, ["落料确认传感器"]
    elif t == "bin":
        di, parts = 1, ["料盒在位/满料传感器"]
    elif t == "tray":
        di, parts = 1, ["料盘在位传感器"]
    elif t == "light_curtain":
        sf, parts = 1, ["安全光栅 (一对)"]
    elif t == "hmi":
        com, parts = 1, ["触摸屏"]
    elif t == "tower_light":
        do, parts = 4, ["三色灯+蜂鸣器"]
    elif t == "scara":
        com, di, do, parts = 1, 3, 4, ["SCARA 机器人+控制器", "末端吸盘/夹爪+真空"]
    return {"DI": di, "DO": do, "伺服轴": sv, "安全输入": sf, "通讯/模拟量": com, "外购件": parts}


def io_summary(comps):
    rows = [(c, io_estimate(c)) for c in comps]
    tot = {k: sum(r[k] for _, r in rows) for k in ("DI", "DO", "伺服轴", "安全输入", "通讯/模拟量")}
    return rows, tot


# ---------------------------------------------------------------- meshes

def ring(r, z, n):
    return [(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n), z) for k in range(n)]


def mesh(p, n):
    """返回 (顶点, 面). 面 = [外环, 内环...], 外环从实体外侧看为逆时针."""
    g, d = p.geo, p.dims
    if g == "box":
        sx, sy, sz = d
        V = [((1 if i & 1 else -1) * sx / 2, (1 if i & 2 else -1) * sy / 2, (1 if i & 4 else -1) * sz / 2)
             for i in range(8)]
        F = [[[0, 2, 3, 1]], [[4, 5, 7, 6]], [[0, 1, 5, 4]], [[2, 6, 7, 3]], [[0, 4, 6, 2]], [[1, 3, 7, 5]]]
    elif g in ("cyl", "cone"):
        r1, r2, h = (d[0], d[0], d[1]) if g == "cyl" else d
        V = ring(r1, -h / 2, n) + ring(r2, h / 2, n)
        F = [[list(range(n - 1, -1, -1))], [list(range(n, 2 * n))]]
        F += [[[k, (k + 1) % n, n + (k + 1) % n, n + k]] for k in range(n)]
    else:
        ro, ri, h = d
        V = ring(ro, -h / 2, n) + ring(ro, h / 2, n) + ring(ri, -h / 2, n) + ring(ri, h / 2, n)
        F = [[[k, (k + 1) % n, n + (k + 1) % n, n + k]] for k in range(n)]
        F += [[[2 * n + k, 3 * n + k, 3 * n + (k + 1) % n, 2 * n + (k + 1) % n]] for k in range(n)]
        F.append([list(range(n, 2 * n)), list(range(4 * n - 1, 3 * n - 1, -1))])
        F.append([list(range(n - 1, -1, -1)), list(range(2 * n, 3 * n))])
    return [vadd(mvec(p.R, v), p.c) for v in V], F


def triangles(V, F):
    out = []
    for loops in F:
        o = loops[0]
        if len(loops) == 1:
            out += [(V[o[0]], V[o[k]], V[o[k + 1]]) for k in range(1, len(o) - 1)]
        else:
            i = loops[1][::-1]
            n = len(o)
            for k in range(n):
                k1 = (k + 1) % n
                out += [(V[o[k]], V[o[k1]], V[i[k1]]), (V[o[k]], V[i[k1]], V[i[k]])]
    return out


def newell(V, loop):
    nx = ny = nz = 0.0
    for k in range(len(loop)):
        a, b = V[loop[k]], V[loop[(k + 1) % len(loop)]]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    return unit((nx, ny, nz))


# ---------------------------------------------------------------- STEP export

def sreal(v):
    if abs(v) < 5e-10:
        v = 0.0
    return f"{v:.6f}".rstrip("0")


def sdir(v):
    return f"{v:.10f}".rstrip("0") if abs(v) >= 5e-12 else "0."


def sstr(s):
    out, buf = [], []

    def flush():
        if buf:
            out.append("\\X2\\" + "".join(f"{ord(ch):04X}" for ch in buf) + "\\X0\\")
            buf.clear()
    for ch in str(s):
        o = ord(ch)
        if 32 <= o < 127:
            flush()
            out.append("''" if ch == "'" else ("\\\\" if ch == "\\" else ch))
        else:
            buf.append(ch if o <= 0xFFFF else "?")
    flush()
    return "'" + "".join(out) + "'"


class StepWriter:
    def __init__(self):
        self.ents = []

    def add(self, text):
        self.ents.append(text)
        return f"#{len(self.ents)}"

    def reserve(self):
        self.ents.append(None)
        return f"#{len(self.ents)}"

    def put(self, ref, text):
        self.ents[int(ref[1:]) - 1] = text

    def point(self, p):
        return self.add(f"CARTESIAN_POINT('',({sreal(p[0])},{sreal(p[1])},{sreal(p[2])}))")

    def direction(self, d):
        return self.add(f"DIRECTION('',({sdir(d[0])},{sdir(d[1])},{sdir(d[2])}))")

    def axis(self, loc, z=(0.0, 0.0, 1.0), x=(1.0, 0.0, 0.0)):
        return self.add(f"AXIS2_PLACEMENT_3D('',{self.point(loc)},{self.direction(z)},{self.direction(x)})")

    def solid(self, name, V, F):
        pts = [self.point(v) for v in V]
        vps = [self.add(f"VERTEX_POINT('',{p})") for p in pts]
        edges = {}

        def oedge(a, b):
            key = (min(a, b), max(a, b))
            if key not in edges:
                seg = vsub(V[b], V[a])
                length = math.sqrt(dot(seg, seg))
                vec = self.add(f"VECTOR('',{self.direction(vmul(seg, 1 / length))},{sreal(length)})")
                line = self.add(f"LINE('',{pts[a]},{vec})")
                edges[key] = (self.add(f"EDGE_CURVE('',{vps[a]},{vps[b]},{line},.T.)"), a)
            ec, first = edges[key]
            return self.add(f"ORIENTED_EDGE('',*,*,{ec},{'.T.' if first == a else '.F.'})")

        faces = []
        for loops in F:
            outer = loops[0]
            nrm = newell(V, outer)
            xd = vsub(V[outer[1]], V[outer[0]])
            xd = unit(vsub(xd, vmul(nrm, dot(xd, nrm))))
            ax = self.add(f"AXIS2_PLACEMENT_3D('',{pts[outer[0]]},{self.direction(nrm)},{self.direction(xd)})")
            plane = self.add(f"PLANE('',{ax})")
            bounds = []
            for k, loop in enumerate(loops):
                oes = [oedge(loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))]
                el = self.add(f"EDGE_LOOP('',({','.join(oes)}))")
                bounds.append(self.add(f"{'FACE_OUTER_BOUND' if k == 0 else 'FACE_BOUND'}('',{el},.T.)"))
            faces.append(self.add(f"ADVANCED_FACE('',({','.join(bounds)}),{plane},.T.)"))
        shell = self.add(f"CLOSED_SHELL('',({','.join(faces)}))")
        return self.add(f"MANIFOLD_SOLID_BREP({sstr(name)},{shell})")


def up_map(up):
    """Z 向上的布局坐标 → 输出坐标. up=y 时 (x, y, z) → (x, z, -y), SolidWorks/Creo 正视图 = 操作者正面."""
    return (lambda v: (v[0], v[2], -v[1])) if up == "y" else (lambda v: v)


def write_step(path, title, comps, nseg=24, flat=False, up="y"):
    U = up_map(up)
    w = StepWriter()
    app = w.add("APPLICATION_CONTEXT('core data for automotive mechanical design processes')")
    w.add(f"APPLICATION_PROTOCOL_DEFINITION('international standard','automotive_design',2000,{app})")
    pc = w.add(f"PRODUCT_CONTEXT('',{app},'mechanical')")
    pdc = w.add(f"PRODUCT_DEFINITION_CONTEXT('part definition',{app},'design')")
    lu = w.add("(LENGTH_UNIT()NAMED_UNIT(*)SI_UNIT(.MILLI.,.METRE.))")
    au = w.add("(NAMED_UNIT(*)PLANE_ANGLE_UNIT()SI_UNIT($,.RADIAN.))")
    su = w.add("(NAMED_UNIT(*)SI_UNIT($,.STERADIAN.)SOLID_ANGLE_UNIT())")
    unc = w.add(f"UNCERTAINTY_MEASURE_WITH_UNIT(LENGTH_MEASURE(1.E-07),{lu},'distance_accuracy_value',"
                "'confusion accuracy')")
    ctx = w.add(f"(GEOMETRIC_REPRESENTATION_CONTEXT(3)GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT(({unc}))"
                f"GLOBAL_UNIT_ASSIGNED_CONTEXT(({lu},{au},{su}))REPRESENTATION_CONTEXT('Context #1',"
                "'3D Context with UNIT and UNCERTAINTY'))")
    styles, styled = {}, []

    def product(name):
        p = w.add(f"PRODUCT({sstr(name)},{sstr(name)},'',({pc}))")
        w.add(f"PRODUCT_RELATED_PRODUCT_CATEGORY('part',$,({p}))")
        pdf = w.add(f"PRODUCT_DEFINITION_FORMATION('','',{p})")
        pd = w.add(f"PRODUCT_DEFINITION('design','',{pdf},{pdc})")
        return pd, w.add(f"PRODUCT_DEFINITION_SHAPE('','',{pd})")

    def style(hexcol):
        if hexcol not in styles:
            r, g, b = (int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))
            col = w.add(f"COLOUR_RGB('',{sreal(r)},{sreal(g)},{sreal(b)})")
            fac = w.add(f"FILL_AREA_STYLE_COLOUR('',{col})")
            fas = w.add(f"FILL_AREA_STYLE('',({fac}))")
            ssfa = w.add(f"SURFACE_STYLE_FILL_AREA({fas})")
            sss = w.add(f"SURFACE_SIDE_STYLE('',({ssfa}))")
            ssu = w.add(f"SURFACE_STYLE_USAGE(.BOTH.,{sss})")
            styles[hexcol] = w.add(f"PRESENTATION_STYLE_ASSIGNMENT(({ssu}))")
        return styles[hexcol]

    def solids(parts):
        out = []
        for p in parts:
            if p.viewer_only:
                continue
            V, F = mesh(p, nseg)
            if flat:
                V = [U(v) for v in V]
            brep = w.solid(p.name, V, F)
            styled.append(w.add(f"STYLED_ITEM('color',({style(p.color)}),{brep})"))
            out.append(brep)
        return out

    if flat:
        pd, pds = product(title)
        breps = []
        for c in comps:
            breps += solids(c.parts)
        absr = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({sstr(title)},({','.join([w.axis((0, 0, 0))] + breps)}),{ctx})")
        w.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{absr})")
    else:
        pd_root, pds_root = product(title)
        sr_root = w.reserve()
        root_items = [w.axis((0, 0, 0))]
        for k, c in enumerate(comps, start=1):
            breps = solids(c.local_parts)
            if not breps:
                continue
            name = f"{c.name} ({c.id})"
            pd, pds = product(name)
            ax0 = w.axis((0, 0, 0))
            absr = w.add(f"ADVANCED_BREP_SHAPE_REPRESENTATION({sstr(name)},({','.join([ax0] + breps)}),{ctx})")
            w.add(f"SHAPE_DEFINITION_REPRESENTATION({pds},{absr})")
            a = math.radians(c.pose[3])
            axp = w.axis(U(c.pose[:3]), U((0.0, 0.0, 1.0)), U((math.cos(a), math.sin(a), 0.0)))
            root_items.append(axp)
            nauo = w.add(f"NEXT_ASSEMBLY_USAGE_OCCURRENCE('{k}',{sstr(name)},'',{pd_root},{pd},$)")
            pdsn = w.add(f"PRODUCT_DEFINITION_SHAPE('Placement','Placement of an item',{nauo})")
            idt = w.add(f"ITEM_DEFINED_TRANSFORMATION('','',{ax0},{axp})")
            rr = w.add(f"(REPRESENTATION_RELATIONSHIP('','',{absr},{sr_root})"
                       f"REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION({idt})SHAPE_REPRESENTATION_RELATIONSHIP())")
            w.add(f"CONTEXT_DEPENDENT_SHAPE_REPRESENTATION({rr},{pdsn})")
        w.put(sr_root, f"SHAPE_REPRESENTATION({sstr(title)},({','.join(root_items)}),{ctx})")
        w.add(f"SHAPE_DEFINITION_REPRESENTATION({pds_root},{sr_root})")
    if styled:
        w.add(f"MECHANICAL_DESIGN_GEOMETRIC_PRESENTATION_REPRESENTATION('',({','.join(styled)}),{ctx})")

    stamp = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("ISO-10303-21;\nHEADER;\n")
        f.write("FILE_DESCRIPTION(('concept layout generated by layout3d.py'),'2;1');\n")
        f.write(f"FILE_NAME({sstr(os.path.basename(path))},'{stamp}',(''),(''),'layout3d.py','layout3d.py','');\n")
        f.write("FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'));\nENDSEC;\nDATA;\n")
        for i, e in enumerate(w.ents, start=1):
            f.write(f"#{i}={e};\n")
        f.write("ENDSEC;\nEND-ISO-10303-21;\n")
    return len(w.ents)


def write_stl(path, comps, nseg=32, up="y"):
    U = up_map(up)
    tris = []
    for c in comps:
        for p in c.parts:
            if not p.viewer_only:
                V, F = mesh(p, nseg)
                tris += triangles([U(v) for v in V], F)
    with open(path, "wb") as f:
        f.write(b"layout3d.py concept layout".ljust(80, b" "))
        f.write(struct.pack("<I", len(tris)))
        for a, b, c in tris:
            n = cross(vsub(b, a), vsub(c, a))
            ln = math.sqrt(dot(n, n)) or 1.0
            f.write(struct.pack("<12fH", n[0] / ln, n[1] / ln, n[2] / ln, *a, *b, *c, 0))
    return len(tris)


# ---------------------------------------------------------------- static PNG views (no browser needed)

NO_IMAGE = {"enclosure", "light_curtain", "hmi", "tower_light"}
DIGITS = {"0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
          "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
          "8": "111101111101111", "9": "111101111001111"}
VIEW_CN = {"iso": "轴测", "top": "俯视", "front": "正视", "right": "右视"}


def balloon_numbers(comps):
    """图号: 除机架/防护罩/光栅外按组件顺序编号, PNG 气泡与报告图号表一致."""
    nums, k = {}, 0
    for c in comps:
        if c.type not in NO_IMAGE and c.type != "frame":
            k += 1
            nums[c.id] = k
    return nums


def view_basis(view):
    if view == "top":
        return (0.0, 0.0, -1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
    if view == "front":
        return (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)
    if view == "right":
        return (-1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    f = vmul(unit((-1.0, -1.0, 0.9)), -1.0)
    r = unit(cross(f, (0.0, 0.0, 1.0)))
    return f, r, cross(r, f)


def render_png(path, comps, view="iso", width=1600, include_all=False, fit="work"):
    """正交投影 + z 缓冲 + 平面着色 + 轮廓线 + 图号气泡, 仅用标准库写 PNG. 返回 (宽, 高)."""
    import array
    import zlib
    f, r, u = view_basis(view)
    light = unit(vadd(vadd(vmul(r, -0.4), vmul(u, 0.7)), vmul(f, -0.6)))
    tris, tcol, tnorm, tpid, fit_pts = [], [], [], [], []
    pid = 0
    work = [c for c in comps if c.type not in NO_PLATE_CHECK]
    for c in comps:
        if c.type in NO_IMAGE and not include_all:
            continue
        use_fit = fit == "all" or not work or c.type not in NO_PLATE_CHECK
        for p in c.parts:
            if p.viewer_only:
                continue
            pid += 1
            rgb = tuple(int(p.color[i:i + 2], 16) for i in (1, 3, 5))
            V, F = mesh(p, 32)
            if use_fit:
                fit_pts += [(dot(v, r), dot(v, u)) for v in V]
            for a, b, d in triangles(V, F):
                n = cross(vsub(b, a), vsub(d, a))
                ln = math.sqrt(dot(n, n))
                if ln < 1e-12:
                    continue
                n = vmul(n, 1 / ln)
                if dot(n, f) >= 0:
                    continue
                k = 0.42 + 0.58 * max(0.0, dot(n, light))
                tris.append([(dot(v, r), dot(v, u), dot(v, f)) for v in (a, b, d)])
                tcol.append(bytes(min(255, int(ch * k)) for ch in rgb))
                tnorm.append(n)
                tpid.append(pid)
    if not tris:
        raise SpecError("没有可渲染的零件")
    xs = [v[0] for v in fit_pts] or [v[0] for tr in tris for v in tr]
    ys = [v[1] for v in fit_pts] or [v[1] for tr in tris for v in tr]
    margin = 40
    sc = (width - 2 * margin) / max(max(xs) - min(xs), 1e-6)
    height = int((max(ys) - min(ys)) * sc + 2 * margin)
    if height > width * 1.3:
        sc *= width * 1.3 / height
        height = int((max(ys) - min(ys)) * sc + 2 * margin)
    x0, y1 = min(xs), max(ys)
    W, H = width, height
    zb = array.array("d", [float("inf")]) * (W * H)
    tb = array.array("i", [-1]) * (W * H)
    for ti, tr in enumerate(tris):
        P = [((v[0] - x0) * sc + margin, (y1 - v[1]) * sc + margin, v[2]) for v in tr]
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = P
        e1x, e1y, e1z, e2x, e2y, e2z = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
        nz = e1x * e2y - e1y * e2x
        if abs(nz) < 1e-9:
            continue
        A = -(e1y * e2z - e1z * e2y) / nz
        B = -(e1z * e2x - e1x * e2z) / nz
        jmin = max(0, int(math.ceil(min(ay, by, cy) - 0.5)))
        jmax = min(H - 1, int(math.floor(max(ay, by, cy) - 0.5)))
        edges = ((ax, ay, bx, by), (bx, by, cx, cy), (cx, cy, ax, ay))
        for j in range(jmin, jmax + 1):
            yc = j + 0.5
            xl, xr = float("inf"), -float("inf")
            for sx, sy, ex, ey in edges:
                if (sy <= yc <= ey or ey <= yc <= sy) and sy != ey:
                    x = sx + (yc - sy) * (ex - sx) / (ey - sy)
                    xl, xr = min(xl, x), max(xr, x)
            i0 = max(0, int(math.ceil(xl - 0.5)))
            i1 = min(W - 1, int(math.floor(xr - 0.5)))
            if i1 < i0:
                continue
            z = az + A * (i0 + 0.5 - ax) + B * (yc - ay)
            row = j * W
            for k in range(row + i0, row + i1 + 1):
                if z < zb[k]:
                    zb[k] = z
                    tb[k] = ti
                z += A
    dz = 3.0
    edge = bytearray(W * H)
    for j in range(H):
        row = j * W
        for i in range(W):
            k = row + i
            t0 = tb[k]
            for k2 in ((k + 1) if i + 1 < W else -1, (k + W) if j + 1 < H else -1):
                if k2 < 0:
                    continue
                t2 = tb[k2]
                if t0 == t2:
                    continue
                if t0 < 0 or t2 < 0:
                    edge[k if t0 >= 0 else k2] = 1
                    continue
                if tpid[t0] != tpid[t2] or dot(tnorm[t0], tnorm[t2]) < 0.85 or abs(zb[k] - zb[k2]) > dz:
                    edge[k if zb[k] <= zb[k2] else k2] = 1
    bg = bytes((246, 247, 249))
    img = bytearray()
    for j in range(H):
        img.append(0)
        row = j * W
        for k in range(row, row + W):
            t0 = tb[k]
            if t0 < 0:
                img += bg
            elif edge[k]:
                c0 = tcol[t0]
                img += bytes((c0[0] * 2 // 7, c0[1] * 2 // 7, c0[2] * 2 // 7))
            else:
                img += tcol[t0]
    nums = balloon_numbers(comps)
    s = max(2, W // 700)
    for c in comps:
        if c.id not in nums:
            continue
        lp = ((c.lo[0] + c.hi[0]) / 2, (c.lo[1] + c.hi[1]) / 2, c.hi[2] + 15)
        bx = int((dot(lp, r) - x0) * sc + margin)
        by = int((y1 - dot(lp, u)) * sc + margin)
        txt = str(nums[c.id])
        R = int(len(txt) * 2.2 * s + 4 * s)
        for j in range(max(0, by - R - 1), min(H, by + R + 2)):
            for i in range(max(0, bx - R - 1), min(W, bx + R + 2)):
                d = math.hypot(i - bx, j - by)
                if d <= R:
                    o = j * (3 * W + 1) + 1 + 3 * i
                    img[o:o + 3] = b"\xff\xff\xff" if d < R - 1.6 * s / 2 else b"\xd9\x48\x0f"
        gw = 4 * s
        x = bx - (len(txt) * gw - s) // 2
        for ch in txt:
            bits = DIGITS[ch]
            for jj in range(5):
                for ii in range(3):
                    if bits[jj * 3 + ii] == "1":
                        for dy in range(s):
                            for dx in range(s):
                                yy, xx = by - (5 * s) // 2 + jj * s + dy, x + ii * s + dx
                                if 0 <= yy < H and 0 <= xx < W:
                                    o = yy * (3 * W + 1) + 1 + 3 * xx
                                    img[o:o + 3] = b"\x1f\x29\x33"
            x += gw

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
                 + chunk(b"IDAT", zlib.compress(bytes(img), 6)) + chunk(b"IEND", b""))
    return W, H


# ---------------------------------------------------------------- HTML viewer

def scene_json(title, comps, issues, env):
    r3 = lambda v: round(v, 3)
    work = [c for c in comps if c.type not in NO_PLATE_CHECK] or comps
    lo = [min(c.lo[i] for c in work) for i in range(3)]
    hi = [max(c.hi[i] for c in work) for i in range(3)]
    data = {"title": title, "env": env, "issues": [f"[{lv}] {m}" for lv, m in issues], "comps": [], "lines": [],
            "work": {"center": [r3((lo[i] + hi[i]) / 2) for i in range(3)], "size": [r3(hi[i] - lo[i]) for i in range(3)]}}
    for c in comps:
        parts = []
        for p in c.parts:
            R = p.R
            parts.append({"g": p.geo, "d": [r3(v) for v in p.dims], "c": p.color,
                          "o": p.opacity, "v": 1 if p.viewer_only else 0, "s": 1 if p.sweep else 0,
                          "m": [r3(R[0][0]), r3(R[0][1]), r3(R[0][2]), r3(p.c[0]),
                                r3(R[1][0]), r3(R[1][1]), r3(R[1][2]), r3(p.c[1]),
                                r3(R[2][0]), r3(R[2][1]), r3(R[2][2]), r3(p.c[2])]})
        data["comps"].append({
            "id": c.id, "name": c.name, "type": c.type, "typeCn": c.type_cn, "color": c.color,
            "params": [[k, v] for k, v in c.params],
            "pos": [r3(c.pose[0]), r3(c.pose[1]), r3(c.pose[2])], "rot": r3(c.pose[3]),
            "label": [r3((c.lo[0] + c.hi[0]) / 2), r3((c.lo[1] + c.hi[1]) / 2), r3(c.hi[2] + 25)],
            "center": [r3((c.lo[i] + c.hi[i]) / 2) for i in range(3)],
            "size": [r3(c.hi[i] - c.lo[i]) for i in range(3)], "parts": parts})
        for ln in c.lines:
            data["lines"].append({"comp": c.id, "pts": [[r3(v) for v in p] for p in ln]})
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def write_html(path, title, comps, issues, env, cdn=False):
    if not cdn and os.path.exists(THREE_JS):
        with open(THREE_JS, encoding="utf-8") as f:
            three = "<script>" + f.read().replace("</script", "<\\/script") + "</script>"
    else:
        three = f'<script src="{THREE_CDN[0]}"></script>\n<script>window.THREE||document.write(' \
                f'\'<script src="{THREE_CDN[1]}"><\\/script>\')</script>'
    esc = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = (HTML_TEMPLATE.replace("__TITLE__", esc).replace("__THREE__", three)
            .replace("__SCENE__", scene_json(title, comps, issues, env)))
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#eef1f4;--panel:#fff;--text:#1f2933;--muted:#5f6b7a;--line:#d5dbe1;--sel:#fff1e6;--accent:#e8590c}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--text);font:13px/1.45 "Microsoft YaHei","PingFang SC","Noto Sans CJK SC",system-ui,sans-serif;overflow:hidden}
#top{position:absolute;left:0;right:0;top:0;height:48px;display:flex;align-items:center;gap:6px;padding:0 12px;background:var(--panel);border-bottom:1px solid var(--line);z-index:5;overflow-x:auto;white-space:nowrap}
#top h1{font-size:15px;margin:0 6px 0 0}
#dims{color:var(--muted);margin-right:auto}
button{font:inherit;border:1px solid var(--line);background:#f8f9fa;border-radius:6px;padding:4px 10px;cursor:pointer;color:var(--text)}
button.on{background:#1f2933;color:#fff;border-color:#1f2933}
button.warn{border-color:var(--accent);color:var(--accent)}
#side{position:absolute;left:0;top:48px;bottom:0;width:270px;background:var(--panel);border-right:1px solid var(--line);overflow:auto;z-index:4}
.row{display:flex;align-items:center;gap:6px;padding:5px 10px;border-bottom:1px solid #f1f3f5;cursor:pointer;user-select:none}
.row:hover{background:#f8f9fa}.row.sel{background:var(--sel)}
.row input{margin:0}
.sw{width:10px;height:10px;border-radius:2px;flex:none;border:1px solid rgba(0,0,0,.15)}
.nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag{margin-left:auto;color:var(--muted);font-size:11px;flex:none}
#view{position:absolute;left:270px;right:0;top:48px;bottom:0}
#view canvas{display:block;touch-action:none}
#labels{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.lbl{position:absolute;transform:translate(-50%,-100%);background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:4px;padding:1px 6px;font-size:12px;white-space:nowrap}
.lbl.sel{border-color:var(--accent);color:var(--accent);font-weight:bold}
#info{position:absolute;right:12px;bottom:12px;width:320px;max-height:50%;overflow:auto;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 12px;display:none;z-index:6;box-shadow:0 4px 16px rgba(0,0,0,.08)}
#info h2{font-size:14px;margin:0 0 6px}
#info table{border-collapse:collapse;width:100%}
#info td{padding:3px 4px;border-bottom:1px solid #f1f3f5;vertical-align:top}
#info td:first-child{color:var(--muted);white-space:nowrap}
#info ul{margin:0;padding-left:18px}
#info .x{float:right;border:none;background:none;font-size:16px;padding:0 4px}
#hint{position:absolute;left:12px;bottom:10px;color:var(--muted);font-size:12px;pointer-events:none}
@media (max-width:760px){#side{display:none}#view{left:0}#info{width:calc(100% - 24px)}}
</style>
</head>
<body>
<div id="top">
<h1 id="ttl"></h1><span id="dims"></span>
<button data-view="iso">轴测</button><button data-view="top">俯视</button><button data-view="front">正视</button><button data-view="right">右视</button><button id="bAll">整机</button>
<button id="bOrtho">平行投影</button><button id="bGuard" class="on">防护罩</button><button id="bLbl" class="on">标签</button><button id="bPath" class="on">路径/包络</button><button id="bMeasure">测距</button><button id="bIssue">检查</button><button id="bShot">截图</button>
</div>
<div id="side"></div>
<div id="view"><div id="labels"></div><div id="hint">左键旋转 · 右键/Shift+左键平移 · 滚轮缩放 · 单击选中组件 · 双击居中 · 测距: 依次点两个表面点 (Esc 退出)</div></div>
<div id="info"></div>
__THREE__
<script>
const S = __SCENE__;
(function(){
const $ = s => document.querySelector(s);
$('#ttl').textContent = S.title;
$('#dims').textContent = '外形 ' + S.env.L + ' × ' + S.env.W + ' × ' + S.env.H + ' mm (长×宽×高, 含机架)';
if (!window.THREE) { $('#view').innerHTML = '<div style="padding:24px">three.js 加载失败: 请不加 --cdn 重新生成 (内嵌 three.js, 可离线打开)。</div>'; return; }
const view = $('#view'), labelsEl = $('#labels');
let renderer;
try { renderer = new THREE.WebGLRenderer({antialias: true, preserveDrawingBuffer: true}); }
catch (e) { view.innerHTML = '<div style="padding:24px">浏览器不支持 WebGL, 请换用 Chrome/Edge。</div>'; return; }
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
view.insertBefore(renderer.domElement, labelsEl);
const scene = new THREE.Scene();
scene.background = new THREE.Color('#eef1f4');
scene.add(new THREE.HemisphereLight(0xffffff, 0x8899aa, 0.85));
const d1 = new THREE.DirectionalLight(0xffffff, 0.75); d1.position.set(1, 2, 1.4); scene.add(d1);
const d2 = new THREE.DirectionalLight(0xffffff, 0.3); d2.position.set(-1.5, 1, -1); scene.add(d2);
const root = new THREE.Group(); root.rotation.x = -Math.PI / 2; scene.add(root);
const w2t = p => new THREE.Vector3(p[0], p[2], -p[1]);

const gCache = {}, eCache = {};
function geom(p) {
  const k = p.g + ':' + p.d.join(',');
  if (gCache[k]) return gCache[k];
  const d = p.d; let g;
  if (p.g === 'box') g = new THREE.BoxGeometry(d[0], d[1], d[2]);
  else if (p.g === 'cyl') g = new THREE.CylinderGeometry(d[0], d[0], d[1], 40).rotateX(Math.PI / 2);
  else if (p.g === 'cone') g = new THREE.CylinderGeometry(d[1], d[0], d[2], 40).rotateX(Math.PI / 2);
  else {
    const sh = new THREE.Shape(); sh.absarc(0, 0, d[0], 0, Math.PI * 2, false);
    const hole = new THREE.Path(); hole.absarc(0, 0, d[1], 0, Math.PI * 2, true); sh.holes.push(hole);
    g = new THREE.ExtrudeGeometry(sh, {depth: d[2], bevelEnabled: false, curveSegments: 40}); g.translate(0, 0, -d[2] / 2);
  }
  gCache[k] = g; eCache[k] = new THREE.EdgesGeometry(g, 30); return g;
}
const edgeMat = new THREE.LineBasicMaterial({color: 0x1f2933, transparent: true, opacity: 0.35});
const comps = {}, pickables = [], sweeps = [];
S.comps.forEach(c => {
  const grp = new THREE.Group(); root.add(grp);
  const meshes = [];
  c.parts.forEach(p => {
    const solid = p.o >= 1;
    const mat = new THREE.MeshStandardMaterial({color: p.c, roughness: 0.6, metalness: 0.15, transparent: !solid,
      opacity: p.o, depthWrite: solid, side: solid ? THREE.FrontSide : THREE.DoubleSide});
    const m = new THREE.Mesh(geom(p), mat);
    const a = p.m; m.matrixAutoUpdate = false;
    m.matrix.set(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], a[9], a[10], a[11], 0, 0, 0, 1);
    m.userData.id = c.id;
    if (solid) m.add(new THREE.LineSegments(eCache[p.g + ':' + p.d.join(',')], edgeMat));
    grp.add(m); meshes.push(m); if (p.o >= 0.3) pickables.push(m);
    if (p.s) sweeps.push(m);
  });
  comps[c.id] = {c, grp, meshes, visible: true, lines: []};
});
const pathMat = new THREE.LineDashedMaterial({color: 0xe8590c, dashSize: 8, gapSize: 5});
S.lines.forEach(l => {
  const g = new THREE.BufferGeometry().setFromPoints(l.pts.map(p => new THREE.Vector3(p[0], p[1], p[2])));
  const ln = new THREE.Line(g, pathMat); ln.computeLineDistances(); root.add(ln);
  comps[l.comp].lines.push(ln);
});
const env = S.env, ctr = w2t(env.center);
const span = Math.max(env.L, env.W, env.H);
const grid = new THREE.GridHelper(Math.ceil(span * 1.8 / 100) * 100, Math.ceil(span * 1.8 / 100), 0xb0b8c1, 0xd5dbe1);
grid.position.set(ctr.x, env.zmin - 0.5, ctr.z); scene.add(grid);

const persp = new THREE.PerspectiveCamera(35, 1, 1, 200000);
const ortho = new THREE.OrthographicCamera(-1, 1, 1, -1, -200000, 200000);
let cam = persp, ortho_on = false;
const target = ctr.clone(), TAN = Math.tan(THREE.MathUtils.degToRad(17.5));
let radius = span * 2.3, theta = -Math.PI / 4, phi = 1.0, pad = 0;
const VIEWS = {iso: [-Math.PI / 4, 1.0], top: [0, 0.0005], front: [0, Math.PI / 2], right: [Math.PI / 2, Math.PI / 2]};
function place() {
  const off = new THREE.Vector3().setFromSphericalCoords(radius, phi, theta);
  const w = view.clientWidth || 1, h = view.clientHeight || 1;
  [persp, ortho].forEach(k => { k.position.copy(target).add(off); k.lookAt(target); k.updateMatrixWorld(); });
  persp.aspect = w / h; persp.updateProjectionMatrix();
  const half = Math.max(radius - pad, 10) * TAN;
  ortho.left = -half * w / h; ortho.right = half * w / h; ortho.top = half; ortho.bottom = -half; ortho.updateProjectionMatrix();
  dirty = true;
}
function fit(center, size) {
  target.copy(w2t(center)); radius = 1000; pad = 0; place();
  const r = new THREE.Vector3().setFromMatrixColumn(persp.matrixWorld, 0), u = new THREE.Vector3().setFromMatrixColumn(persp.matrixWorld, 1);
  const f = new THREE.Vector3().setFromMatrixColumn(persp.matrixWorld, 2);
  let hx = 0, hy = 0, hz = 0;
  for (let i = 0; i < 8; i++) {
    const v = w2t([(i & 1 ? 0.5 : -0.5) * size[0], (i & 2 ? 0.5 : -0.5) * size[1], (i & 4 ? 0.5 : -0.5) * size[2]]);
    hx = Math.max(hx, Math.abs(v.dot(r))); hy = Math.max(hy, Math.abs(v.dot(u))); hz = Math.max(hz, Math.abs(v.dot(f)));
  }
  const aspect = (view.clientWidth || 1) / (view.clientHeight || 1);
  pad = hz; radius = Math.max(hy, hx / aspect) * 1.12 / TAN + pad; place();
}
const fitWork = () => fit(S.work.center, S.work.size);
let dirty = true;
function resize() { renderer.setSize(view.clientWidth, view.clientHeight); place(); }
new ResizeObserver(resize).observe(view);

// labels
const lbls = {}, NOLBL = {frame: 1, enclosure: 1};
S.comps.forEach(c => { const d = document.createElement('div'); d.className = 'lbl'; d.textContent = c.name; labelsEl.appendChild(d); lbls[c.id] = d; });
let showLbl = true, sel = null;
function updateLabels() {
  const w = view.clientWidth, h = view.clientHeight;
  S.comps.forEach(c => {
    const el = lbls[c.id];
    if (!showLbl || !comps[c.id].visible || !comps[c.id].grp.visible || (NOLBL[c.type] && sel !== c.id)) { el.style.display = 'none'; return; }
    const v = w2t(c.label).project(cam);
    if (v.z > 1 || v.z < -1) { el.style.display = 'none'; return; }
    el.style.display = ''; el.style.left = ((v.x + 1) / 2 * w) + 'px'; el.style.top = ((1 - v.y) / 2 * h) + 'px';
  });
}
function loop() { if (dirty) { renderer.render(scene, cam); updateLabels(); dirty = false; } requestAnimationFrame(loop); }

// sidebar
const side = $('#side');
S.comps.forEach(c => {
  const r = document.createElement('div'); r.className = 'row'; r.dataset.id = c.id;
  r.innerHTML = '<input type="checkbox" checked><span class="sw"></span><span class="nm"></span><span class="tag"></span>';
  r.querySelector('.sw').style.background = c.color;
  r.querySelector('.nm').textContent = c.name; r.querySelector('.nm').title = c.name + ' (' + c.id + ')';
  r.querySelector('.tag').textContent = c.typeCn;
  r.querySelector('input').addEventListener('click', e => { e.stopPropagation(); setVis(c.id, e.target.checked); });
  r.addEventListener('click', () => select(c.id));
  r.addEventListener('dblclick', () => focus(c.id));
  side.appendChild(r);
});
function setVis(id, on) { const k = comps[id]; k.visible = on; k.grp.visible = on && (k.c.type !== 'enclosure' || guard); k.lines.forEach(l => l.visible = on && paths); k.meshes.forEach(m => { if (sweeps.includes(m)) m.visible = paths; }); dirty = true; }

// selection & info
const info = $('#info');
function esc(s) { return String(s).replace(/[&<>"]/g, m => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[m])); }
function select(id) {
  if (sel) { comps[sel].meshes.forEach(m => m.material.emissive.setHex(0)); lbls[sel].classList.remove('sel'); }
  document.querySelectorAll('.row.sel').forEach(r => r.classList.remove('sel'));
  sel = id;
  if (!id) { info.style.display = 'none'; dirty = true; return; }
  const k = comps[id], c = k.c;
  k.meshes.forEach(m => m.material.emissive.setHex(0x5a2a00)); lbls[id].classList.add('sel');
  const row = side.querySelector('.row[data-id="' + CSS.escape(id) + '"]'); row.classList.add('sel'); row.scrollIntoView({block: 'nearest'});
  let h = '<button class="x" title="关闭">×</button><h2>' + esc(c.name) + '</h2><table>';
  h += '<tr><td>ID / 类型</td><td>' + esc(c.id) + ' / ' + esc(c.typeCn) + '</td></tr>';
  c.params.forEach(p => h += '<tr><td>' + esc(p[0]) + '</td><td>' + esc(p[1]) + '</td></tr>');
  h += '<tr><td>位置 x, y, z</td><td>' + c.pos.map(v => v.toFixed(1)).join(', ') + ' mm</td></tr>';
  h += '<tr><td>朝向</td><td>' + c.rot.toFixed(1) + '°</td></tr>';
  h += '<tr><td>包络尺寸</td><td>' + c.size.map(v => v.toFixed(0)).join(' × ') + ' mm</td></tr></table>';
  info.innerHTML = h; info.style.display = 'block';
  info.querySelector('.x').onclick = () => select(null);
  dirty = true;
}
function focus(id) { const c = comps[id].c; fit(c.center, c.size.map(v => Math.max(v, 120))); }
function showIssues() {
  select(null);
  let h = '<button class="x" title="关闭">×</button><h2>布局检查</h2><ul>';
  S.issues.forEach(s => h += '<li>' + esc(s) + '</li>');
  info.innerHTML = h + '</ul>'; info.style.display = 'block';
  info.querySelector('.x').onclick = () => { info.style.display = 'none'; };
}

// controls
const el = renderer.domElement, ptrs = new Map();
let mode = null, sx = 0, sy = 0, moved = 0, pinch = 0;
el.addEventListener('contextmenu', e => e.preventDefault());
el.addEventListener('pointerdown', e => {
  el.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  if (ptrs.size === 2) { const p = [...ptrs.values()]; pinch = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]); mode = 'pinch'; return; }
  mode = (e.button === 2 || e.shiftKey) ? 'pan' : 'rot'; sx = e.clientX; sy = e.clientY; moved = 0;
});
el.addEventListener('pointermove', e => {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  if (mode === 'pinch' && ptrs.size === 2) {
    const p = [...ptrs.values()], d = Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]);
    if (pinch > 0) { radius = Math.min(span * 20, Math.max(50, radius * pinch / d)); place(); }
    pinch = d; return;
  }
  const dx = e.clientX - sx, dy = e.clientY - sy; sx = e.clientX; sy = e.clientY; moved += Math.abs(dx) + Math.abs(dy);
  if (mode === 'rot') { theta -= dx * 0.008; phi = Math.min(Math.PI - 0.001, Math.max(0.0005, phi - dy * 0.008)); place(); }
  else if (mode === 'pan') {
    const k = 2 * radius * Math.tan(THREE.MathUtils.degToRad(17.5)) / view.clientHeight;
    const right = new THREE.Vector3().setFromMatrixColumn(cam.matrix, 0), up = new THREE.Vector3().setFromMatrixColumn(cam.matrix, 1);
    target.addScaledVector(right, -dx * k).addScaledVector(up, dy * k); place();
  }
});
function endPtr(e) {
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId);
  if (mode === 'rot' && moved < 4 && ptrs.size === 0) pick(e);
  if (ptrs.size === 0) mode = null;
}
el.addEventListener('pointerup', endPtr); el.addEventListener('pointercancel', endPtr);
el.addEventListener('wheel', e => { e.preventDefault(); radius = Math.min(span * 20, Math.max(50, radius * Math.exp(e.deltaY * 0.0012))); place(); }, {passive: false});
const ray = new THREE.Raycaster();
function hit(e) {
  const r = el.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), cam);
  const hs = ray.intersectObjects(pickables.filter(m => m.parent.visible), false);
  return hs.length ? hs[0].object.userData.id : null;
}
function hitPoint(e) {
  const r = el.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1), cam);
  const hs = ray.intersectObjects(pickables.filter(m => m.parent.visible), false);
  return hs.length ? hs[0].point.clone() : null;
}
let measuring = false, mpts = [];
const mgrp = new THREE.Group(); scene.add(mgrp);
const t2w = v => [v.x, -v.z, v.y];
function clearMeasure() { mpts = []; while (mgrp.children.length) mgrp.remove(mgrp.children[0]); dirty = true; }
function measurePick(e) {
  const p = hitPoint(e); if (!p) return;
  if (mpts.length === 2) clearMeasure();
  mpts.push(p);
  const mk = new THREE.Mesh(new THREE.SphereGeometry(Math.max(2, span / 300), 16, 12), new THREE.MeshBasicMaterial({color: 0xe03131, depthTest: false}));
  mk.renderOrder = 10; mk.position.copy(p); mgrp.add(mk);
  const f = v => v.map(x => x.toFixed(1)).join(', ');
  let h = '<button class="x" title="关闭">×</button><h2>测距</h2><table>';
  if (mpts.length === 2) {
    const ln = new THREE.Line(new THREE.BufferGeometry().setFromPoints(mpts), new THREE.LineBasicMaterial({color: 0xe03131, depthTest: false}));
    ln.renderOrder = 10; mgrp.add(ln);
    const a = t2w(mpts[0]), b = t2w(mpts[1]), d = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    h += '<tr><td>距离</td><td><b>' + Math.hypot(d[0], d[1], d[2]).toFixed(1) + ' mm</b></td></tr>';
    h += '<tr><td>ΔX / ΔY / ΔZ</td><td>' + f(d) + ' mm</td></tr><tr><td>水平距离</td><td>' + Math.hypot(d[0], d[1]).toFixed(1) + ' mm</td></tr>';
    h += '<tr><td>A 点</td><td>' + f(a) + '</td></tr><tr><td>B 点</td><td>' + f(b) + '</td></tr>';
  } else h += '<tr><td>A 点</td><td>' + f(t2w(mpts[0])) + '</td></tr><tr><td colspan="2">再点第二个点</td></tr>';
  info.innerHTML = h + '</table>'; info.style.display = 'block';
  info.querySelector('.x').onclick = () => { info.style.display = 'none'; };
  dirty = true;
}
function setMeasure(on) { measuring = on; $('#bMeasure').classList.toggle('on', on); if (!on) { clearMeasure(); info.style.display = 'none'; } else select(null); }
function pick(e) { if (measuring) measurePick(e); else select(hit(e)); }
el.addEventListener('dblclick', e => { const id = hit(e); if (id) focus(id); });

// toolbar
document.querySelectorAll('[data-view]').forEach(b => b.onclick = () => { [theta, phi] = VIEWS[b.dataset.view]; fitWork(); });
$('#bAll').onclick = () => { [theta, phi] = VIEWS.iso; fit(env.center, [env.L, env.W, env.H]); };
let guard = true, paths = true;
$('#bOrtho').onclick = e => { ortho_on = !ortho_on; cam = ortho_on ? ortho : persp; e.target.classList.toggle('on', ortho_on); place(); };
$('#bGuard').onclick = e => { guard = !guard; e.target.classList.toggle('on', guard); Object.keys(comps).forEach(id => setVis(id, comps[id].visible)); };
$('#bLbl').onclick = e => { showLbl = !showLbl; e.target.classList.toggle('on', showLbl); dirty = true; };
$('#bPath').onclick = e => { paths = !paths; e.target.classList.toggle('on', paths); Object.keys(comps).forEach(id => setVis(id, comps[id].visible)); };
const nWarn = S.issues.filter(s => s.indexOf('[OK]') !== 0).length;
$('#bIssue').textContent = '检查' + (nWarn ? ' (' + nWarn + ')' : ' ✓');
if (nWarn) $('#bIssue').classList.add('warn');
$('#bIssue').onclick = showIssues;
$('#bMeasure').onclick = () => setMeasure(!measuring);
document.addEventListener('keydown', e => { if (e.key === 'Escape' && measuring) setMeasure(false); });
$('#bShot').onclick = () => {
  renderer.render(scene, cam); updateLabels();
  const src = renderer.domElement, pr = renderer.getPixelRatio();
  const cv = document.createElement('canvas'); cv.width = src.width; cv.height = src.height;
  const g = cv.getContext('2d'); g.drawImage(src, 0, 0);
  g.font = (12 * pr) + 'px "Microsoft YaHei","PingFang SC",sans-serif'; g.textBaseline = 'middle';
  S.comps.forEach(c => {
    const l = lbls[c.id]; if (l.style.display === 'none') return;
    const x = parseFloat(l.style.left) * pr, y = parseFloat(l.style.top) * pr, tw = g.measureText(c.name).width, p = 5 * pr, hh = 18 * pr;
    g.fillStyle = 'rgba(255,255,255,0.9)'; g.strokeStyle = '#d5dbe1'; g.fillRect(x - tw / 2 - p, y - hh, tw + 2 * p, hh); g.strokeRect(x - tw / 2 - p, y - hh, tw + 2 * p, hh);
    g.fillStyle = '#1f2933'; g.fillText(c.name, x - tw / 2, y - hh / 2);
  });
  g.fillStyle = '#5f6b7a'; g.fillText(S.title + '  外形 ' + S.env.L + '×' + S.env.W + '×' + S.env.H + ' mm', 10 * pr, 14 * pr);
  const a = document.createElement('a'); a.download = S.title + '.png'; a.href = cv.toDataURL('image/png'); a.click();
};
resize(); fitWork(); loop();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- report

def envelope(comps):
    lo = [min(c.lo[i] for c in comps) for i in range(3)]
    hi = [max(c.hi[i] for c in comps) for i in range(3)]
    return lo, hi


def report(title, comps, anchors, issues, lo, hi, outputs):
    L, W, H = (hi[i] - lo[i] for i in range(3))
    out = [f"## 3D 概念布局: {title}", "",
           "| 项目 | 数值 |", "|---|---|",
           f"| 整机外形 (长 × 宽 × 高, 含机架/防护罩/三色灯) | {L:.0f} × {W:.0f} × {H:.0f} mm |",
           f"| 组件 / 零件数 | {len(comps)} / {sum(len(c.parts) for c in comps)} |", ""]
    out += ["### 组件清单", "", "| ID | 名称 | 类型 | 关键参数 | 位置 x, y, z (mm) | 朝向 ° |",
            "|---|---|---|---|---|---:|"]
    for c in comps:
        params = "; ".join(f"{k} {v}" for k, v in c.params)
        out.append(f"| {c.id} | {c.name} | {c.type_cn} | {params} | "
                   f"{c.pose[0]:.0f}, {c.pose[1]:.0f}, {c.pose[2]:.0f} | {c.pose[3]:.1f} |")
    out += ["", "### 锚点坐标", "", "| 锚点 | x | y | z |", "|---|---:|---:|---:|"]
    out += [f"| {k} | {v[0]:.1f} | {v[1]:.1f} | {v[2]:.1f} |" for k, v in anchors.items()]
    out += ["", "### 布局检查", ""] + [f"- [{lv}] {m}" for lv, m in issues]
    rows, tot = io_summary(comps)
    out += ["", "### IO / 轴数 / 主要外购件估算", "",
            "| ID | 名称 | DI | DO | 伺服轴 | 安全输入 | 通讯/模拟量 | 主要外购件 |", "|---|---|--:|--:|--:|--:|--:|---|"]
    for c, r in rows:
        if any(r[k] for k in tot) or r["外购件"]:
            out.append(f"| {c.id} | {c.name} | {r['DI']} | {r['DO']} | {r['伺服轴']} | {r['安全输入']} | "
                       f"{r['通讯/模拟量']} | {'、'.join(r['外购件'])} |")
    out.append(f"| **合计** | | {tot['DI']} | {tot['DO']} | {tot['伺服轴']} | {tot['安全输入']} | "
               f"{tot['通讯/模拟量']} | |")
    up = lambda n: int(math.ceil(n * 1.2 / 16.0)) * 16 if n else 0
    out += ["", f"控制器初选 (含 20% 余量): DI ≥ {up(tot['DI'])} 点, DO ≥ {up(tot['DO'])} 点, "
            f"伺服 {tot['伺服轴']} 轴 (≥ 4 轴建议总线型 PLC/运动控制器), "
            f"安全输入 {tot['安全输入']} 路 (双通道, 安全继电器或安全 PLC), 通讯/模拟量 {tot['通讯/模拟量']} 路. "
            "按组件类型估算, 详细设计时按电气原理图核对."]
    calc = [f"- {c.name} ({c.id}): `python3 scripts/{cmd}`" for c in comps for cmd in c.calc]
    if calc:
        out += ["", "### 建议校核 (把 <> 换成实际值后运行)", ""] + calc
    nums = balloon_numbers(comps)
    out += ["", "### 图号对照 (PNG 气泡数字)", "", "| 图号 | ID | 名称 |", "|--:|---|---|"]
    out += [f"| {nums[c.id]} | {c.id} | {c.name} |" for c in comps if c.id in nums]
    if outputs:
        out += ["", "### 输出文件", ""] + [f"- {o}" for o in outputs]
    out += ["", "> 概念布局为方块级示意 (圆柱在 STEP/STL 中为多棱柱近似), 用于确认布局、行程和空间关系; "
                "详细设计在 CAD 中完成。"]
    return "\n".join(out)


def write_bom(path, comps):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["图号", "id", "名称", "类型", "关键参数", "x", "y", "z", "朝向°", "包络长", "包络宽", "包络高",
                     "DI", "DO", "伺服轴", "安全输入", "通讯/模拟量", "主要外购件"])
        nums = balloon_numbers(comps)
        for c, r in io_summary(comps)[0]:
            wr.writerow([nums.get(c.id, ""), c.id, c.name, c.type_cn, "; ".join(f"{k} {v}" for k, v in c.params),
                         round(c.pose[0], 1), round(c.pose[1], 1), round(c.pose[2], 1), round(c.pose[3], 1),
                         round(c.hi[0] - c.lo[0]), round(c.hi[1] - c.lo[1]), round(c.hi[2] - c.lo[2]),
                         r["DI"], r["DO"], r["伺服轴"], r["安全输入"], r["通讯/模拟量"], "、".join(r["外购件"])])


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("layout", nargs="?", help="布局 JSON")
    ap.add_argument("--types", action="store_true", help="列出组件类型、参数和锚点")
    ap.add_argument("--html", help="输出交互式 3D 预览 HTML")
    ap.add_argument("--step", help="输出 STEP (AP214) 装配体")
    ap.add_argument("--step-flat", action="store_true", help="STEP 输出为单零件多实体 (不建装配结构)")
    ap.add_argument("--stl", help="输出 STL")
    ap.add_argument("--up", choices=["y", "z"], default="y",
                    help="STEP/STL 向上轴: y = SolidWorks/Creo/Inventor 习惯 (默认), z = NX/中望 3D 习惯")
    ap.add_argument("--bom", help="输出组件清单 CSV (含图号、IO、主要外购件)")
    ap.add_argument("--png", help="输出静态视图 PNG 的文件名前缀, 如 out/layout → layout_iso.png (不需要浏览器)")
    ap.add_argument("--views", default="iso,top", help="PNG 视图: iso,top,front,right (默认 iso,top)")
    ap.add_argument("--png-width", type=int, default=1600, help="PNG 宽度 px (默认 1600)")
    ap.add_argument("--png-all", action="store_true", help="PNG 中也画防护罩、光栅、触摸屏和三色灯")
    ap.add_argument("--png-fit", choices=["work", "all"], default="work",
                    help="PNG 取景: work = 台面上的工作区域 (默认), all = 整机")
    ap.add_argument("--cdn", action="store_true", help="HTML 从 CDN 加载 three.js (文件小, 需联网)")
    ap.add_argument("--segments", type=int, default=24, help="STEP 中圆柱的棱数 (默认 24)")
    ap.add_argument("--tol", type=float, default=0.5, help="干涉检查容差 mm (默认 0.5)")
    ap.add_argument("--out", help="报告写入文件 (UTF-8)")
    a = ap.parse_args(argv)
    if a.types:
        print_types()
        return
    if not a.layout:
        ap.error("需要布局 JSON 文件 (或用 --types 查看组件类型)")
    try:
        for enc in ("utf-8-sig", "gbk"):
            try:
                with open(a.layout, encoding=enc) as f:
                    spec = json.load(f)
                break
            except UnicodeDecodeError:
                continue
        if not isinstance(spec, dict):
            raise SpecError("JSON 顶层应为对象: {\"title\": ..., \"components\": [...]}")
        title = str(spec.get("title", os.path.splitext(os.path.basename(a.layout))[0]))
        comps, anchors = build_layout(spec)
        machine = {k: spec[k] for k in ("uph", "product", "refill_min") if k in spec}
        if "uph" in machine and (not isinstance(machine["uph"], (int, float)) or machine["uph"] <= 0):
            raise SpecError("顶层 uph 应为正数 (目标产能 pcs/h)")
        if "product" in machine:
            product_parts(Builder(), machine["product"], 0, 0, 0, "x")
    except json.JSONDecodeError as e:
        sys.exit(f"错误: JSON 格式错误 (第 {e.lineno} 行第 {e.colno} 列): {e.msg}")
    except SpecError as e:
        sys.exit(f"错误: {e}")
    if a.segments < 8:
        sys.exit("错误: --segments 须 ≥ 8")

    issues = check_layout(comps, a.tol, machine)
    bad_top = sorted(k for k in spec if k not in TOP_KEYS)
    if bad_top:
        issues.insert(0, ("注意", f"顶层未知字段 {', '.join(bad_top)} 已忽略 (可用: {', '.join(sorted(TOP_KEYS))})"))
    lo, hi = envelope(comps)
    env = {"L": round(hi[0] - lo[0]), "W": round(hi[1] - lo[1]), "H": round(hi[2] - lo[2]),
           "zmin": round(lo[2], 1), "center": [round((lo[i] + hi[i]) / 2, 1) for i in range(3)]}
    outputs = []
    if a.html:
        write_html(a.html, title, comps, issues, env, a.cdn)
        outputs.append(f"{a.html} (浏览器打开; {'CDN 加载 three.js' if a.cdn or not os.path.exists(THREE_JS) else '内嵌 three.js, 可离线'})")
    if a.step:
        n = write_step(a.step, title, comps, a.segments, a.step_flat, a.up)
        outputs.append(f"{a.step} ({'单零件多实体' if a.step_flat else '装配体, 每个组件一个零件'}, "
                       f"{'Y' if a.up == 'y' else 'Z'} 向上, {n} 个实体记录)")
    if a.stl:
        outputs.append(f"{a.stl} ({write_stl(a.stl, comps, up=a.up)} 个三角面)")
    if a.png:
        views = [v.strip() for v in a.views.split(",") if v.strip()]
        bad = [v for v in views if v not in VIEW_CN]
        if bad:
            sys.exit(f"错误: 未知视图 {bad} (可用 iso, top, front, right)")
        for v in views:
            path = f"{a.png}_{v}.png"
            w, h = render_png(path, comps, v, max(400, a.png_width), a.png_all, a.png_fit)
            outputs.append(f"{path} ({VIEW_CN[v]}, {w}×{h}, 气泡数字 = 报告中的图号)")
    if a.bom:
        write_bom(a.bom, comps)
        outputs.append(f"{a.bom} (组件清单)")
    text = report(title, comps, anchors, issues, lo, hi, outputs)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写入 {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
