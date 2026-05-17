from pathlib import Path
import os
import py_compile
import re
import shutil
import subprocess
import textwrap
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.clean_reapply_gui_schema_contract"
BACKUP.mkdir(parents=True, exist_ok=True)

FILES = {
    "mki": "eli/gui/eli_pro_audio_gui_MKI.py",
    "app": "eli/gui/app.py",
    "labs": "eli/gui/labs_tab.py",
    "executor": "eli/execution/executor_enhanced.py",
}

def backup_current(rel: str) -> None:
    path = ROOT / rel
    if path.exists():
        dst = BACKUP / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"BACKUP_CURRENT {rel} -> {dst}")

def git_head_text(rel: str) -> str:
    proc = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git show HEAD:{rel} failed: {proc.stderr.strip()}")
    return proc.stdout

def write_text(rel: str, text: str) -> None:
    path = ROOT / rel
    old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if old != text:
        path.write_text(text, encoding="utf-8")
        print(f"PATCHED {rel}")
    else:
        print(f"UNCHANGED {rel}")

def compile_one(rel: str) -> int:
    try:
        py_compile.compile(str(ROOT / rel), doraise=True)
        print(f"COMPILE_OK {rel}")
        return 0
    except Exception as exc:
        print(f"COMPILE_BAD {rel}: {exc}")
        return 1

def patch_mki() -> None:
    rel = FILES["mki"]
    src = git_head_text(rel)

    engine_method = textwrap.dedent('''
        def _engine_ask(self, prompt: str, max_tokens: int = 512) -> str:
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

            return "(model not loaded)"

    ''')

    start_token = "\n    def _engine_ask("
    end_token = "\n    def create_labs_tab("
    start = src.find(start_token)
    end = src.find(end_token)

    if end < 0:
        raise RuntimeError("Could not find create_labs_tab in MKI")

    if start >= 0 and start < end:
        src = src[:start + 1] + engine_method + src[end + 1:]
        print("MKI_ENGINE_ASK_REPLACED")
    else:
        src = src[:end + 1] + engine_method + src[end + 1:]
        print("MKI_ENGINE_ASK_INSERTED")

    first_qtimer = src.find("QTimer.singleShot(600")
    if first_qtimer < 0:
        raise RuntimeError("Could not find QTimer.singleShot(600 in MKI")

    line_start = src.rfind("\n", 0, first_qtimer) + 1
    indent = src[line_start:first_qtimer]

    handoff_body = textwrap.dedent('''
        # Runtime handoff from launcher/model picker. Portable: no absolute source paths.
        _PRELOADED_PARAMS = globals().get("_PRELOADED_PARAMS", {})
        if not isinstance(_PRELOADED_PARAMS, dict):
            _PRELOADED_PARAMS = {}
        _pre_params = dict(_PRELOADED_PARAMS)
        _runtime_handoff = {}

        for _src in (_pre_params, locals()):
            if isinstance(_src, dict):
                for _key in (
                    "provider",
                    "model_path",
                    "model_name",
                    "n_ctx",
                    "n_gpu_layers",
                    "n_threads",
                    "n_batch",
                    "batch_size",
                    "max_tokens",
                    "temperature",
                    "top_p",
                ):
                    _value = _src.get(_key)
                    if _value is not None and _key not in _runtime_handoff:
                        _runtime_handoff[_key] = _value

        def _apply_preloaded_runtime_params():
            if not _runtime_handoff:
                return {}
            try:
                from eli.cognition import gguf_inference as _gguf_runtime
                for _fn_name in (
                    "set_live_runtime_params",
                    "set_runtime_override",
                    "apply_runtime_override",
                    "configure_runtime",
                ):
                    _fn = getattr(_gguf_runtime, _fn_name, None)
                    if callable(_fn):
                        try:
                            _fn(dict(_runtime_handoff))
                            return dict(_runtime_handoff)
                        except TypeError:
                            continue
                setattr(_gguf_runtime, "_live_runtime_override", dict(_runtime_handoff))
                setattr(_gguf_runtime, "_live_runtime_params", dict(_runtime_handoff))
            except Exception as _handoff_err:
                print(f"[GUI] preloaded runtime handoff failed: {_handoff_err}")
            return dict(_runtime_handoff)

        try:
            QTimer.singleShot(600, _apply_preloaded_runtime_params)
        except Exception:
            _apply_preloaded_runtime_params()
    ''').strip("\n")

    handoff_block = textwrap.indent(handoff_body, indent) + "\n\n"
    src = src[:line_start] + handoff_block + src[line_start:]
    print("MKI_PRELOADED_HANDOFF_INSERTED")

    write_text(rel, src)

