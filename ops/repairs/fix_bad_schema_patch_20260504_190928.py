from pathlib import Path
import re
import shutil
import textwrap
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.fix_bad_schema_patch"
BACKUP.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/gui/labs_tab.py",
    ROOT / "eli/gui/app.py",
    ROOT / "eli/execution/executor_enhanced.py",
]

def backup(path: Path):
    try:
        if path.exists():
            dst = BACKUP / path.relative_to(ROOT)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dst)
            print(f"BACKUP {path.relative_to(ROOT)}")
        else:
            print(f"MISSING {path.relative_to(ROOT)}")
    except Exception:
        print(f"BACKUP_FAIL {path}")
        traceback.print_exc()

def write_if_changed(path: Path, text: str):
    old = path.read_text(encoding="utf-8", errors="replace")
    if old != text:
        path.write_text(text, encoding="utf-8")
        print(f"PATCHED {path.relative_to(ROOT)}")
    else:
        print(f"UNCHANGED {path.relative_to(ROOT)}")

def replace_def_by_text(path: Path, def_name: str, replacement: str):
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines(keepends=True)

    start = None
    for i, line in enumerate(lines):
        if re.match(rf"^([ \t]*)def {re.escape(def_name)}\s*\(", line):
            start = i
            break

    if start is None:
        print(f"DEF_NOT_FOUND {path.relative_to(ROOT)}::{def_name}")
        return

    indent = re.match(r"^([ \t]*)", lines[start]).group(1)
    end = len(lines)

    for j in range(start + 1, len(lines)):
        line = lines[j]
        if not line.strip():
            continue
        current_indent = re.match(r"^([ \t]*)", line).group(1)
        if len(current_indent) <= len(indent) and re.match(r"^[ \t]*(def |class |@)", line):
            end = j
            break

    repl = textwrap.indent(textwrap.dedent(replacement).strip("\n"), indent) + "\n"
    new_src = "".join(lines[:start]) + repl + "".join(lines[end:])
    write_if_changed(path, new_src)

for p in TARGETS:
    backup(p)

# -------------------------------------------------------------------
# 1. Fix labs_tab._engine_ask by raw text, not AST.
# -------------------------------------------------------------------
try:
    replace_def_by_text(
        ROOT / "eli/gui/labs_tab.py",
        "_engine_ask",
        '''
        def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:
            """Synchronous ELI inference adapter for Labs.

            This adapter accepts native CognitiveEngine/GGUF response shapes
            and normalises them to visible text.
            """
            prompt = str(prompt or "").strip()
            if not prompt:
                return ""

            def _normalise_result(result):
                if isinstance(result, dict):
                    for key in ("content", "response", "text", "answer", "message", "output"):
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
                    text = _normalise_result(result)
                    if text:
                        return text
            except Exception:
                pass

            try:
                from eli.cognition import gguf_inference
                result = gguf_inference.generate(prompt, max_tokens=max_tokens)
                text = _normalise_result(result)
                if text:
                    return text
            except Exception:
                pass

            return "(model not loaded)"
        '''
    )
except Exception:
    print("PATCH_FAIL labs_tab._engine_ask")
    traceback.print_exc()

# -------------------------------------------------------------------
# 2. Remove bad app.py handoff block and reinsert after __future__.
# -------------------------------------------------------------------
try:
    path = ROOT / "eli/gui/app.py"
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines(keepends=True)

    # Remove the broken block inserted before from __future__.
    cleaned = []
    i = 0
    while i < len(lines):
        if "phase_nonfatal_preloaded_runtime_handoff" in lines[i] or "phase_portable_schema_runtime_preloaded_handoff" in lines[i]:
            print(f"REMOVING_BAD_HANDOFF_BLOCK_AT_LINE {i+1}")
            i += 1
            while i < len(lines):
                if lines[i].startswith("from __future__ import "):
                    break
                if lines[i].startswith("import ") or lines[i].startswith("from "):
                    break
                i += 1
            continue
        cleaned.append(lines[i])
        i += 1

    src = "".join(cleaned)

    marker = "phase_fixed_preloaded_runtime_handoff"
    if marker not in src:
        block = textwrap.dedent('''

        # phase_fixed_preloaded_runtime_handoff
        _PRELOADED_PARAMS = globals().get("_PRELOADED_PARAMS", {})
        if not isinstance(_PRELOADED_PARAMS, dict):
            _PRELOADED_PARAMS = {}

        def _apply_preloaded_runtime_params():
            params = globals().get("_PRELOADED_PARAMS", {}) or {}
            if not isinstance(params, dict):
                return {}

            allowed = {
                "provider", "model_path", "model_name",
                "n_ctx", "n_gpu_layers", "n_threads", "n_batch", "batch_size",
                "max_tokens", "temperature", "top_p",
            }
            clean = {k: v for k, v in params.items() if k in allowed and v is not None}
            if not clean:
                return {}

            try:
                from eli.cognition import gguf_inference
                for fn_name in (
                    "set_live_runtime_params",
                    "set_runtime_override",
                    "apply_runtime_override",
                    "configure_runtime",
                ):
                    fn = getattr(gguf_inference, fn_name, None)
                    if callable(fn):
                        try:
                            fn(dict(clean))
                            return dict(clean)
                        except TypeError:
                            continue

                setattr(gguf_inference, "_live_runtime_override", dict(clean))
                setattr(gguf_inference, "_live_runtime_params", dict(clean))
                return dict(clean)
            except Exception as exc:
                print(f"[GUI] preloaded runtime params not applied: {exc}")
                return {}

        def _schedule_preloaded_runtime_handoff():
            try:
                QTimer.singleShot(600, _apply_preloaded_runtime_params)
            except Exception:
                return _apply_preloaded_runtime_params()

        ''')

        app_lines = src.splitlines(keepends=True)
        insert_at = 0
        for idx, line in enumerate(app_lines):
            if line.startswith("from __future__ import "):
                insert_at = idx + 1

        src = "".join(app_lines[:insert_at]) + block + "".join(app_lines[insert_at:])

    write_if_changed(path, src)
