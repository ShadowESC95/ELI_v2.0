from pathlib import Path
import py_compile
import re
import shutil
import time
import traceback

ROOT = Path.cwd()
REL = "eli/gui/eli_pro_audio_gui_MKI.py"
MKI = ROOT / REL
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.fix_mki_engine_ask_indent"
BACKUP.mkdir(parents=True, exist_ok=True)

METHOD = '''    def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:
        """Synchronous ELI inference adapter for Labs generation."""
        prompt = str(prompt or "").strip()
        if not prompt:
            return ""

        def _normalise_engine_text(result):
            if isinstance(result, dict):
                response = result.get("response")
                if response is not None and str(response).strip():
                    return str(response).strip()
                for key in ("content", "text", "answer", "message", "output"):
                    value = result.get(key)
                    if value is not None and str(value).strip():
                        return str(value).strip()
                return str(result).strip()
            if result is not None and str(result).strip():
                return str(result).strip()
            return ""

        try:
            from eli.kernel.engine import get_engine
            engine = get_engine()
            if engine is not None and hasattr(engine, "process"):
                result = engine.process(prompt, stream=False, reasoning_mode="quick")
                text = _normalise_engine_text(result)
                if text:
                    return text
        except Exception:
            pass

        backend = getattr(self, "active_backend", None)
        try:
            if backend is not None and hasattr(backend, "chat"):
                result = backend.chat(prompt, max_tokens=max_tokens)
                text = _normalise_engine_text(result)
                if text:
                    return text
        except Exception:
            pass

        try:
            from eli.cognition import gguf_inference
            result = gguf_inference.generate(prompt, max_tokens=max_tokens)
            text = _normalise_engine_text(result)
            if text:
                return text
        except Exception:
            pass

        return ""

'''

def backup_file() -> None:
    dst = BACKUP / REL
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MKI, dst)
    print(f"BACKUP {REL} -> {dst}")

def compile_file() -> int:
    try:
        py_compile.compile(str(MKI), doraise=True)
        print(f"COMPILE_OK {REL}")
        return 0
    except Exception as exc:
        print(f"COMPILE_BAD {REL}: {exc}")
        return 1

def main() -> int:
    backup_file()

    src = MKI.read_text(encoding="utf-8", errors="replace")

    create_matches = list(re.finditer(r'(?m)^    def create_labs_tab\(', src))
    if not create_matches:
        print("ERROR: could not find class-level create_labs_tab marker")
        return 1

    create_start = create_matches[0].start()
    prefix = src[:create_start]
    suffix = src[create_start:]

    ask_matches = list(re.finditer(r'(?m)^[ \t]*def _engine_ask\(', prefix))
    if ask_matches:
        ask_start = ask_matches[-1].start()
        print(f"FOUND_EXISTING_ENGINE_ASK_AT_CHAR={ask_start}")
        prefix = prefix[:ask_start].rstrip() + "\n\n"
    else:
        print("NO_EXISTING_ENGINE_ASK_BEFORE_CREATE_LABS_TAB; INSERTING")

    new_src = prefix + METHOD + suffix
    MKI.write_text(new_src, encoding="utf-8")
    print("PATCHED eli/gui/eli_pro_audio_gui_MKI.py")

    check = MKI.read_text(encoding="utf-8", errors="replace")
    print("HAS_CLASS_ENGINE_ASK", "    def _engine_ask(" in check)
    print("HAS_TOP_LEVEL_ENGINE_ASK", "\ndef _engine_ask(" in check)
    print("ENGINE_BEFORE_CREATE", check.index("    def _engine_ask(") < check.index("    def create_labs_tab("))

    start_line = check[:check.index("    def _engine_ask(")].count("\n") + 1
    print(f"ENGINE_ASK_LINE={start_line}")
    lines = check.splitlines()
    for i in range(max(1, start_line - 3), min(len(lines), start_line + 55) + 1):
        print(f"{i:5d}: {lines[i-1]}")

    return compile_file()

try:
    INTERNAL_RC = main()
except Exception:
    traceback.print_exc()
    INTERNAL_RC = 1

print(f"BACKUP={BACKUP}")
print(f"INTERNAL_RC={INTERNAL_RC}")
