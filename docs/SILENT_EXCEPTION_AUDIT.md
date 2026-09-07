# Silent `except: pass` audit

**Remaining count: 177** (CEILING ratchet target for v2.3.84)

v2.3.84 converted **469** handlers (where `log = get_logger(__name__)` was already in scope or safely added). This document lists **remaining** handlers still using bare `pass`.

## Index by file

| File | Count |
|------|------:|
| `eli/gui/eli_pro_audio_gui_v2_0.py` | 12 |
| `eli/memory/memory.py` | 6 |
| `eli/core/model_download.py` | 5 |
| `eli/cognition/output_governor.py` | 4 |
| `eli/perception/vision.py` | 4 |
| `eli/planning/insight_synthesis.py` | 4 |
| `eli/runtime/device_names.py` | 4 |
| `eli/runtime/grounded_remediation.py` | 4 |
| `eli/cognition/context_synthesiser.py` | 3 |
| `eli/cognition/grounded_status.py` | 3 |
| `eli/cognition/user_info_builder.py` | 3 |
| `eli/cognition/working_memory.py` | 3 |
| `eli/core/netguard.py` | 3 |
| `eli/gui/docks/operator_console_dock.py` | 3 |
| `eli/kernel/self_upgrade.py` | 3 |
| `eli/memory/memory_service.py` | 3 |
| `eli/perception/analyze_csv.py` | 3 |
| `eli/plugins/document_reader/plugin.py` | 3 |
| `eli/runtime/evidence_arbitration.py` | 3 |
| `eli/runtime/personal_memory_surface.py` | 3 |
| `eli/runtime/user_model.py` | 3 |
| `eli/runtime/visible_output.py` | 3 |
| `eli/tools/image_engine/gui_bridge.py` | 3 |
| `eli/world/renderers/pyside6/world_scene.py` | 3 |
| `eli/core/dynamic_runtime_budget.py` | 2 |
| `eli/core/model_tier.py` | 2 |
| `eli/core/startup_hardware_optimizer.py` | 2 |
| `eli/gui/panels/settings.py` | 2 |
| `eli/learning/lora_eval.py` | 2 |
| `eli/memory/__init__.py` | 2 |
| `eli/memory/habits_memory_db.py` | 2 |
| `eli/perception/log_rotation.py` | 2 |
| `eli/perception/voice_worker.py` | 2 |
| `eli/planning/autonomy_controller.py` | 2 |
| `eli/planning/habits_state.py` | 2 |
| `eli/plugins/web/plugin.py` | 2 |
| `eli/runtime/active_project.py` | 2 |
| `eli/runtime/generated_script_guard.py` | 2 |
| `eli/runtime/memory_evidence.py` | 2 |
| `eli/runtime/operator_state.py` | 2 |
| `eli/runtime/runtime_policy.py` | 2 |
| `eli/runtime/server_util.py` | 2 |
| `eli/runtime/truth_report.py` | 2 |
| `eli/runtime/user_visible_response_surface.py` | 2 |
| `eli/tools/api.py` | 2 |
| `eli/tools/image_engine/image_engine/engine.py` | 2 |
| `eli/tools/image_engine/runtime_paths.py` | 2 |
| `eli/tools/registry/capability_updater.py` | 2 |
| `eli/world/world_event_bus.py` | 2 |
| `eli/cli/headless.py` | 1 |
| `eli/cognition/persona_values.py` | 1 |
| `eli/cognition/stance_store.py` | 1 |
| `eli/core/dag.py` | 1 |
| `eli/core/db_paths.py` | 1 |
| `eli/core/full_control.py` | 1 |
| `eli/core/hardware_profile.py` | 1 |
| `eli/core/init_data.py` | 1 |
| `eli/core/legacy_paths.py` | 1 |
| `eli/core/runtime_settings.py` | 1 |
| `eli/execution/portable_intent_contract.py` | 1 |
| `eli/execution/route_authority.py` | 1 |
| `eli/execution/tool_execution_authority.py` | 1 |
| `eli/integrations/ollama/client.py` | 1 |
| `eli/kernel/engine.py` | 1 |
| `eli/kernel/scheduler.py` | 1 |
| `eli/learning/dataset_builder.py` | 1 |
| `eli/memory/memory_truth.py` | 1 |
| `eli/memory/sqlite_memory.py` | 1 |
| `eli/perception/analyze_image.py` | 1 |
| `eli/perception/os_controller.py` | 1 |
| `eli/runtime/api_users.py` | 1 |
| `eli/runtime/approval_engine.py` | 1 |
| `eli/runtime/evidence_ledger.py` | 1 |
| `eli/runtime/evidence_store.py` | 1 |
| `eli/runtime/experimental_inventory.py` | 1 |
| `eli/runtime/final_response_provider.py` | 1 |
| `eli/runtime/identity_guard.py` | 1 |
| `eli/runtime/license_info.py` | 1 |
| `eli/runtime/personal_memory_clean_response.py` | 1 |
| `eli/runtime/reasoning_status.py` | 1 |
| `eli/runtime/security.py` | 1 |
| `eli/runtime/stage_packet_store.py` | 1 |
| `eli/tools/image_engine/image_engine/visual_core.py` | 1 |
| `eli/tools/news/news_fetcher.py` | 1 |
| `eli/world/agency/reflection_bridge.py` | 1 |

