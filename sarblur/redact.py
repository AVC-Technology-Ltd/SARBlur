"""Irreversible redaction of rectangles in a frame.

Gaussian blur is deliberately not offered: mild blur can be partially
reversed. Pixelation here reduces each region to at most PIXEL_BLOCKS
blocks along its longest side, which leaves too little information to
recognise anyone.
"""
from __future__ import annotations

import cv2
import numpy as np

STYLES = ("pixelate", "solid")
PIXEL_BLOCKS = 6


def apply(frame: np.ndarray, rects, style: str = "pixelate") -> np.ndarray:
    """Redact rects (x0, y0, x1, y1) in place and return the frame."""
    for x0, y0, x1, y1 in rects:
        roi = frame[y0:y1, x0:x1]
        h, w = roi.shape[:2]
        if h == 0 or w == 0:
            continue
        if style == "solid":
            roi[:] = 0
            continue
        longest = max(w, h)
        bw = max(1, round(w / longest * PIXEL_BLOCKS))
        bh = max(1, round(h / longest * PIXEL_BLOCKS))
        small = cv2.resize(roi, (bw, bh), interpolation=cv2.INTER_AREA)
        roi[:] = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
    return frame
