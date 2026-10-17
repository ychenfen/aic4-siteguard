"""论文实验：在仿真场景上比较告警策略，输出 results/*.csv、results/*.md 与 docs/paper/figures/*.png。

    python scripts/run_experiments.py            # 完整实验（约数分钟）
    python scripts/run_experiments.py --quick    # 少量种子快速检查

实验设置（与论文第 5 章一致）：
- 场景：每个 10 分钟、5 fps、6 名工人、1 个塔吊区 + 1 个基坑临边区，随机生成违规与烟火事件；
- 检测器误差：siteguard.sim.NoiseModel 默认参数（强度 k=1）；
- 实验一：五种策略对比（20 个随机种子）：两个基线 B1/B2、两个消融 A1/A2、本文方法；
- 实验二：确认时长缩放与命中占比阈值扫描（10 个种子）；
- 实验三：检测器误差强度 k 扫描（10 个种子）。
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from siteguard.engine import load_config  # noqa: E402
from siteguard.evaluate import KINDS, run_strategy, score, strategy_config  # noqa: E402
from siteguard.sim import NoiseModel, generate  # noqa: E402

RES = ROOT / "results"
FIG = ROOT / "docs" / "paper" / "figures"
STRATS = ["frame", "dedup", "dur", "ours_cd", "ours"]
NAMES = {"frame": "B1 逐帧报警", "dedup": "B2 逐帧+固定冷却", "dur": "A1 仅时长确认",
         "ours_cd": "A2 双条件确认+固定冷却", "ours": "本文方法"}
KIND_NAMES = {"no_helmet": "未戴安全帽", "no_vest": "未穿反光背心", "crane": "进入塔吊区",
              "pit": "基坑临边滞留", "fire": "烟火"}


def _job(args):
    seed, k, specs = args
    sc = generate(seed=seed, noise=NoiseModel().scaled(k))
    out = []
    for tag, cfg in specs:
        r = score(sc, run_strategy(sc, cfg))
        out.append((tag, seed, k, r))
    return out


def run(jobs, workers):
    with ProcessPoolExecutor(workers) as ex:
        res = []
        for part in ex.map(_job, jobs):
            res += part
    return res


def ms(xs):
    xs = [x for x in xs if not (isinstance(x, float) and math.isnan(x))]
    if not xs:
        return float("nan"), float("nan")
    return statistics.fmean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)


def write_csv(path, rows, header):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    n1, n2 = (4, 3) if a.quick else (20, 10)
    base = load_config()

    # ---------------- 实验一 ----------------
    specs = [(s, strategy_config(s, base)) for s in STRATS]
    r1 = run([(seed, 1.0, specs) for seed in range(n1)], a.workers)
    rows, md = [], ["| 策略 | 事件召回率 | 误报（次/小时） | 告警精确率 | 每事件告警数 | 平均确认时延（秒） |",
                    "|---|---|---|---|---|---|"]
    summary = {}
    for s in STRATS:
        rs = [r for tag, _, _, r in r1 if tag == s]
        m = {f: ms([getattr(r, f) for r in rs]) for f in
             ["recall", "fa_per_hour", "precision", "alarms_per_event", "latency"]}
        summary[s] = m
        rows.append([s] + [f"{m[f][0]:.4f}" for f in m] + [f"{m[f][1]:.4f}" for f in m])
        md.append(f"| {NAMES[s]} | {m['recall'][0]:.3f} ± {m['recall'][1]:.3f} | "
                  f"{m['fa_per_hour'][0]:.1f} ± {m['fa_per_hour'][1]:.1f} | "
                  f"{m['precision'][0]:.3f} ± {m['precision'][1]:.3f} | "
                  f"{m['alarms_per_event'][0]:.2f} ± {m['alarms_per_event'][1]:.2f} | "
                  f"{m['latency'][0]:.2f} ± {m['latency'][1]:.2f} |")
    write_csv(RES / "exp1_main.csv", rows,
              ["strategy", "recall", "fa_per_hour", "precision", "alarms_per_event", "latency",
               "recall_sd", "fa_sd", "precision_sd", "ape_sd", "latency_sd"])

    # 分规则（本文方法 vs 逐帧+冷却去重）
    md += ["", "分规则结果：", "",
           "| 规则 | 真值事件数（均值/场景） | 召回率：B2 | 召回率：本文 | 误报/小时：B2 | 误报/小时：本文 |",
           "|---|---|---|---|---|---|"]
    kind_rows = []
    for k in KINDS:
        d = [r for tag, _, _, r in r1 if tag == "dedup"]
        o = [r for tag, _, _, r in r1 if tag == "ours"]
        ev = ms([r.per_kind[k]["events"] for r in o])[0]
        rd, ro = ms([r.per_kind[k]["recall"] for r in d])[0], ms([r.per_kind[k]["recall"] for r in o])[0]
        fd, fo = ms([r.per_kind[k]["fa_per_hour"] for r in d])[0], ms([r.per_kind[k]["fa_per_hour"] for r in o])[0]
        kind_rows.append([k, ev, rd, ro, fd, fo])
        md.append(f"| {KIND_NAMES[k]} | {ev:.1f} | {rd:.3f} | {ro:.3f} | {fd:.1f} | {fo:.1f} |")
    write_csv(RES / "exp1_per_kind.csv", kind_rows,
              ["kind", "events_per_scene", "recall_dedup", "recall_ours", "fa_dedup", "fa_ours"])

    # 复合风险
    o = [r for tag, _, _, r in r1 if tag == "ours"]
    comp_total = sum(r.n_compound for r in o)
    comp_hit = sum(r.compound_recall * r.n_compound for r in o if r.n_compound)
    major_false = sum(r.major_false for r in o)
    hours = len(o) * 600 / 3600
    md += ["", f"复合风险：真值复合事件 {comp_total} 个，升级为重大 {comp_hit:.0f} 个"
               f"（召回率 {comp_hit / comp_total:.3f}）；误升级 {major_false} 次"
               f"（{major_false / hours:.2f} 次/小时）；仿真总时长 {hours:.1f} 小时。"]
    write_csv(RES / "exp1_compound.csv", [[comp_total, comp_hit, major_false, hours]],
              ["gt_compound", "escalated", "false_major", "hours"])
    (RES / "exp1_main.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))

    # ---------------- 实验二 ----------------
    scales = [0.0, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0]
    ratios = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]
    specs2 = []
    for c in scales:
        specs2.append((f"scale={c}", strategy_config("ours_nc", base, confirm_scale=c)))
    for q in ratios:
        cfg = strategy_config("ours_nc", base)
        cfg["confirm_ratio"] = q
        specs2.append((f"ratio={q}", cfg))
    r2 = run([(seed, 1.0, specs2) for seed in range(100, 100 + n2)], a.workers)
    rows2 = []
    for tag, _ in specs2:
        rs = [r for t, _, _, r in r2 if t == tag]
        rows2.append([tag] + [f"{ms([getattr(r, f) for r in rs])[0]:.4f}"
                              for f in ["recall", "fa_per_hour", "latency", "alarms_per_event"]])
    write_csv(RES / "exp2_sweep.csv", rows2, ["setting", "recall", "fa_per_hour", "latency", "alarms_per_event"])
    print("\n".join(",".join(map(str, r)) for r in rows2))

    # ---------------- 实验三 ----------------
    ks = [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]
    specs3 = [(s, strategy_config(s, base)) for s in ["dedup", "dur", "ours_nc"]]  # ours_nc = 本文方法（不含复合升级）
    r3 = run([(seed, k, specs3) for seed in range(200, 200 + n2) for k in ks], a.workers)
    rows3 = []
    for k in ks:
        for s, _ in specs3:
            rs = [r for t, _, kk, r in r3 if t == s and kk == k]
            rows3.append([k, s] + [f"{ms([getattr(r, f) for r in rs])[0]:.4f}"
                                   for f in ["recall", "fa_per_hour", "precision"]])
    write_csv(RES / "exp3_noise.csv", rows3, ["k", "strategy", "recall", "fa_per_hour", "precision"])
    print("\n".join(",".join(map(str, r)) for r in rows3))

    plot(summary, rows2, rows3)


def plot(summary, rows2, rows3):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager  # noqa: F401

    plt.rcParams.update({
        "font.family": ["Noto Sans CJK SC", "Noto Sans CJK TC", "DejaVu Sans"],
        "axes.unicode_minus": False, "font.size": 10,
        "axes.edgecolor": "#8a8984", "axes.labelcolor": "#2b2a27", "xtick.color": "#52514e",
        "ytick.color": "#52514e", "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#e6e5e1", "grid.linewidth": 0.8, "figure.dpi": 150,
    })
    INK, MUTED = "#2b2a27", "#52514e"
    C = {"dedup": "#eb6834", "dur": "#1baf7a", "ours_cd": "#eda100", "ours_nc": "#2a78d6", "ours": "#2a78d6",
         "frame": "#b4b2ab"}
    FIG.mkdir(parents=True, exist_ok=True)

    # 图：策略对比（误报 log 轴 + 召回）
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    strats = STRATS
    y = range(len(strats))
    fa = [summary[s]["fa_per_hour"][0] for s in strats]
    rc = [summary[s]["recall"][0] for s in strats]
    a1.barh(y, fa, color=[C[s] for s in strats], height=0.55)
    a1.set_xscale("log")
    a1.set_yticks(list(y), [NAMES[s] for s in strats])
    a1.invert_yaxis()
    a1.set_xlabel("误报次数 / 小时（对数轴）")
    a1.grid(axis="y", visible=False)
    for i, v in enumerate(fa):
        a1.text(v * 1.15, i, f"{v:,.0f}", va="center", color=INK, fontsize=9)
    a1.set_xlim(right=max(fa) * 8)
    a2.barh(y, rc, color=[C[s] for s in strats], height=0.55)
    a2.set_yticks(list(y), [""] * len(strats))
    a2.invert_yaxis()
    a2.set_xlim(0, 1.12)
    a2.set_xlabel("事件召回率")
    a2.grid(axis="y", visible=False)
    for i, v in enumerate(rc):
        a2.text(v + 0.01, i, f"{v:.3f}", va="center", color=INK, fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG / "fig_strategy_compare.png")
    plt.close(fig)

    # 图：确认时长缩放 → 误报 vs 时延
    sc = [r for r in rows2 if r[0].startswith("scale=")]
    rt = [r for r in rows2 if r[0].startswith("ratio=")]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    xs = [float(r[0].split("=")[1]) for r in sc]
    lat = [float(r[3]) for r in sc]
    fas = [float(r[2]) for r in sc]
    a1.plot(lat, fas, color=C["ours"], lw=2, marker="o", ms=5)
    a1.set_yscale("log")
    a1.set_xlabel("平均确认时延（秒）")
    a1.set_ylabel("误报次数 / 小时（对数轴）", color=INK)
    for x, la, fa_, r in zip(xs, lat, fas, sc):
        a1.annotate(f"×{x:g}  召回 {float(r[1]):.2f}", (la, fa_), textcoords="offset points",
                    xytext=(7, 3), ha="left", fontsize=7.5, color=MUTED)
    a1.set_xlim(0, max(lat) * 1.35)
    a1.set_title("确认时长缩放（×1 为默认值）", fontsize=9.5, color=INK, loc="left")
    xq = [float(r[0].split("=")[1]) for r in rt]
    a2.plot(xq, [float(r[2]) for r in rt], color=C["ours"], lw=2, marker="o", ms=5)
    a2.set_yscale("log")
    a2.set_xlabel("命中占比阈值 confirm_ratio")
    a2.set_ylabel("误报次数 / 小时（对数轴）", color=INK)
    for x, r in zip(xq, rt):
        a2.annotate(f"召回 {float(r[1]):.2f}", (x, float(r[2])), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=7.5, color=MUTED)
    a2.set_ylim(top=max(float(r[2]) for r in rt) * 2)
    from matplotlib.ticker import FixedLocator, NullLocator, ScalarFormatter
    a2.yaxis.set_major_locator(FixedLocator([20, 50, 100, 200, 500]))
    a2.yaxis.set_minor_locator(NullLocator())
    a2.yaxis.set_major_formatter(ScalarFormatter())
    a2.set_title("命中占比阈值（默认 0.7）", fontsize=9.5, color=INK, loc="left")
    fig.tight_layout()
    fig.savefig(FIG / "fig_sweep.png")
    plt.close(fig)

    # 图：检测器误差强度
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.4))
    for s in ["dedup", "dur", "ours_nc"]:
        rr = [r for r in rows3 if r[1] == s]
        ks = [float(r[0]) for r in rr]
        fa = [max(float(r[3]), 0.5) for r in rr]  # 0 画在对数轴底部
        rc = [float(r[2]) for r in rr]
        lab = {"dedup": "B2 逐帧+固定冷却", "dur": "A1 仅时长确认", "ours_nc": "本文方法"}[s]
        a1.plot(ks, fa, color=C[s], lw=2, marker="o", ms=5, label=lab)
        a2.plot(ks, rc, color=C[s], lw=2, marker="o", ms=5, label=lab)
        a1.annotate(lab, (ks[-1], fa[-1]), textcoords="offset points", xytext=(6, 0), va="center",
                    fontsize=8.5, color=INK)
    a1.set_yscale("log")
    a1.set_xlabel("检测器误差强度 k（1 = 默认误差模型）")
    a1.set_ylabel("误报次数 / 小时（对数轴）")
    a1.set_xlim(right=3.9)
    a2.set_xlabel("检测器误差强度 k")
    a2.set_ylabel("事件召回率")
    a2.set_ylim(0, 1.05)
    a2.legend(frameon=False, loc="lower left", fontsize=8.5)
    fig.tight_layout()
    fig.savefig(FIG / "fig_noise.png")
    plt.close(fig)
    print("figures written")


if __name__ == "__main__":
    main()
