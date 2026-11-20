# Silent `except: pass` audit

**Remaining count: 164** (the ceiling tests/claims/test_no_silent_swallow.py holds the count to; it only goes down)

v2.3.84 converted **469** handlers (where `log = get_logger(__name__)` was already in scope or safely added). This document lists **remaining** handlers still using bare `pass`.

## Index by file

| File | Count |
|------|------:|
| `eli/gui/eli_pro_audio_gui_v2_0.py` | 12 |
| `eli/cognition/working_memory.py` | 5 |
| `eli/core/model_download.py` | 5 |
| `eli/kernel/engine.py` | 5 |
| `eli/cognition/output_governor.py` | 4 |
| `eli/perception/vision.py` | 4 |
| `eli/planning/insight_synthesis.py` | 4 |
| `eli/runtime/device_names.py` | 4 |
| `eli/runtime/grounded_remediation.py` | 4 |
| `eli/cognition/context_synthesiser.py` | 3 |
| `eli/cognition/grounded_status.py` | 3 |
| `eli/cognition/user_info_builder.py` | 3 |
| `eli/core/netguard.py` | 3 |
| `eli/gui/docks/operator_console_dock.py` | 3 |
| `eli/kernel/self_upgrade.py` | 3 |
| `eli/learning/lora_eval.py` | 3 |
| `eli/perception/analyze_csv.py` | 3 |
| `eli/plugins/document_reader/plugin.py` | 3 |
| `eli/runtime/personal_memory_surface.py` | 3 |
| `eli/runtime/user_model.py` | 3 |
| `eli/tools/image_engine/gui_bridge.py` | 3 |
| `eli/world/renderers/pyside6/world_scene.py` | 3 |
| `eli/cognition/query_planner.py` | 2 |
| `eli/core/model_tier.py` | 2 |
| `eli/core/runtime_settings.py` | 2 |
| `eli/gui/panels/settings.py` | 2 |
| `eli/gui/panels/startup.py` | 2 |
| `eli/memory/__init__.py` | 2 |
| `eli/memory/memory.py` | 2 |
| `eli/perception/log_rotation.py` | 2 |
| `eli/plugins/web/plugin.py` | 2 |
| `eli/runtime/active_project.py` | 2 |
| `eli/runtime/evidence_arbitration.py` | 2 |
| `eli/runtime/operator_state.py` | 2 |
| `eli/runtime/profile_extractor.py` | 2 |
| `eli/runtime/server_util.py` | 2 |
| `eli/runtime/truth_report.py` | 2 |
| `eli/runtime/user_visible_response_surface.py` | 2 |
| `eli/tools/api.py` | 2 |
| `eli/tools/image_engine/runtime_paths.py` | 2 |
| `eli/world/world_event_bus.py` | 2 |
| `eli/cli/headless.py` | 1 |
| `eli/cognition/context_budget.py` | 1 |
| `eli/cognition/evidence_format.py` | 1 |
| `eli/cognition/llm_intent.py` | 1 |
| `eli/cognition/persona_values.py` | 1 |
| `eli/cognition/stance_store.py` | 1 |
| `eli/contracts/grounded_control.py` | 1 |
| `eli/core/dag.py` | 1 |
| `eli/core/db_paths.py` | 1 |
| `eli/core/full_control.py` | 1 |
| `eli/core/init_data.py` | 1 |
| `eli/core/legacy_paths.py` | 1 |
| `eli/execution/portable_intent_contract.py` | 1 |
| `eli/execution/router_enhanced.py` | 1 |
| `eli/integrations/ollama/client.py` | 1 |
| `eli/kernel/scheduler.py` | 1 |
| `eli/learning/dataset_builder.py` | 1 |
| `eli/memory/memory_truth.py` | 1 |
| `eli/memory/vector_store.py` | 1 |
| `eli/perception/analyze_image.py` | 1 |
| `eli/perception/local_whisper_stt.py` | 1 |
| `eli/perception/os_controller.py` | 1 |
| `eli/planning/goal_store.py` | 1 |
| `eli/runtime/api_users.py` | 1 |
| `eli/runtime/approval_engine.py` | 1 |
| `eli/runtime/control_contracts.py` | 1 |
| `eli/runtime/evidence_ledger.py` | 1 |
| `eli/runtime/experimental_inventory.py` | 1 |
| `eli/runtime/final_response_provider.py` | 1 |
| `eli/runtime/generated_script_guard.py` | 1 |
| `eli/runtime/license_info.py` | 1 |
| `eli/runtime/personal_memory_clean_response.py` | 1 |
| `eli/runtime/reasoning_status.py` | 1 |
| `eli/runtime/runtime_policy.py` | 1 |
| `eli/runtime/security.py` | 1 |
| `eli/runtime/stage_packet_store.py` | 1 |
| `eli/tools/image_engine/image_engine/visual_core.py` | 1 |
| `eli/tools/news/news_fetcher.py` | 1 |
| `eli/tools/registry/capability_updater.py` | 1 |
| `eli/world/agency/reflection_bridge.py` | 1 |

---

## `eli/cli/headless.py` (1)

### Line 136 — `def run_headless()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  134|         try:
  135|             engine.shutdown()
  136|         except Exception:
  137|             pass
