from pathlib import Path
import py_compile
import shutil
import traceback

ROOT = Path.cwd()
ROUTER = ROOT / "eli/execution/router_enhanced.py"
EXECUTOR = ROOT / "eli/execution/executor_enhanced.py"


def latest_backup_file(rel: str):
    candidates = sorted(
        (ROOT / "ops/backups").glob("*.generic_runtime_contract_v2"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for backup in candidates:
        src = backup / rel
        if src.exists():
            return src
    return None


def restore_from_pre_bad_backup(rel: str):
    dst = ROOT / rel
    src = latest_backup_file(rel)
    if not src:
        print(f"RESTORE_SKIPPED missing backup for {rel}")
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"RESTORED {rel} <- {src}")
    return True


def append_once(path: Path, marker: str, block: str):
    src = path.read_text(encoding="utf-8", errors="replace")
    if marker in src:
        print(f"UNCHANGED {path.relative_to(ROOT)} marker={marker}")
        return
    path.write_text(src.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")
    print(f"PATCHED {path.relative_to(ROOT)} marker={marker}")


router_hook = '''
# portable_runtime_contract_v3_router_hook
try:
    from eli.execution.portable_intent_contract import wrap_router_callable as _eli_portable_wrap_router

    for _eli_name in (
        "route", "route_text", "route_command", "route_intent",
        "parse", "parse_intent", "parse_command",
        "classify", "classify_intent",
    ):
        _eli_fn = globals().get(_eli_name)
        if callable(_eli_fn):
            globals()[_eli_name] = _eli_portable_wrap_router(_eli_fn)

    for _eli_obj in list(globals().values()):
        if isinstance(_eli_obj, type):
            for _eli_name in (
                "route", "route_text", "route_command", "route_intent",
                "parse", "parse_intent", "parse_command",
                "classify", "classify_intent",
            ):
                try:
                    _eli_method = getattr(_eli_obj, _eli_name, None)
                    if callable(_eli_method):
                        setattr(_eli_obj, _eli_name, _eli_portable_wrap_router(_eli_method))
                except Exception:
                    pass
except Exception as _eli_portable_router_err:
    print(f"[portable_intent_contract] router hook unavailable: {_eli_portable_router_err}")
'''


executor_hook = '''
# portable_runtime_contract_v3_executor_hook
try:
    _ELI_PORTABLE_V3_ORIG_EXECUTE
except NameError:
    _ELI_PORTABLE_V3_ORIG_EXECUTE = globals().get("execute")
    _ELI_PORTABLE_V3_ORIG_EXECUTE_ACTION = globals().get("execute_action")

    def _eli_v3_action_name(action):
        return str(action or "").strip().upper().replace("-", "_")

    def _eli_v3_args(args):
        return args if isinstance(args, dict) else {}

    def _eli_v3_error(action_name, text):
        return {
            "ok": False,
            "action": action_name,
            "error": str(text),
            "content": str(text),
            "response": str(text),
            "evidence": [str(text)],
        }

    def _eli_v3_direct_system_action(action, args=None):
        action_name = _eli_v3_action_name(action)
        data = _eli_v3_args(args)

        if action_name in {"OPEN_APP", "LAUNCH_APP", "OPEN_APPLICATION"}:
            from eli.system.portable_app_control import open_app
            return open_app(data.get("name") or data.get("target") or data.get("app") or "")

        if action_name in {"CLOSE_APP", "QUIT_APP", "EXIT_APP", "CLOSE_APPLICATION"}:
            from eli.system.portable_app_control import close_app
            return close_app(
                data.get("name") or data.get("target") or data.get("app") or "",
                force=bool(data.get("force", False)),
            )

        if action_name in {
            "MINIMIZE_APP", "MINIMISE_APP", "HIDE_APP",
            "MINIMIZE_WINDOW", "MINIMISE_WINDOW",
        }:
            from eli.system.portable_app_control import minimize_app
            return minimize_app(data.get("name") or data.get("target") or data.get("app") or "")

        return None

    def _eli_v3_project_root():
        from pathlib import Path
        import os
        env_root = os.environ.get("ELI_PROJECT_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()
        return Path(__file__).resolve().parents[2]

    def _eli_v3_artifacts_dir():
        from pathlib import Path
        import os
        root = _eli_v3_project_root()
        env_dir = os.environ.get("ELI_ARTIFACTS_DIR")
        if env_dir:
            p = Path(env_dir).expanduser()
            return p.resolve() if p.is_absolute() else (root / p).resolve()
        return (root / "artifacts").resolve()

    def _eli_v3_slug(text, default="generated_script"):
        import re
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._-")
        return slug[:80] or default

    def _eli_v3_language_ext(language):
        mapping = {
            "python": "py", "py": "py",
            "bash": "sh", "shell": "sh", "sh": "sh", "zsh": "zsh",
            "javascript": "js", "js": "js",
            "typescript": "ts", "ts": "ts",
            "c++": "cpp", "cpp": "cpp",
            "c": "c",
            "c#": "cs", "csharp": "cs",
            "java": "java",
            "rust": "rs",
            "go": "go",
            "ruby": "rb",
            "php": "php",
            "lua": "lua",
            "r": "r",
            "swift": "swift",
            "kotlin": "kt",
            "scala": "scala",
            "sql": "sql",
            "html": "html",
            "css": "css",
            "json": "json",
            "yaml": "yaml", "yml": "yml",
        }
        lang = str(language or "auto").strip().lower()
        return mapping.get(lang, lang if lang and lang != "auto" and len(lang) <= 12 else "txt")

    def _eli_v3_extract_code(raw, language="auto"):
        import re
        if isinstance(raw, dict):
            for key in ("code", "content", "response", "text", "answer", "message", "output"):
                val = raw.get(key)
                if val is not None and str(val).strip():
                    raw = str(val)
                    break
            else:
                raw = str(raw)
        else:
            raw = str(raw or "")

        fences = re.findall(r"```([A-Za-z0-9+#._-]*)\\n(.*?)```", raw, flags=re.DOTALL)
        if fences:
            wanted = str(language or "").lower()
            for lang, code in fences:
                if wanted and wanted != "auto" and lang.lower() == wanted:
                    return code.strip()
            return fences[0][1].strip()

        return raw.strip()

    def _eli_v3_generate_script(args=None):
        action_name = "GENERATE_SCRIPT"
        data = _eli_v3_args(args)

        description = (
            data.get("description")
            or data.get("prompt")
            or data.get("task")
            or data.get("query")
            or data.get("message")
            or ""
        )

        if not str(description).strip():
            return _eli_v3_error(action_name, "No script description supplied.")

        language = data.get("language") or "auto"
        if str(language).strip().lower() in {"", "auto", "none"}:
            try:
                from eli.execution.portable_intent_contract import infer_script_language
                language = infer_script_language(description)
            except Exception:
                language = "auto"

        generation_prompt = (
            "Generate only the requested source code. "
            "Do not include markdown commentary unless code fences are unavoidable. "
            f"Requested language: {language}. "
            f"Task: {description}"
        )

        raw = None
        chat_fn = globals().get("chat")
        if callable(chat_fn):
            raw = chat_fn(generation_prompt)

        if raw is None:
            try:
                from eli.cognition import gguf_inference
                raw = gguf_inference.generate(
                    generation_prompt,
                    max_tokens=int(data.get("max_tokens") or 1200),
                )
            except Exception as exc:
                return _eli_v3_error(action_name, f"Script generation backend unavailable: {exc}")

        code = _eli_v3_extract_code(raw, language=language)
        if not code:
            return _eli_v3_error(action_name, "Script generation returned no source code.")

        ext = _eli_v3_language_ext(language)

        if ext == "py":
            try:
                compile(code, "<eli-generated-script>", "exec")
            except SyntaxError as exc:
                return _eli_v3_error(
                    action_name,
                    f"Generated Python script failed syntax validation: {exc}",
                )

        out_dir = _eli_v3_artifacts_dir() / "scripts"
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = _eli_v3_slug(data.get("title") or description)
        path = out_dir / f"{stem}.{ext}"

        if path.exists() and not bool(data.get("overwrite", False)):
            idx = 2
            while True:
                candidate = out_dir / f"{path.stem}_{idx}{path.suffix}"
                if not candidate.exists():
                    path = candidate
                    break
                idx += 1

        path.write_text(code, encoding="utf-8")

        text = f"Script generated: {path}"
        return {
            "ok": True,
            "action": action_name,
            "script_path": str(path),
            "path": str(path),
            "language": language,
            "destination": data.get("destination") or "labs_sim_ide",
            "open_in_labs": bool(data.get("open_in_labs", True)),
            "open_in_ide": bool(data.get("open_in_ide", True)),
            "content": text,
            "response": text,
        }

    if callable(_ELI_PORTABLE_V3_ORIG_EXECUTE):
        def execute(action, args=None, *pargs, **kwargs):
            action_name = _eli_v3_action_name(action)

            direct = _eli_v3_direct_system_action(action, args)
            if direct is not None:
                return direct

            if action_name in {
                "GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT",
                "GENERATE_CODE", "WRITE_CODE",
            }:
                return _eli_v3_generate_script(args)

            return _ELI_PORTABLE_V3_ORIG_EXECUTE(action, args, *pargs, **kwargs)

    if callable(_ELI_PORTABLE_V3_ORIG_EXECUTE_ACTION):
        def execute_action(action, args=None, *pargs, **kwargs):
            action_name = _eli_v3_action_name(action)

            direct = _eli_v3_direct_system_action(action, args)
            if direct is not None:
                return direct

            if action_name in {
                "GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT",
                "GENERATE_CODE", "WRITE_CODE",
            }:
                return _eli_v3_generate_script(args)

            return _ELI_PORTABLE_V3_ORIG_EXECUTE_ACTION(action, args, *pargs, **kwargs)
'''


try:
    restored_router = restore_from_pre_bad_backup("eli/execution/router_enhanced.py")
    restored_executor = restore_from_pre_bad_backup("eli/execution/executor_enhanced.py")

    append_once(ROUTER, "portable_runtime_contract_v3_router_hook", router_hook)
    append_once(EXECUTOR, "portable_runtime_contract_v3_executor_hook", executor_hook)

    for rel in (
        "eli/execution/router_enhanced.py",
        "eli/execution/executor_enhanced.py",
        "eli/execution/portable_intent_contract.py",
        "eli/system/portable_app_control.py",
        "eli/system/__init__.py",
    ):
        path = ROOT / rel
        py_compile.compile(str(path), doraise=True)
        print(f"COMPILE_OK {rel}")

    print(f"RESTORED_ROUTER={restored_router}")
    print(f"RESTORED_EXECUTOR={restored_executor}")
    print("PATCH_RC=0")
except Exception:
    traceback.print_exc()
    print("PATCH_RC=1")
