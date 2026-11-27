**First public beta of SARBlur** — free, offline face redaction for CCTV Subject Access Requests.

> **Beta:** test SARBlur on your own footage before using it for a real SAR, and always watch the
> exported video through before releasing it.

### Download and run (Windows 10/11, 64-bit)

1. Download `SARBlur-1.0.0-beta-windows-x64.zip` below.
2. Right-click the zip → **Extract All**.
3. Open the extracted `SARBlur` folder and run **SARBlur.exe**.

Windows may show "Windows protected your PC" because this beta is not yet code-signed.
Click **More info → Run anyway**. Nothing is installed and nothing is uploaded. Delete the
folder to remove it.

### What it does

- Detects and tracks faces in MP4, AVI, MKV and MOV footage, entirely on your PC
- Mark the requester's boxes **Keep visible**; everyone else is pixelated or blacked out
- Review with a preview, and add, move or resize boxes by hand
- Exports a redacted H.264 MP4 (audio removed) plus a redaction log with SHA-256 hashes
- The original footage is never modified

### Known limitations

- Detects **faces** only. People seen from behind or too small for the detector need boxes added by hand.
- Output is re-encoded at a constant frame rate.
- No undo yet (your review is saved continuously).

### Licences

SARBlur is Apache 2.0, © 2026 AVC Technology Ltd. The bundled FFmpeg is a minimal
LGPL build compiled from the official source. That source (`ffmpeg-*.tar.xz`) and the exact build
configuration (`FFMPEG-BUILD.txt`) are attached below. See `THIRD_PARTY_NOTICES.md` in the download
for all components.
