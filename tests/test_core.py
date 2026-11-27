import json

import cv2
import numpy as np
import pytest

from sarblur import redact
from sarblur.analysis import analyse
from sarblur.export import export, log_paths
from sarblur.project import Project, Track, pad_box, unpad_rect
from sarblur.tracking import Tracker, iou
from sarblur.video import probe

W, H, FPS, N = 320, 240, 25.0, 50


@pytest.fixture
def video(tmp_path):
    """A noisy synthetic clip: a bright square moves left to right."""
    path = tmp_path / "clip.avi"
    out = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (W, H))
    rng = np.random.default_rng(0)
    for i in range(N):
        f = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
        x = 20 + i * 4
        f[100:140, x:x + 40] = (0, 200, 255)
        out.write(f)
    out.release()
    return path


def test_track_interpolation_and_hold():
    t = Track(id=1, kind="auto", start=0, end=20)
    t.set_box(5, (0, 0, 10, 10))
    t.set_box(15, (100, 0, 10, 10))
    assert t.box_at(10) == pytest.approx((50, 0, 10, 10))
    assert t.box_at(2) == (0, 0, 10, 10)        # held before first keyframe
    assert t.box_at(20) == (100, 0, 10, 10)     # held after last keyframe
    assert t.box_at(21) is None


def test_pad_unpad_round_trip():
    box = (50.0, 40.0, 30.0, 36.0)
    r = pad_box(box, 0.25, 1000, 1000)
    back = unpad_rect(*r, 0.25)
    assert back == pytest.approx(box, abs=1.5)
    assert pad_box((0, 0, 50, 50), 0.5, 40, 40) == (0, 0, 40, 40)  # clipped to frame


def test_tracker_links_moving_face_and_splits_distant_ones():
    tr = Tracker(max_gap=5)
    for f in range(10):
        tr.update(f, [(10 + f * 3, 10, 20, 20, 0.9), (200, 150, 20, 20, 0.9)])
    tr.update(30, [(10, 10, 20, 20, 0.9)])  # after a long gap -> new track
    tracks = tr.finish(preroll=2, frame_count=40)
    assert len(tracks) == 3
    assert [t.id for t in tracks] == [1, 2, 3]
    first = tracks[0]
    assert first.start == 0 and first.end == 11


def test_iou():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1
    assert iou((0, 0, 10, 10), (20, 20, 10, 10)) == 0


@pytest.mark.parametrize("style", ["pixelate", "solid"])
def test_redaction_destroys_detail(style):
    rng = np.random.default_rng(1)
    frame = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    before = frame.copy()
    redact.apply(frame, [(50, 50, 150, 150)], style)
    roi = frame[50:150, 50:150].reshape(-1, 3)
    assert len(np.unique(roi, axis=0)) <= redact.PIXEL_BLOCKS ** 2
    assert np.array_equal(frame[:50], before[:50])  # outside untouched


def test_project_save_load(tmp_path):
    p = Project(video_path="x.mp4", width=W, height=H, fps=FPS, frame_count=N)
    t = p.add_manual(3, (10, 10, 20, 20), hold_frames=10)
    t.redact = False
    path = p.save(tmp_path / "x.json")
    q = Project.load(path)
    assert q.tracks[0].redact is False
    assert q.tracks[0].box_at(5) == pytest.approx((10, 10, 20, 20))


def test_analyse_runs_without_faces(video):
    info = probe(str(video))
    p = Project(video_path=str(video), width=info.width, height=info.height, fps=info.fps,
                frame_count=info.frame_count)
    p.add_manual(0, (0, 0, 10, 10), 5)
    analyse(p, stride=2)
    assert p.analysed and p.frame_count == N
    assert any(t.kind == "manual" for t in p.tracks)


def test_export_redacts_box_and_writes_log(video, tmp_path):
    info = probe(str(video))
    p = Project(video_path=str(video), width=info.width, height=info.height, fps=info.fps,
                frame_count=N, padding=0.0, style="solid")
    p.add_manual(0, (100, 50, 60, 60), hold_frames=N)
    keep = p.add_manual(0, (0, 0, 30, 30), hold_frames=N)
    keep.redact = False
    out = tmp_path / "out.mp4"
    log = export(p, str(out), operator="Tester", reference="SAR-1", reviewed=True)

    cap = cv2.VideoCapture(str(out))
    frames = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames += 1
        assert f[60:100, 110:150].mean() < 8   # redacted region is black (allowing for compression)
        assert f[0:30, 0:30].std() > 30        # kept region still has detail
    assert frames == N
    jp, tp = log_paths(out)
    data = json.loads(jp.read_text())
    assert data["frames_total"] == N and data["sar_reference"] == "SAR-1"
    assert log["output"]["sha256"] == data["output"]["sha256"]
    assert "left visible (requester)" in tp.read_text() or "Left visible (1)" in tp.read_text()


def test_export_refuses_to_overwrite_source(video):
    info = probe(str(video))
    p = Project(video_path=str(video), width=info.width, height=info.height, fps=info.fps, frame_count=N)
    with pytest.raises(ValueError):
        export(p, str(video))
