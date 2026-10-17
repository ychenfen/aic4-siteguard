"""轻量 IoU 跟踪器：给人员分配稳定 ID，用于时序确认和去重。"""
from __future__ import annotations

from dataclasses import dataclass

from .geometry import iou
from .models import BBox, Worker


@dataclass
class _Track:
    track_id: int
    bbox: BBox
    misses: int = 0


class IouTracker:
    def __init__(self, iou_threshold: float = 0.3, max_misses: int = 5):
        self.iou_threshold = iou_threshold
        self.max_misses = max_misses
        self._tracks: list[_Track] = []
        self._next_id = 1

    def update(self, workers: list[Worker]) -> list[Worker]:
        unmatched = list(self._tracks)
        for w in workers:
            best, best_iou = None, self.iou_threshold
            for t in unmatched:
                s = iou(w.bbox, t.bbox)
                if s > best_iou:
                    best, best_iou = t, s
            if best is not None:
                unmatched.remove(best)
                best.bbox, best.misses = w.bbox, 0
                w.track_id = best.track_id
            else:
                t = _Track(self._next_id, w.bbox)
                self._next_id += 1
                self._tracks.append(t)
                w.track_id = t.track_id
        for t in unmatched:
            t.misses += 1
        self._tracks = [t for t in self._tracks if t.misses <= self.max_misses]
        return workers
