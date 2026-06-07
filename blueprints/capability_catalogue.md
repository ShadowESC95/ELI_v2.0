# ELI Capability Catalogue — every action & module, what it actually does

> **Purpose.** A systematic, ground-truth catalogue built by reading the real
> handlers and modules — not summarised from memory. It exists because
> conversational summaries of a 126k-LOC project keep undershooting; this is the
> persisted, exhaustive map. Built in committed batches.
>
> **Method.** Action list comes from the live `capability_manifest.json` (193
> entries: 180 executor/router + 13 plugin-backed), verified against the
> `executor_enhanced.py` dispatch. Behaviour grounded in the handlers and the
> subsystem blueprints. Where a description is inferred from name+structure
> rather than a line-by-line handler read, it is marked *(inferred)*.
>
> **Status:** Batch 1 — action catalogue (this file will grow with the
> runtime/ + cognition/ module catalogues and the remaining unread files).

---

## Headline finding: 193 is real but aliased

The manifest's 193 is honest (it's *measured* by `capability_sync`, not asserted)
but inflated by **alias families** — multiple action names routing to one
behaviour. Collapsed, there are roughly **~110 distinct capabilities**. Alias
families are grouped below so the real surface is visible.

---

## 1. Conversation & reasoning
| Action(s) | What it does |
|---|---|
| `CHAT` | The default — full cognitive pipeline (router→agents→orchestrator→reasoning mode→governed output). |
| `ANSWER`, `DIRECT_RESPONSE`, `SAY` | Direct/short response surfaces (lighter than CHAT). *(inferred for some)* |
| `SET_AI_MODE` | Set the reasoning mode (quick / chain_of_thought / self_consistency / tree_of_thoughts / constitutional_ai). |
| `SEQUENCE`, `SEQUENCE_STEP` | Multi-step action chaining (run a sequence of actions). *(inferred)* |
| `TEMPLATE`, `NOOP` | Internal scaffolding / no-op. |

## 2. OS & application control
| Action(s) | What it does |
|---|---|
| `OPEN_APP` = `OPEN_APPLICATION` = `LAUNCH_APP` | Launch an app, resolved via the `system_index` (7,843 executables) + `portable_app_control`. On failure → **remediation offer** (install it). |
| `CLOSE_APP` = `CLOSE_APPLICATION` = `EXIT_APP` = `QUIT_APP` | Close/quit an app. |
| `FOCUS_APP`, `HIDE_APP` | Focus / hide a window. |
| `MINIMISE_APP` = `MINIMIZE_APP`, `MINIMISE_WINDOW` = `MINIMIZE_WINDOW`, `MAXIMISE_WINDOW` | Window state control (UK/US spellings aliased). |
| `MINIMISE_ALL`, `RESTORE_WINDOWS`, `TILE_WINDOWS`, `NEXT_WINDOW`, `PREVIOUS_WINDOW` | Desktop window management. |
| `SWITCH_WORKSPACE` | Switch virtual desktop/workspace. |
| `OPEN_SYSTEM_SETTINGS`, `OPEN_AUDIO_SETTINGS`, `OPEN_POWER_SETTINGS`, `OPEN_FILE_SYSTEM`, `OPEN_COMMUNICATION_HUB`, `OPEN_MEDIA_HUB`, `OPEN_NETWORK_BROWSER` | Open specific OS setting panels / hub launchers. |
| `OPEN_IDE`, `OPEN_IN_IDE` | Open the IDE (optionally at a file). |
| `OPEN_BROWSER`, `OPEN_URL` | Open browser / a URL (local hand-off; respects net toggle for fetches). |

## 3. Input & screen control
| Action(s) | What it does |
|---|---|
| `KEYBOARD` | Send keypresses (`os_controller.press_key`). |
| `MOUSE_CONTROL` | Move/click the mouse (`os_controller.mouse_click`). |
| `VOLUME` | Get/set system volume. |
| `SET_CLIPBOARD`, `GET_CLIPBOARD` | Read/write the clipboard. |
| `SCREENSHOT` | Capture the screen. |

