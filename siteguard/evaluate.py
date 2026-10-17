"""告警策略评估：在仿真场景上运行不同策略，与真值事件匹配并计算指标。

策略：
- frame   逐帧报警：每帧只要判定违规就报警（无确认、无去重、无复合升级）
- dedup   逐帧 + 固定冷却去重：无确认；同一人同一规则在冷却期内只报一次（常见商用做法）
- dur     仅时长确认 + 片段去重（去掉命中占比条件，消融）
- ours_cd 双条件确认 + 固定冷却去重（把片段去重换回固定冷却，消融）
- ours    本文方法：双条件时序确认 + 片段级去重 + 复合风险升级
- ours_nc 本文方法去掉复合风险升级（仅用于参数扫描）

指标：
- recall           真值事件中至少被报警一次的比例
- fa_per_hour      无法匹配任何真值事件（含瞬时违规）的报警数 / 小时
- precision        匹配到真值事件的报警 / 全部非中性报警
- alarms_per_event 每个被检出事件平均收到的报警条数（越接近 1 越不刷屏）
- latency          事件开始到首条报警的平均时延（秒）
"""
from __future__ import annotations

import copy
import statistics
from dataclasses import dataclass

from .engine import HazardEngine, load_config
from .geometry import iou
from .models import Hazard
from .sim import GTEvent, Scenario, gt_compound

RULE_KIND = {"R01": "no_helmet", "R02": "no_vest", "R03": "crane", "R04": "pit", "R05": "fire"}
KINDS = ["no_helmet", "no_vest", "crane", "pit", "fire"]
BASELINE_COOLDOWN = {"R01": 60, "R02": 120, "R03": 30, "R04": 60, "R05": 60}
MATCH_TOL = 2.0  # 报警可在事件结束后 2 秒内到达
PRE_TOL = 1.0    # 框抖动使脚底点提前越过区域边界，允许报警比真值早 1 秒


def strategy_config(name: str, base: dict | None = None, confirm_scale: float | None = None,
                    confirm_override: float | None = None) -> dict:
    cfg = copy.deepcopy(base or load_config())
    if name in ("frame", "dedup", "dur"):
        cfg["confirm_ratio"] = 0.0
    if name in ("frame", "dedup", "ours_cd"):
        cfg["dedup"] = {"mode": "cooldown"}
    for r in cfg["rules"]:
        r["cooldown_seconds"] = 0.0 if name == "frame" else BASELINE_COOLDOWN[r["rule_id"]]
        if name in ("frame", "dedup"):
            r["confirm_seconds"] = 0.0
        if confirm_scale is not None:
            r["confirm_seconds"] *= confirm_scale
        if confirm_override is not None:
            r["confirm_seconds"] = confirm_override
    if name in ("frame", "dedup", "dur", "ours_cd", "ours_nc"):
        cfg["compound"] = []
    return cfg


def run_strategy(sc: Scenario, cfg: dict) -> list[Hazard]:
    eng = HazardEngine(sc.zones, config=cfg)
    out: list[Hazard] = []
    for f in sc.frames:
        out += eng.process(f)[1]
    return out


def _gt_worker(sc: Scenario, h: Hazard) -> int | None:
    if h.bbox is None:
        return None
    i = min(len(sc.gt_boxes) - 1, round(h.ts * sc.fps))
    best, bi = None, 0.3
    for w, b in sc.gt_boxes[i].items():
        s = iou(h.bbox, b)
        if s > bi:
            best, bi = w, s
    return best


def _find(events: list[GTEvent], kind: str, worker, ts: float) -> GTEvent | None:
    for e in events:
        if e.kind == kind and (kind == "fire" or e.worker == worker) and e.start - PRE_TOL <= ts <= e.end + MATCH_TOL:
            return e
    return None


@dataclass
class Result:
    recall: float
    fa_per_hour: float
    precision: float
    alarms_per_event: float
    latency: float
    n_alarms: int
    n_events: int
    per_kind: dict
    compound_recall: float
    major_false: int
    n_compound: int


def score(sc: Scenario, alarms: list[Hazard]) -> Result:
    hours = sc.duration / 3600
    matched: dict[int, list[float]] = {}  # id(event) -> alarm ts list
    fa_by_kind = {k: 0 for k in KINDS}
    neutral = 0
    for h in alarms:
        kind = RULE_KIND[h.rule_id]
        w = _gt_worker(sc, h) if kind != "fire" else None
        e = _find(sc.gt_events, kind, w, h.ts)
        if e is not None:
            matched.setdefault(id(e), []).append(h.ts)
        elif _find(sc.gt_short, kind, w, h.ts) is not None:
            neutral += 1
        else:
            fa_by_kind[kind] += 1

    per_kind = {}
    for k in KINDS:
        evs = [e for e in sc.gt_events if e.kind == k]
        hit = [e for e in evs if id(e) in matched]
        per_kind[k] = {
            "events": len(evs),
            "recall": len(hit) / len(evs) if evs else float("nan"),
            "fa_per_hour": fa_by_kind[k] / hours,
        }
    hit_events = [e for e in sc.gt_events if id(e) in matched]
    n_matched_alarms = sum(len(v) for v in matched.values())
    n_fa = sum(fa_by_kind.values())
    lat = [max(0.0, min(matched[id(e)]) - e.start) for e in hit_events]

    comp = gt_compound(sc)
    majors = [h for h in alarms if h.level == "重大"]
    comp_hit = 0
    used = set()
    for c in comp:
        for h in majors:
            if h.rule_id == "R03" and _gt_worker(sc, h) == c.worker and c.start - MATCH_TOL <= h.ts <= c.end + MATCH_TOL:
                comp_hit += 1
                used.add(id(h))
                break
    major_false = sum(
        1 for h in majors if id(h) not in used and not any(
            _gt_worker(sc, h) == c.worker and c.start - MATCH_TOL <= h.ts <= c.end + MATCH_TOL for c in comp)
    )
    return Result(
        recall=len(hit_events) / len(sc.gt_events) if sc.gt_events else float("nan"),
        fa_per_hour=n_fa / hours,
        precision=n_matched_alarms / (n_matched_alarms + n_fa) if (n_matched_alarms + n_fa) else float("nan"),
        alarms_per_event=n_matched_alarms / len(hit_events) if hit_events else float("nan"),
        latency=statistics.fmean(lat) if lat else float("nan"),
        n_alarms=len(alarms),
        n_events=len(sc.gt_events),
        per_kind=per_kind,
        compound_recall=comp_hit / len(comp) if comp else float("nan"),
        major_false=major_false,
        n_compound=len(comp),
    )
