# PyInstaller spec for the Windows release (one-folder build).
#
# One-folder (not one-file) on purpose: Qt stays as separate, replaceable DLLs
# as the LGPL requires, and the program starts faster.
#
# Build:  pyinstaller packaging/sarblur.spec
# The release workflow first places a minimal LGPL ffmpeg.exe in
# build/ffmpeg/ffmpeg.exe; without it the build has no FFmpeg and exports
# fall back to OpenCV's MPEG-4 writer.
import os
from pathlib import Path

root = Path(SPECPATH).parent
ffmpeg = root / "build" / "ffmpeg" / "ffmpeg.exe"

datas = [
    (str(root / "sarblur" / "models" / "face_detection_yunet_2023mar.onnx"), "sarblur/models"),
    (str(root / "sarblur" / "models" / "LICENSE-YuNet.txt"), "sarblur/models"),
]
binaries = [(str(ffmpeg), "ffmpeg")] if ffmpeg.exists() else []

a = Analysis(
    [str(root / "packaging" / "launch.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["imageio_ffmpeg", "tkinter", "matplotlib", "PySide6.QtWebEngineCore",
              "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf"],
    noarchive=False,
)
# Qt parts a widgets-only app never loads
_unused = ("opengl32sw.dll", "qt6qml", "qt6quick", "qt6pdf", "qt6virtualkeyboard", "qt6opengl.dll")
a.binaries = [b for b in a.binaries if not os.path.basename(b[0]).lower().startswith(_unused)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SARBlur",
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="SARBlur", upx=False)
