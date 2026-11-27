"""Reading source video (OpenCV) and writing the redacted MP4 (FFmpeg, OpenCV fallback)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
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


_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def ffmpeg_exe() -> str | None:
    """The FFmpeg to encode with.

    Release builds ship a minimal LGPL FFmpeg in an `ffmpeg` folder beside the
    program. From source, use SARBLUR_FFMPEG, then imageio-ffmpeg (dev only),
    then FFmpeg on PATH.
    """
    exe_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    bases = [Path(getattr(sys, "_MEIPASS", "")), Path(sys.executable).parent] if getattr(sys, "frozen", False) else []
    for base in bases:
        candidate = base / "ffmpeg" / exe_name
        if candidate.exists():
            return str(candidate)
    if os.environ.get("SARBLUR_FFMPEG") and Path(os.environ["SARBLUR_FFMPEG"]).exists():
        return os.environ["SARBLUR_FFMPEG"]
    if not getattr(sys, "frozen", False):
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return shutil.which("ffmpeg")


_h264_ok: dict[str, bool] = {}


def h264_available(exe: str) -> bool:
    """Whether Windows' H.264 encoder (Media Foundation) works here.

    It is missing on Windows 'N' editions without the Media Feature Pack, so
    try a tiny encode once and remember the answer.
    """
    if exe not in _h264_ok:
        ok = False
        if sys.platform == "win32":
            fd, tmp = tempfile.mkstemp(suffix=".mp4")
            os.close(fd)
            try:
                frames = np.zeros((240, 320, 3), np.uint8).tobytes() * 3
                r = subprocess.run([exe, "-y", "-hide_banner", "-loglevel", "error",
                                    "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "320x240", "-r", "25",
                                    "-i", "-", "-c:v", "h264_mf", "-pix_fmt", "nv12", tmp],
                                   input=frames, capture_output=True, timeout=30, creationflags=_NO_WINDOW)
                ok = r.returncode == 0 and os.path.getsize(tmp) > 0
            except Exception:
                ok = False
            finally:
                Path(tmp).unlink(missing_ok=True)
        _h264_ok[exe] = ok
    return _h264_ok[exe]


def h264_bitrate(width: int, height: int, fps: float) -> int:
    """Around 4 Mbit/s for 1080p at 25 fps, scaled by pixel rate, within 1.5-12 Mbit/s."""
    return int(min(12e6, max(1.5e6, width * height * fps * 0.08)))


class VideoWriter:
    """Writes BGR frames to an MP4 via FFmpeg (no audio track).

    Uses H.264 from Windows' own encoder where available, otherwise MPEG-4
    Part 2. Falls back to OpenCV's MPEG-4 writer if there is no FFmpeg.
    """

    def __init__(self, path: str, width: int, height: int, fps: float):
        self.path = path
        self.encoder = ""
        self._proc = None
        self._cv = None
        exe = ffmpeg_exe()
        if exe:
            if h264_available(exe):
                rate = h264_bitrate(width, height, fps)
                codec = ["-c:v", "h264_mf", "-b:v", str(rate), "-pix_fmt", "nv12"]
                self.encoder = f"FFmpeg + Windows H.264 encoder ({rate / 1e6:.1f} Mbit/s)"
            else:
                codec = ["-c:v", "mpeg4", "-q:v", "3", "-pix_fmt", "yuv420p"]
                self.encoder = "FFmpeg MPEG-4 Part 2 (q 3)"
            cmd = [exe, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", f"{fps:.6g}",
                   "-i", "-", "-an",
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                   *codec,
                   "-movflags", "+faststart", "-map_metadata", "-1",
                   "-metadata", "comment=Redacted with SARBlur",
                   path]
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                          creationflags=_NO_WINDOW)
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