## 4. Gaze (webcam eye-tracking)
| Action(s) | What it does |
|---|---|
| `GAZE_ENABLE`, `GAZE_DISABLE` | Start/stop the MediaPipe gaze engine (writes `latest_gaze.json` @10Hz). |
| `GAZE_CALIBRATE` | Run gaze calibration. |
| `GAZE_CLICK` | Move the cursor to where you're looking and click. |
| `GAZE_STATUS` | Report gaze-engine state. |

## 5. Media
| Action(s) | What it does |
|---|---|
| `PLAY_MEDIA` | Play a song/playlist on a named platform (Spotify playlist-tab / YouTube Mix-radio); honest about reachability; explicit platform never falls through to a second. |
| `PAUSE_MEDIA`, `STOP_MEDIA`, `NEXT_MEDIA`, `PREVIOUS_MEDIA`, `REPEAT_MEDIA`, `SHUFFLE_MEDIA` | MPRIS/playerctl transport control. |
| `MEDIA_CONTROL` | Generic media-control dispatch. |
| `SKIP_YOUTUBE_AD` | Skip a YouTube ad. *(inferred)* |

## 6. Files & documents
| Action(s) | What it does |
|---|---|
| `CREATE_FILE`, `CREATE_FOLDER`, `READ_FILE`, `LIST_DIR` | Filesystem ops (path-allowlist gated). |
| `SUMMARIZE_FILE` | Summarise a file's contents (also the route for "read your persona.auto.txt / settings"). |
| `CONVERT_DOCUMENT` | Convert document formats. |
| `CREATE_DOCUMENT` = `CREATE_DOC` = `DOC_GENERATE` = `GENERATE_DOCUMENT` = `WRITE_DOCUMENT` | Generate a document (the Report-Builder family). |
| `ANALYZE_CSV`, `ANALYZE_PDF`, `ANALYZE_PDF_FOLDER`, `ANALYZE_IMAGE`, `OCR_IMAGE` | Local file-type analysers (CSV stats, PDF text/structure, image VL description, OCR). |

## 7. Vision & screen understanding
| Action(s) | What it does |
|---|---|
| `ANALYZE_IMAGE` | Local GGUF vision-language description of an image. |
| `OCR_IMAGE` | Tesseract OCR text extraction. |
| `AMBIENT_VISION` | Toggle periodic background screen glances. |
| `SCREEN_LOCATE` | OCR-locate a named UI element on screen ("the button that says X"). |
| `SCREEN_READ_ANALYZE` | Screenshot → analyse what's on screen. |
| `IMAGE_STATUS` | Report vision/image-engine state. |

## 8. Coding & code-repair
| Action(s) | What it does |
|---|---|
| `CODE_SOLVE` | The frontier coding agent: plan → DAG decompose → UCB tree search → verify (syntax/exec/tests) → repair → bug-memory. |
| `GENERATE_SCRIPT` = `CREATE_SCRIPT` = `WRITE_SCRIPT` = `GENERATE_CODE` = `WRITE_CODE` | Generate a script — routes through the coding agent (falls back to inline gen). |
| `GENERATE_PROJECT` | Generate a multi-file project. |
| `EXAMINE_CODE` | Tiered file scan (syntax/import → lint → gated LLM logic review) → offer fix. |
| `FIX_FILE`, `CONFIRM_CODE_FIX`, `CANCEL_CODE_FIX` | Apply/confirm/cancel a verified auto-reverting code fix. |
| `FILE_AUDIT`, `SHOW_DIFF`, `CODE_CHANGES` | Audit a file / show a diff / report recent code changes. |