```

## `eli/cognition/context_budget.py` (1)

### Line 32 — `def output_reserve_tokens()`

- **Except:** `ValueError`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   30|         try:
   31|             return max(1, int(env))
   32|         except ValueError:
   33|             pass
```

## `eli/cognition/context_synthesiser.py` (3)

### Line 649 — `def build_persona_handoff()`

- **Except:** `_SkipWorldState`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  647|                 + "\n".join(f"  {p}" for p in _world_parts)
  648|             )
  649|     except _SkipWorldState:
  650|         pass          # not a world question — nothing about rooms reaches the model
```

### Line 180 — `def synthesise()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  178|             if _uname:
  179|                 sections.append(f'USER:\nName: {_uname}')
  180|         except Exception:
  181|             pass
```

### Line 242 — `def _build_turns_block()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  240|                 if should_exclude_turn_from_prompt(role, content):
  241|                     continue
  242|             except Exception:
  243|                 pass
```

## `eli/cognition/evidence_format.py` (1)

### Line 157 — `def date_facts()`

- **Except:** `ValueError`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  155|         try:
  156|             by_pos.setdefault(pos, []).append(datetime(int(y), mo, d))
  157|         except ValueError:
  158|             pass
```

## `eli/cognition/grounded_status.py` (3)

### Line 131 — `def _best_text_column()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  129|             if "TEXT" in col_type or "CHAR" in col_type or "CLOB" in col_type:
  130|                 candidates.append(col_name)
  131|     except Exception:
  132|         pass
```

### Line 60 — `def _load_profile()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   58|                     data["_source"] = str(p)
   59|                     return data
   60|             except Exception:
   61|                 pass
```

### Line 393 — `def _infer_identity_from_memory()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  391|                         if found.get("preferred_name") and found.get("name"):
  392|                             return found, evidence[:12]
  393|                 except Exception:
  394|                     pass
```

## `eli/cognition/llm_intent.py` (1)

### Line 245 — `def is_plain_statement()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  243|         if _attachment_marker_path(t):
  244|             return False
  245|     except Exception:
  246|         pass
```

## `eli/cognition/output_governor.py` (4)

### Line 77 — `def normalize_assistant_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   75|     try:
   76|         result = repair_local_persona_drift(result, user_input=user_input).strip()
   77|     except Exception:
   78|         pass
```

### Line 722 — `def _runtime_user_facts()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  720|             if len(parts) > 1:
  721|                 facts["last_name"] = parts[-1]
  722|     except Exception:
  723|         pass
```

### Line 737 — `def _runtime_user_facts()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  735|             if k in _USER_FACT_KEYS and v:
  736|                 facts[k] = str(v).strip()
  737|     except Exception:
  738|         pass
```

### Line 1202 — `def validate_against_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1200|             if Path(match).exists():
 1201|                 continue
 1202|         except Exception:
 1203|             pass
```

## `eli/cognition/persona_values.py` (1)

### Line 32 — `def load_values()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   30|             merged.update(data)
   31|             return merged
   32|     except Exception:
   33|         pass
```

## `eli/cognition/query_planner.py` (2)

### Line 91 — `def add()`

- **Except:** `ValueError`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   89|                 day = datetime(day.year - 1, mo, d)
   90|             found.append((pos, day))
   91|         except ValueError:
   92|             pass
```

### Line 100 — `def _explicit_dates()`

- **Except:** `ValueError`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   98|         try:
   99|             by_pos.setdefault(pos, []).append(datetime(int(y), mo, d))
  100|         except ValueError:
  101|             pass
```

## `eli/cognition/stance_store.py` (1)

### Line 83 — `def ensure_tables()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   81|         try:
   82|             cur.execute(stmt)
   83|         except Exception:
   84|             pass  # already present on an existing install
```

## `eli/cognition/user_info_builder.py` (3)

### Line 732 — `def _bg_loop()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  730|         try:
  731|             maybe_refresh_user_info(reason="scheduled")
  732|         except Exception:
  733|             pass
```

### Line 754 — `def _flush()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  752|         try:
  753|             refresh_user_info(force=True, reason="process_exit")
  754|         except Exception:
  755|             pass
```

### Line 612 — `def refresh_user_info()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  610|                 recent_turns = _gather_recent_turns(conn, user_id=user_id)
  611|                 conn.close()
  612|             except Exception:
  613|                 pass
```

## `eli/cognition/working_memory.py` (5)

### Line 211 — `def absorb_user_message()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  209|             if _nm:
  210|                 self.pin(f"User's name is {_nm}", source="identity_extract", importance=0.85)
  211|         except Exception:
  212|             pass
```

### Line 334 — `def persist()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  332|             conn.commit()
  333|             conn.close()
  334|         except Exception:
  335|             pass
```

### Line 373 — `def restore()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  371|             self._evict_stale()
  372|             loaded = min(loaded, len(self._facts))
  373|         except Exception:
  374|             pass
```

### Line 268 — `def context_block()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  266|                     said = turn_stamp(fact.ts, now)
  267|                     age = f"(said {said})" if said else age
  268|                 except Exception:
  269|                     pass
```

### Line 294 — `def flush_to_memory()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  292|                     )
  293|                     saved += 1
  294|                 except Exception:
  295|                     pass
