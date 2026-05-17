from pathlib import Path
import ast
import shutil
import textwrap
import time
import traceback

ROOT = Path.cwd()
BACKUP = ROOT / "ops" / "backups" / f"{time.strftime('%Y%m%d_%H%M%S')}.nonfatal_schema_patch"
BACKUP.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/gui/labs_tab.py",
    ROOT / "eli/gui/app.py",
    ROOT / "eli/execution/executor_enhanced.py",
]

def backup(path: Path) -> None:
    if not path.exists():
        print(f"MISSING {path}")
        return
    dst = BACKUP / path.relative_to(ROOT)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dst)
    print(f"BACKUP {path.relative_to(ROOT)}")

def write_if_changed(path: Path, text: str) -> None:
    old = path.read_text(encoding="utf-8", errors="replace")
    if old != text:
        path.write_text(text, encoding="utf-8")
        print(f"PATCHED {path.relative_to(ROOT)}")
    else:
        print(f"UNCHANGED {path.relative_to(ROOT)}")

def replace_function(path: Path, func_name: str, replacement: str) -> None:
    src = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    lines = src.splitlines(keepends=True)

    matches = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            start = node.lineno
            if getattr(node, "decorator_list", None):
                start = min([start] + [d.lineno for d in node.decorator_list])
            end = getattr(node, "end_lineno", None)
            matches.append((start, end))

    if not matches:
        print(f"FUNC_NOT_FOUND {path.relative_to(ROOT)}::{func_name}")
        return

    start, end = matches[0]
    indent = lines[start - 1][:len(lines[start - 1]) - len(lines[start - 1].lstrip())]
    repl = textwrap.indent(textwrap.dedent(replacement).strip("\n"), indent) + "\n"
    new_src = "".join(lines[:start - 1]) + repl + "".join(lines[end:])
    write_if_changed(path, new_src)

for target in TARGETS:
    backup(target)

try:
    replace_function(
        ROOT / "eli/gui/labs_tab.py",
        "_engine_ask",
        '''
        def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:
            """Synchronous ELI inference adapter for Labs.

            Accepts native runtime response shapes and normalises them to
            visible text without hard-coded answer content.
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

try:
    path = ROOT / "eli/gui/app.py"
    src = path.read_text(encoding="utf-8", errors="replace")
    marker = "phase_nonfatal_preloaded_runtime_handoff"

    if marker in src:
        print("APP_HANDOFF_ALREADY_PRESENT")
    else:
        block = textwrap.dedent('''

        # phase_nonfatal_preloaded_runtime_handoff
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

        lines = src.splitlines(keepends=True)
        insert_at = 0
        while insert_at < len(lines):
            line = lines[insert_at]
            if insert_at == 0 and line.startswith("#!"):
                insert_at += 1
                continue
            if line.lstrip().startswith("#") and "coding" in line:
                insert_at += 1
                continue
            if line.startswith("from __future__ import "):
                insert_at += 1
                continue
            break

        src = "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])
        write_if_changed(path, src)
except Exception:
    print("PATCH_FAIL app.py")
    traceback.print_exc()

try:
    path = ROOT / "eli/execution/executor_enhanced.py"
    src = path.read_text(encoding="utf-8", errors="replace")
    marker = "phase_nonfatal_executor_schema_guard"

    if marker in src:
        print("EXECUTOR_SCHEMA_ALREADY_PRESENT")
    else:
        wrapper = r'''

# phase_nonfatal_executor_schema_guard
try:
    _ELI_EXECUTE_ACTION_BEFORE_SCHEMA_GUARD
except NameError:
    _ELI_EXECUTE_ACTION_BEFORE_SCHEMA_GUARD = execute_action

    def _eli_schema_project_root():
        from pathlib import Path
        import os
        env_root = os.environ.get("ELI_PROJECT_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()
        return Path(__file__).resolve().parents[2]

    def _eli_schema_artifacts_dir():
        from pathlib import Path
        import os
        env_dir = os.environ.get("ELI_ARTIFACTS_DIR")
        if env_dir:
            p = Path(env_dir).expanduser()
            return p.resolve() if p.is_absolute() else (_eli_schema_project_root() / p).resolve()
        return (_eli_schema_project_root() / "artifacts").resolve()

    def _eli_schema_slug(text, default="document"):
        import re
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._-")
        return slug or default

    def _eli_schema_create_document(args):
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

        name = _eli_schema_slug(title)
        if not name.lower().endswith(f".{ext}"):
            name = f"{name}.{ext}"

        out_dir = _eli_schema_artifacts_dir() / "documents"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name

        if path.exists() and not bool(args.get("overwrite", False)):
            base = path.stem
            suffix = path.suffix
            i = 2
            while True:
                candidate = out_dir / f"{base}_{i}{suffix}"
                if not candidate.exists():
                    path = candidate
                    break
                i += 1

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

    def _eli_schema_supplied_python(args):
        args = args if isinstance(args, dict) else {}

        for key in ("code", "script", "source", "content", "python", "body", "text"):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value

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

    def _eli_schema_normalise_failure(action, result):
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

        if action_name in {"CREATE_DOCUMENT", "CREATE_DOC", "WRITE_DOCUMENT"}:
            return _eli_schema_create_document(args)

        if action_name in {"GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT"}:
            supplied = _eli_schema_supplied_python(args)
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

        result = _ELI_EXECUTE_ACTION_BEFORE_SCHEMA_GUARD(action, args, *pargs, **kwargs)
        return _eli_schema_normalise_failure(action_name, result)
'''
        src = src.rstrip() + "\n" + wrapper + "\n"
        write_if_changed(path, src)
except Exception:
    print("PATCH_FAIL executor_enhanced.py")
    traceback.print_exc()

print(f"BACKUP={BACKUP}")