## 9. Self-management & self-improvement
| Action(s) | What it does |
|---|---|
| `SELF_REPORT` | Grounded runtime self-report (deterministic, from live state). |
| `SELF_ANALYZE`, `SELF_IMPROVE`, `SELF_IMPROVEMENT_LOG` | Analyse failures / surface improvement proposals / show the improvement log. |
| `SELF_PATCH` | Generate+apply a verified self-patch. |
| `SELF_TEST` | Run self-tests. |
| `SELF_UPGRADE` = `SELF_UPDATE` | Maintenance: git pull, pip, rebuild FAISS/KG, refresh manifest + system index. |

## 10. Introspection & audits (grounded, deterministic)
| Action(s) | What it does |
|---|---|
| `RUNTIME_STATUS`, `RUNTIME_AUDIT` | Live runtime report; RUNTIME_AUDIT also runs **health probes** (plugin mgr, memory, agent bus, habit integrity, recent failures). |
| `GUI_RUNTIME_AUDIT`, `IMPORT_AUDIT`, `DIAGNOSE_WRAPPERS`, `RESOLVE_RUNTIME_PATHS` | GUI/runtime audits, import smoke-audit, executor-wrapper diagnostic, path resolution. |
| `FRONTIER_STATUS`, `ELI_IDENTITY_AUDIT` | Full cross-system matrix / identity-classification audit. |
| `COGNITION_STATUS`, `EXPLAIN_COGNITION_RUNTIME`, `EXPLAIN_MEMORY_RUNTIME` | Cognition + memory runtime explainers (verbatim, deterministic). |
| `EXPLAIN_ALL_REASONING_MODES`, `REASONING_MODE_STATUS` | Describe the 5 reasoning modes / current mode. |
| `EXPLAIN_LAST_RESPONSE`, `EXPLAIN_LAST_FAILURE`, `NAME_SOURCE_AUDIT`, `ROUTING_FAULT_EXPLAIN` | Explain the last answer/failure, the source of your name, or a routing fault. |
| `HARDWARE_PROFILE`, `GPU_STATUS`, `GET_STATUS`, `AWARENESS_STATUS` | Hardware/GPU/general/awareness status. |
| `HELP`, `LIST_CAPABILITIES` | Help / list the capability surface. |

## 11. Memory & identity
| Action(s) | What it does |
|---|---|
| `MEMORY_RECALL`, `MEMORY_STORE`, `MEMORY_STATS`, `MEMORY_STATUS` | Recall/store memories; memory inventory/stats. |
| `PERSONAL_MEMORY_SUMMARY`, `PERSONAL_MEMORY_DEEP_EXPLAIN` | "What do you know about me" (clean) / deep memory-internals explain. |
| `USER_IDENTITY_SUMMARY`, `USER_INFO_REPORT`, `REFRESH_USER_INFO` | Who-you-are summary / full profile report / rebuild the living profile. |
| `SET_USER_NAME` | Set the user's name. |
| `MESSAGE_TIME_QUERY` | "What time did I first/last message (today)" — from `conversation_turns`. |
| `CLEAR_CHAT_HISTORY` | Clear chat history. |
| `PERSONA_LOCK_SET`, `PERSONA_LOCK_CLEAR`, `PERSONA_LOCK_STATUS` | Lock/unlock/inspect the persona. |

## 12. Habits, proactivity & goals
| Action(s) | What it does |
|---|---|
| `CONFIRM_HABIT`, `DECLINE_HABIT`, `HABIT_STATUS` | Approve/decline a detected habit; report habits. |
| `MORNING_REPORT` | The consolidated morning brief (news digest + activity + attention). |
| `PROACTIVE_START`, `PROACTIVE_STOP`, `PROACTIVE_STATUS` | Control the proactive daemon. |
| `EXECUTE_GOAL` | Execute a mission-layer goal (governed). |
| `BACKGROUND_JOBS`, `CHECK_JOB` | List background tasks / check a job id. |

