#!/usr/bin/env bash
set -euo pipefail

cd "${ELI_PROJECT_ROOT:-$HOME/Desktop/ELI_MKXI}"

python3 - <<'PY'
from pathlib import Path

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")

marker = "ELI_RUNTIME_STATUS_QUICK_GENERATION_SETTINGS_V16"
if marker in src:
    print("[SKIP] runtime-status quick generation settings v16 already installed")
    raise SystemExit(0)

append = r'''

# ---------------------------------------------------------------------------
# ELI_RUNTIME_STATUS_QUICK_GENERATION_SETTINGS_V16
# Fill Quick-mode runtime-status generation fields from live runtime/settings.
# This does NOT hard-code runtime answers. It only replaces "unknown" fields
# using artifacts/runtime_snapshot.json and config/settings.json.
# ---------------------------------------------------------------------------

try:
    ELI_RUNTIME_STATUS_QUICK_GENERATION_SETTINGS_V16_PREV_PROCESS = CognitiveEngine.process

    def _eli_v16_project_root():
        from pathlib import Path
        return Path(__file__).resolve().parents[2]

    def _eli_v16_load_json(path):
        try:
            import json
            from pathlib import Path
            path = Path(path)
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    def _eli_v16_first_present(*values, default="unknown"):
        for value in values:
            if value is not None and value != "":
                return value
        return default

    def _eli_v16_live_generation_settings():
        root = _eli_v16_project_root()

        settings = _eli_v16_load_json(root / "config" / "settings.json")
        snap = _eli_v16_load_json(root / "artifacts" / "runtime_snapshot.json")

        runtime = snap.get("runtime") if isinstance(snap, dict) and isinstance(snap.get("runtime"), dict) else snap
        if not isinstance(runtime, dict):
            runtime = {}

        max_tokens = _eli_v16_first_present(
            runtime.get("max_tokens"),
            runtime.get("n_predict"),
            settings.get("max_tokens"),
        )

        temperature = _eli_v16_first_present(
            runtime.get("temperature"),
            settings.get("temperature"),
        )

        use_mmap = _eli_v16_first_present(
            runtime.get("use_mmap"),
            settings.get("use_mmap"),
        )

        use_mlock = _eli_v16_first_present(
            runtime.get("use_mlock"),
            settings.get("use_mlock"),
        )

        return {
            "max_tokens": max_tokens,
            "temperature": temperature,
            "use_mmap": use_mmap,
            "use_mlock": use_mlock,
        }

    def _eli_v16_fill_quick_generation_unknowns(text):
        if not isinstance(text, str):
            return text

        if "Runtime status evidence:" not in text and "Runtime status," not in text:
            return text

        if not any(x in text for x in (
            "- max_tokens: unknown",
            "- temperature: unknown",
            "- use_mmap: unknown",
            "- use_mlock: unknown",
        )):
            return text

        vals = _eli_v16_live_generation_settings()

        text = text.replace("- max_tokens: unknown", f"- max_tokens: {vals['max_tokens']}")
        text = text.replace("- temperature: unknown", f"- temperature: {vals['temperature']}")
        text = text.replace("- use_mmap: unknown", f"- use_mmap: {vals['use_mmap']}")
        text = text.replace("- use_mlock: unknown", f"- use_mlock: {vals['use_mlock']}")

        return text

    def _eli_runtime_status_quick_generation_settings_v16_process(self, *args, **kwargs):
        result = ELI_RUNTIME_STATUS_QUICK_GENERATION_SETTINGS_V16_PREV_PROCESS(self, *args, **kwargs)

        try:
            if isinstance(result, dict) and result.get("action") == "RUNTIME_STATUS":
                content = result.get("content") or result.get("response") or ""
                fixed = _eli_v16_fill_quick_generation_unknowns(content)

                if fixed != content:
                    result = dict(result)
                    result["content"] = fixed
                    result["response"] = fixed
                    result["repair_reason"] = "quick_generation_settings_completed_from_live_config_v16"
        except Exception:
            return result

        return result

    CognitiveEngine.process = _eli_runtime_status_quick_generation_settings_v16_process
    print("[ENGINE] runtime-status quick generation settings v16 installed")

except Exception as e:
    print(f"[ENGINE] runtime-status quick generation settings v16 install failed: {e}")
'''

p.write_text(src.rstrip() + "\n" + append + "\n", encoding="utf-8")
print("[OK] installed runtime-status quick generation settings v16")
PY

python3 -m py_compile eli/kernel/engine.py
