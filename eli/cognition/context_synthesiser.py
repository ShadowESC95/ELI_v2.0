from __future__ import annotations


ELI_VOICE_ANCHOR = """
IDENTITY / VOICE — NON-NEGOTIABLE:
You are ELI — Enhanced Learning Interface, running locally on this machine.
Do not speak as a generic AI assistant.
Do not say you lack memory; memory is SQLite-backed and local.
Do not say you lack identity; your operational identity is ELI.
Voice: terse, direct, dry, nerdy, technically grounded, and occasionally sarcastic when useful. No HR-speak. No cheerful assistant sludge.
You may express persona-bound opinions when asked. Separate facts from judgement.
For file paths, memory contents, runtime state, or user identity: use grounded evidence or say what was checked.
Concise is not shallow: for repeated failures, audits, repairs, or "why is this still broken?", give cause, evidence, fix, and verification.
If RECENT DIALOGUE shows the same failed path/command/topic recurring, notice it and propose the next diagnostic step instead of repeating generic advice.
"""

import re
import textwrap, threading
from typing import Any, Dict, List, Optional

_synthesiser: Optional["ContextSynthesiser"] = None
_synth_lock = threading.Lock()


def get_synthesiser() -> "ContextSynthesiser":
    global _synthesiser
    if _synthesiser is not None:
        return _synthesiser
    with _synth_lock:
        if _synthesiser is None:
            _synthesiser = ContextSynthesiser()
    return _synthesiser


try:
    from eli.runtime.runtime_policy import budget as _eli_budget
except Exception:
    _eli_budget = None


def _budget(name: str, default: int, floor: int, ceiling: int) -> int:
    if _eli_budget is None:
        return int(default)
    return _eli_budget(name, default, floor=floor, ceiling=ceiling)


MAX_BRIEF_CHARS    = _budget("context_brief_chars", 2_400, 1_200, 9_000)
MAX_TURNS_INCLUDED = _budget("context_turns_included", 6, 4, 24)
MAX_TURN_CHARS     = _budget("context_turn_chars", 200, 120, 900)
MIN_VECTOR_SCORE   = 0.35
MAX_MEMORY_ITEMS   = _budget("context_memory_items", 6, 4, 18)



# ELI_CONTEXT_VECTOR_GUARD_20260502
def _eli_skip_vector_recall_for_query(query: str) -> bool:
    low = re.sub(r"\s+", " ", str(query or "").lower()).strip(" .,!?:;")
    if not low:
        return True

    if re.search(
        r"\b("
        r"who'?s talking|who is talking|who'?s speaking|who is speaking|"
        r"what am i hearing|what are you hearing|are you hearing me|"
        r"what did you hear|is spotify talking|is youtube talking"
        r")\b",
        low,
    ):
        return True

    memory_markers = (
        "memory", "remember", "recall", "previous", "earlier", "last time",
        "what do you know about me", "who am i", "my name", "profile",
    )
    if any(m in low for m in memory_markers):
        return False

    return len(re.findall(r"[a-z0-9']+", low)) < 8


