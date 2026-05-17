from pathlib import Path
import py_compile
import shutil
import time
import traceback

ROOT = Path.cwd()
STAMP = time.strftime("%Y%m%d_%H%M%S")
BACKUP = ROOT / "ops" / "backups" / f"{STAMP}.voice_runtime_contract_fix"
BACKUP.mkdir(parents=True, exist_ok=True)

ROUTER = ROOT / "eli/execution/router_enhanced.py"
EXECUTOR = ROOT / "eli/execution/executor_enhanced.py"

def backup(path: Path):
    if path.exists():
        dst = BACKUP / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)
        print(f"BACKUP {path.relative_to(ROOT)} -> {dst}")
    else:
        print(f"MISSING {path.relative_to(ROOT)}")

def append_once(path: Path, marker: str, block: str):
    src = path.read_text(encoding="utf-8", errors="replace")
    if marker in src:
        print(f"UNCHANGED {path.relative_to(ROOT)} marker already present: {marker}")
        return
    path.write_text(src.rstrip() + "\n\n" + block.strip() + "\n", encoding="utf-8")
    print(f"PATCHED {path.relative_to(ROOT)} marker={marker}")

def compile_report(path: Path):
    try:
        py_compile.compile(str(path), doraise=True)
        print(f"COMPILE_OK {path.relative_to(ROOT)}")
        return 0
    except Exception as exc:
        print(f"COMPILE_BAD {path.relative_to(ROOT)}: {exc}")
        traceback.print_exc()
        return 1

for p in (ROUTER, EXECUTOR):
    backup(p)

router_block = r'''
# voice_runtime_contract_guard
# Deterministic voice-command grammar for common local-control requests.
# This layer fixes ASR wording variants before the broad tiny-fragment/fallback
# chat guards see them. It contains no user-machine absolute paths.

def _eli_voice_contract_text_from_call(args, kwargs):
    for item in args:
        if isinstance(item, str) and item.strip():
            return item
    for key in ("text", "message", "command", "prompt", "query", "utterance"):
        item = kwargs.get(key)
        if isinstance(item, str) and item.strip():
            return item
    return ""

def _eli_voice_contract_norm(text):
    import re
    text = str(text or "").lower()
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace(" per cent", "%").replace(" percent", "%")
    text = re.sub(r"[^a-z0-9%'\s]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def _eli_voice_contract_response(message, matched_by):
    return {
        "action": "NOOP",
        "args": {
            "message": message,
            "response": message,
            "content": message,
        },
        "confidence": 0.999,
        "meta": {"matched_by": matched_by},
    }

def _eli_voice_contract_route(text):
    import re

    raw = str(text or "").strip()
    norm = _eli_voice_contract_norm(raw)
    if not norm:
        return None

    # Absolute volume: "volume 80", "volume 80%", "set volume to 80".
    m = re.fullmatch(r"(?:set\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?", norm)
    if m:
        level = max(0, min(100, int(m.group(1))))
        return {
            "action": "VOLUME",
            "args": {"level": level, "percent": level, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {
                "matched_by": "voice_runtime_contract.volume_absolute",
                "normalized": f"volume {level}%",
            },
        }

    if re.fullmatch(r"volume\s+(?:max|maximum|full)", norm):
        return {
            "action": "VOLUME",
            "args": {"level": 100, "percent": 100, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "voice_runtime_contract.volume_maximum"},
        }

    if re.fullmatch(r"volume\s+(?:off|zero|mute)", norm):
        return {
            "action": "VOLUME",
            "args": {"level": 0, "percent": 0, "mode": "absolute"},
            "confidence": 0.999,
            "meta": {"matched_by": "voice_runtime_contract.volume_zero"},
        }

    # Keep "open settings" on the direct-execution path. Do not send this to
    # cognition/broker after the OS action has already succeeded.
    if re.fullmatch(r"(?:open|launch|show)\s+(?:system\s+)?settings", norm):
        return {
            "action": "OPEN_APP",
            "args": {"name": "settings", "app": "settings"},
            "confidence": 0.999,
            "meta": {
                "matched_by": "voice_runtime_contract.open_settings_direct",
                "normalized": "open settings",
            },
        }

    # ASR variants for "May the Fourth" / "May the Force".
    may_fourth = (
        re.search(r"\bmay\s+(?:the\s+)?(?:4th|fourth|forth|fort|force|default)\b", norm)
        or re.search(r"\b(?:4th|fourth|forth|fort)\s+of\s+may\b", norm)
        or "fort of may" in norm
        or "fort fou or th" in norm
        or "made of fort" in norm
        or "fort be with you" in norm
        or "force be with you" in norm
    )
    if may_fourth:
        msg = (
            "You mean May the Fourth. Its significance is Star Wars Day: "
            "a pun on “May the Force be with you.”"
        )
        return _eli_voice_contract_response(msg, "voice_runtime_contract.may_fourth_asr_normalised")

    return None

def _eli_voice_contract_wrap_callable(fn):
    if not callable(fn) or getattr(fn, "_eli_voice_contract_wrapped", False):
        return fn

    def _wrapped(*args, **kwargs):
        shortcut = _eli_voice_contract_route(_eli_voice_contract_text_from_call(args, kwargs))
        if shortcut is not None:
            return shortcut
        return fn(*args, **kwargs)

    try:
        _wrapped.__name__ = getattr(fn, "__name__", "_wrapped")
        _wrapped.__doc__ = getattr(fn, "__doc__", None)
        _wrapped._eli_voice_contract_wrapped = True
    except Exception:
        pass
    return _wrapped

_eli_voice_contract_route_names = (
    "route",
    "route_text",
    "route_command",
    "route_intent",
    "parse",
    "parse_intent",
    "parse_command",
    "classify",
    "classify_intent",
)

for _name in _eli_voice_contract_route_names:
    _fn = globals().get(_name)
    if callable(_fn) and _fn is not _eli_voice_contract_route:
        globals()[_name] = _eli_voice_contract_wrap_callable(_fn)

for _obj in list(globals().values()):
    if isinstance(_obj, type):
        for _name in _eli_voice_contract_route_names:
            try:
                _method = getattr(_obj, _name, None)
                if callable(_method):
                    setattr(_obj, _name, _eli_voice_contract_wrap_callable(_method))
            except Exception:
                pass
'''

