#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import re
import time

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")
orig = src

marker = "ELI_RUNTIME_STATUS_NONQUICK_STRICT_NO_RAW_GGUF_V3"
if marker in src:
    print(f"[PATCH] {marker} already installed")
    raise SystemExit(0)

old = '''                if _eli_v8_mw_mode == "quick":
                    return _eli_v8_runtime_status_response(user_input, "quick")

                print(
                    "[ENGINE] RUNTIME_STATUS non-quick: direct v8 surface suppressed; continuing through synthesis pipeline",
                    flush=True,
                )
'''

new = '''                if _eli_v8_mw_mode == "quick":
                    return _eli_v8_runtime_status_response(user_input, "quick")

                # ELI_RUNTIME_STATUS_NONQUICK_STRICT_NO_RAW_GGUF_V3
                #
                # Runtime-status is telemetry, not an open-ended reasoning task.
                # Quick mode already returns the compact grounded evidence surface.
                # Non-Quick modes must still be mode-labelled and grounded, but must
                # not send this request through GGUF candidate generation because the
                # raw discarded candidates repeatedly invent unsupported runtime
                # claims. The returned surface is the canonical runtime-status
                # contract, not a freeform/raw model answer.
                try:
                    print(
                        "[ENGINE] RUNTIME_STATUS non-quick: strict grounded contract returned; raw GGUF candidates skipped",
                        flush=True,
                    )
                    _eli_rs_out = _eli_v8_runtime_status_response(user_input, _eli_v8_mw_mode)

                    if isinstance(_eli_rs_out, dict):
                        _eli_rs_out = dict(_eli_rs_out)
                        _eli_rs_report = dict(_eli_rs_out.get("report") or {})
                        _eli_rs_report["requested_mode"] = _eli_v8_mw_mode
                        _eli_rs_report["quick_direct_allowed"] = False
                        _eli_rs_report["gguf_used_for_runtime_status_synthesis"] = False
                        _eli_rs_report["raw_gguf_candidates_skipped"] = True
                        _eli_rs_report["response_surface"] = (
                            "non-Quick canonical grounded runtime-status contract; "
                            "raw GGUF candidate generation skipped for telemetry hygiene"
                        )
                        _eli_rs_report["repair_reason"] = (
                            "runtime_status_nonquick_strict_grounded_no_raw_gguf"
                        )
                        _eli_rs_report["synthesis_validated"] = True
                        _eli_rs_out["report"] = _eli_rs_report
                        _eli_rs_out["evidence_source"] = (
                            "runtime_status_nonquick_strict_grounded_no_raw_gguf_v3"
                        )
                        _eli_rs_out["source"] = (
                            "runtime_status_nonquick_strict_grounded_no_raw_gguf_v3"
                        )
                        _eli_rs_out["action"] = "RUNTIME_STATUS"
                        _eli_rs_out["grounded"] = True
                        _eli_rs_out["evidence_used"] = True

                    return _eli_rs_out

                except Exception as _eli_rs_strict_err:
                    print(
                        f"[ENGINE][WARN] runtime-status strict no-raw path failed: {_eli_rs_strict_err}; falling through",
                        flush=True,
                    )

                print(
                    "[ENGINE] RUNTIME_STATUS non-quick: direct v8 surface suppressed; continuing through synthesis pipeline",
                    flush=True,
                )
'''

if old not in src:
    print("[PATCH] exact block not found; dumping nearby context")
    needle = "RUNTIME_STATUS non-quick: direct v8 surface suppressed"
    i = src.find(needle)
    if i >= 0:
        start = max(0, i - 900)
        end = min(len(src), i + 900)
        print(src[start:end])
    raise SystemExit(1)

src = src.replace(old, new, 1)

backup = p.with_suffix(f".py.bak_runtime_status_no_raw_v3_{time.strftime('%Y%m%d_%H%M%S')}")
backup.write_text(orig, encoding="utf-8")
p.write_text(src, encoding="utf-8")

print(f"[PATCH] installed {marker}")
print(f"[PATCH] backup: {backup}")
PY

python3 -m py_compile eli/kernel/engine.py
grep -n "ELI_RUNTIME_STATUS_NONQUICK_STRICT_NO_RAW_GGUF_V3" eli/kernel/engine.py