```

## `eli/contracts/grounded_control.py` (1)

### Line 247 — `def evidence_gap_reason()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  245|         if rel.get("n", 0) >= 5 and rel.get("p", 1.0) < 0.4:
  246|             return "unreliable_tool"
  247|     except Exception:
  248|         pass
```

## `eli/core/dag.py` (1)

### Line 390 — `def _emit()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  388|                 try:
  389|                     self.on_event(o.id, o)
  390|                 except Exception:
  391|                     pass
```

## `eli/core/db_paths.py` (1)

### Line 60 — `def get_db_paths()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   58|     try:
   59|         _db_dir().mkdir(parents=True, exist_ok=True)
   60|     except Exception:
   61|         pass
```

## `eli/core/full_control.py` (1)

### Line 41 — `def set_full_control()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   39|         from eli.core.config import set as _set
   40|         _set("full_control", enabled)
   41|     except Exception:
   42|         pass
```

## `eli/core/init_data.py` (1)

### Line 42 — `def init_all_data()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   40|         if hint:
   41|             results.append(("platform_hint", True, hint))
   42|     except Exception:
   43|         pass
```

## `eli/core/legacy_paths.py` (1)

### Line 60 — `def migrate_text_file()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   58|             )
   59|             return canonical_path
   60|         except Exception:
   61|             pass
```

## `eli/core/model_download.py` (5)

### Line 246 — `def _load_override_catalog()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  244|     try:
  245|         candidates.append(models_dir() / "catalog.json")
  246|     except Exception:
  247|         pass
```

### Line 206 — `def aux_status()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  204|             out["size_mib"] = round(nbytes / (1024 * 1024), 1)
  205|             out["size_gib_actual"] = round(file_size_gib(path), 2)
  206|         except Exception:
  207|             pass
```

### Line 565 — `def interactive_select()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  563|             from eli.core.hardware_profile import detect_hardware
  564|             free = (getattr(detect_hardware(), "free_vram_mb", 0) or 0) / 1024.0
  565|         except Exception:
  566|             pass
```

### Line 436 — `def download_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  434|                     try:
  435|                         progress_cb(downloaded, total)
  436|                     except Exception:
  437|                         pass
```

### Line 450 — `def download_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  448|                             try:
  449|                                 progress_cb(downloaded, total)
  450|                             except Exception:
  451|                                 pass
```

## `eli/core/model_tier.py` (2)

### Line 48 — `def _file_gb()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   46|         if p and Path(p).exists():
   47|             return Path(p).stat().st_size / (1024.0 ** 3)
   48|     except Exception:
   49|         pass
```

### Line 94 — `def record_speed()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   92|             return
   93|         _speed_ema = v if _speed_ema <= 0 else (_SPEED_ALPHA * v + (1.0 - _SPEED_ALPHA) * _speed_ema)
   94|     except Exception:
   95|         pass
```

## `eli/core/netguard.py` (3)

### Line 87 — `def _net_allowed()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   85|         if is_full_control():
   86|             return True
   87|     except Exception:
   88|         pass
```

### Line 284 — `def _record_egress()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  282|                 except Exception:
  283|                     pass            # queue full → ring still has it; drop the ledger write
  284|     except Exception:
  285|         pass
```

### Line 282 — `def _record_egress()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  280|                 try:
  281|                     _egress_q.put_nowait((nh, port, ts))
  282|                 except Exception:
  283|                     pass            # queue full → ring still has it; drop the ledger write
```

## `eli/core/runtime_settings.py` (2)

### Line 296 — `def pinned_gpu_layers_for_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  294|             if int(s.get("hw_profile_n_gpu_layers") or 0) == pin:
  295|                 return None
  296|         except Exception:
  297|             pass
```

### Line 697 — `def save_settings()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  695|     if "n_threads" in existing:
  696|         try: existing["n_threads"] = int(existing["n_threads"])
  697|         except Exception: pass
  698|     if "n_gpu_layers" in existing:
```

## `eli/execution/portable_intent_contract.py` (1)

### Line 641 — `def try_route()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  639|             if raw_m:
  640|                 query = _clean_target(raw_m.group(1))
  641|         except Exception:
  642|             pass
```

## `eli/execution/router_enhanced.py` (1)

### Line 6487 — `def _eli_self_improvement_phrase_guard()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 6485|                 },
 6486|             }
 6487|     except Exception:
 6488|         pass
```

## `eli/gui/docks/operator_console_dock.py` (3)

### Line 256 — `def refresh_all()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  254|             if idx >= 0:
  255|                 self.policy_mode.setCurrentIndex(idx)
  256|         except Exception:
  257|             pass
```

### Line 267 — `def refresh_all()`

- **Except:** `Exception`
- **Why it exists / risk:** GUI optional widget/audio path — often pre-log binding; convert carefully after boot logger exists.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  265|             try:
  266|                 item.setData(Qt.ItemDataRole.UserRole, pid)
  267|             except Exception:
  268|                 pass
```

### Line 280 — `def refresh_all()`

- **Except:** `Exception`
- **Why it exists / risk:** GUI optional widget/audio path — often pre-log binding; convert carefully after boot logger exists.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  278|             try:
  279|                 item.setData(Qt.ItemDataRole.UserRole, gid)
  280|             except Exception:
  281|                 pass
