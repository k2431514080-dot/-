#!/usr/bin/env python3
"""方案加权评分 — 仅依赖 Python 标准库.

输入 CSV (UTF-8 或 GBK):
  criterion,weight,方案A,方案B,方案C,note
  节拍满足度,25,4,5,3,按节拍表余量打分
  磁环互吸卡料风险,20,2,4,5,
  满足客户指定品牌,veto,1,1,0,一票否决: 1=满足 0=不满足

  - 第 1 列: 评价项; weight/权重 列: 权重 (任意正数, 自动归一化) 或 veto/否决
  - 其余列 (除 note/备注/说明) 为各方案得分, 越高越好 (成本、风险类请反向打分)
  - 默认 5 分制, 可用 --scale 10 改为 10 分制

输出: 加权得分 (满分 100)、排名、否决情况、权重敏感性 (每项权重 ±30% 是否改变第一名).

示例: python3 scheme_score.py scoring.csv
"""

import argparse
import csv
import json
import sys

WEIGHT_COLS = ("weight", "权重")
NOTE_COLS = ("note", "备注", "说明", "依据")
VETO = ("veto", "否决", "一票否决")
YES = ("1", "y", "yes", "是", "ok", "满足", "√", "true")
NO = ("0", "n", "no", "否", "ng", "不满足", "×", "x", "false")


def fail(msg):
    sys.exit(f"错误: {msg}")


def read_rows(path):
    for enc in ("utf-8-sig", "gbk"):
        try:
            with open(path, newline="", encoding=enc) as f:
                return [r for r in csv.reader(f) if any(c.strip() for c in r)]
        except UnicodeDecodeError:
            continue
    fail("文件编码无法识别, 请另存为 UTF-8 CSV")


def load(path, scale):
    rows = read_rows(path)
    if len(rows) < 2:
        fail("至少需要表头和一行评价项")
    header = [h.strip() for h in rows[0]]
    low = [h.lower() for h in header]
    w_col = next((i for i, h in enumerate(low) if h in WEIGHT_COLS), None)
    if w_col is None:
        fail("缺少 weight/权重 列")
    note_col = next((i for i, h in enumerate(low) if h in NOTE_COLS), None)
    schemes = [(i, header[i]) for i in range(1, len(header)) if i not in (w_col, note_col)]
    if len(schemes) < 2:
        fail("至少需要 2 个方案列")
    crits, vetoes = [], []
    for n, r in enumerate(rows[1:], start=2):
        r = r + [""] * (len(header) - len(r))
        name, w = r[0].strip(), r[w_col].strip().lower()
        note = r[note_col].strip() if note_col is not None else ""
        if w in VETO:
            vals = []
            for i, s in schemes:
                v = r[i].strip().lower()
                if v not in YES + NO:
                    fail(f"第 {n} 行: 否决项 '{name}' 的 {s} 应填 1/0 (满足/不满足)")
                vals.append(v in YES)
            vetoes.append((name, vals, note))
            continue
        try:
            weight = float(w[:-1]) if w.endswith("%") else float(w)
            scores = [float(r[i]) for i, _ in schemes]
        except ValueError:
            fail(f"第 {n} 行: 权重或得分不是数字")
        if weight <= 0:
            fail(f"第 {n} 行: 权重须 > 0")
        for s in scores:
            if not 0 <= s <= scale:
                fail(f"第 {n} 行: 得分 {s:g} 超出 0~{scale:g}")
        crits.append((name, weight, scores, note))
    if not crits:
        fail("没有可评分的评价项")
    return [s for _, s in schemes], crits, vetoes


def totals(crits, n, scale, weights=None):
    weights = weights or [c[1] for c in crits]
    wsum = sum(weights)
    return [sum(w / wsum * c[2][j] / scale * 100 for w, c in zip(weights, crits)) for j in range(n)]


def main(argv=None):
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--scale", type=float, default=5, help="满分 (默认 5)")
    ap.add_argument("--swing", type=float, default=0.3, help="敏感性分析权重变化幅度 (默认 0.3 = ±30%%)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", help="写入文件 (UTF-8)")
    a = ap.parse_args(argv)

    schemes, crits, vetoes = load(a.csv, a.scale)
    n = len(schemes)
    tot = totals(crits, n, a.scale)
    alive = [all(v[1][j] for v in vetoes) for j in range(n)]
    ranked = sorted(range(n), key=lambda j: (not alive[j], -tot[j]))
    best = ranked[0] if alive[ranked[0]] else None

    flips = []
    if best is not None:
        for k, c in enumerate(crits):
            for f in (1 - a.swing, 1 + a.swing):
                w = [x[1] for x in crits]
                w[k] *= f
                t2 = totals(crits, n, a.scale, w)
                win = max((j for j in range(n) if alive[j]), key=lambda j: t2[j])
                if win != best:
                    flips.append(f"「{c[0]}」权重 ×{f:g} 时第一名变为 {schemes[win]}")

    wsum = sum(c[1] for c in crits)
    md = lambda s: str(s).replace("|", "\\|")
    lines = ["## 方案加权评分", "",
             "| 评价项 | 权重 | " + " | ".join(md(s) for s in schemes) + " | 依据 |",
             "|---|---:|" + "---:|" * n + "---|"]
    for name, w, scores, note in crits:
        cells = [f"{s:g} ({w / wsum * s / a.scale * 100:.1f})" for s in scores]
        lines.append(f"| {md(name)} | {w / wsum:.0%} | " + " | ".join(cells) + f" | {md(note)} |")
    for name, vals, note in vetoes:
        lines.append(f"| {md(name)} | 否决项 | " + " | ".join("满足" if v else "**不满足**" for v in vals)
                     + f" | {md(note)} |")
    lines.append("| **加权总分 (满分 100)** | 100% | " + " | ".join(
        f"**{t:.1f}**" if alive[j] else f"~~{t:.1f}~~ 否决" for j, t in enumerate(tot)) + " | |")
    lines += ["", "单元格格式: 得分 (加权得分)", "", "**排名**", ""]
    for r, j in enumerate(ranked, start=1):
        lines.append(f"{r}. {schemes[j]}: {tot[j]:.1f}" + ("" if alive[j] else " (否决项不满足, 淘汰)"))
    lines.append("")
    if best is None:
        lines.append("**结论**: 所有方案均未通过否决项, 需调整方案或放宽硬性要求。")
    else:
        others = [j for j in ranked[1:] if alive[j]]
        gap = tot[best] - tot[others[0]] if others else None
        concl = f"**结论**: 推荐 {schemes[best]} ({tot[best]:.1f} 分)"
        if gap is not None:
            concl += f", 领先第二名 {schemes[others[0]]} {gap:.1f} 分"
        lines.append(concl + "。")
        if gap is not None and gap < 5:
            lines.append(f"- 差距 < 5 分, 结论对打分主观性敏感, 建议用样机/实测数据补强关键评价项。")
        if flips:
            lines.append(f"- 权重敏感: " + "; ".join(flips) + "。汇报时需说明权重依据。")
        else:
            lines.append(f"- 各项权重 ±{a.swing:.0%} 变化时第一名不变, 结论稳健。")
    text = "\n".join(lines)
    if a.json:
        text = json.dumps({"schemes": schemes, "totals": tot, "alive": alive,
                           "ranking": [schemes[j] for j in ranked],
                           "recommended": schemes[best] if best is not None else None,
                           "sensitivity_flips": flips}, ensure_ascii=False, indent=2)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"已写入 {a.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
