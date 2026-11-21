# Voice Creation / Cloning Engine — end-to-end (2026-07-28)

> **Updated for v2.5.36.** Character presets (ffmpeg) vs XTTS zero-shot cloning;
> see also `blueprints/perception.md` for mic auto-detect (v2.3.44+). The packaged app
> ships Piper only: cloning and natural voices need a source install with the neural extra.

How ELI turns a short audio/video clip of *any* voice — a character, an actor, a
friend — into a usable ELI voice. Covers the full path from a dropped-in file to
spoken output, the two distinct technologies involved, the dependency stack, and
the real defects found and fixed while verifying it end-to-end on this machine.

## The two voice technologies (don't confuse them)

ELI actually has **two** different ways to get a "character" voice (the packaged app ships the
first; the second needs a source install with the neural extra), and they trade off very
differently:

| | Character presets (`voice_fx.py`) | Voice cloning (`tts_xtts.py`) |
|---|---|---|
| Built-in styles | calm, robotic, energetic, synthetic, refined (and your own, from `DESIGN_VOICE`: a base voice + pitch/speed) | none — always from *your* clip |
| How it works | base Piper voice + an ffmpeg `-af` effect chain (pitch/speed/filters) | Coqui XTTS-v2 zero-shot cloning from a ~6–20s reference clip |
| Fidelity | an approximation / vibe | reproduces the actual voice characteristics |
| Cost | free, instant, always available | opt-in ~1.8GB neural model (source install), on CUDA when the installed torch has it |
| Covers characters with no preset (Cartman, Vader, …) | no | yes |

Cloning a reference clip **you have rights to use** will sound closer than a
built-in ffmpeg preset — presets exist so *something* is available with zero
extra install; cloning is the accurate path for a specific timbre.

## End-to-end flow

```
 user: "create a voice called vader from vader_clip.mp4"
   │        (or Settings ▸ Runtime ▸ "VOICE / TTS" ▸ drop-zone)
   ▼
 router_enhanced.py  (voice.create pattern, ~line 2644)
   regex: (voice|clone) + (creat|make|build|clone|generat|record)
        + a media extension OR "from/using/out of/with … recording/audio/clip/sample/file/voice"
          OR "my/this/the recording/audio/clip/sample/voice"
   extracts: name ("called/named/name it/as X") + file (a .wav/.mp3/.mp4/.m4a/.ogg/.flac/.aac/.webm path)
   ──► {action: CREATE_VOICE, args: {name, file}}
   ▼
 executor_enhanced.py  CREATE_VOICE handler (~line 11366)
   resolves ~ in the path, checks the file exists; no name → the file's own name
   ──► tts_xtts.add_clone(name, path)
   ▼
 tts_xtts.add_clone()                                    (offline, no TTS needed)
   ffmpeg -i <clip> -ac 1 -ar 22050 <ref.wav>   (mono/22.05kHz — any container, audio-only too;
                                                 without ffmpeg only a .wav is taken, as it is)
   registry write: <config dir>/voices/clones.json   { name: {ref_wav, language, desc} }
   reference clip stored:                             <models dir>/voice_profiles/<name>.wav
   ──► {ok: true, name, id: "clone:<name>", ref_wav, synth_ready: xtts_available()}
   ▼
 executor sets it active: tts_router.set_active_voice("clone:<name>")
   replies: "Created the voice '<name>' … set it active."
            (+ a note if the neural extra isn't installed yet)

 ── later, any time ELI speaks ──

 tts_router.synthesize_wav(text, voice)
   voice startswith "clone:" ──► tts_xtts.synthesize_wav(text, name)
       _patch_transformers_compat()            (see "Defects found" below)
       os.environ["COQUI_TOS_AGREED"] = "1"    (see "Defects found" below)
       _get_model()  lazy-loads XTTS-v2 once (~1.8GB, one-time download; cuda when this torch
                     build has CUDA, else cpu; ELI_XTTS_DEVICE=cpu keeps it on the processor)
       model.tts_to_file(text, speaker_wav=ref.wav, language, file_path=tmp.wav)
       ──► WAV bytes
   None returned at ANY step ──► caller falls back to the Piper default voice (en_US-amy-medium),
       logged once and shown in Settings ▸ Audio (never goes silent; CREATE_VOICE's own
       confirmation message says so up front)
```

## Files involved

