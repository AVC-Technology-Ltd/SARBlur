"""Reading source video (OpenCV) and writing the redacted MP4 (FFmpeg, OpenCV fallback)."""
from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

DEFAULT_FPS = 25.0  # UK CCTV is almost always 25 fps (PAL) when the file does not say


@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    frame_count: int  # container's estimate; analysis counts the real number


def probe(path: str) -> VideoInfo:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise IOError(f"Could not open video: {path}")
    try:
        ok, frame = cap.read()
        if not ok:
            raise IOError(f"Could not read any frames from: {path}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps or fps < 1 or fps > 240:
            fps = DEFAULT_FPS
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        return VideoInfo(path, frame.shape[1], frame.shape[0], float(fps), max(count, 1))
    finally:
        cap.release()


class FrameReader:
    """Random-access frame reader, fast for sequential reads."""

    def __init__(self, path: str):
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            raise IOError(f"Could not open video: {path}")
        self._next = 0

    def read(self, index: int) -> np.ndarray | None:
        if index != self._next:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        self._next = index + 1 if ok else -1
        return frame if ok else None

    def close(self) -> None:
        self.cap.release()


def ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


class VideoWriter:
    """Writes BGR frames to an H.264 MP4 via FFmpeg (no audio track).

    Falls back to OpenCV's MPEG-4 Part 2 writer if FFmpeg is unavailable.
    """

    def __init__(self, path: str, width: int, height: int, fps: float):
        self.path = path
        self.encoder = ""
        self._proc = None
        self._cv = None
        exe = ffmpeg_exe()
        if exe:
            cmd = [exe, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.6g}",
                   "-i", "-", "-an",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                   "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                   "-movflags", "+faststart", "-map_metadata", "-1",
                   "-metadata", "comment=Redacted with SARBlur",
                   path]
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=flags)
            self.encoder = "FFmpeg libx264 (CRF 18)"
        else:
            self._cv = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
            if not self._cv.isOpened():
                raise IOError(f"Could not create output video: {path}")
            self.encoder = "OpenCV mp4v"

    def write(self, frame: np.ndarray) -> None:
        if self._proc:
            try:
                self._proc.stdin.write(np.ascontiguousarray(frame).tobytes())
            except (BrokenPipeError, OSError):
                err = self._proc.stderr.read().decode(errors="replace") if self._proc.stderr else ""
                raise IOError(f"FFmpeg stopped unexpectedly: {err.strip()}")
        else:
            self._cv.write(frame)

    def close(self) -> None:
        if self._proc:
            self._proc.stdin.close()
            err = self._proc.stderr.read().decode(errors="replace")
            if self._proc.wait() != 0:
                raise IOError(f"FFmpeg failed: {err.strip()}")
            self._proc = None
        elif self._cv:
            self._cv.release()
            self._cv = None

    def abort(self) -> None:
        try:
            if self._proc:
                self._proc.kill()
                self._proc.wait()
            elif self._cv:
                self._cv.release()
        finally:
            self._proc = self._cv = None
            Path(self.path).unlink(missing_ok=True)
