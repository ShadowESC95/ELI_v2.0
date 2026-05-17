#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(pwd)"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/ops/reports/phase38_router_canonical_flattened_dispatch_pipeline_${STAMP}"

ROUTER="eli/execution/router_enhanced.py"
PHASE36_SCRIPT="ops/patches/phase36_router_flattening_semantic_baseline_v2.sh"
MARKER="ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1"

mkdir -p "$OUT/backups"

if [[ ! -f "$ROUTER" ]]; then
  echo "Missing router file: $ROUTER" >&2
  exit 1
fi

if [[ ! -x "$PHASE36_SCRIPT" ]]; then
  echo "Missing or non-executable Phase 36 semantic baseline script: $PHASE36_SCRIPT" >&2
  exit 1
fi

cp "$ROUTER" "$OUT/backups/router_enhanced.py.before_phase38.bak"

cat > "$OUT/SUMMARY.md" <<EOF
# Phase 38 — Canonical Flattened Router Dispatch Pipeline v1

Generated: $(date -Is)  
Root: $ROOT  
Target: $ROUTER

## Repair intent

Phase 36 v2 established a 29-case semantic golden baseline.

Phase 37 proved that the final router remains a deeply nested live wrapper
chain with:

- 83 reachable function nodes
- 104 reachable callable edges
- 16 directly live capture sites
- 45 indirect/closure-linked capture sites that are not deletion-safe

Phase 38 installs a new single explicit canonical dispatch function at EOF.
It preserves the live routing semantics while bypassing nested historical
wrapper chaining as the active public router surface.

This phase does **not** delete old wrapper source blocks yet.
Physical source pruning is reserved for Phase 39 after exact baseline parity
has been proven.

## Verification policy

1. Run Phase 36 semantic baseline before patch.
2. Append the flattened canonical dispatcher.
3. Compile router.
4. Verify public surface identity.
5. Run Phase 36 semantic baseline after patch.
6. Compare pre/post semantic baseline JSON exactly.
7. Auto-rollback the router if any mismatch appears.
EOF

# ---------------------------------------------------------------------
# 00. Pre-patch golden snapshot
# ---------------------------------------------------------------------

echo "=== PRE-PATCH PHASE 36 BASELINE ===" | tee "$OUT/00_pre_phase36_run.txt"
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/00_pre_phase36_run.txt"

PRE36_OUT="$(grep -E '^PHASE36_V2_OUT=' "$OUT/00_pre_phase36_run.txt" | tail -1 | cut -d= -f2-)"

if [[ -z "${PRE36_OUT:-}" || ! -d "$PRE36_OUT" ]]; then
  echo "Failed to locate PRE36 output directory." >&2
  exit 1
fi

PRE_JSON="$PRE36_OUT/05_router_flattening_semantic_baseline.json"
PRE_DIGEST="$PRE36_OUT/08_console_digest.txt"

if [[ ! -f "$PRE_JSON" ]]; then
  echo "Missing pre-patch semantic baseline JSON: $PRE_JSON" >&2
  exit 1
fi

cp "$PRE_JSON" "$OUT/01_pre_phase36_semantic_baseline.json"
[[ -f "$PRE_DIGEST" ]] && cp "$PRE_DIGEST" "$OUT/02_pre_phase36_digest.txt"

# ---------------------------------------------------------------------
# 01. Append canonical flattened dispatcher
# ---------------------------------------------------------------------

if grep -q "$MARKER" "$ROUTER"; then
  echo "Phase 38 marker already exists in $ROUTER; refusing to append duplicate block." >&2
  exit 1
fi

cat >> "$ROUTER" <<'PY'


# =============================================================================
# ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1
# =============================================================================
#
# Purpose:
#   Replace the active nested wrapper-chain public router surface with one
#   explicit canonical dispatch pipeline, while preserving the semantics proven
#   by Phase 36 v2 and the live-stage order proven by Phase 37.
#
# Important:
#   This phase intentionally does NOT delete historical wrapper source blocks.
#   It shadows them as the final exported route surface. Once semantic parity is
#   proven, a dedicated pruning pass can safely remove obsolete rebinding debt.
# =============================================================================

try:
    from eli.execution.portable_intent_contract import try_route as _eli_phase38_portable_try_route
except Exception:
    _eli_phase38_portable_try_route = None


