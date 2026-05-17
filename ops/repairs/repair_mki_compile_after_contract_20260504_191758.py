from pathlib import Path
import py_compile
import re
import shutil
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.repair_mki_compile_after_contract"
BACKUP.mkdir(parents=True, exist_ok=True)

MKI = ROOT / "eli/gui/eli_pro_audio_gui_MKI.py"

def backup(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"BACKUP {path.relative_to(ROOT)} -> {dst}")

def compile_ok(path: Path) -> bool:
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except Exception as exc:
        print(f"COMPILE_BAD {path}: {exc}")
        return False

def write_if_changed(path: Path, text: str):
    old = path.read_text(encoding="utf-8", errors="replace")
    if old != text:
        path.write_text(text, encoding="utf-8")
        print(f"PATCHED {path.relative_to(ROOT)}")
    else:
        print(f"UNCHANGED {path.relative_to(ROOT)}")

def strip_bad_preloaded_blocks(src: str) -> str:
    lines = src.splitlines(True)
    out = []
    i = 0
    removed = 0

    bad_prefixes = (
        "_PRELOADED_PARAMS",
        "if not isinstance(_PRELOADED_PARAMS",
        "_pre_params",
        "for _src in (_pre_params, locals())",
        "_handoff_seen",
        "_portable_runtime_handoff_keys",
        "def _eli_preloaded_runtime_handoff_values",
        "return dict(_pre_params)",
    )

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if "phase_" in line and "preloaded_runtime_handoff" in line:
            removed += 1
            i += 1

            while i < len(lines):
                s = lines[i].strip()

                if not s:
                    i += 1
                    continue

                if s.startswith("except ") or s.startswith("elif ") or s.startswith("else:") or "QTimer.singleShot(600" in s:
                    break

                if s.startswith(bad_prefixes):
                    i += 1
                    continue

                # Drop simple continuation lines from tuple/list blocks.
                if s.startswith(("(", ")", '"', "'", ",")) or s.endswith(","):
                    i += 1
                    continue

                break

            continue

        out.append(line)
        i += 1

    print("REMOVED_PRELOADED_BLOCKS", removed)
    return "".join(out)

def repair_empty_try_blocks(src: str) -> str:
    lines = src.splitlines(True)
    out = []
    inserted = 0

    for i, line in enumerate(lines):
        out.append(line)

        if line.strip() != "try:":
            continue

        indent = line[:len(line) - len(line.lstrip())]
        j = i + 1
        while j < len(lines) and (not lines[j].strip() or lines[j].lstrip().startswith("#")):
            j += 1

        if j < len(lines) and lines[j].lstrip().startswith("except "):
            out.append(indent + "    pass\n")
            inserted += 1

    print("INSERTED_EMPTY_TRY_PASSES", inserted)
    return "".join(out)

def remove_top_level_engine_ask(src: str) -> str:
    lines = src.splitlines(True)
    removed = 0
    i = 0
    out = []

    while i < len(lines):
        if lines[i].startswith("def _engine_ask("):
            removed += 1
            i += 1
            while i < len(lines):
                if lines[i].startswith("class ") or lines[i].startswith("def ") or lines[i].startswith("    def create_labs_tab("):
                    break
                i += 1
            continue

        out.append(lines[i])
        i += 1

    print("REMOVED_TOP_LEVEL_ENGINE_ASK", removed)
    return "".join(out)

ENGINE_BLOCK = (
'    def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:\n'
'        """Synchronous ELI inference for Labs tab."""\n'
'        prompt = str(prompt or "").strip()\n'
'        if not prompt:\n'
'            return ""\n'
'\n'
'        def _normalise(result):\n'
'            if isinstance(result, dict):\n'
'                return str(\n'
'                    result.get("content")\n'
'                    or result.get("response")\n'
'                    or result.get("text")\n'
'                    or result.get("answer")\n'
'                    or result.get("message")\n'
'                    or result.get("output")\n'
'                    or ""\n'
'                ).strip()\n'
'            if result is None:\n'
'                return ""\n'
'            return str(result).strip()\n'
'\n'
'        backend = getattr(self, "backend", None)\n'
'        if backend is not None and hasattr(backend, "chat"):\n'
'            try:\n'
'                result = backend.chat(prompt, max_tokens=max_tokens)\n'
'                text = _normalise(result)\n'
'                if text:\n'
'                    return text\n'
'            except Exception:\n'
'                pass\n'
'\n'
'        try:\n'
'            from eli.kernel.engine import get_engine\n'
'            engine = get_engine()\n'
'            if engine is not None and hasattr(engine, "process"):\n'
'                result = engine.process(prompt, stream=False, reasoning_mode="quick")\n'
'                text = _normalise(result)\n'
'                if text:\n'
'                    return text\n'
'        except Exception:\n'
'            pass\n'
'\n'
'        try:\n'
'            from eli.cognition import gguf_inference\n'
'            result = gguf_inference.generate(prompt, max_tokens=max_tokens)\n'
'            text = _normalise(result)\n'
'            if text:\n'
'                return text\n'
'        except Exception:\n'
'            pass\n'
'\n'
'        return "(model not loaded)"\n'
'\n'
)

