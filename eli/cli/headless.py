"""Headless terminal REPL for ELI MKXI.

Invoked via:
    python -m eli --headless
    eli --headless
    eli -H

Runs a CognitiveEngine directly without any GUI imports.  Suitable for
scripting, server use, and headless (display-less) environments.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Optional


_BANNER = """
╔══════════════════════════════════════╗
║  ELI MKXI  —  Headless Terminal Mode ║
║  Type your message and press Enter.  ║
║  Commands: /quit  /reset  /status    ║
╚══════════════════════════════════════╝
"""

_HELP = """
Headless commands:
  /quit, /exit, /q   — exit the session
  /reset             — clear the current session and start fresh
  /status            — show engine and hardware status
  /mode <name>       — switch reasoning mode (quick | standard | cot)
  /help              — show this help
"""


def run_headless() -> int:
    """Start the headless REPL.  Returns exit code (0 = clean exit)."""
    # Suppress Qt-related imports by flagging headless environment
    os.environ.setdefault("ELI_HEADLESS", "1")
    os.environ.setdefault("ELI_NO_GUI", "1")

    print(_BANNER)

    # ── Load engine ──────────────────────────────────────────────────────────
    print("Loading ELI engine…", flush=True)
    try:
        from eli.kernel.engine import CognitiveEngine
        engine = CognitiveEngine(auto_init_gguf=True)
        print("Engine ready.\n", flush=True)
    except Exception as exc:
        print(f"[HEADLESS] Failed to initialise engine: {exc}", file=sys.stderr)
        return 1

    session_id = f"headless-{int(time.time())}"
    reasoning_mode = "standard"

    def _process(text: str) -> str:
        try:
            result = engine.process(
                text,
                source="user",
                stream=False,
                reasoning_mode=reasoning_mode,
                session_id=session_id,
            )
            # Normalise: engine.process may return str, dict, or generator
            if isinstance(result, str):
                return result.strip()
            if isinstance(result, dict):
                return (
                    result.get("response")
                    or result.get("content")
                    or result.get("text")
                    or str(result)
                ).strip()
            # Generator — consume all tokens
            tokens = []
            for chunk in result:
                if isinstance(chunk, dict):
                    tokens.append(chunk.get("response") or chunk.get("token") or "")
                elif isinstance(chunk, str):
                    tokens.append(chunk)
            return "".join(tokens).strip()
        except Exception as exc:
            return f"[Error] {exc}"

    # ── REPL loop ────────────────────────────────────────────────────────────
    try:
        while True:
            try:
                raw = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[HEADLESS] Session ended.")
                break

            if not raw:
                continue

            # Built-in slash commands
            low = raw.lower()
            if low in ("/quit", "/exit", "/q"):
                print("[HEADLESS] Goodbye.")
                break
            if low == "/reset":
                session_id = f"headless-{int(time.time())}"
                print("[HEADLESS] Session reset.\n")
                continue
            if low == "/help":
                print(_HELP)
                continue
            if low == "/status":
                status = _process("/status")
                print(f"ELI: {status}\n")
                continue
            if low.startswith("/mode "):
                mode_name = raw[6:].strip().lower()
                valid_modes = {"quick", "standard", "cot", "self_consistency", "tree_of_thoughts"}
                if mode_name in valid_modes:
                    reasoning_mode = mode_name
                    print(f"[HEADLESS] Reasoning mode set to: {reasoning_mode}\n")
                else:
                    print(f"[HEADLESS] Unknown mode '{mode_name}'. Valid: {', '.join(sorted(valid_modes))}\n")
                continue

            # Normal message
            response = _process(raw)
            print(f"ELI: {response}\n")

    finally:
        try:
            engine.shutdown()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(run_headless())
