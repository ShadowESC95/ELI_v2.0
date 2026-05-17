from pathlib import Path

p = Path("eli/kernel/engine.py")
s = p.read_text()

old = '''            print("[COGNITIVE] Stream: Stage 11 primary path yielded zero visible tokens")
        except Exception as _stage11_err:
            print(f"[COGNITIVE] Stream Stage 11 primary failed: {_stage11_err}")

        # 5. Same-dispatch direct GGUF fallback. This is not a GUI rerun and does
        #    not re-dispatch AgentBus/process().
        try:
            print("[COGNITIVE] Stream: direct gguf fallback path")
'''

new = '''            print("[COGNITIVE] Stream: Stage 11 primary path yielded zero visible tokens")

            _mode_now = str(reasoning_mode or "quick").strip().lower()
            if _mode_now not in {"quick", "fast", "direct"}:
                _fault = (
                    "Internal cognition-pipeline fault: Stage 11 produced zero visible tokens while "
                    f"reasoning_mode={_mode_now}. I am blocking direct GGUF fallback because this is a "
                    "non-Quick mode. The correct path is router → AgentBus plan → memory/context grounding "
                    "→ Stage 11 synthesis → governor. Current failure point: generate_stream_from_assembled_prompt "
                    "returned no visible chunks."
                )
                yield _fault
                try:
                    self._store_assistant_turn(_fault)
                except Exception:
                    pass
                print(f"[COGNITIVE][TIMING] stream_total={_time.perf_counter() - started:.3f}s")
                return

        except Exception as _stage11_err:
            print(f"[COGNITIVE] Stream Stage 11 primary failed: {_stage11_err}")
            _mode_now = str(reasoning_mode or "quick").strip().lower()
            if _mode_now not in {"quick", "fast", "direct"}:
                _fault = (
                    "Internal cognition-pipeline fault: Stage 11 raised an exception in a non-Quick mode. "
                    f"reasoning_mode={_mode_now}; error={_stage11_err}. Direct GGUF fallback blocked."
                )
                yield _fault
                return

        # 5. Same-dispatch direct GGUF fallback. QUICK MODE ONLY.
        try:
            _mode_now = str(reasoning_mode or "quick").strip().lower()
            if _mode_now not in {"quick", "fast", "direct"}:
                print(f"[COGNITIVE] Direct GGUF fallback blocked for non-Quick mode: {_mode_now}")
                return

            print("[COGNITIVE] Stream: direct gguf fallback path")
'''

if old not in s:
    raise SystemExit("Could not find exact Stage 11 fallback block.")

s = s.replace(old, new, 1)
p.write_text(s)