```

## `eli/gui/eli_pro_audio_gui_v2_0.py` (12)

### Line 2516 — `def _on_auto_speak_toggled()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 2514|         self._tts_auto = checked
 2515|         try: self.auto_speak_btn.setText('🔊 Auto-Speak: ON' if checked else '🔇 Auto-Speak: OFF')
 2516|         except Exception: pass
 2517| 
```

### Line 11016 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
11014|             except Exception: pass
11015|             _acon.close()
11016|         except Exception: pass
11017| 
```

### Line 11027 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
11025|                                  session_id="proactive-gui", user_id="local-user")
11026|             ground["bus_context"] = (_dr.memory_context or "")[:1200]
11027|         except Exception: pass
11028| 
```

### Line 10966 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10964|             try:
10965|                 ground["memories"] = self._central_memory.recall_memory(_q[:300], limit=10) or []
10966|             except Exception: pass
10967|             try:
```

### Line 10969 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10967|             try:
10968|                 ground["recent_conv"] = self._central_memory.get_recent_conversation(limit=20) or []
10969|             except Exception: pass
10970|             try:
```

### Line 10972 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10970|             try:
10971|                 ground["memory_stats"] = memory_system.get_stats() if memory_system else {}
10972|             except Exception: pass
10973|             try:
```

### Line 10977 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10975|                 if vs:
10976|                     ground["faiss_count"] = vs.ntotal
10977|             except Exception: pass
10978| 
```

### Line 10983 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10981|             try:
10982|                 ground["daemon_patterns"] = self._proactive_daemon.analyze_user_patterns() or []
10983|             except Exception: pass
10984|             try:
```

### Line 10988 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10986|                 if mem_h and hasattr(mem_h, "get_habit_rules"):
10987|                     ground["habit_rules"] = mem_h.get_habit_rules(enabled_only=True) or []
10988|             except Exception: pass
10989| 
```

### Line 10999 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10997|                     "SELECT user_input, error, occurrence_count FROM failures "
10998|                     "ORDER BY timestamp DESC LIMIT 8").fetchall()]
10999|             except Exception: pass
11000|             try:
```

### Line 11004 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
11002|                     "SELECT category, detail FROM improvements "
11003|                     "ORDER BY timestamp DESC LIMIT 8").fetchall()]
11004|             except Exception: pass
11005|             try:
```

### Line 11014 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
11012|                     except Exception:
11013|                         ground["agent_obs"].append({"raw": str(content)[:150]})
11014|             except Exception: pass
11015|             _acon.close()
```

## `eli/gui/panels/settings.py` (2)

### Line 448 — `def _populate_models_table()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  446|                 size_str = f"{m.get('size_gb', 0.0):.2f} GB"
  447|                 rows.append((m.get("name", "?"), "GGUF", size_str, m.get("path", "")))
  448|         except Exception:
  449|             pass
```

### Line 458 — `def _populate_models_table()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  456|             for name in ollama_names:
  457|                 rows.append((name, "Ollama", "\u2014", host))
  458|         except Exception:
  459|             pass
```

## `eli/gui/panels/startup.py` (2)

### Line 1117 — `def _populate_compute_mode_combo()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1115|             from eli.core.runtime_settings import load_settings as _ls_cm
 1116|             _saved = str((_ls_cm() or {}).get("compute_mode") or "auto").lower()
 1117|         except Exception:
 1118|             pass
```

### Line 1330 — `def showEvent()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1328|                 if path and self.selected_provider() != "ollama" and Path(path).is_file():
 1329|                     self._select_model_path(path)
 1330|             except Exception:
 1331|                 pass
```

## `eli/integrations/ollama/client.py` (1)

### Line 402 — `def get_active_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  400|         if v:
  401|             return v
  402|     except Exception:
  403|         pass
```

## `eli/kernel/engine.py` (5)

### Line 1915 — `module-level`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1913|     from eli.contracts.grounded_control import FILE_EVIDENCE_ACTIONS as _ELI_FILE_EVIDENCE_ACTIONS
 1914|     _ELI_PHASE19_GROUNDED_FOLLOWUP_ACTIONS |= _ELI_FILE_EVIDENCE_ACTIONS
 1915| except Exception:
 1916|     pass
```

### Line 794 — `def _eli_bad_identity_self_report_output()`

- **Except:** `(ValueError, TypeError)`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  792|             ):
  793|                 return False
  794|     except (ValueError, TypeError):
  795|         pass  # a plain-text reply isn't JSON — expected, fall through to the text checks
```

### Line 7071 — `def _get_chat_response()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 7069|             if _ggi_cancel.is_cancel_requested():
 7070|                 return ""
 7071|         except Exception:
 7072|             pass
```

### Line 10453 — `def _correction_repair()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10451|             if gguf_inference is not None and gguf_inference.is_cancel_requested():
10452|                 return None
10453|         except Exception:
10454|             pass
```

### Line 7364 — `def _get_chat_response()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 7362|                     if _ggi_cancel2.is_cancel_requested():
 7363|                         return ""
 7364|                 except Exception:
 7365|                     pass
```

## `eli/kernel/scheduler.py` (1)

### Line 50 — `def shutdown()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   48|                 try:
   49|                     timer.cancel()
   50|                 except Exception:
   51|                     pass
