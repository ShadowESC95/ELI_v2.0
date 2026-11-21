> **Updated 2026-11-21 (v2.5.36).** Every Part 1 entry re-read against its handler: the 37 actions
> that had no entry are in, and `SELF_UPDATE`, `DOC_GENERATE`, `SAY`, `EXECUTE_GOAL`,
> `GAZE_CALIBRATE`, `SHOW_DIFF`, `FILE_AUDIT` and the plugin-backed rows are corrected. Module tables
> re-measured against `git ls-files 'eli/*.py'`: missing modules added, `runtime/auth.py` removed.
> v2.5.36 behaviour is described where it lands: forgetting deletes what rested on a memory, API
> members cannot run the owner's actions (`authority_gate`), the shell gate reads every command in a
> line, no canned scripts (`generated_script_guard`), long messages fitted to the model, notes in the
> data folder. Orchestration detail: `runtime_planning_world.md`, `orchestration_and_agents.md`, `dag.md`.

# ELI Capability Catalogue — every action & module, what it actually does

> **Purpose.** A systematic, ground-truth catalogue built by reading the real
> handlers and modules — not summarised from memory. It exists because
> conversational summaries of a 207,321-line project (`eli/`, measured 2026-11-21) keep undershooting; this is the
> persisted, exhaustive map.
>
> **Method.** Action list comes from the live `capability_manifest.json` (**231**
> entries: 190 routable, 207 in the executor's `SUPPORTED_ACTIONS`, every one in its dispatch), the
> same list `capability_sync` discovers from the code, checked against the `executor_enhanced.py`
> handlers. **The always-current,
> auto-generated action list with activation phrases is
> `capabilities_and_actions.md`** — this catalogue is the deeper module-level read.
> Behaviour grounded in the handlers and the
> subsystem blueprints. Where a description is inferred from name+structure
> rather than a line-by-line handler read, it is marked *(inferred)*.
>
> **Who may run what.** Actions run through `executor_enhanced.execute()`, which first asks
> `authority_gate.check()`: a caller whose role is below admin (an API member or viewer in
> multi-user mode, or an MCP client while control is off) cannot have ELI run the owner-only
> actions — shell, code, file read/write, screen, clipboard, keyboard/mouse, ELI's own settings,
> plugins, MCP (`authority_gate.owner_only()`). Commands reached through `CHAT`, `MULTI_COMMAND`
> or a `SEQUENCE` step get the same check, and a check that cannot answer refuses a lesser role.
> The actions in `llm_intent._EXPLICIT_ONLY_ACTIONS` (persona, settings, plugins, MCP,
> self-patching, the shell, erasing data) run from the router's exact phrases only, never from the
> model's guess.
>
> **Coverage:** every action in the manifest (Part 1), every module under `eli/` (Parts 2–4 and 7).

---

## Headline finding: 231 is real and lightly aliased

The manifest's 231 entries are honest (*measured* by `capability_sync`, not asserted).
**24 of them are alias names** — another name for a behaviour listed under a
different name (the families are in the Reading note) — so there are **207 distinct
behaviours**. Alias families are grouped below so the real surface is visible.

---

## 1. Conversation & reasoning
| Action(s) | What it does |
|---|---|
| `CHAT` | The default. The engine runs it through its full pipeline (router → gradient orchestrator → mode algorithm → governed output). Called on the executor directly, `CHAT` goes to `chat()`: the loaded GGUF model with the persona (Ollama only when Ollama is the chosen backend), after routing the text as a command first; its keyword shortcuts (live memory audit, "what did we discuss yesterday") apply to the user's own words only, never to prompts the engine assembles. |
| `NOOP`, `SAY`, `ANSWER`, `DIRECT_RESPONSE` | Return the `message` (or `response`/`content`) they were given as the reply; nothing else runs. `SAY` does not speak (that is `SPEAK`). |
| `SET_AI_MODE` | Set the reasoning mode (Quick / Normal / Advanced / Research / Expert). Legacy names still accepted as input (`reasoning_modes.canonical_mode`); saved to settings and applied to the running engine. |
| `SEQUENCE` | Run a given list of `{action, args}` steps in order, each held to the caller's role, and report what each step did. No dependency handling. |
| `MULTI_COMMAND` | The real chained-command executor ("close steam and set an alarm"). Router's `command_splitter.py` splits; dependency edges come from one optional model call (`command_dependency_graph.py`, validated by `eli/core/dag`), the parts run in topological layers, and a step whose dependency failed is skipped. `command_sequence_log.py` durably records each step's outcome, so a crash mid-sequence isn't a silent loss and a resubmit within an hour skips steps already known to have succeeded. Steps ELI listed and the user agreed to run without the dependency call. `SEQUENCE` above is a different, simpler mechanism. |

## 2. OS & application control
| Action(s) | What it does |
|---|---|
| `OPEN_APP` = `OPEN_APPLICATION` = `LAUNCH_APP` | Launch an app: `portable_app_control.open_app` resolves the name against the apps installed on this OS (desktop entries on Linux, `.app` bundles on macOS, the Start menu on Windows); "settings" opens the system settings. When that fails, all three go on as `OPEN_APP`: a missing app gets a **remediation offer** (installed with the platform's package manager on a yes, §13), else the executor's own launcher (common-name map, web apps such as Gmail or YouTube opened in the browser, a launch counted only with a desktop entry or a known GUI program behind it). "Open/start" plus one of ELI's own features (dictation, a new chat, system settings) is routed to that feature instead. |
| `CLOSE_APP` = `CLOSE_APPLICATION` = `EXIT_APP` = `QUIT_APP` | Close an app: `portable_app_control.close_app` closes its windows, then the program ELI resolved for it, on every OS. When that fails, all four go on as `CLOSE_APP`: `wmctrl -c` on Linux, then `process_guard.safe_pkill` (process name, then command line, dry-run first, protected processes refused); says why when nothing closed. |
| `FOCUS_APP` | Bring an app's window to the front; a browser tab only when it is the one showing in its window. |
| `HIDE_APP` = `MINIMISE_APP` = `MINIMIZE_APP` = `MINIMISE_WINDOW` = `MINIMIZE_WINDOW`, `MAXIMISE_WINDOW` | Minimise a named app's window (UK/US spellings aliased); maximise a named window, or the active one when none is named. |
| `MINIMISE_ALL`, `RESTORE_WINDOWS`, `TILE_WINDOWS`, `NEXT_WINDOW`, `PREVIOUS_WINDOW` | Desktop window management (`portable_app_control`). |
| `SWITCH_WORKSPACE` | Switch virtual desktop/workspace (`direction`, right by default). |
| `OPEN_SYSTEM_SETTINGS`, `OPEN_AUDIO_SETTINGS`, `OPEN_POWER_SETTINGS` | Open the OS's own settings panel (`platform_compat.open_role`: ms-settings: on Windows, System Settings panes on macOS, the desktop's panel on Linux). |
| `OPEN_FILE_SYSTEM` | Open a folder in the file manager: home by default, the trash, or a named path under home, Desktop or Documents. |
| `OPEN_COMMUNICATION_HUB`, `OPEN_MEDIA_HUB`, `OPEN_NETWORK_BROWSER` | This OS's mail app (else whatever opens `mailto:` links); Spotify when installed, else the OS's music player, else the Music folder; the browser at a URL (DuckDuckGo by default). |
| `OPEN_IDE`, `OPEN_IN_IDE` | Open the first IDE installed for this OS (a named one opens as an app, a missing one gets the remediation offer; "editor" opens the text editor); `OPEN_IN_IDE` opens a file in it. |
| `OPEN_BROWSER`, `OPEN_URL` | Open the browser: a URL, several named sites at once, a YouTube search, else a DuckDuckGo search (strict safe search when it is on). `OPEN_URL` opens a link, or a site named or referred to ("that website"), found in the conversation and then by a web search (`site_address.py`). |

## 3. Input & screen control
| Action(s) | What it does |
|---|---|
| `KEYBOARD` | Press a key or type text (`os_controller.press_key` / `type_text`). |
| `MOUSE_CONTROL` | Move the pointer (to coordinates, or a direction, 100 px by default), click (left/right/middle, double) or scroll: `xdotool` (X11) / `ydotool` (Wayland) first on Linux, `pyautogui` elsewhere. A key name in the button slot ("click enter") is pressed as a key; nothing reports success unless a backend acted. |
| `VOLUME` | Get, set, raise/lower (by 10 by default), mute or unmute the system volume on every OS (`effectors/system_helpers.volume_fallback`). |
| `SET_CLIPBOARD`, `GET_CLIPBOARD` | Read/write the clipboard. |
| `SCREENSHOT` | Capture the screen or a region (`os_controller.take_screenshot`). |

## 4. Gaze (webcam eye-tracking)
| Action(s) | What it does |
|---|---|
| `GAZE_ENABLE`, `GAZE_DISABLE` | Start/stop the MediaPipe gaze engine (writes `latest_gaze.json` @10Hz). "Enable gaze clicking" also turns on dwell-click: rest the gaze on a target about a second to click it; "disable gaze clicking" turns it off alone, and `GAZE_DISABLE` without it stops the engine and dwell-click both. |
| `GAZE_CALIBRATE` | Says whether a calibration file exists and how to run the 25-point calibration script (`experimental/eli_ar_avatar_kit/scripts/eli_gaze_calibrate_plus.py`), with `--out` set to the file ELI reads; it does not run it. |
| `GAZE_CLICK` | Move the cursor to where you're looking and click. |
| `GAZE_STATUS` | Report gaze-engine state: running, calibration, camera, last gaze point and confidence. |

## 5. Media
| Action(s) | What it does |
|---|---|
| `PLAY_MEDIA` | Play a song, artist, album or playlist (`play_specific`): Spotify's own app (never the web player), YouTube through ELI's player (yt-dlp + mpv; a Mix keeps related tracks coming), a browser watch page only when asked ("youtube.com"); a named streaming service (Netflix, Prime, Disney+ …) opens its app at a search. Honest about reachability; an explicit platform never falls through to a second. With nothing named it resumes playback. |
| `PAUSE_MEDIA`, `STOP_MEDIA`, `NEXT_MEDIA`, `PREVIOUS_MEDIA`, `REPEAT_MEDIA`, `SHUFFLE_MEDIA` | Transport control: ELI's own mpv player when it is the active source, else MPRIS/playerctl on Linux and the system media session or media keys on Windows and macOS. Spotify gets pause for stop; repeat cycles off → track → playlist. |
| `NOW_PLAYING` | What is playing and from where (mpv's title, the OS media session, or live playerctl metadata). |
| `MEDIA_CONTROL` | Generic media command ("pause", "skip", "loop", "toggle") mapped onto the actions above. |
| `SKIP_YOUTUBE_AD` | Finds YouTube's "Skip Ad" button on the screen and clicks it (`screen_locator`); ELI's own mpv player shows no ads. |

## 6. Files & documents
| Action(s) | What it does |
|---|---|
| `CREATE_FILE` | Write text to a path and read it back. Relative paths go under `artifacts/scratch`; a path outside home, the project, `ELI_ALLOW_ROOTS` (`SecurityManager.is_path_allowed`) and the temp folder is refused unless Full Control is on. Never replaces an existing file unless overwriting was asked for ("overwrite", "replace"). |
| `CREATE_FOLDER`, `READ_FILE`, `LIST_DIR` | Make a folder (a bare name goes under home); read a file (PDF/DOCX/DOC/ODT/EPUB through the document reader, others as text; a folder is listed instead); list a folder (up to 500 entries; a file is read instead). No path allowlist on these three. |
| `SUMMARIZE_FILE` | Summarise a whole file (map-reduce sized to the model), saved as a `.docx` summary under documents and opened; images go to `ANALYZE_IMAGE`, folders holding PDFs to `ANALYZE_PDF_FOLDER`. Also the route for "read your persona.auto.txt / settings". |
| `CONVERT_DOCUMENT` | Convert document formats with pandoc (LuaLaTeX for PDF from LaTeX), else headless LibreOffice. |
| `CREATE_DOCUMENT` = `GENERATE_DOCUMENT` = `CREATE_DOC` = `WRITE_DOCUMENT` | Generate a document on a topic (the Report-Builder discipline): evidence gathered first (`evidence_planner`), then the multi-stage `report_pipeline` (outline, grounded sections, review, polish; one pass as fallback) on the local model, saved under `artifacts/documents/`; a result under 800 characters (`ELI_DOCUMENT_MIN_CHARS`) is refused. Given an explicit body (`content`/`text`), `CREATE_DOCUMENT`, `CREATE_DOC` and `WRITE_DOCUMENT` save that body as written. |
| `DOC_GENERATE` | Saves the content it is given (or a one-line title stub) to `artifacts/docs/<title>.md` and opens it; it does not write the document itself. |
| `ANALYZE_CSV`, `ANALYZE_PDF`, `ANALYZE_PDF_FOLDER`, `ANALYZE_IMAGE`, `OCR_IMAGE` | Local file-type analysers: CSV shape and columns with a Markdown report; one PDF analysed by the model for the instruction given (critique/falsification, equations, …); a folder of PDFs read whole into the document index with one summary and a PDF result (`folder_analysis.py`; a background job when heavy); image and OCR in §7. |

## 7. Vision & screen understanding
| Action(s) | What it does |
|---|---|
| `ANALYZE_IMAGE` | Metadata and OCR, a local GGUF vision-language description (a small fast model on request), and the two fused by the text model into a description from that evidence only; without either it says so instead of guessing. |
| `OCR_IMAGE` | Tesseract OCR text extraction (the CLI, else `pytesseract`). |
| `AMBIENT_VISION` | Toggle periodic background screen glances (about every 5 minutes by default, not mid-reply); says so when the vision model is missing. |
| `SCREEN_LOCATE` | OCR-locate a named UI element or word on screen ("the button that says X", "find the word compose"), and click it ("click compose"). |
| `SCREEN_READ_ANALYZE` | Screenshot → `ANALYZE_IMAGE` with a prompt for the depth asked (quick / standard / deep; OCR fused for standard and deep). |
| `IMAGE_STATUS` | Evidence packet of recent runtime events and recently generated artifacts (images, scripts or documents, by the question), from `evidence_ledger.status_evidence`. |

## 8. Coding & code-repair
| Action(s) | What it does |
|---|---|
| `CODE_SOLVE` | The coding agent (`eli.coding.solve`): plan → DAG decompose → UCB tree search → verify (syntax/exec/tests) → repair → bug-memory; Quick mode is lean; heavy work runs as a background job. Python that does not parse is saved as a `.draft`. With `code_mode` a short program runs in-process against `eli.api` instead (Full Control only). |
| `GENERATE_SCRIPT` = `CREATE_SCRIPT` = `WRITE_SCRIPT` = `GENERATE_CODE` = `WRITE_CODE` | Generate a script with one model call (the executor's `chat()`, else `gguf_inference.generate`): language inferred from the request, stub or empty output refused, Python compiled with one standard-library-only retry, saved to `artifacts/scripts/` under a new name rather than over a file, opened in the Labs Sim-IDE; `generated_script_guard` quarantines a template or chatter file. The executor's older coding-agent branch for `GENERATE_SCRIPT` is not reached. |
| `GENERATE_PROJECT` | Generate a multi-file project through the coding planner DAG (`CodeAgent.solve(use_dag=True)`), saved under `artifacts/projects`; one model pass if that fails. |
| `GENERATE_TESTS` | Write and sandbox-verify behavioural tests per function (`test_generator.run_testgen`, 3 targets by default, at most 10); only passing drafts are kept, in the drafts folder, for review. |
| `EXAMINE_CODE` | Tiered file scan (syntax/import → lint → gated LLM logic review) → offers a fix only for named files with real breakage; "list the errors you found" replays the saved audit. |
| `FIX_FILE` | Fix (or with `mode=improve`, improve) a named file: protected guardrail files refused, a backup first, Python through the verified CodeAgent; a Python module that no longer imports or fails its targeted tests is restored. |
| `CONFIRM_CODE_FIX`, `CANCEL_CODE_FIX` | Apply / drop `EXAMINE_CODE`'s pending fix: each patch syntax-checked and import-verified, auto-reverted if it breaks its module; logic (Tier-3) findings only when asked. |
| `FILE_AUDIT`, `SHOW_DIFF`, `CODE_CHANGES` | File inventory of ELI's own package (files per directory under `eli/`); the project folder's own git history when it is a checkout (uncommitted changes with `git status` and `git diff HEAD`, or the latest commit's when there are none, and the latest commits), two named files compared line by line, else a plain "no change history"; the code changes the awareness code monitor saw since its last check. |

## 9. Self-management & self-improvement
| Action(s) | What it does |
|---|---|
| `SELF_REPORT` | Grounded runtime self-report (deterministic, from live state): model, context, GPU layers, measured health and concerns, the active user's name; "what updates/checks have you done" gets the recent-updates report. |
| `SELF_ANALYZE`, `SELF_IMPROVE`, `SELF_IMPROVEMENT_LOG` | Open failures in the analysis window, each with a root cause (known signatures, else up to three model inferences) / one self-maintenance cycle (`self_maintenance.run_maintenance_cycle`: analyse, `propose` via the coding agent in the background, or `patch`) / the improvement log (5 entries over 30 days by default). |
| `SELF_PATCH` | The patch cycle: up to 3 patches generated, verified, applied, auto-reverted on failure. |
| `SELF_TEST`, `RUN_TESTS`, `TEST_REVIEW` | Persona-lock status, a chat handshake with the active backend (GGUF or Ollama) and, on Ollama, a consistency probe / pytest through `tools/run_test_report.py` (default `tests/claims/test_structural_claims.py`), returning `artifacts/test_report.md` / run a target, back up the previous report, write the errors, list failing tests with what the code examiner found in their modules, offer next steps. |
| `SELF_REPAIR_PLAYBOOK`, `AUTOPILOT_DEBUG` | Which mechanism fixes which class of problem (`repair_playbook`, live) / a failure (error text or traceback) turned into a plan: affected files and their git history, the static examiner, root cause, rollback, patch, validation; `run_tests` runs the targets' tests, `verify` re-runs failing tests read-only. |
| `SELF_UPGRADE` | Upgrade by install kind (AppImage download checked against its SHA-256, packaged build, or a source checkout: release wheel, `git pull --ff-only`, pip), then maintenance: rebuild FAISS/KG, refresh manifest + system index. Says "NOT upgraded" when nothing new was installed. |
| `SELF_UPDATE` | Not an upgrade: refreshes ELI's self-model (persona and user-profile overlays, capability manifest, world-model runtime) through `control_contracts.build_control_evidence`. |
| `LORA_STATUS`, `LORA_TRAIN` | LoRA training readiness per target (`training_preflight.preflight_all`) / the LoRA pipeline's stages in order (`lora_pipeline.run_pipeline`), a dry run from chat (preflight → dataset → eval); real training only with `execute`, from the scheduled task or the Training tab. |

## 10. Introspection & audits (grounded, deterministic)
| Action(s) | What it does |
|---|---|
| `RUNTIME_STATUS`, `RUNTIME_AUDIT` | Live runtime report (also a bare "status" / "/status"); RUNTIME_AUDIT also runs **health probes** (plugin mgr, memory, agent bus, habit integrity, recent failures). |
| `GUI_RUNTIME_AUDIT`, `IMPORT_AUDIT`, `DIAGNOSE_WRAPPERS`, `RESOLVE_RUNTIME_PATHS` | GUI/runtime audits, import smoke-audit, executor-wrapper diagnostic, path resolution. |
| `FRONTIER_STATUS`, `ELI_IDENTITY_AUDIT` | Cross-system matrix (runtime, memory, awareness, proactive, image, world/labs, chat flow, modules) / identity-classification audit (source inventory, contract counts, capability matrix). |
| `COGNITION_STATUS`, `EXPLAIN_COGNITION_RUNTIME`, `EXPLAIN_MEMORY_RUNTIME` | Cognition + memory runtime explainers (verbatim, deterministic). |
| `EXPLAIN_ALL_REASONING_MODES`, `REASONING_MODE_STATUS` | Describe the 5 reasoning modes / current mode. |
| `EXPLAIN_LAST_RESPONSE`, `EXPLAIN_LAST_FAILURE`, `NAME_SOURCE_AUDIT`, `ROUTING_FAULT_EXPLAIN` | The last turn's trace with its per-cycle telemetry (agent dispatch timings, runtime events); the last failure (the remediation record, else the failure log); the source of your name; a routing fault. |
| `EXPLAIN_FAILURE_LOG`, `EXPLAIN_GGUF_DIAGNOSTICS` | The executor failure log (last 50) / GGUF load-compatibility and runtime diagnostics (`gguf_runtime_report`). |
| `ORCHESTRATION_STATUS`, `CODEBASE_GRAPH` | The agent DAG (agents, execution layers, dependencies, last run) / questions about ELI's own architecture answered from the live import graph (`codebase_graph.explain`). |
| `HARDWARE_PROFILE`, `GPU_STATUS`, `AWARENESS_STATUS` | Hardware benchmark and recommended model/layers/context/batch ("apply hardware recommendation" saves it, restart needed) / GPU state / the awareness briefing. |
| `GET_STATUS` | A short status record (user name, default chat model, persona lock, and Ollama's loaded models only when Ollama is the chosen backend). Not routable: a bare "status" goes to `RUNTIME_STATUS`. |
| `HELP`, `LIST_CAPABILITIES` | Every action in the code (`CapabilitySync.discover`), each marked as having worked on this machine, unable to run here (and why) or untried (`capability_updater.capability_status`); `HELP` also names plugins. |

## 11. Memory & identity
| Action(s) | What it does |
|---|---|
| `MEMORY_RECALL`, `MEMORY_STORE`, `MEMORY_STATS`, `MEMORY_STATUS` | Recall (`Memory.search_memory`; each hit dated, the user's own just-sent words left out, 3,000 characters at most; an identity-shaped recall becomes `USER_INFO_REPORT`) / store through the memory filter, saying whether it reached the semantic index / table counts and conversation-log size / memory status with the database schema, with own reports for "recent processing", "health" and count questions. |
| `MEMORY_FORGET` | Find stored memories (and indexed documents) matching what to forget, list them and wait for a yes or "confirm forget memories <ids>"; then delete them and everything derived from them: derived memories, semantic facts and quotes, claims resting only on them (a claim another memory still supports keeps that support), session summaries holding their words or identifiers or summing up the conversation they were said in, user-model items, stances, graph entries and the matching conversation turns; their vectors are compacted out of the index files at once. A forgotten document leaves the index; the file stays on disk. |
| `PERSONAL_MEMORY_SUMMARY`, `PERSONAL_MEMORY_DEEP_EXPLAIN` | Both give the clean "what do you know about me" report (`personal_memory_clean_response`: reset-aware, poison-filtered, stale volatile facts aged out); asked for the inventory, the preferences or the full profile, they answer that scope from the active user's profile. |
| `USER_IDENTITY_SUMMARY`, `USER_INFO_REPORT`, `REFRESH_USER_INFO` | Who-you-are summary / full profile report / rebuild the living profile. |
| `SET_USER_NAME` | Set the user's name (phrases and sentence fragments refused); stale identity patterns that disagree are purged. |
| `MESSAGE_TIME_QUERY` | "What time did I first/last message (today)" — from `conversation_turns`; with a topic, every message where the user wrote about it, by day. |
| `CLEAR_CHAT_HISTORY` | Empties the chat history in the executor's `state.json`; memories and the conversation log stay. |
| `PERSONA_LOCK_SET`, `PERSONA_LOCK_CLEAR`, `PERSONA_LOCK_STATUS` | Record / clear / check the persona lock: the chat model name, an optional Modelfile's SHA-256 and Ollama's digest, verified by the executor's `chat()` before it answers. |
| `PERSONA_REFRESH` | Purge the stale persona auto-overlay (`persona_hygiene.clean_auto_persona`) and rebuild the active profile; no memory or conversation rows are deleted. |
| `SET_COMMUNICATION_STYLE`, `SET_TONE`, `CLEAR_TONE` | A free-text speaking style saved to the profile ("blunt, concise"; "set your style to none" or the Settings field left blank clears it, "reset your tone" does not) / a named tone from the emotion palette for words, voice and face ("be comedic") / back to adaptive tone. |

## 12. Habits, proactivity & goals
| Action(s) | What it does |
|---|---|
| `CONFIRM_HABIT`, `DECLINE_HABIT`, `HABIT_STATUS` | Approve the offered habit (run now if today's slot has passed, then at its time daily) / decline it (kept disabled, no longer suggested) / report detected patterns, the most-used actions and scheduled habit rules. |
| `MORNING_REPORT` | A report named for the hour it is made: the last 24 hours' activity insights (`reflection.run_reflection`) plus news on the user's interests when the network is on. |
| `PROACTIVE_START`, `PROACTIVE_STOP`, `PROACTIVE_STATUS` | They act on the daemon ELI runs as a thread in its own process (`proactive_daemon.start_daemon`, as the GUI and the engine start it). Status: whether that loop is live. Start: runs it again after a stop or a crash, or says it is already running. Stop: ends the loop at once when it is between steps, and says so when it is finishing one. |
| `EXECUTE_GOAL` | Shows the step list `execution_planner.build_execution_plan` makes for a goal; nothing is run. |
| `GET_PROPOSALS` | ELI's own proposals: proposal-only goals `goal_autogenesis` formed from its signals (world-model suggestions, recurring failures) and pending capability proposals. |
| `RESUME_TASK` | Explicit "continue/resume the X project" — `goal_store.find_task()` bypasses the passive 14-day idle window, states real staleness, says plainly when nothing matches rather than guessing. |
| `SCHEDULE_TASK` | Schedule heavy or overnight work at a parsed time (`scheduled_tasks.schedule_request`; "every/each/daily/nightly" repeats); the result appears in the Tasks/Proactive panel. |
| `BACKGROUND_JOBS`, `CHECK_JOB` | List background tasks / check a job id: done (its result when asked), failed, cut off when ELI closed, scheduled, or running with progress and time left. |

## 13. Self-healing remediation
These five pass the message to `grounded_remediation.try_handle_query`.

| Action(s) | What it does |
|---|---|
| `PREPARE_REMEDIATION` | Diagnose a failure + build a repair plan (e.g. install a missing app with the platform's package manager: apt/dnf/zypper/pacman, snap or flatpak on Linux, brew on macOS, winget or choco on Windows). |
| `CONFIRM_PENDING_REMEDIATION`, `CANCEL_PENDING_REMEDIATION` | The first yes previews the pending plan and the second runs it (a media tool runs on the first yes) in a visible terminal, with package-lock handling and a check afterwards / cancel it. On Windows the lookup runs `where` without a shell, and only plain app/package names reach winget or choco. |
| `CHECK_TARGET_STATUS`, `EXPLAIN_LAST_FAILURE` | Check whether a target app/path is now present / the last grounded failure (§10). |

## 14. Voice & transcription
| Action(s) | What it does |
|---|---|
| `DICTATE` | Tell the GUI to start or stop dictation mode (the GUI runs the loop). |
| `TRANSCRIBE` | Transcribe an audio file, or one utterance from the microphone (up to 30 s, ends after 1.2 s of silence), with faster-whisper `small` on the CPU. Reached by "transcribe X" or "make a transcript of X"; a sentence that only mentions a transcript is not a request. |
| `LISTEN_FOR_COMMAND` | One-shot listen (5 s by default). |
| `STT_DIAGNOSTICS` = `VOICE_DIAGNOSTICS` | The voice pipeline's state: speech-recognition import, wake word (on/off, trained, phrase), Whisper cache/model/device, output and media ducking, and the TTS backends (Piper, espeak-ng, espeak). |
| `SPEAK` | Speak text through `tts_router` (Piper, espeak fallback). |
| `LIST_VOICES`, `SET_VOICE`, `DOWNLOAD_VOICE` | Installed and character voices with a count of downloadable ones / switch to an installed voice / fetch a Piper voice by accent or name (MD5-checked, network-gated) and make it active. |
| `DESIGN_VOICE`, `CREATE_VOICE` | A named character voice (`char:<name>`): a base voice with pitch (−6..+6 semitones) and speed (0.5–1.5) / a cloned voice (`clone:<name>`) from an audio clip, sounding like the sample once the neural voice extra is installed. |
| `WAKE_TRAIN`, `WAKE_ENROLL`, `WAKE_SET`, `TRAIN_VOICE` | Train the local wake-word model from Piper-synthesised samples mixed with noise / record the user saying it and retrain / change the wake phrase and train on it in the background / learn the user's voice baseline (pitch, energy, rate) for tone detection. |

## 15. Time, timers & utility
| Action(s) | What it does |
|---|---|
| `TIME` = `GET_TIME`, `DATE` = `GET_DATE` | Current time / date, for a place named in the question (`worldclock.describe`). |
| `SET_TIMER`, `SET_ALARM` | A duration starts a timer that notifies and plays the alarm sound (in memory, gone on restart); a clock time ("7am", "tomorrow at 7:30pm", "noon") becomes an agenda reminder that survives a restart; `SET_ALARM` with text ("remind me at 4pm to …") is a labelled reminder. |
| `TIMESTAMP_DIAG` | Wall clock beside the stored timestamps of the last turns. |
| `CHECK_CHRONAL_ALIGNMENT` | Easter-egg: "Chronal alignment nominal. Local time: …" (a playful time report). |
| `DATA_FABRICATOR` | Generate a document from a topic (via CREATE_DOCUMENT) **and open it in this OS's text editor**; with no topic, a blank `data_construct_<time>.md` in ELI's documents folder. |
| `RUN_CMD`, `SHELL_EXEC` | Run a command: `RUN_CMD` without a shell, `SHELL_EXEC` through the OS shell. `shell_gate.check_command` judges every command in the line (`;` `&&` `\|\|` `\|` `&`, newlines, `$( )`, `<( )`, backticks, and what wrappers such as sudo, env, nice, timeout, xargs or busybox run) and refuses destructive patterns and denylisted programs (shells, interpreters, disk and firewall tools, `rm`, `find -delete`) unless ELI Full Control is on. |

## 16. Plugins & MCP (management)
| Action(s) | What it does |
|---|---|
| `PLUGIN_LIST`, `PLUGIN_SEARCH`, `PLUGIN_STATUS` | List installed or available / search registry / status: installed and available counts and each installed plugin's health as the plugin manager's loader found it (OK, disabled, or the error it did not load with). |
| `PLUGIN_INSTALL`, `PLUGIN_UNINSTALL`, `PLUGIN_ENABLE`, `PLUGIN_DISABLE` | Install (a community listing through the marketplace path: checksum, signature, static check, eleven scanners, consent; a bundled plugin through the manager; else a search) / remove / enable / disable a plugin. |
| `MCP_LIST`, `MCP_STATUS`, `MCP_TOOLS`, `MCP_CALL` | Configured MCP servers (on/off, tool count, verified) / which are connected, with their tools / the tools live servers offer / call one. |
| `MCP_DOCTOR`, `MCP_REMOVE`, `MCP_ADD` | Check each configured server / remove one / adding one is not done from chat: it runs a separate program, so it goes through Settings ▸ Marketplace ▸ MCP servers. |

## 17. Plugin-backed capabilities
The executor answers each of these with its own branch; an installed plugin is consulted last, only
for an action no built-in branch handles. "Plugin" is the plugin that declares the action in
`eli/plugins/registry/index.json`; the text says what runs.

| Action | Plugin | What it does |
|---|---|---|
| `WEB_SEARCH` | web | Live results as grounding, never a browser window: the web plugin's search (SearXNG when configured, else DuckDuckGo), the local news store when that is empty; results that don't answer the query are withheld. Refused while the network toggle is off. |
| `WEB_FETCH` | — (web plugin's `read_page`) | Read a linked page so ELI answers from it; network-gated. |
| `GET_WEATHER` | weather | The plugin's `get_weather`: open-meteo geocoding + forecast (network-gated); current conditions or the forecast for the day asked about; the last place asked about in the session when none is named. |
| `NEW_NOTE`, `LIST_NOTES`, `SEARCH_NOTES` | notes (its actions run this) | Executor branch: `<title>.md` notes in `paths.notes_dir()` (`<data dir>/notes`, `ELI_NOTES_DIR` overrides), a second note with the same title saved beside the first; listing and substring search cover every note there, WRITE_NOTE's daily pages too, and the pages older versions left in `paths.notebook_dir()`; a search shows the line that matched. |
| `WRITE_NOTE` | — | Appends "- [HH:MM:SS] text" to today's page (`<date>.md`) in `paths.notes_dir()`, the folder the note actions read, under a lock. |
| `ADD_EVENT`, `LIST_EVENTS`, `REMOVE_EVENT` | — (calendar plugin uses the same store) | ELI's own local calendar and reminders (`runtime/agenda.py`): add, move, list, remove. Mirrored to `calendar.ics`. |
| `POMODORO_START`, `POMODORO_STOP`, `POMODORO_STATUS` | pomodoro (its actions run this) | Executor branch: a work (25 minutes by default) or break (5) session kept in `pomodoro.json`, whose end is an agenda reminder, announced like any reminder (desktop notification, alarm sound, the Proactive tab) and after a restart too; stop cancels it; status gives elapsed and remaining time, or when the last one ended. |
| `CPU_USAGE`, `RAM_USAGE`, `SYSTEM_STATS` | system_stats (its actions run this) | psutil readings: CPU load, cores, frequency, temperature / RAM used and total / OS, CPU, RAM, disk and battery. |
| `SMART_HOME` | — (executor and device server) | A device, room or scene switched on/off (or set to a brightness or value) through ELI's own MQTT device server; read from what was said (`device_server.resolve_spoken_target`: the name with the most of its words said, a kind of device narrowing a room or naming every one of that kind) (ESPHome / Tasmota / Zigbee2MQTT), which also runs saved automations; Bluetooth connect, disconnect, pair, trust or use-for-audio by name. Home Assistant removed. |
| `SPEAK` | tts (its actions run this) | Text-to-speech through `tts_router` (Piper, espeak fallback). |
| `NEWS_FETCH` | — (executor + news tool) | Fetch headlines and read them as a short briefing (`news_synthesis.synthesise_news_briefing`: a general ask mixes top stories with the user's interests, a topic ask keeps to the topic); also stored-news search, recent headlines (refetched after 6 hours) and store stats. The proactive daemon summarises each 3-hour window into `news_reflections`; only windows with real articles become memories. |

*(Also reachable through the plugin manager: `web_automation` plugin — Playwright browser navigate/search/screenshot/close; `document_reader` plugin — PDF/DOCX/DOC/ODT/EPUB read + index, whose reader `READ_FILE` and `SUMMARIZE_FILE` use.)*

---

## Reading note
Alias families that collapse the count: app-open (3 names), app-close (4), minimise/hide
(5 across window/app + UK/US), document (4: `CREATE_DOCUMENT`, `GENERATE_DOCUMENT`, `CREATE_DOC`,
`WRITE_DOCUMENT`; `DOC_GENERATE` only saves text it is given), script/code-generate (5),
time/date (2 each), direct reply (4: `NOOP`, `SAY`, `ANSWER`, `DIRECT_RESPONSE`), voice
diagnostics (2), personal memory (2), help (2). That is 24 alias names; removing them yields
**207 genuinely distinct capabilities** — a broad surface for a local assistant, spanning OS
control, media, files, vision, gaze, voice, coding, memory, introspection, autonomy, remediation,
and plugins. `SELF_UPDATE` is not an alias of `SELF_UPGRADE` (§9).

---

# Part 2 — `runtime/` module catalogue (101 files, 40.0k lines)

The largest package. It's the **grounding/governance + introspection + plumbing**
layer that wraps the probabilistic model. Grouped by function:

## Grounding & anti-confabulation
| Module | LOC | Role |
|---|---|---|
| `deterministic_grounding_gate.py` | 3303 | Renders control/status answers directly from live runtime (bypasses the model). One ordered `render_action` pipeline of layers composed by `_stack`; an unhandled action returns a `missing_deterministic_renderer` surface. |
| `grounding_escalation.py` | 851 | When a **checkable factual** question is poorly grounded by the bus, escalates through tiers (the web, or local deepening at a higher reasoning mode with more evidence, then a hedge) instead of letting the model confabulate (a musician's real name, for example). A clarification of an earlier question (`clarifies_a_question`) and "the new one" of what the talk is about are looked up. |
| `diagnostic_patterns.py` | 112 | Regexes that catch vague/dynamic status confabulation ("currently processing updates…") and image-status fabrication; user challenges; which turns to keep out of the prompt. |
| `control_contracts.py` | 1311 | Control-action evidence contract: build evidence → validate the model's output doesn't violate it → finalise. `SELF_UPDATE` and `EXPLAIN_LAST_RESPONSE` answer from it. |
| `persistence_gate.py` | 208 | Gates what gets stored — refuses to persist internal report dumps, recall narration, chatter and error-pattern noise as memory. |

## Self-honesty / introspection / self-reporting
| Module | LOC | Role |
|---|---|---|
| `live_introspection.py` | 736 | Live runtime snapshot, last trace, stored user name, mines user-fact candidates, agents-for-action, build_report. |
| `deterministic_introspection.py` | 601 | The engine's live diagnostic dispatcher (`handle_diagnostic_action`) — deterministic answers for RUNTIME_STATUS / EXPLAIN_* / IMPORT_AUDIT, the reasoning mode, and agent-bus / orchestrator / output-governor status. |
| `truth_report.py` | 419 | Runtime truth report: git, platform, settings against the runtime snapshot (what loaded, VRAM free at load), `ELI_*` environment, GGUF runtime, import health. |
| `frontier_status.py` | 433 | Full cross-system status matrix (runtime/memory/awareness/proactive/image/world-labs/chatflow + module matrix). |
| `eli_identity_audit.py` | 424 | Identity-classification audit (source inventory, contract counts, capability matrix). |
| `reasoning_status.py` | 199 | Current reasoning-mode reporting. |
| `experimental_inventory.py` | 146 | Inventory of experimental projects. |

## Self-improvement & code-awareness
| Module | LOC | Role |
|---|---|---|
| `self_improvement.py` | 1909 | Failure logging/clustering, patch generate→verify→apply→**auto-revert**, full patch cycle; the protected-path list no patch may touch (`is_protected_patch_path`: the shell gate and other guardrails). |
| `code_examiner.py` | 927 | Tiered file error scan (syntax/import → lint → gated LLM) → offer → verified fix. |
| `code_monitor.py` | 261 | Detects source changes via git diff, classifies by subsystem, summarises for memory/context (ELI is aware of its own code changes). |
| `capability_sync.py` | 459 | **AST-discovers** the live capability surface (executor dispatch + `SUPPORTED_ACTIONS`, router intents, plugin registry), diffs it against the last snapshot and writes the inventory; `eli/tools/registry/capability_updater.py` turns that into `capability_manifest.json` — this is why the count is *measured*, not asserted. |
| `generated_script_guard.py` | 208 | Wraps the executor so what script and document generation leave behind is checked before it is reported done: a generated script that is a template or the model's chatter (TODO, "Add code here", a shell file full of Python) is **quarantined** in an `invalid/` folder and reported as failed; a generated document is filed under documents and refused when a stub or too short. The keyword-chosen pre-written scripts it used to return are gone (v2.5.36). |

## Self-healing remediation
| Module | LOC | Role |
|---|---|---|
| `grounded_remediation.py` | 1688 | Diagnoses failures (missing app/path/browser/IDE/media tool) → builds a repair plan for the platform's package manager (apt/dnf/zypper/pacman + snap/flatpak; brew; winget/choco) → offers → previews → **executes** in a visible terminal (sudo/admin, package-lock handling) → verifies. On Windows the lookup runs `where` without a shell and only plain names reach winget/choco. |
| `incident_log.py` | 21 | Writes incident records. |

## Awareness & boot
| Module | LOC | Role |
|---|---|---|
| `awareness_boot.py` | 396 | Boots all awareness subsystems at startup, returns an `AwarenessState` the engine queries. Its live self-model line goes in every prompt and does not name the avatar's room (the room reaches the model only when the person asks about ELI's world). |
| `action_commitment.py` | 287 | Detects when ELI's reply commits to an action. The engine then runs it only if it is a read (news, weather, calendar listing) or something the user's own message asked for; anything that changes state waits for a "yes". |

## Autonomy / operator (governed)
| Module | LOC | Role |
|---|---|---|
| `operator_state.py`, `operator_feed.py` | ~177 | Operator console state: proposals, goals, self-model status, event feed. |
| `pending_proposal.py` | 656 | What ELI's last reply left open, for 30 minutes: the steps it offered (`read_reply`: actions, tasks ELI does by writing, explicit-only, what it said it would do before a "Deal?"), the question it ended on, a detail an action asked for, and where to save what it wrote (`destination`, `what_was_written`). Reads the user's reply against it: `is_consent`, `chosen_items`, `selection`, `is_the_detail`. |
| `agenda.py` | 1074 | ELI's calendar and reminders: SQLite store, plain-language dates and times (`parse_when`), a notifier thread that delivers what is due (and what was missed while shut), `calendar.ics` mirror, the next 36 hours as a prompt line. |
| `approval_engine.py` | 103 | Who may propose / evaluate a proposal record (governance). |

## Response surfaces & governance
| Module | LOC | Role |
|---|---|---|
| `user_visible_response_surface.py` | 308 | The engine's user-visible response surface: runtime-truth, identity and name-source formatting (`format_name_source_audit`) + coercion of what is shown or streamed (`coerce_user_visible`). |
| `visible_output.py`, `visible_text.py` | ~144 | Central visible-output contract; stringify/sanitise streamed output. |
| `response_policy.py`, `response_contracts.py` | ~160 | Classify response mode; per-action contracts. |
| `final_response_provider.py` | 85 | The current action's response contract, per thread: a grounded-answer header on non-quick prompts (`decorate_prompt`) and temperature/token caps (`apply_generation_kwargs`). |

## Personal-memory surfaces
| Module | LOC | Role |
|---|---|---|
| `personal_memory_surface.py` | 452 | "Is this a personal-memory query" + surface builder. |
| `personal_memory_clean_response.py` | 338 | Clean "what do you know about me" report (reset-aware, poison-filtered, dynamic-fact aging). |
| `personal_memory_deep_response.py` | 489 | Routing-fault explain (`build_routing_fault_explanation`); its `build_personal_memory_deep_response` is overridden at import to return the clean report above, so the old schema/tables explain is no longer served. |
| `profile_extractor.py` | 1671 | Extracts user facts from turns (role/interests/field/"remember that I…"), writes user_patterns + LLM session summaries; recency refresh. `_SINGLE_VALUED_PATTERNS` (single source of truth, `user_model.py` imports it) gets belief-weighed supersession with revision history on a correction, not accumulation of contradictory rows. |
| `identity_validation.py` | 211 | Validate identity candidates. |

## Typed pipeline plumbing (evidence/packets)
| Module | LOC | Role |
|---|---|---|
| `evidence_ledger.py` | 759 | Records artifacts/events with signatures in a tamper-evident HMAC-keyed chain (`verify_chain`); recent generated artifacts; status evidence; recency-weighted action reliability. |
| `evidence_arbitration.py` | 212 | Scores competing evidence (stage packets + tool results + goals), dedup-by-fingerprint, keep-max. |
| `stage_packet_store.py`, `stage_packets.py`, `pipeline_models.py` | ~177 | The typed packet substrate: route/plan/evidence/generation/output packets flow between stages; this is the plumbing behind "no fake actions". |
| `background_tasks.py` | 479 | In-process multi-threaded task manager (heavy work → job id → `CHECK_JOB`). |
| `runtime_policy.py` | 124 | Per-turn budgets/timeouts/context size from runtime snapshot. |

## Security
| Module | LOC | Role |
|---|---|---|
| `security.py` | 76 | `SecurityManager.is_path_allowed`: the folders `CREATE_FILE` may write in (the project, home, `ELI_ALLOW_ROOTS` split on the OS path separator), built once per setting by `get_security_manager()`. The live command gate is `execution/shell_gate.py`. |

---

# Part 3 — `cognition/` module catalogue (52 files, 23.7k lines)

The thinking layer: agents, orchestration, inference, persona, reasoning, governance.

## Orchestration & agents
| Module | LOC | Role |
|---|---|---|
| `agent_bus.py` | 3575 | 15 built-in specialist agents on a dependency DAG (topological layers) + calibrated weight-free confidence aggregation + per-action agent selection; custom agents attach as `AgentSpec` agents or trusted code (`agent_trust`). |
| `orchestrator.py` | 1477 | Gradient 12-stage pipeline (all CHAT modes): intent → persona lock → HyDE → planner → keyword/semantic/document/KG retrieval (`retrieve_for_turn()`) → hybrid merge → heuristic rerank → `dispatch_specialists()` → context assembly → generation → finalise. Composes the specialist bus; a non-CHAT action gets executor evidence instead of retrieval. |
| `learning_coordinator.py` | 102 | Stage 12 `finalize_turn()` — store assistant turn, publish meta, `_learn_from_result()`. The latter is gated by `source` (`CognitiveEngine._is_autonomous_source()`): a habit-scheduler-fired turn doesn't feed `habit_events`, so ELI's own automation can't reinforce itself as fresh evidence of a user routine. |
| `hyde.py` | 69 | Hypothetical-document-embedding query expansion. |
| `reranker.py` | 176 | Stage 9 candidate reranking (token overlap + recency + source bonus); reciprocal-rank fusion of ranked lists (`fuse_ranked_lists`, used by memory search). |
| `introspection_agent.py` | 164 | Wraps introspection for the bus (pipeline/memory/runtime/audit). |
| `llm_intent.py` | 389 | LLM intent parsing fallback (GGUF, cached) over the live action list, never the internal or explicit-only actions; used only when `action_trust` says the loaded model chooses well. |

## Inference
| Module | LOC | Role |
|---|---|---|
| `gguf_inference.py` | 2759 | Model-agnostic GGUF inference: model resolution (no baked model), the model's own chat template (`chat_template.py`; family formats only for a file without one), graceful GPU-layer fallback that stops on failures no setting can fix (a GPU the machine does not have, a file this runtime cannot read), streaming, output cleaning (only a closing "(Note: …)" is stripped), token budgeting, the fixed prompt prefix's model state kept for reuse. |
| `inference_broker.py` | 257 | Thin GGUF broker (`infer`, passing temperature and `top_p`) used by agents/coding/patching; tracks foreground activity so background calls yield. |

## Reasoning & engagement
| Module | LOC | Role |
|---|---|---|
| `reasoning_modes.py` | 678 | The 5 modes — canonicalisation, per-mode private system instruction, execution contract (samples/branches/stages + dynamic token budget), reasoning-leak stripping. |
| `engagement_tracker.py` | 249 | Session depth tracking → **auto-escalates reasoning mode** (Quick→Normal→Advanced→Research) as a conversation deepens; session narrative. |
| `working_memory.py` | 430 | Turn-scoped pinned facts (pin/absorb/evict/persist/restore). |

## Context & grounding
| Module | LOC | Role |
|---|---|---|
| `context_synthesiser.py` | 818 | Builds the precise prompt context: persona handoff, turns block, vector block, live-runtime brief, budgeting. |
| `grounded_status.py` | 648 | Identity + memory-inventory rendered directly from profile/DBs (direct grounded answers). |

## Persona (the living voice)
| Module | LOC | Role |
|---|---|---|
| `persona.py` | 372 | Canonical persona authority — base + auto sections, preferences, compose/refresh. |
| `persona_updater.py` | 750 | Re-derives the persona overlay from memory/reflection/habits/runtime patterns; KG population; stale-fact aging. |
| `persona_hygiene.py` | 130 | Cleans/dedups/prunes the auto-persona. |
| `persona_status.py`, `persona_values.py` | ~112 | Persona status report; values store. |

## Output governance (consolidated this session)
| Module | LOC | Role |
|---|---|---|
| `output_governor.py` | 1547 | **Canonical** governance: sanitize, role-prefix/identity-drift repair (a speaker label needs a colon or a spaced dash, so `USER-M000` and `AI-generated` stay words), self↔user confusion repair, style cleanup, confabulation detection (fabricated actions, diagnostics, self-status), memory-worthiness, GGUF-artifact cleaning (`clean_gguf_artifacts`), evidence validation. |
| `tone_analyzer.py` | 371 | Analyses recent user turns → tone preferences ELI adapts to over time. |

## Profile
| Module | LOC | Role |
|---|---|---|
| `user_info_builder.py` | 756 | The living, versioned user profile: multi-source gather, noise filter, categorise, hash, diff-on-change. |

---

# Part 4 — remaining packages (module catalogue)

## `kernel/` (the engine + boot) — 19.3k lines
| Module | LOC | Role |
|---|---|---|
| `engine.py` | 17431 | `CognitiveEngine` — the conductor: persona, generation settings, the per-mode reasoning passes (`_run_chain_of_thought`, `_run_self_consistency`, `_run_tree_of_thoughts`, `_run_constitutional_ai`, chosen by `_run_mode_algorithm`), grounding overrides, synthesis prompt build + the context-bloat cap, fragment/placeholder guards, dispatch gate to bus vs orchestrator, startup loops (reflection/habit/scheduler/self-improve/proactive). Each message is fitted to the loaded model first (Part 5). |
| `world_model.py` | 278 | Symbolic self-model: Identity/Runtime/Memory/Goal/Capability states + snapshot/merge. |
| `pipeline_trace.py` | 85 | Canonical S01–S12 stage names and `log_pipeline_stage()` observability. |
| `state.py` | 364 | User/runtime state + profile (active user id, name, profile text, communication style). |
| `self_upgrade.py` | 564 | Self-upgrade orchestrator, steps chosen by install kind (AppImage, packaged build, source: release wheel, git pull, pip) + rebuild FAISS/KG, manifest, system index. |
| `scheduler.py` | 65 | Kernel thread-pool/timer scheduler (generic). |
| `pipeline.py` | 147 | Pipeline step description. |
| `prompt_rules.py` | 225 | The system-prompt rule block, assembled per turn: each guard (added for an observed failure) is included only when the turn can need it, and the full block whenever the turn cannot be assessed (`select_rules`). |
| `request_context.py` | 110 | Per-turn state as ContextVars (session, user, request id, reasoning mode, turn facts, input channel, the API caller's role) and a session-keyed store, so concurrent API requests never share a turn. |

## `core/` (paths, settings, hardware, safety) — 12.4k lines
| Module | LOC | Role |
|---|---|---|
| `runtime_settings.py` | 1235 | Canonical settings.json load/save, legacy-key migration, portable-path healing/sanitising. |
| `hardware_profile.py` | 3257 | Auto-detect GPU/VRAM/RAM → fit ctx/gpu_layers/batch (KV-cache + compute-buffer reserve); model discovery (`discover_models`: `paths.models_dir()` and the program's own `models/`); hardware authority enforcement. |
| `paths.py` | 828 | Single-source-of-truth path resolution (data/config/cache/db/models/voices…): `models_dir()` honours `ELI_MODELS_DIR`, `notes_dir()` (every note) is `<data dir>/notes` unless `ELI_NOTES_DIR` says otherwise, `notebook_dir()` (where WRITE_NOTE's pages went up to 2.5.36, still read) `<data dir>/notebook` unless `ELI_NOTEBOOK_DIR` does. |
| `startup_hardware_optimizer.py` | 237 | A model's trained context, the context free RAM holds, and the reasoning-mode budgets sized from the context that loaded; what loads where is `load_plan.py`'s job. |
| `config.py` | 364 | Thin config shim over runtime_settings (canonical key mapping). |
| `model_download.py` | 676 | Curated GGUF catalogue + VRAM-based recommend + download (install-time only; ELI loads whatever `.gguf` files it finds). |
| `dag.py` | 475 | **Generic DAG engine** (Kahn topo-order, parallel layers, critical path) — shared by the agent bus, the coding engine and MULTI_COMMAND. |
| `netguard.py` | 615 | **Offline-by-default** socket-level network gate (fail-closed) + `guarded_urlopen`/`http_get_json`; telemetry hosts refused whatever the setting. |
| `memory_reset.py` | 333 | Factory-reset of memory/identity (scrub names, clear DBs, backup). |
| `cognition_tunables.py` | 342 | User-tunable knowledge-gathering limits + synthesis cap registry (GUI-surfaced). |
| `grounding.py` | 145 | `is_grounded_query` classifier. |
| `crisis_guard.py` | 113 | STT-robust self-harm detector + persona steering directive. |
| `portable_paths.py`, `db_paths.py`, `legacy_paths.py` | small | path helpers. |

## `memory/` — 10.6k lines
| Module | LOC | Role |
|---|---|---|
| `memory.py` | 6008 | The `Memory` class (88 public methods): semantic store/recall, conversations, habits, failures/improvements, storage policy, upkeep (merge, archive, vector compaction), weight decay, KG bridge, `forget` (a memory and everything derived from it, Part 1 §11), `mark_failure_resolved`, `disable_invalid_habit_rules`. |
| `knowledge_graph.py` | 758 | Entity/relation graph + multi-hop BFS (`related`) + `context_for_prompt` + extract-from-memory. A preference is stored only from "I/user (really/also …) like/love/prefer X"; dislikes, "don't like", "looks like" and "would like" are not. |
| `retrieval.py` | 327 | Shared turn retrieval (`retrieve_for_turn`) with an 8 s cache, time window and `memory_diag` stats. |
| `policy.py` | 128 | Storage policy: origin, dedupe key, forgetting curve, archive rule. |
| `claims.py` | 406 | Bitemporal claims about the user: valid interval, learned-at, supersession, extraction. Forgetting a memory deletes the claims that rested only on it (`purge_from_memories`). |
| `unified_retrieval.py` | 373 | Orchestrator stages consume `retrieve_for_turn` through it. |
| `vector_store.py` | 788 | FAISS index (L2, 1/(1+dist) sim) + nomic embedder + keyword fallback (forgotten memories skipped) + auto-rebuild; `compact_tombstones` takes forgotten rows out of the index files (after each forget and in the daily upkeep); saving takes its locks in one fixed order. |
| `system_index.py` | 283 | OS app/exe/dir index in `system_index.sqlite3` (`find_app`, `find_path`), built at first run and refreshed by SELF_UPGRADE. App launching does not read it: OPEN_APP resolves names through `portable_app_control`. |
| `memory_truth.py`, `memory_adapter.py` | small | inspection/compat/session helpers. |

## `perception/` — 10.8k lines
| Module | LOC | Role |
|---|---|---|
| `audio_stt.py` | 2487 | faster-whisper STT + VoiceGate (wake-word, debounce, incomplete-command wait), self-echo suppression, output ducking, per-user voice profile bias. |
| `vision.py` | 713 | Local GGUF VL (Moondream fast / primary), hot-swap with text model, CPU-pinned CLIP, OCR. |
| `tts_router.py` | 1368 | Piper/espeak TTS, voice selection, unspeakable-fragment guard; plays at the device's own rate when it refuses the voice's. |
| `audio_samples.py` | 74 | A sound file as one channel of float32 samples at the rate a consumer needs (speech input, playback, the wake word, the voice profile): PCM WAV read with the standard library, other formats with soundfile. |
| `os_controller.py` | 673 | Screenshot/volume/keys/mouse/clipboard + `gaze_click`. |
| `screen_locator.py` | 497 | OCR (tesseract) → locate a named UI element on screen. |
| `gaze_engine.py` | 350 | MediaPipe face-gaze + calibration mapper + One-Euro smoothing → `latest_gaze.json` @10Hz. |
| `local_whisper_stt.py`, `ambient_vision.py`, `analyze_{pdfs,image,csv}.py`, `log_rotation.py`, `voice_worker*.py` | ~1.4k | Whisper backend; ambient glances; file analysers; log rotation; voice workers. |

## `planning/` (autonomy, habits, proactive) — 4.4k lines
| Module | LOC | Role |
|---|---|---|
| `proactive_daemon.py` | 1583 | Background 10-min loop: pattern/code analysis, habit detect+offer, morning report, error tracking. |
| `autonomy_scheduler.py` | 334 | Policy-gated (observe/proposal/goal-driven) goal scheduler w/ cooldown + attention queue. |
| `habits.py` | 370 | Habit detection (circular time-of-day clustering, shift and lapse notes), offer/pending state, disabled-by-default. |
| `routine_stats.py` | 125 | Circular clustering, routine shift and lapse detection. |
| `habits_scheduler.py` | 170 | Fires active habits at their time (self-heals legacy rows, once-per-minute dedupe). |
| `goal_store.py`, `goal_models.py`, `goal_tick.py`, `operator_goal_actions.py` | ~550 | Mission goals (priority/cadence/risk/constraints/success-criteria) → governed proposals; tasks (`open_task`, `close_task`, `find_task`). |
| `attention_queue.py`, `proposal_queue.py`, `proposal_*.py`, `jobqueue*.py`, `autonomy_controller.py` | ~890 | Attention ranking; proposal queue/archive; job queue; safe autonomy ticks. |

## `coding/` (the frontier coder) — 2.1k lines
| Module | LOC | Role |
|---|---|---|
| `agent.py` | 215 | `CodeAgent.solve` — composes the loop; broker-backed generator; full provenance. |
| `bug_memory.py` | 340 | Bug classification + (signature→fix) long-term SQLite memory w/ fuzzy recall. |
| `verification.py` | 353 | Gate ladder (syntax→exec→tests) + weighted scoring + test synthesis. |
| `sandbox.py` | 234 | Bounded isolated execution (scrubbed env, CPU limit, timeout). |
| `search.py` | 176 | UCB1 tree search over a temperature-ladder beam. |
| `plan_graph.py` | 164 | Subtask DAG decompose + topological solve + compose. |
| `planner.py`, `cost.py` | ~230 | Planner/implementer split; cost → foreground/background decision. |

## `learning/` (real LoRA self-training) — 4.3k lines
| Module | LOC | Role |
|---|---|---|
| `lora_trainer.py` | 834 | Real torch/PEFT/transformers `Trainer` LoRA run. |
| `lora_trainer_guard.py` | 630 | `TrainerTarget` plans + safety validation. |
| `dataset_builder.py` | 552 | Build supervised dataset from logged turns/corrections (PII-redacted, deduped). |
| `lora_eval.py` | 505 | Adapter eval suite. |
| `bootstrap_phi3_base.py`, `base_model_resolver.py`, `dataset_filters.py`, `export_trainable_dataset.py`, `merge_reviewed_datasets.py`, `training_preflight.py` | ~1.1k | Trainable base download/resolve, quality gates, export/merge, preflight. |

## `contracts/`, `integrations/`, `system/`, `utils/`, `cli/`
| Module | LOC | Role |
|---|---|---|
| `contracts/runtime_status.py` | 546 | Canonical runtime-status evidence contract (detect question, build live evidence, validate/repair). |
| `contracts/grounded_control.py` | 278 | Grounded-control synthesis guard (evidence-complete? suppress bad clarifications). |
| `integrations/mpris/playerctl_backend.py` | 780 | MPRIS2/playerctl media backend (player resolve, transport, status, volume); on Windows and macOS transport goes through `integrations/media/system_session.py`, then the system media keys. |
| `integrations/ollama/client.py` | 593 | Optional Ollama backend client, used only when Ollama is the chosen backend (`ollama_chosen`). |
| `system/portable_app_control.py` | 1100 | Cross-platform installed-app discovery (desktop entries, `.app` bundles, the Start menu) + open/close/minimise/maximise/focus and window management (tile, next/previous, workspaces). |
| `utils/platform_compat.py` | 1955 | Cross-platform layer (open url/file/app, the first installed app for a role such as mail, music, ide or settings (`open_role`), volume, clipboard, notify, user folders, executables). |
| `utils/log.py`, `cli/headless.py` | ~200 | Central logger; headless terminal REPL. |

## `world/` (embodied self-model) — 1.9k lines
| Module | LOC | Role |
|---|---|---|
| `agency/autonomy_engine.py` | 324 | Awareness vector (easing/decay) → avatar-room routing + symbolic-object creation during reasoning; provenance/snapshots/journal. |
| `agency/{policy,goal_ecology,habit_engine,reflection_bridge,world_constitution}.py` | small | Permission classes; goal decay; default habits; reflection→world; world identity. |
| `core/schemas.py`, `core/ontology.py` | ~160 | World state schemas (rooms/objects/events/actions/awareness); object templates. |
| `renderers/pyside6/{world_scene,world_panel}.py` | ~520 | The PySide6 "Eli's World" tab (house/rooms/avatar/objects, live state). |
| `avatar/*`, `persistence/*`, `world_event_bus.py`, `local_world_bridge.py` | ~750 | Avatar behaviour/locomotion/persona-map; journal/provenance/snapshots/storage; event bus + bridge. |

## `gui/` (PySide6 desktop) — 26.7k lines
| Module | LOC | Role |
|---|---|---|
| `eli_pro_audio_gui_v2_0.py` | 12542 | Main window: 17 top-level tabs (Chat, Proactive, Habits, Self-Improve, Quick Actions, Screen, IDE, Images, Eli's World, Labs, Coding, Tasks, Experimental, Report Builder, Files, Audit, Settings) + adapters (CentralMemory/LocalModel/Ollama/Executor bridges, the `_GUIEngineAdapter`), chat, drag-drop, reasoning-mode auto-select, all toggles. |
| `labs_tab.py` | 5747 | Labs workspace: Notebook, Memory & Conversations, Jupyter, Calculator, Physics, File Chat, Workspaces, Sim / IDE, Orchestration, Test & Review and Training tabs; also the **Report Builder** (evidence-grounded docs) the main window shows as its own tab. |
| `app.py` | 325 | Launcher: hardware-aware model selector with auto-tuned parameters (`main()`). |
| `panels/startup.py` | 2204 | StartupModelSelectionDialog, FirstBootWizard, HardwareTuningDock. |
| `panels/settings.py` | 818 | Advanced Settings (Agents/Models/**Cognition**/Plugins/Marketplace/Self-Upgrade). |
| `docks/operator_console_dock.py` | 303 | Governed operator console (proposals/goals/policy/attention). |
| `widgets/`, `tabs/`, `panels/agent_wizard.py`, `docks/proactive_dock.py`, `qt_compat.py` | ~3.9k | ELI's face, Ollama selector, voice downloader; world, experimental, marketplace, tasks and training tabs; agent wizard, proactive dock, Qt shim. |

## `plugins/` — 10 bundled plugins + manager
| Module | Role |
|---|---|
| `manager.py` (670L) | Discover/install (pip dependencies; download, or the bundled copy of a built-in)/uninstall/enable/disable/search/dispatch; auto-load; registry (`registry/index.json`). |
| `web`, `web_automation`, `weather`, `calendar`, `notes`, `pomodoro`, `system_stats`, `media`, `tts`, `document_reader` | The 10 bundled plugins (see Part 1 §17: several declare actions the executor answers itself). |
| `base/base.py` | Plugin base class + action validation + loader. |

---

# Part 7 — modules not covered above

Every remaining module under `eli/`, with its line count and a one-line role (the module's own
docstring where it has one). Modules Part 4 names only inside a group (`avatar/*`, `persistence/*`,
`widgets/`, `tabs/`, `voice_worker*.py`, `jobqueue*.py`, `proposal_*.py`) are listed here one by
one. Package `__init__.py` files that are empty or only re-export (e.g. `coding/`, `gui/panels/`,
`integrations/media/`, `integrations/mcp/`, `onboarding/`, `setup/`, `tools/image_engine/`) are not
listed. `tools/refresh_doc_metrics.py` rewrites the count on rows whose file name has no folder and
is unique under `eli/`; recount the others with `wc -l`.

## `runtime/`
| Module | Lines | Role |
|---|---:|---|
| `active_project.py` | 78 | Active project signal. |
| `api_users.py` | 145 | API users + roles (admin / member / viewer RBAC) for the web server. |
| `authority_gate.py` | 86 | Who may have ELI carry out an action: `check()` refuses a caller whose role is below admin (`request_context.caller_role_var`, set by the API) the owner-only actions (`owner_only()`: shell, code, file read/write, screen, clipboard, keyboard/mouse, plus `llm_intent`'s explicit-only list of settings, plugins, MCP …); the desktop app and ELI's own daemons are the owner. Checked at the executor's entry and on each `SEQUENCE` step; the MCP server withholds the same list. |
| `autopilot_debugger.py` | 424 | Autopilot debugger — one loop that turns a failure into a plan. |
| `background_deepening.py` | 143 | Stage 3b background deepening: a poorly-grounded Quick factual answer is returned at once and re-gathered in the background, surfacing in the Proactive panel only when it does better (Part 6). |
| `ble_light.py` | 247 | BLE light control — the GATT writes ELI never had. |
| `bt_platform.py` | 1340 | Cross-platform Bluetooth radio detection, recovery, and classic discovery. |
| `capability_state.py` | 306 | Incremental per-capability state (discovered, dependency ready, permission, reachable, probes, runs), built up one fact at a time instead of wiped on every manifest regeneration. |
| `codebase_graph.py` | 306 | Codebase self-graph — ELI's live, grounded model of how its OWN code connects. |
| `command_splitter.py` | 426 | Split one utterance that chains several commands into its parts; read a message as sentences and tell an instruction from a statement or a question. A labelled sentence inside a longer message ("Note: …", "Context: …") is material for the question, not an order (`labels_material`); "note: buy milk" on its own still writes a note. Holds the one list of verbs a command starts with. |
| `conversation_thread.py` | 321 | Conversation thread awareness — topic carryover, proactive grounding, web queries. |
| `desktop_launchers.py` | 749 | Redistribution-safe desktop / Start Menu launchers. |
| `deterministic_failure_patches.py` | 108 | Rule-based code patches for recurring executor failures without LLM guessing. |
| `device_drivers.py` | 1121 | Pluggable local-control drivers for ELI's device server, for devices that don't speak MQTT (UPnP/DLNA renderers, Chromecast, Fire TV, AirPlay, Bluetooth), all on the LAN. |
| `device_names.py` | 219 | User-chosen device names — stable keys for voice control across hardware/OS. |
| `device_server.py` | 1566 | ELI's own device server — original, MQTT-first. No Home Assistant. |
| `eval_review.py` | 117 | Eval + LLM-judge board, in the shape Labs ▸ Test & Review already renders. |
| `evidence_planner.py` | 302 | Evidence planner + gatherer — the DAG/plan principle for generative & grounded tasks. |
| `failure_taxonomy.py` | 251 | Classify a runtime failure by what actually went wrong, and where. |
| `folder_analysis.py` | 269 | Reading a folder of PDFs (ANALYZE_PDF_FOLDER): every file kept whole in the document index, one summary covering all of them, the result as a PDF with its formulas typeset. |
| `gguf_runtime_report.py` | 257 | Portable GGUF / inference diagnostics — model-agnostic, path-agnostic. |
| `home_intel.py` | 114 | ELI home intelligence — weave the LLM into the home/device system. |
| `home_mesh.py` | 432 | ELI home mesh — tiered brains with LAN failover. |
| `inference_footprint.py` | 421 | Live inference RAM — read from the loaded llama.cpp model and this process, never guessed. |
| `last_trace.py` | 62 | Persists the last response trace, keyed to the process id so a restart never reports a closed session's turn. |
| `license_info.py` | 118 | Locate and print ELI's licence (Apache-2.0; `eli --license`), wherever ELI happens to be running from. |
| `live_reads.py` | 81 | Cheap reads of the present (ELI's own work, measured health, live facts) made for the turn that asks about them, so a fact one tool call away is not denied. |
| `local_connectivity.py` | 764 | Local-only WiFi and audio routing — sovereign stack, no cloud. |
| `memory_provenance.py` | 153 | Memory provenance and verification tier for grounded recall. |
| `mqtt_setup.py` | 444 | Cross-platform MQTT broker onboarding for ELI redistribution. |
| `native_locks.py` | 39 | Process-wide locks for native llama.cpp and FAISS entry points, preventing cross-context heap corruption. |
| `orchestrator_audit_ledger.py` | 319 | Tamper-evident audit chain for the orchestrator pipeline, metadata only: one row per turn when it really ends (who, from where, action, agents used, confidence); `verify_chain`. |
| `proposal_adapters.py` | 1 | Re-export shim of `planning/proposal_adapters.py`. |
| `reflection.py` | 383 | Reflection engine — analyses memories, conversations, and patterns to extract insights. |
| `lessons.py` | 345 | Expiring, checked lessons from recurring failures (trigger, evidence, predicted outcome, retire when unhelpful). |
| `relational_facts.py` | 83 | Extract relational facts the user mentions in passing. |
| `repair_playbook.py` | 243 | ELI repair playbook — decision guide for self-maintenance, code examine, and upgrades. |
| `report_pipeline.py` | 198 | Multi-stage grounded document pipeline (Report-Builder discipline, chat scale). |
| `research_corpus.py` | 426 | Local research corpus workspaces. |
| `rich_document.py` | 416 | Markdown with LaTeX maths typeset without a TeX installation: matplotlib draws each formula, Python-Markdown lays out the text, Qt writes the PDF (`write_pdf`, `write_docx`). |
| `scheduled_tasks.py` | 569 | Scheduled / overnight advanced tasks. |
| `self_facts.py` | 411 | Verified facts about ELI's own construction, assembled from live sources. |
| `self_maintenance.py` | 181 | Unified self-maintenance orchestration for ELI. |
| `self_maintenance_config.py` | 6 | Shared constants for ELI self-maintenance (analysis windows, cluster gates). |
| `self_model_refresh.py` | 61 | `refresh_all_overlays_nonfatal`: refreshes the persona and user-profile overlays without raising; `refresh_world_model_runtime`. |
| `self_status.py` | 177 | Real, measured self-status for ELI. |
| `server_util.py` | 255 | Helpers for detecting an existing ELI web server and firewall guidance. |
| `session_continuity.py` | 223 | Session continuity — live thread memory injected into every CHAT turn. |
| `shell_followup.py` | 68 | Resolve deictic shell follow-ups ("run that command") from prior assistant output. |
| `site_address.py` | 119 | The address behind a site's name or a reference to one ("nasa website", "that website"): from the conversation, then a web search. Never built from the words. |
| `state_providers.py` | 80 | State providers — the hook that lets components expose save/restore state to a project's "Save State" / "Resume". |
| `test_generator.py` | 291 | ELI-assisted behavioural test generation (Phase 4). |
| `test_review.py` | 234 | Full test/project run → review workflow. |
| `user_model.py` | 371 | Continuous User Model — ELI's living, semantic, auto-updating model of the user. |
| `voice_assets.py` | 558 | Ensure the local voice models (STT + TTS weights) are present. |

## `cognition/`
| Module | Lines | Role |
|---|---:|---|
| `action_trust.py` | 144 | Whether the loaded model may choose actions: a short quiz the first time a model loads, kept per model file; a model that fails keeps every rule and chat but does not pick actions for messages the router did not recognise. |
| `agent_spec.py` | 436 | A real specification for a custom agent — objective, prompt, triggers, measures. |
| `agent_trust.py` | 262 | Trust for custom agent code — provenance, not just a hash in a dict. |
| `belief.py` | 239 | Belief revision — what ELI holds, how strongly, and what it takes to change it. |
| `chat_grounding_gate.py` | 157 | Fail-closed CHAT gate — skip LLM when user-fact grounding is required but absent. |
| `chat_template.py` | 320 | A model's own chat format, rendered from the Jinja template stored in its GGUF (`tokenizer.chat_template`), with its reasoning, stop and scaffold markers. |
| `context_budget.py` | 130 | Sizing and trimming the memory block that goes into a prompt. |
| `correction_patterns.py` | 297 | Shared patterns for user correction / dispute turns. |
| `emotion_palette.py` | 254 | Emotion / tone palette — the shared taxonomy ELI expresses through. |
| `emotion_timeline.py` | 452 | Emotion timeline — the durable record of how the USER has been feeling. |
| `evidence_format.py` | 239 | Dates on evidence lines, from each row's own timestamp; `time_facts` (clock times in the user's message worked out against now); `this_conversation` (the dialogue block holds this conversation, not turns from days ago). |
| `exact_recall_value.py` | 52 | A single value asked for by name ("reply with only the code"), served from what the person said earlier only when the records agree on one. |
| `explicit_output_contract.py` | 85 | Enforces an answer format the user explicitly asked for when the model's text already holds a verifiable candidate; never infers a missing answer or changes a tool result. |
| `expression_state.py` | 63 | Live avatar/expression state — the thin bridge that lets ELI's face react in real time to what he is doing (speaking, amplitude, thinking). |
| `memory_diag.py` | 86 | What memory retrieval actually did this turn, from telemetry, so ELI never has to guess why. States facts only: an absence is said only for a scope that gave nothing (the "Only say nothing is stored" instruction is gone), and a reply claiming the search never ran is corrected (`drop_false_diagnosis`). |
| `model_identity.py` | 240 | Model-agnostic identity: chat family + thinking from GGUF metadata. |
| `model_load_diagnostics.py` | 709 | Say why a GGUF would not load — for ANY model, not a known list of them. Failures no setting can fix ("invalid value for main_gpu" — a GPU the machine does not have, a file this runtime cannot read) stop the retry ladder. |
| `model_output_tokens.py` | 331 | Canonical special tokens, stop sequences, and persona drift patterns for all GGUF families. |
| `personal_context_gate.py` | 118 | Gate when past-session plans/projects may enter the persona handoff. |
| `prompt_dedupe.py` | 94 | One copy of each line of evidence or dialogue per prompt, across the memory block, the persona handoff and the history. |
| `query_planner.py` | 347 | Deterministic query planning: the time window a question asks about. A message that supplies its own facts, or is date arithmetic, opens no window on the user's history. |
| `scoring.py` | 136 | Canonical scoring + confidence primitives for ELI. |
| `self_claims.py` | 1040 | What ELI may say about its own workings: each turn's audit record (what routed it, what ran, why it escalated, what retrieval found) is handed to the model when asked about its behaviour; a sentence naming a setting, table or module ELI does not have, or reporting a switch nothing made, is dropped — in streamed replies too. |
| `stance_capture.py` | 151 | Notice when ELI has taken a position, so it survives the conversation. |
| `stance_store.py` | 318 | Persistence for beliefs — ELI's own positions, and the record of revisions. |
| `supplied_in_message.py` | 224 | What a message brings with it: facts to reason from (`holds_its_own_answer`, sums and date offsets worked out) and text that is material rather than orders (`supplied_as_data`, `without_supplied_text`); shared by grounding, the query planner and the router. |
| `tone_adaptor.py` | 234 | Tone adaptor — decides the emotion ELI *expresses* and feeds every output channel. |
| `turn_dossier.py` | 448 | Turn dossier — single assembly point for awareness, memory, and cognition context. |
| `user_claim_validator.py` | 258 | Post-generation validation of user-attribution claims in CHAT output. |

## `execution/`
| Module | Lines | Role |
|---|---:|---|
| `app_aliases.py` | 119 | Speech-damage layer for app names, on top of the cross-platform resolver. |
| `command_dependency_graph.py` | 60 | MULTI_COMMAND's `infer_dependencies()` — one optional LLM call for dependency edges among an already-split command list, validated via `eli.core.dag`. |
| `command_sequence_log.py` | 102 | MULTI_COMMAND's durable per-step log — crash-survival and skip-already-done on resubmit. |
| `effectors/system_helpers.py` | 179 | Cross-platform system helpers shared by executor and effectors (v3). |
| `execution_planner.py` | 111 | Builds `RouteDecision` and the typed `ExecutionPlan`/`PlanStep` artifacts — `.agent_profile` (agent-name filter) is the only field anything reads; `.steps` is never executed, only rendered as decorative text by `EXECUTE_GOAL`. |
| `executor_enhanced.py` | 15712 | The action executor. `execute()` checks `authority_gate`, runs a middleware table and a chain of wrappers (media, document/script contracts, direct app control, reasoning mode, personal memory, the generated-script guard), then the flat `if a == "ACTION":` dispatch in `_execute_impl`; a plugin is consulted last. |
| `media_runtime.py` | 659 | Media runtime control for ELI. |
| `operator_actions.py` | 105 | Valid states and helpers for operator (proposal) actions: pending, approved, rejected, blocked, pending_confirmation. |
| `operator_policy.py` | 65 | The valid operator policy modes: `proposal_only`, `operator_supervised`, `goal_driven`, `observe_only`. Only `observe_only` (silences the autonomy loop) and `goal_driven` (elevated + self-upgrade scheduling) have distinct behavior — `proposal_only`/`operator_supervised` are currently identical code paths. |
| `portable_intent_contract.py` | 780 | Portable intent rules; hard-blocks document, code and analysis prompts from `PLAY_MEDIA`. The one reading of an "open ..." target that is a website (`web_open_target`) and of the window a command names (`window_target`); "open/start" plus one of ELI's own features is not an app; the language a script request asks for (`infer_script_language`). |
| `route_contracts.py` | 245 | Small predicates that classify a request for the router; whether an action changes anything (`changes_something`) and whether a sentence tells ELI to do what was matched in it (`fits`). |
| `router_enhanced.py` | 9355 | The router: `route(text)` regex-first priority pipeline with LLM-intent fallback (see `architecture.md` §4). |
| `shell_gate.py` | 240 | The live shell-command gate (`check_command`): destructive patterns and denylisted programs refused in every command of a line (`;` `&&` `\|\|` `\|` `&`, newlines, `$( )`, `<( )`, backticks, wrappers such as sudo/env/nice/timeout/xargs/busybox, `env -S`, `find -delete` / `-exec rm`); Full Control lifts it. Protected from self-patching. |

## `core/`
| Module | Lines | Role |
|---|---:|---|
| `confidence.py` | 9 | The one confidence-score to label mapping. |
| `full_control.py` | 46 | ELI Full Control — a single master override that lifts ELI's safety barriers. |
| `gguf_sizes.py` | 441 | What a GGUF model costs in memory — the bytes each layer puts on the GPU and the KV-cache bytes per token — read from the file and corrected by what llama.cpp reports. |
| `gpu_pack_runtime.py` | 85 | Activate the optional GPU pack before llama_cpp is imported (AppImage/portable). |
| `host_env.py` | 141 | The environment a program ELI starts should see: the machine's own, not a frozen bundle's (`LD_LIBRARY_PATH`, `QT_PLUGIN_PATH`, `SSL_CERT_FILE` and friends). |
| `init_data.py` | 283 | First-run data initialiser — build ELI's FULL database architecture up front. |
| `llama_cpu_compat.py` | 240 | CPU compatibility for llama-cpp-python — parity with GPU probe/fallback policy. |
| `load_plan.py` | 1002 | What a model loads with on this machine, and where each part goes, measured before it loads by llama.cpp's load simulation (llama-cpp-python 0.3.35 and later) on every GPU; a machine with no GPU gets processor-only arguments (`main_gpu=-1`). |
| `mem_units.py` | 50 | One place to turn bytes into the GiB/MiB figures ELI reports and compares. |
| `model_tier.py` | 141 | Model-capability tier — the single signal that lets ELI's cognition budgets auto-scale to whatever model is loaded. |
| `moe_offload.py` | 162 | Keep a mixture-of-experts model's expert tensors in RAM and everything else on the GPU. |
| `secure_io.py` | 94 | Race-free writing of files that must never be world-readable. |
| `self_provenance.py` | 207 | Is this row ELI's own bookkeeping, or evidence about the user? |
| `singleton_refs.py` | 58 | Keep `None`, `True` and `False` from being freed by an extension that drops references to them (Python before 3.12). |
| `sqlite_util.py` | 127 | Shared SQLite pragmas — WAL with a portable-safe fallback. |
| `toml_util.py` | 19 | Load TOML on Python 3.10+ (tomli backport) and 3.11+ (stdlib tomllib). |
| `worldclock.py` | 348 | Place-aware wall-clock answers. |

## `memory/`
| Module | Lines | Role |
|---|---:|---|
| `__init__.py` | 278 | The package facade: `Memory`, `get_memory` and the compatibility helpers (`add_memory`, `search_memory`, `recall_recent`, `store_memory`, `recall_memory`, `log_event`, `get_memory_status`). |
| `document_index.py` | 916 | The document index: every document ELI has read, kept whole and found again by passage (the orchestrator's document channel); forgetting a document removes it with its passages and vectors, not the file. |

## `perception/`
| Module | Lines | Role |
|---|---:|---|
| `desktop_capabilities.py` | 186 | Cross-OS desktop control capability probe — one place for per-platform truth. |
| `mic_resolver.py` | 613 | ELI microphone resolver — pick a capture device that actually delivers audio, for any user on any machine, Bluetooth or wired, with no manual configuration. |
| `screen_analysis.py` | 194 | Local screen analysis — depth modes, memory recall, research context. |
| `tts_xtts.py` | 394 | Voice cloning backend (Coqui XTTS-v2). |
| `ui_ground.py` | 322 | Optional UI grounding backends — 100% local by default. |
| `ui_tree.py` | 380 | Accessibility-tree UI targeting (Linux / AT-SPI). |
| `voice_fx.py` | 252 | Character-voice effects layer. |
| `voice_profile.py` | 410 | Voice profile + prosody — the foundation for tone/emotion detection. |
| `voice_worker_streaming.py` | 61 | Stream-aware voice worker for ELI. |
| `wakeword.py` | 443 | Self-trained, fully-local wake-word detector (openWakeWord features + a custom head). |

## `planning/`
| Module | Lines | Role |
|---|---:|---|
| `goal_autogenesis.py` | 224 | Turns ELI's own signals (world-model suggestions, recurring failures) into proposal-only goals, deduped by a stable id and capped (`propose_goals_from_signals`). |
| `insight_synthesis.py` | 136 | Cached, background-synthesised reflection insight. |
| `jobqueue.py` | 184 | Durable SQLite-backed job queue for external subprocess jobs; files under `<data>/jobs`. |
| `jobqueue_cli.py` | 59 | Durable background jobs that run as separate processes and survive a restart. |
| `proposal_adapters.py` | 165 | Adapters that make proposal execution results look like `subprocess.CompletedProcess`. |
| `proposal_memory_bridge.py` | 64 | Bridge that records proposal outcomes into memory through safe calls. |
| `proposal_models.py` | 48 | `ProposalRecord`: kind, payload, source, priority. |

## `coding/`
| Module | Lines | Role |
|---|---:|---|
| `code_mode.py` | 91 | Code-mode — the model writes a small program against ELI's own capabilities. |
| `repo_context.py` | 91 | Repo-context retrieval for the coding agent (Advancement C). |
| `restricted_exec.py` | 170 | In-process restricted execution for code-mode. |

## `learning/`
| Module | Lines | Role |
|---|---:|---|
| `lora_pipeline.py` | 149 | LoRA training pipeline — a fixed sequence that chains the standalone learning stages. |
| `review_queue.py` | 270 | The human review gate that had no way to be passed. |
| `target_registry.py` | 266 | User-declared LoRA training targets — the registry that replaces the Phi-3 lock. |

## `integrations/`
| Module | Lines | Role |
|---|---:|---|
| `local_gguf/config.py`, `local_gguf/paths.py` | 6 each | Compatibility shims re-exporting `eli.core.config` and `eli.core.paths`. |
| `local_gguf/inference.py` | 2 | Compatibility shim: canonical GGUF inference lives in eli.cognition.gguf_inference. |
| `mcp/client.py` | 322 | ELI as an MCP host: launches configured MCP servers as local subprocesses, speaks JSON-RPC 2.0 over stdio and gains their tools (`status`, `list_tools`, `call_tool`). |
| `mcp/server.py` | 215 | MCP server — ELI's own capabilities exposed to any MCP client, each tool described from the capability table (`capabilities_doc._C`). Without `ELI_MCP_ALLOW_CONTROL=1` it withholds the control actions and the owner-only actions (`authority_gate.owner_only()`: files, screen, clipboard, the shell …) and runs every call as a role below the owner's, so `CHAT`, `MULTI_COMMAND` and `SEQUENCE` cannot reach them either. |
| `media/capabilities.py` | 181 | Runtime media capability probe — what works on THIS machine/OS. |
| `media/cross_platform.py` | 773 | Cross-platform Spotify control and mpv IPC. |
| `media/media_deps.py` | 203 | Discover media CLI tools — bundled install root, then system PATH. |
| `media/spotify_intent.py` | 153 | Parse user phrasing into Spotify playback intents (no Web API). |
| `media/system_session.py` | 217 | What is playing, and control of it, on Windows (the system media session) and macOS; Linux uses MPRIS. |
| `media/youtube_playback.py` | 344 | Shared YouTube playback helpers — mpv, yt-dlp clients, browser URLs. |

## `system/`
| Module | Lines | Role |
|---|---:|---|
| `process_guard.py` | 473 | Verified process-kill safety for CLOSE_APP and friends. |

## `utils/`
| Module | Lines | Role |
|---|---:|---|
| `jsonio.py` | 40 | Small tolerant JSON readers shared across the runtime. |
| `native_io.py` | 74 | Silence stderr written by C extensions, at the file-descriptor level. |

## `onboarding/`
| Module | Lines | Role |
|---|---:|---|
| `interview.py` | 748 | Light, skippable first-run onboarding interview. |

## `setup/`
| Module | Lines | Role |
|---|---:|---|
| `__main__.py` | 48 | Entry: python -m eli.setup [--wizard] [--launch] [--status] [--full-install] |
| `hardware_policy.py` | 330 | Install-time accelerator inventory and CPU-only recommendation. |
| `install_backend.py` | 185 | Cross-platform install backend — streams install.sh / install.ps1 into GUI progress. |
| `install_messages.py` | 116 | Curated installer copy — ELI voice: direct, dry, nerdy, occasionally a pisstaker. |
| `platform_profile.py` | 142 | Install-time platform detection — routes GUI, headless, and Android profiles. |
| `status.py` | 120 | Read-only setup completeness checks for first-run / grandparent setup. |
| `unified_installer.py` | 686 | One-click GUI installer — backend terminal work with OS-style progress and ELI wit. |
| `wizard.py` | 298 | Grandparent-ready graphical setup wizard — every first-run stage in one place. |

## `world/`
| Module | Lines | Role |
|---|---:|---|
| `avatar/behaviour_controller.py` | 36 | `AvatarBehaviourController.choose_room`: picks the room from the awareness vector (anomaly room on low evidence, memory archive on low memory confidence). |
| `avatar/locomotion.py` | 17 | Room coordinates and `target_for_room`. |
| `avatar/persona_mapper.py` | 40 | `PersonaToAvatarMapper`: maps persona and awareness to avatar tint and expression. |
| `persistence/journal.py` | 25 | World journal path and append helper (`journal_path`, `append_journal_entry`). |
| `persistence/provenance.py` | 22 | World provenance ledger (`ledger_path`, `make_provenance_id`, `record_provenance`). |
| `persistence/snapshots.py` | 35 | World snapshots (`snapshot_dir`, `create_snapshot`, `latest_snapshot`, `restore_snapshot`). |
| `persistence/storage.py` | 273 | World state directory resolution and load and save of world state. |

## `gui/`
| Module | Lines | Role |
|---|---:|---|
| `branding.py` | 143 | Shared ELI branding assets (window icon, Freedesktop theme, Windows .ico). |
| `code_editor.py` | 220 | Native code editor for the IDE — PySide6/PyQt, no QScintilla required. |
| `coding_tab.py` | 178 | The Coding tab: type a task, pick a language, and the verified coding agent runs its full pipeline. |
| `off_thread.py` | 41 | Blocking work off the Qt window's thread while the window keeps painting (`run_pumping`), shared by the main and start-up windows. |
| `panels/_qt.py` | 33 | Shared Qt import shim for eli.gui.panels modules. |
| `panels/permission_dialog.py` | 232 | The consent dialog — the moment the operator actually decides. |
| `tabs/eli_world_tab.py` | 11 | The Eli's World tab: wraps `EliWorldPanel`. |
| `tabs/experimental_tab.py` | 170 | Read-only workbench over the `experimental/` folder: lists prototype kits and opens their folders or READMEs. |
| `tabs/marketplace_tab.py` | 991 | Settings ▸ Plugins ▸ Marketplace — browse, scan, install, and revoke. |
| `tabs/tasks_tab.py` | 307 | The Tasks tab: advanced, scheduled and overnight work in the shared BackgroundTasks pool (coding jobs, timed tasks). |
| `tabs/training_tab.py` | 841 | ELI v2.0 — Labs ▸ Training. The GUI half of the LoRA pipeline. |
| `widgets/eli_face.py` | 230 | ELI's animated face — a procedural 2D face that shows the tone_adaptor's emotion. |
| `widgets/ollama_model_selector.py` | 494 | Ollama model selector widget for ELI GUI. |
| `widgets/voice_downloader.py` | 282 | Voice library browser — acquire additional Piper voices, accents and tones. |

## `plugins/`
| Module | Lines | Role |
|---|---:|---|
| `base.py` | 4 | Dead stub that raises ImportError; `eli.plugins.base` resolves to the `base/` package. |
| `calendar/plugin.py` | 27 | Calendar plugin: its `list` and `add` actions go to `runtime/agenda.py` (`do_list_events`, `do_add_event`), the store the executor's ADD_EVENT / LIST_EVENTS use. |
| `document_reader/plugin.py` | 417 | Document reader plugin: reads and indexes PDF and docx files. |
| `integrity.py` | 291 | Integrity and publisher identity for community plugins. |
| `manifest.py` | 302 | Plugin manifests: what a plugin says it is, checked against what it does. |
| `marketplace.py` | 793 | ELI's plugin marketplace client — federated, community-hosted, consent-gated. |
| `mcp.py` | 481 | MCP servers: one config ELI owns, and an install that proves it works. |
| `media/plugin.py` | 171 | Media control plugin: a thin wrapper over `integrations/mpris/playerctl_backend.py`. |
| `notes/plugin.py` | 35 | Notes plugin: its `new_note`, `list_notes`, `search_notes` run ELI's own NEW_NOTE / LIST_NOTES / SEARCH_NOTES. |
| `permissions.py` | 395 | Android-style consent for plugins: allow always, allow once, reject. |
| `pomodoro/plugin.py` | 36 | Pomodoro plugin: its `start`, `stop`, `status` run ELI's own POMODORO_* actions. |
| `sandbox.py` | 283 | Runtime capability enforcement for loaded plugins: what a plugin may do once it runs, on top of the manifest, hash and scanner checks made before. |
| `security_scan.py` | 547 | Multi-engine malware scanner for community plugins. |
| `subprocess_sandbox.py` | 349 | Containment for child processes — the gap netguard structurally cannot cover. |
| `system_stats/plugin.py` | 35 | System stats plugin: its actions run ELI's own `CPU_USAGE`, `RAM_USAGE`, `SYSTEM_STATS`. |
| `tts/plugin.py` | 20 | TTS plugin: its `speak`, `say`, `tts` run ELI's own `SPEAK` (through `tts_router`). |
| `weather/plugin.py` | 187 | Weather plugin: `GET_WEATHER` (open-meteo geocoding plus forecast, toggle-gated). Current conditions, or the forecast for a named day; a day word is never the place. |
| `web/plugin.py` | 645 | Web plugin: search (SearXNG when configured, else DuckDuckGo; safe search on by default) and `read_page`, which the executor's `WEB_SEARCH` and `WEB_FETCH` call (toggle-gated). |
| `web_automation/plugin.py` | 92 | Web Automation plugin for ELI – lazy Playwright import, safe under broken installs. |

## `tools/`
| Module | Lines | Role |
|---|---:|---|
| `api.py` | 73 | eli.api — a small, curated callable surface over ELI's action executor. |
| `image_engine/fetch_model.py` | 59 | Fetch a diffusers image model's weights into the local models dir. |
| `image_engine/gui_bridge.py` | 453 | Bridge between the GUI image tab and the engine: `ImageGenerationRequest`, model and preset discovery, recent outputs. |
| `image_engine/image_engine/__main__.py` | 3 | `python -m` entry for the image engine CLI. |
| `image_engine/image_engine/cli.py` | 312 | Command-line interface for the image engine. |
| `image_engine/image_engine/contracts.py` | 126 | `EngineConfig`, `JobRequest`, `ArtifactRecord`, `JobResult`. |
| `image_engine/image_engine/memory.py` | 169 | `ImageMemory`: a small SQLite index of generated images, plots and jobs. |
| `image_engine/image_engine/plotting.py` | 324 | Loads records and plots them with matplotlib. |
| `image_engine/image_engine/project_analyzer.py` | 41 | `analyze_project_profile`, `infer_style_hints`: derives a colour and style profile from a project path. |
| `image_engine/image_engine/prompt_compiler.py` | 118 | `VisualBrief` and `PromptCompiler`: turns a request into a structured visual brief. |
| `image_engine/image_engine/quality.py` | 94 | Image hashing and scoring (`score_image`, `choose_best`). |
| `image_engine/image_engine/service.py` | 369 | `ImageEngine`: runs image jobs and records artifacts. |
| `image_engine/image_engine/visual_core.py` | 1446 | The procedural renderer: scene types, composition, palettes, atmosphere and post-processing. |
| `image_engine/runtime_paths.py` | 130 | Resolves image-engine paths from the project root or the data directory. |
| `mic_diag.py` | 149 | Microphone diagnostic: probes every input device for one that delivers audio, then measures speech against ambient energy to set the threshold. |
| `news/news_fetcher.py` | 577 | News and current-events fetcher (standard-library `urllib`; articles stored for reading offline, `search_stored_news`). |
| `news/news_synthesis.py` | 926 | News synthesis: every 3 hours the window's articles are summarised into `news_reflections` (a window with no articles advances the cadence but is not stored as a memory); the briefing NEWS_FETCH reads, interest news for the morning report, the 24-hour digest (`build_morning_digest`). |
| `registry/capabilities_doc.py` | 395 | capabilities_doc.py — regenerate blueprints/capabilities_and_actions.md. |
| `registry/capability_registry.py` | 38 | Process-local capability registry (`register_capability`). |
| `registry/capability_updater.py` | 200 | Writes `capability_manifest.json` from `CapabilitySync.discover()` (only when the capabilities changed), keeps per-capability state and regenerates `capabilities_and_actions.md`; `capability_status` says what has worked on this machine. |

## package root
| Module | Lines | Role |
|---|---:|---|
| `__init__.py` | 52 | Package init: printing never fails on a non-Unicode stream, library telemetry is switched off before anything loads (onnxruntime, Hugging Face, Gradio, OpenTelemetry …), and GPUs are numbered in PCI bus order. |
| `__main__.py` | 93 | Console entry point. `python -m eli` and the `eli` script both call this. |

## `scripts/`
| Module | Lines | Role |
|---|---:|---|
| `rebuild_vector_index.py` | 137 | Rebuild the FAISS vector index from scratch from the SQLite memories. |

---

# Part 5 — engine request lifecycle (`engine.process`)

The entry flow, in order:

1. **Turn id** — the request's id (`request_context.request_id_var`, else a fresh `eng-…`);
   with `ELI_PIPELINE_TRACE` set, every stage is logged against it (observability).
2. **Prompt-injection guard FIRST** — `_eli_sanitize_user_input` runs before the
   router or LLM ever sees the raw text, so injected instructions can't reach
   them unsanitised. (A security control that sits at the very top of the pipe.) It also
   fits the message to what the loaded model can read: its context window less the reply's
   room (`ELI_MAX_INPUT_LEN` overrides); a longer message keeps its start and end, with the
   middle marked as left out (`_eli_max_input_chars` / `_eli_fit_input`). There is no fixed
   8,192-character cut.
3. **Multi-question splitter** (`kernel/engine.py`) — if a message has more than
   one `?`, more than 25 words and is not conversational, it splits into
   standalone sub-questions (each at least 6 words and opening like a question, at most 4) and
   answers each, so genuinely multi-part asks get multiple grounded answers. A part that
   continues the one before ("…? or are you …") stops the split.
4. Router → **gradient orchestrator** (all CHAT modes, depth by reasoning mode) →
   shared retrieval → specialist bus composition → governed output (Parts 1–4).
   Fallback: direct `AgentBus.dispatch()` if orchestration fails.

Note: `engine.py` still carries 37 lines with `PHASE…` markers: layered patches whose
residue (engine 17.4k / executor 15.7k / GUI 12.5k lines) is documented here at
behavioural level, not line by line.

---

# Part 6 — reasoning modes & autonomous deepening

The 5 reasoning modes were renamed (public layer; internal keys unchanged) and
made adaptive + self-deepening.

| Public mode | Internal key | Multi-pass algorithm | Agent time budget | Deepen iters | Confidence target |
|---|---|---|---|---|---|
| **Quick** | quick | single pass | 1.0× | 0 (never) | 0.45 |
| **Normal** | chain_of_thought | one reasoned pass | 1.0× | 1 | 0.55 |
| **Advanced** | self_consistency | N samples + consensus | 1.5× | 2 | 0.65 |
| **Research** | tree_of_thoughts | branch + prune | 2.0× | 3 | 0.75 |
| **Expert** | constitutional_ai | draft → critique → revise | 2.5× | 4 | 0.80 |

**Auto-selection** (`cognition/engagement_tracker.py`): the mode is escalated
automatically as a conversation deepens (Quick→Normal→Advanced→Research) without the
user asking. (Internal strategy keys are stable; users only ever see the public names.)

**Per-mode agent time budgets** (`reasoning_modes.mode_budget_multiplier`,
Stage 1b): each mode scales every agent's timeout — quick/normal unchanged,
deeper modes get proportionally more time. Threaded via `intent["_mode_budget_mult"]`
→ `agent_bus._collect_layer`. Tunable in the Cognition tab (`cog.mode_budget_*`).

**Confidence-driven iterative deepening** (`runtime/grounding_escalation.escalate`,
Stage 2): on a poorly-grounded *checkable-factual* turn, ELI re-dispatches the
agent bus broadly, **escalating the reasoning mode one tier per iteration** and
(Stage 3a) **raising the gather budget** each pass (1.5×→2.0×→2.5×), until grounding
crosses the per-mode target or the per-mode iteration budget is spent (early
no-improvement break). Banter/opinion/command/meta never deepen.

**Background deepening** (`runtime/background_deepening.py`, Stage 3b): a Quick
answer returns instantly; if it was a poorly-grounded factual turn, a background
thread keeps gathering (broad re-dispatch at Advanced + 2× gather) and surfaces a
better answer in the Proactive panel **only if** it crosses grounding 0.55 and
isn't degenerate. Tightly gated (quick-only, grounding<0.40, factual-only,
deduped, 1 in-flight, 10-min cooldown). Toggle: `cog.background_deepen` /
`ELI_BACKGROUND_DEEPEN`.
