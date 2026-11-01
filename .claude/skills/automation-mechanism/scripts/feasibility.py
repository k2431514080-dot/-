#!/usr/bin/env python3
"""方案可行性判定 (出图前的闸门) — 仅依赖 Python 标准库.

把一个方案的 3D 布局、节拍表、选型计算、假设条件和验证计划放进一个项目文件, 一次跑完所有检查,
给出唯一结论:
  可行          本工具能计算的项目全部通过, 所有假设已确认, 验证项已通过
  有条件可行    无不可行项, 但有假设待确认或验证待完成 (逐条列出条件和验证方法)
  评估未完成    有本工具无法计算、且没有验证计划的项目
  不可行        有干涉、选型不足、节拍不够、安全距离不够等问题, 不得作为推荐方案出图

退出码: 0 可行, 1 有条件可行, 2 评估未完成, 3 不可行.
项目文件格式见 references/feasibility.md, 样例 assets/project_magnet_ring.json.

示例: python3 feasibility.py project.json --out 可行性判定.md
"""

import argparse
import io
import json
import os
import shlex
import sys
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cycle_time  # noqa: E402
import layout3d  # noqa: E402
import mech_calc  # noqa: E402

PASS, COND, TODO, FAIL = "OK", "条件", "未验证", "NG"
RANK = {PASS: 0, COND: 1, TODO: 2, FAIL: 3}

# 本工具无法计算的项目: 每项必须有验证计划 (tests[].covers), 否则判 "评估未完成"
UNCOMPUTABLE = {
    "定位方案": "过定位/欠定位、定位基准与图纸基准是否统一、取放方式与治具是否匹配",
    "产品损伤": "划伤、崩边、变形、静电、磁性件互吸 (落料、夹持、推料对产品的影响)",
    "结构刚性": "立柱/悬臂/转盘的刚性和振动, 压装/冲击工位的变形",
    "供应商数据": "凸轮/机器人/DD/模组等外购件的节拍、精度、负载以厂家规格书为准",
    "线缆与维护": "气管线缆走向、拖链、易损件更换和调试空间",
}
MEASURE_TYPES = {"probe", "camera"}
HEADLINE = {"cylinder": "推荐标准缸径", "vacuum": "推荐吸盘直径", "gripper": "每爪所需夹持力",
            "rotary": "输出侧峰值扭矩", "indexer": "输出轴所需扭矩", "safety": "最小安全距离",
            "guide": "额定寿命", "move": "单程总时间"}


def fail(msg):
    sys.exit(f"错误: {msg}")


def add(rows, cat, item, result, status, how=""):
    rows.append({"类别": cat, "检查项": item, "结果": result, "状态": status, "条件/验证": how})


def check_layout(rows, proj, base):
    path = os.path.join(base, proj["layout"])
    spec = json.load(open(path, encoding="utf-8-sig"))
    comps, _ = layout3d.build_layout(spec)
    machine = {k: spec[k] for k in ("uph", "product", "refill_min") if k in spec}
    if "uph" not in machine and proj.get("target_uph"):
        machine["uph"] = proj["target_uph"]
    for lv, m in layout3d.check_layout(comps, 0.5, machine):
        clash = ("干涉" in m or "遮挡光栅" in m) and "未发现" not in m
        if lv == "NG" or clash:
            st = FAIL
        elif lv == "OK":
            st = PASS
        else:
            st = COND
        add(rows, "3D 布局", m.split(":")[0][:40], m, st,
            "" if st != COND else "改布局消除, 或在风险表中给出决定 (已接受的写入 assumptions)")
    return spec, comps


