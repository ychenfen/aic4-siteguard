from datetime import datetime
from pathlib import Path

import pytest

from siteguard.association import associate
from siteguard.detectors import ReplayDetector
from siteguard.engine import HazardEngine
from siteguard.geometry import iou, point_in_polygon
from siteguard.models import Detection, Frame, Zone
from siteguard.tickets import TicketBook

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "site_demo.json"
CRANE = Zone("Z1", "塔吊", "crane", [(500, 0), (1000, 0), (1000, 720), (500, 720)])


def person(x, helmet=True, vest=True, y=600, h=200):
    w = h * 0.4
    dets = [Detection("person", 0.9, (x, y - h, x + w, y))]
    dets.append(Detection("helmet" if helmet else "head", 0.8, (x + w * 0.25, y - h, x + w * 0.75, y - h * 0.85)))
    if vest:
        dets.append(Detection("vest", 0.8, (x + 5, y - h * 0.75, x + w - 5, y - h * 0.4)))
    return dets


def frames(dets_fn, seconds, fps=5):
    return [Frame("cam", i / fps, 1280, 720, dets_fn(i / fps)) for i in range(int(seconds * fps) + 1)]


def run(engine, fs):
    out = []
    for f in fs:
        out += engine.process(f)[1]
    return out


def test_geometry():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert point_in_polygon((5, 5), sq) and not point_in_polygon((15, 5), sq)


def test_association_states():
    ws = associate(person(100) + person(400, helmet=False, vest=False))
    by_x = sorted(ws, key=lambda w: w.bbox[0])
    assert (by_x[0].helmet, by_x[0].vest) == (True, True)
    assert (by_x[1].helmet, by_x[1].vest) == (False, False)


def test_small_person_not_judged():
    ws = associate(person(100, helmet=False, h=30))
    assert ws[0].helmet is None


def test_single_frame_false_positive_filtered():
    eng = HazardEngine()
    fs = frames(lambda t: person(100, helmet=not (0.9 < t < 1.1)), 5)
    assert run(eng, fs) == []


def test_persistent_violation_reported_once_with_cooldown():
    eng = HazardEngine()
    hz = run(eng, frames(lambda t: person(100, helmet=False), 20))
    assert [h.rule_id for h in hz] == ["R01"]
    assert hz[0].ts == pytest.approx(2.0)


def test_compound_risk_escalates_to_major():
    eng = HazardEngine(zones=[CRANE])
    hz = run(eng, frames(lambda t: person(600, helmet=False), 5))
    # 吊装区规则 1 秒先确认（较大）；安全帽规则 2 秒确认后，再发一条复合升级告警（重大）
    seq = [(h.rule_id, h.level) for h in hz]
    assert seq == [("R03", "较大"), ("R03", "重大"), ("R01", "较大")]
    up = hz[1]
    assert "复合" in up.title and up.score == 9.0
    assert sum("复合" in h.title for h in hz) == 1


def test_compound_when_already_confirmed_sends_only_escalation():
    eng = HazardEngine(zones=[CRANE])
    # 先在区外未戴帽 3 秒（安全帽规则已确认），再走进吊装区
    walk = lambda t: person(min(600, 100 + max(0.0, t - 3) * 125), helmet=False)
    hz = run(eng, frames(walk, 10))
    crane = [h for h in hz if h.rule_id == "R03"]
    assert len(crane) == 1 and crane[0].level == "重大"


def test_sparse_flips_do_not_chain_into_alarm():
    """每隔 1 秒误检一帧：只看持续时长会被串成一段，加上命中占比后不报警。"""
    eng = HazardEngine()
    fs = frames(lambda t: person(100, helmet=abs(t - round(t)) > 0.01), 10)
    assert run(eng, fs) == []


def test_zone_with_helmet_is_not_compound():
    eng = HazardEngine(zones=[CRANE])
    hz = run(eng, frames(lambda t: person(600), 5))
    assert [h.rule_id for h in hz] == ["R03"] and hz[0].level == "较大"


def test_ticket_lifecycle():
    eng = HazardEngine(zones=[CRANE])
    book = TicketBook(eng.levels, base_time=datetime(2026, 10, 17, 9))
    for h in run(eng, frames(lambda t: person(600, helmet=False), 5)):
        book.issue(h)
    t = next(t for t in book.tickets if t.hazard.level == "重大")
    assert t.deadline == t.issued_at  # 重大隐患立即整改
    t.advance("已停工"); t.advance("已整改")
    t.reject("帽带未系")
    assert t.status == "整改中"
    t.advance(); t.advance("复查通过")
    assert t.status == "已闭环"
    with pytest.raises(ValueError):
        t.advance()
    assert "整改通知单" in t.to_markdown()


def test_sample_scenario():
    det = ReplayDetector(SAMPLE)
    zones = [Zone(z["zone_id"], z["name"], z["kind"], [tuple(p) for p in z["polygon"]]) for z in det.zones]
    eng = HazardEngine(zones)
    hz = run(eng, det.frames())
    rules = {h.rule_id for h in hz}
    assert rules == {"R01", "R02", "R03", "R04", "R05"}
    assert sum(h.level == "重大" for h in hz) == 1


def test_second_episode_within_old_cooldown_is_reported():
    """摘帽 5 秒→戴上 15 秒→再摘帽：片段去重会报两次，固定 60 秒冷却会吞掉第二次。"""
    off = lambda t: person(100, helmet=not (t < 5 or 20 <= t < 25))
    assert [h.rule_id for h in run(HazardEngine(), frames(off, 30))] == ["R01", "R01"]
    from siteguard.evaluate import strategy_config
    cd = HazardEngine(config=strategy_config("ours_cd"))
    assert [h.rule_id for h in run(cd, frames(off, 30))] == ["R01"]


def test_simulation_is_reproducible():
    from siteguard.sim import generate
    a, b = generate(seed=3, duration=60), generate(seed=3, duration=60)
    assert [(e.kind, e.worker, e.start) for e in a.gt_events] == [(e.kind, e.worker, e.start) for e in b.gt_events]
    assert a.frames[100].detections == b.frames[100].detections