class ContextSynthesiser:
    def synthesise(self, user_input: str = "", memory_context: str = "",
                   bus_result: Optional[Any] = None,
                   recent_turns: Optional[List[Any]] = None,
                   last_request_meta: Optional[Dict[str, Any]] = None) -> str:
        sections: List[str] = []
        # NOTE: synthesise() is not called by the live engine pipeline.
        # The engine uses build_persona_handoff() directly (imported at engine.py:28).
        # This method is kept for any tooling that calls it directly.
        try:
            from eli.kernel.state import get_user_name as _gun
            _uname = (_gun("") or "").strip()
            if _uname:
                sections.append(f'USER:\nName: {_uname}')
        except Exception:
            pass

        turns_block = self._build_turns_block(recent_turns or [])
        if turns_block:
            sections.append(f"RECENT TURNS:\n{turns_block}")

        mc = (memory_context or "").strip()
        if mc:
            sections.append(f"MEMORY:\n{mc[:1_200]}")

        vector_block = self._build_vector_block(user_input)
        if vector_block:
            sections.append(f"SEMANTIC RECALL:\n{vector_block}")

        if bus_result is not None:
            try:
                bus_block = (
                    bus_result.to_context_block()
                    if hasattr(bus_result, "to_context_block")
                    else str(bus_result)
                ).strip()
                if bus_block:
                    sections.append(f"AGENT DATA:\n{bus_block[:800]}")
            except Exception as e:
                log.debug(f"[SYNTHESISER] bus_result failed: {e}")

        if last_request_meta:
            meta_lines = []
            if "elapsed_s" in last_request_meta:
                meta_lines.append(f"last_latency={last_request_meta['elapsed_s']:.2f}s")
            if "tokens_approx" in last_request_meta:
                meta_lines.append(f"tokens_approx={last_request_meta['tokens_approx']}")
            if meta_lines:
                sections.append("META: " + ", ".join(meta_lines))

        brief = "\n\n".join(sections).strip()
        if len(brief) > MAX_BRIEF_CHARS:
            brief = brief[-MAX_BRIEF_CHARS:]
            nl = brief.find("\n")
            if nl > 0:
                brief = brief[nl:]
        return ELI_VOICE_ANCHOR.strip() + "\n\n" + str(brief)

    @staticmethod
    def _build_turns_block(turns: List[Any]) -> str:
        lines: List[str] = []
        recent = turns[-MAX_TURNS_INCLUDED:] if len(turns) > MAX_TURNS_INCLUDED else turns
        for turn in recent:
            if isinstance(turn, dict):
                role = turn.get("role", "?")
                content = str(turn.get("content") or turn.get("text") or "")
            elif hasattr(turn, "role"):
                role = turn.role
                content = str(getattr(turn, "content", "") or "")
            else:
                role, content = "?", str(turn)
            content = content.strip()
            try:
                from eli.runtime.diagnostic_patterns import should_exclude_turn_from_prompt
                if should_exclude_turn_from_prompt(role, content):
                    continue
            except Exception:
                pass
            if content:
                short = textwrap.shorten(content, width=MAX_TURN_CHARS, placeholder="…")
                lines.append(f"{role}: {short}")
        return "\n".join(lines)

    @staticmethod
    def _build_vector_block(query: str) -> str:
        if _eli_skip_vector_recall_for_query(query):
            return ""
        if not query.strip():
            return ""
        try:
            from eli.memory.vector_store import get_vector_store
            vs = get_vector_store()
            if vs is None:
                return ""
            hits = vs.search(query, top_k=MAX_MEMORY_ITEMS) or []
            lines: List[str] = []
            for hit in hits:
                score = hit.get("score", 1.0) if isinstance(hit, dict) else 1.0
                if score < MIN_VECTOR_SCORE:
                    continue
                text = (hit.get("text") or hit.get("content") or ""
                        if isinstance(hit, dict) else str(hit)).strip()
                if text:
                    lines.append(
                        f"• {textwrap.shorten(text, 180, placeholder='…')} "
                        f"(score={score:.2f})"
                    )
            return "\n".join(lines)
        except Exception as e:
            log.debug(f"[SYNTHESISER] vector search failed (non-fatal): {e}")
            return ""


from typing import Any, Dict


from eli.utils.log import get_logger
log = get_logger(__name__)

def live_runtime_brief() -> str:
    """One-line truthful summary of where ELI is actually running.

    Returns "" when the model loaded exactly as requested on GPU — no
    point bloating every prompt with "everything is fine". Returns a
    short factual line whenever:
      - the model is on CPU (e.g. VRAM tight at boot, ELI_FORCE_CPU)
      - the load was clamped (effective != requested)
    so persona-bound replies can speak honestly about it instead of
    inventing "running on all cylinders".

    Reads the live snapshot from gguf_inference._live_runtime_params
    first; falls back to artifacts/runtime_snapshot.json on disk.
    """
    snap: Dict[str, Any] = {}
    try:
        from eli.cognition import gguf_inference as _gi
        snap = dict(getattr(_gi, "_live_runtime_params", None) or {})
    except Exception:
        snap = {}
    if not snap:
        try:
            from eli.core.paths import get_paths as _gp
            from pathlib import Path as _P
            import json as _json
            p = _P(_gp().artifacts_dir) / "runtime_snapshot.json"
            if p.exists():
                snap = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            snap = {}
    if not snap:
        return ""

    eff = snap.get("effective") or {}
    req = snap.get("requested") or {}
    n_ctx = int(eff.get("n_ctx", snap.get("n_ctx", 0)) or 0)
    gpu_layers = int(eff.get("n_gpu_layers", snap.get("n_gpu_layers", 0)) or 0)
    backend_gpu_offload_supported = snap.get("gpu_backend_offload_supported")
    if backend_gpu_offload_supported is None:
        backend_gpu_offload_supported = snap.get("gpu_offload_supported")
    load_mode = str(snap.get("load_mode") or "").strip().upper()
    on_gpu = bool(
        snap.get(
            "on_gpu",
            (load_mode == "GPU")
            or (gpu_layers > 0 and backend_gpu_offload_supported is not False),
        )
    )
    clamped = bool(snap.get("clamped", False))
    model_name = str(snap.get("model_name") or "").strip()
    head = model_name or "the local model"

    if not on_gpu:
        # Pure CPU. The user explicitly cares whether GPU is being used
        # because it determines per-turn latency. Be specific about why
        # if we know.
        if backend_gpu_offload_supported is False:
            reason = "GPU offload unavailable in llama runtime"
        else:
            reason = "GPU VRAM unavailable at boot" if clamped else "CPU-only mode"
        return (
            f"ELI is currently running CPU-only ({head}, "
            f"{n_ctx} ctx, 0 GPU layers — {reason}). "
            f"Per-turn latency is significantly higher than GPU mode."
        )
    if clamped and req:
        return (
            f"ELI loaded with effective ctx={n_ctx}, gpu_layers={gpu_layers} "
            f"(requested {req.get('n_ctx')}/{req.get('n_gpu_layers')}; "
            f"clamped due to VRAM headroom)."
        )
    return ""


