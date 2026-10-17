"""隐患规则引擎：逐帧判定 → 时序确认 → 去重 → 风险分级与复合升级。

设计要点：
1. 双条件时序确认：违规状态持续不少于 confirm_seconds，且这段时间内命中帧占比不低于
   confirm_ratio，才确认为隐患。只看持续时长会被「零星误检串成一段」骗过，只看占比
   又会被单帧误检触发，两者结合才能稳定过滤检测噪声；
2. 片段级去重：一段连续违规只报一次（违规持续则每 repeat_seconds 提醒一次），
   同一对象同一规则的新违规片段与上次告警至少间隔 rearm_seconds。相比固定冷却期，
   不会把同一人短时间内的第二次违规吞掉；也可切换为传统固定冷却（dedup.mode = "cooldown"）；
3. 复合风险升级：同一人同时有多条规则处于已确认状态（如未戴安全帽 + 位于吊装区）时，
   叠加风险分并单独发出升级告警；若条件成立时主规则恰好首次确认，则只发升级告警；
4. 规则数据化：规则、规范依据、整改措施写在 rules.json，可按项目增删。
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
GAP_RESET_SECONDS = 1.5  # 连续这么久没有命中，则违规状态清零


def load_config(path: Path | str = DEFAULT_RULES) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class _State:
    start: float
    last: float
    start_frame: int
    hits: int = 1
    bbox: Optional[tuple] = None
    zone_id: Optional[str] = None
    emitted: bool = False
    escalated: set = None  # 已发过升级告警的复合规则序号


class HazardEngine:
    def __init__(self, zones: list[Zone] | None = None, rules_path: Path | str = DEFAULT_RULES,
                 config: dict | None = None):
        cfg = config if config is not None else load_config(rules_path)
        self.rules = {r["rule_id"]: r for r in cfg["rules"]}
        self.levels = sorted(cfg["levels"], key=lambda l: -l["min_score"])
        self.compound = cfg.get("compound", [])
        self.default_ratio = cfg.get("confirm_ratio", 0.0)
        d = cfg.get("dedup", {})
        self.dedup_mode = d.get("mode", "cooldown")
        self.rearm = d.get("rearm_seconds", 10.0)
        self.repeat = d.get("repeat_seconds", 300.0)
        self.zones = zones or []
        self.tracker = IouTracker()
        self._active: dict[tuple[str, object], _State] = {}
        self._last_emit: dict[tuple, float] = {}
        self._seq = 0
        self._frame = -1

    # ---------- 公共接口 ----------
    def process(self, frame: Frame) -> tuple[list[Worker], list[Hazard]]:
        self._frame += 1
        workers = self.tracker.update(associate(frame.detections))
        hits = self._evaluate(frame, workers)
        self._update_states(frame.ts, hits)
        hazards = self._emit(frame, hits)
        return workers, hazards

    def level_of(self, score: float) -> dict:
        for lv in self.levels:
            if score >= lv["min_score"]:
                return lv
        return self.levels[-1]

    def is_confirmed(self, key: tuple[str, object], now: float) -> bool:
        st = self._active.get(key)
        if st is None:
            return False
        r = self.rules[key[0]]
        if now - st.start < r["confirm_seconds"]:
            return False
        ratio = r.get("confirm_ratio", self.default_ratio)
        return st.hits / (self._frame - st.start_frame + 1) >= ratio

    # ---------- 单帧判定 ----------
    def _evaluate(self, frame: Frame, workers: list[Worker]):
        """返回本帧命中的 {(rule_id, subject): (bbox, zone_id)}。"""
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

    # ---------- 状态更新 ----------
    def _update_states(self, now: float, hits) -> None:
        for key, (bbox, zone_id) in hits.items():
            st = self._active.get(key)
            if st is None or now - st.last > GAP_RESET_SECONDS:
                self._active[key] = _State(now, now, self._frame, 1, bbox, zone_id)
            else:
                st.last, st.bbox, st.zone_id = now, bbox, zone_id
                st.hits += 1
        for key in [k for k, s in self._active.items() if now - s.last > GAP_RESET_SECONDS]:
            del self._active[key]

    # ---------- 告警生成 ----------
    def _cooled(self, key: tuple, now: float, cooldown: float) -> bool:
        last = self._last_emit.get(key)
        return last is None or now - last >= cooldown

    def _make(self, frame: Frame, rid: str, subject, title: str, score: float) -> Hazard:
        r, st = self.rules[rid], self._active[(rid, subject)]
        self._seq += 1
        return Hazard(
            hazard_id=f"{frame.camera_id}-{self._seq:04d}",
            rule_id=rid, title=title, camera_id=frame.camera_id, ts=frame.ts,
            track_id=subject if isinstance(subject, int) else None,
            bbox=st.bbox, level=self.level_of(score)["name"], score=score,
            standard=r["standard"], measure=r["measure"], zone_id=st.zone_id,
        )

    def _should_emit(self, key: tuple, st: _State, now: float, cooldown: float) -> bool:
        if self.dedup_mode == "cooldown":
            return self._cooled(key, now, cooldown)
        if not st.emitted:
            return self._cooled(key, now, self.rearm)
        return self._cooled(key, now, self.repeat)  # 同一片段持续违规：定时提醒

    def _emit(self, frame: Frame, hits) -> list[Hazard]:
        now = frame.ts
        out: list[Hazard] = []
        # 1) 复合风险升级
        for ci, c in enumerate(self.compound):
            lead = max(c["when"], key=lambda x: self.rules[x]["severity"])
            for (rid, subject) in hits:
                if rid != lead:
                    continue
                if not all(self.is_confirmed((o, subject), now) for o in c["when"]):
                    continue
                st = self._active[(lead, subject)]
                ckey = ("C", ci, subject)
                if self.dedup_mode == "cooldown":
                    if not self._cooled(ckey, now, self.rules[lead].get("cooldown_seconds", 0)):
                        continue
                else:
                    st.escalated = st.escalated or set()
                    if ci in st.escalated or not self._cooled(ckey, now, self.rearm):
                        continue
                    st.escalated.add(ci)
                self._last_emit[ckey] = now
                if not st.emitted:  # 主规则尚未报过，只发升级告警
                    st.emitted = True
                    self._last_emit[(lead, subject)] = now
                out.append(self._make(frame, lead, subject, c["title"],
                                      float(self.rules[lead]["severity"]) + c["bonus"]))
        # 2) 单条规则
        for key in hits:
            rid, subject = key
            st = self._active[key]
            if not self.is_confirmed(key, now):
                continue
            if not self._should_emit(key, st, now, self.rules[rid].get("cooldown_seconds", 0)):
                continue
            st.emitted = True
            self._last_emit[key] = now
            out.append(self._make(frame, rid, subject, self.rules[rid]["title"],
                                  float(self.rules[rid]["severity"])))
        return out
