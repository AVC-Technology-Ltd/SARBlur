"""Project model: tracks of boxes over time, and the JSON sidecar that stores them.

A Track is a run of boxes for one person (auto-detected) or one manual box.
Boxes are stored as keyframes; between keyframes the box is linearly
interpolated, and between `start`/`end` and the first/last keyframe the
nearest keyframe box is held. That gives auto tracks a little pre/post-roll
and lets a single manual keyframe cover a span of frames.
"""
from __future__ import annotations

import bisect
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

Box = tuple[float, float, float, float]  # x, y, w, h in source pixels

PROJECT_VERSION = 1


@dataclass(eq=False)
class Track:
    id: int
    kind: str  # "auto" or "manual"
    start: int
    end: int
    keyframes: dict[int, Box] = field(default_factory=dict)
    redact: bool = True  # False = requester / keep visible
    _keys: list[int] | None = field(default=None, init=False, repr=False)

    # -- keyframes ---------------------------------------------------------
    def _sorted(self) -> list[int]:
        if self._keys is None:
            self._keys = sorted(self.keyframes)
        return self._keys

    def set_box(self, frame: int, box: Box) -> None:
        self.keyframes[frame] = tuple(float(v) for v in box)  # type: ignore[assignment]
        self._keys = None
        self.start = min(self.start, frame)
        self.end = max(self.end, frame)

    def remove_box(self, frame: int) -> None:
        if frame in self.keyframes and len(self.keyframes) > 1:
            del self.keyframes[frame]
            self._keys = None

    def box_at(self, frame: int) -> Box | None:
        if frame < self.start or frame > self.end or not self.keyframes:
            return None
        kf = self.keyframes.get(frame)
        if kf is not None:
            return kf
        keys = self._sorted()
        i = bisect.bisect_left(keys, frame)
        if i == 0:
            return self.keyframes[keys[0]]
        if i == len(keys):
            return self.keyframes[keys[-1]]
        a, b = keys[i - 1], keys[i]
        t = (frame - a) / (b - a)
        ba, bb = self.keyframes[a], self.keyframes[b]
        return tuple(pa + (pb - pa) * t for pa, pb in zip(ba, bb))  # type: ignore[return-value]

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "redact": self.redact,
            "keyframes": {str(k): [round(v, 1) for v in b] for k, b in sorted(self.keyframes.items())},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Track":
        t = cls(id=int(d["id"]), kind=d["kind"], start=int(d["start"]), end=int(d["end"]),
                redact=bool(d.get("redact", True)))
        t.keyframes = {int(k): tuple(float(v) for v in b) for k, b in d["keyframes"].items()}  # type: ignore[misc]
        return t


def pad_box(box: Box, pad: float, width: int, height: int) -> tuple[int, int, int, int]:
    """Grow a face box so it covers the whole head (hair, ears, chin), clipped to the frame.

    `pad` is the fraction of the box size added on each side; the top gets a
    little extra because face detectors cut off at the hairline.
    Returns integer (x0, y0, x1, y1).
    """
    x, y, w, h = box
    px, py = w * pad, h * pad
    x0 = int(max(0, x - px))
    y0 = int(max(0, y - py * 1.4))
    x1 = int(min(width, x + w + px + 0.999))
    y1 = int(min(height, y + h + py + 0.999))
    return x0, y0, x1, y1


def unpad_rect(x0: float, y0: float, x1: float, y1: float, pad: float) -> Box:
    """Inverse of pad_box (ignoring clipping): the face box whose padded rect is the given rect."""
    w = (x1 - x0) / (1 + 2 * pad)
    h = (y1 - y0) / (1 + 2.4 * pad)
    return (x0 + pad * w, y0 + 1.4 * pad * h, w, h)


@dataclass
class Project:
    video_path: str
    width: int
    height: int
    fps: float
    frame_count: int
    tracks: list[Track] = field(default_factory=list)
    padding: float = 0.25
    style: str = "pixelate"  # "pixelate" or "solid"
    analysed: bool = False
    analysis_settings: dict = field(default_factory=dict)
    video_size: int = 0  # bytes, used to check the sidecar still matches the video

    # -- tracks --------------------------------------------------------------
    def next_id(self) -> int:
        return max((t.id for t in self.tracks), default=0) + 1

    def track(self, track_id: int) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    def add_manual(self, frame: int, box: Box, hold_frames: int) -> Track:
        t = Track(id=self.next_id(), kind="manual", start=frame,
                  end=min(self.frame_count - 1, frame + hold_frames) if self.frame_count else frame + hold_frames)
        t.set_box(frame, box)
        self.tracks.append(t)
        return t

    def delete(self, track_id: int) -> None:
        self.tracks = [t for t in self.tracks if t.id != track_id]

    def boxes_at(self, frame: int) -> list[tuple[Track, Box]]:
        out = []
        for t in self.tracks:
            b = t.box_at(frame)
            if b is not None:
                out.append((t, b))
        return out

    def redaction_rects(self, frame: int) -> list[tuple[int, int, int, int]]:
        """Padded, clipped (x0, y0, x1, y1) rects to redact on this frame."""
        rects = []
        for t, b in self.boxes_at(frame):
            if t.redact:
                r = pad_box(b, self.padding, self.width, self.height)
                if r[2] > r[0] and r[3] > r[1]:
                    rects.append(r)
        return rects

    # -- persistence -----------------------------------------------------------
    @staticmethod
    def sidecar_path(video_path: str | os.PathLike) -> Path:
        p = Path(video_path)
        return p.with_name(p.name + ".sarblur.json")

    def to_dict(self) -> dict:
        return {
            "sarblur_project": PROJECT_VERSION,
            "video_path": self.video_path,
            "video_size": self.video_size,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "padding": self.padding,
            "style": self.style,
            "analysed": self.analysed,
            "analysis_settings": self.analysis_settings,
            "tracks": [t.to_dict() for t in self.tracks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        p = cls(video_path=d["video_path"], width=int(d["width"]), height=int(d["height"]),
                fps=float(d["fps"]), frame_count=int(d["frame_count"]))
        p.video_size = int(d.get("video_size", 0))
        p.padding = float(d.get("padding", 0.25))
        p.style = d.get("style", "pixelate")
        p.analysed = bool(d.get("analysed", False))
        p.analysis_settings = d.get("analysis_settings", {})
        p.tracks = [Track.from_dict(t) for t in d.get("tracks", [])]
        return p

    def save(self, path: str | os.PathLike | None = None) -> Path:
        path = Path(path) if path else self.sidecar_path(self.video_path)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=1), encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
