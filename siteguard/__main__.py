"""命令行入口。

    python -m siteguard run samples/site_demo.json --out out/
    python -m siteguard yolo --weights best.pt --source site.mp4 --zones zones.json --out out/
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from .detectors import ReplayDetector
from .engine import HazardEngine
from .models import Zone
from .tickets import TicketBook


def _zones(raw: list[dict]) -> list[Zone]:
    return [Zone(z["zone_id"], z["name"], z["kind"], [tuple(p) for p in z["polygon"]]) for z in raw]


def run(frames, zones, out: Path, base_time: datetime | None = None) -> TicketBook:
    engine = HazardEngine(zones)
    book = TicketBook(engine.levels, base_time=base_time)
    for f in frames:
        _, hazards = engine.process(f)
        for h in hazards:
            t = book.issue(h)
            print(f"[{h.ts:6.1f}s] {h.level:<2} {h.title}  -> {t.ticket_no}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "tickets.json").write_text(
        json.dumps([t.to_dict() for t in book.tickets], ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "tickets.md").write_text(
        "\n\n---\n\n".join(t.to_markdown() for t in book.tickets), encoding="utf-8")
    s = book.summary()
    (out / "summary.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n共生成 {s['total']} 张整改单：{s['by_level']}；输出目录 {out}")
    return book


def main() -> None:
    p = argparse.ArgumentParser(prog="siteguard", description="筑安智检：施工现场安全隐患 AI 巡检")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="回放标注数据（离线演示）")
    r.add_argument("replay")
    r.add_argument("--out", default="out")
    y = sub.add_parser("yolo", help="用 YOLO 权重处理视频")
    y.add_argument("--weights", required=True)
    y.add_argument("--source", required=True)
    y.add_argument("--zones", help="危险区 JSON（列表）")
    y.add_argument("--out", default="out")
    a = p.parse_args()

    if a.cmd == "run":
        det = ReplayDetector(a.replay)
        run(det.frames(), _zones(det.zones), Path(a.out),
            base_time=datetime(2026, 10, 17, 9, 0, 0))
    else:
        from .detectors import YoloDetector
        det = YoloDetector(a.weights, a.source)
        zones = _zones(json.loads(Path(a.zones).read_text(encoding="utf-8"))) if a.zones else []
        run(det.frames(), zones, Path(a.out))


if __name__ == "__main__":
    main()
