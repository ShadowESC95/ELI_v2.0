from pathlib import Path
import py_compile
import re
import traceback

ROOT = Path.cwd()
ROUTER = ROOT / "eli/execution/router_enhanced.py"
EXECUTOR = ROOT / "eli/execution/executor_enhanced.py"


def append_once(path: Path, marker: str, block: str) -> None:
    src = path.read_text(encoding="utf-8", errors="replace")
    if marker in src:
        print(f"UNCHANGED {path.relative_to(ROOT)} marker={marker}")
        return
    path.write_text(src.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")
    print(f"PATCHED {path.relative_to(ROOT)} marker={marker}")


def remove_obvious_target_router_cases(path: Path) -> None:
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines(keepends=True)
    kill_markers = (
        "open spotify",
        "spotify open",
        "open_settings_direct",
        "system.settings",
        "OPEN_SYSTEM_SETTINGS",
    )

    changed = False
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if any(marker in line for marker in kill_markers):
            start = i
            while start > 0:
                s = lines[start].lstrip()
                if s.startswith(("if ", "elif ")):
                    break
                start -= 1

            base_indent = len(lines[start]) - len(lines[start].lstrip())
            end = i + 1
            while end < len(lines):
                stripped = lines[end].strip()
                indent = len(lines[end]) - len(lines[end].lstrip())
                if stripped and indent <= base_indent and not stripped.startswith(("#", ")", "}", "]")):
                    break
                end += 1

            print(f"REMOVED_TARGET_SPECIFIC_ROUTER_BLOCK lines={start+1}-{end}")
            if out and out[-1].strip():
                out.append("\n")
            i = end
            changed = True
            continue

        out.append(line)
        i += 1

    if changed:
        path.write_text("".join(out), encoding="utf-8")
    else:
        print("NO_TARGET_SPECIFIC_ROUTER_BLOCK_REMOVED")


router_hook = '''
# portable_runtime_contract_v2_router_hook
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
# portable_runtime_contract_v2_executor_hook
try:
    _ELI_PORTABLE_V2_ORIG_EXECUTE
except NameError:
    _ELI_PORTABLE_V2_ORIG_EXECUTE = globals().get("execute")
    _ELI_PORTABLE_V2_ORIG_EXECUTE_ACTION = globals().get("execute_action")

    def _eli_portable_v2_action_name(action):
        return str(action or "").strip().upper().replace("-", "_")

    def _eli_portable_v2_args(args):
        return args if isinstance(args, dict) else {}

    def _eli_portable_v2_direct(action, args=None):
        action_name = _eli_portable_v2_action_name(action)
        data = _eli_portable_v2_args(args)

        if action_name in {"OPEN_APP", "LAUNCH_APP", "OPEN_APPLICATION"}:
            from eli.system.portable_app_control import open_app
            return open_app(data.get("name") or data.get("target") or data.get("app") or "")

        if action_name in {"CLOSE_APP", "QUIT_APP", "EXIT_APP", "CLOSE_APPLICATION"}:
            from eli.system.portable_app_control import close_app
            return close_app(
                data.get("name") or data.get("target") or data.get("app") or "",
                force=bool(data.get("force", False)),
            )

        if action_name in {"MINIMIZE_APP", "MINIMISE_APP", "HIDE_APP", "MINIMIZE_WINDOW", "MINIMISE_WINDOW"}:
            from eli.system.portable_app_control import minimize_app
            return minimize_app(data.get("name") or data.get("target") or data.get("app") or "")

        return None

    def _eli_portable_v2_result_error(action_name, text):
        return {
            "ok": False,
            "action": action_name,
            "error": str(text),
            "content": str(text),
            "response": str(text),
            "evidence": [str(text)],
        }

    def _eli_portable_v2_project_root():
        from pathlib import Path
        import os
        env_root = os.environ.get("ELI_PROJECT_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()
        return Path(__file__).resolve().parents[2]

    def _eli_portable_v2_artifacts_dir():
        import os
        from pathlib import Path
        root = _eli_portable_v2_project_root()
        env_dir = os.environ.get("ELI_ARTIFACTS_DIR")
        if env_dir:
            p = Path(env_dir).expanduser()
            return p.resolve() if p.is_absolute() else (root / p).resolve()
        return (root / "artifacts").resolve()

    def _eli_portable_v2_slug(text, default="generated_script"):
        import re
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text or "").strip()).strip("._-")
        return slug[:80] or default

    def _eli_portable_v2_language_ext(language):
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

    def _eli_portable_v2_extract_code(raw, language="auto"):
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
                if wanted and wanted != "auto" and lang.lower() in {wanted, wanted.replace("+", "p")}:
                    return code.strip()
            return fences[0][1].strip()

        return raw.strip()

    def _eli_portable_v2_generate_script(args=None):
        action_name = "GENERATE_SCRIPT"
        data = _eli_portable_v2_args(args)
        description = data.get("description") or data.get("prompt") or data.get("task") or data.get("query") or ""
        language = data.get("language") or "auto"

        if not str(description).strip():
            return _eli_portable_v2_result_error(action_name, "No script description supplied.")

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
                raw = gguf_inference.generate(generation_prompt, max_tokens=int(data.get("max_tokens") or 1200))
            except Exception as exc:
                return _eli_portable_v2_result_error(action_name, f"Script generation backend unavailable: {exc}")

        code = _eli_portable_v2_extract_code(raw, language=language)
        if not code:
            return _eli_portable_v2_result_error(action_name, "Script generation returned no source code.")

        ext = _eli_portable_v2_language_ext(language)
        if ext == "py":
            try:
                compile(code, "<eli-generated-script>", "exec")
            except SyntaxError as exc:
                return _eli_portable_v2_result_error(
                    action_name,
                    f"Generated Python script failed syntax validation: {exc}",
                )

        out_dir = _eli_portable_v2_artifacts_dir() / "scripts"
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = _eli_portable_v2_slug(data.get("title") or description)
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

    if callable(_ELI_PORTABLE_V2_ORIG_EXECUTE):
        def execute(action, args=None, *pargs, **kwargs):
            action_name = _eli_portable_v2_action_name(action)
            direct = _eli_portable_v2_direct(action, args)
            if direct is not None:
                return direct
            if action_name in {"GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT", "GENERATE_CODE", "WRITE_CODE"}:
                return _eli_portable_v2_generate_script(args)
            return _ELI_PORTABLE_V2_ORIG_EXECUTE(action, args, *pargs, **kwargs)

    if callable(_ELI_PORTABLE_V2_ORIG_EXECUTE_ACTION):
        def execute_action(action, args=None, *pargs, **kwargs):
            action_name = _eli_portable_v2_action_name(action)
            direct = _eli_portable_v2_direct(action, args)
            if direct is not None:
                return direct
            if action_name in {"GENERATE_SCRIPT", "CREATE_SCRIPT", "WRITE_SCRIPT", "GENERATE_CODE", "WRITE_CODE"}:
                return _eli_portable_v2_generate_script(args)
            return _ELI_PORTABLE_V2_ORIG_EXECUTE_ACTION(action, args, *pargs, **kwargs)
'''

try:
    remove_obvious_target_router_cases(ROUTER)
    append_once(ROUTER, "portable_runtime_contract_v2_router_hook", router_hook)
    append_once(EXECUTOR, "portable_runtime_contract_v2_executor_hook", executor_hook)

    for rel in (
        "eli/system/__init__.py",
        "eli/system/portable_app_control.py",
        "eli/execution/portable_intent_contract.py",
        "eli/execution/router_enhanced.py",
        "eli/execution/executor_enhanced.py",
    ):
        path = ROOT / rel
        py_compile.compile(str(path), doraise=True)
        print(f"COMPILE_OK {rel}")

    print("PATCH_RC=0")
except Exception:
    traceback.print_exc()
    print("PATCH_RC=1")
