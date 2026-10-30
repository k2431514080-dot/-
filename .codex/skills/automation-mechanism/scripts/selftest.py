#!/usr/bin/env python3
"""技能脚本自检 — 修改任何脚本后运行: python3 scripts/selftest.py

覆盖: 选型计算的手算校核值、节拍样例、评分样例、两个 3D 布局样例 (无干涉、STEP 结构完整、
网格朝外)、以及几类必须报出的问题 (参数拼写错误、转盘旋转路径障碍、SCARA 超出臂展、输入校验).
全部通过返回 0, 否则返回 1.
"""

import io
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
sys.path.insert(0, HERE)

import cycle_time  # noqa: E402
import layout3d  # noqa: E402
import mech_calc  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(f"[{'OK' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def calc(*argv):
    a = mech_calc.build_parser().parse_args(list(argv))
    return a.func(a)


def res(report, prefix):
    for n, v, _ in report.results:
        if n.startswith(prefix):
            return v
    raise KeyError(prefix)


def near(v, want, tol):
    return abs(v - want) <= tol


def rejected(fn):
    try:
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            fn()
    except SystemExit as e:
        return e.code not in (0, None)
    return False


def test_mech_calc():
    for k, (vm, am, q) in {"ms": (1.76, 5.53, 0.99), "mt": (2.00, 4.89, 1.65), "cyc": (2.00, 6.28, 1.30)}.items():
        p = mech_calc.profile(k)
        check(f"运动曲线 {k} 特性值", near(p["Vm"], vm, 0.01) and near(p["Am"], am, 0.01)
              and near(p["AVm"] / p["Am"], q, 0.01))
    r = calc("cylinder", "--mass", "1.5", "--mode", "vertical", "--stroke", "50", "--speed", "200")
    check("气缸 垂直 1.5 kg → Φ10", res(r, "推荐标准缸径") == 10 and near(res(r, "所需理论出力"), 29.42, 0.01))
    check("气缸 夹紧 800 N → Φ63", res(calc("cylinder", "--mode", "clamp", "--force", "800"), "推荐标准缸径") == 63)
    check("吸盘 0.02 kg 10 m/s² → Φ6", res(calc("vacuum", "--mass", "0.02", "--accel", "10"), "推荐吸盘直径") == 6)
    check("吸盘 接受 -60 kPa", res(calc("vacuum", "--mass", "0.1", "--vacuum", "-60"), "推荐吸盘直径") == 10)
    r = calc("screw", "--mass", "8", "--lead", "10", "--speed", "500", "--accel-time", "0.1", "--stroke", "300")
    check("丝杠 转速/惯量/危险转速", near(res(r, "丝杠最高转速"), 3000, 0.1) and near(res(r, "丝杠惯量"), 0.2273, 0.001)
          and near(res(r, "危险转速许用值"), 7922, 2))
    check("丝杠 初选 100 W", any(lv == "OK" and "100 W" in m for lv, m in r.checks))
    r = calc("rotary", "--stations", "6", "--index-time", "0.4", "--table-dia", "400", "--table-thk", "15",
             "--fixture-mass", "0.3", "--fixture-radius", "160")
    check("DD 转盘 峰值扭矩 4.356 N·m", near(res(r, "输出侧峰值扭矩"), 4.356, 0.01))
    r = calc("indexer", "--stations", "8", "--cycle-time", "1.2", "--index-angle", "120", "--table-dia", "500",
             "--table-thk", "15", "--fixture-mass", "0.8", "--fixture-radius", "210")
    check("凸轮分割器 Te 21.6 / Tc 8.0", near(res(r, "输出轴所需扭矩"), 21.6, 0.05) and near(res(r, "输入轴所需扭矩"), 8.0, 0.05))
    check("导轨寿命 101,615 km", near(res(calc("guide", "--C", "11.4", "--load", "600"), "额定寿命"), 101615, 1))
    s1 = res(calc("safety", "--curtain-ms", "15", "--stop-ms", "120", "--resolution", "30"), "最小安全距离")
    s2 = res(calc("safety", "--curtain-ms", "15", "--stop-ms", "300", "--resolution", "30"), "最小安全距离")
    check("光栅距离 438 / 664 mm", near(s1, 438, 0.5) and near(s2, 664, 0.5))
    check("点到点 150 mm 0.3975 s", near(res(calc("move", "--dist", "150", "--speed", "800", "--accel", "5"), "单程总时间"), 0.3975, 1e-4))
    check("气爪 0.5 kg → 74.0 N/爪", near(res(calc("gripper", "--mass", "0.5", "--accel", "5"), "每爪所需夹持力"), 74.03, 0.05))
    r = calc("conveyor", "--load", "20", "--speed", "15", "--belt-mass", "2")
    check("皮带线 阻力 64.7 N / 95.5 rpm", near(res(r, "运行阻力"), 64.72, 0.05) and near(res(r, "滚筒转速"), 95.49, 0.05))
    check("拒绝: 节拍 < 分度时间", rejected(lambda: calc("rotary", "--stations", "6", "--index-time", "0.8",
                                                           "--cycle-time", "0.5", "--table-dia", "400", "--table-thk", "15")))
    check("拒绝: 分度角 400°", rejected(lambda: calc("indexer", "--stations", "8", "--cycle-time", "1.2", "--index-angle",
                                                       "400", "--table-dia", "500", "--table-thk", "15")))
    check("拒绝: 负载率 -0.5", rejected(lambda: calc("cylinder", "--mass", "2", "--load-ratio", "-0.5")))


def test_cycle_and_score():
    acts, order = cycle_time.load(os.path.join(ASSETS, "cycle_example_magnet_ring.csv"))
    r = cycle_time.analyze(acts, order, "sync")
    check("节拍样例 CT 1.60 s, 瓶颈上料手", near(r["ct"], 1.6, 1e-9) and r["critical"] == [f"L{i}" for i in range(1, 9)])
    check("拒绝: --oee 85", rejected(lambda: cycle_time.main([os.path.join(ASSETS, "cycle_example_magnet_ring.csv"),
                                                               "--oee", "85"])))
    out = subprocess.run([sys.executable, os.path.join(HERE, "scheme_score.py"),
                          os.path.join(ASSETS, "scoring_example.csv"), "--json"], capture_output=True, text=True,
                         encoding="utf-8")
    data = json.loads(out.stdout)
    check("评分样例 推荐 B (85 分)", data["recommended"].startswith("B") and near(max(data["totals"]), 85, 1e-6))


def step_lint(path):
    text = open(path, encoding="ascii").read()
    defined = set(re.findall(r"^#(\d+)=", text, re.M))
    body = text.split("DATA;", 1)[1]
    used = set(re.findall(r"#(\d+)", body))
    return len(used - defined), text.count("MANIFOLD_SOLID_BREP("), text.count("NEXT_ASSEMBLY_USAGE_OCCURRENCE(")


def test_layout():
    tmp = tempfile.mkdtemp()
    for name in ("layout_example_magnet_ring.json", "layout_example_wheel_test.json"):
        spec = json.load(open(os.path.join(ASSETS, name), encoding="utf-8"))
        comps, _ = layout3d.build_layout(spec)
        issues = layout3d.check_layout(comps, 0.5)
        clash = [m for _, m in issues if "干涉" in m and "未发现" not in m]
        check(f"{name}: 无干涉", not clash, "; ".join(clash))
        check(f"{name}: 无参数警告", not any("未知参数" in m or "touch 中" in m for _, m in issues))
        solids = sum(1 for c in comps for p in c.parts if not p.viewer_only)
        for up in ("y", "z"):
            path = os.path.join(tmp, f"{name}.{up}.step")
            layout3d.write_step(path, spec["title"], comps, up=up)
            dangling, breps, nauo = step_lint(path)
            check(f"{name}: STEP up={up} 引用完整, 实体 {solids}, 组件 {len(comps)}",
                  dangling == 0 and breps == solids and nauo == len(comps),
                  f"dangling={dangling} breps={breps} nauo={nauo}")
        worst = float("inf")
        for c in comps:
            for p in c.parts:
                V, F = layout3d.mesh(p, 24)
                vol = sum(layout3d.dot(a, layout3d.cross(b, d)) for a, b, d in layout3d.triangles(V, F)) / 6
                worst = min(worst, vol)
        check(f"{name}: 网格法向朝外", worst > 0)
        html = os.path.join(tmp, name + ".html")
        layout3d.write_html(html, spec["title"], comps, issues, {"L": 1, "W": 1, "H": 1, "zmin": 0, "center": [0, 0, 0]})
        check(f"{name}: HTML 生成且内嵌 three.js", os.path.getsize(html) > 500000)

    def issues_of(spec):
        comps, _ = layout3d.build_layout(spec)
        return layout3d.check_layout(comps, 0.5)

    typo = {"components": [{"id": "c", "type": "cylinder_actuator", "tip": [0, 0, 50], "dir": 0, "strok": 80}]}
    check("报出: 参数拼写错误", any("未知参数 strok" in m for _, m in issues_of(typo)))
    spec = json.load(open(os.path.join(ASSETS, "layout_example_magnet_ring.json"), encoding="utf-8"))
    spec["components"].append({"id": "blk", "type": "box", "at": {"ref": "tt.center", "offset": [160, 0, 0]},
                               "size": [10, 10, 185]})
    check("报出: 转盘旋转路径上的障碍", any("运动干涉" in m and "blk" in m for _, m in issues_of(spec)))
    scara = {"components": [{"id": "r", "type": "scara", "at": [0, 0], "reach": 400,
                             "targets": [[300, 0, 50], [0, 450, 50]]}]}
    check("报出: SCARA 目标超出臂展", any(lv == "NG" and "T2" in m for lv, m in issues_of(scara)))
    bad = {"components": [{"id": "p", "type": "pick_place", "from": [0, 0, 50], "to": [300, 0, 50], "drive": "servo"}]}
    try:
        layout3d.build_layout(bad)
        check("拒绝: 非法枚举值 drive=servo", False)
    except layout3d.SpecError:
        check("拒绝: 非法枚举值 drive=servo", True)


def main():
    test_mech_calc()
    test_cycle_and_score()
    test_layout()
    print(f"\n{'全部通过' if not FAILS else f'{len(FAILS)} 项失败: ' + ', '.join(FAILS)}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
