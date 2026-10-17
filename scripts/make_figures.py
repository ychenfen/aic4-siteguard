"""论文示意图：系统架构图、双条件时序确认示意图。输出到 docs/paper/figures/。"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIG = ROOT / "docs" / "paper" / "figures"
FIG.mkdir(parents=True, exist_ok=True)

plt.rcParams.update({"font.family": ["Noto Sans CJK SC", "Noto Sans CJK TC", "DejaVu Sans"],
                     "axes.unicode_minus": False, "font.size": 10, "figure.dpi": 150})
INK, MUTED, LINE = "#2b2a27", "#52514e", "#8a8984"
BLUE, ORANGE, AQUA, YEL, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#b4b2ab"


def box(ax, x, y, w, h, title, sub, color):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                fc="white", ec=color, lw=1.8))
    ax.add_patch(FancyBboxPatch((x, y + h - 0.09), w, 0.09, boxstyle="square,pad=0", fc=color, ec=color, lw=0))
    ax.text(x + w / 2, y + h * 0.6, title, ha="center", va="center", fontsize=10.5, color=INK, weight="bold")
    ax.text(x + w / 2, y + h * 0.27, sub, ha="center", va="center", fontsize=8, color=MUTED, linespacing=1.4)


def arrow(ax, x1, y1, x2, y2, text=None, rad=0.0):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=12, lw=1.3,
                                 color=LINE, connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.07, text, ha="center", va="bottom", fontsize=7.5, color=MUTED)


def architecture():
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 4.6)
    ax.axis("off")
    # 感知层
    ax.text(0.05, 4.4, "感知层", fontsize=9, color=MUTED)
    box(ax, 0.1, 3.0, 1.7, 1.15, "工地监控视频", "现有摄像头\nRTSP / 录像", GREY)
    box(ax, 2.2, 3.0, 1.9, 1.15, "目标检测", "YOLO 系列\n人/帽/裸头/背心/烟火", BLUE)
    box(ax, 4.5, 3.0, 1.9, 1.15, "人员-装备关联", "头部/躯干区域包含度\n远景不判定", BLUE)
    box(ax, 6.8, 3.0, 1.6, 1.15, "多目标跟踪", "IoU 跟踪\n稳定人员编号", BLUE)
    arrow(ax, 1.8, 3.575, 2.2, 3.575)
    arrow(ax, 4.1, 3.575, 4.5, 3.575)
    arrow(ax, 6.4, 3.575, 6.8, 3.575)
    # 决策层
    ax.text(0.05, 2.62, "决策层", fontsize=9, color=MUTED)
    box(ax, 6.8, 1.3, 1.6, 1.15, "规则判定", "佩戴/危险区多边形\n烟火（rules.json）", AQUA)
    box(ax, 4.5, 1.3, 1.9, 1.15, "双条件时序确认", "持续时长 ≥ T\n命中占比 ≥ ρ", ORANGE)
    box(ax, 2.2, 1.3, 1.9, 1.15, "片段去重与分级", "一段违规报一次\n复合风险升级", ORANGE)
    arrow(ax, 7.6, 3.0, 7.6, 2.45)
    arrow(ax, 6.8, 1.875, 6.4, 1.875)
    arrow(ax, 4.5, 1.875, 4.1, 1.875)
    # 应用层
    ax.text(5.95, 0.47, "← 应用层", fontsize=9, color=MUTED, va="center")
    box(ax, 0.1, 1.3, 1.7, 1.15, "整改通知单", "规范依据/措施/期限\n自动生成", YEL)
    box(ax, 0.1, 0.05, 2.6, 0.95, "整改闭环", "待整改→整改中→待复查→已闭环", YEL)
    box(ax, 3.1, 0.05, 2.6, 0.95, "安全看板与统计", "隐患分布 / 闭环率 / 时效", YEL)
    arrow(ax, 2.2, 1.875, 1.8, 1.875)
    arrow(ax, 0.95, 1.3, 0.95, 1.0)
    arrow(ax, 2.7, 0.525, 3.1, 0.525)
    # 规范库
    box(ax, 8.65, 1.3, 1.25, 2.85, "规范知识", "JGJ59\nGB 2811\nGB 6067.1\nGB 50720\nJGJ 120\n企业规定", GREY)
    arrow(ax, 8.65, 1.875, 8.4, 1.875)
    fig.tight_layout()
    fig.savefig(FIG / "fig_architecture.png")
    plt.close(fig)


def confirmation():
    """同一条时间轴上：逐帧命中 → 仅时长确认 vs 双条件确认。"""
    fps, T, rho, gap = 5, 2.0, 0.7, 1.5
    n = 70  # 14 秒
    hits = [False] * n
    for i in (6, 12, 17, 22, 26, 31):  # 零星误检：每隔约 1 秒一帧
        hits[i] = True
    for i in range(44, 66):  # 真实违规 4.4 秒，中间有 2 帧漏判
        hits[i] = i not in (51, 58)

    def simulate(use_ratio):
        start = last = None
        cnt = sf = 0
        state, fired = [], None
        for i, h in enumerate(hits):
            t = i / fps
            if h:
                if start is None or t - last > gap:
                    start, last, cnt, sf = t, t, 1, i
                else:
                    last, cnt = t, cnt + 1
            if start is not None and t - last > gap:
                start = None
            active = start is not None
            ok = active and h and t - start >= T and (not use_ratio or cnt / (i - sf + 1) >= rho)
            if ok and fired is None:
                fired = t
            state.append(active)
        return state, fired

    s_dur, f_dur = simulate(False)
    s_dual, f_dual = simulate(True)
    fig, ax = plt.subplots(figsize=(10, 2.9))
    t = [i / fps for i in range(n)]
    rows = [(2.0, "逐帧判定（违规帧）"), (1.0, "仅时长确认"), (0.0, "双条件确认")]
    for i, h in enumerate(hits):
        ax.add_patch(plt.Rectangle((t[i], 1.8), 1 / fps * 0.85, 0.4, color=ORANGE if h else "#ecebe8", lw=0))
    for y, st, fired, col in ((0.8, s_dur, f_dur, AQUA), (-0.2, s_dual, f_dual, BLUE)):
        for i, a in enumerate(st):
            if a:
                ax.add_patch(plt.Rectangle((t[i], y), 1 / fps, 0.4, color=col, alpha=0.35, lw=0))
        x = 0.0
        alarms = []
        # 标出触发时刻（逐段）
        for seg_start in [k for k in range(n) if st[k] and (k == 0 or not st[k - 1])]:
            pass
        if fired is not None:
            alarms.append(fired)
        _ = x
    # 两个策略各自的全部触发时刻
    def all_fires(use_ratio):
        out, start, last, cnt, sf, done = [], None, None, 0, 0, False
        for i, h in enumerate(hits):
            tt = i / fps
            if h:
                if start is None or tt - last > gap:
                    start, last, cnt, sf, done = tt, tt, 1, i, False
                else:
                    last, cnt = tt, cnt + 1
            if start is not None and tt - last > gap:
                start = None
            if start is not None and h and not done and tt - start >= T and \
                    (not use_ratio or cnt / (i - sf + 1) >= rho):
                out.append(tt)
                done = True
        return out

    for y, fires, col in ((1.0, all_fires(False), AQUA), (0.0, all_fires(True), BLUE)):
        for f in fires:
            ax.plot([f + 0.1, f + 0.1], [y - 0.25, y + 0.25], color=col, lw=2.5)
            real = f >= 8.8
            ax.annotate("告警（真实违规）" if real else "误报", (f + 0.1, y + 0.25), textcoords="offset points",
                        xytext=(0, 3), ha="center", fontsize=8, color=INK)
    ax.axvspan(8.8, 13.2, ymin=0, ymax=1, color="#f6f5f2", zorder=-1)
    ax.text(11.0, 2.55, "真实违规（4.4 秒，含 2 帧漏判）", ha="center", fontsize=8, color=MUTED)
    ax.text(3.6, 2.55, "零星误检（约每秒 1 帧）", ha="center", fontsize=8, color=MUTED)
    ax.text(4.5, -0.5, "浅色带：违规状态正在计时（连续 1.5 秒无命中才清零）；竖线：发出告警", ha="center",
            fontsize=7.5, color=MUTED)
    ax.set_yticks([2.0, 1.0, 0.0], [r[1] for r in rows])
    ax.set_ylim(-0.6, 2.85)
    ax.set_xlim(0, n / fps)
    ax.set_xlabel(f"时间（秒）　参数：T = {T:g} 秒，ρ = {rho:g}，中断清零 {gap:g} 秒，{fps} fps")
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    fig.tight_layout()
    fig.savefig(FIG / "fig_confirmation.png")
    plt.close(fig)


if __name__ == "__main__":
    architecture()
    confirmation()
    print("ok")
