#!/usr/bin/env python3
"""节拍 (Cycle Time) / 时序分析 — 仅依赖 Python 标准库.

输入: 动作表 CSV (UTF-8 或 GBK; Excel "CSV UTF-8" 另存即可)
  id,station,action,duration,after,resource,note
  id        动作编号, 唯一; 只用字母/数字/下划线/中文/点, 不含 + - ^ ;
  station   工位或机构名称
  action    动作描述
  duration  动作时间 s (也可写 300ms)
  after     前置条件, 多个用 ; 分隔, 空 = 节拍开始即可动作
              A3        A3 结束后开始
              A3+0.05   A3 结束 0.05 s 后开始
              A3-0.10   A3 结束前 0.10 s 提前开始 (动作重叠)
              ^A3       与 A3 同时开始
              ^A3+0.2   A3 开始 0.2 s 后开始
  resource  执行机构 (可选). 同一机构的动作不能重叠; 其动作时间之和是节拍下限
  note      备注 (可选)
  中文表头 编号/工位/动作/时间/前置/执行机构/备注 亦可.

模式
  sync  (默认) 整张表是一台设备的一个节拍 (转盘机/同步搬运), CT = 关键路径长度
  async 各工位独立循环 (带缓存的直线异步线), 跨工位前置被忽略, CT = 最慢工位

示例
  python3 cycle_time.py actions.csv --target-uph 1800 --oee 0.85 --svg gantt.svg
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import defaultdict

EPS = 1e-9
ALIASES = {
    "id": ["id", "编号", "序号", "步骤"],
    "station": ["station", "工位", "模块"],
    "action": ["action", "动作", "动作描述", "名称"],
    "duration": ["duration", "time", "duration_s", "时间", "时间(s)", "时间s", "耗时", "耗时(s)"],
    "after": ["after", "前置", "前置条件", "依赖", "predecessors"],
    "resource": ["resource", "执行机构", "机构", "资源"],
    "note": ["note", "备注", "说明"],
}
ID_RE = re.compile(r"^[0-9A-Za-z_.一-鿿]+$")
DEP_RE = re.compile(r"^(\^)?([0-9A-Za-z_.一-鿿]+)(?:([+-])(\d+(?:\.\d+)?)(ms|s)?)?$")


class Act:
    def __init__(self, row, aid, station, action, dur, deps, resource, note):
        self.row, self.id, self.station, self.action = row, aid, station, action
        self.dur, self.deps, self.resource, self.note = dur, deps, resource, note


def fail(msg):
    sys.exit(f"错误: {msg}")


def md(s):
    """Markdown 表格单元格转义."""
    return str(s).replace("|", "\\|").replace("\n", " ")


def parse_seconds(text, where):
    t = text.strip().lower().replace(" ", "")
    m = re.match(r"^(\d+(?:\.\d+)?)(ms|s)?$", t)
    if not m:
        fail(f"{where}: 无法识别的时间 '{text}'")
    v = float(m.group(1))
    return v / 1000 if m.group(2) == "ms" else v


def read_rows(path):
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, newline="", encoding=enc) as f:
                return list(csv.reader(f))
        except UnicodeDecodeError:
            continue
    fail("文件编码无法识别, 请另存为 UTF-8 CSV")


def load(path):
    rows = [r for r in read_rows(path) if any(c.strip() for c in r)]
    if not rows:
        fail("CSV 为空")
    header = [h.strip().lower() for h in rows[0]]
    col = {}
    for key, names in ALIASES.items():
        for i, h in enumerate(header):
            if h in names:
                col[key] = i
                break
    for key in ("id", "duration"):
        if key not in col:
            fail(f"缺少必需列 {key} (或中文: {'/'.join(ALIASES[key][1:])})")

    def cell(r, key):
        i = col.get(key)
        return r[i].strip() if i is not None and i < len(r) else ""

    acts, order = {}, []
    for n, r in enumerate(rows[1:], start=2):
        aid = cell(r, "id")
        if not aid:
            continue
        if not ID_RE.match(aid):
            fail(f"第 {n} 行: 编号 '{aid}' 含非法字符 (不能含 + - ^ ; 空格)")
        if aid in acts:
            fail(f"第 {n} 行: 编号 '{aid}' 重复")
        deps = []
        text = re.sub(r"\s*([+\-^])\s*", r"\1", cell(r, "after"))
        for tok in filter(None, re.split(r"[;；,，、\s]+", text)):
            m = DEP_RE.match(tok)
            if not m:
                fail(f"第 {n} 行: 前置条件 '{tok}' 格式错误")
            lag = 0.0
            if m.group(4):
                lag = float(m.group(4)) / (1000 if m.group(5) == "ms" else 1)
                lag = -lag if m.group(3) == "-" else lag
            deps.append((m.group(2), "SS" if m.group(1) else "FS", lag))
        dur = parse_seconds(cell(r, "duration") or "0", f"第 {n} 行")
        acts[aid] = Act(n, aid, cell(r, "station") or "-", cell(r, "action") or aid,
                        dur, deps, cell(r, "resource"), cell(r, "note"))
        order.append(aid)
    if not acts:
        fail("没有有效动作行")
    for a in acts.values():
        for p, _, _ in a.deps:
            if p not in acts:
                fail(f"第 {a.row} 行: 前置动作 '{p}' 不存在")
    return acts, order


def topo(acts, order):
    indeg = {k: 0 for k in acts}
    succ = defaultdict(list)
    for a in acts.values():
        for p, _, _ in a.deps:
            indeg[a.id] += 1
            succ[p].append(a.id)
    queue = [k for k in order if indeg[k] == 0]
    out = []
    while queue:
        k = queue.pop(0)
        out.append(k)
        for s in succ[k]:
            indeg[s] -= 1
            if indeg[s] == 0:
                queue.append(s)
    if len(out) != len(acts):
        loop = [k for k in order if indeg[k] > 0]
        fail("前置条件存在循环依赖: " + ", ".join(loop))
    return out


def schedule(acts, topo_order, ids):
    """对子集 ids 做正推/逆推. 返回 es, ef, slack, makespan."""
    es, ef = {}, {}
    for k in topo_order:
        if k not in ids:
            continue
        a = acts[k]
        s = 0.0
        for p, kind, lag in a.deps:
            if p in ids:
                s = max(s, (ef[p] if kind == "FS" else es[p]) + lag)
        es[k], ef[k] = s, s + a.dur
    span = max(ef.values())
    lf = {k: span for k in es}
    ls = {}
    for k in reversed(topo_order):
        if k not in es:
            continue
        ls[k] = lf[k] - acts[k].dur
        for p, kind, lag in acts[k].deps:
            if p in es:
                bound = ls[k] - lag if kind == "FS" else ls[k] - lag + acts[p].dur
                lf[p] = min(lf[p], bound)
    slack = {k: max(0.0, ls[k] - es[k]) for k in es}
    return es, ef, slack, span


def union_length(intervals):
    total, cur_s, cur_e = 0.0, None, None
    for s, e in sorted(intervals):
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += cur_e - cur_s
    return total


def analyze(acts, order, mode):
    topo_order = topo(acts, order)
    stations = list(dict.fromkeys(acts[k].station for k in order))
    dropped = []
    if mode == "sync":
        es, ef, slack, ct = schedule(acts, topo_order, set(acts))
        st_ct = {}
        bottleneck = None
    else:
        es, ef, slack, st_ct = {}, {}, {}, {}
        for st in stations:
            ids = {k for k in acts if acts[k].station == st}
            e1, e2, sl, span = schedule(acts, topo_order, ids)
            es.update(e1), ef.update(e2), slack.update(sl)
            st_ct[st] = span
        for a in acts.values():
            dropped += [f"{p}→{a.id}" for p, _, _ in a.deps if acts[p].station != a.station]
        bottleneck = max(st_ct, key=st_ct.get)
        ct = st_ct[bottleneck]
        # 非瓶颈工位不在关键路径上
        for k in acts:
            if acts[k].station != bottleneck:
                slack[k] = max(slack[k], ct - st_ct[acts[k].station])

    res_busy = defaultdict(float)
    res_items = defaultdict(list)
    for k in order:
        a = acts[k]
        if a.resource:
            res_busy[a.resource] += a.dur
            res_items[a.resource].append(k)
    overlaps = []
    for res, items in res_items.items():
        items = sorted(items, key=lambda k: es[k])
        for x, y in zip(items, items[1:]):
            if es[y] < ef[x] - EPS:
                overlaps.append((res, x, y, ef[x] - es[y]))

    st_rows = []
    for st in stations:
        ks = [k for k in order if acts[k].station == st]
        start = min(es[k] for k in ks)
        end = max(ef[k] for k in ks)
        busy = union_length([(es[k], ef[k]) for k in ks])
        st_rows.append({"station": st, "start": start, "end": end, "span": end - start,
                        "busy": busy, "util": busy / ct if ct else 0.0})
    critical = sorted((k for k in acts if slack[k] <= 1e-6 and acts[k].dur > 0),
                      key=lambda k: (es[k], order.index(k)))
    return {"ct": ct, "es": es, "ef": ef, "slack": slack, "critical": critical,
            "stations": st_rows, "station_ct": st_ct, "bottleneck": bottleneck,
            "res_busy": dict(res_busy), "overlaps": overlaps, "dropped": dropped}


# ---------------------------------------------------------------- output

def dwidth(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def fit(s, w):
    if dwidth(s) <= w:
        return s + " " * (w - dwidth(s))
    out = ""
    for c in s:
        if dwidth(out + c) > w - 2:
            break
        out += c
    return out + ".." + " " * (w - 2 - dwidth(out))


def ascii_gantt(acts, order, r, width=56, label_w=30):
    ct = max(r["ct"], max(r["ef"].values()))
    col = lambda t: int(round(t / ct * width)) if ct else 0
    crit = set(r["critical"])
    ruler = [" "] * (width + 8)
    for k in range(5):
        t = ct * k / 4
        s = f"{t:.2f}"
        pos = min(col(t), width + 8 - len(s))
        for j, ch in enumerate(s):
            ruler[pos + j] = ch
    lines = [fit("时间(s)", label_w) + " " + "".join(ruler).rstrip()]
    for k in order:
        a = acts[k]
        c0, c1 = col(r["es"][k]), col(r["ef"][k])
        if c1 <= c0 and a.dur > 0:
            c1 = c0 + 1
        bar = [" "] * width
        for j in range(c0, min(c1, width)):
            bar[j] = "#" if k in crit else "="
        lines.append(fit(f"{k} {a.station}/{a.action}", label_w) + "|" + "".join(bar) + "|")
    lines.append(fit("", label_w) + " # 关键路径   = 非关键动作")
    return "\n".join(lines)


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def svg_gantt(acts, order, r, title):
    ct = max(r["ct"], max(r["ef"].values()))
    label_w, chart_w, row_h, top = 300, 640, 24, 64
    height = top + row_h * len(order) + 40
    sx = lambda t: label_w + t / ct * chart_w if ct else label_w
    step = next((s for s in (0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 30, 60)
                 if ct / s <= 12), 120)
    crit = set(r["critical"])
    font = "Microsoft YaHei, PingFang SC, Noto Sans CJK SC, WenQuanYi Zen Hei, sans-serif"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{label_w + chart_w + 60}" '
           f'height="{height}" font-family="{font}" font-size="12">',
           '<rect width="100%" height="100%" fill="#ffffff"/>',
           f'<text x="12" y="24" font-size="16" font-weight="bold">{esc(title)}</text>',
           f'<rect x="{label_w + chart_w - 250}" y="12" width="12" height="12" fill="#d9480f"/>'
           f'<text x="{label_w + chart_w - 232}" y="22">关键路径</text>'
           f'<rect x="{label_w + chart_w - 160}" y="12" width="12" height="12" fill="#4c6ef5"/>'
           f'<text x="{label_w + chart_w - 142}" y="22">非关键动作</text>']
    for n in range(1, len(order), 2):
        out.append(f'<rect x="0" y="{top + n * row_h}" width="{label_w + chart_w + 60}" '
                   f'height="{row_h}" fill="#f8f9fa"/>')
    for n in range(int(ct / step + 1e-6) + 1):
        t = round(n * step, 6)
        x = sx(t)
        out.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{height - 36}" '
                   f'stroke="#dee2e6" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{top - 12}" text-anchor="middle" fill="#495057">{t:g}</text>')
    x = sx(r["ct"])
    out.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{height - 36}" '
               f'stroke="#c92a2a" stroke-width="1.5" stroke-dasharray="4 3"/>')
    out.append(f'<text x="{x:.1f}" y="{height - 20}" text-anchor="middle" fill="#c92a2a">'
               f'CT {r["ct"]:.2f} s</text>')
    for n, k in enumerate(order):
        a = acts[k]
        y = top + n * row_h
        out.append(f'<text x="12" y="{y + 16}">{esc(fit(f"{k} {a.station}/{a.action}", 44).rstrip())}</text>')
        x0, x1 = sx(r["es"][k]), sx(r["ef"][k])
        color = "#d9480f" if k in crit else "#4c6ef5"
        out.append(f'<rect x="{x0:.1f}" y="{y + 5}" width="{max(x1 - x0, 1.5):.1f}" height="{row_h - 10}" '
                   f'rx="2" fill="{color}"><title>{esc(a.action)} {a.dur:g}s</title></rect>')
        out.append(f'<text x="{x1 + 4:.1f}" y="{y + 16}" fill="#495057">{a.dur:g}s</text>')
    out.append("</svg>")
    return "\n".join(out)


def build_report(acts, order, r, a):
    ct = r["ct"]
    lines = ["## 节拍分析结果", ""]
    uph = 3600 / ct * a.pcs if ct else 0.0
    real = uph * a.oee
    res_bound = max(r["res_busy"].items(), key=lambda kv: kv[1]) if r["res_busy"] else None
    summary = [("计算模式", "同步: 整机一个节拍" if a.mode == "sync" else "异步: 各工位独立, 取最慢工位")]
    if a.mode == "async":
        summary.append(("瓶颈工位", r["bottleneck"]))
    summary += [("节拍 CT", f"{ct:.3f} s")]
    if res_bound:
        summary.append(("机构节拍下限", f"{res_bound[1]:.3f} s ({res_bound[0]})"))
    summary += [("每节拍产出", f"{a.pcs:g} pcs"),
                ("理论 UPH", f"{uph:,.0f}"),
                (f"实际 UPH (综合效率 {a.oee:.0%})", f"{real:,.0f}"),
                (f"日产能 ({a.hours:g} h)", f"{real * a.hours:,.0f} pcs")]
    verdict = None
    if a.target_uph:
        ct_req = 3600 * a.pcs * a.oee / a.target_uph
        margin = (ct_req - ct) / ct_req
        verdict = "OK" if margin >= 0.10 else ("注意" if margin >= 0 else "NG")
        summary.append(("目标 UPH", f"{a.target_uph:,.0f} → 要求 CT ≤ {ct_req:.3f} s, "
                                    f"余量 {margin:+.1%} [{verdict}]"))
    lines += ["| 指标 | 数值 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in summary] + [""]

    crit = r["critical"]
    lines += ["### 关键路径", "",
              " → ".join(f"{k} {acts[k].action} ({acts[k].dur:g})" for k in crit) or "-", ""]

    lines += ["### 动作时序表", "",
              "| ID | 工位 | 动作 | 时间 s | 开始 s | 结束 s | 浮动 s | 关键 | 执行机构 |",
              "|---|---|---|---:|---:|---:|---:|:-:|---|"]
    for k in order:
        x = acts[k]
        lines.append(f"| {md(k)} | {md(x.station)} | {md(x.action)} | {x.dur:.2f} | {r['es'][k]:.2f} | "
                     f"{r['ef'][k]:.2f} | {r['slack'][k]:.2f} | {'★' if k in crit else ''} | "
                     f"{md(x.resource)} |")
    lines.append("")

    lines += ["### 工位负荷", "", "| 工位 | 开始 s | 结束 s | 跨度 s | 动作占用 s | 占用率 |",
              "|---|---:|---:|---:|---:|---:|"]
    for s in r["stations"]:
        lines.append(f"| {md(s['station'])} | {s['start']:.2f} | {s['end']:.2f} | {s['span']:.2f} | "
                     f"{s['busy']:.2f} | {s['util']:.0%} |")
    lines.append("")
    if r["res_busy"]:
        lines += ["### 执行机构负荷", "", "| 执行机构 | 动作时间合计 s | 占节拍 |", "|---|---:|---:|"]
        for res, busy in sorted(r["res_busy"].items(), key=lambda kv: -kv[1]):
            lines.append(f"| {md(res)} | {busy:.2f} | {busy / ct:.0%} |")
        lines.append("")

    lines += ["### 甘特图", "", "```text", ascii_gantt(acts, order, r), "```", ""]

    tips = []
    if verdict == "NG":
        tips.append(f"节拍不足: 需压缩 {ct - 3600 * a.pcs * a.oee / a.target_uph:.3f} s, 优先处理关键路径。")
    elif verdict == "注意":
        tips.append("节拍余量 < 10%, 调试损失和动作时间偏差会吃掉余量, 建议继续压缩关键路径。")
    longest = sorted(crit, key=lambda k: -acts[k].dur)[:3]
    if longest:
        tips.append("关键路径上耗时最长的动作: " + "、".join(
            f"{k} {acts[k].action} ({acts[k].dur:g} s)" for k in longest) +
            " — 可考虑缩短行程、提高速度、动作重叠 (负 lag) 或拆成并行动作。")
    for res, busy in r["res_busy"].items():
        if busy >= 0.9 * ct:
            tips.append(f"执行机构「{res}」占节拍 {busy / ct:.0%}, 是硬瓶颈: 可用双吸嘴/双工位、"
                        "凸轮取放、取放分离 (一取一放两套机构) 或缩短其动作。")
    if res_bound and a.mode == "sync" and ct - res_bound[1] > 0.05 * ct:
        tips.append(f"节拍 {ct:.2f} s 高于机构下限 {res_bound[1]:.2f} s, 存在等待: 可通过预取料、"
                    "提前动作或跨节拍并行 (如分度时同时取料) 压缩。")
    for res, x, y, ov in r["overlaps"]:
        tips.append(f"[冲突] 执行机构「{res}」的 {x} 与 {y} 时间重叠 {ov:.2f} s, 请补充前置条件。")
    if r["dropped"]:
        tips.append("异步模式已忽略跨工位前置: " + ", ".join(r["dropped"]))
    if tips:
        lines += ["### 优化建议", ""] + [f"- {t}" for t in tips] + [""]
    lines.append("> 动作时间为估算值时, 节拍结论仅用于方案阶段; 样机调试后以实测时间更新本表。")
    return "\n".join(lines), {"ct": ct, "uph_theory": uph, "uph_real": real,
                              "daily": real * a.hours, "verdict": verdict}


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="动作表 CSV")
    ap.add_argument("--mode", choices=["sync", "async"], default="sync", help="sync 同步 (默认) / async 异步")
    ap.add_argument("--pcs", type=float, default=1, help="每节拍产出数量 (多穴/多头, 默认 1)")
    ap.add_argument("--oee", type=float, default=0.85, help="综合效率 = 稼动率×性能×良率 (默认 0.85)")
    ap.add_argument("--hours", type=float, default=20, help="每天运行小时 (默认 20)")
    ap.add_argument("--target-uph", type=float, help="目标 UPH (实际产出)")
    ap.add_argument("--svg", help="输出 SVG 甘特图文件")
    ap.add_argument("--csv-out", help="输出时序结果 CSV (可导入 Excel 作图)")
    ap.add_argument("--out", help="Markdown 报告写入文件 (UTF-8)")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args(argv)
    if not 0 < a.oee <= 1:
        fail(f"--oee 应在 0~1 之间 (85% 写成 0.85), 当前 {a.oee:g}")
    if a.pcs <= 0 or a.hours <= 0 or (a.target_uph is not None and a.target_uph <= 0):
        fail("--pcs、--hours、--target-uph 须 > 0")

    acts, order = load(a.csv)
    r = analyze(acts, order, a.mode)
    text, metrics = build_report(acts, order, r, a)

    if a.svg:
        with open(a.svg, "w", encoding="utf-8") as f:
            f.write(svg_gantt(acts, order, r, f"节拍甘特图  CT = {r['ct']:.2f} s"))
    if a.csv_out:
        with open(a.csv_out, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "station", "action", "duration", "start", "end", "slack", "critical", "resource"])
            for k in order:
                x = acts[k]
                w.writerow([k, x.station, x.action, x.dur, round(r["es"][k], 4), round(r["ef"][k], 4),
                            round(r["slack"][k], 4), int(k in r["critical"]), x.resource])
    if a.json:
        data = dict(metrics, critical_path=r["critical"], stations=r["stations"],
                    resource_busy=r["res_busy"], bottleneck=r["bottleneck"],
                    actions=[{"id": k, "station": acts[k].station, "action": acts[k].action,
                              "duration": acts[k].dur, "start": r["es"][k], "end": r["ef"][k],
                              "slack": r["slack"][k]} for k in order])
        text = json.dumps(data, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写入 {a.out}")
    else:
        print(text)
    for path in (a.svg, a.csv_out):
        if path:
            print(f"已写入 {path}", file=sys.stderr)


if __name__ == "__main__":
    main()
