"""生成离线演示用的检测回放数据 samples/site_demo.json。

模拟一路 1280x720 工地摄像头，30 秒 @ 5fps，包含：
- 工人A：装备齐全，正常走动；第 3 秒有一帧误检为「裸头」（用于展示时序确认过滤误报）
- 工人B：未戴安全帽，第 10~16 秒走进塔吊回转区（复合风险）
- 工人C：未穿反光背心，约第 9 秒起走到基坑临边并滞留
- 第 22~25 秒出现烟雾
"""
import json
import random
from pathlib import Path

random.seed(7)
W, H, FPS, DUR = 1280, 720, 5, 30

ZONES = [
    {"zone_id": "Z1", "name": "1#塔吊回转半径", "kind": "crane",
     "polygon": [[700, 260], [1080, 260], [1180, 520], [620, 520]]},
    {"zone_id": "Z2", "name": "东侧基坑临边", "kind": "pit",
     "polygon": [[60, 300], [380, 300], [420, 470], [40, 470]]},
]


def lerp(a, b, t):
    return a + (b - a) * t


def path(points, t):
    """points: [(t, x, y)]，按时间分段线性插值脚底坐标。"""
    for (t0, x0, y0), (t1, x1, y1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            k = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return lerp(x0, x1, k), lerp(y0, y1, k)
    return points[-1][1], points[-1][2]


def person_dets(fx, fy, helmet=True, vest=True, scale=1.0, jitter=2.0):
    h = 150 * scale * (0.6 + 0.6 * fy / H)  # 近大远小
    w = h * 0.38
    jx, jy = random.uniform(-jitter, jitter), random.uniform(-jitter, jitter)
    x1, y1, x2, y2 = fx - w / 2 + jx, fy - h + jy, fx + w / 2 + jx, fy + jy
    out = [{"label": "person", "conf": round(random.uniform(0.82, 0.95), 2), "bbox": [x1, y1, x2, y2]}]
    hw, hh = w * 0.5, h * 0.16
    head = [fx - hw / 2 + jx, y1 + h * 0.01, fx + hw / 2 + jx, y1 + hh]
    out.append({"label": "helmet" if helmet else "head", "conf": round(random.uniform(0.7, 0.9), 2), "bbox": head})
    if vest:
        out.append({"label": "vest", "conf": round(random.uniform(0.7, 0.9), 2),
                    "bbox": [x1 + w * 0.1, y1 + h * 0.25, x2 - w * 0.1, y1 + h * 0.6]})
    return out


A = [(0, 200, 640), (15, 1100, 660), (30, 300, 650)]
B = [(0, 560, 600), (8, 640, 560), (10, 760, 480), (16, 900, 420), (19, 1180, 600), (30, 1200, 640)]
C = [(0, 520, 420), (18, 300, 430), (26, 260, 440), (30, 520, 520)]

frames = []
for i in range(DUR * FPS + 1):
    t = round(i / FPS, 2)
    dets = []
    ax, ay = path(A, t)
    dets += person_dets(ax, ay, helmet=not (2.9 < t < 3.1))  # 单帧误检
    bx, by = path(B, t)
    dets += person_dets(bx, by, helmet=False)
    cx, cy = path(C, t)
    dets += person_dets(cx, cy, vest=False)
    if 22 <= t <= 25:
        dets.append({"label": "smoke", "conf": 0.66, "bbox": [980, 120, 1120, 230]})
    for d in dets:
        d["bbox"] = [round(v, 1) for v in d["bbox"]]
    frames.append({"ts": t, "dets": dets})

out = Path(__file__).resolve().parents[1] / "samples" / "site_demo.json"
out.write_text(json.dumps({"camera_id": "CAM-03 东区塔吊", "width": W, "height": H, "fps": FPS,
                           "zones": ZONES, "frames": frames}, ensure_ascii=False), encoding="utf-8")
print(f"wrote {out} ({len(frames)} frames)")