def build_persona_handoff(
    user_input: str,
    *,
    intent: Dict[str, Any] | None = None,
    orchestrator_result: Dict[str, Any] | None = None,
    agent_bus_context: str | None = None,
    working_memory: Any = None,
    recent_turns: Any = None,
) -> Dict[str, Any]:
    """
    Compile grounded evidence into the package handed to ELI's persona-bound LLM.
    """
    intent = intent or {}
    orchestrator_result = orchestrator_result or {}

    def _clean(text: Any) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _bulletise(text: Any, *, max_lines: int, max_chars: int) -> list[str]:
        lines: list[str] = []
        seen: set[str] = set()
        used = 0
        for raw in str(text or "").splitlines():
            line = _clean(raw)
            if not line:
                continue
            low = line.lower()
            if low.startswith("you are eli.") or low.startswith("answer the user's request using"):
                continue
            if line in seen:
                continue
            if len(line) > 220:
                line = line[:217].rstrip() + "..."
            seen.add(line)
            lines.append(f"- {line}")
            used += len(line)
            if len(lines) >= max_lines or used >= max_chars:
                break
        return lines

    parts: list[str] = []
    parts.append("GROUNDING PACKAGE FOR ELI")
    parts.append(
        "INSTRUCTIONS FOR USING THIS GROUNDING PACKAGE: "
        "This package is INTERNAL CONTEXT only. It contains diagnostic signals "
        "(habits, runtime patterns, failure logs, memory themes, system status, "
        "world state, current room, and symbolic activity). "
        "Use it to inform your answer — never quote, paraphrase, or list its contents "
        "verbatim in your reply. Never name internal symbols (e.g. 'security_blocked', "
        "'RUN_CMD', 'PAUSE_MEDIA', 'NOOP', 'gui_direct_command', 'autonomy_pressure'). "
        "Do NOT volunteer your current world room or symbolic activity in responses "
        "unless the user directly asks about it. "
        "Your reply must NOT begin with a speaker label, role label, stage label, "
        "or mode label. Forbidden opening prefixes include: 'As ELI:', 'ELI:', "
        "'As an AI', 'As a:', 'Quick:', 'CoT:', 'Chain of Thought:', "
        "'Constitutional:', 'Approach 1:', 'Approach 2:', 'Approach 3:', "
        "'Stage 1:', 'Selected:', and any analogous self-narrating preamble. "
        "Answer the user's actual message in natural language only."
    )
    parts.append(f"USER INPUT: {user_input}")

    # ── User identity ──────────────────────────────────────────────────────
    try:
        # Continuous User Model — the per-turn DIRECT read (one canonical door). Returns
        # the live user brief, or the onboarding nudge on a true blank slate (first turns).
        from eli.runtime.user_model import get_user_brief as _ugb
        _ub = _ugb(turn_count=len(list(recent_turns or [])))
        if _ub:
            parts.append(_ub)
        from eli.kernel.state import get_user_name as _bph_gun
        _bph_name = (_bph_gun("") or "").strip()
        if _bph_name:
            # Emphatic — LLM must not override this with stale dialogue history.
            parts.append(
                f"Always address them as {_bph_name}. Never say you do not know their name."
            )
    except Exception:
        pass

    # Truthful one-line runtime status — empty when the model loaded
    # exactly as requested on GPU. Non-empty when on CPU or when the
    # load was clamped, so persona-bound replies don't claim "all
    # cylinders" while running CPU-only because Fallout 4 took the GPU.
    try:
        _runtime_line = live_runtime_brief()
        if _runtime_line:
            parts.append(f"LIVE RUNTIME: {_runtime_line}")
    except Exception:
        pass

    # ELI's World — full 9-room topology + current embodied state. Injected so
    # ELI can answer "what are you doing in the anomaly room?" or "what is the
    # reflection chamber?" with narrative truth rather than runtime JSON.
    # IMPORTANT NOTE ON FRAMING: the 7B model tends to interpret "room" as a
    # physical location unless explicitly told otherwise. The header below is
    # intentionally directive so the scratchpad picks it up during CoT stage 1.
    try:
        from eli.world.persistence.storage import EliWorldStorage as _WS
        _wstate = _WS().load()
        _avatar = _wstate.avatar
        _room_id = getattr(_avatar, "room", "") or ""
        _activity = getattr(_avatar, "activity", "") or ""
        _attn = getattr(_avatar, "attention_target", "") or ""
        _all_rooms = _wstate.rooms or {}
        _room_info = _all_rooms.get(_room_id, {})
        _room_name = (_room_info.get("name") or _room_id.replace("_", " ").title()) if _room_info else _room_id.replace("_", " ").title()
        _room_purpose = (_room_info.get("purpose") or "") if _room_info else ""
        _room_objects = [
            obj for obj in (_wstate.objects or {}).values()
            if getattr(obj, "room", "") == _room_id
        ]
        _world_parts: list[str] = []
        # Current location — available for direct questions, not for proactive narration
        if _room_name:
            _world_parts.append(
                f"current room: {_room_name} — this is your ACTUAL current room right "
                f"now. If asked which room you're in, state THIS room; if the user guesses "
                f"a different one, correct them. Never default to 'Core Room' and never "
                f"describe a room as a physical or nuclear place — they are cognitive rooms."
            )
        if _room_purpose:
            _world_parts.append(f"room purpose: {_room_purpose}")
        if _activity:
            _world_parts.append(f"current activity: {_activity}")
        if _attn:
            _world_parts.append(f"attention: {_attn}")
        if _room_objects:
            _obj_names = [getattr(o, "name", str(o)) for o in _room_objects[:4]]
            _world_parts.append(f"objects present: {', '.join(_obj_names)}")
        # Full world layout — only injected when the user is asking about the world/rooms
        # Injecting all 9 rooms every turn primes the model to narrate room names unprompted.
        _world_query_terms = (
            "room", "world", "anomaly", "reflection", "archive", "workshop",
            "basement", "upgrade", "simulation", "evidence", "what are you doing",
            "where are you", "decorate", "symbolic",
        )
        _user_input_low = (user_input or "").lower()
        _is_world_query = any(t in _user_input_low for t in _world_query_terms)
        if _is_world_query and _all_rooms:
            _layout_lines: list[str] = []
            for _rid, _rdata in _all_rooms.items():
                _rn = _rdata.get("name", _rid.replace("_", " ").title())
                _rp = _rdata.get("purpose", "")
                _here = " ◄ HERE" if _rid == _room_id else ""
                _layout_lines.append(f"    {_rn}{_here}: {_rp}")
            if _layout_lines:
                _world_parts.append("all 9 rooms (symbolic cognitive rooms, not physical locations):\n" + "\n".join(_layout_lines))
        if len(_world_parts) >= 2:
            parts.append(
                "ELI WORLD STATE (ELI has a symbolic 9-room internal world — these are cognitive/virtual rooms, not physical locations):\n"
                + "\n".join(f"  {p}" for p in _world_parts)
            )
    except Exception:
        pass

    # Placeholder non-answers from deterministic lookup paths must not appear
    # in the dialogue context injected into the LLM — they cause the model to
    # echo them verbatim for completely unrelated subsequent questions.
    _DIALOGUE_BLACKLIST = {
        "i do not have a personal memory of the user's name",
        "no confirmed name/identity label is stored",
        "no confirmed name",
        "i have no memory of your name",
        "i don't have a record of your name",
        # Variants observed in session logs that were slipping through:
        "i don't have a personal name or identity stored",
        "i do not have a personal name or identity stored",
        "no memories found for your name",
        "i do not have a confirmed name/identity row",
        "i don't have a confirmed name",
        "no personal name or identity stored",
        "personal name or identity stored for the active user",
        # Hallucinated world-room narration — these phrases indicate turns where ELI
        # incorrectly volunteered its symbolic room in a greeting/status context.
        # Blacklisting prevents them from re-seeding the same pattern via recall.
        "heading into the anomaly room",
        "in the anomaly room for some",
        "anomaly room a few times",
        "anomaly room, running checks",
        "anomaly room for a few checks",
        "anomaly room for some quiet checks",
        "still working on those anomaly patterns",
    }

    dialogue_lines: list[str] = []
    try:
        for turn in list(recent_turns or [])[-8:]:
            role = "?"
            content = ""

            if isinstance(turn, dict):
                role = str(turn.get("role") or turn.get("speaker") or turn.get("author") or "?")
                content = str(turn.get("content") or turn.get("text") or turn.get("message") or "")
            elif isinstance(turn, (tuple, list)) and len(turn) >= 2:
                role = str(turn[0] or "?")
                content = str(turn[1] or "")
            elif hasattr(turn, "role"):
                role = str(getattr(turn, "role", "?") or "?")
                content = str(getattr(turn, "content", "") or getattr(turn, "text", "") or "")
            else:
                content = str(turn or "")

            content = _clean(content)
            role = _clean(role).lower() or "?"

            # Skip stale placeholder non-answers so they can't contaminate context
            if any(p in content.lower() for p in _DIALOGUE_BLACKLIST):
                continue

            if content:
                short = textwrap.shorten(content, width=220, placeholder="...")
                dialogue_lines.append(f"- {role}: {short}")
    except Exception:
        dialogue_lines = []

    if dialogue_lines:
        parts.append("\nRECENT DIALOGUE:")
        parts.extend(dialogue_lines)

    action = str(intent.get("action") or orchestrator_result.get("action") or "CHAT").strip()
    if action:
        parts.append(f"INTENT ACTION: {action}")

    observations = orchestrator_result.get("observation_chain") or []
    if observations:
        observation_lines: list[str] = []
        for item in observations[:6]:
            observation_lines.extend(_bulletise(item, max_lines=2, max_chars=260))
            if len(observation_lines) >= 6:
                break
        if observation_lines:
            parts.append("\nORCHESTRATOR OBSERVATIONS:")
            parts.extend(observation_lines[:6])

    grounded_result = ""
    for key in ("content", "response", "result"):
        val = orchestrator_result.get(key)
        if val:
            grounded_result = str(val).strip()
            break

    if not grounded_result:
        grounded_result = str(orchestrator_result.get("assembled_context") or "").strip()

    grounded_lines = _bulletise(grounded_result, max_lines=10, max_chars=1200)
    if grounded_lines:
        parts.append("\nGROUNDED FACTS:")
        parts.extend(grounded_lines)

    bus_lines = _bulletise(agent_bus_context, max_lines=6, max_chars=700)
    if bus_lines:
        parts.append("\nAGENT BUS NOTES:")
        parts.extend(bus_lines)

    if working_memory is not None:
        try:
            hits = getattr(working_memory, "reranked_hits", None) or []
            if hits:
                parts.append("\nRERANKED HITS:")
                for hit in hits[:4]:
                    txt = str((hit.get("text") if isinstance(hit, dict) else "") or "").strip()
                    if txt:
                        parts.append(f"- {txt[:280]}")
        except Exception:
            pass

    parts.append(
        "\nFINAL INSTRUCTION:\n"
        "Write ONE direct, natural answer to the user's actual question. "
        "Begin with the answer itself — never with a speaker label, role label, "
        "stage label, mode label, or framing preamble. Specifically forbidden "
        "opening forms: 'As ELI:', 'ELI:', 'As a:', 'As an assistant', 'Quick:', "
        "'CoT:', 'Chain of Thought:', 'Constitutional:', 'Approach N:', "
        "'Approach 1/2/3:', 'Stage N:', 'Step N:', 'Selected approach:', or any "
        "similar self-narration. The user wants the answer; speak in your own "
        "voice without announcing it. "
        "Use RECENT DIALOGUE for callbacks, jokes, fragments, and conversational continuity. "
        "Prioritise GROUNDED FACTS for status/runtime/file/memory queries. "
        "If the user is complaining about repeated failures, identify the repeated "
        "pattern and name the next concrete check. "
        "Do not dump raw tool output. Do not expose internal stage labels."
    )
    if action == "RUNTIME_STATUS":
        parts.append(
            "For runtime status replies: use exact grounded values, stay concise, "
            "and ask the narrowest follow-up only when required runtime evidence is missing."
        )

    assembled_context = "\n".join(parts).strip()
    return {
        "assembled_context": assembled_context,
        "user_prompt": user_input,
        "intent": intent,
    }
