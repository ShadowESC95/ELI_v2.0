#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

STAMP="$(date +%Y%m%d_%H%M%S)"
TARGET="eli/kernel/engine.py"
BACKUP="${TARGET}.bak_runtime_status_nonquick_full_pipeline_${STAMP}"

cp "$TARGET" "$BACKUP"

python3 - <<'PY'
from pathlib import Path

target = Path("eli/kernel/engine.py")
src = target.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_SYNTHESIS_V1"
if marker in src:
    print("[PATCH] marker already present; no duplicate install")
else:
    block = r'''

# =============================================================================
# ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_SYNTHESIS_V1
#
# Contract:
#   - Quick mode may return deterministic live runtime telemetry directly.
#   - Non-Quick modes must NOT return raw/direct telemetry packets.
#   - Non-Quick modes gather live telemetry as evidence, synthesize via local GGUF,
#     validate the synthesized answer, then return only the synthesized surface.
#
# This repairs the earlier overcorrection where runtime-status telemetry bypassed
# Constitutional/CoT/Self-C/ToT synthesis under the phrase:
#   "raw GGUF candidate generation skipped"
# =============================================================================
try:
    _ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_PREV_PROCESS = CognitiveEngine.process

    def _eli_rs_v19_text_from_args(_args, _kwargs):
        for key in ("user_input", "message", "text", "prompt"):
            val = _kwargs.get(key)
            if val is not None:
                return str(val)
        if _args:
            return str(_args[0])
        return ""

    def _eli_rs_v19_mode_from_args(_args, _kwargs):
        mode = _kwargs.get("reasoning_mode")
        if mode is None and len(_args) >= 4:
            mode = _args[3]
        try:
            from eli.cognition.reasoning_modes import canonical_mode as _cm
            return _cm(mode)
        except Exception:
            return str(mode or "quick").strip().lower() or "quick"

    def _eli_rs_v19_is_quick(mode):
        return str(mode or "").strip().lower() in {"quick", "fast", "direct"}

    def _eli_rs_v19_is_runtime_status_question(text):
        raw = str(text or "").strip()
        low = raw.lower()
        if not low:
            return False

        # Prefer the real router contract where possible.
        try:
            routed = route_intent(raw)
            if isinstance(routed, dict):
                return str(routed.get("action") or "").strip().upper() == "RUNTIME_STATUS"
        except Exception:
            pass

        # Conservative fallback.
        import re as _re
        return bool(
            _re.search(r"\b(who are you|what are you actually running on|runtime status|model|context size|gpu layers|gpu|ctx)\b", low)
            and _re.search(r"\b(running|runtime|model|context|ctx|gpu|layers|provider|everything)\b", low)
        )

    def _eli_rs_v19_extract_text(out):
        if isinstance(out, dict):
            return str(
                out.get("content")
                or out.get("response")
                or out.get("message")
                or ""
            ).strip()
        return str(out or "").strip()

    def _eli_rs_v19_call_runtime_status(question):
        try:
            from eli.execution.executor_enhanced import execute as _exec
            out = _exec("RUNTIME_STATUS", {"question": str(question or ""), "detail": "full"})
            if not isinstance(out, dict):
                txt = str(out or "").strip()
                out = {
                    "ok": bool(txt),
                    "action": "RUNTIME_STATUS",
                    "content": txt,
                    "response": txt,
                    "source": "runtime_status_executor_text",
                    "evidence_source": "runtime_status_live_runtime_telemetry",
                }
            return dict(out)
        except Exception as e:
            return {
                "ok": False,
                "action": "RUNTIME_STATUS",
                "content": "",
                "response": "",
                "error": repr(e),
                "source": "runtime_status_nonquick_full_pipeline_v1_evidence_error",
                "evidence_source": "runtime_status_live_runtime_telemetry_failed",
            }

    def _eli_rs_v19_generate(prompt, system, mode):
        """
        Use local GGUF generation directly for the synthesis step.
        This is not a raw telemetry return. It is evidence-conditioned synthesis.
        """
        try:
            from eli.cognition import gguf_inference as _gguf

            # Preferred public/compat surfaces.
            candidates = [
                "chat_completion",
                "complete",
                "generate_text",
                "_chat_completion_impl",
            ]

            last_err = None
            for name in candidates:
                fn = getattr(_gguf, name, None)
                if not callable(fn):
                    continue
                try:
                    txt = fn(
                        prompt=prompt,
                        system=system,
                        max_tokens=900,
                        temperature=0.35 if mode == "constitutional_ai" else 0.45,
                        top_p=0.9,
                    )
                    if isinstance(txt, dict):
                        txt = txt.get("response") or txt.get("content") or txt.get("text") or ""
                    txt = str(txt or "").strip()
                    if txt:
                        return txt
                except Exception as e:
                    last_err = e

            # Generator-style fallback used by gguf_inference in older builds.
            gen_fn = getattr(_gguf, "_generate_impl", None)
            if callable(gen_fn):
                chunks = []
                try:
                    result = gen_fn(
                        prompt=prompt,
                        system=system,
                        stream=False,
                        max_tokens=900,
                        temperature=0.35 if mode == "constitutional_ai" else 0.45,
                        top_p=0.9,
                    )
                    for chunk in result:
                        if isinstance(chunk, dict):
                            chunks.append(str(chunk.get("response") or chunk.get("content") or ""))
                        else:
                            chunks.append(str(chunk or ""))
                    txt = "".join(chunks).strip()
                    if txt:
                        return txt
                except Exception as e:
                    last_err = e

            raise RuntimeError(f"No usable GGUF synthesis surface produced text; last_err={last_err!r}")
        except Exception as e:
            raise RuntimeError(f"runtime-status non-Quick synthesis failed: {e}") from e

    def _eli_rs_v19_bad_synthesis(text):
        low = str(text or "").lower()
        if not low.strip():
            return "empty synthesis"
        forbidden = [
            "raw gguf candidate",
            "raw_gguf_candidates_skipped",
            "repair_reason",
            "response_surface:",
            "synthesis_validated",
            "evidence_source:",
            "{'ok':",
            '"ok":',
            "canonical live grounded telemetry",
        ]
        for frag in forbidden:
            if frag in low:
                return f"leaked internal/direct telemetry marker: {frag}"
        required_any = [
            "model",
            "context",
            "gpu",
            "provider",
            "runtime",
        ]
        if sum(1 for x in required_any if x in low) < 3:
            return "synthesis did not preserve enough runtime facts"
        return ""

    def _eli_rs_v19_synthesize_runtime_status(original_question, mode, evidence):
        evidence_text = _eli_rs_v19_extract_text(evidence)
        if not evidence_text:
            err = evidence.get("error") if isinstance(evidence, dict) else ""
            return {
                "ok": False,
                "action": "RUNTIME_STATUS",
                "content": f"Runtime-status evidence collection failed, so non-Quick synthesis was not attempted. Error: {err}",
                "response": f"Runtime-status evidence collection failed, so non-Quick synthesis was not attempted. Error: {err}",
                "source": "runtime_status_nonquick_full_pipeline_v1_fail_closed",
                "evidence_source": "runtime_status_live_runtime_telemetry_failed",
                "grounded": False,
                "evidence_used": False,
                "report": {
                    "requested_mode": mode,
                    "synthesis_validated": False,
                    "direct_telemetry_returned": False,
                    "quick_direct_allowed": False,
                    "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
                },
            }

        mode_instruction = {
            "chain_of_thought": "Use private structured reasoning. Do not reveal hidden reasoning. Output only the final answer.",
            "self_consistency": "Privately compare several possible phrasings and output only the strongest final answer.",
            "tree_of_thoughts": "Privately explore branches, prune weak ones, and output only the strongest final answer.",
            "constitutional_ai": "Draft, privately critique for accuracy and contract compliance, revise, and output only the final answer.",
        }.get(str(mode), "Use the normal non-Quick synthesis path. Output only the final answer.")

        system = (
            "You are ELI, the local assistant inside the ELI MKXI project. "
            "You are answering from live runtime telemetry evidence. "
            "Do not invent runtime facts. "
            "Do not expose JSON packets, internal report fields, repair reasons, raw candidate metadata, or validation machinery. "
            "Do not say telemetry was skipped. "
            "Return a concise but complete synthesized answer."
        )

        prompt = f"""Original user question:
{original_question}

Reasoning mode:
{mode}

Mode contract:
{mode_instruction}

Live runtime telemetry evidence:
{evidence_text}

Task:
Answer the user as ELI. Include identity, model/provider, model path/name, context size, GPU layers, batch size, CPU threads, GPU info if present, project paths if present, and generation settings if present.
This must be a synthesized final answer, not a raw telemetry dump.
"""

        try:
            synthesized = _eli_rs_v19_generate(prompt, system, mode).strip()
        except Exception as e:
            return {
                "ok": False,
                "action": "RUNTIME_STATUS",
                "content": f"Runtime-status evidence was collected, but non-Quick synthesis failed validation/execution: {e}",
                "response": f"Runtime-status evidence was collected, but non-Quick synthesis failed validation/execution: {e}",
                "source": "runtime_status_nonquick_full_pipeline_v1_synthesis_failed",
                "evidence_source": "runtime_status_live_runtime_telemetry",
                "grounded": True,
                "evidence_used": True,
                "report": {
                    "requested_mode": mode,
                    "synthesis_validated": False,
                    "direct_telemetry_returned": False,
                    "quick_direct_allowed": False,
                    "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
                    "error": repr(e),
                },
            }

        bad = _eli_rs_v19_bad_synthesis(synthesized)
        if bad:
            return {
                "ok": False,
                "action": "RUNTIME_STATUS",
                "content": f"Runtime-status non-Quick synthesis failed validation: {bad}. Direct telemetry was not returned because only Quick mode may use that surface.",
                "response": f"Runtime-status non-Quick synthesis failed validation: {bad}. Direct telemetry was not returned because only Quick mode may use that surface.",
                "source": "runtime_status_nonquick_full_pipeline_v1_validation_failed",
                "evidence_source": "runtime_status_live_runtime_telemetry",
                "grounded": True,
                "evidence_used": True,
                "report": {
                    "requested_mode": mode,
                    "synthesis_validated": False,
                    "direct_telemetry_returned": False,
                    "quick_direct_allowed": False,
                    "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
                    "validation_error": bad,
                },
            }

        return {
            "ok": True,
            "action": "RUNTIME_STATUS",
            "content": synthesized,
            "response": synthesized,
            "source": "runtime_status_nonquick_full_pipeline_synthesized_v1",
            "evidence_source": "runtime_status_live_runtime_telemetry",
            "grounded": True,
            "evidence_used": True,
            "report": {
                "requested_mode": mode,
                "synthesis_validated": True,
                "direct_telemetry_returned": False,
                "quick_direct_allowed": False,
                "repair_reason": "runtime_status_nonquick_full_pipeline_v1",
            },
        }

    def process(self, *args, _prev=_ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_PREV_PROCESS, **kwargs):
        user_text = _eli_rs_v19_text_from_args(args, kwargs)
        mode = _eli_rs_v19_mode_from_args(args, kwargs)

        if _eli_rs_v19_is_runtime_status_question(user_text):
            if _eli_rs_v19_is_quick(mode):
                return _prev(self, *args, **kwargs)

            evidence = _eli_rs_v19_call_runtime_status(user_text)
            result = _eli_rs_v19_synthesize_runtime_status(user_text, mode, evidence)
            print("[ENGINE] RUNTIME_STATUS non-Quick full-pipeline synthesis contract returned", flush=True)
            return result

        return _prev(self, *args, **kwargs)

    CognitiveEngine.process = process
    print("[ENGINE] runtime-status non-Quick full-pipeline synthesis contract installed", flush=True)

except Exception as _eli_runtime_status_nonquick_full_pipeline_err:
    print(f"[ENGINE] runtime-status non-Quick full-pipeline synthesis contract failed: {_eli_runtime_status_nonquick_full_pipeline_err}", flush=True)
# =============================================================================
'''
    target.write_text(src.rstrip() + "\n" + block + "\n", encoding="utf-8")
    print("[PATCH] installed ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_SYNTHESIS_V1")

PY

echo
echo "=== compile ==="
python3 -m py_compile eli/kernel/engine.py

echo
echo "=== marker ==="
grep -n "ELI_RUNTIME_STATUS_NONQUICK_FULL_PIPELINE_SYNTHESIS_V1" eli/kernel/engine.py

echo
echo "=== focused diff ==="
git diff -- eli/kernel/engine.py | sed -n '1,260p'