except Exception:
    print("PATCH_FAIL app.py")
    traceback.print_exc()

# -------------------------------------------------------------------
# 3. Add final executor schema guard. Broad action interception.
# -------------------------------------------------------------------
try:
    path = ROOT / "eli/execution/executor_enhanced.py"
    src = path.read_text(encoding="utf-8", errors="replace")
    marker = "phase_fixed_final_executor_schema_guard"

    if marker not in src:
        wrapper = r'''

# phase_fixed_final_executor_schema_guard
try:
    _ELI_EXECUTE_ACTION_BEFORE_FIXED_SCHEMA_GUARD
except NameError:
    _ELI_EXECUTE_ACTION_BEFORE_FIXED_SCHEMA_GUARD = execute_action

    def _eli_fixed_project_root():
        from pathlib import Path
        import os
        env_root = os.environ.get("ELI_PROJECT_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()
        return Path(__file__).resolve().parents[2]

    def _eli_fixed_artifacts_dir():
        from pathlib import Path
        import os
        env_dir = os.environ.get("ELI_ARTIFACTS_DIR")
        if env_dir:
            p = Path(env_dir).expanduser()
            return p.resolve() if p.is_absolute() else (_eli_fixed_project_root() / p).resolve()
        return (_eli_fixed_project_root() / "artifacts").resolve()

    def _eli_fixed_slug(value, default="artifact"):
        import re
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
        return slug or default

    def _eli_fixed_create_document(args):
        import time
        args = args if isinstance(args, dict) else {}

        title = (
            args.get("title")
            or args.get("name")
            or args.get("filename")
            or args.get("file_name")
            or f"document_{int(time.time())}"
        )
        content = (
            args.get("content")
            or args.get("body")
            or args.get("text")
            or args.get("markdown")
            or ""
        )

        ext = str(args.get("format") or args.get("ext") or "md").lower().lstrip(".")
        if ext not in {"md", "txt", "json", "csv", "tex", "py"}:
            ext = "md"

        filename = _eli_fixed_slug(title, "document")
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{filename}.{ext}"

        out_dir = _eli_fixed_artifacts_dir() / "documents"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / filename

        if path.exists() and not bool(args.get("overwrite", False)):
            stem = path.stem
            suffix = path.suffix
            n = 2
            while True:
                candidate = out_dir / f"{stem}_{n}{suffix}"
                if not candidate.exists():
                    path = candidate
                    break
                n += 1

        path.write_text(str(content), encoding="utf-8")
        msg = f"Document saved: {path}"
        return {
            "ok": True,
            "action": "CREATE_DOCUMENT",
            "doc_path": str(path),
            "path": str(path),
            "content": msg,
            "response": msg,
        }

    def _eli_fixed_supplied_python(args):
        args = args if isinstance(args, dict) else {}

        for key in ("code", "script", "source", "content", "python", "body", "text"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val

        prompt = args.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            stripped = prompt.lstrip()
            if (
                bool(args.get("test_mode"))
                or "\n" in prompt
                or stripped.startswith(("def ", "class ", "import ", "from ", "print(", "for ", "while ", "if ", "try:"))
            ):
                return prompt

        return None

    def _eli_fixed_failure_schema(action, result):
        if not isinstance(result, dict):
            return result

        if bool(result.get("ok", True)):
            return result

        if result.get("error"):
            return result

        evidence = result.get("evidence")
        if isinstance(evidence, (list, tuple)) and evidence:
            result["error"] = str(evidence[0])
        elif result.get("content"):
            result["error"] = str(result.get("content"))
        elif result.get("response"):
            result["error"] = str(result.get("response"))
        else:
            result["error"] = f"{action} failed"

        return result

    def execute_action(action, args=None, *pargs, **kwargs):
        action_name = str(action or "").strip().upper().replace("-", "_")
        args = args if isinstance(args, dict) else {}

        if "DOCUMENT" in action_name and any(x in action_name for x in ("CREATE", "WRITE", "NEW", "SAVE")):
            return _eli_fixed_create_document(args)

        if "SCRIPT" in action_name and any(x in action_name for x in ("GENERATE", "CREATE", "WRITE", "NEW", "SAVE")):
            supplied = _eli_fixed_supplied_python(args)
            if supplied is not None:
                try:
                    compile(str(supplied), "<eli-generated-script>", "exec")
                except SyntaxError as exc:
                    err = f"Generated Python script failed syntax validation: {exc}"
                    return {
                        "ok": False,
                        "action": action_name,
                        "error": err,
                        "content": err,
                        "response": err,
                        "evidence": [err],
                    }

        result = _ELI_EXECUTE_ACTION_BEFORE_FIXED_SCHEMA_GUARD(action, args, *pargs, **kwargs)
        return _eli_fixed_failure_schema(action_name, result)
'''
        src = src.rstrip() + "\n" + wrapper + "\n"
        write_if_changed(path, src)
    else:
        print("FINAL_EXECUTOR_GUARD_ALREADY_PRESENT")
except Exception:
    print("PATCH_FAIL executor_enhanced.py")
    traceback.print_exc()

print(f"BACKUP={BACKUP}")
