"""几何工具：IoU、包含度、点在多边形内。"""
from __future__ import annotations

from .models import BBox


def area(b: BBox) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a: BBox, b: BBox) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0.0, x2 - x1) * max(0.0, y2 - y1)


def iou(a: BBox, b: BBox) -> float:
    inter = intersection(a, b)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def containment(inner: BBox, outer: BBox) -> float:
    """inner 有多大比例落在 outer 内（0~1）。"""
    a = area(inner)
    return intersection(inner, outer) / a if a > 0 else 0.0


def head_region(person: BBox, ratio: float = 0.28) -> BBox:
    """人体框上部区域，用于匹配安全帽/头部框。"""
    x1, y1, x2, y2 = person
    h = y2 - y1
    pad = (x2 - x1) * 0.1
    return (x1 - pad, y1 - h * 0.08, x2 + pad, y1 + h * ratio)


def torso_region(person: BBox) -> BBox:
    """人体框中部区域，用于匹配反光衣框。"""
    x1, y1, x2, y2 = person
    h = y2 - y1
    return (x1, y1 + h * 0.18, x2, y1 + h * 0.70)


def point_in_polygon(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    """射线法。"""
    x, y = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            x_cross = (xj - xi) * (y - yi) / (yj - yi) + xi
            if x < x_cross:
                inside = not inside
        j = i
    return inside