---

## `eli/cli/headless.py` (1)

### Line 137 — `def run_headless()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  135|         try:
  136|             engine.shutdown()
  137|         except Exception:
  138|             pass
```

## `eli/cognition/context_synthesiser.py` (3)

### Line 559 — `def build_persona_handoff()`

- **Except:** `_SkipWorldState`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  557|                 + "\n".join(f"  {p}" for p in _world_parts)
  558|             )
  559|     except _SkipWorldState:
  560|         pass          # not a world question — nothing about rooms reaches the model
```

### Line 96 — `def synthesise()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   94|             if _uname:
   95|                 sections.append(f'USER:\nName: {_uname}')
   96|         except Exception:
   97|             pass
```

### Line 158 — `def _build_turns_block()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  156|                 if should_exclude_turn_from_prompt(role, content):
  157|                     continue
  158|             except Exception:
  159|                 pass
```

## `eli/cognition/grounded_status.py` (3)

### Line 137 — `def _best_text_column()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  135|             if "TEXT" in col_type or "CHAR" in col_type or "CLOB" in col_type:
  136|                 candidates.append(col_name)
  137|     except Exception:
  138|         pass
```

### Line 66 — `def _load_profile()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   64|                     data["_source"] = str(p)
   65|                     return data
   66|             except Exception:
   67|                 pass
```

### Line 399 — `def _infer_identity_from_memory()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  397|                         if found.get("preferred_name") and found.get("name"):
  398|                             return found, evidence[:12]
  399|                 except Exception:
  400|                     pass
```

## `eli/cognition/output_governor.py` (4)

### Line 76 — `def normalize_assistant_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   74|     try:
   75|         result = repair_local_persona_drift(result, user_input=user_input).strip()
   76|     except Exception:
   77|         pass
```

### Line 693 — `def _runtime_user_facts()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  691|             if len(parts) > 1:
  692|                 facts["last_name"] = parts[-1]
  693|     except Exception:
  694|         pass
```

### Line 708 — `def _runtime_user_facts()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  706|             if k in _USER_FACT_KEYS and v:
  707|                 facts[k] = str(v).strip()
  708|     except Exception:
  709|         pass
```

### Line 1135 — `def validate_against_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1133|             if Path(match).exists():
 1134|                 continue
 1135|         except Exception:
 1136|             pass
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

## `eli/cognition/stance_store.py` (1)

### Line 80 — `def ensure_tables()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   78|         try:
   79|             cur.execute(stmt)
   80|         except Exception:
   81|             pass  # already present on an existing install
```

## `eli/cognition/user_info_builder.py` (3)

### Line 731 — `def _bg_loop()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  729|         try:
  730|             maybe_refresh_user_info(reason="scheduled")
  731|         except Exception:
  732|             pass
```

### Line 753 — `def _flush()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  751|         try:
  752|             refresh_user_info(force=True, reason="process_exit")
  753|         except Exception:
  754|             pass
```

### Line 611 — `def refresh_user_info()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  609|                 recent_turns = _gather_recent_turns(conn, user_id=user_id)
  610|                 conn.close()
  611|             except Exception:
  612|                 pass