| File | Role |
|---|---|
| `eli/execution/router_enhanced.py` (~2644) | `voice.create` pattern → `CREATE_VOICE` |
| `eli/execution/executor_enhanced.py` (~11366) | `CREATE_VOICE` handler → `add_clone` → sets active voice |
| `eli/perception/tts_xtts.py` | registry (`add_clone`/`get_clone`/`list_clones`/`delete_clone`), synthesis (`synthesize_wav`, `synthesize_natural_wav`), availability (`xtts_available`, `natural_available`) |
| `eli/perception/tts_router.py` | `synthesize_wav()` dispatches `clone:`/`natural:`/`char:`/plain Piper by prefix |
| `eli/perception/voice_fx.py` | the *other* path — ffmpeg character presets, unrelated dependency-wise |
| `<config dir>/voices/clones.json` | clone registry (name → reference wav path, language, description) |
| `<models dir>/voice_profiles/<name>.wav` | the normalised 22.05kHz mono reference clip per clone |

`<config dir>` and `<models dir>` are `config/` and `models/` in a source checkout
(`core/paths.py`: `config_dir()`, `models_dir()`).

## Dependency stack

The optional extra is declared three ways in `pyproject.toml` (`clone`, `natural`,
`voice` — all aliases for the same thing, worded for whichever the user searches):

```
clone   = ["torch>=2.0", "torchaudio", "torchcodec", "coqui-tts>=0.24", "transformers>=4.40,<5"]
natural = ["torch>=2.0", "torchaudio", "torchcodec", "coqui-tts>=0.24", "transformers>=4.40,<5"]
voice   = ["torch>=2.0", "torchaudio", "torchcodec", "coqui-tts>=0.24", "transformers>=4.40,<5"]
```

The torch trio is declared explicitly: `coqui-tts` does **not** declare
torch/torchaudio/torchcodec itself, but imports all three at load time. `transformers` is held
below 5 because `import TTS` must work unaided where no runtime shim applies (a build's
isolated submodule collection; see defect 2 below). The rest of the stack is on transformers
5.x (`requirements.txt` pins 5.6.2, `requirements.lock.txt` 5.8.1), so the two cannot both be
satisfied in one environment.

