"""Write the redacted video and the redaction log for the SAR file."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import platform
from pathlib import Path
from typing import Callable

import cv2

from sarblur import APP_NAME, PUBLISHER, __version__, redact
from sarblur.analysis import Cancelled
from sarblur.project import Project
from sarblur.video import VideoWriter


def sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log_paths(output: str | Path) -> tuple[Path, Path]:
    out = Path(output)
    stem = out.with_suffix("")
    return Path(f"{stem}.redaction-log.json"), Path(f"{stem}.redaction-log.txt")


def _timecode(frame: int, fps: float) -> str:
    s = frame / fps
    return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{s % 60:06.3f}"


def export(project: Project, output: str, *, operator: str = "", reference: str = "",
           reviewed: bool = False, notes: str = "",
           progress: Callable[[int, int], None] | None = None,
           cancelled: Callable[[], bool] = lambda: False) -> dict:
    src = Path(project.video_path).resolve()
    out = Path(output).resolve()
    if out == src:
        raise ValueError("The output file must be different from the original footage.")

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        raise IOError(f"Could not open video: {src}")
    writer = VideoWriter(str(out), project.width, project.height, project.fps)
    frames = redacted_frames = 0
    total = project.frame_count
    started = dt.datetime.now().astimezone()
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if frame.shape[1] != project.width or frame.shape[0] != project.height:
                frame = cv2.resize(frame, (project.width, project.height))
            rects = project.redaction_rects(frames)
            if rects:
                redact.apply(frame, rects, project.style)
                redacted_frames += 1
            writer.write(frame)
            frames += 1
            if frames % 10 == 0:
                if cancelled():
                    raise Cancelled()
                if progress:
                    progress(frames, max(total, frames))
        writer.close()
    except BaseException:
        writer.abort()
        raise
    finally:
        cap.release()

    fps = project.fps
    tracks = []
    for t in sorted(project.tracks, key=lambda t: t.id):
        tracks.append({
            "id": t.id,
            "source": "automatic detection" if t.kind == "auto" else "added manually",
            "action": "redacted" if t.redact else "left visible (requester)",
            "first_frame": t.start, "last_frame": t.end,
            "from": _timecode(t.start, fps), "to": _timecode(t.end, fps),
        })

    log = {
        "tool": f"{APP_NAME} {__version__} ({PUBLISHER})",
        "created": started.isoformat(timespec="seconds"),
        "computer": platform.node(),
        "operator": operator,
        "sar_reference": reference,
        "operator_confirmed_full_review": reviewed,
        "notes": notes,
        "source": {"file": str(src), "size_bytes": src.stat().st_size, "sha256": sha256(src),
                   "width": project.width, "height": project.height, "fps": fps},
        "output": {"file": str(out), "size_bytes": out.stat().st_size, "sha256": sha256(out),
                   "encoder": writer.encoder, "audio": "removed"},
        "frames_total": frames,
        "frames_with_redaction": redacted_frames,
        "method": {"style": project.style, "padding": project.padding,
                   "detection": project.analysis_settings if project.analysed else "not run"},
        "tracks": tracks,
    }
    json_path, txt_path = log_paths(out)
    json_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    txt_path.write_text(_text_log(log), encoding="utf-8")
    if progress:
        progress(frames, frames)
    return log


def _text_log(log: dict) -> str:
    redacted = [t for t in log["tracks"] if t["action"] == "redacted"]
    kept = [t for t in log["tracks"] if t["action"] != "redacted"]
    s, o = log["source"], log["output"]
    lines = [
        "CCTV REDACTION LOG",
        "==================",
        f"Created:            {log['created']}",
        f"Tool:               {log['tool']}",
        f"Operator:           {log['operator'] or '(not given)'}",
        f"SAR reference:      {log['sar_reference'] or '(not given)'}",
        f"Full review confirmed by operator: {'YES' if log['operator_confirmed_full_review'] else 'NO'}",
        "",
        "Original footage (not modified)",
        f"  File:     {s['file']}",
        f"  SHA-256:  {s['sha256']}",
        f"  Format:   {s['width']}x{s['height']} @ {s['fps']:.3g} fps",
        "",
        "Redacted copy",
        f"  File:     {o['file']}",
        f"  SHA-256:  {o['sha256']}",
        f"  Encoder:  {o['encoder']}; audio removed",
        "",
        f"Frames: {log['frames_total']} total, {log['frames_with_redaction']} with redaction",
        f"Method: {log['method']['style']} (irreversible), padding {log['method']['padding']:.0%}",
        "",
        f"Redacted ({len(redacted)}):",
    ]
    lines += [f"  #{t['id']:<4} {t['from']} - {t['to']}  ({t['source']})" for t in redacted] or ["  none"]
    lines += ["", f"Left visible ({len(kept)}):"]
    lines += [f"  #{t['id']:<4} {t['from']} - {t['to']}  ({t['source']})" for t in kept] or ["  none"]
    if log["notes"]:
        lines += ["", "Notes:", log["notes"]]
    lines += ["", "The person releasing this footage is responsible for checking every frame before disclosure."]
    return "\n".join(lines) + "\n"