```

## `eli/kernel/self_upgrade.py` (3)

### Line 234 — `def _local_version()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  232|             if m:
  233|                 return m.group(1)
  234|         except Exception:
  235|             pass
```

### Line 239 — `def _local_version()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  237|             import importlib.metadata as im
  238|             return str(im.version("eli-v2.0"))
  239|         except Exception:
  240|             pass
```

### Line 466 — `def _release_upgrade()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  464|                     p.unlink(missing_ok=True)
  465|                 work.rmdir()
  466|             except Exception:
  467|                 pass
```

## `eli/learning/dataset_builder.py` (1)

### Line 341 — `def load_jsonish_file()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  339|         obj = json.loads(raw)
  340|         return obj if isinstance(obj, list) else [obj]
  341|     except Exception:
  342|         pass
```

## `eli/learning/lora_eval.py` (3)

### Line 62 — `def _patch_dynamic_cache_seen_tokens()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   60|         try:
   61|             DynamicCache.seen_tokens = property(_get_seen_tokens)
   62|         except Exception:
   63|             pass
```

### Line 93 — `def _patch_transformers_cache_compat_v2()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   91|         try:
   92|             DynamicCache.get_max_length = _get_max_length
   93|         except Exception:
   94|             pass
```

### Line 108 — `def _patch_transformers_cache_compat_v2()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  106|         try:
  107|             DynamicCache.get_usable_length = _get_usable_length
  108|         except Exception:
  109|             pass
```

## `eli/memory/__init__.py` (2)

### Line 176 — `def get_memory_status()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  174|                 out["semantic_facts"] = sem
  175|                 out["memory_entries"] = out["memory_entries"] + sem
  176|             except Exception:
  177|                 pass
```

### Line 199 — `def get_memory_status()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  197|                         if _v > _ds:
  198|                             _ds = _v
  199|                     except Exception:
  200|                         pass
```

## `eli/memory/memory.py` (2)

### Line 2933 — `def adaptive_half_life()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 2931|             if _override > 0:
 2932|                 return _override
 2933|         except Exception:
 2934|             pass
```

### Line 5494 — `def get_dashboard_counts()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 5492|             if _eli_table_exists(conn, "semantic"):
 5493|                 try: semantic_count = conn.execute("SELECT COUNT(*) FROM semantic").fetchone()[0] or 0
 5494|                 except Exception: pass
 5495| 
```

## `eli/memory/memory_truth.py` (1)

### Line 31 — `def _artifact_path()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   29|         if val:
   30|             return Path(val).expanduser().resolve().joinpath(*parts)
   31|     except Exception:
   32|         pass
```

## `eli/memory/vector_store.py` (1)

### Line 55 — `def embedder_footprint_gib()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   53|         if path and os.path.exists(path):
   54|             return file_size_gib(path)
   55|     except Exception:
   56|         pass
```

## `eli/perception/analyze_csv.py` (3)

### Line 46 — `def analyze_csv_file()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   44|         try:
   45|             info["nulls"] = int(s.isna().sum())
   46|         except Exception:
   47|             pass
```

### Line 57 — `def analyze_csv_file()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   55|                     info["max"] = float(finite.max())
   56|                     info["mean"] = float(finite.mean())
   57|         except Exception:
   58|             pass
```

### Line 64 — `def analyze_csv_file()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   62|             vc = s.astype(str).value_counts().head(10)
   63|             info["top_values"] = [{"value": k, "count": int(v)} for k, v in vc.items()]
   64|         except Exception:
   65|             pass
```

## `eli/perception/analyze_image.py` (1)

### Line 46 — `def _tesseract_ocr()`

- **Except:** `Exception`
- **Why it exists / risk:** Fallback chain probe (tool/browser/player) — silent failure causes wrong 'nothing works' UX.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   44|             text = out.read_text(encoding="utf-8", errors="replace")
   45|             return " ".join(text.split())[:max_chars]
   46|     except Exception:
   47|         pass
```

## `eli/perception/local_whisper_stt.py` (1)

### Line 158 — `def resident_footprint_gib()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  156|         if hub.is_dir():
  157|             return dir_size_gib(hub)
  158|     except Exception:
  159|         pass
```

## `eli/perception/log_rotation.py` (2)

### Line 114 — `def convlog_append()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  112|         with open(path, "a", encoding="utf-8") as f:
  113|             f.write(json.dumps(rec, ensure_ascii=False) + "\n")
  114|     except Exception:
  115|         pass  # Never crash ELI on logging failure
```

### Line 126 — `def _rotate_current()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  124|         rotated = path.parent / f"{stem}_{suffix}.jsonl"
  125|         path.rename(rotated)
  126|     except Exception:
  127|         pass
```

## `eli/perception/os_controller.py` (1)

### Line 362 — `def set_volume()`

- **Except:** `Exception`
- **Why it exists / risk:** Fallback chain probe (tool/browser/player) — silent failure causes wrong 'nothing works' UX.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  360|                 subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=True, capture_output=True)
  361|                 return {"ok": True, "content": "Unmuted", "response": "Unmuted"}
  362|         except Exception as e:
  363|             pass  # fall through to wpctl
```