```

## `eli/cognition/working_memory.py` (3)

### Line 256 — `def persist()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  254|             conn.commit()
  255|             conn.close()
  256|         except Exception:
  257|             pass
```

### Line 282 — `def restore()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  280|                     self._facts[key or self._key(text)] = fact
  281|                     loaded += 1
  282|         except Exception:
  283|             pass
```

### Line 226 — `def flush_to_memory()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  224|                     )
  225|                     saved += 1
  226|                 except Exception:
  227|                     pass
```

## `eli/core/dag.py` (1)

### Line 405 — `def _emit()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  403|                 try:
  404|                     self.on_event(o.id, o)
  405|                 except Exception:
  406|                     pass
```

## `eli/core/db_paths.py` (1)

### Line 71 — `def get_db_paths()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   69|     try:
   70|         _db_dir().mkdir(parents=True, exist_ok=True)
   71|     except Exception:
   72|         pass
```

## `eli/core/dynamic_runtime_budget.py` (2)

### Line 55 — `def detect_ram_gb()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   53|         import psutil
   54|         return psutil.virtual_memory().total / 1e9
   55|     except Exception:
   56|         pass
```

### Line 62 — `def detect_ram_gb()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   60|         if m:
   61|             return int(m.group(1)) / 1024 / 1024
   62|     except Exception:
   63|         pass
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

## `eli/core/hardware_profile.py` (1)

### Line 1229 — `def apply_recommendation()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1227|                 encoding="utf-8",
 1228|             )
 1229|         except Exception:
 1230|             pass  # non-fatal — settings.json is the source of truth
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

### Line 248 — `def _load_override_catalog()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  246|     try:
  247|         candidates.append(models_dir() / "catalog.json")
  248|     except Exception:
  249|         pass
```

### Line 210 — `def aux_status()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  208|             out["size_mib"] = round(nbytes / (1024 * 1024), 1)
  209|             out["size_gib_actual"] = round(_as_gib(nbytes / 1e9), 2)
  210|         except Exception:
  211|             pass
```

### Line 568 — `def interactive_select()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  566|             from eli.core.hardware_profile import detect_hardware
  567|             free = (getattr(detect_hardware(), "free_vram_mb", 0) or 0) / 1024.0
  568|         except Exception:
  569|             pass
```

### Line 438 — `def download_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  436|                     try:
  437|                         progress_cb(downloaded, total)
  438|                     except Exception:
  439|                         pass
```

### Line 452 — `def download_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  450|                             try:
  451|                                 progress_cb(downloaded, total)
  452|                             except Exception:
  453|                                 pass
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

### Line 98 — `def record_speed()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   96|             return
   97|         _speed_ema = v if _speed_ema <= 0 else (_SPEED_ALPHA * v + (1.0 - _SPEED_ALPHA) * _speed_ema)
   98|     except Exception:
   99|         pass
```

## `eli/core/netguard.py` (3)

### Line 90 — `def _net_allowed()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   88|         if is_full_control():
   89|             return True
   90|     except Exception:
   91|         pass
```

### Line 275 — `def _record_egress()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  273|                 except Exception:
  274|                     pass            # queue full → ring still has it; drop the ledger write
  275|     except Exception:
  276|         pass
```

### Line 273 — `def _record_egress()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  271|                 try:
  272|                     _egress_q.put_nowait((nh, port, ts))
  273|                 except Exception:
  274|                     pass            # queue full → ring still has it; drop the ledger write
```

## `eli/core/runtime_settings.py` (1)

### Line 581 — `def save_settings()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  579|     if "n_threads" in existing:
  580|         try: existing["n_threads"] = int(existing["n_threads"])
  581|         except Exception: pass
  582|     if "n_gpu_layers" in existing:
```

## `eli/core/startup_hardware_optimizer.py` (2)

### Line 135 — `def detect_other_gpus()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  133|                 if "vram" in kl and "total" in kl and "memory" in kl and "used" not in kl:
  134|                     try: _tot = int(v)
  135|                     except Exception: pass
  136|                 elif "vram" in kl and "used" in kl and "memory" in kl:
```

### Line 138 — `def detect_other_gpus()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  136|                 elif "vram" in kl and "used" in kl and "memory" in kl:
  137|                     try: _used = int(v)
  138|                     except Exception: pass
  139|             if _tot > 0:
```

## `eli/execution/portable_intent_contract.py` (1)

### Line 520 — `def try_route()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  518|             if raw_m:
  519|                 query = _clean_target(raw_m.group(1))
  520|         except Exception:
  521|             pass
```

## `eli/execution/route_authority.py` (1)

### Line 25 — `def end_route_cycle()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   23|         try:
   24|             delattr(_tls, k)
   25|         except Exception:
   26|             pass
```

## `eli/execution/tool_execution_authority.py` (1)

### Line 33 — `def latest_execution_intent_payload()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   31|             if getattr(pkt, "kind", "") == "execution_intent_packet":
   32|                 return dict(getattr(pkt, "payload", {}) or {})
   33|         except Exception:
   34|             pass
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

### Line 3197 — `def _on_auto_speak_toggled()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 3195|         self._tts_auto = checked
 3196|         try: self.auto_speak_btn.setText('🔊 Auto-Speak: ON' if checked else '🔇 Auto-Speak: OFF')
 3197|         except Exception: pass
 3198| 
```

### Line 10995 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10993|             except Exception: pass
10994|             _acon.close()
10995|         except Exception: pass
10996| 
```

### Line 11006 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
11004|                                  session_id="proactive-gui", user_id="local-user")
11005|             ground["bus_context"] = (_dr.memory_context or "")[:1200]
11006|         except Exception: pass
11007| 
```

### Line 10945 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10943|             try:
10944|                 ground["memories"] = self._central_memory.recall_memory(_q[:300], limit=10) or []
10945|             except Exception: pass
10946|             try:
```

### Line 10948 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10946|             try:
10947|                 ground["recent_conv"] = self._central_memory.get_recent_conversation(limit=20) or []
10948|             except Exception: pass
10949|             try:
```

### Line 10951 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10949|             try:
10950|                 ground["memory_stats"] = memory_system.get_stats() if memory_system else {}
10951|             except Exception: pass
10952|             try:
```

### Line 10956 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10954|                 if vs:
10955|                     ground["faiss_count"] = vs.ntotal
10956|             except Exception: pass
10957| 
```

### Line 10962 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10960|             try:
10961|                 ground["daemon_patterns"] = self._proactive_daemon.analyze_user_patterns() or []
10962|             except Exception: pass
10963|             try:
```

### Line 10967 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10965|                 if mem_h and hasattr(mem_h, "get_habit_rules"):
10966|                     ground["habit_rules"] = mem_h.get_habit_rules(enabled_only=True) or []
10967|             except Exception: pass
10968| 
```

### Line 10978 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10976|                     "SELECT user_input, error, occurrence_count FROM failures "
10977|                     "ORDER BY timestamp DESC LIMIT 8").fetchall()]
10978|             except Exception: pass
10979|             try:
```

### Line 10983 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10981|                     "SELECT category, detail FROM improvements "
10982|                     "ORDER BY timestamp DESC LIMIT 8").fetchall()]
10983|             except Exception: pass
10984|             try:
```

### Line 10993 — `def _build_proactive_ground_truth()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
10991|                     except Exception:
10992|                         ground["agent_obs"].append({"raw": str(content)[:150]})
10993|             except Exception: pass
10994|             _acon.close()
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

## `eli/integrations/ollama/client.py` (1)

### Line 386 — `def get_active_model()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  384|         if v:
  385|             return v
  386|     except Exception:
  387|         pass
```

## `eli/kernel/engine.py` (1)

### Line 716 — `def _eli_bad_identity_self_report_output()`

- **Except:** `(ValueError, TypeError)`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  714|             ):
  715|                 return False
  716|     except (ValueError, TypeError):
  717|         pass  # a plain-text reply isn't JSON — expected, fall through to the text checks
```

## `eli/kernel/scheduler.py` (1)

### Line 59 — `def shutdown()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   57|                 try:
   58|                     timer.cancel()
   59|                 except Exception:
   60|                     pass
```

## `eli/kernel/self_upgrade.py` (3)

### Line 235 — `def _local_version()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  233|             if m:
  234|                 return m.group(1)
  235|         except Exception:
  236|             pass
```

### Line 240 — `def _local_version()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  238|             import importlib.metadata as im
  239|             return str(im.version("eli-v2.0"))
  240|         except Exception:
  241|             pass