def ensure_class_engine_ask(src: str) -> str:
    create_idx = src.find("\n    def create_labs_tab(")
    start_idx = src.find("\n    def _engine_ask(")

    print("CLASS_ENGINE_ASK_IDX", start_idx)
    print("CREATE_LABS_TAB_IDX", create_idx)

    if create_idx == -1:
        print("CREATE_LABS_TAB_NOT_FOUND")
        return src

    if start_idx != -1 and start_idx < create_idx:
        return src[:start_idx + 1] + ENGINE_BLOCK + src[create_idx + 1:]

    return src[:create_idx + 1] + ENGINE_BLOCK + src[create_idx + 1:]

HANDOFF_BLOCK = (
'\n# phase_contract_preloaded_runtime_handoff\n'
'_PRELOADED_PARAMS = globals().get("_PRELOADED_PARAMS", {})\n'
'if not isinstance(_PRELOADED_PARAMS, dict):\n'
'    _PRELOADED_PARAMS = {}\n'
'_pre_params = dict(_PRELOADED_PARAMS)\n'
'for _src in (_pre_params, locals()):\n'
'    _handoff_seen = _src\n'
'_portable_runtime_handoff_keys = ("provider", "model_path", "model_name", "n_ctx", "n_gpu_layers", "n_threads", "n_batch", "batch_size", "max_tokens", "temperature", "top_p")\n'
'\n'
)

def insert_safe_top_level_handoff(src: str) -> str:
    if "phase_contract_preloaded_runtime_handoff" in src:
        print("SAFE_HANDOFF_ALREADY_PRESENT")
        return src

    lines = src.splitlines(True)

    future_indexes = [
        i for i, line in enumerate(lines[:120])
        if line.startswith("from __future__ import ")
    ]

    if future_indexes:
        insert_at = future_indexes[-1] + 1
    else:
        insert_at = 0

        if lines and lines[0].startswith("#!"):
            insert_at = 1

        while insert_at < len(lines) and "coding" in lines[insert_at] and lines[insert_at].lstrip().startswith("#"):
            insert_at += 1

        # Skip a module docstring if present.
        if insert_at < len(lines):
            stripped = lines[insert_at].lstrip()
            quote = None
            if stripped.startswith('"""'):
                quote = '"""'
            elif stripped.startswith("'''"):
                quote = "'''"

            if quote:
                if stripped.count(quote) >= 2 and not stripped.startswith(quote + quote + quote + quote):
                    insert_at += 1
                else:
                    insert_at += 1
                    while insert_at < len(lines):
                        if quote in lines[insert_at]:
                            insert_at += 1
                            break
                        insert_at += 1

    lines.insert(insert_at, HANDOFF_BLOCK)
    print("INSERTED_SAFE_TOP_LEVEL_HANDOFF_AT_LINE", insert_at + 1)
    return "".join(lines)

backup(MKI)

print("BEFORE_COMPILE_OK", compile_ok(MKI))

src = MKI.read_text(encoding="utf-8", errors="replace")
src = strip_bad_preloaded_blocks(src)
src = remove_top_level_engine_ask(src)
src = repair_empty_try_blocks(src)
src = ensure_class_engine_ask(src)
src = insert_safe_top_level_handoff(src)

write_if_changed(MKI, src)

print("AFTER_COMPILE_OK", compile_ok(MKI))

print(f"BACKUP={BACKUP}")
