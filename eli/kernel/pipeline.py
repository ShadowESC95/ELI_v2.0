import inspect
import sys
from pathlib import Path
from typing import List, Dict, Any

# ------------------------------------------------------------
# Step definitions with actual source locations
# ------------------------------------------------------------

# Fallback paths use the live `eli/` layout so evidence sent to the model
# cannot cite stale source locations.
STEPS = [
    {
        "name": "1. PERCEIVE + INGEST",
        "desc": "Capture input, attach metadata, normalize text.",
        "module": None,
        "function": None,
        "fallback_path": "eli/gui/eli_pro_audio_gui_MKI.py, eli/perception/audio_stt.py"
    },
    {
        "name": "2. INPUT NORMALIZATION + GUARDS",
        "desc": "Long‑question guard, command guard, wake‑word gating.",
        "module": None,
        "function": None,
        "fallback_path": "eli/kernel/engine.py (input_guards)"
    },
    {
        "name": "3. ROUTER + TASK DECOMPOSER",
        "desc": "Parse intent, return action, args, confidence, meta.",
        "module": "eli.execution.router_enhanced",
        "function": "route",
        "fallback_path": "eli/execution/router_enhanced.py"
    },
    {
        "name": "4. TRUTH / GROUNDING GATE",
        "desc": "Forbid direct LLM answer if grounding required.",
        "module": "eli.kernel.engine",
        "function": "_intent_requires_grounding",
        "fallback_path": "eli/kernel/engine.py"
    },
    {
        "name": "5. EXECUTIVE CONTROLLER / PLANNER",
        "desc": "Build plan: which agents to call, order, requirements.",
        "module": "eli.kernel.engine",
        "function": "_build_runtime_orchestrator_plan",
        "fallback_path": "eli/kernel/engine.py"
    },
    {
        "name": "6. AGENT BUS (parallel specialist agents)",
        "desc": "Memory, System, Habit, Self‑Improvement, Proactive, Frontier, Plugin, Capability, Voice, Orchestrator, File/Code, Introspection, Reflection, KnowledgeGraph agents — run concurrently via a ThreadPoolExecutor sized to the live agent count (read your runtime for the exact number).",
        "module": "eli.cognition.agent_bus",
        "function": None,
        "fallback_path": "eli/cognition/agent_bus.py"
    },
    {
        "name": "7. WORKING MEMORY / CONTEXT ASSEMBLER",
        "desc": "Combine evidence from agents into structured packet.",
        "module": "eli.kernel.engine",
        "function": "assemble_precise_context",
        "fallback_path": "eli/kernel/engine.py"
    },
    {
        "name": "8. SINGLE INFERENCE BROKER",
        "desc": "Serialises all LLM calls — local GGUF only (model-agnostic; no cloud, no Ollama on the default path).",
        "module": "eli.cognition.inference_broker",
        "function": None,
        "fallback_path": "eli/cognition/inference_broker.py"
    },
    {
        "name": "9. REASONING / SYNTHESIS LAYER",
        "desc": "Pure chat, grounded query, or hybrid synthesis.",
        "module": "eli.kernel.engine",
        "function": "_run_chat_reasoning_loop",
        "fallback_path": "eli/kernel/engine.py"
    },
    {
        "name": "10. OUTPUT GOVERNOR",
        "desc": "Enforce answer shape, evidence summary, confidence.",
        "module": "eli.cognition.output_governor",
        "function": None,
        "fallback_path": "eli/cognition/output_governor.py"
    },
    {
        "name": "11. RESPONSE DELIVERY",
        "desc": "GUI / TTS / voice / executor feedback.",
        "module": None,
        "function": None,
        "fallback_path": "eli/gui/eli_pro_audio_gui_MKI.py, eli/perception/tts_router.py"
    },
    {
        "name": "12. LEARNING + STATE UPDATE",
        "desc": "Store turns, memories, habits, failures, self‑model.",
        "module": "eli.memory.memory",
        "function": None,
        "fallback_path": "eli/memory/memory.py"
    }
]

def _get_source_location(module_name: str, func_name: str = None) -> str:
    """Return file path and optional line number for a function/module."""
    try:
        if func_name:
            # Get the function object
            mod = __import__(module_name, fromlist=[func_name])
            func = getattr(mod, func_name, None)
            # Many engine "functions" are actually CognitiveEngine METHODS, invisible to a
            # module-level getattr — resolve them on the class so the stage reports a real
            # line (else it falls back to a path with no line, implying false vagueness).
            if not callable(func):
                for _cls_name in ("CognitiveEngine",):
                    _cls = getattr(mod, _cls_name, None)
                    if _cls is not None and callable(getattr(_cls, func_name, None)):
                        func = getattr(_cls, func_name)
                        break
            if not callable(func):
                raise AttributeError(func_name)
            file_path = inspect.getfile(func)
            line_no = inspect.getsourcelines(func)[1]
            return f"{file_path} (line {line_no})"
        else:
            # Module only
            import importlib
            spec = importlib.import_module(module_name)
            file_path = inspect.getfile(spec)
            return file_path
    except Exception:
        # Fallback to static path
        for step in STEPS:
            if step['module'] == module_name:
                return step.get('fallback_path', 'unknown')
        return 'unknown'

def get_pipeline_description() -> List[str]:
    """Return a list of lines describing the full cognition pipeline."""
    lines = []
    for step in STEPS:
        name = step['name']
        desc = step['desc']
        location = "unknown"
        if step['module']:
            location = _get_source_location(step['module'], step.get('function'))
        else:
            location = step['fallback_path']
        lines.append(f"- **{name}** : {desc}\n  *Implementation:* {location}")
    return lines