```

### Line 469 — `def _release_upgrade()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  467|                     p.unlink(missing_ok=True)
  468|                 work.rmdir()
  469|             except Exception:
  470|                 pass
```

## `eli/learning/dataset_builder.py` (1)

### Line 347 — `def load_jsonish_file()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  345|         obj = json.loads(raw)
  346|         return obj if isinstance(obj, list) else [obj]
  347|     except Exception:
  348|         pass
```

## `eli/learning/lora_eval.py` (2)

### Line 68 — `def _patch_dynamic_cache_seen_tokens()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   66|         try:
   67|             DynamicCache.seen_tokens = property(_get_seen_tokens)
   68|         except Exception:
   69|             pass
```

### Line 94 — `def _patch_transformers_cache_compat_v2()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   92|         try:
   93|             DynamicCache.get_max_length = _get_max_length
   94|         except Exception:
   95|             pass
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

## `eli/memory/habits_memory_db.py` (2)

### Line 111 — `def _recall_recent_legacy_1()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  109|         try:
  110|             limit = int(k)
  111|         except Exception:
  112|             pass
```

### Line 376 — `def recall_recent()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  374|         try:
  375|             limit = int(k)
  376|         except Exception:
  377|             pass
```

## `eli/memory/memory.py` (6)

### Line 46 — `def _resolve_project_artifacts_dir()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   44|             return Path(core_paths.get_artifact_dir()).expanduser().resolve()
   45|         return core_paths.get_paths().artifacts_dir.resolve()
   46|     except Exception:
   47|         pass
```

### Line 154 — `def _clear_memory_singletons()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  152| 
  153|         _si._self_engine = None
  154|     except Exception:
  155|         pass
```

### Line 136 — `def _flush_recall_writes_locked()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  134|             finally:
  135|                 conn.close()
  136|         except Exception:
  137|             pass
```

### Line 76 — `def _pick()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   74|             try:
   75|                 return Path(fn()).expanduser().resolve()
   76|             except Exception:
   77|                 pass
```

### Line 4559 — `def get_dashboard_counts()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 4557|             if _eli_table_exists(conn, "semantic"):
 4558|                 try: semantic_count = conn.execute("SELECT COUNT(*) FROM semantic").fetchone()[0] or 0
 4559|                 except Exception: pass
 4560| 
```

### Line 131 — `def _flush_recall_writes_locked()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  129|                     try:
  130|                         fn(conn)
  131|                     except Exception:
  132|                         pass
```

## `eli/memory/memory_service.py` (3)

### Line 15 — `def ensure_schema()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   13|         from eli.memory import get_memory
   14|         get_memory()  # Schema created on init
   15|     except Exception:
   16|         pass
```

### Line 42 — `def append_chat_turn()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   40|         mem.add_conversation_turn("user", user_msg, session_id=session_id)
   41|         mem.add_conversation_turn("assistant", assistant_msg, session_id=session_id)
   42|     except Exception:
   43|         pass  # Never crash the chat pipeline
```

### Line 55 — `def get_last_user_utterance()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   53|             if turn.get("role") == "user":
   54|                 return turn.get("content")
   55|     except Exception:
   56|         pass
```

## `eli/memory/memory_truth.py` (1)

### Line 33 — `def _artifact_path()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   31|         if val:
   32|             return Path(val).expanduser().resolve().joinpath(*parts)
   33|     except Exception:
   34|         pass
```

## `eli/memory/sqlite_memory.py` (1)

### Line 42 — `def log_event()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   40|     try:
   41|         get_memory().log_habit_event(event_type, data or {})
   42|     except Exception:
   43|         pass
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

## `eli/perception/log_rotation.py` (2)

### Line 115 — `def convlog_append()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  113|         with open(path, "a", encoding="utf-8") as f:
  114|             f.write(json.dumps(rec, ensure_ascii=False) + "\n")
  115|     except Exception:
  116|         pass  # Never crash ELI on logging failure
```

### Line 127 — `def _rotate_current()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  125|         rotated = path.parent / f"{stem}_{suffix}.jsonl"
  126|         path.rename(rotated)
  127|     except Exception:
  128|         pass
