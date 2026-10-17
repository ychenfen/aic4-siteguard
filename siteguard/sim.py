"""带真值的工地场景仿真器 + 检测器误差模型，用于定量评估告警策略。

为什么要仿真：真实工地视频难以获得逐帧真值（谁在哪一秒摘了安全帽、何时进入警戒区），
而告警策略的好坏恰恰取决于这些时间信息。仿真器先生成「真实世界」（人员轨迹、佩戴状态、
危险区进出、烟火），再按可调的误差模型生成「检测器输出」（漏检、类别翻转、遮挡突发、
装备框漏检/误检、框抖动、烟火误报），从而可以在同一组输入上比较不同告警策略，
并扫描检测器质量对系统表现的影响。

所有随机性由 seed 控制，实验可完全复现。
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from .geometry import point_in_polygon
from .models import Detection, Frame, Zone

W, H = 1280, 720

DEFAULT_ZONES = [
    Zone("Z1", "1#塔吊回转半径", "crane", [(700, 260), (1080, 260), (1180, 520), (620, 520)]),
    Zone("Z2", "东侧基坑临边", "pit", [(60, 300), (380, 300), (420, 470), (40, 470)]),
]


@dataclass
class NoiseModel:
    """检测器误差模型（均为逐帧概率）。"""

    p_person_miss: float = 0.05   # 人体漏检
    p_flip: float = 0.05          # 安全帽/裸头 类别翻转（独立误差）
    p_burst: float = 0.01         # 每帧进入一次「遮挡突发」的概率，突发期间头部判断持续出错
    burst_mean_frames: float = 4  # 突发平均持续帧数
    p_head_miss: float = 0.08     # 头部框（帽/裸头）漏检 → 该帧无法判断
    p_vest_miss: float = 0.06     # 穿了背心但背心框漏检 → 被判为未穿
    p_vest_fp: float = 0.03       # 没穿背心却检出背心
    p_smoke_fp: float = 0.002     # 无烟火时出现烟雾误报
    jitter: float = 4.0           # 框抖动（像素标准差）

    def scaled(self, k: float) -> "NoiseModel":
        """按比例整体放大/缩小误差强度（用于鲁棒性实验）。"""
        return NoiseModel(
            p_person_miss=min(0.9, self.p_person_miss * k),
            p_flip=min(0.9, self.p_flip * k),
            p_burst=min(0.9, self.p_burst * k),
            burst_mean_frames=self.burst_mean_frames,
            p_head_miss=min(0.9, self.p_head_miss * k),
            p_vest_miss=min(0.9, self.p_vest_miss * k),
            p_vest_fp=min(0.9, self.p_vest_fp * k),
            p_smoke_fp=min(0.9, self.p_smoke_fp * k),
            jitter=self.jitter * max(1.0, k),
        )


@dataclass
class GTEvent:
    """真值隐患事件。kind ∈ no_helmet / no_vest / crane / pit / fire。"""

    kind: str
    worker: int | None
    start: float
    end: float
    zone_id: str | None = None

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Scenario:
    fps: int
    duration: float
    zones: list[Zone]
    frames: list[Frame]
    gt_boxes: list[dict[int, tuple]]           # 每帧：worker -> 真实人体框
    gt_events: list[GTEvent] = field(default_factory=list)
    gt_helmet: list[dict[int, bool]] = field(default_factory=list)
    gt_short: list[GTEvent] = field(default_factory=list)  # 短于 min_event 的瞬时违规，评估时视为中性


def _episodes(rng: random.Random, duration: float, rate_per_min: float,
              dmin: float, dmax: float) -> list[tuple[float, float]]:
    """泊松到达的若干不重叠区间。"""
    out, t = [], 0.0
    while True:
        t += rng.expovariate(rate_per_min / 60.0)
        if t >= duration:
            break
        d = rng.uniform(dmin, dmax)
        out.append((t, min(duration, t + d)))
        t += d
    return out


def _in(intervals, t) -> bool:
    return any(a <= t < b for a, b in intervals)


def _random_point(rng, zone: Zone | None, zones: list[Zone]):
    if zone is not None:
        xs = [p[0] for p in zone.polygon]
        ys = [p[1] for p in zone.polygon]
        for _ in range(200):
            p = (rng.uniform(min(xs), max(xs)), rng.uniform(min(ys), max(ys)))
            if point_in_polygon(p, zone.polygon):
                return p
    for _ in range(200):
        p = (rng.uniform(60, W - 60), rng.uniform(300, H - 20))
        if not any(point_in_polygon(p, z.polygon) for z in zones):
            return p
    return (W / 2, H - 40)


def _trajectory(rng, duration, zones, p_zone=0.22):
    """路径点序列：在若干位置停留，按一定概率走进危险区并停留。"""
    pts = []  # (t, x, y)
    t = 0.0
    x, y = _random_point(rng, None, zones)
    pts.append((t, x, y))
    while t < duration:
        target_zone = rng.choice(zones) if rng.random() < p_zone else None
        nx, ny = _random_point(rng, target_zone, zones)
        dist = math.hypot(nx - x, ny - y)
        t += max(1.0, dist / rng.uniform(60, 110))  # 行走 60~110 px/s
        pts.append((t, nx, ny))
        t += rng.uniform(2, 14) if target_zone is None else rng.uniform(3, 18)  # 停留
        pts.append((t, nx, ny))
        x, y = nx, ny
    return pts


def _pos(pts, t):
    for (t0, x0, y0), (t1, x1, y1) in zip(pts, pts[1:]):
        if t0 <= t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
    return pts[-1][1], pts[-1][2]


def _box(fx, fy):
    h = 150 * (0.6 + 0.6 * fy / H)
    w = h * 0.38
    return (fx - w / 2, fy - h, fx + w / 2, fy)


def generate(seed: int = 0, duration: float = 600.0, fps: int = 5, n_workers: int = 6,
             noise: NoiseModel | None = None, zones: list[Zone] | None = None,
             min_event: float = 3.0) -> Scenario:
    rng = random.Random(seed)
    noise = noise or NoiseModel()
    zones = zones or DEFAULT_ZONES

    workers = []
    for _ in range(n_workers):
        workers.append({
            "traj": _trajectory(rng, duration, zones),
            "no_helmet": _episodes(rng, duration, 0.35, 4, 40),
            "no_vest": _episodes(rng, duration, 0.25, 6, 60),
        })
    fire = _episodes(rng, duration, 0.08, 6, 25)

    frames, gt_boxes, gt_helmet = [], [], []
    in_zone_runs: dict[tuple[int, str], list[list[float]]] = {}
    burst_left = [0] * n_workers
    n = int(duration * fps)
    for i in range(n + 1):
        t = i / fps
        dets: list[Detection] = []
        boxes, helm = {}, {}
        for wi, wk in enumerate(workers):
            fx, fy = _pos(wk["traj"], t)
            box = _box(fx, fy)
            boxes[wi] = box
            helmet = not _in(wk["no_helmet"], t)
            vest = not _in(wk["no_vest"], t)
            helm[wi] = helmet
            for z in zones:
                key = (wi, z.zone_id)
                runs = in_zone_runs.setdefault(key, [])
                if point_in_polygon((fx, fy), z.polygon):
                    if runs and abs(runs[-1][1] - (t - 1 / fps)) < 1e-6:
                        runs[-1][1] = t
                    else:
                        runs.append([t, t])
            # ---- 检测器输出 ----
            if rng.random() < noise.p_person_miss:
                continue
            j = noise.jitter
            jb = tuple(v + rng.gauss(0, j) for v in box)
            dets.append(Detection("person", rng.uniform(0.6, 0.95), jb))
            x1, y1, x2, y2 = jb
            bw, bh = x2 - x1, y2 - y1
            cx = (x1 + x2) / 2
            if burst_left[wi] > 0:
                burst_left[wi] -= 1
            elif rng.random() < noise.p_burst:
                burst_left[wi] = max(1, int(rng.expovariate(1 / noise.burst_mean_frames)))
            if rng.random() >= noise.p_head_miss:
                seen = helmet
                if burst_left[wi] > 0 or rng.random() < noise.p_flip:
                    seen = not helmet
                dets.append(Detection("helmet" if seen else "head", rng.uniform(0.5, 0.9),
                                      (cx - bw * 0.25, y1 + bh * 0.01, cx + bw * 0.25, y1 + bh * 0.16)))
            has_vest_box = (vest and rng.random() >= noise.p_vest_miss) or \
                           (not vest and rng.random() < noise.p_vest_fp)
            if has_vest_box:
                dets.append(Detection("vest", rng.uniform(0.5, 0.9),
                                      (x1 + bw * 0.1, y1 + bh * 0.25, x2 - bw * 0.1, y1 + bh * 0.6)))
        if _in(fire, t) or rng.random() < noise.p_smoke_fp:
            dets.append(Detection("smoke", rng.uniform(0.45, 0.8), (980, 120, 1120, 230)))
        frames.append(Frame("SIM", t, W, H, dets))
        gt_boxes.append(boxes)
        gt_helmet.append(helm)

    events: list[GTEvent] = []
    for wi, wk in enumerate(workers):
        for a, b in wk["no_helmet"]:
            events.append(GTEvent("no_helmet", wi, a, b))
        for a, b in wk["no_vest"]:
            events.append(GTEvent("no_vest", wi, a, b))
    zkind = {z.zone_id: z.kind for z in zones}
    for (wi, zid), runs in in_zone_runs.items():
        for a, b in runs:
            events.append(GTEvent(zkind[zid], wi, a, b + 1 / fps, zid))
    for a, b in fire:
        events.append(GTEvent("fire", None, a, b))
    short = [e for e in events if e.duration < min_event]
    events = [e for e in events if e.duration >= min_event]
    return Scenario(fps, duration, zones, frames, gt_boxes, events, gt_helmet, short)


def gt_compound(sc: Scenario, min_overlap: float = 1.0) -> list[GTEvent]:
    """真值复合风险：同一人在未戴安全帽的同时处于塔吊/吊装区，重叠 ≥ min_overlap 秒。"""
    out = []
    by_w: dict[int, list[GTEvent]] = {}
    for e in sc.gt_events + sc.gt_short:  # 进入塔吊区哪怕不足 3 秒，与未戴帽重叠也算复合风险
        if e.worker is not None:
            by_w.setdefault(e.worker, []).append(e)
    for w, evs in by_w.items():
        for h in (e for e in evs if e.kind == "no_helmet" and e.duration >= 3.0):
            for z in (e for e in evs if e.kind == "crane"):
                a, b = max(h.start, z.start), min(h.end, z.end)
                if b - a >= min_overlap:
                    out.append(GTEvent("compound", w, a, b, z.zone_id))
    return out