## `eli/perception/vision.py` (4)

### Line 127 — `def _candidate_model_dirs()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  125|             dirs.append(Path(mp).expanduser().parent)
  126|         dirs.append(Path(_c.get_model_dir()))
  127|     except Exception:
  128|         pass
```

### Line 132 — `def _candidate_model_dirs()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  130|         from eli.core.paths import project_root
  131|         dirs.append(Path(project_root()) / "models")
  132|     except Exception:
  133|         pass
```

### Line 525 — `def _close_vl()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  523|         if llm is not None:
  524|             llm.close()
  525|     except Exception:
  526|         pass
```

### Line 474 — `def _patched()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  472|             try:
  473|                 params.use_gpu = False
  474|             except Exception:
  475|                 pass
```

## `eli/planning/goal_store.py` (1)

### Line 131 — `def _notify_world()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  129|         from eli.world.local_world_bridge import append_event
  130|         append_event(event_type, "goal_store", summary, payload)
  131|     except Exception:
  132|         pass
```

## `eli/planning/insight_synthesis.py` (4)

### Line 48 — `def get_cached_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   46|                 return ""
   47|             return str(d.get("insight") or "").strip()
   48|     except Exception:
   49|         pass
```

### Line 127 — `def refresh_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  125|             p.write_text(json.dumps({"insight": out, "ts": time.time()}, indent=2),
  126|                          encoding="utf-8")
  127|         except Exception:
  128|             pass
```

### Line 64 — `def refresh_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   62|                 if time.time() - float(d.get("ts", 0)) < _MIN_REFRESH_INTERVAL:
   63|                     return str(d.get("insight") or "")
   64|             except Exception:
   65|                 pass
```

### Line 74 — `def refresh_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   72|                 if foreground_recently_active():
   73|                     return get_cached_insight()
   74|             except Exception:
   75|                 pass
```

## `eli/plugins/document_reader/plugin.py` (3)

### Line 113 — `def html_to_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  111|         parser.feed(markup)
  112|         parser.close()
  113|     except Exception:
  114|         pass
```

### Line 372 — `def _read_pdf()`

- **Except:** `ImportError`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  370|                 "page_starts": _starts(pages),
  371|             }
  372|         except ImportError:
  373|             pass
```

### Line 381 — `def _read_pdf()`

- **Except:** `ImportError`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  379|             return {"ok": True, "content": text[:self._max_chars], "response": text[:self._max_chars],
  380|                     "path": str(p), "page_starts": _starts(pages)}
  381|         except ImportError:
  382|             pass
```

## `eli/plugins/web/plugin.py` (2)

### Line 152 — `def _open_in_browser()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  150|                 except Exception:
  151|                     pass
  152|     except Exception:
  153|         pass
```

### Line 150 — `def _open_in_browser()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  148|                     fn(url)
  149|                     return True
  150|                 except Exception:
  151|                     pass
```

## `eli/runtime/active_project.py` (2)

### Line 42 — `def set_active()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   40|             _path().write_text(json.dumps({"name": name, "memory_tag": tag,
   41|                                            "ts": time.time()}, indent=2), encoding="utf-8")
   42|         except Exception:
   43|             pass
```

### Line 74 — `def clear_active()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   72|         try:
   73|             _path().unlink(missing_ok=True)
   74|         except Exception:
   75|             pass
```

## `eli/runtime/api_users.py` (1)

### Line 50 — `def _load_raw()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   48|             if isinstance(data, list):
   49|                 return [d for d in data if isinstance(d, dict)]
   50|     except Exception:
   51|         pass
```

## `eli/runtime/approval_engine.py` (1)

### Line 64 — `def evaluate_record()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   62|             record.policy_reason = "ELI Full Control enabled — approval barriers lifted"
   63|             return record
   64|     except Exception:
   65|         pass
```

## `eli/runtime/control_contracts.py` (1)

### Line 575 — `def _trace_header_line()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  573|             from eli.cognition.agent_bus import _confidence_label as _lbl
  574|             label = _lbl(agg_val)
  575|         except Exception:
  576|             pass
```

## `eli/runtime/device_names.py` (4)

### Line 63 — `def load_custom_names()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   61|             if mac:
   62|                 names[f"sink:{mac}"] = str(alias).strip()[:64]
   63|     except Exception:
   64|         pass
```

### Line 169 — `def list_nameable_devices()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  167|             _add(registry_key(d.get("id", "")), d.get("driver") or "device",
  168|                  str(d.get("name") or d.get("id") or ""), {"device_id": d.get("id")})
  169|     except Exception:
  170|         pass
```

### Line 180 — `def list_nameable_devices()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  178|             _add(sink_key(sid), s.get("kind") or "audio", os_name,
  179|                  {"sink": sid, "device_number": i + 1, "is_default": s.get("is_default")})
  180|     except Exception:
  181|         pass
```

### Line 192 — `def list_nameable_devices()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  190|             if k:
  191|                 _add(k, "bluetooth", str(d.get("name") or addr), {"address": addr})
  192|     except Exception:
  193|         pass
```

## `eli/runtime/evidence_arbitration.py` (2)

### Line 172 — `def arbitrate_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  170|         for pkt in list(current_stage_packets() or [])[-limit:]:
  171|             items.append(_score_stage_packet(pkt))
  172|     except Exception:
  173|         pass
