from pathlib import Path
import py_compile
import re
import shutil
import subprocess
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.surgical_mki_compile_contract_fix"
BACKUP.mkdir(parents=True, exist_ok=True)

MKI = ROOT / "eli/gui/eli_pro_audio_gui_MKI.py"
REL = "eli/gui/eli_pro_audio_gui_MKI.py"

def backup(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"BACKUP {path.relative_to(ROOT)} -> {dst}")

def compile_report(path: Path):
    try:
        py_compile.compile(str(path), doraise=True)
        return True, None
    except py_compile.PyCompileError as exc:
        err = exc.exc_value
        print(f"COMPILE_BAD file={getattr(err, 'filename', path)} line={getattr(err, 'lineno', None)} msg={err}")
        return False, err
    except Exception as exc:
        print(f"COMPILE_BAD_UNKNOWN {type(exc).__name__}: {exc}")
        return False, exc

def get_git_head_text():
    proc = subprocess.run(
        ["git", "show", f"HEAD:{REL}"],
        cwd=str(ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    print(f"GIT_SHOW_RC={proc.returncode}")
    if proc.returncode != 0:
        print(proc.stderr.strip())
        return None
    return proc.stdout

def line_context(src: str, line_no: int, radius: int = 18):
    lines = src.splitlines()
    lo = max(1, line_no - radius)
    hi = min(len(lines), line_no + radius)
    for n in range(lo, hi + 1):
        print(f"{n:5d}: {lines[n-1]}")

def find_candidate_defs_backwards(src: str, line_no: int):
    lines = src.splitlines(keepends=True)
    candidates = []
    for i in range(min(line_no - 1, len(lines) - 1), -1, -1):
        m = re.match(r"^(\s*)def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", lines[i])
        if m:
            candidates.append((i, len(m.group(1)), m.group(2)))
    return candidates

def find_def_span_by_name(src: str, name: str, indent: int):
    lines = src.splitlines(keepends=True)
    pat = re.compile(rf"^{{0,{indent}}}def\s+{re.escape(name)}\s*\(")
    exact_pat = re.compile(rf"^ {' ' * max(indent-1, 0)}$")  # intentionally unused; keeps no lint concern

    starts = []
    for i, line in enumerate(lines):
        m = re.match(r"^(\s*)def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
        if m and m.group(2) == name:
            starts.append((i, len(m.group(1))))

    # Prefer same indentation.
    ordered = sorted(starts, key=lambda x: 0 if x[1] == indent else 1)
    for start, real_indent in ordered:
        end = len(lines)
        for j in range(start + 1, len(lines)):
            m = re.match(r"^(\s*)(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\b", lines[j])
            if m and len(m.group(1)) <= real_indent:
                end = j
                break
        return start, end
    return None

def replace_span_lines(src: str, start: int, end: int, replacement_lines):
    lines = src.splitlines(keepends=True)
    return "".join(lines[:start] + replacement_lines + lines[end:])

def transplant_enclosing_function_from_head(current: str, donor: str, error_line: int):
    current_lines = current.splitlines(keepends=True)
    donor_lines = donor.splitlines(keepends=True)

    print(f"ERROR_CONTEXT_AROUND_LINE={error_line}")
    line_context(current, error_line)

    for cur_start, cur_indent, name in find_candidate_defs_backwards(current, error_line):
        donor_span = find_def_span_by_name(donor, name, cur_indent)
        print(f"CANDIDATE_DEF name={name} cur_start_line={cur_start+1} indent={cur_indent} donor_span={donor_span}")
        if donor_span is None:
            continue

        cur_end = len(current_lines)
        for j in range(cur_start + 1, len(current_lines)):
            m = re.match(r"^(\s*)(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\b", current_lines[j])
            if m and len(m.group(1)) <= cur_indent:
                cur_end = j
                break

        donor_start, donor_end = donor_span
        replacement = donor_lines[donor_start:donor_end]

        print(f"TRANSPLANT_FUNCTION name={name} current_lines={cur_start+1}-{cur_end} donor_lines={donor_start+1}-{donor_end}")
        return replace_span_lines(current, cur_start, cur_end, replacement)

    raise RuntimeError("Could not locate a matching donor function for the syntax-broken region")

def remove_bad_top_level_engine_ask(src: str):
    lines = src.splitlines(keepends=True)
    changed = False
    out = []
    i = 0
    while i < len(lines):
        if re.match(r"^def\s+_engine_ask\s*\(", lines[i]):
            start = i
            i += 1
            while i < len(lines):
                if re.match(r"^(def|class)\s+[A-Za-z_][A-Za-z0-9_]*\b", lines[i]):
                    break
                i += 1
            print(f"REMOVED_TOP_LEVEL_ENGINE_ASK lines={start+1}-{i}")
            changed = True
            continue
        out.append(lines[i])
        i += 1
    return "".join(out), changed

ENGINE_ASK_METHOD = '''    def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:
        """Synchronous ELI inference adapter for Labs tab."""
        prompt = str(prompt or "").strip()
        if not prompt:
            return ""

        def _normalise(result):
            if isinstance(result, dict):
                val = result.get("response")
                if val is not None and str(val).strip():
                    return str(val).strip()
                for key in ("content", "text", "answer", "message", "output"):
                    val = result.get(key)
                    if val is not None and str(val).strip():
                        return str(val).strip()
                return str(result).strip()
            if result is not None and str(result).strip():
                return str(result).strip()
            return ""

        try:
            backend = getattr(self, "active_backend", None)
            if backend is not None and hasattr(backend, "chat"):
                result = backend.chat(prompt, max_tokens=max_tokens)
                text = _normalise(result)
                if text:
                    return text
        except Exception:
            pass

        try:
            from eli.kernel.engine import get_engine
            engine = get_engine()
            if engine is not None and hasattr(engine, "process"):
                result = engine.process(prompt, stream=False, reasoning_mode="quick")
                text = _normalise(result)
                if text:
                    return text
        except Exception:
            pass

        try:
            from eli.cognition import gguf_inference
            result = gguf_inference.generate(prompt, max_tokens=max_tokens)
            text = _normalise(result)
            if text:
                return text
        except Exception:
            pass

        return "(model not loaded)"

'''

def enforce_class_engine_ask(src: str):
    create_idx = src.find("    def create_labs_tab(")
    if create_idx < 0:
        raise RuntimeError("Missing class-level create_labs_tab marker")

    start = src.find("    def _engine_ask(")
    if 0 <= start < create_idx:
        print(f"REPLACE_CLASS_ENGINE_ASK start={start} end={create_idx}")
        return src[:start] + ENGINE_ASK_METHOD + src[create_idx:]

    print(f"INSERT_CLASS_ENGINE_ASK before_create_labs_tab={create_idx}")
    return src[:create_idx] + ENGINE_ASK_METHOD + src[create_idx:]

def remove_runtime_handoff_blocks_inside_methods(src: str):
    lines = src.splitlines(keepends=True)
    out = []
    i = 0
    removed = 0

    while i < len(lines):
        line = lines[i]
        if "phase_" in line and "preloaded_runtime_handoff" in line and line.startswith("        "):
            start = i
            i += 1
            while i < len(lines):
                # Stop before the original first-time setup timer or next major comment/section at same indentation.
                if "QTimer.singleShot(600, self.maybe_run_first_time_setup)" in lines[i]:
                    break
                if re.match(r"^        # ---------- ", lines[i]):
                    break
                i += 1
            print(f"REMOVED_BAD_METHOD_HANDOFF_BLOCK lines={start+1}-{i}")
            removed += 1
            continue
        out.append(line)
        i += 1

    print(f"REMOVED_BAD_METHOD_HANDOFF_BLOCKS={removed}")
    return "".join(out)

def insert_runtime_handoff_before_first_time_setup(src: str):
    marker = "# phase_surgical_preloaded_runtime_handoff"
    if marker in src:
        print("SURGICAL_HANDOFF_ALREADY_PRESENT")
        return src

    target = "        QTimer.singleShot(600, self.maybe_run_first_time_setup)"
    idx = src.find(target)
    if idx < 0:
        raise RuntimeError("Could not find first-time setup QTimer target")

    block = '''        # phase_surgical_preloaded_runtime_handoff
        _PRELOADED_PARAMS = globals().get("_PRELOADED_PARAMS", {})
        if not isinstance(_PRELOADED_PARAMS, dict):
            _PRELOADED_PARAMS = {}
        _pre_params = dict(_PRELOADED_PARAMS)
        _eli_runtime_publish = {}
        for _src in (_pre_params, locals()):
            if isinstance(_src, dict):
                for _k in ("provider", "model_path", "model_name", "n_ctx", "n_gpu_layers", "n_threads", "n_batch", "batch_size", "max_tokens", "temperature", "top_p"):
                    _v = _src.get(_k)
                    if _v is not None and _k not in _eli_runtime_publish:
                        _eli_runtime_publish[_k] = _v

        def _apply_preloaded_runtime_params():
            if not _eli_runtime_publish:
                return {}
            try:
                from eli.cognition import gguf_inference as _ggi
                fn = getattr(_ggi, "set_runtime_override", None)
                if callable(fn):
                    fn(dict(_eli_runtime_publish))
                else:
                    setattr(_ggi, "_live_runtime_override", dict(_eli_runtime_publish))
                return dict(_eli_runtime_publish)
            except Exception as _preload_err:
                print(f"[GUI] preloaded runtime handoff failed: {_preload_err}")
                return {}

        try:
            QTimer.singleShot(600, _apply_preloaded_runtime_params)
        except Exception:
            _apply_preloaded_runtime_params()

'''
    print(f"INSERT_SURGICAL_HANDOFF_BEFORE_INDEX={idx}")
    return src[:idx] + block + src[idx:]

try:
    backup(MKI)

    donor = get_git_head_text()
    if donor is None:
        raise RuntimeError("git HEAD donor unavailable; cannot surgically transplant corrupted function")

    ok, err = compile_report(MKI)

    # Fix syntax-broken regions first. Current known case: unterminated f-string near line 5992.
    attempts = 0
    while not ok and attempts < 4:
        attempts += 1
        error_line = getattr(err, "lineno", None)
        if not error_line:
            raise RuntimeError("Compile failed without a line number")

        current = MKI.read_text(encoding="utf-8", errors="replace")
        fixed = transplant_enclosing_function_from_head(current, donor, int(error_line))
        MKI.write_text(fixed, encoding="utf-8")
        ok, err = compile_report(MKI)

    print(f"POST_TRANSPLANT_COMPILE_OK={ok}")

    # Now reapply only the contract edits, cleanly.
    src = MKI.read_text(encoding="utf-8", errors="replace")
    src, _ = remove_bad_top_level_engine_ask(src)
    src = remove_runtime_handoff_blocks_inside_methods(src)
    src = enforce_class_engine_ask(src)
    src = insert_runtime_handoff_before_first_time_setup(src)
    MKI.write_text(src, encoding="utf-8")

    ok, err = compile_report(MKI)
    print(f"FINAL_MKI_COMPILE_OK={ok}")

    source = MKI.read_text(encoding="utf-8", errors="replace")
    engine_ask = source[source.index("    def _engine_ask("):source.index("    def create_labs_tab(")]
    handoff = source[source.index("_PRELOADED_PARAMS"):source.index("QTimer.singleShot(600")]

    print("ENGINE_HAS_DICT", "if isinstance(result, dict):" in engine_ask)
    print("ENGINE_HAS_RESPONSE", 'result.get("response")' in engine_ask)
    print("ENGINE_HAS_BACKEND_CHAT", "backend.chat" in engine_ask)
    print("HANDOFF_HAS_PRE_PARAMS", "_pre_params" in handoff)
    print("HANDOFF_HAS_FOR_SRC", "for _src in (_pre_params, locals())" in handoff)
    print("HANDOFF_HAS_MODEL_PATH", '"model_path"' in handoff)
    print("HANDOFF_HAS_BATCH_SIZE", '"batch_size"' in handoff)
    print(f"BACKUP={BACKUP}")

except Exception:
    traceback.print_exc()
