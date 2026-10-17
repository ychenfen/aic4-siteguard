"""把检测框关联成「人员 + 佩戴状态」。

检测模型通常输出独立的 person / helmet / head / vest 框，
需要按空间关系把装备框归到对应的人身上：
- helmet 框落在人体头部区域 → 戴了安全帽
- head（裸头）框落在头部区域 → 没戴安全帽
- vest 框落在躯干区域 → 穿了反光衣
人体框太小（远景）时不做判断，避免误报。
"""
from __future__ import annotations

from .geometry import containment, head_region, torso_region
from .models import Detection, Worker

MIN_PERSON_HEIGHT = 48  # 像素，低于此高度不判断佩戴
MATCH_THRESHOLD = 0.5


def associate(detections: list[Detection], min_conf: float = 0.35) -> list[Worker]:
    persons = [d for d in detections if d.label == "person" and d.conf >= min_conf]
    helmets = [d for d in detections if d.label == "helmet" and d.conf >= min_conf]
    heads = [d for d in detections if d.label == "head" and d.conf >= min_conf]
    vests = [d for d in detections if d.label == "vest" and d.conf >= min_conf]

    used: set[int] = set()
    workers: list[Worker] = []
    # 置信度高的人优先认领装备框，避免两人抢同一顶帽子
    for p in sorted(persons, key=lambda d: -d.conf):
        w = Worker(bbox=p.bbox, conf=p.conf)
        height = p.bbox[3] - p.bbox[1]
        if height >= MIN_PERSON_HEIGHT:
            hr = head_region(p.bbox)
            tr = torso_region(p.bbox)
            h = _best(helmets, hr, used)
            if h is not None:
                w.helmet = True
                used.add(id(h))
            elif (b := _best(heads, hr, used)) is not None:
                w.helmet = False
                used.add(id(b))
            v = _best(vests, tr, used)
            if v is not None:
                w.vest = True
                used.add(id(v))
            else:
                w.vest = False
        workers.append(w)
    return workers


def _best(cands: list[Detection], region, used: set[int]):
    best, best_score = None, MATCH_THRESHOLD
    for c in cands:
        if id(c) in used:
            continue
        s = containment(c.bbox, region)
        if s > best_score:
            best, best_score = c, s
    return best
