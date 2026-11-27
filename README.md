# SARBlur

**Free, offline face blurring for CCTV Subject Access Requests.**

When someone makes a Subject Access Request (SAR) under UK GDPR for CCTV footage, the
footage usually has to be released with everyone *except the requester* obscured.
SARBlur helps you do that on your own PC — no uploads, no cloud, no subscription.

> **Status:** v1 in testing. Not ready for real SARs yet: test it on your own footage first.

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

Run the tests with `.venv\Scripts\python -m pytest`.

## How it works

1. **Open** the video (File > Open, or drag it onto the window).
2. **Detect faces.** Every frame is checked and faces are linked into numbered boxes (tracks).
3. **Review.** Mark the requester's boxes *Keep visible* (green). They may have several if they
   leave the frame or turn away. Play the whole video with *Preview redaction* on. Drag on the
   picture to add a box for anyone who was missed. Drag a box, or its corner, to correct it at
   that frame. *Start here* and *End here* set how long a box lasts.
   Your review saves automatically next to the video (`<video>.sarblur.json`).
4. **Export.** This writes `<name>_redacted.mp4` and a redaction log. You must confirm you
   reviewed the whole video. The audio track is removed.

Keyboard: `Space` play/pause, `←`/`→` one frame, `Shift+←`/`→` one second, `K` keep, `R` redact,
`[`/`]` start/end here, `Del` delete box, `P` preview.

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
- Windows installer

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
