from pathlib import Path
import re
import shutil
import textwrap
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.final_gui_schema_contract"
BACKUP.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ROOT / "eli/gui/labs_tab.py",
    ROOT / "eli/gui/app.py",
    ROOT / "eli/gui/eli_pro_audio_gui_MKI.py",
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

for p in TARGETS:
    backup(p)

# ---------------------------------------------------------------------
# 1. labs_tab.py: do not replace the whole method; patch the bad line.
# ---------------------------------------------------------------------
try:
    path = ROOT / "eli/gui/labs_tab.py"
    src = path.read_text(encoding="utf-8", errors="replace")

    hits = [(i + 1, line.rstrip()) for i, line in enumerate(src.splitlines()) if "_engine_ask" in line]
    print("LABS_ENGINE_ASK_HITS=" + repr(hits[:20]))

    pattern = re.compile(
        r'(?m)^(?P<indent>[ \t]*)text = result\.get\("text", ""\) if isinstance\(result, dict\) else str\(result\)[ \t]*$'
    )

    def repl(m):
        ind = m.group("indent")
        return (
            f'{ind}if isinstance(result, dict):\n'
            f'{ind}    text = (\n'
            f'{ind}        result.get("content")\n'
            f'{ind}        or result.get("response")\n'
            f'{ind}        or result.get("text")\n'
            f'{ind}        or result.get("answer")\n'
            f'{ind}        or result.get("message")\n'
            f'{ind}        or result.get("output")\n'
            f'{ind}        or ""\n'
            f'{ind}    )\n'
            f'{ind}else:\n'
            f'{ind}    text = str(result)'
        )

    src2, n = pattern.subn(repl, src)
    print(f"LABS_DICT_LINE_PATCH_COUNT={n}")

    if n == 0 and "if isinstance(result, dict):" not in src:
        print("LABS_PATCH_WARNING: exact one-line dict normaliser not found")

    write_if_changed(path, src2)
except Exception:
    print("PATCH_FAIL labs_tab.py")
    traceback.print_exc()

# ---------------------------------------------------------------------
# 2. GUI preloaded handoff: add portable handoff to both possible files.
# ---------------------------------------------------------------------
HANDOFF_MARKER = "phase_final_preloaded_runtime_handoff"

HANDOFF_BLOCK = textwrap.dedent('''

# phase_final_preloaded_runtime_handoff
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

def insert_handoff(path: Path):
    if not path.exists():
        print(f"HANDOFF_SKIP_MISSING {path.relative_to(ROOT)}")
        return

    src = path.read_text(encoding="utf-8", errors="replace")

    if HANDOFF_MARKER in src:
        print(f"HANDOFF_ALREADY_PRESENT {path.relative_to(ROOT)}")
        return

    lines = src.splitlines(keepends=True)

    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from __future__ import "):
            insert_at = i + 1

    if insert_at == 0:
        while insert_at < len(lines):
            s = lines[insert_at]
            if s.startswith("#!") or "coding" in s or not s.strip():
                insert_at += 1
                continue
            break

    src2 = "".join(lines[:insert_at]) + HANDOFF_BLOCK + "".join(lines[insert_at:])
    write_if_changed(path, src2)

try:
    insert_handoff(ROOT / "eli/gui/app.py")
    insert_handoff(ROOT / "eli/gui/eli_pro_audio_gui_MKI.py")
except Exception:
    print("PATCH_FAIL GUI handoff")
    traceback.print_exc()

# ---------------------------------------------------------------------
# 3. Final executor schema guard. Appended last, broad but portable.
# ---------------------------------------------------------------------
try:
    path = ROOT / "eli/execution/executor_enhanced.py"
    src = path.read_text(encoding="utf-8", errors="replace")
    marker = "phase_final_executor_schema_contract_guard"

    if marker not in src:
        guard = r'''

# phase_final_executor_schema_contract_guard
try:
    _ELI_EXECUTE_ACTION_BEFORE_FINAL_SCHEMA_CONTRACT
except NameError:
    _ELI_EXECUTE_ACTION_BEFORE_FINAL_SCHEMA_CONTRACT = execute_action

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

    def _eli_schema_slug(value, default="artifact"):
        import re
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip()).strip("._-")
        return slug or default

    def _eli_schema_create_document(args):
        import time
        args = args if isinstance(args, dict) else {}

        title = (
            args.get("title")
            or args.get("name")
            or args.get("filename")
            or args.get("file_name")
            or "document"
        )
        content = (
            args.get("content")
            or args.get("body")
            or args.get("text")
            or args.get("markdown")
            or args.get("prompt")
            or ""
        )

        ext = str(args.get("format") or args.get("ext") or "md").lower().lstrip(".")
        if ext not in {"md", "txt", "json", "csv", "tex", "py"}:
            ext = "md"

        filename = _eli_schema_slug(title, "document")
        if not filename.lower().endswith(f".{ext}"):
            filename = f"{filename}.{ext}"

        out_dir = _eli_schema_artifacts_dir() / "documents"
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

    def _eli_schema_python_source(args):
        args = args if isinstance(args, dict) else {}

        preferred = (
            "code", "script", "source", "content", "python", "body", "text",
            "script_text", "raw", "input", "prompt", "instructions",
        )
        for key in preferred:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val

        for val in args.values():
            if isinstance(val, str) and val.strip():
                return val

        return None

    def _eli_schema_failure(action_name, result):
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
            result["error"] = f"{action_name} failed"

        return result

    def execute_action(action, args=None, *pargs, **kwargs):
        action_name = str(action or "").strip().upper().replace("-", "_")
        args = args if isinstance(args, dict) else {}

        is_document_action = (
            "DOCUMENT" in action_name
            or action_name.endswith("_DOC")
            or "_DOC_" in action_name
            or action_name in {"CREATE_DOC", "WRITE_DOC", "SAVE_DOC", "NEW_DOC"}
        )
        wants_create = any(x in action_name for x in ("CREATE", "WRITE", "SAVE", "NEW", "GENERATE"))

        if is_document_action and wants_create:
            return _eli_schema_create_document(args)

        is_script_action = (
            "SCRIPT" in action_name
            or action_name in {"GENERATE_PYTHON", "CREATE_PYTHON", "WRITE_PYTHON"}
        )

        if is_script_action and any(x in action_name for x in ("GENERATE", "CREATE", "WRITE", "SAVE", "NEW")):
            supplied = _eli_schema_python_source(args)
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

        result = _ELI_EXECUTE_ACTION_BEFORE_FINAL_SCHEMA_CONTRACT(action, args, *pargs, **kwargs)
        return _eli_schema_failure(action_name, result)
'''
        src = src.rstrip() + "\n" + guard + "\n"
        write_if_changed(path, src)
    else:
        print("FINAL_EXECUTOR_SCHEMA_GUARD_ALREADY_PRESENT")
except Exception:
    print("PATCH_FAIL executor_enhanced.py")
    traceback.print_exc()

print(f"BACKUP={BACKUP}")
