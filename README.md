# SARBlur

**Free, offline face blurring for CCTV Subject Access Requests.**

When someone makes a Subject Access Request (SAR) under UK GDPR for CCTV footage, the
footage usually has to be released with everyone *except the requester* obscured.
SARBlur helps you do that on your own PC — no uploads, no cloud, no subscription.

> **Status:** 1.0.0 beta. Test it on your own footage before using it for a real SAR, and always
> watch the exported video through before releasing it.

## Download

Get the latest Windows build from the
[Releases page](https://github.com/AVC-Technology-Ltd/SARBlur/releases). Extract the zip and run
`SARBlur.exe`; nothing is installed. Windows 10 or 11, 64-bit.

The beta is not yet code-signed, so Windows may say "Windows protected your PC". Click
**More info → Run anyway**.

## Features (v1)

- **100% offline** — footage never leaves your machine
- Automatic face detection (YuNet) and tracking across frames
- Mark the requester's boxes *Keep visible*: they stay visible, everyone else is obscured
- Review timeline to add, remove and adjust boxes before export
  (no detector is perfect: a human review step is always required)
- Irreversible redaction (solid fill / heavy pixelation), original file never modified
- Exports a redacted H.264 MP4 plus a redaction log (.txt and .json, with SHA-256 hashes)
- Input: MP4, AVI, MKV, MOV (export from your DVR/NVR software first)

## Running from source (Windows)

Requires Python 3.11 or newer.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m sarblur
```

Run the tests with `.venv\Scripts\python -m pytest`. Check a build end to end with
`python -m sarblur --self-test`.

Releases are built by [`.github/workflows/release.yml`](.github/workflows/release.yml) when a
`v*` tag is pushed. It compiles a minimal LGPL FFmpeg from source, packages the app with
PyInstaller, self-tests it, and creates a draft release.

## How it works

The four buttons down the right-hand side are the four steps:

1. **Open video:** pick the footage, or drag it onto the window.
2. **Detect faces:** every frame is checked and faces are linked into numbered boxes.
3. **Keep visible:** click one of the requester's boxes on the video, then press this button so it
   turns green. The requester may have several boxes if they leave the frame or turn away. Press
   it again to redact a box again. Then play the whole video with *Preview redaction* on. If
   anyone is visible, drag on the picture to add a box. Drag a box, or its corner, to correct it
   at that frame. Your review saves automatically next to the video (`<video>.sarblur.json`).
4. **Export:** writes `<name>_redacted.mp4` and a redaction log (`.txt` and `.json`) with SHA-256
   hashes of the original and the redacted copy. You must confirm you reviewed the whole video.
   The audio track is removed.

Keyboard: `Space` play/pause, `←`/`→` one frame, `Shift+←`/`→` one second, `K` keep, `R` redact,
`[`/`]` box starts/ends at this frame, `Del` delete box, `P` preview.

## Known limitations (v1)

- Detection finds **faces**. Someone seen only from behind, or too small or blurred for the
  detector, will not get a box, so the manual review step matters.
- Output is re-encoded at a constant frame rate. Footage with a variable frame rate may drift
  slightly in time against the original.
- No undo yet. The review is saved continuously, so nothing is lost on a crash.

## Later

- Number plate and screen/document redaction
- Keeping audio with selective muting
- Batch processing
- Windows installer and code signing
- Undo

## Support the project

SARBlur is free. If it saves you time or money, donations to support development will be
welcome — details coming soon.

## Licence

SARBlur is open source under the [Apache License 2.0](LICENSE). Third-party components are
listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
Copyright 2026 AVC Technology Ltd.

SARBlur is a tool to assist redaction; it is provided "as is", without warranty.
You remain responsible for reviewing every export before releasing footage.

---

Published by **AVC Technology Ltd**.
