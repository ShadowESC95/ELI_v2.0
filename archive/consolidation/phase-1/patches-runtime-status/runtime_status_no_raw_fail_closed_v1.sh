#!/usr/bin/env bash
set -euo pipefail

cd ~/Desktop/ELI_MKXI || exit 1
source .venv/bin/activate || true

python3 - <<'PY'
from pathlib import Path
import time

p = Path("eli/kernel/engine.py")
src = p.read_text(encoding="utf-8")
orig = src

marker = "ELI_RUNTIME_STATUS_NO_RAW_FAIL_CLOSED_V1"
if marker in src:
    print(f"[PATCH] {marker} already installed")
    raise SystemExit(0)

old = '''                except Exception as _eli_rs_strict_err:
                    print(
                        f"[ENGINE][WARN] runtime-status strict no-raw path failed: {_eli_rs_strict_err}; falling through",
                        flush=True,
                    )

                print(
                    "[ENGINE] RUNTIME_STATUS non-quick: direct v8 surface suppressed; continuing through synthesis pipeline",
                    flush=True,
                )
'''

new = '''                except Exception as _eli_rs_strict_err:
                    # ELI_RUNTIME_STATUS_NO_RAW_FAIL_CLOSED_V1
                    #
                    # Runtime-status telemetry must never fall through to raw GGUF
                    # synthesis if the strict no-raw path fails. Returning a small
                    # deterministic failure surface is safer than allowing fabricated
                    # runtime claims.
                    _eli_rs_fail_msg = (
                        "Runtime-status strict no-raw telemetry path failed before "
                        "canonical evidence could be built. Refusing to fall through "
                        "to GGUF synthesis."
                    )
                    print(
                        f"[ENGINE][WARN] runtime-status strict no-raw path failed closed: {_eli_rs_strict_err}",
                        flush=True,
                    )
                    return {
                        "ok": False,
                        "action": "RUNTIME_STATUS",
                        "source": "runtime_status_nonquick_strict_grounded_no_raw_gguf_v3_fail_closed",
                        "evidence_source": "runtime_status_nonquick_strict_grounded_no_raw_gguf_v3_fail_closed",
                        "grounded": True,
                        "evidence_used": True,
                        "response": _eli_rs_fail_msg,
                        "content": _eli_rs_fail_msg,
                        "report": {
                            "ok": False,
                            "requested_mode": _eli_v8_mw_mode,
                            "quick_direct_allowed": False,
                            "gguf_used_for_runtime_status_synthesis": False,
                            "raw_gguf_candidates_skipped": True,
                            "synthesis_validated": False,
                            "repair_reason": "strict_no_raw_runtime_status_failed_closed",
                            "error": str(_eli_rs_strict_err),
                        },
                    }

                print(
                    "[ENGINE] RUNTIME_STATUS non-quick: direct v8 surface suppressed; continuing through synthesis pipeline",
                    flush=True,
                )
'''

if old not in src:
    raise SystemExit("[PATCH] target fail-open runtime-status except block not found")

src = src.replace(old, new, 1)

backup = p.with_suffix(p.suffix + f".bak_runtime_status_fail_closed_{time.strftime('%Y%m%d_%H%M%S')}")
backup.write_text(orig, encoding="utf-8")
p.write_text(src, encoding="utf-8")

print(f"[PATCH] installed {marker}")
print(f"[PATCH] backup: {backup}")
PY
