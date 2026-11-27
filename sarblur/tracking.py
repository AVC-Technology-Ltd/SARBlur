"""Link per-frame face detections into tracks (one track per person appearance)."""
from __future__ import annotations

from sarblur.project import Box, Track


def iou(a: Box, b: Box) -> float:
    ax1, ay1, ax2, ay2 = a[0], a[1], a[0] + a[2], a[1] + a[3]
    bx1, by1, bx2, by2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _affinity(a: Box, b: Box) -> float:
    """IoU, or a weaker centre-distance score for fast movers at low CCTV frame rates."""
    v = iou(a, b)
    if v > 0:
        return 1.0 + v
    size = max(a[2], a[3], b[2], b[3])
    dx = (a[0] + a[2] / 2) - (b[0] + b[2] / 2)
    dy = (a[1] + a[3] / 2) - (b[1] + b[3] / 2)
    dist = (dx * dx + dy * dy) ** 0.5
    ratio = max(a[2], b[2]) / max(1.0, min(a[2], b[2]))
    if dist < 1.0 * size and ratio < 2.0:
        return 1.0 - dist / size
    return 0.0


class Tracker:
    def __init__(self, max_gap: int = 25, min_affinity: float = 0.15):
        self.max_gap = max_gap
        self.min_affinity = min_affinity
        self._active: list[tuple[Track, int, Box]] = []  # track, last frame, last box
        self._done: list[Track] = []
        self._next_id = 1

    def update(self, frame: int, detections) -> None:
        still = []
        for item in self._active:
            if frame - item[1] > self.max_gap:
                self._done.append(item[0])
            else:
                still.append(item)
        self._active = still

        boxes = [tuple(d[:4]) for d in detections]
        pairs = []
        for ti, (_, _, last) in enumerate(self._active):
            for di, b in enumerate(boxes):
                a = _affinity(last, b)
                if a >= self.min_affinity:
                    pairs.append((a, ti, di))
        pairs.sort(reverse=True)
        used_t, used_d = set(), set()
        for _, ti, di in pairs:
            if ti in used_t or di in used_d:
                continue
            used_t.add(ti)
            used_d.add(di)
            track = self._active[ti][0]
            track.set_box(frame, boxes[di])
            self._active[ti] = (track, frame, boxes[di])
        for di, b in enumerate(boxes):
            if di not in used_d:
                t = Track(id=self._next_id, kind="auto", start=frame, end=frame)
                self._next_id += 1
                t.set_box(frame, b)
                self._active.append((t, frame, b))

    def finish(self, preroll: int, frame_count: int) -> list[Track]:
        tracks = self._done + [t for t, _, _ in self._active]
        self._active, self._done = [], []
        for t in tracks:
            t.start = max(0, t.start - preroll)
            t.end = min(frame_count - 1, t.end + preroll) if frame_count else t.end + preroll
        tracks.sort(key=lambda t: (t.start, t.id))
        for i, t in enumerate(tracks, 1):
            t.id = i
        return tracks
