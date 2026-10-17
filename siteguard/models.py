"""核心数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

BBox = tuple[float, float, float, float]  # x1, y1, x2, y2（像素）


@dataclass(frozen=True)
class Detection:
    """检测器输出的一个目标框。"""

    label: str  # person / helmet / head / vest / fire / smoke ...
    conf: float
    bbox: BBox


@dataclass
class Worker:
    """关联后的人员：一个人体框 + 其佩戴状态。"""

    bbox: BBox
    conf: float
    helmet: Optional[bool] = None  # None = 无法判断（遮挡/过小）
    vest: Optional[bool] = None
    track_id: Optional[int] = None

    @property
    def foot_point(self) -> tuple[float, float]:
        x1, _, x2, y2 = self.bbox
        return ((x1 + x2) / 2, y2)


@dataclass
class Zone:
    """危险区域（多边形），如塔吊回转半径、基坑临边、吊装警戒区。"""

    zone_id: str
    name: str
    kind: str  # crane / pit / lifting / electric ...
    polygon: list[tuple[float, float]]
    active: bool = True


@dataclass
class Frame:
    camera_id: str
    ts: float  # 秒
    width: int
    height: int
    detections: list[Detection] = field(default_factory=list)


@dataclass
class Hazard:
    """一条已确认的隐患事件（经过时序确认后才产生）。"""

    hazard_id: str
    rule_id: str
    title: str
    camera_id: str
    ts: float
    track_id: Optional[int]
    bbox: Optional[BBox]
    level: str  # 一般 / 较大 / 重大
    score: float
    standard: str
    measure: str
    zone_id: Optional[str] = None