executor_block = r'''
# voice_runtime_executor_contract_guard
# Stable execution support for direct voice rules. Uses commands discovered
# through PATH and platform APIs; no absolute user-machine paths.

try:
    _ELI_VOICE_CONTRACT_ORIG_EXECUTE
except NameError:
    _ELI_VOICE_CONTRACT_ORIG_EXECUTE = globals().get("execute")
    _ELI_VOICE_CONTRACT_ORIG_EXECUTE_ACTION = globals().get("execute_action")

    def _eli_voice_contract_action_name(action):
        return str(action or "").strip().upper().replace("-", "_")

    def _eli_voice_contract_arg_text(args, *keys):
        if not isinstance(args, dict):
            return ""
        for key in keys:
            val = args.get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""

    def _eli_voice_contract_open_settings():
        import os
        import platform
        import shutil
        import subprocess
        import sys

        system = platform.system().lower()

        if system == "linux":
            candidates = (
                "gnome-control-center",
                "systemsettings",
                "xfce4-settings-manager",
                "mate-control-center",
                "cinnamon-settings",
            )
            for cmd in candidates:
                resolved = shutil.which(cmd)
                if resolved:
                    subprocess.Popen(
                        [resolved],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                    return {
                        "ok": True,
                        "action": "OPEN_SYSTEM_SETTINGS",
                        "content": f"Opened system settings: {cmd}",
                        "response": f"Opened system settings: {cmd}",
                    }

        if system == "darwin":
            subprocess.Popen(
                ["open", "-b", "com.apple.systempreferences"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return {
                "ok": True,
                "action": "OPEN_SYSTEM_SETTINGS",
                "content": "Opened system settings.",
                "response": "Opened system settings.",
            }

        if system == "windows":
            try:
                os.startfile("ms-settings:")
                return {
                    "ok": True,
                    "action": "OPEN_SYSTEM_SETTINGS",
                    "content": "Opened system settings.",
                    "response": "Opened system settings.",
                }
            except Exception:
                pass

        return {
            "ok": False,
            "action": "OPEN_SYSTEM_SETTINGS",
            "error": "No supported system settings launcher was found on PATH.",
            "content": "No supported system settings launcher was found on PATH.",
            "response": "No supported system settings launcher was found on PATH.",
        }

    def _eli_voice_contract_set_volume(percent):
        import platform
        import shutil
        import subprocess

        level = max(0, min(100, int(percent)))
        system = platform.system().lower()

        if system == "linux":
            pactl = shutil.which("pactl")
            if pactl:
                subprocess.run(
                    [pactl, "set-sink-mute", "@DEFAULT_SINK@", "0"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                rc = subprocess.run(
                    [pactl, "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                if rc == 0:
                    return {
                        "ok": True,
                        "action": "VOLUME",
                        "content": f"Volume set to {level}%",
                        "response": f"Volume set to {level}%",
                    }

            amixer = shutil.which("amixer")
            if amixer:
                rc = subprocess.run(
                    [amixer, "-D", "pulse", "sset", "Master", f"{level}%"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                if rc == 0:
                    return {
                        "ok": True,
                        "action": "VOLUME",
                        "content": f"Volume set to {level}%",
                        "response": f"Volume set to {level}%",
                    }

        if system == "darwin":
            rc = subprocess.run(
                ["osascript", "-e", f"set volume output volume {level}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            ).returncode
            if rc == 0:
                return {
                    "ok": True,
                    "action": "VOLUME",
                    "content": f"Volume set to {level}%",
                    "response": f"Volume set to {level}%",
                }

        return None

    def _eli_voice_contract_direct_result(action, args):
        action_name = _eli_voice_contract_action_name(action)
        args = args if isinstance(args, dict) else {}

        if action_name in {"NOOP", "SAY", "DIRECT_RESPONSE", "ANSWER"}:
            msg = (
                args.get("message")
                or args.get("response")
                or args.get("content")
                or ""
            )
            return {
                "ok": True,
                "action": action_name,
                "content": str(msg),
                "response": str(msg),
            }

        app_name = _eli_voice_contract_arg_text(args, "name", "app", "target", "application").lower()
        if action_name == "OPEN_SYSTEM_SETTINGS" or (
            action_name in {"OPEN_APP", "OPEN_APPLICATION", "LAUNCH_APP"}
            and app_name in {"settings", "system settings", "gnome settings"}
        ):
            return _eli_voice_contract_open_settings()

        if action_name == "VOLUME":
            level = args.get("level", args.get("percent", args.get("value")))
            if level is not None:
                try:
                    result = _eli_voice_contract_set_volume(int(level))
                    if result is not None:
                        return result
                except Exception as exc:
                    return {
                        "ok": False,
                        "action": "VOLUME",
                        "error": f"Volume set failed: {exc}",
                        "content": f"Volume set failed: {exc}",
                        "response": f"Volume set failed: {exc}",
                    }

        return None

    if callable(_ELI_VOICE_CONTRACT_ORIG_EXECUTE):
        def execute(action, args=None, *pargs, **kwargs):
            direct = _eli_voice_contract_direct_result(action, args)
            if direct is not None:
                return direct
            return _ELI_VOICE_CONTRACT_ORIG_EXECUTE(action, args, *pargs, **kwargs)

    if callable(_ELI_VOICE_CONTRACT_ORIG_EXECUTE_ACTION):
        def execute_action(action, args=None, *pargs, **kwargs):
            direct = _eli_voice_contract_direct_result(action, args)
            if direct is not None:
                return direct
            return _ELI_VOICE_CONTRACT_ORIG_EXECUTE_ACTION(action, args, *pargs, **kwargs)
'''

append_once(ROUTER, "voice_runtime_contract_guard", router_block)
append_once(EXECUTOR, "voice_runtime_executor_contract_guard", executor_block)

rc = 0
for p in (ROUTER, EXECUTOR):
    rc |= compile_report(p)

print(f"BACKUP={BACKUP}")
print(f"PATCH_RC={rc}")