## 13. Self-healing remediation (Linux)
| Action(s) | What it does |
|---|---|
| `PREPARE_REMEDIATION` | Diagnose a failure + build a repair plan (e.g. install a missing app via apt/snap/flatpak). |
| `CONFIRM_PENDING_REMEDIATION`, `CANCEL_PENDING_REMEDIATION` | Execute / cancel the pending repair (sudo terminal, lock-handling, verification). |
| `CHECK_TARGET_STATUS` | Check whether a target app/path is now present. |

## 14. Voice & transcription
| Action(s) | What it does |
|---|---|
| `DICTATE`, `TRANSCRIBE` | Dictation / transcribe audio (faster-whisper). |
| `LISTEN_FOR_COMMAND` | One-shot listen. |
| `STT_DIAGNOSTICS`, `VOICE_DIAGNOSTICS` | Diagnose the STT/voice pipeline (mic, ducking, wake gate). |
| `SAY` / `SPEAK` *(plugin: tts)* | Speak text (Piper TTS). |

## 15. Time, timers & utility
| Action(s) | What it does |
|---|---|
| `TIME` = `GET_TIME`, `DATE` = `GET_DATE` | Current time / date. |
| `SET_TIMER`, `SET_ALARM` | Timers/alarms. *(inferred)* |
| `CHECK_CHRONAL_ALIGNMENT` | An easter-egg / curiosity action. |
| `DATA_FABRICATOR` | Generate synthetic/sample data. *(inferred)* |
| `RUN_CMD`, `SHELL_EXEC` | Run a shell command — **fail-closed** (blocked unless `ELI_ALLOWED_CMDS`/`ELI_FULL_CONTROL`). |

## 16. Plugins (management)
| Action(s) | What it does |
|---|---|
| `PLUGIN_LIST`, `PLUGIN_SEARCH`, `PLUGIN_STATUS` | List installed / search registry / status. |
| `PLUGIN_INSTALL`, `PLUGIN_UNINSTALL`, `PLUGIN_ENABLE`, `PLUGIN_DISABLE` | Install/remove/enable/disable a plugin. |

## 17. Plugin-backed capabilities (the 13)
| Action | Plugin | What it does |
|---|---|---|
| `WEB_SEARCH` | web | DuckDuckGo/SearXNG web search (toggle-gated). |
| `GET_WEATHER` | weather | Local geocode + open-meteo (toggle-gated). |
| `NEW_NOTE`/`WRITE_NOTE`, `LIST_NOTES`, `SEARCH_NOTES` | notes | Markdown notes with FTS. |
| `ADD_EVENT`, `LIST_EVENTS` | calendar | ICS calendar events. |
| `POMODORO_START`, `POMODORO_STOP`, `POMODORO_STATUS` | pomodoro | Focus timers. |
| `CPU_USAGE`, `RAM_USAGE`, `SYSTEM_STATS` | system_stats | CPU/RAM/disk/network. |
| `SMART_HOME` | smart_home | Home Assistant device control. |
| `SPEAK` | tts | Text-to-speech. |
| `NEWS_FETCH` | (executor + news tool) | Fetch + synthesise news (rolling 3-hourly reflections → 24h digest). |

*(Also reachable: `web_automation` plugin — Playwright browser navigate/search/screenshot; `document_reader` plugin — PDF/docx read+index.)*

---

## Reading note
Alias families that collapse the count: app-open (3), app-close (4), minimise
(4 across window/app + UK/US), document-generate (5), script/code-generate (5),
time/date (2 each), self-upgrade/update (2). Removing pure aliases yields
**~110 genuinely distinct capabilities** — still an unusually broad surface for a
local single-user assistant, spanning OS control, media, files, vision, gaze,
voice, coding, memory, introspection, autonomy, remediation, and plugins.


---

## Update Advisory — 2026-06-07
- Created this session (Batch 1: action catalogue). Next batches: the `runtime/`
  (70 files) and `cognition/` (26 files) module catalogues, then the remaining
  unread bodies (GUI, full `gguf_inference`, `persona_updater`, `profile_extractor`,
  the learning trainer internals, the world renderers, every plugin's logic).