```

### Line 179 — `def arbitrate_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  177|         for goal in list(list_active_goals() or [])[: max(1, min(10, limit // 4))]:
  178|             items.append(_score_goal(goal))
  179|     except Exception:
  180|         pass
```

## `eli/runtime/evidence_ledger.py` (1)

### Line 608 — `def recent_generated_artifacts()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  606|         try:
  607|             conn.close()
  608|         except Exception:
  609|             pass
```

## `eli/runtime/experimental_inventory.py` (1)

### Line 31 — `def _first_heading()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   29|             if stripped:
   30|                 return stripped[:120]
   31|     except Exception:
   32|         pass
```

## `eli/runtime/final_response_provider.py` (1)

### Line 32 — `def clear_current_action()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   30|         try:
   31|             delattr(_tls, k)
   32|         except Exception:
   33|             pass
```

## `eli/runtime/generated_script_guard.py` (1)

### Line 176 — `def _quarantine()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  174|         p.rename(q)
  175|         q.with_suffix(q.suffix + ".reason.txt").write_text(reason, encoding="utf-8")
  176|     except Exception:
  177|         pass
```

## `eli/runtime/grounded_remediation.py` (4)

### Line 168 — `def remember_failure()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  166|     try:
  167|         write_incident({"kind": "failure", "result": result})
  168|     except Exception:
  169|         pass
```

### Line 329 — `def _run_in_terminal()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  327|             "created_at": _now(),
  328|         }, ensure_ascii=False, indent=2), encoding="utf-8")
  329|     except Exception:
  330|         pass
```

### Line 117 — `def _save_pending_state()`

- **Except:** `FileNotFoundError`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  115|         try:
  116|             path.unlink()
  117|         except FileNotFoundError:
  118|             pass
```

### Line 148 — `def get_pending()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  146|                         _PENDING = None
  147|                         _save_pending_state(None)
  148|                 except Exception:
  149|                     pass
```

## `eli/runtime/license_info.py` (1)

### Line 116 — `def print_license()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  114|         try:
  115|             sys.stdout.write(SUMMARY)
  116|         except Exception:
  117|             pass
```

## `eli/runtime/operator_state.py` (2)

### Line 63 — `def safe_proposal_summary()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   61|             out.setdefault("ok", True)
   62|             return out
   63|     except Exception:
   64|         pass
```

### Line 34 — `def _as_dict()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   32|             if isinstance(val, dict):
   33|                 return val
   34|         except Exception:
   35|             pass
```

## `eli/runtime/personal_memory_clean_response.py` (1)

### Line 330 — `def build_clean_personal_memory_response()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  328|         if _name and _name.lower() not in {"unknown", "user", "none"}:
  329|             lines.append(f"- The active user's name is {_name.title()} (from your runtime profile).")
  330|     except Exception:
  331|         pass
```

## `eli/runtime/personal_memory_surface.py` (3)

### Line 249 — `def personal_memory_surface()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  247|             if _res:
  248|                 research.append(_item("user_profile", "research", _res, 500, 8, _now_ts))
  249|     except Exception:
  250|         pass
```

### Line 381 — `def personal_memory_surface()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  379|             )
  380|             con.commit()
  381|     except Exception:
  382|         pass
```

### Line 393 — `def personal_memory_surface()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  391|                 if key in snap and snap[key] not in (None, ""):
  392|                     runtime_bits.append(f"{key}={snap[key]}")
  393|         except Exception:
  394|             pass
```

## `eli/runtime/profile_extractor.py` (2)

### Line 74 — `def ensure_profile_tables()`

- **Except:** `sqlite3.OperationalError`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   72|     try:
   73|         cur.execute("ALTER TABLE user_patterns ADD COLUMN claim_id INTEGER")
   74|     except sqlite3.OperationalError:
   75|         pass
```

### Line 100 — `def ensure_profile_tables()`

- **Except:** `sqlite3.OperationalError`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   98|         try:
   99|             cur.execute(f"ALTER TABLE semantic ADD COLUMN {_col} {_decl}")
  100|         except sqlite3.OperationalError:
  101|             pass
```

## `eli/runtime/reasoning_status.py` (1)

### Line 69 — `def _label()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   67|         if val:
   68|             return str(val)
   69|     except Exception:
   70|         pass
```

## `eli/runtime/runtime_policy.py` (1)

### Line 37 — `def _snapshot()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   35|             data = json.loads(path.read_text(encoding="utf-8"))
   36|             return data if isinstance(data, dict) else {}
   37|     except Exception:
   38|         pass
```

## `eli/runtime/security.py` (1)

### Line 128 — `def is_command_allowed()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  126|             if is_full_control():
  127|                 return True
  128|         except Exception:
  129|             pass
```

## `eli/runtime/server_util.py` (2)

### Line 51 — `def effective_api_port()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   49|         if v:
   50|             return int(v)
   51|     except Exception:
   52|         pass
```

### Line 44 — `def effective_api_port()`

- **Except:** `(TypeError, ValueError)`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   42|         try:
   43|             return int(env)
   44|         except (TypeError, ValueError):
   45|             pass
```

## `eli/runtime/stage_packet_store.py` (1)

