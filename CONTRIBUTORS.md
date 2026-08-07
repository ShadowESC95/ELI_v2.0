# Contributors

The following individuals have contributed to ELI's development through code, testing, feedback, and community support.

## Code Contributors

- **Claude (Anthropic)** – diagnostic and remediation work via Claude Code, including
  in v2.1.52–v2.1.53:
  - YouTube playback verified before it is reported (a spawned-but-dead mpv was being
    announced as playing, and its stderr was discarded); playback is now claimed only
    once mpv confirms it opened the stream, so a slow yt-dlp failure cannot pass as
    success either
  - live-state actions (`NOW_PLAYING`, `*_STATUS`, `*_STATS`, `*_USAGE`) exempted from
    the low-grounding downgrade, so a state query is answered from the device instead
    of being re-routed to CHAT and guessed at
  - `mic_diag.py` restored to working order on SpeechRecognition 3.16
  - microphone no longer stays deaf when the room is loud: a mic drowned by speaker
    bleed is detected and the gate lifted above the noise, then walked back down once
    it is quiet, plus opt-in acoustic echo cancellation (`ELI_STT_ECHO_CANCEL=1`,
    measured to cut bleed from 17x to 4x) — the "noise cancellation in the launcher"
    that this file's comments had long credited was never actually implemented
  - speech dropped for want of a wake word is now recorded, instead of vanishing
    without trace and looking exactly like a broken microphone
  - the Windows setup wizard carries the ELI icon on every page rather than Inno's
    stock artwork, and the manuals carry it on their title page

## Non-Code Contributors

- **Node815** – Arch Linux testing, bug reports, and feedback. Their detailed logs helped fix cross-platform issues in v2.1.19–v2.1.23, including:
  - SQLite WAL fallback for NTFS/exFAT filesystems
  - Qt xcb library bundling in the AppImage
  - GPU detection for hybrid Intel+NVIDIA systems
  - Ollama selector improvements

---

*Note: This list recognizes both code and non-code contributors. All contributions are valued equally.*