def check_cycle(rows, proj, base, comps):
    path = os.path.join(base, proj["cycle"])
    acts, order = cycle_time.load(path)
    r = cycle_time.analyze(acts, order, proj.get("cycle_mode", "sync"))
    target, oee, pcs = proj.get("target_uph"), proj.get("oee", 0.85), proj.get("pcs", 1)
    need = proj.get("margin_min", 0.10)
    ct = r["ct"]
    if target:
        req = 3600 * pcs * oee / target
        margin = (req - ct) / req
        st = PASS if margin >= need else (COND if margin >= 0 else FAIL)
        add(rows, "节拍", "节拍余量", f"CT {ct:.2f} s, 要求 ≤ {req:.2f} s, 余量 {margin:+.1%}", st,
            "" if st == PASS else ("压缩关键路径: " + " → ".join(r["critical"]) if st == FAIL else
                                   f"余量 < {need:.0%}: 调试损失会吃掉余量, 建议继续压缩关键路径"))
    else:
        add(rows, "节拍", "节拍余量", f"CT {ct:.2f} s", COND, "项目文件未填 target_uph, 无法判定是否满足产能")
    busy = r["res_busy"]
    linked = set()
    byid = {c.id: c for c in comps or []}
    for ln in proj.get("links", []):
        cid, res = ln.get("layout"), ln.get("resource")
        linked.add(cid)
        c = byid.get(cid)
        if c is None or "loop_s" not in c.meta:
            add(rows, "一致性", f"{cid} ↔ {res}", "布局中没有该取放机构", FAIL, "检查 links.layout")
            continue
        if res not in busy:
            add(rows, "一致性", f"{cid} ↔ {res}", "节拍表中没有该执行机构", FAIL, "检查 links.resource")
            continue
        est, csv_s = c.meta["loop_s"], busy[res]
        if csv_s >= 0.8 * est:
            add(rows, "一致性", f"{c.name} 动作时间", f"节拍表 {csv_s:.2f} s / 布局估算 {est:.2f} s", PASS)
        else:
            note = ln.get("note")
            add(rows, "一致性", f"{c.name} 动作时间", f"节拍表 {csv_s:.2f} s 比布局估算 {est:.2f} s 快 "
                f"{1 - csv_s / est:.0%}", COND, note or "节拍表比几何估算快, 需说明依据 (速度/缓冲/动作重叠) 并实测")
    if comps:
        for c in comps:
            if c.type == "pick_place" and c.id not in linked:
                add(rows, "一致性", f"{c.name} 动作时间", "未与节拍表关联 (links)", COND,
                    "在 links 中关联节拍表执行机构, 核对动作时间")


def check_calcs(rows, proj, spec):
    pending = []
    curtain_need = [c.get("min_distance") for c in (spec or {}).get("components", [])
                    if c.get("type") == "light_curtain"]
    for item in proj.get("calcs", []):
        name, cmd = item.get("name", "?"), item.get("cmd", "")
        argv = shlex.split(cmd)
        try:
            with redirect_stderr(io.StringIO()) as err, redirect_stdout(io.StringIO()):
                a = mech_calc.build_parser().parse_args(argv)
                rep = a.func(a)
        except SystemExit as e:
            msg = (err.getvalue().strip().splitlines() or [str(e.code)])[-1] if isinstance(e.code, int) else str(e.code)
            add(rows, "选型计算", name, f"命令无效: {msg}", FAIL, cmd)
            continue
        levels = [lv for lv, _ in rep.checks]
        head = HEADLINE.get(argv[0])
        val = next((v for n, v, u in rep.results if head and n.startswith(head)), None)
        unit = next((u for n, v, u in rep.results if head and n.startswith(head)), "")
        summary = f"{head} {mech_calc.fmt(val)} {unit}".strip() if val is not None else \
            next((m for lv, m in rep.checks if lv == "OK"), "")
        st, how = PASS, ""
        if "NG" in levels:
            st, how = FAIL, "; ".join(m for lv, m in rep.checks if lv == "NG")
        sel = {"cylinder": item.get("selected_bore"), "vacuum": item.get("selected_cup")}.get(argv[0])
        if sel is not None and val is not None and sel < val:
            st, how = FAIL, f"选用 {sel:g} 小于计算值 {mech_calc.fmt(val)}"
        elif sel is not None:
            summary += f" → 选用 {sel:g}"
        if st == PASS and "注意" in levels and not item.get("confirmed"):
            pending.append(name)
            summary += " (待样本复核)"
        add(rows, "选型计算", name, summary, st, how)
        if argv[0] == "safety" and val is not None:
            for need in curtain_need:
                if need is None:
                    add(rows, "一致性", "光栅安全距离", f"计算 S = {val:.0f} mm, 布局未填 min_distance", COND,
                        f"布局光栅加 \"min_distance\": {val:.0f}")
                elif need < val - 0.5:
                    add(rows, "一致性", "光栅安全距离", f"布局按 {need:g} mm 判定, 计算 S = {val:.0f} mm", FAIL,
                        "布局 min_distance 改为计算值后重新检查")
    if pending:
        add(rows, "选型计算", "外购件按厂家样本复核", "、".join(pending), COND,
            "选定品牌型号后核对样本 (额定扭矩/推力、允许动能、惯量、断气保持等, 见各计算的 [注意]); "
            "复核完成的在 calcs 中加 \"confirmed\": true")


def check_assumptions(rows, proj):
    for a in proj.get("assumptions", []):
        item, st = a.get("item", "?"), a.get("status", "假设")
        if st == "已确认":
            add(rows, "假设条件", item, "已确认", PASS)
        else:
            how = a.get("verify")
            add(rows, "假设条件", item, st, COND, how or "缺少验证方法: 写明谁、怎么确认")


