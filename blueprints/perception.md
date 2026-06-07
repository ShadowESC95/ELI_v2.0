# ELI Perception — Vision, Voice, OS Control

`eli/perception/` — 5.5k LOC, 18 files. ELI's senses and hands: local vision,
speech-to-text, text-to-speech, and OS control. All local, no APIs.

## Files

| File | LOC | Role |
|---|---|---|
| `audio_stt.py` | 1481 | speech-to-text + mic capture + output ducking |
| `tts_router.py` | 603 | multi-backend text-to-speech |
| `vision.py` | 491 | local VL inference (hot-swap + co-resident) |
| `os_controller.py` | 484 | screenshot / volume / keyboard / clipboard |
| `screen_locator.py` | 389 | locate UI elements on screen |
| `gaze_engine.py` | 290 | gaze tracking (off by default) |
| `log_rotation.py` | 215 | log housekeeping |
| `analyze_pdfs/image/mesh/csv.py` | ~600 | file-type analysers |
| `ambient_vision.py` | 207 | periodic screen glances (off by default) |
| `local_whisper_stt.py` | 176 | Whisper STT backend |
| `voice_worker(_streaming).py`, `eli_listen.py`, `extract_equations.py` | small | workers/helpers |

## Vision (`vision.py` + `ambient_vision.py` + `analyze_image.py`)

The working local-vision stack (see memory `eli-image-analysis`):
- VL model (default Qwen2.5-VL, configurable) loaded via
  `Qwen25VLChatHandler`; **CPU clip forced** by monkeypatching
  `mtmd_cpp.mtmd_init_from_file(use_gpu=False)` — the GPU mtmd clip path
  **segfaults** on compute-7.5 cards.
- **Hot-swap**: unload text model → load VL → infer → restore in `finally`,
  holding `gguf_inference._LLM_CALL_LOCK`.
- **Co-resident fast path**: a small model (Moondream2 Q4) loaded first, with the
  text model's ctx capped (`vision_coresident_text_ctx`) so both fit 8GB;
  `prefer_fast=True` uses it without a swap.
- Images downscaled to `vision_max_image_px` (1280) to avoid context overflow;
  `repeat_penalty`/`top_k`/`top_p` set to kill a repetition loop.
- `ambient_vision.py`: optional periodic screen glances (OFF by default). A
  guarded daemon re-reads the toggle/interval each cycle and **skips a glance
  whenever the shared LLM lock is busy** (so it never steals the model
  mid-reply). Stores a short description as memory for rolling awareness.

## Speech-to-text (`audio_stt.py`, `local_whisper_stt.py`)

A large, feature-dense STT module:
- Mic capture + Whisper transcription (`local_whisper_stt`).
- **Output ducking** — lowers system sink volume while listening
  (`_eli_duck_output`/`_eli_restore_output` via `wpctl`) so ELI doesn't hear
  itself.
- **Echo/self-hearing suppression** (`_eli_echo_like_assistant_output`,
  `_eli_media_probably_audible`).
- Transcript cleanup: `_cleanup`, `_collapse_repeated_phrase`,
  `_eli_fast_command_alias` (maps spoken phrases to commands),
  `_is_safe_direct`/`_allow_direct_chat` (gates which utterances bypass to chat).
- ALSA stderr suppression to keep the console clean.

## Text-to-speech (`tts_router.py`)

Multi-backend router with graceful fallback: **Piper** (packaged binary under
`tts_piper/` or `models/tts/piper`, voice-dir resolution) → **espeak-ng /
espeak**. Resolves voices from several candidate dirs so a packaged build or a
source checkout both work.

## OS control (`os_controller.py`)

**Platform-aware** (Linux/Windows/macOS) screenshot, volume, keyboard, clipboard.
`take_screenshot(region)` picks the right tool per platform
(`gnome-screenshot`, PIL `ImageGrab`, platform CLIs); fails gracefully where a
capability isn't available (e.g. area screenshots on some Windows installs).
`screen_locator.py` finds UI targets for click/automation.

## File analysers

`analyze_pdfs`, `analyze_image`, `analyze_csv`, `analyze_mesh`,
`extract_equations` — typed handlers behind the `ANALYZE_*` actions, feeding
extracted content (text/OCR/structure) into the grounded pipeline.

## Honest assessment

- **Strong:** this is the layer that makes ELI genuinely multimodal and local —
  eyes (VL + OCR + ambient), ears (Whisper + ducking), mouth (Piper/espeak),
  hands (cross-platform OS control). The vision co-residence + hot-swap + CPU-clip
  workaround is real engineering against hard 8GB-GPU constraints.
- **Weak / watch:**
  1. **Vision latency** — the hot-swap unloads/reloads the text model per glance;
     even the co-resident path runs CPU clip (~3.5s). Acceptable, not fast.
  2. `audio_stt.py` is a **1.48k-line** module mixing capture, ducking, echo
     suppression, command aliasing, and cleanup — wants splitting.
  3. **Residual "7B" comment** in `ambient_vision.py` ("the 7B vision model
     hot-swaps…") — cosmetic, but inconsistent with the model-agnostic line;
     should read "the vision model". (Flagged for a future scrub.)
  4. `gaze_engine.py` is experimental and off by default — fine, but it's carried
     weight.
  5. Platform tools are detected at call time; a machine missing
     `gnome-screenshot`/`wpctl`/`piper` degrades silently to fallbacks (good) but
     there's no single "what perception capabilities do I actually have here?"
     probe surfaced to the user.


---

## Update Advisory — 2026-06-01
- Unchanged this session. Still-open: the residual "7B" comment in `ambient_vision.py` should be scrubbed for model-agnostic consistency (see memory `eli-model-agnostic`).


---

## Update Advisory — 2026-06-07
- Unchanged this cycle (LOC drift only). TTS unspeakable-fragment guard and CPU-pinned vision CLIP remain in place.
