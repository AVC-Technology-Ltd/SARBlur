# Third-party components

SARBlur is licensed under the Apache License 2.0. It uses the following components,
which keep their own licences. Licence texts are in the `licenses` folder of the Windows download.

| Component | Use | Licence |
|---|---|---|
| [YuNet face detector](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (`face_detection_yunet_2023mar.onnx`) | Face detection model | MIT (`LICENSE-YuNet.txt`) |
| [OpenCV](https://opencv.org/) (`opencv-python`) | Video decoding, image processing, running the model | Apache 2.0 |
| FFmpeg libraries inside OpenCV (`opencv_videoio_ffmpeg*.dll`) | Reading video files | LGPL v2.1+. Built and distributed by the OpenCV project as part of `opencv-python` (see `opencv-python-LICENSE-3RD-PARTY.txt`); build scripts and source: <https://github.com/opencv/opencv_3rdparty> (ffmpeg branches) and <https://ffmpeg.org> |
| [Qt for Python / PySide6](https://www.qt.io/qt-for-python) | User interface | LGPL v3. The Qt DLLs in the `_internal\PySide6` folder are separate files and can be replaced. Source: <https://download.qt.io/official_releases/QtForPython/> |
| [FFmpeg](https://ffmpeg.org/) (`_internal\ffmpeg\ffmpeg.exe`) | Writing the redacted MP4 (Windows' own H.264 encoder via Media Foundation, or MPEG-4) | LGPL v2.1 or later. A minimal build with no GPL or non-free parts, compiled by our release workflow (`.github/workflows/release.yml`) from the official source tarball. That exact source and the build configuration (`FFMPEG-BUILD.txt`) are attached to each GitHub release. |
| [NumPy](https://numpy.org/) | Image arrays | BSD 3-Clause |
| [Python](https://www.python.org/) | Runtime | PSF License |

When running from source, the optional `imageio-ffmpeg` development dependency downloads its
own (GPL) FFmpeg build. That build is **not** part of SARBlur releases.

H.264 encoding uses the encoder that ships with Windows, so no H.264 encoder is distributed
with SARBlur. On Windows "N" editions without the Media Feature Pack, SARBlur exports MPEG-4
video instead.