def check_uncomputable(rows, proj, comps):
    tests = proj.get("tests", [])
    cats = dict(UNCOMPUTABLE)
    if comps and any(c.type in MEASURE_TYPES for c in comps):
        cats = {"测量能力": "测量重复性/GR&R、与基准设备的相关性", **cats}
    for cat, what in cats.items():
        cover = [t for t in tests if cat in t.get("covers", [])]
        if not cover:
            add(rows, "无法计算项", cat, what, TODO, "本工具无法计算, 且项目文件没有对应验证计划 (tests)")
            continue
        for t in cover:
            done = t.get("status") == "已通过"
            add(rows, "无法计算项", cat, t.get("item", ""), PASS if done else COND,
                "" if done else f"验证: {t.get('item', '')} ({t.get('when', '时间待定')})")


VERDICT = {
    PASS: ("可行", "本工具能计算的项目全部通过, 假设已确认, 验证项已通过。仍需正常的详细设计评审。"),
    COND: ("有条件可行", "没有不可行项, 但下列条件必须全部成立或验证通过; 在此之前只能作为概念方案, "
                         "关键尺寸不要据此直接出加工图。"),
    TODO: ("评估未完成", "有本工具无法计算、且没有验证计划的项目; 补充验证计划前不能声称方案可行。"),
    FAIL: ("不可行", "存在不可行项, 不得作为推荐方案出图; 修改后重新运行本判定。"),
}


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project", help="项目 JSON")
    ap.add_argument("--out", help="报告写入文件 (UTF-8)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args(argv)
    try:
        proj = json.load(open(a.project, encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        fail(f"无法读取项目文件: {e}")
    base = os.path.dirname(os.path.abspath(a.project))
    rows, spec, comps = [], None, None
    try:
        if proj.get("layout"):
            spec, comps = check_layout(rows, proj, base)
        else:
            add(rows, "3D 布局", "布局", "项目文件未给 layout", TODO, "用 layout3d.py 建布局并检查干涉")
        if proj.get("cycle"):
            with redirect_stdout(io.StringIO()):
                check_cycle(rows, proj, base, comps)
        else:
            add(rows, "节拍", "节拍表", "项目文件未给 cycle", TODO, "用 cycle_time.py 核算节拍")
    except (layout3d.SpecError, OSError, json.JSONDecodeError) as e:
        add(rows, "输入", "项目引用的文件", str(e), FAIL, "修正后重新运行")
    except SystemExit as e:
        add(rows, "输入", "节拍表", str(e.code), FAIL, "修正后重新运行")
    if not proj.get("calcs"):
        add(rows, "选型计算", "选型计算", "项目文件未给 calcs", TODO, "关键受力/节拍件用 mech_calc.py 计算并写入 calcs")
    check_calcs(rows, proj, spec)
    check_assumptions(rows, proj)
    check_uncomputable(rows, proj, comps)

    for acc in proj.get("accepted", []):
        key, reason = acc.get("match", ""), acc.get("reason", "")
        for r in rows:
            if key and r["状态"] == COND and (key in r["检查项"] or key in r["结果"]):
                r["状态"], r["结果"] = PASS, f"{r['结果']} (已接受: {reason or '未写理由'})"
    worst = max((r["状态"] for r in rows), key=lambda s: RANK[s])
    verdict, meaning = VERDICT[worst]
    if a.json:
        text = json.dumps({"verdict": verdict, "rows": rows}, ensure_ascii=False, indent=2)
    else:
        n = {s: sum(1 for r in rows if r["状态"] == s) for s in RANK}
        md = lambda s: str(s).replace("|", "\\|")
        lines = [f"## 可行性判定: {proj.get('title', os.path.basename(a.project))}", "",
                 f"**结论: {verdict}** — {meaning}", "",
                 f"通过 {n[PASS]} 项, 有条件 {n[COND]} 项, 未验证 {n[TODO]} 项, 不可行 {n[FAIL]} 项。", "",
                 "| 类别 | 检查项 | 结果 | 状态 |", "|---|---|---|:-:|"]
        for r in sorted(rows, key=lambda r: -RANK[r["状态"]]):
            lines.append(f"| {r['类别']} | {md(r['检查项'])} | {md(r['结果'])} | {r['状态']} |")
        todo = [r for r in rows if r["状态"] != PASS]
        if todo:
            lines += ["", "### 出图前必须解决或验证", ""]
            lines += [f"{i}. [{r['状态']}] {r['检查项']}: {r['条件/验证']}" for i, r in
                      enumerate(sorted(todo, key=lambda r: -RANK[r["状态"]]), start=1)]
        lines += ["", "> \"可行\" 只代表本工具能计算的范围 (干涉、运动包络、行程、节拍、选型、安全距离、补料周期) "
                      "内没有发现问题; 无法计算的项目按验证计划完成后才算闭环。"]
        text = "\n".join(lines)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写入 {a.out}  结论: {verdict}")
    else:
        print(text)
    return RANK[worst]


if __name__ == "__main__":
    sys.exit(main())
