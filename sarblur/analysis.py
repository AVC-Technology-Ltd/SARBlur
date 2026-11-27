"""Run face detection across a whole video and build tracks."""
from __future__ import annotations

from typing import Callable

import cv2

from sarblur.detect import FaceDetector
from sarblur.project import Project
from sarblur.tracking import Tracker


class Cancelled(Exception):
    pass


def analyse(project: Project, stride: int = 1, score_threshold: float = 0.6,
            progress: Callable[[int, int], None] | None = None,
            cancelled: Callable[[], bool] = lambda: False) -> None:
    """Detect faces in every `stride`-th frame and replace the project's auto tracks.

    Manual tracks and the keep/redact choice of manual tracks are preserved.
    Also corrects project.frame_count to the number of frames actually decoded.
    """
    detector = FaceDetector(score_threshold=score_threshold)
    fps = project.fps or 25.0
    tracker = Tracker(max_gap=max(stride * 2, round(fps)))
    cap = cv2.VideoCapture(project.video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video: {project.video_path}")
    total = project.frame_count
    frame_no = 0
    try:
        while True:
            if stride > 1 and frame_no % stride:
                if not cap.grab():
                    break
            else:
                ok, frame = cap.read()
                if not ok:
                    break
                tracker.update(frame_no, detector.detect(frame))
            frame_no += 1
            if frame_no % 10 == 0:
                if cancelled():
                    raise Cancelled()
                if progress:
                    progress(frame_no, max(total, frame_no))
    finally:
        cap.release()

    project.frame_count = frame_no
    preroll = max(stride, round(fps * 0.5))
    auto = tracker.finish(preroll, frame_no)
    manual = [t for t in project.tracks if t.kind == "manual"]
    project.tracks = auto
    for t in manual:  # renumber after the auto tracks
        t.id = project.next_id()
        project.tracks.append(t)
    project.analysed = True
    project.analysis_settings = {"detector": "YuNet 2023mar", "stride": stride,
                                 "score_threshold": score_threshold}
    if progress:
        progress(frame_no, frame_no)
