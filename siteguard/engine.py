"""隐患规则引擎：逐帧判定 → 时序确认 → 风险分级。

设计要点（也是方案里的创新点）：
1. 时序确认：违规需持续 confirm_seconds 才报警，过滤单帧误检；
2. 冷却去重：同一人同一规则在 cooldown_seconds 内只报一次，避免刷屏；
3. 复合风险：同一人同时触发多条规则（如未戴安全帽 + 进入吊装区）时叠加分值、升级等级；
4. 规则数据化：规则与规范依据写在 rules.json，项目可自行增删。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .association import associate
from .geometry import point_in_polygon
from .models import Frame, Hazard, Worker, Zone
from .tracker import IouTracker

DEFAULT_RULES = Path(__file__).with_name("rules.json")
GAP_RESET_SECONDS = 1.5  # 违规中断超过该时长则重新计时


@dataclass
class _State:
    start: float
    last: float
    bbox: Optional[tuple] = None
    zone_id: Optional[str] = None


class HazardEngine:
    def __init__(self, zones: list[Zone] | None = None, rules_path: Path | str = DEFAULT_RULES):
        cfg = json.loads(Path(rules_path).read_text(encoding="utf-8"))
        self.rules = {r["rule_id"]: r for r in cfg["rules"]}
        self.levels = sorted(cfg["levels"], key=lambda l: -l["min_score"])
        self.compound = cfg.get("compound", [])
        self.zones = zones or []
        self.tracker = IouTracker()
        self._active: dict[tuple[str, object], _State] = {}
        self._last_emit: dict[tuple[str, object], float] = {}
        self._seq = 0

    # ---------- 公共接口 ----------
    def process(self, frame: Frame) -> tuple[list[Worker], list[Hazard]]:
        workers = self.tracker.update(associate(frame.detections))
        hits = self._evaluate(frame, workers)
        hazards = self._confirm(frame, hits)
        return workers, hazards

    def level_of(self, score: float) -> dict:
        for lv in self.levels:
            if score >= lv["min_score"]:
                return lv
        return self.levels[-1]

    # ---------- 单帧判定 ----------
    def _evaluate(self, frame: Frame, workers: list[Worker]):
        """返回本帧命中的 {(rule_id, key): (bbox, zone_id)}。"""
        hits: dict[tuple[str, object], tuple] = {}
        for rid, r in self.rules.items():
            t = r["type"]
            if t == "no_helmet":
                for w in workers:
                    if w.helmet is False:
                        hits[(rid, w.track_id)] = (w.bbox, None)
            elif t == "no_vest":
                for w in workers:
                    if w.vest is False:
                        hits[(rid, w.track_id)] = (w.bbox, None)
            elif t == "zone_intrusion":
                kinds = set(r.get("zone_kinds", []))
                for z in self.zones:
                    if not z.active or z.kind not in kinds:
                        continue
                    for w in workers:
                        if point_in_polygon(w.foot_point, z.polygon):
                            hits[(rid, w.track_id)] = (w.bbox, z.zone_id)
            elif t == "fire_smoke":
                for d in frame.detections:
                    if d.label in ("fire", "smoke") and d.conf >= 0.4:
                        hits[(rid, "fire")] = (d.bbox, None)
                        break
        return hits

    # ---------- 时序确认 + 分级 ----------
    def _confirm(self, frame: Frame, hits) -> list[Hazard]:
        now = frame.ts
        for key, (bbox, zone_id) in hits.items():
            st = self._active.get(key)
            if st is None or now - st.last > GAP_RESET_SECONDS:
                self._active[key] = _State(start=now, last=now, bbox=bbox, zone_id=zone_id)
            else:
                st.last, st.bbox, st.zone_id = now, bbox, zone_id
        # 清理已中断的状态
        for key in [k for k, s in self._active.items() if now - s.last > GAP_RESET_SECONDS]:
            del self._active[key]

        out: list[Hazard] = []
        for key in hits:
            rid, subject = key
            r = self.rules[rid]
            st = self._active[key]
            if now - st.start < r["confirm_seconds"]:
                continue
            last = self._last_emit.get(key)
            if last is not None and now - last < r["cooldown_seconds"]:
                continue
            title, bonus = r["title"], 0.0
            for c in self.compound:
                # 复合风险只挂在组内最严重的那条规则上，避免重复升级
                lead = max(c["when"], key=lambda x: self.rules[x]["severity"])
                if rid == lead and all(
                    (other, subject) in self._active for other in c["when"] if other != rid
                ):
                    title, bonus = c["title"], c["bonus"]
            score = float(r["severity"]) + bonus
            self._seq += 1
            self._last_emit[key] = now
            out.append(
                Hazard(
                    hazard_id=f"{frame.camera_id}-{self._seq:04d}",
                    rule_id=rid,
                    title=title,
                    camera_id=frame.camera_id,
                    ts=now,
                    track_id=subject if isinstance(subject, int) else None,
                    bbox=st.bbox,
                    level=self.level_of(score)["name"],
                    score=score,
                    standard=r["standard"],
                    measure=r["measure"],
                    zone_id=st.zone_id,
                )
            )
        return out
