# Third-party components

SARBlur is licensed under the Apache License 2.0. It uses the following components,
which keep their own licences.

| Component | Use | Licence |
|---|---|---|
| [YuNet face detector](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) (`face_detection_yunet_2023mar.onnx`) | Face detection model, shipped in `sarblur/models/` | MIT, see `sarblur/models/LICENSE-YuNet.txt` |
| [OpenCV](https://opencv.org/) (`opencv-python`) | Video decoding, image processing, running the model | Apache 2.0 |
| [Qt for Python / PySide6](https://www.qt.io/qt-for-python) | User interface | LGPL v3 |
| [NumPy](https://numpy.org/) | Image arrays | BSD 3-Clause |
| [FFmpeg](https://ffmpeg.org/) via [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | H.264 encoding of the redacted video | imageio-ffmpeg: BSD 2-Clause. The bundled FFmpeg binary is a GPL v3 build (includes x264); it runs as a separate program. |

Before distributing a packaged build, the LGPL (Qt) and GPL (FFmpeg) obligations need to be
met: ship the licence texts, keep Qt as replaceable shared libraries, and offer the
corresponding FFmpeg source.
