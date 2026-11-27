"""Face detection with YuNet (MIT licence, OpenCV Zoo) via OpenCV's DNN module."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

try:  # silence OpenCV's DNN backend chatter
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:  # pragma: no cover
    pass

MODEL_NAME = "face_detection_yunet_2023mar.onnx"


def model_path() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for candidate in (base / "sarblur" / "models" / MODEL_NAME, Path(__file__).resolve().parent / "models" / MODEL_NAME):
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Face model {MODEL_NAME} not found")


class FaceDetector:
    """Detects faces in BGR frames.

    The score threshold is set lower than YuNet's usual 0.9 on purpose: for
    redaction a false positive (blurring a bag) is cheap, a miss is not.
    Small frames (typical D1/720p CCTV) are upscaled so distant faces are
    big enough for the detector.
    """

    def __init__(self, score_threshold: float = 0.6, nms_threshold: float = 0.3,
                 min_side: int = 1280, max_side: int = 1920):
        self.score_threshold = score_threshold
        self.min_side = min_side
        self.max_side = max_side
        self._net = cv2.FaceDetectorYN.create(str(model_path()), "", (320, 320),
                                              score_threshold, nms_threshold, 5000)
        self._size: tuple[int, int] | None = None

    def detect(self, frame: np.ndarray) -> list[tuple[float, float, float, float, float]]:
        h, w = frame.shape[:2]
        longest = max(h, w)
        scale = 1.0
        if longest < self.min_side:
            scale = self.min_side / longest
        elif longest > self.max_side:
            scale = self.max_side / longest
        img = frame
        if scale != 1.0:
            interp = cv2.INTER_LINEAR if scale > 1 else cv2.INTER_AREA
            img = cv2.resize(frame, (round(w * scale), round(h * scale)), interpolation=interp)
        size = (img.shape[1], img.shape[0])
        if size != self._size:
            self._net.setInputSize(size)
            self._size = size
        _, faces = self._net.detect(img)
        if faces is None:
            return []
        out = []
        for row in faces:
            x, y, bw, bh = (float(v) / scale for v in row[:4])
            out.append((x, y, bw, bh, float(row[-1])))
        return out