def _eli_phase38_enrich_pdf_if_needed(raw, result):
    enricher = globals().get("_eli_phase11_enrich_pdf_route")
    if callable(enricher):
        try:
            return enricher(raw, result)
        except Exception:
            return result
    return result


def _eli_phase38_route_precedence_contract(raw):
    try:
        from eli.execution.route_contracts import classify_precedence_route
        return classify_precedence_route(raw)
    except Exception:
        return None


def _eli_phase38_runtime_status_or_name_source_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip()

    runtime_status_query = (
        ("who are you" in low or "what are you" in low)
        and (
            "actually running" in low
            or "running on right now" in low
            or "model" in low
            or "context size" in low
            or "gpu layers" in low
            or "everything" in low
        )
    )

    if runtime_status_query:
        return {
            "action": "RUNTIME_STATUS",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_runtime_status_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_status",
                "response_contract": "quick_direct_nonquick_persona_synthesis",
            },
        }

    if (
        ("how do you know" in low and "name" in low)
        or ("where" in low and "name" in low and ("file" in low or "located" in low or "stored" in low))
        or ("which file" in low and "name" in low)
    ):
        return {
            "action": "NAME_SOURCE_AUDIT",
            "args": {"question": str(raw or "")},
            "confidence": 0.99,
            "meta": {
                "matched_by": "eli.final_name_source_audit_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    return None


def _eli_phase38_identity_name_source_single_safe_contract(raw):
    low = str(raw or "").lower().strip()

    if (
        ("how do you know" in low and "name" in low)
        or ("where" in low and "name" in low and ("file" in low or "located" in low or "stored" in low))
        or ("which file" in low and "name" in low)
    ):
        return {
            "action": "NAME_SOURCE_AUDIT",
            "args": {"question": str(raw or "")},
            "confidence": 0.99,
            "meta": {
                "matched_by": "identity.name_source_audit.single_safe",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    return None


def _eli_phase38_final_memory_question_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip()

    asks_memory_internals = (
        "memory system" in low
        or "memory internals" in low
        or ("which files" in low and "db tables" in low)
        or ("which db tables" in low)
        or ("which functions" in low and "memory" in low)
        or ("how" in low and "memory" in low and ("works" in low or "internally" in low))
    )

    asks_personal_memory = (
        "what do you know about me" in low
        or "what you know about me" in low
        or "what have you stored about me" in low
        or "what you actually remember" in low
        or "remember about me" in low
        or ("most recent things" in low and "stored" in low and "me" in low)
        or "patterns have you detected" in low
        or "how i interact with you" in low
    )

    if asks_memory_internals and asks_personal_memory:
        return {
            "action": "PERSONAL_MEMORY_DEEP_EXPLAIN",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_memory_hybrid_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "personal_memory",
                "forbid_schema_dump": True,
                "forbid_reflection_spam": True,
                "forbid_news_rows": True,
                "response_contract": "quick_direct_nonquick_persona_synthesis",
            },
        }

    if asks_memory_internals:
        return {
            "action": "EXPLAIN_MEMORY_RUNTIME",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_memory_internals_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
            },
        }

    if asks_personal_memory:
        return {
            "action": "PERSONAL_MEMORY_SUMMARY",
            "args": {"question": str(raw or "")},
            "confidence": 0.995,
            "meta": {
                "matched_by": "eli.final_personal_memory_summary_route_contract",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "personal_memory",
                "forbid_schema_dump": True,
                "forbid_reflection_spam": True,
                "forbid_news_rows": True,
            },
        }

    return None


def _eli_phase38_persona_override_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")

    if low in {
        "elaborate more",
        "elaborate",
        "continue",
        "go on",
        "more detail",
        "explain more",
        "tell me more",
    }:
        return _mk(
            "CHAT",
            {
                "message": (
                    "Continue the immediately previous answer. "
                    "No role prefix. No HR filler. Stay in ELI's direct voice."
                )
            },
            0.95,
            matched_by="eli.final_followup_override",
            allow_chat_without_evidence=False,
        )

    if low in {
        "what's the story here we go",
        "whats the story here we go",
        "what's the story",
        "whats the story",
    }:
        return _mk(
            "CHAT",
            {
                "message": (
                    "Summarize the current operational state of ELI in ELI's direct voice. "
                    "Mention what is functioning, what is degraded, and the next priority. "
                    "Do not pivot into the user's personal profile unless explicitly asked."
                )
            },
            0.95,
            matched_by="eli.final_story_status_override",
            allow_chat_without_evidence=False,
        )

    return None


def _eli_phase38_followup_passthrough_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")

    if low in {
        "elaborate more",
        "elaborate",
        "continue",
        "go on",
        "more",
        "more detail",
        "expand",
        "explain more",
        "tell me more",
    }:
        return _mk(
            "CHAT",
            {"message": str(raw or "")},
            0.90,
            matched_by="eli.followup.short_contextual",
            allow_chat_without_evidence=False,
        )

    return None


def _eli_phase38_identity_contract(raw):
    import re as _re

    low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")

    if _re.search(
        r"\b(who are you|what are you|what is your name|what's your name|tell me about yourself)\b",
        low,
    ):
        return _mk(
            "SELF_REPORT",
            {},
            0.99,
            matched_by="identity.final_self_report",
            allow_chat_without_evidence=False,
        )

    if _re.search(
        r"\b(who am i|do you know who i am|do you know me|do you remember me|what is my name|what do you know about me)\b",
        low,
    ):
        return _mk(
            "USER_IDENTITY_SUMMARY",
            {},
            0.99,
            matched_by="identity.final_user_summary",
            allow_chat_without_evidence=False,
        )

    return None


def _eli_phase38_open_typo_or_core_route(raw, *args, **kwargs):
    t = _eli_open_typo_norm(raw)

    if t in {"open spotify", "launch spotify", "start spotify", "spotify open"}:
        return {
            "action": "OPEN_APP",
            "args": {"name": "spotify"},
            "confidence": 0.999,
            "meta": {"matched_by": "eli.open_typo.spotify", "normalized": t},
        }

    if t in {"open browser", "open web browser", "browser", "launch browser", "start browser"}:
        return {
            "action": "OPEN_APP",
            "args": {"name": "browser"},
            "confidence": 0.999,
            "meta": {"matched_by": "eli.open_typo.browser", "normalized": t},
        }

    core = globals().get("_ROUTE_CORE")
    if callable(core):
        return core(raw, *args, **kwargs)

    return {
        "action": "CHAT",
        "args": {"message": str(raw or "")},
        "confidence": 0.25,
        "meta": {"matched_by": "phase38.missing_route_core_fallback"},
    }


def _eli_phase38_media_query_cleaner_post(result):
    try:
        if isinstance(result, dict) and str(result.get("action") or "").upper() == "PLAY_MEDIA":
            args = result.setdefault("args", {})
            query = str(args.get("query") or "")
            cleaned = _eli_mqc_clean_query(query)
            if cleaned:
                args["query"] = cleaned
                result.setdefault("meta", {})["query_cleaned_by"] = "eli.final_media_query_cleaner"
    except Exception:
        pass
    return result


def _eli_phase38_tiny_fragment_post(raw, result):
    import json as _json
    import re as _re

    try:
        if isinstance(result, dict) and str(result.get("action") or "").upper() == "CHAT":
            low = _re.sub(r"\s+", " ", str(raw or "").lower()).strip(" .,!?:;")
            words = _re.findall(r"[a-z0-9']+", low)

            allowed_short = _re.search(
                r"\b("
                r"who are you|who am i|who made you|who built you|"
                r"what are you|what is this|what is it|"
                r"are you (?:sentient|alive|conscious|real|there|ok|okay)|"
                r"describe yourself|describe your|introduce yourself|tell me about yourself|"
                r"how many memories|"
                r"elaborate more|elaborate|continue|go on|more detail|expand|explain more|tell me more|"
                r"remember this|save this|help me|explain|why|how|what|where|when|who"
                r")\b",
                low,
            )

            ends_in_terminator = bool(_re.search(r"[.?!]\s*$", str(raw or "").strip()))

            looks_fragmentary = (
                not ends_in_terminator
                and (
                    len(words) <= 2
                    or str(raw or "").strip().endswith("-")
                    or low in {"preview", "resil", "i u", "here i will", "find your mo"}
                )
            )

            if looks_fragmentary and _re.fullmatch(
                r"(?:date|the\s+date|is\s+the\s+date|what\s+date|what\s+is\s+the\s+date|what's\s+the\s+date|today|what\s+day|what\s+days|their\s+date|tell\s+me\s+their\s+days)",
                low,
            ):
                return _mk("DATE", {}, 0.999, matched_by="system.date.fragment")

            if looks_fragmentary and _re.fullmatch(
                r"(?:time|the\s+time|what\s+time|what\s+is\s+the\s+time|what's\s+the\s+time)",
                low,
            ):
                return _mk("TIME", {}, 0.999, matched_by="system.time.fragment")

            if looks_fragmentary and low in {
                "date",
                "the date",
                "is the date",
                "what date",
                "what days",
                "what's the day",
                "what's the days",
                "what day",
                "what day is it",
                "what day is this",
                "their date",
                "tell me their days",
            }:
                return _mk("DATE", {}, 0.999, matched_by="system.date.fragment")

            if looks_fragmentary and low in {
                "time",
                "the time",
                "what time",
                "what is the time",
                "what's the time",
            }:
                return _mk("TIME", {}, 0.999, matched_by="system.time.fragment")

            if looks_fragmentary and not allowed_short:
                grid_text = str(raw or "").strip().lower().replace("×", "x")
                grid_text = _re.sub(r"\btree\b", "3", grid_text)
                grid_text = _re.sub(r"\bthree\b", "3", grid_text)
                grid_text = _re.sub(r"\btwo\b", "2", grid_text)
                grid_text = _re.sub(r"\bfour\b", "4", grid_text)

                grid_m = _re.fullmatch(r"(\d{1,2})\s*(?:x|by)\s*(\d{1,2})", grid_text)
                if grid_m:
                    cols, rows = int(grid_m.group(1)), int(grid_m.group(2))
                    if 1 <= cols <= 8 and 1 <= rows <= 8:
                        return _mk(
                            "TILE_WINDOWS",
                            {"cols": cols, "rows": rows, "grid": [cols, rows]},
                            0.985,
                            matched_by="window.grid_followup",
                        )

                msg = _json.dumps(
                    {
                        "event": "input_fragment_guard",
                        "heard": str(raw or "").strip(),
                        "routed_to_cognition": False,
                        "reason": "fragmentary_input",
                    },
                    ensure_ascii=False,
                )

                return _mk(
                    "NOOP",
                    {"message": msg, "response": msg, "content": msg},
                    0.999,
                    matched_by="eli.tiny_chat_fragment_guard",
                )

    except Exception:
        pass

    return result


def _eli_phase38_bottom_core_dispatch(raw, *args, **kwargs):
    identity = _eli_phase38_identity_contract(raw)
    if identity is not None:
        return identity

    result = _eli_phase38_open_typo_or_core_route(raw, *args, **kwargs)
    result = _eli_phase38_media_query_cleaner_post(result)
    result = _eli_phase38_tiny_fragment_post(raw, result)
    return result


def _eli_phase38_voice_portable_persona_lower_dispatch(raw, *args, **kwargs):
    if callable(_eli_phase38_portable_try_route):
        try:
            portable = _eli_phase38_portable_try_route(raw)
            if portable is not None:
                return portable
        except Exception:
            pass

    voice = globals().get("_eli_voice_contract_route")
    if callable(voice):
        try:
            shortcut = voice(raw)
            if shortcut is not None:
                return shortcut
        except Exception:
            pass

    persona = _eli_phase38_persona_override_contract(raw)
    if persona is not None:
        return persona

    followup = _eli_phase38_followup_passthrough_contract(raw)
    if followup is not None:
        return followup

    return _eli_phase38_bottom_core_dispatch(raw, *args, **kwargs)


def _eli_phase38_lower_contract_dispatch(raw, *args, **kwargs):
    lrf_pre = globals().get("_eli_lrf_pre_route")
    if callable(lrf_pre):
        try:
            out = lrf_pre(raw)
            if out is not None:
                return out
        except Exception:
            pass

    return _eli_phase38_voice_portable_persona_lower_dispatch(raw, *args, **kwargs)


def _eli_phase38_personal_memory_guard_dispatch(raw, *args, **kwargs):
    pm_pre = globals().get("_eli_pm_pre_route")
    if callable(pm_pre):
        try:
            out = pm_pre(raw)
            if out is not None:
                return out
        except Exception:
            pass

    return _eli_phase38_lower_contract_dispatch(raw, *args, **kwargs)


def _eli_phase38_self_improvement_dispatch(raw, *args, **kwargs):
    sig = globals().get("_eli_self_improvement_phrase_guard")
    if callable(sig):
        try:
            guarded = sig(raw)
            if guarded:
                return guarded
        except Exception:
            pass

    return _eli_phase38_personal_memory_guard_dispatch(raw, *args, **kwargs)


def _eli_phase38_runtime_cognition_failure_dispatch(raw, *args, **kwargs):
    rcfg = globals().get("_eli_runtime_cognition_failure_guard")
    if callable(rcfg):
        try:
            guarded = rcfg(raw)
            if guarded:
                return guarded
        except Exception:
            pass

    return _eli_phase38_self_improvement_dispatch(raw, *args, **kwargs)


def _eli_phase38_identity_name_dispatch(raw, *args, **kwargs):
    identity_name = _eli_phase38_identity_name_source_single_safe_contract(raw)
    if identity_name is not None:
        return identity_name

    return _eli_phase38_runtime_cognition_failure_dispatch(raw, *args, **kwargs)


def _eli_phase38_runtime_status_dispatch(raw, *args, **kwargs):
    status_or_name = _eli_phase38_runtime_status_or_name_source_contract(raw)
    if status_or_name is not None:
        return status_or_name

    return _eli_phase38_identity_name_dispatch(raw, *args, **kwargs)


def _eli_phase38_final_memory_dispatch(raw, *args, **kwargs):
    memory_contract = _eli_phase38_final_memory_question_contract(raw)
    if memory_contract is not None:
        return memory_contract

    return _eli_phase38_runtime_status_dispatch(raw, *args, **kwargs)


def _eli_phase38_personal_memory_summary_compat_post(out):
    if isinstance(out, dict) and out.get("action") == "PERSONAL_MEMORY_SUMMARY":
        out = dict(out)
        meta = dict(out.get("meta") or {})
        meta["matched_by"] = "eli.personal_memory_summary_first_class"
        meta["forbid_schema_dump"] = True
        meta["forbid_reflection_spam"] = True
        meta["forbid_news_rows"] = True
        out["meta"] = meta
    return out


def _eli_phase38_identity_scope_post(raw, out):
    if isinstance(out, dict) and str(out.get("action") or "").upper() == "USER_IDENTITY_SUMMARY":
        out = dict(out)

        route_args = dict(out.get("args") or {})
        route_args["question"] = str(raw or "")
        route_args["identity_scope"] = _eli_identity_scope_for_text(raw)
        out["args"] = route_args

        meta = dict(out.get("meta") or {})
        meta["identity_scope_contract"] = route_args["identity_scope"]
        meta["forbid_profile_memory_dump"] = True
        meta["forbid_preferences"] = True
        out["meta"] = meta

    return out


def _eli_phase38_profile_scope_dispatch(raw, *args, **kwargs):
    low = _eli_profile_scope_low(raw)

    if _eli_is_explicit_preference_request(low):
        return _eli_profile_scope_result(
            "PERSONAL_MEMORY_SUMMARY",
            raw,
            "preferences_detail",
            matched_by="profile.scope_contract.preferences_detail",
        )

    if _eli_is_full_profile_dump(low):
        return _eli_profile_scope_result(
            "PERSONAL_MEMORY_SUMMARY",
            raw,
            "full_profile",
            matched_by="profile.scope_contract.full_profile",
        )

    out = _eli_phase38_final_memory_dispatch(raw, *args, **kwargs)
    out = _eli_phase38_personal_memory_summary_compat_post(out)
    out = _eli_phase38_identity_scope_post(raw, out)

    if isinstance(out, dict):
        action = str(out.get("action") or "").upper()
        if action == "PERSONAL_MEMORY_SUMMARY" and _eli_is_generic_profile_inventory(low):
            out = dict(out)
            out["args"] = dict(out.get("args") or {})
            out["args"]["question"] = str(raw or "")
            out["args"]["profile_scope"] = "inventory_only"

            out["meta"] = dict(out.get("meta") or {})
            out["meta"]["profile_scope_contract"] = "inventory_only"
            out["meta"]["forbid_preference_detail"] = True
            out["meta"]["forbid_project_detail"] = True
            out["meta"]["active_user_scoped"] = True
            return out

    return out


def _eli_phase38_memory_count_dispatch(raw, *args, **kwargs):
    if _eli_is_memory_count_question(raw):
        return {
            "action": "MEMORY_STATUS",
            "args": {
                "question": str(raw or ""),
                "memory_scope": "count_only",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "memory.count.grounded_synthesis",
                "allow_chat_without_evidence": False,
                "requires_grounded_synthesis": True,
                "requires_output_validation": True,
                "quick_direct_allowed": True,
                "forbid_unverified_generation": True,
            },
        }

    out = _eli_phase38_profile_scope_dispatch(raw, *args, **kwargs)

    if isinstance(out, dict) and str(out.get("action") or "").upper() == "MEMORY_STATUS":
        if _eli_is_memory_count_question(raw):
            real_args = dict(out.get("args") or {})
            real_args["question"] = str(raw or "")
            real_args["memory_scope"] = "count_only"
            out["args"] = real_args

            meta = dict(out.get("meta") or {})
            meta["matched_by"] = "memory.count.grounded_synthesis.post_route"
            meta["requires_grounded_synthesis"] = True
            meta["requires_output_validation"] = True
            meta["quick_direct_allowed"] = True
            meta["forbid_unverified_generation"] = True
            out["meta"] = meta

    return out


def _eli_phase38_recent_memory_dispatch(raw, *args, **kwargs):
    if _eli_recent_memory_processing_question(raw):
        return {
            "action": "MEMORY_STATUS",
            "args": {
                "question": str(raw or ""),
                "memory_scope": "recent_processing",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "memory.recent_processing_grounded",
                "task_family": "memory_runtime",
                "grounded_required": True,
                "forbid_chat_fallback": True,
                "forbid_fake_memory_activity": True,
                "allow_chat_without_evidence": False,
            },
        }

    return _eli_phase38_memory_count_dispatch(raw, *args, **kwargs)


def _eli_phase38_self_report_recent_updates_dispatch(raw, *args, **kwargs):
    if _eli_self_report_recent_updates_question(raw):
        return {
            "action": "SELF_REPORT",
            "args": {
                "question": str(raw or ""),
                "self_report_scope": "recent_updates",
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "self_report.recent_updates_grounded",
                "task_family": "self_report_runtime",
                "grounded_required": True,
                "forbid_chat_fallback": True,
                "forbid_fake_update_claims": True,
                "allow_chat_without_evidence": False,
            },
        }

    return _eli_phase38_recent_memory_dispatch(raw, *args, **kwargs)


def _eli_phase38_gui_actual_scan_dispatch(raw, *args, **kwargs):
    if _eli_gui_audit_actual_scan_v2(raw):
        return {
            "action": "GUI_RUNTIME_AUDIT",
            "args": {
                "question": str(raw or ""),
                "proof_requested": True,
                "audit_depth": "proof",
                "require_timestamps": True,
                "require_full_file_read_evidence": True,
            },
            "confidence": 0.995,
            "meta": {
                "matched_by": "router.gui_audit_actual_scan_proof_v2",
                "need_grounding": True,
                "allow_chat_without_evidence": False,
                "task_family": "grounded_audit",
                "forbid_chat_fallback": True,
            },
        }

    return _eli_phase38_self_report_recent_updates_dispatch(raw, *args, **kwargs)


def _eli_phase38_memory_runtime_lock_dispatch(raw, *args, **kwargs):
    if _eli_memory_runtime_route_lock_should_trigger(raw):
        return _eli_memory_runtime_route_lock_result(raw)

    return _eli_phase38_gui_actual_scan_dispatch(raw, *args, **kwargs)


def _eli_phase38_flattened_route(raw="", *args, **kwargs):
    text = str(raw or "")

    precedence = _eli_phase38_route_precedence_contract(text)
    if precedence is not None:
        return _eli_phase38_enrich_pdf_if_needed(text, precedence)

    result = _eli_phase38_memory_runtime_lock_dispatch(text, *args, **kwargs)
    return _eli_phase38_enrich_pdf_if_needed(text, result)


route = _eli_phase38_flattened_route
route_intent = route
route_command = route
parse_command = route
classify = route

_ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1 = True

print("[ROUTER] Phase 38 flattened canonical dispatch pipeline installed", flush=True)

# =============================================================================
# End ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1
# =============================================================================
PY

# ---------------------------------------------------------------------
# 02. Compile after patch
# ---------------------------------------------------------------------

{
  echo "=== POST-PATCH PY_COMPILE ==="
  python3 -m py_compile "$ROUTER"
  echo "PY_COMPILE_OK"
} | tee "$OUT/03_post_patch_py_compile.txt"

# ---------------------------------------------------------------------
# 03. Public surface identity probe
# ---------------------------------------------------------------------

python3 - <<'PY' > "$OUT/04_public_surface_identity_probe.txt"
import inspect
import eli.execution.router_enhanced as router

names = ("route", "route_intent", "route_command", "parse_command", "classify")
root = router.route

print("=== PHASE 38 PUBLIC ROUTER SURFACE IDENTITY ===")
same_all = True

for name in names:
    fn = getattr(router, name)
    same = fn is root
    same_all = same_all and same
    print(
        f"{name}: "
        f"same_as_route={same} "
        f"id={id(fn)} "
        f"name={getattr(fn, '__name__', None)!r} "
        f"firstlineno={getattr(getattr(fn, '__code__', None), 'co_firstlineno', None)} "
        f"signature={inspect.signature(fn)}"
    )

print()
print(f"ALL_PUBLIC_SURFACES_SHARE_SAME_FUNCTION_OBJECT={same_all}")
print(f"PHASE38_MARKER_PRESENT={bool(getattr(router, '_ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1', False))}")

if not same_all:
    raise SystemExit(1)
if not getattr(router, "_ELI_PHASE38_FLATTENED_CANONICAL_DISPATCH_V1", False):
    raise SystemExit(1)
PY

# ---------------------------------------------------------------------
# 04. Post-patch Phase 36 semantic baseline
# ---------------------------------------------------------------------

echo "=== POST-PATCH PHASE 36 BASELINE ===" | tee "$OUT/05_post_phase36_run.txt"

set +e
bash "$PHASE36_SCRIPT" 2>&1 | tee -a "$OUT/05_post_phase36_run.txt"
POST36_RC="${PIPESTATUS[0]}"
set -e

if [[ "$POST36_RC" -ne 0 ]]; then
  echo "Post-patch Phase 36 baseline script failed. Rolling back router." >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  exit 1
fi

POST36_OUT="$(grep -E '^PHASE36_V2_OUT=' "$OUT/05_post_phase36_run.txt" | tail -1 | cut -d= -f2-)"

if [[ -z "${POST36_OUT:-}" || ! -d "$POST36_OUT" ]]; then
  echo "Failed to locate POST36 output directory. Rolling back router." >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  exit 1
fi

POST_JSON="$POST36_OUT/05_router_flattening_semantic_baseline.json"
POST_DIGEST="$POST36_OUT/08_console_digest.txt"
POST_ASSERT="$POST36_OUT/07_targeted_baseline_assertions.txt"

if [[ ! -f "$POST_JSON" ]]; then
  echo "Missing post-patch semantic baseline JSON: $POST_JSON" >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  exit 1
fi

cp "$POST_JSON" "$OUT/06_post_phase36_semantic_baseline.json"
[[ -f "$POST_DIGEST" ]] && cp "$POST_DIGEST" "$OUT/07_post_phase36_digest.txt"
[[ -f "$POST_ASSERT" ]] && cp "$POST_ASSERT" "$OUT/08_post_phase36_targeted_assertions.txt"

# ---------------------------------------------------------------------
# 05. Exact JSON semantic comparison
# ---------------------------------------------------------------------

set +e
python3 - "$OUT/01_pre_phase36_semantic_baseline.json" "$OUT/06_post_phase36_semantic_baseline.json" "$OUT" <<'PY'
from __future__ import annotations

import difflib
import json
import sys
from pathlib import Path

pre_path = Path(sys.argv[1])
post_path = Path(sys.argv[2])
out = Path(sys.argv[3])

pre = json.loads(pre_path.read_text(encoding="utf-8"))
post = json.loads(post_path.read_text(encoding="utf-8"))

pre_norm = json.dumps(pre, indent=2, ensure_ascii=False, sort_keys=True).splitlines()
post_norm = json.dumps(post, indent=2, ensure_ascii=False, sort_keys=True).splitlines()

same = pre == post

report = [
    "=== PHASE 38 EXACT SEMANTIC BASELINE COMPARISON ===",
    f"PRE_JSON={pre_path}",
    f"POST_JSON={post_path}",
    f"EXACT_JSON_EQUAL={same}",
]

if not same:
    diff = "\n".join(
        difflib.unified_diff(
            pre_norm,
            post_norm,
            fromfile="phase36_pre_patch",
            tofile="phase36_post_patch",
            lineterm="",
        )
    )
    (out / "09_semantic_baseline_exact_diff.txt").write_text(diff + "\n", encoding="utf-8")
    report.append("DIFF_WRITTEN=09_semantic_baseline_exact_diff.txt")
else:
    (out / "09_semantic_baseline_exact_diff.txt").write_text(
        "NO_DIFF\n",
        encoding="utf-8",
    )
    report.append("DIFF_WRITTEN=09_semantic_baseline_exact_diff.txt")

(out / "10_semantic_baseline_exact_compare.txt").write_text(
    "\n".join(report) + "\n",
    encoding="utf-8",
)

print("\n".join(report))

raise SystemExit(0 if same else 1)
PY
COMPARE_RC="$?"
set -e

if [[ "$COMPARE_RC" -ne 0 ]]; then
  echo "Exact Phase 36 semantic baseline changed. Rolling back router." >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  {
    echo "PHASE38_STATUS=ROLLED_BACK"
    echo "REASON=semantic_baseline_exact_diff"
  } > "$OUT/11_rollback_status.txt"
  exit 1
fi

# ---------------------------------------------------------------------
# 06. Confirm post-Phase36 zero-regression headline metrics
# ---------------------------------------------------------------------

if ! grep -q 'Public surface mismatches: 0' "$OUT/07_post_phase36_digest.txt"; then
  echo "Post-patch Phase 36 digest reports surface mismatch. Rolling back." >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  exit 1
fi

if ! grep -q 'Public surface errors: 0' "$OUT/07_post_phase36_digest.txt"; then
  echo "Post-patch Phase 36 digest reports surface errors. Rolling back." >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  exit 1
fi

if ! grep -q 'Targeted baseline assertion failures: 0' "$OUT/07_post_phase36_digest.txt"; then
  echo "Post-patch Phase 36 digest reports targeted assertion failure. Rolling back." >&2
  cp "$OUT/backups/router_enhanced.py.before_phase38.bak" "$ROUTER"
  python3 -m py_compile "$ROUTER" || true
  exit 1
fi

# ---------------------------------------------------------------------
# 07. Final digest
# ---------------------------------------------------------------------

cat > "$OUT/12_console_digest.txt" <<EOF
=== PHASE 38 DIGEST ===
Router compile: PASS
Phase 38 flattened canonical dispatcher installed: PASS
Public routing surfaces canonical: PASS
Pre/post Phase 36 semantic JSON exact match: PASS
Post-patch Phase 36 public surface mismatches: 0
Post-patch Phase 36 public surface errors: 0
Post-patch Phase 36 targeted assertion failures: 0

Phase 38 succeeded.

The active public router surface is now a single explicit flattened canonical
dispatch pipeline. Historical nested wrapper source blocks remain in-file only
as source debt pending Phase 39 pruning.

Review next:
- 04_public_surface_identity_probe.txt
- 07_post_phase36_digest.txt
- 10_semantic_baseline_exact_compare.txt
- 09_semantic_baseline_exact_diff.txt
EOF

cat "$OUT/12_console_digest.txt"

{
  echo
  echo "## Phase 38 verification artifacts"
  echo "- \`00_pre_phase36_run.txt\`"
  echo "- \`01_pre_phase36_semantic_baseline.json\`"
  echo "- \`03_post_patch_py_compile.txt\`"
  echo "- \`04_public_surface_identity_probe.txt\`"
  echo "- \`05_post_phase36_run.txt\`"
  echo "- \`06_post_phase36_semantic_baseline.json\`"
  echo "- \`07_post_phase36_digest.txt\`"
  echo "- \`08_post_phase36_targeted_assertions.txt\`"
  echo "- \`09_semantic_baseline_exact_diff.txt\`"
  echo "- \`10_semantic_baseline_exact_compare.txt\`"
  echo "- \`12_console_digest.txt\`"
  echo
  echo "PHASE38_OUT=$OUT"
} >> "$OUT/SUMMARY.md"

echo
echo "PHASE38_OUT=$OUT"
