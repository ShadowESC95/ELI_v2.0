# Contributors

The following individuals have contributed to ELI's development through code, testing, feedback, and community support.

## Code Contributors

- **Claude (Anthropic)** – diagnostic and remediation work via Claude Code, including
  in v2.1.52:
  - YouTube playback verified before it is reported (a spawned-but-dead mpv was being
    announced as playing, and its stderr was discarded)
  - live-state actions (`NOW_PLAYING`, `*_STATUS`, `*_STATS`, `*_USAGE`) exempted from
    the low-grounding downgrade, so a state query is answered from the device instead
    of being re-routed to CHAT and guessed at
  - `mic_diag.py` restored to working order on SpeechRecognition 3.16

## Non-Code Contributors

- **Node815** – Arch Linux testing, bug reports, and feedback. Their detailed logs helped fix cross-platform issues in v2.1.19–v2.1.23, including:
  - SQLite WAL fallback for NTFS/exFAT filesystems
  - Qt xcb library bundling in the AppImage
  - GPU detection for hybrid Intel+NVIDIA systems
  - Ollama selector improvements

---

*Note: This list recognizes both code and non-code contributors. All contributions are valued equally.*