Installed from the repo root as `pip install -e ".[natural]"` (**not**
`pip install "eli-v2.0[natural]"` — that string only resolves once the project
itself is installed; it isn't published to PyPI under that name). On a box that
already has `torch`+CUDA for the main model, only the delta installs.

### Not in the shipped app

The XTTS-v2 engine is **not** in any release build: the packaged app's voice engine is Piper.
The `natural` extra was bundled into the Linux AppImage for a few 2.1.x releases (v2.1.65 and
v2.1.66 shipped `coqui_tts-*.dist-info` without the `TTS` package itself) and taken out after
v2.1.72 (`.github/workflows/release.yml`, `build-linux`): the bundle has to use a CPU-only torch
(a CUDA torch blows GitHub's 2 GiB per-asset limit), so XTTS ran on the processor at a cost far
out of proportion to a voice, and on a GPU machine the startup picker's `ELI_XTTS_DEVICE=cuda`
crashed it with "Torch not compiled with CUDA enabled" (`tts_xtts._select_device` now checks
that torch has CUDA before honouring it). `OPTIONAL_EXTRAS` is `tts asr image vision web
wakeword`, with no override on any job. What remains of the wiring:

* **CPU torch only.** `packaging/ci_linux_deps.sh` installs `torch torchaudio` from the pytorch
  CPU index *before* the extras loop; default PyPI torch drags ~6 GB of `nvidia-*` CUDA wheels
  in. A guard fails the build if any `nvidia-` or `triton` package appears afterwards.
* **Collection fixes kept.** `ELI.spec` still applies the transformers shim before collecting
  `TTS`, and the frozen selftest checks the engine imports when `ELI_REQUIRE_NEURAL_VOICE=1`
  (no release job sets it).
* **Weights are never bundled.** The ~1.8 GB XTTS-v2 model downloads on first use.
  ELI is offline-by-default, so that first synthesis needs network access.

When the engine is absent the voice still registers, but synthesis falls back to
Piper — and that fallback is now **visible** rather than silent: `tts_router`
records what was requested and why it failed, logs it once per change, and the
Settings ▸ Audio panel shows a `NOT IN USE` line naming the voice that is
actually speaking. See `neural_fallback_state()`.

## Defects found and fixed while verifying this end-to-end (2026-07-28)

Installing the extra and actually cloning a voice surfaced four real problems —
none of them hypothetical, all reproduced and fixed on this machine:

1. **Non-editable install shadowed the source tree.** `pip install ".[natural]"`
   (no `-e`) builds and installs a frozen wheel copy of `eli-v2.0` into
   site-packages, with its own `eli`/`eli-gui`/etc. console scripts — silently
   diverging from the live checkout on every future edit. Fixed by uninstalling
   it and reinstalling with `-e`, matching what `install.sh` always does.

2. **`transformers` 5.x removed a function `coqui-tts` still imports.**
   `TTS.tts.layers.tortoise.autoregressive` imports
   `transformers.pytorch_utils.isin_mps_friendly`, which existed only as an old
   Apple-MPS `torch.isin()` workaround and is gone in `transformers>=5` — the
   exact version this project's own `requirements.lock.txt` pins for the rest of
   the stack (`transformers==5.8.1`), so downgrading transformers was not a safe
   option. Fixed with a lazy compat shim in `tts_xtts._patch_transformers_compat()`:
   if the name is missing, define it as plain `torch.isin()` (identical behaviour
   off MPS). Called from both `_get_model()` (before loading) **and**
   `xtts_available()`/`natural_available()` — the first pass only patched the
   model-loading path, so the availability check itself still returned `False`
   even once cloning would actually have worked. The shim still serves an environment that
   keeps transformers 5.x; the extras themselves now ask for `transformers>=4.40,<5`, because
   PyInstaller collects `TTS` in an isolated subprocess where no in-process shim applies.

3. **`torchaudio`/`torchcodec` missing.** `coqui-tts` needs `torchaudio` (not
   auto-pulled here since a newer `torch` was already present) and, since
   `torch>=2.9` moved audio I/O off the old backends, `torchcodec` too. Installed
   `torchaudio==2.11.0+cu130` (matching the installed `torch 2.12.0+cu130`, via
   `--index-url https://download.pytorch.org/whl/cu130`) and `coqui-tts[codec]`.

4. **Interactive TOS prompt blocks first use with no TTY.** `coqui-tts` gates the
   *first* XTTS-v2 download behind `ModelManager.ask_tos()`, an `input()` y/n
   prompt ("I have purchased a commercial license" / "otherwise I agree to the
   non-commercial CPML"). ELI's GUI has no terminal for that prompt to read
   from — it would hang or raise `EOFError` on literally every user's first
   clone, GUI or voice command alike. Fixed in `_get_model()`:
   `os.environ.setdefault("COQUI_TOS_AGREED", "1")` before importing `TTS.api` —
   `ModelManager.tos_agreed()` short-circuits true on that env var, same effect
   as answering "y" at the prompt. This is always the non-commercial path here
   (a local, personal voice, never redistributed — same policy the shipped voice
   library already applies to restricted Piper voices).

## Verified end-to-end (this session)

Ran the real path with no shortcuts — Piper-synthesised a reference clip (so the
test needs no external/copyrighted audio), registered it exactly as `CREATE_VOICE`
would, then synthesised *new* text (never in the reference) through
`tts_xtts.synthesize_wav` directly (not the router's fallback-friendly wrapper, so
a silent fallback to a normal voice could not masquerade as a working clone):

```
[1] Piper reference clip synthesised                       — 312,738 bytes
[2] add_clone("demo_clone", ref.wav)                        — {"ok": true, "synth_ready": true}
[3] xtts_available()                                        — True
[4] tts_xtts.synthesize_wav(new_text, "demo_clone")         — real XTTS-v2 clone, non-empty WAV
[5] tts_router.synthesize_wav(new_text, "clone:demo_clone") — same result through the full app path
```

First attempt (before fix #4) returned `None` at step 4 — the TOS prompt raised
`EOFError`, and the *router* path (step 5) had silently produced normal Piper
speech instead, which is exactly the failure mode a real user would have hit
invisibly. Second attempt, with the fix in place, produced genuine cloned audio
at both step 4 and step 5.

## Licensing note

XTTS-v2 is Coqui's model under the **CPML (Coqui Public Model License)** —
non-commercial personal use, which is exactly what this feature is for (a local,
personal voice, never redistributed by ELI). ELI answers the model's licence prompt with the
non-commercial CPML on the user's behalf when it first downloads the weights
(`COQUI_TOS_AGREED=1`, defect 4 above). ELI's own code is under the Apache License 2.0 from
v2.5.36; that does not extend to the model, whose terms stay the CPML's. A commercial deployment
would need a paid licence from Coqui directly; that is a deployment decision, not something
this pipeline enforces.

## Known limitations

- First clone/natural use on a fresh install downloads ~1.8GB — no progress UI
  wired into the GUI yet beyond the console `tqdm` bar; a user driving this from
  chat/voice sees no feedback during the download.
- `synthesize_wav`/`synthesize_natural_wav` load the model once into the *same*
  process as the main GGUF model (on its GPU when torch has CUDA) and keep it there —
  no VRAM budget coordination between the two the way vision hot-swap has
  (`gguf_inference._LLM_CALL_LOCK`), and the load planner sets nothing aside for it:
  XTTS takes whatever the language model's plan left free. Worth revisiting for 8GB
  targets if natural/clone voices see real usage there.
- No per-clone quality/duration validation on the reference clip — a 1-second or
  very noisy clip is accepted and will simply clone poorly rather than being
  rejected up front.
