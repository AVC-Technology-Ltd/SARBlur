"""`SARBlur --self-test`: check a build can load the model, detect, and export.

Used by the release workflow on the packaged program. Writes a short report
to the path given after the flag (the windowed build has no console) and
exits 0 on success.
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

import cv2
import numpy as np


def run(report_path: str | None = None) -> int:
    lines = []
    ok = False
    try:
        from sarblur import __version__
        from sarblur.analysis import analyse
        from sarblur.detect import FaceDetector
        from sarblur.export import export
        from sarblur.project import Project
        from sarblur.video import ffmpeg_exe, h264_available, probe

        lines.append(f"SARBlur {__version__}")
        FaceDetector().detect(np.zeros((480, 640, 3), np.uint8))
        lines.append("face model: ok")
        exe = ffmpeg_exe()
        lines.append(f"ffmpeg: {exe}")
        lines.append(f"h264: {bool(exe) and h264_available(exe)}")
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "selftest.avi"
            w = cv2.VideoWriter(str(src), cv2.VideoWriter_fourcc(*"MJPG"), 25.0, (321, 241))
            for i in range(40):
                f = np.full((241, 321, 3), 90, np.uint8)
                f[100:140, 20 + i * 5:60 + i * 5] = (0, 200, 255)
                w.write(f)
            w.release()
            info = probe(str(src))
            p = Project(video_path=str(src), width=info.width, height=info.height, fps=info.fps,
                        frame_count=info.frame_count, padding=0.0, style="solid")
            p.add_manual(0, (150, 60, 80, 80), hold_frames=40)
            analyse(p, stride=4)
            out = Path(tmp) / "selftest_redacted.mp4"
            log = export(p, str(out), operator="self-test", reviewed=True)
            cap = cv2.VideoCapture(str(out))
            n, dark = 0, True
            while True:
                good, frame = cap.read()
                if not good:
                    break
                n += 1
                dark &= frame[70:130, 160:220].mean() < 10
            cap.release()
            lines.append(f"export: {log['output']['encoder']}, {n} frames, redacted={dark}")
            ok = n == 40 and dark
    except Exception:
        lines.append(traceback.format_exc())
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    text = "\n".join(lines) + "\n"
    if report_path:
        Path(report_path).write_text(text, encoding="utf-8")
    elif sys.stdout:
        sys.stdout.write(text)
    return 0 if ok else 1