### Line 34 — `def end_stage_packet_cycle()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   32|     try:
   33|         delattr(_tls, "packets")
   34|     except Exception:
   35|         pass
```

## `eli/runtime/truth_report.py` (2)

### Line 25 — `def _read_json()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   23|         if path.exists():
   24|             return json.loads(path.read_text(encoding="utf-8", errors="replace"))
   25|     except Exception:
   26|         pass
```

### Line 229 — `def _gguf_runtime()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  227|                 if hasattr(llm, "n_ctx") and callable(llm.n_ctx):
  228|                     effective["llm_n_ctx_callable"] = llm.n_ctx()
  229|             except Exception:
  230|                 pass
```

## `eli/runtime/user_model.py` (3)

### Line 94 — `def _resolve_user_id()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   92|         if f.exists():
   93|             return f.read_text(encoding="utf-8", errors="ignore").strip() or "default"
   94|     except Exception:
   95|         pass
```

### Line 202 — `def ensure_user_model_row()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  200|         finally:
  201|             con.close()
  202|     except Exception:
  203|         pass
```

### Line 370 — `def _upsert()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  368|         finally:
  369|             con.close()
  370|     except Exception:
  371|         pass
```

## `eli/runtime/user_visible_response_surface.py` (2)

### Line 250 — `def coerce_user_visible()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  248|                     if isinstance(_v, str) and _v.strip():
  249|                         return _v.strip()
  250|             except Exception:
  251|                 pass
```

### Line 208 — `def coerce_user_visible()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  206|                         if (not _model) or _model == "unknown":
  207|                             _model = _core.get("model_path") or _core.get("model_name")
  208|                     except Exception:
  209|                         pass
```

## `eli/tools/api.py` (2)

### Line 51 — `def actions()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   49|                 if n:
   50|                     names.add(n)
   51|         except Exception:
   52|             pass
```

### Line 65 — `def actions()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   63|                         if n:
   64|                             names.add(n)
   65|             except Exception:
   66|                 pass
```

## `eli/tools/image_engine/gui_bridge.py` (3)

### Line 452 — `def _write_runtime_artifact()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  450|             encoding="utf-8",
  451|         )
  452|     except Exception:
  453|         pass
```

### Line 412 — `def generate_images()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  410|             _gguf.unload_model()
  411|             _swapped = True
  412|         except Exception:
  413|             pass
```

### Line 421 — `def generate_images()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  419|                 from eli.cognition import gguf_inference as _gguf
  420|                 _gguf.reload_model(await_completion=False)  # restore chat LLM in background
  421|             except Exception:
  422|                 pass
```

## `eli/tools/image_engine/image_engine/visual_core.py` (1)

### Line 1179 — `def __init__()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1177|                 try:
 1178|                     getattr(self.pipe, _opt)()
 1179|                 except Exception:
 1180|                     pass
```

## `eli/tools/image_engine/runtime_paths.py` (2)

### Line 65 — `def project_root()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   63|             if not (physical / "eli").is_dir():
   64|                 return env_root
   65|         except Exception:
   66|             pass
```

### Line 59 — `def project_root()`

- **Except:** `ValueError`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   57|                 here.relative_to(env_root)
   58|                 return env_root
   59|             except ValueError:
   60|                 pass
```

## `eli/tools/news/news_fetcher.py` (1)

### Line 76 — `def _init_db()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   74|         conn.execute(_CREATE_FTS)
   75|         conn.execute(_CREATE_TRIGGER_INSERT)
   76|     except Exception:
   77|         pass
```

## `eli/tools/registry/capability_updater.py` (1)

### Line 178 — `def update_capability_manifest()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  176|         _doc = generate_capabilities_doc()
  177|         doc_needs_phrase = _doc.get("needs_phrase", [])
  178|     except Exception:
  179|         pass
```

## `eli/world/agency/reflection_bridge.py` (1)

### Line 14 — `def load_persona_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   12|             try:
   13|                 chunks.append(path.read_text(encoding="utf-8", errors="replace")[:12000])
   14|             except Exception:
   15|                 pass
```

## `eli/world/renderers/pyside6/world_scene.py` (3)

### Line 243 — `def update_from_state()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  241|                 f"{avatar.get('name', 'ELI')} | {avatar.get('activity')} | {avatar.get('expression')}"
  242|             )
  243|         except Exception:
  244|             pass
```

### Line 227 — `def _room_items_for_objects()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  225|             try:
  226|                 dot.setToolTip(str(obj.get("symbolic_meaning") or obj.get("reason") or object_id))
  227|             except Exception:
  228|                 pass
```

### Line 204 — `def _clear_objects()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  202|                 try:
  203|                     self.removeItem(item)
  204|                 except Exception:
  205|                     pass
```

## `eli/world/world_event_bus.py` (2)

### Line 66 — `def fire_world_event()`

- **Except:** `queue.Full`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   64|     try:
   65|         _event_queue.put_nowait((event_type, source, summary, payload or {}))
   66|     except queue.Full:
   67|         pass
```

### Line 37 — `def _world_worker()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   35|             from eli.world.local_world_bridge import append_event
   36|             append_event(event_type, source, summary, payload)
   37|         except Exception:
   38|             pass                  # world unavailable — don't crash runtime
```