```

## `eli/perception/os_controller.py` (1)

### Line 262 — `def set_volume()`

- **Except:** `Exception`
- **Why it exists / risk:** Fallback chain probe (tool/browser/player) — silent failure causes wrong 'nothing works' UX.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  260|                 subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], check=True, capture_output=True)
  261|                 return {"ok": True, "content": "Unmuted", "response": "Unmuted"}
  262|         except Exception as e:
  263|             pass  # fall through to wpctl
```

## `eli/perception/vision.py` (4)

### Line 126 — `def _candidate_model_dirs()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  124|             dirs.append(Path(mp).expanduser().parent)
  125|         dirs.append(Path(_c.get_model_dir()))
  126|     except Exception:
  127|         pass
```

### Line 131 — `def _candidate_model_dirs()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  129|         from eli.core.paths import project_root
  130|         dirs.append(Path(project_root()) / "models")
  131|     except Exception:
  132|         pass
```

### Line 504 — `def _close_vl()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  502|         if llm is not None:
  503|             llm.close()
  504|     except Exception:
  505|         pass
```

### Line 453 — `def _patched()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  451|             try:
  452|                 params.use_gpu = False
  453|             except Exception:
  454|                 pass
```

## `eli/perception/voice_worker.py` (2)

### Line 26 — `def stop()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   24|         try:
   25|             p.send_signal(signal.SIGINT)
   26|         except Exception:
   27|             pass
```

### Line 30 — `def stop()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   28|         try:
   29|             p.terminate()
   30|         except Exception:
   31|             pass
```

## `eli/planning/autonomy_controller.py` (2)

### Line 72 — `module-level`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   70|             return safe_goal_tick(limit=limit)
   71|         AutonomyController.goal_tick = _goal_tick
   72| except Exception:
   73|     pass
```

### Line 96 — `module-level`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   94|             return safe_scheduler_tick(limit=limit, cooldown_sec=cooldown_sec)
   95|         AutonomyController.scheduler_tick = _scheduler_tick
   96| except Exception:
   97|     pass
```

## `eli/planning/habits_state.py` (2)

### Line 14 — `def _load_state()`

- **Except:** `bare except`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   12|         if _STATE_PATH.exists():
   13|             return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
   14|     except:
   15|         pass
```

### Line 22 — `def _save_state()`

- **Except:** `bare except`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   20|         _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
   21|         _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
   22|     except:
   23|         pass
```

## `eli/planning/insight_synthesis.py` (4)

### Line 41 — `def get_cached_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   39|             d = json.loads(p.read_text(encoding="utf-8"))
   40|             return str(d.get("insight") or "").strip()
   41|     except Exception:
   42|         pass
```

### Line 119 — `def refresh_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  117|             p.write_text(json.dumps({"insight": out, "ts": time.time()}, indent=2),
  118|                          encoding="utf-8")
  119|         except Exception:
  120|             pass
```

### Line 57 — `def refresh_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   55|                 if time.time() - float(d.get("ts", 0)) < _MIN_REFRESH_INTERVAL:
   56|                     return str(d.get("insight") or "")
   57|             except Exception:
   58|                 pass
```

### Line 67 — `def refresh_insight()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   65|                 if foreground_recently_active():
   66|                     return get_cached_insight()
   67|             except Exception:
   68|                 pass
```

## `eli/plugins/document_reader/plugin.py` (3)

### Line 92 — `def _html_to_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   90|         parser.feed(markup)
   91|         parser.close()
   92|     except Exception:
   93|         pass
```

### Line 319 — `def _read_pdf()`

- **Except:** `ImportError`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  317|                 "path": str(p), "pages": len(reader.pages), "truncated": truncated,
  318|             }
  319|         except ImportError:
  320|             pass
```

### Line 327 — `def _read_pdf()`

- **Except:** `ImportError`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  325|             text = "\n".join(pages)
  326|             return {"ok": True, "content": text[:8000], "response": text[:8000], "path": str(p)}
  327|         except ImportError:
  328|             pass
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

## `eli/runtime/evidence_arbitration.py` (3)

### Line 148 — `def arbitrate_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  146|         for pkt in list(current_stage_packets() or [])[-limit:]:
  147|             items.append(_score_stage_packet(pkt))
  148|     except Exception:
  149|         pass
