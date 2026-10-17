"""检测器适配层。

- YoloDetector：接入 Ultralytics YOLO 系列权重（需自行准备在安全帽/反光衣数据集上训练的模型，
  例如基于公开的 SHWD 安全帽数据集微调）。类别名通过 label_map 映射到统一标签。
- ReplayDetector：读取标注好的 JSON 回放，离线演示和单元测试用，不依赖 GPU 或网络。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator, Protocol

from .models import Detection, Frame

UNIFIED_LABELS = {"person", "helmet", "head", "vest", "fire", "smoke"}


class Detector(Protocol):
    def frames(self) -> Iterator[Frame]: ...


class ReplayDetector:
    """从 samples/*.json 回放检测结果。"""

    def __init__(self, path: str | Path):
        self.data = json.loads(Path(path).read_text(encoding="utf-8"))

    @property
    def zones(self) -> list[dict]:
        return self.data.get("zones", [])

    def frames(self) -> Iterator[Frame]:
        meta = self.data
        for f in meta["frames"]:
            yield Frame(
                camera_id=meta["camera_id"],
                ts=f["ts"],
                width=meta["width"],
                height=meta["height"],
                detections=[Detection(d["label"], d["conf"], tuple(d["bbox"])) for d in f["dets"]],
            )


class YoloDetector:
    """视频流/视频文件 → Frame。ultralytics 为可选依赖。"""

    DEFAULT_MAP = {
        "person": "person",
        "helmet": "helmet",
        "hardhat": "helmet",
        "head": "head",
        "no-helmet": "head",
        "vest": "vest",
        "safety-vest": "vest",
        "fire": "fire",
        "smoke": "smoke",
    }

    def __init__(self, weights: str, source: str, camera_id: str = "cam01",
                 label_map: dict[str, str] | None = None, stride: int = 5, conf: float = 0.35):
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise RuntimeError("需要先 pip install ultralytics 才能使用 YoloDetector") from e
        self.model = YOLO(weights)
        self.source = source
        self.camera_id = camera_id
        self.label_map = {k.lower(): v for k, v in (label_map or self.DEFAULT_MAP).items()}
        self.stride = stride
        self.conf = conf

    def frames(self) -> Iterator[Frame]:  # pragma: no cover - 需要模型与视频
        names = self.model.names
        for i, r in enumerate(self.model.predict(self.source, stream=True, conf=self.conf,
                                                 vid_stride=self.stride, verbose=False)):
            h, w = r.orig_shape
            dets = []
            for b in r.boxes:
                raw = str(names[int(b.cls)]).lower()
                label = self.label_map.get(raw)
                if label in UNIFIED_LABELS:
                    dets.append(Detection(label, float(b.conf), tuple(float(v) for v in b.xyxy[0])))
            fps = 25.0
            yield Frame(self.camera_id, i * self.stride / fps, w, h, dets)
