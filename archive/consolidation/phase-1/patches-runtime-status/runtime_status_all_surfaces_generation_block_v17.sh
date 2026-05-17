#!/usr/bin/env bash
set -euo pipefail

cd "${ELI_PROJECT_ROOT:-$HOME/Desktop/ELI_MKXI}"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_ALL_SURFACES_GENERATION_BLOCK_V17"
if marker in src:
    print("[SKIP] runtime-status all-surfaces generation block v17 already installed")
    raise SystemExit(0)

append = r'''

# ---------------------------------------------------------------------------
# ELI_RUNTIME_STATUS_ALL_SURFACES_GENERATION_BLOCK_V17
# Normalize every RUNTIME_STATUS visible surface, including older fallback
# surfaces such as V10, so generation settings cannot disappear.
# Dynamic: reads live runtime snapshot/settings; does not hard-code values.
# ---------------------------------------------------------------------------

try:
    ELI_RUNTIME_STATUS_ALL_SURFACES_GENERATION_BLOCK_V17_PREV_PROCESS = CognitiveEngine.process

    def _eli_v17_project_root():
        from pathlib import Path
        return Path(__file__).resolve().parents[2]

    def _eli_v17_load_json(path):
        try:
            import json
            from pathlib import Path
            path = Path(path)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    def _eli_v17_first_present(*values, default="unknown"):
        for value in values:
            if value is not None and value != "":
                return value
        return default

    def _eli_v17_runtime_and_settings():
        root = _eli_v17_project_root()
        settings = _eli_v17_load_json(root / "config" / "settings.json")
        snap = _eli_v17_load_json(root / "artifacts" / "runtime_snapshot.json")

        runtime = {}
        if isinstance(snap, dict):
            if isinstance(snap.get("runtime"), dict):
                runtime = snap.get("runtime") or {}
            else:
                runtime = snap

        if not isinstance(settings, dict):
            settings = {}
        if not isinstance(runtime, dict):
            runtime = {}

        return runtime, settings

    def _eli_v17_generation_values():
        runtime, settings = _eli_v17_runtime_and_settings()

        return {
            "max_tokens": _eli_v17_first_present(
                runtime.get("max_tokens"),
                runtime.get("n_predict"),
                settings.get("max_tokens"),
            ),
            "temperature": _eli_v17_first_present(
                runtime.get("temperature"),
                settings.get("temperature"),
            ),
            "use_mmap": _eli_v17_first_present(
                runtime.get("use_mmap"),
                settings.get("use_mmap"),
            ),
            "use_mlock": _eli_v17_first_present(
                runtime.get("use_mlock"),
                settings.get("use_mlock"),
            ),
        }

    def _eli_v17_generation_block():
        vals = _eli_v17_generation_values()
        return (
            "Generation settings:\n"
            f"- max_tokens: {vals['max_tokens']}\n"
            f"- temperature: {vals['temperature']}\n"
            f"- use_mmap: {vals['use_mmap']}\n"
            f"- use_mlock: {vals['use_mlock']}\n"
        )

    def _eli_v17_normalize_generation_block(text):
        if not isinstance(text, str) or not text.strip():
            return text

        if "Runtime status" not in text:
            return text

        vals = _eli_v17_generation_values()

        replacements = {
            "- max_tokens: unknown": f"- max_tokens: {vals['max_tokens']}",
            "- temperature: unknown": f"- temperature: {vals['temperature']}",
            "- use_mmap: unknown": f"- use_mmap: {vals['use_mmap']}",
            "- use_mlock: unknown": f"- use_mlock: {vals['use_mlock']}",
        }

        out = text
        for old, new in replacements.items():
            out = out.replace(old, new)

        required_lines = [
            "- max_tokens:",
            "- temperature:",
            "- use_mmap:",
            "- use_mlock:",
        ]

        has_generation_header = "Generation settings:" in out
        has_all_generation_lines = all(line in out for line in required_lines)

        if has_generation_header and has_all_generation_lines:
            return out

        block = _eli_v17_generation_block().rstrip()

        if "\nValidation note:" in out:
            out = out.replace("\nValidation note:", "\n\n" + block + "\n\nValidation note:", 1)
        else:
            out = out.rstrip() + "\n\n" + block + "\n"

        return out

    def _eli_runtime_status_all_surfaces_generation_block_v17_process(self, *args, **kwargs):
        result = ELI_RUNTIME_STATUS_ALL_SURFACES_GENERATION_BLOCK_V17_PREV_PROCESS(self, *args, **kwargs)

        try:
            if isinstance(result, dict) and result.get("action") == "RUNTIME_STATUS":
                content = result.get("content") or result.get("response") or ""
                fixed = _eli_v17_normalize_generation_block(content)

                if fixed != content:
                    result = dict(result)
                    result["content"] = fixed
                    result["response"] = fixed

                    prev_reason = result.get("repair_reason")
                    v17_reason = "generation_settings_block_completed_from_live_config_v17"
                    result["repair_reason"] = (
                        f"{prev_reason};{v17_reason}" if prev_reason else v17_reason
                    )

                    src = result.get("evidence_source") or result.get("source")
                    if src and "v17" not in str(src):
                        result["evidence_source"] = f"{src}_generation_block_v17"
        except Exception:
            return result

        return result

    CognitiveEngine.process = _eli_runtime_status_all_surfaces_generation_block_v17_process
    print("[ENGINE] runtime-status all-surfaces generation block v17 installed")

except Exception as e:
    print(f"[ENGINE] runtime-status all-surfaces generation block v17 install failed: {e}")
'''

p.write_text(src.rstrip() + "\n" + append + "\n", encoding="utf-8")
print("[OK] installed runtime-status all-surfaces generation block v17")
PY

python3 -m py_compile eli/kernel/engine.py