```

### Line 155 — `def arbitrate_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  153|         for rec in load_recent_tool_results(limit=limit):
  154|             items.append(_score_tool_result(rec))
  155|     except Exception:
  156|         pass
```

### Line 162 — `def arbitrate_evidence()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  160|         for goal in list(list_active_goals() or [])[: max(1, min(10, limit // 4))]:
  161|             items.append(_score_goal(goal))
  162|     except Exception:
  163|         pass
```

## `eli/runtime/evidence_ledger.py` (1)

### Line 564 — `def recent_generated_artifacts()`

- **Except:** `Exception`
- **Why it exists / risk:** Best-effort teardown (close socket/file/mpv) — non-fatal but should log for diagnosis.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  562|         try:
  563|             conn.close()
  564|         except Exception:
  565|             pass
```

## `eli/runtime/evidence_store.py` (1)

### Line 15 — `def clear_pipeline_state()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   13|         try:
   14|             delattr(_tls, k)
   15|         except Exception:
   16|             pass
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

## `eli/runtime/generated_script_guard.py` (2)

### Line 131 — `def _write_gpu_memory_watch_script()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  129|     try:
  130|         path.chmod(0o755)  # harmless / ignored on Windows
  131|     except Exception:
  132|         pass
```

### Line 781 — `def _quarantine()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  779|         p.rename(q)
  780|         q.with_suffix(q.suffix + ".reason.txt").write_text(reason, encoding="utf-8")
  781|     except Exception:
  782|         pass
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

## `eli/runtime/identity_guard.py` (1)

### Line 61 — `def clear_lock()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   59|         if hasattr(state, "persona_lock"):
   60|             state.persona_lock = None
   61|     except Exception:
   62|         pass
```

## `eli/runtime/license_info.py` (1)

### Line 97 — `def print_license()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   95|         try:
   96|             sys.stdout.write(SUMMARY)
   97|         except Exception:
   98|             pass
```

## `eli/runtime/memory_evidence.py` (2)

### Line 91 — `def _memory_instance()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   89|         if mem is not None:
   90|             return mem
   91|     except Exception:
   92|         pass
```

### Line 80 — `def _coerce_score()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   78|             if 0.0 <= f <= 1.0:
   79|                 return max(base, f)
   80|         except Exception:
   81|             pass
```

## `eli/runtime/operator_state.py` (2)

### Line 78 — `def safe_proposal_summary()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   76|             out.setdefault("ok", True)
   77|             return out
   78|     except Exception:
   79|         pass
```

### Line 49 — `def _as_dict()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   47|             if isinstance(val, dict):
   48|                 return val
   49|         except Exception:
   50|             pass
```

## `eli/runtime/personal_memory_clean_response.py` (1)

### Line 327 — `def build_clean_personal_memory_response()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  325|         if _name and _name.lower() not in {"unknown", "user", "none"}:
  326|             lines.append(f"- The active user's name is {_name.title()} (from your runtime profile).")
  327|     except Exception:
  328|         pass
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

## `eli/runtime/reasoning_status.py` (1)

### Line 70 — `def _label()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   68|         if val:
   69|             return str(val)
   70|     except Exception:
   71|         pass
```

## `eli/runtime/runtime_policy.py` (2)

### Line 38 — `def _snapshot()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   36|             data = json.loads(path.read_text(encoding="utf-8"))
   37|             return data if isinstance(data, dict) else {}
   38|     except Exception:
   39|         pass
```

### Line 50 — `def context_size()`

- **Except:** `Exception`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   48|             if value > 0:
   49|                 return value
   50|         except Exception:
   51|             pass
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

### Line 48 — `def effective_api_port()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   46|         if v:
   47|             return int(v)
   48|     except Exception:
   49|         pass
```

### Line 41 — `def effective_api_port()`

- **Except:** `(TypeError, ValueError)`
- **Why it exists / risk:** Invalid env override — falls back to default; silent pass hides misconfiguration.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   39|         try:
   40|             return int(env)
   41|         except (TypeError, ValueError):
   42|             pass
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

### Line 26 — `def _read_json()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   24|         if path.exists():
   25|             return json.loads(path.read_text(encoding="utf-8", errors="replace"))
   26|     except Exception:
   27|         pass
```

### Line 127 — `def _gguf_runtime()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  125|                 if hasattr(llm, "n_ctx") and callable(llm.n_ctx):
  126|                     effective["llm_n_ctx_callable"] = llm.n_ctx()
  127|             except Exception:
  128|                 pass
```

## `eli/runtime/user_model.py` (3)

### Line 97 — `def _resolve_user_id()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   95|         if f.exists():
   96|             return f.read_text(encoding="utf-8", errors="ignore").strip() or "default"
   97|     except Exception:
   98|         pass
```

### Line 206 — `def ensure_user_model_row()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  204|         finally:
  205|             con.close()
  206|     except Exception:
  207|         pass
```

### Line 374 — `def _upsert()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  372|         finally:
  373|             con.close()
  374|     except Exception:
  375|         pass
```

## `eli/runtime/user_visible_response_surface.py` (2)

### Line 277 — `def coerce_user_visible()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  275|                     if isinstance(_v, str) and _v.strip():
  276|                         return _v.strip()
  277|             except Exception:
  278|                 pass
```

### Line 250 — `def coerce_user_visible()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  248|                         if (not _model) or _model == "unknown":
  249|                             _model = _core.get("model_path") or _core.get("model_name")
  250|                     except Exception:
  251|                         pass
```

## `eli/runtime/visible_output.py` (3)

### Line 70 — `def visible_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   68|         from eli.cognition.response_sanitizer import sanitize_assistant_text
   69|         raw = sanitize_assistant_text(raw)
   70|     except Exception:
   71|         pass
```

### Line 77 — `def visible_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   75|         raw = normalize_assistant_text(user_input or "", raw)
   76|         raw = govern_output(raw, is_grounded=is_grounded, evidence=evidence or "")
   77|     except Exception:
   78|         pass
```

### Line 83 — `def visible_text()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   81|         from eli.cognition.response_sanitizer import sanitize_assistant_text
   82|         raw = sanitize_assistant_text(raw)
   83|     except Exception:
   84|         pass
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

### Line 443 — `def _write_runtime_artifact()`

- **Except:** `Exception`
- **Why it exists / risk:** Settings read/write — silent pass can leave stale config or failed deletes unnoticed.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  441|             encoding="utf-8",
  442|         )
  443|     except Exception:
  444|         pass
```

### Line 403 — `def generate_images()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  401|             _gguf.unload_model()
  402|             _swapped = True
  403|         except Exception:
  404|             pass
```

### Line 412 — `def generate_images()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  410|                 from eli.cognition import gguf_inference as _gguf
  411|                 _gguf.reload_model(await_completion=False)  # restore chat LLM in background
  412|             except Exception:
  413|                 pass
```

## `eli/tools/image_engine/image_engine/engine.py` (2)

### Line 110 — `def get_font()`

- **Except:** `Exception`
- **Why it exists / risk:** Try/return fallback — exception swallowed to return None/False/default.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  108|         try:
  109|             return ImageFont.truetype(path, size)
  110|         except Exception:
  111|             pass
```

### Line 470 — `def analyze()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  468|                 try:
  469|                     text_chunks.append(path.read_text(errors="ignore")[:12000])
  470|                 except Exception:
  471|                     pass
```

## `eli/tools/image_engine/image_engine/visual_core.py` (1)

### Line 1180 — `def __init__()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
 1178|                 try:
 1179|                     getattr(self.pipe, _opt)()
 1180|                 except Exception:
 1181|                     pass
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

## `eli/tools/registry/capability_updater.py` (2)

### Line 120 — `def update_capability_manifest()`

- **Except:** `Exception`
- **Why it exists / risk:** Optional import or platform module — failure means feature degrades; should log at debug (converted where safe).
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
  118|         _doc = generate_capabilities_doc()
  119|         doc_needs_phrase = _doc.get("needs_phrase", [])
  120|     except Exception:
  121|         pass
```

### Line 58 — `def extract_plugin_actions()`

- **Except:** `Exception`
- **Why it exists / risk:** Unclassified best-effort block — review whether failure should surface to operator logs.
- **Action:** Convert to `log.debug(..., exc_info=True)` when logger is in scope; never add new silent passes.

```python
   56|                 if a.isupper() and len(a) > 3 and "_" in a or a.isupper()
   57|             ][:20]
   58|         except Exception:
   59|             pass
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