def patch_executor() -> None:
    rel = FILES["executor"]
    src = git_head_text(rel)

    guard = textwrap.dedent('''

        # gui_schema_contract_guard
        try:
            _ELI_SCHEMA_CONTRACT_ORIGINAL_EXECUTE
        except NameError:
            _ELI_SCHEMA_CONTRACT_ORIGINAL_EXECUTE = execute

            def _eli_schema_project_root():
                env_root = os.environ.get("ELI_PROJECT_ROOT")
                if env_root:
                    return Path(env_root).expanduser().resolve()
                return Path(__file__).resolve().parents[2]

            def _eli_schema_artifacts_dir():
                root = _eli_schema_project_root()
                env_artifacts = os.environ.get("ELI_ARTIFACTS_DIR")
                if env_artifacts:
                    candidate = Path(env_artifacts).expanduser()
                    return candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
                return (root / "artifacts").resolve()

            def _eli_schema_slug(value, default="document"):
                slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
                return slug or default

            def _eli_schema_text_from_result(result):
                if isinstance(result, dict):
                    for key in ("content", "response", "text", "answer", "message", "output"):
                        value = result.get(key)
                        if value is not None and str(value).strip():
                            return str(value)
                    return ""
                if result is not None:
                    return str(result)
                return ""

            def _eli_schema_create_document(args):
                args = args if isinstance(args, dict) else {}
                topic = args.get("topic") or args.get("title") or args.get("name") or "document"
                title = args.get("title") or args.get("name") or topic
                fmt = str(args.get("format") or args.get("ext") or "md").lower().lstrip(".")
                if fmt not in {"md", "txt", "json", "csv", "tex", "py"}:
                    fmt = "md"

                content = (
                    args.get("content")
                    or args.get("body")
                    or args.get("text")
                    or args.get("markdown")
                )
                if content is None:
                    content = f"{title}\\n\\nRequested topic: {topic}\\n"

                out_dir = _eli_schema_artifacts_dir() / "documents"
                out_dir.mkdir(parents=True, exist_ok=True)

                filename = _eli_schema_slug(title, "document")
                if not filename.lower().endswith(f".{fmt}"):
                    filename = f"{filename}.{fmt}"

                path = out_dir / filename
                if path.exists() and not bool(args.get("overwrite", False)):
                    stem = path.stem
                    suffix = path.suffix
                    idx = 2
                    while True:
                        candidate = out_dir / f"{stem}_{idx}{suffix}"
                        if not candidate.exists():
                            path = candidate
                            break
                        idx += 1

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

            def _eli_schema_extract_python_source(args):
                args = args if isinstance(args, dict) else {}
                for key in ("code", "script", "source", "content", "python", "body", "text"):
                    value = args.get(key)
                    if isinstance(value, str) and value.strip():
                        return value

                generator = globals().get("chat")
                if callable(generator):
                    prompt = args.get("description") or args.get("prompt") or "Generate a Python script."
                    result = generator(str(prompt))
                    text = _eli_schema_text_from_result(result)
                    if text.strip():
                        return text

                prompt = args.get("prompt")
                if isinstance(prompt, str) and prompt.strip():
                    stripped = prompt.lstrip()
                    if "\\n" in prompt or stripped.startswith(("def ", "class ", "import ", "from ", "print(", "for ", "while ", "if ", "try:")):
                        return prompt

                return None

            def _eli_schema_failure(action_name, message):
                return {
                    "ok": False,
                    "action": action_name,
                    "error": str(message),
                    "content": str(message),
                    "response": str(message),
                    "evidence": [str(message)],
                }

            def _eli_schema_normalise_failure(action_name, result):
                if not isinstance(result, dict):
                    return result
                if bool(result.get("ok", True)):
                    return result
                if result.get("error"):
                    return result
                for key in ("content", "response", "message"):
                    value = result.get(key)
                    if value:
                        result["error"] = str(value)
                        return result
                evidence = result.get("evidence")
                if isinstance(evidence, (list, tuple)) and evidence:
                    result["error"] = str(evidence[0])
                    return result
                result["error"] = f"{action_name} failed"
                return result

            def execute(action, args=None, *pargs, **kwargs):
                action_name = str(action or "").strip().upper().replace("-", "_")
                call_args = args if isinstance(args, dict) else {}

                if action_name in {"CREATE_DOCUMENT", "CREATE_DOC", "WRITE_DOCUMENT"}:
                    return _eli_schema_create_document(call_args)

                if action_name in {"GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT"}:
                    source = _eli_schema_extract_python_source(call_args)
                    if source is not None:
                        try:
                            compile(str(source), "<eli-generated-script>", "exec")
                        except SyntaxError as exc:
                            return _eli_schema_failure(
                                action_name,
                                f"Generated Python script failed syntax validation: {exc}",
                            )

                result = _ELI_SCHEMA_CONTRACT_ORIGINAL_EXECUTE(action, args, *pargs, **kwargs)
                return _eli_schema_normalise_failure(action_name, result)
    ''')

    src = src.rstrip() + "\n" + guard + "\n"
    write_text(rel, src)

def main() -> int:
    for rel in FILES.values():
        backup_current(rel)

    # Remove all failed patch debris by restoring clean HEAD versions first.
    write_text(FILES["app"], git_head_text(FILES["app"]))
    write_text(FILES["labs"], git_head_text(FILES["labs"]))

    patch_mki()
    patch_executor()

    rc = 0
    for rel in FILES.values():
        rc |= compile_one(rel)

    print(f"BACKUP={BACKUP}")
    print(f"PATCH_RC={rc}")
    return rc

try:
    raise SystemExit(main())
except SystemExit:
    raise
except Exception:
    traceback.print_exc()
    print(f"BACKUP={BACKUP}")
    print("PATCH_RC=1")
    raise SystemExit(1)
