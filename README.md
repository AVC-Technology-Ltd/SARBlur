# SARBlur

**Free, offline face blurring for CCTV Subject Access Requests.**

When someone makes a Subject Access Request (SAR) under UK GDPR for CCTV footage, the
footage usually has to be released with everyone *except the requester* obscured.
SARBlur helps you do that on your own PC — no uploads, no cloud, no subscription.

> **Status:** early development. Not yet ready for use.

## Planned features (v1)

- **100% offline** — footage never leaves your machine
- Automatic face detection and tracking across frames
- Mark the requester once — they stay visible, everyone else is blurred
- Review timeline to add, remove and adjust blur boxes before export
  (no detector is perfect: a human review step is always required)
- Irreversible redaction (solid fill / heavy pixelation), original file never modified
- Exports a redacted MP4 plus a redaction log for your SAR records
- Input: MP4, AVI, MKV (export from your DVR/NVR software first)

## Later

- Number plate and screen/document redaction
- Audio muting
- Batch processing

## Support the project

SARBlur is free. If it saves you time or money, donations to support development will be
welcome — details coming soon.

## Licence

SARBlur is open source under the [Apache License 2.0](LICENSE).
Copyright 2026 AVC Technology Ltd.

SARBlur is a tool to assist redaction; it is provided "as is", without warranty.
You remain responsible for reviewing every export before releasing footage.

---

Published by **AVC Technology Ltd**.
