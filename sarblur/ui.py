"""SARBlur desktop UI (PySide6): open footage, detect faces, review, export."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, QSettings, QSize, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QImage, QKeySequence,
                           QPainter, QPen, QShortcut)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressDialog,
                               QPushButton, QSizePolicy, QSlider, QStyle,
                               QVBoxLayout, QWidget)

from sarblur import APP_NAME, PUBLISHER, __version__, redact
from sarblur.analysis import Cancelled, analyse
from sarblur.export import export, log_paths
from sarblur.project import Project, pad_box, unpad_rect
from sarblur.video import FrameReader, probe

VIDEO_FILTER = "Video files (*.mp4 *.avi *.mkv *.mov *.m4v *.wmv *.ts);;All files (*)"
RED = QColor(230, 57, 70)
GREEN = QColor(46, 196, 113)
YELLOW = QColor(255, 209, 64)


def timecode(frame: int, fps: float) -> str:
    s = frame / (fps or 25)
    return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}.{int(s * 1000) % 1000:03d}"


def to_qimage(bgr: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


# --------------------------------------------------------------------------- workers
class Worker(QThread):
    progress = Signal(int, int)
    failed = Signal(str)
    succeeded = Signal(object)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn, self._args, self._kwargs = fn, args, kwargs
        self.cancel_requested = False

    def run(self):
        try:
            result = self._fn(*self._args, progress=lambda a, b: self.progress.emit(a, b),
                              cancelled=lambda: self.cancel_requested, **self._kwargs)
        except Cancelled:
            self.failed.emit("")
        except Exception as e:  # surfaced to the user
            self.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.succeeded.emit(result)


# --------------------------------------------------------------------------- video view
class VideoView(QWidget):
    """Shows the current frame with redaction boxes; click to select, drag to add/move/resize."""

    selected = Signal(int)          # track id, -1 for none
    boxDrawn = Signal(tuple)        # padded rect (x0, y0, x1, y1) in source pixels
    boxEdited = Signal(int, tuple)  # track id, padded rect

    HANDLE = 10

    def __init__(self):
        super().__init__()
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self.image: QImage | None = None
        self.project: Project | None = None
        self.frame = 0
        self.selected_id = -1
        self.show_boxes = True
        self._drag = None  # (mode, track_id, start_src_point, original_rect)
        self._temp: tuple | None = None

    # geometry ------------------------------------------------------------
    def _target(self) -> QRectF:
        if not self.image:
            return QRectF()
        iw, ih = self.image.width(), self.image.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_src(self, p: QPointF) -> QPointF:
        t = self._target()
        s = self.image.width() / t.width()
        return QPointF((p.x() - t.x()) * s, (p.y() - t.y()) * s)

    def _to_widget(self, r) -> QRectF:
        t = self._target()
        s = t.width() / self.image.width()
        x0, y0, x1, y1 = r
        return QRectF(t.x() + x0 * s, t.y() + y0 * s, (x1 - x0) * s, (y1 - y0) * s)

    def _rects(self):
        if not self.project:
            return []
        p = self.project
        out = []
        for t, b in p.boxes_at(self.frame):
            r = pad_box(b, p.padding, p.width, p.height)
            if self._drag and self._drag[1] == t.id and self._temp:
                r = self._temp
            out.append((t, r))
        return out

    # painting ------------------------------------------------------------
    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(18, 18, 20))
        if not self.image:
            p.setPen(QColor(150, 150, 160))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       "Open a CCTV video to begin  (File > Open video, or drag a file here)")
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawImage(self._target(), self.image)
        if not self.show_boxes:
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setBold(True)
        p.setFont(font)
        for t, r in self._rects():
            wr = self._to_widget(r)
            sel = t.id == self.selected_id
            colour = YELLOW if sel else (RED if t.redact else GREEN)
            p.setPen(QPen(colour, 3 if sel else 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(wr)
            label = f"#{t.id}" + ("" if t.redact else " KEEP")
            p.fillRect(QRectF(wr.x(), wr.y() - 18, p.fontMetrics().horizontalAdvance(label) + 8, 18), colour)
            p.setPen(QColor(0, 0, 0))
            p.drawText(QPointF(wr.x() + 4, wr.y() - 5), label)
            if sel:
                p.fillRect(QRectF(wr.right() - self.HANDLE, wr.bottom() - self.HANDLE,
                                  self.HANDLE, self.HANDLE), colour)
        if self._drag and self._drag[0] == "draw" and self._temp:
            p.setPen(QPen(YELLOW, 2, Qt.PenStyle.DashLine))
            p.drawRect(self._to_widget(self._temp))

    # mouse ----------------------------------------------------------------
    def mousePressEvent(self, e):
        if not self.image or e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position()
        src = self._to_src(pos)
        hits = []
        for t, r in self._rects():
            wr = self._to_widget(r)
            if wr.adjusted(-4, -4, 4, 4).contains(pos):
                hits.append((t.id == self.selected_id, -(wr.width() * wr.height()), t, r, wr))
        if hits:
            hits.sort(key=lambda h: (h[0], h[1]), reverse=True)  # selected first, then smallest
            _, _, t, r, wr = hits[0]
            near_corner = (abs(pos.x() - wr.right()) < self.HANDLE * 1.5 and
                           abs(pos.y() - wr.bottom()) < self.HANDLE * 1.5)
            mode = "resize" if (near_corner and t.id == self.selected_id) else "move"
            if t.id != self.selected_id:
                self.selected_id = t.id
                self.selected.emit(t.id)
            self._drag = (mode, t.id, src, r)
        else:
            if self.selected_id != -1:
                self.selected_id = -1
                self.selected.emit(-1)
            self._drag = ("draw", -1, src, None)
        self._temp = None
        self.update()

    def mouseMoveEvent(self, e):
        if not self._drag or not self.project:
            return
        mode, _, start, orig = self._drag
        cur = self._to_src(e.position())
        W, H = self.project.width, self.project.height
        if mode == "draw":
            x0, x1 = sorted((start.x(), cur.x()))
            y0, y1 = sorted((start.y(), cur.y()))
            self._temp = (max(0, x0), max(0, y0), min(W, x1), min(H, y1))
        else:
            dx, dy = cur.x() - start.x(), cur.y() - start.y()
            x0, y0, x1, y1 = orig
            if mode == "move":
                self._temp = (x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            else:
                self._temp = (x0, y0, max(x0 + 8, x1 + dx), max(y0 + 8, y1 + dy))
        self.update()

    def mouseReleaseEvent(self, e):
        if not self._drag:
            return
        mode, tid, _, _ = self._drag
        temp = self._temp
        self._drag, self._temp = None, None
        if temp:
            x0, y0, x1, y1 = temp
            if mode == "draw":
                if (x1 - x0) >= 6 and (y1 - y0) >= 6:
                    self.boxDrawn.emit(temp)
            else:
                self.boxEdited.emit(tid, temp)
        self.update()


# --------------------------------------------------------------------------- timeline
class Timeline(QWidget):
    """Strip under the video: where redaction boxes exist, the selected track, the playhead."""

    seek = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        self.project: Project | None = None
        self.frame = 0
        self.selected_id = -1
        self._cache: tuple | None = None

    def invalidate(self):
        self._cache = None
        self.update()

    def _coverage(self, width: int):
        key = (width, id(self.project), len(self.project.tracks) if self.project else 0)
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        n = max(1, self.project.frame_count)
        red = np.zeros(width, bool)
        green = np.zeros(width, bool)
        for t in self.project.tracks:
            a = int(t.start / n * width)
            b = max(a + 1, int((t.end + 1) / n * width))
            (red if t.redact else green)[a:b] = True
        self._cache = (key, (red, green))
        return red, green

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 40, 46))
        if not self.project:
            return
        w, h = self.width(), self.height()
        red, green = self._coverage(w)
        for x in np.flatnonzero(red):
            p.fillRect(int(x), 4, 1, h // 2 - 5, RED)
        for x in np.flatnonzero(green):
            p.fillRect(int(x), h // 2 + 1, 1, h // 2 - 5, GREEN)
        n = max(1, self.project.frame_count)
        t = self.project.track(self.selected_id) if self.selected_id != -1 else None
        if t:
            a, b = t.start / n * w, (t.end + 1) / n * w
            p.setPen(QPen(YELLOW, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(a, 2, max(2, b - a), h - 4))
        x = self.frame / n * w
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))

    def _seek(self, e):
        if self.project:
            n = self.project.frame_count
            self.seek.emit(int(min(n - 1, max(0, e.position().x() / self.width() * n))))

    def mousePressEvent(self, e):
        self._seek(e)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self._seek(e)

    def resizeEvent(self, e):
        self.invalidate()


# --------------------------------------------------------------------------- dialogs
class AnalyseDialog(QDialog):
    def __init__(self, parent, has_auto: bool):
        super().__init__(parent)
        self.setWindowTitle("Detect faces")
        form = QFormLayout(self)
        self.sensitivity = QComboBox()
        self.sensitivity.addItem("High - catch more faces, more false boxes", 0.5)
        self.sensitivity.addItem("Normal", 0.6)
        self.sensitivity.addItem("Low - fewer false boxes, may miss faces", 0.75)
        self.sensitivity.setCurrentIndex(1)
        self.stride = QComboBox()
        self.stride.addItem("Every frame (most thorough)", 1)
        self.stride.addItem("Every 2nd frame (faster)", 2)
        self.stride.addItem("Every 3rd frame (fastest)", 3)
        form.addRow("Sensitivity:", self.sensitivity)
        form.addRow("Check:", self.stride)
        if has_auto:
            warn = QLabel("Running detection again replaces all automatically detected boxes, "
                          "including any you marked as the requester. Boxes you added by hand are kept.")
            warn.setWordWrap(True)
            warn.setStyleSheet("color: #e0a030")
            form.addRow(warn)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)


class ExportDialog(QDialog):
    def __init__(self, parent, project: Project, settings: QSettings):
        super().__init__(parent)
        self.setWindowTitle("Export redacted video")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        src = Path(project.video_path)
        default = src.with_name(f"{src.stem}_redacted.mp4")
        self.path = QLineEdit(str(default))
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        form.addRow("Save as:", row)
        self.style = QComboBox()
        self.style.addItem("Pixelate (heavy)", "pixelate")
        self.style.addItem("Solid black box", "solid")
        self.style.setCurrentIndex(0 if project.style == "pixelate" else 1)
        form.addRow("Redaction:", self.style)
        self.operator = QLineEdit(settings.value("operator", ""))
        form.addRow("Your name:", self.operator)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("e.g. SAR-2026-014")
        form.addRow("SAR reference:", self.reference)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Optional notes for the redaction log")
        self.notes.setFixedHeight(70)
        form.addRow("Notes:", self.notes)
        self.reviewed = QCheckBox("I have watched the whole video and checked every person "
                                  "other than the requester is obscured.")
        self.reviewed.setStyleSheet("font-weight: bold")
        form.addRow(self.reviewed)
        note = QLabel("The audio track is removed. The original file is not modified. "
                      "A redaction log (.txt and .json) is saved next to the video.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")
        form.addRow(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self.reviewed.toggled.connect(self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save redacted video", self.path.text(), "MP4 video (*.mp4)")
        if path:
            self.path.setText(path)


# --------------------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(PUBLISHER, APP_NAME)
        self.project: Project | None = None
        self.reader: FrameReader | None = None
        self.frame = 0
        self.raw: np.ndarray | None = None
        self.preview = False
        self.worker: Worker | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(1280, 800)
        self.setAcceptDrops(True)

        self.view = VideoView()
        self.view.selected.connect(self._select_track)
        self.view.boxDrawn.connect(self._add_manual)
        self.view.boxEdited.connect(self._edit_box)
        self.timeline = Timeline()
        self.timeline.seek.connect(self.seek)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._slider_moved)
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self.toggle_play)
        self.time_label = QLabel("--:--:--")
        self.time_label.setMinimumWidth(230)
        self.preview_box = QCheckBox("Preview redaction")
        self.preview_box.toggled.connect(self._toggle_preview)
        self.preview_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        transport = QHBoxLayout()
        for w in (self.play_btn, self._btn("< Frame", lambda: self.step(-1)),
                  self._btn("Frame >", lambda: self.step(1))):
            transport.addWidget(w)
        transport.addWidget(self.time_label)
        transport.addStretch(1)
        transport.addWidget(self.preview_box)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.view, 1)
        lv.addWidget(self.timeline)
        lv.addWidget(self.slider)
        lv.addLayout(transport)

        # side panel: stacked buttons acting on the box selected in the video
        self.keep_btn = self._btn("Keep visible (requester)  [K]", lambda: self._set_redact(False))
        self.blur_btn = self._btn("Redact  [R]", lambda: self._set_redact(True))
        self.start_btn = self._btn("Start here  [", self._set_start)
        self.end_btn = self._btn("End here  ]", self._set_end)
        self.del_btn = self._btn("Delete box  [Del]", self._delete_track)
        self.jump_btn = self._btn("Go to start", self._jump_to_track)
        help_text = QLabel(
            "<b>How to review</b><br>"
            "1. Find the requester and mark each of their boxes <b>Keep visible</b> (green). "
            "They may have several boxes if they leave the frame or turn away.<br>"
            "2. Play through the whole video with <b>Preview redaction</b> on.<br>"
            "3. If anyone is visible, <b>drag on the video</b> to add a box. "
            "Drag a box to move it, or its corner to resize - that fixes it at this frame.<br>"
            "4. Use <b>Start here / End here</b> to set how long a box lasts.")
        help_text.setWordWrap(True)
        help_text.setStyleSheet("color: #444; padding: 4px")
        side = QWidget()
        side.setFixedWidth(270)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(6, 0, 0, 0)
        sv.setSpacing(6)
        self.count_label = QLabel("No video open")
        self.count_label.setWordWrap(True)
        self.selection_label = QLabel()
        self.selection_label.setWordWrap(True)
        self.selection_label.setMinimumHeight(44)
        self.selection_label.setStyleSheet("background: #e6e9ee; border-radius: 4px; padding: 6px")
        sv.addWidget(self.count_label)
        sv.addWidget(self.selection_label)
        for b in (self.keep_btn, self.blur_btn, self.start_btn, self.end_btn, self.jump_btn, self.del_btn):
            b.setMinimumHeight(32)
            sv.addWidget(b)
        sv.addSpacing(8)
        sv.addWidget(help_text)
        sv.addStretch(1)

        central = QWidget()
        ch = QHBoxLayout(central)
        ch.setContentsMargins(0, 0, 6, 0)
        ch.addWidget(left, 1)
        ch.addWidget(side)
        self.setCentralWidget(central)

        self._build_menus()
        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._tick)
        self.autosave = QTimer(self)
        self.autosave.setSingleShot(True)
        self.autosave.setInterval(1500)
        self.autosave.timeout.connect(self.save_project)
        self._shortcuts()
        self._update_enabled()
        self.statusBar().showMessage("Everything runs on this PC. Footage is never uploaded.")

    # -- construction helpers ------------------------------------------------------
    def _btn(self, text, slot):
        b = QPushButton(text)
        b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        b.clicked.connect(slot)
        return b

    def _build_menus(self):
        m = self.menuBar().addMenu("&File")
        self.open_act = QAction("&Open video...", self, shortcut=QKeySequence.StandardKey.Open, triggered=self.open_dialog)
        self.save_act = QAction("&Save review", self, shortcut=QKeySequence.StandardKey.Save, triggered=self.save_project)
        self.export_act = QAction("&Export redacted video...", self, shortcut="Ctrl+E", triggered=self.export_dialog)
        quit_act = QAction("E&xit", self, triggered=self.close)
        for a in (self.open_act, self.save_act, self.export_act):
            m.addAction(a)
        m.addSeparator()
        m.addAction(quit_act)
        v = self.menuBar().addMenu("&Video")
        self.analyse_act = QAction("&Detect faces...", self, shortcut="Ctrl+D", triggered=self.analyse_dialog)
        v.addAction(self.analyse_act)
        h = self.menuBar().addMenu("&Help")
        h.addAction(QAction("&About SARBlur", self, triggered=self.about))
        tb = self.addToolBar("Main")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setIconSize(QSize(20, 20))
        tb.setStyleSheet("""
            QToolBar { spacing: 8px; padding: 6px; border: none; }
            QToolButton {
                font-size: 14px; font-weight: bold; color: white;
                background: #3a5f8f; border: 1px solid #2c4a70; border-radius: 6px;
                padding: 7px 16px;
            }
            QToolButton:hover { background: #4a74ab; }
            QToolButton:pressed { background: #2c4a70; }
            QToolButton:disabled { background: #9aa3ad; border-color: #8a929b; color: #e8e8e8; }
            QToolButton#export { background: #2e8b57; border-color: #236b43; }
            QToolButton#export:hover { background: #38a869; }
            QToolButton#export:pressed { background: #236b43; }
            QToolButton#export:disabled { background: #9aa3ad; border-color: #8a929b; }
        """)
        style = self.style()
        icons = {self.open_act: QStyle.StandardPixmap.SP_DialogOpenButton,
                 self.analyse_act: QStyle.StandardPixmap.SP_FileDialogContentsView,
                 self.export_act: QStyle.StandardPixmap.SP_DialogSaveButton}
        labels = {self.open_act: "1. Open video", self.analyse_act: "2. Detect faces",
                  self.export_act: "3. Export redacted video"}
        for act in (self.open_act, self.analyse_act, self.export_act):
            act.setIcon(style.standardIcon(icons[act]))
            act.setIconText(labels[act])  # toolbar label; menus keep the action's own text
            tb.addAction(act)
            btn = tb.widgetForAction(act)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(f"{act.text().replace('&', '').rstrip('.')} ({act.shortcut().toString()})")
        tb.widgetForAction(self.export_act).setObjectName("export")

    def _shortcuts(self):
        keys = {
            "Space": self.toggle_play, "Left": lambda: self.step(-1), "Right": lambda: self.step(1),
            "Shift+Left": lambda: self.step(-round(self._fps())), "Shift+Right": lambda: self.step(round(self._fps())),
            "K": lambda: self._set_redact(False), "R": lambda: self._set_redact(True),
            "Delete": self._delete_track, "[": self._set_start, "]": self._set_end,
            "P": lambda: self.preview_box.toggle(),
        }
        for k, fn in keys.items():
            s = QShortcut(QKeySequence(k), self)
            s.activated.connect(fn)

    def _fps(self) -> float:
        return self.project.fps if self.project else 25.0

    def _update_enabled(self):
        has = self.project is not None
        for a in (self.save_act, self.export_act, self.analyse_act):
            a.setEnabled(has)
        sel = self._selected() is not None
        for b in (self.keep_btn, self.blur_btn, self.start_btn, self.end_btn, self.del_btn, self.jump_btn):
            b.setEnabled(sel)
        self.play_btn.setEnabled(has)

    # -- opening ---------------------------------------------------------------------
    def open_dialog(self):
        start = self.settings.value("last_dir", str(Path.home()))
        path, _ = QFileDialog.getOpenFileName(self, "Open CCTV video", start, VIDEO_FILTER)
        if path:
            self.open_video(path)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.open_video(urls[0].toLocalFile())

    def open_video(self, path: str, ask_resume: bool = True):
        self.stop()
        if self.project:
            self.save_project()
        try:
            info = probe(path)
        except Exception as ex:
            QMessageBox.critical(self, APP_NAME, f"Could not open this video.\n\n{ex}\n\n"
                                 "If it came from a DVR/NVR in its own format, export it to MP4 or AVI "
                                 "with the recorder's software first.")
            return
        size = os.path.getsize(path)
        project = None
        sidecar = Project.sidecar_path(path)
        if sidecar.exists():
            try:
                saved = Project.load(sidecar)
                if (saved.video_size == size and saved.width == info.width and saved.height == info.height):
                    if not ask_resume or QMessageBox.question(
                            self, APP_NAME, "A saved review of this video was found. Carry on from where you left off?"
                    ) == QMessageBox.StandardButton.Yes:
                        project = saved
                        project.video_path = path
            except Exception:
                pass
        if project is None:
            project = Project(video_path=path, width=info.width, height=info.height,
                              fps=info.fps, frame_count=info.frame_count, video_size=size)
        if self.reader:
            self.reader.close()
        self.reader = FrameReader(path)
        self.project = project
        self.view.project = self.timeline.project = project
        self.settings.setValue("last_dir", str(Path(path).parent))
        self.setWindowTitle(f"{Path(path).name} - {APP_NAME}")
        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, project.frame_count - 1))
        self.slider.blockSignals(False)
        self._refresh_panel()
        self.timeline.invalidate()
        self.seek(0)
        self._update_enabled()
        if not project.analysed:
            self.statusBar().showMessage("Video opened. Click '2. Detect faces' when you're ready.")

    # -- frames ----------------------------------------------------------------------
    def seek(self, frame: int):
        if not self.project:
            return
        frame = max(0, min(self.project.frame_count - 1, frame))
        img = self.reader.read(frame)
        if img is None:
            if self.play_timer.isActive():
                self.stop()
            return
        self.frame, self.raw = frame, img
        self.slider.blockSignals(True)
        self.slider.setValue(frame)
        self.slider.blockSignals(False)
        self._render()

    def _render(self):
        if self.raw is None:
            return
        img = self.raw
        if self.preview:
            img = redact.apply(img.copy(), self.project.redaction_rects(self.frame), self.project.style)
        self.view.image = to_qimage(img)
        self.view.frame = self.timeline.frame = self.frame
        self.view.update()
        self.timeline.update()
        n = len(self.project.boxes_at(self.frame))
        self.time_label.setText(f"{timecode(self.frame, self.project.fps)}   frame {self.frame + 1}/"
                                f"{self.project.frame_count}   {n} box{'es' if n != 1 else ''}")

    def _slider_moved(self, v):
        self.seek(v)

    def step(self, d: int):
        self.stop()
        self.seek(self.frame + d)

    def toggle_play(self):
        if not self.project:
            return
        if self.play_timer.isActive():
            self.stop()
        else:
            if self.frame >= self.project.frame_count - 1:
                self.seek(0)
            self.play_timer.start(max(1, int(1000 / self._fps())))
            self.play_btn.setText("Pause")

    def stop(self):
        self.play_timer.stop()
        self.play_btn.setText("Play")

    def _tick(self):
        if self.frame >= self.project.frame_count - 1:
            self.stop()
            return
        self.seek(self.frame + 1)

    def _toggle_preview(self, on):
        self.preview = on
        self.view.show_boxes = not on
        self._render()

    # -- tracks ----------------------------------------------------------------------
    def _selected(self):
        if not self.project or self.view.selected_id == -1:
            return None
        return self.project.track(self.view.selected_id)

    def _refresh_panel(self):
        p = self.project
        kept = sum(1 for t in p.tracks if not t.redact)
        status = "" if p.analysed else "\n(face detection not run yet)"
        self.count_label.setText(f"{len(p.tracks)} boxes: {len(p.tracks) - kept} redacted, "
                                 f"{kept} kept visible{status}")
        t = self._selected()
        if t:
            colour = "#c62832" if t.redact else "#1e8a4c"
            action = "Redacted" if t.redact else "Kept visible (requester)"
            found = "found by detector" if t.kind == "auto" else "added by you"
            self.selection_label.setText(
                f"<b>Box #{t.id}</b> - <span style='color:{colour}'><b>{action}</b></span><br>"
                f"{timecode(t.start, p.fps)[:-4]} to {timecode(t.end, p.fps)[:-4]}, {found}")
        else:
            self.selection_label.setText("Click a box on the video to select it.")
        self.timeline.invalidate()

    def _changed(self, refresh_panel=True):
        if refresh_panel:
            self._refresh_panel()
        self.timeline.invalidate()
        self._render()
        self._update_enabled()
        self.autosave.start()

    def _select_track(self, track_id: int):
        self.view.selected_id = self.timeline.selected_id = track_id
        if self.project:
            self._refresh_panel()
        self.view.update()
        self.timeline.update()
        self._update_enabled()

    def _jump_to_track(self):
        t = self._selected()
        if t:
            self.stop()
            self.seek(t.start)

    def _set_redact(self, value: bool):
        t = self._selected()
        if t:
            t.redact = value
            self._changed()

    def _set_start(self):
        t = self._selected()
        if t and self.frame <= t.end:
            t.start = self.frame  # the earliest keyframe box is held back to here
            self._changed()

    def _set_end(self):
        t = self._selected()
        if t and self.frame >= t.start:
            t.end = self.frame
            self._changed()

    def _delete_track(self):
        t = self._selected()
        if not t:
            return
        if t.kind == "auto" and QMessageBox.question(
                self, APP_NAME, f"Delete box #{t.id}? Only do this if it is not a person "
                                "(for example a poster or a reflection).") != QMessageBox.StandardButton.Yes:
            return
        self.project.delete(t.id)
        self._select_track(-1)
        self._changed()

    def _add_manual(self, rect):
        p = self.project
        box = unpad_rect(*rect, p.padding)
        t = p.add_manual(self.frame, box, hold_frames=round(p.fps * 2))
        self._select_track(t.id)
        self._changed()
        self.statusBar().showMessage(f"Added box #{t.id} for 2 seconds. Use 'End here' to change how long it lasts.", 6000)

    def _edit_box(self, track_id: int, rect):
        t = self.project.track(track_id)
        if t:
            t.set_box(self.frame, unpad_rect(*rect, self.project.padding))
            self._changed(refresh_panel=False)

    # -- analysis ---------------------------------------------------------------------
    def analyse_dialog(self):
        if not self.project or self.worker:
            return
        dlg = AnalyseDialog(self, any(t.kind == "auto" for t in self.project.tracks))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.stop()
        self._run(analyse, "Detecting faces...", self._analysis_done, self.project,
                  stride=dlg.stride.currentData(), score_threshold=dlg.sensitivity.currentData())

    def _analysis_done(self, _):
        p = self.project
        self.slider.setRange(0, max(0, p.frame_count - 1))
        self._select_track(-1)
        self._changed()
        self.save_project()
        n = sum(1 for t in p.tracks if t.kind == "auto")
        QMessageBox.information(self, APP_NAME,
                                f"Found {n} face track{'s' if n != 1 else ''}.\n\n"
                                "Next: mark the requester's boxes as 'Keep visible', then play the whole video "
                                "with 'Preview redaction' on and add boxes for anyone the detector missed.")

    # -- export -----------------------------------------------------------------------
    def export_dialog(self):
        if not self.project or self.worker:
            return
        self.stop()
        if not self.project.analysed and QMessageBox.question(
                self, APP_NAME, "Face detection has not been run on this video. Export anyway?"
        ) != QMessageBox.StandardButton.Yes:
            return
        if all(t.redact for t in self.project.tracks) and self.project.tracks:
            if QMessageBox.question(self, APP_NAME, "No boxes are marked 'Keep visible', so the requester will "
                                    "also be obscured. Continue?") != QMessageBox.StandardButton.Yes:
                return
        dlg = ExportDialog(self, self.project, self.settings)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        out = dlg.path.text().strip()
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        if Path(out).resolve() == Path(self.project.video_path).resolve():
            QMessageBox.warning(self, APP_NAME, "Choose a different file name - the original footage must not be overwritten.")
            return
        if Path(out).exists() and QMessageBox.question(
                self, APP_NAME, f"{Path(out).name} already exists. Replace it?") != QMessageBox.StandardButton.Yes:
            return
        self.settings.setValue("operator", dlg.operator.text())
        self.project.style = dlg.style.currentData()
        self._render()
        self.save_project()
        self._run(export, "Exporting redacted video...", self._export_done, self.project, out,
                  operator=dlg.operator.text().strip(), reference=dlg.reference.text().strip(),
                  reviewed=dlg.reviewed.isChecked(), notes=dlg.notes.toPlainText().strip())

    def _export_done(self, log):
        out = log["output"]["file"]
        _, txt = log_paths(out)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(f"Export complete.\n\nVideo: {out}\nLog: {txt}\n\n"
                    "Watch the exported file through once more before releasing it.")
        open_btn = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(out).parent)))

    # -- background jobs --------------------------------------------------------------
    def _run(self, fn, label, on_done, *args, **kwargs):
        dlg = QProgressDialog(label, "Cancel", 0, 1000, self)
        dlg.setWindowTitle(APP_NAME)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        w = Worker(fn, *args, **kwargs)
        self.worker = w

        def progress(a, b):
            dlg.setValue(int(a / max(1, b) * 1000))
            dlg.setLabelText(f"{label}\n{a} of ~{b} frames")

        def finished_ok(result):
            dlg.close()
            self.worker = None
            on_done(result)

        def finished_err(msg):
            dlg.close()
            self.worker = None
            if msg:
                QMessageBox.critical(self, APP_NAME, msg)
            else:
                self.statusBar().showMessage("Cancelled.", 4000)
            self._changed()

        def cancel():
            w.cancel_requested = True
            dlg.setLabelText("Cancelling...")

        w.progress.connect(progress)
        w.succeeded.connect(finished_ok)
        w.failed.connect(finished_err)
        dlg.canceled.connect(cancel)
        dlg.show()
        w.start()

    # -- misc ------------------------------------------------------------------------
    def save_project(self):
        if not self.project:
            return
        try:
            path = self.project.save()
            self.statusBar().showMessage(f"Review saved to {path.name}", 3000)
        except OSError as e:
            self.statusBar().showMessage(f"Could not save review: {e}", 8000)

    def about(self):
        QMessageBox.about(self, f"About {APP_NAME}",
                          f"<h3>{APP_NAME} {__version__}</h3>"
                          "<p>Free, offline face redaction for CCTV Subject Access Requests.</p>"
                          f"<p>&copy; 2026 {PUBLISHER}. Apache License 2.0.</p>"
                          "<p>Face detection: YuNet (MIT licence). Built with OpenCV, Qt (PySide6) and FFmpeg.</p>"
                          "<p>SARBlur assists redaction; it is provided as is, without warranty. You remain "
                          "responsible for reviewing every export before releasing footage.</p>")

    def closeEvent(self, e):
        if self.worker:
            QMessageBox.information(self, APP_NAME, "Please wait for the current job to finish or cancel it first.")
            e.ignore()
            return
        self.stop()
        self.save_project()
        if self.reader:
            self.reader.close()
        e.accept()


def main(argv=None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(PUBLISHER)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    if len(argv) > 1 and Path(argv[1]).exists():
        w.open_video(argv[1])
    return app.exec()
