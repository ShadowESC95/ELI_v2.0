#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase11_multipdf_route_executor_contract_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

changed = []


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_with_backup(path: Path, text: str) -> None:
    backup = OUT / (str(path.relative_to(ROOT)).replace("/", "__") + ".before")
    backup.write_text(read(path), encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    changed.append(str(path.relative_to(ROOT)))


# ---------------------------------------------------------------------
# 1. Router: post-process ANALYZE_PDF routes so multi-PDF prompts expose paths[]
# ---------------------------------------------------------------------

router = ROOT / "eli/execution/router_enhanced.py"
src = read(router)

router_block = r'''

# --- Phase 11: multi-PDF route contract wrapper -----------------------
# Purpose:
#   Existing route branches call _extract_pdf_path(raw), which returns only the
#   first PDF. Phase 10 added _extract_pdf_paths(raw). This wrapper preserves
#   existing route behaviour while enriching ANALYZE_PDF args with paths=[...].
try:
    if not globals().get("_ELI_PHASE11_MULTIPDF_ROUTE_INSTALLED"):
        _ELI_PHASE11_MULTIPDF_ROUTE_INSTALLED = True

        _eli_phase11_prev_route = route
        _eli_phase11_prev_route_intent = route_intent

        def _eli_phase11_enrich_pdf_route(raw, result):
            try:
                if not isinstance(result, dict):
                    return result

                action = str(result.get("action") or "").upper().strip()
                if action != "ANALYZE_PDF":
                    return result

                args = result.setdefault("args", {})
                if not isinstance(args, dict):
                    return result

                text = str(raw or "")
                if ".pdf" not in text.lower():
                    return result

                paths = []
                try:
                    paths = list(_extract_pdf_paths(text))
                except Exception:
                    paths = []

                if not paths:
                    return result

                args["path"] = str(args.get("path") or paths[0])
                args["paths"] = paths

                meta = result.setdefault("meta", {})
                if isinstance(meta, dict):
                    entities = meta.setdefault("entities", {})
                    if isinstance(entities, dict):
                        entities["path"] = args["path"]
                        entities["paths"] = paths
                    meta["multipdf_count"] = len(paths)
                    meta["matched_by"] = str(meta.get("matched_by") or "analyze.pdf") + "+phase11_multipdf"

                return result
            except Exception:
                return result

        def route(raw, *args, **kwargs):  # type: ignore[no-redef]
            return _eli_phase11_enrich_pdf_route(
                raw,
                _eli_phase11_prev_route(raw, *args, **kwargs),
            )

        def route_intent(raw, *args, **kwargs):  # type: ignore[no-redef]
            return _eli_phase11_enrich_pdf_route(
                raw,
                _eli_phase11_prev_route_intent(raw, *args, **kwargs),
            )

        print("[ROUTER] Phase 11 multi-PDF route contract installed", flush=True)

except Exception as _eli_phase11_multipdf_route_err:
    print(f"[ROUTER] Phase 11 multi-PDF route contract failed: {_eli_phase11_multipdf_route_err}", flush=True)
'''

if "_ELI_PHASE11_MULTIPDF_ROUTE_INSTALLED" not in src:
    write_with_backup(router, src.rstrip() + "\n" + router_block + "\n")


# ---------------------------------------------------------------------
# 2. Executor: if ANALYZE_PDF receives paths[], run the existing single-PDF
#    executor once per path and aggregate the visible result.
# ---------------------------------------------------------------------

executor = ROOT / "eli/execution/executor_enhanced.py"
src = read(executor)

executor_block = r'''

# --- Phase 11: multi-PDF executor contract wrapper --------------------
# Purpose:
#   Preserve the existing ANALYZE_PDF implementation, but support args["paths"]
#   by invoking the existing single-PDF path once per file.
try:
    if not globals().get("_ELI_PHASE11_MULTIPDF_EXECUTOR_INSTALLED"):
        _ELI_PHASE11_MULTIPDF_EXECUTOR_INSTALLED = True

        _eli_phase11_prev_execute = execute

        def _eli_phase11_action_and_params(call_args, call_kwargs):
            action = None
            params = None

            if call_args:
                first = call_args[0]
                if isinstance(first, dict):
                    action = first.get("action")
                    params = first.get("args") or first.get("params") or {}
                else:
                    action = first
                    if len(call_args) >= 2 and isinstance(call_args[1], dict):
                        params = call_args[1]
                    else:
                        params = call_kwargs.get("args") or call_kwargs.get("params") or {}

            if action is None:
                action = call_kwargs.get("action")
            if params is None:
                params = call_kwargs.get("args") or call_kwargs.get("params") or {}

            return str(action or "").upper().strip(), dict(params or {})

        def _eli_phase11_replace_params(call_args, call_kwargs, new_params):
            call_args = list(call_args)
            call_kwargs = dict(call_kwargs)

            if call_args:
                first = call_args[0]
                if isinstance(first, dict):
                    new_first = dict(first)
                    new_first["args"] = new_params
                    call_args[0] = new_first
                else:
                    if len(call_args) >= 2 and isinstance(call_args[1], dict):
                        call_args[1] = new_params
                    else:
                        call_args.insert(1, new_params)
            else:
                call_kwargs["args"] = new_params

            return tuple(call_args), call_kwargs

        def _eli_phase11_clean_paths(paths):
            if isinstance(paths, str):
                raw = [p.strip() for p in paths.split(",")]
            elif isinstance(paths, (list, tuple, set)):
                raw = list(paths)
            else:
                raw = []

            out = []
            seen = set()
            for p in raw:
                s = str(p or "").strip()
                if not s:
                    continue
                if s not in seen:
                    seen.add(s)
                    out.append(s)
            return out

        def _eli_phase11_format_multipdf_result(results, paths):
            lines = [
                f"Multi-PDF analysis completed for {len(paths)} file(s).",
                "",
            ]

            ok_count = 0
            fail_count = 0

            for idx, (path, res) in enumerate(zip(paths, results), 1):
                ok = bool(isinstance(res, dict) and res.get("ok"))
                if ok:
                    ok_count += 1
                else:
                    fail_count += 1

                status = "OK" if ok else "FAILED"
                lines.append(f"## {idx}. {Path(path).name} — {status}")
                lines.append(f"Source: `{path}`")

                if isinstance(res, dict):
                    saved_to = res.get("saved_to")
                    pages = res.get("pages")
                    chars = res.get("chars")
                    err = res.get("error")
                    response = res.get("response") or res.get("content") or ""

                    if pages is not None or chars is not None:
                        lines.append(f"Pages: {pages} | Characters: {chars}")
                    if saved_to:
                        lines.append(f"Saved to: `{saved_to}`")
                    if err:
                        lines.append(f"Error: {err}")
                    if response:
                        lines.append("")
                        lines.append(str(response))
                else:
                    lines.append(f"Unexpected executor result type: {type(res).__name__}")

                lines.append("")

            lines.insert(1, f"Successful: {ok_count} | Failed: {fail_count}")
            return "\n".join(lines).strip()

        def execute(*call_args, **call_kwargs):  # type: ignore[no-redef]
            action, params = _eli_phase11_action_and_params(call_args, call_kwargs)

            if action == "ANALYZE_PDF":
                paths = _eli_phase11_clean_paths(params.get("paths"))
                if len(paths) > 1:
                    results = []
                    instruction = str(params.get("instruction") or "").strip()

                    for p in paths:
                        one_params = dict(params)
                        one_params["path"] = p
                        one_params.pop("paths", None)
                        if instruction:
                            one_params["instruction"] = instruction

                        n_args, n_kwargs = _eli_phase11_replace_params(
                            call_args,
                            call_kwargs,
                            one_params,
                        )
                        try:
                            res = _eli_phase11_prev_execute(*n_args, **n_kwargs)
                        except Exception as e:
                            res = {
                                "ok": False,
                                "action": "ANALYZE_PDF",
                                "path": p,
                                "error": f"{type(e).__name__}: {e}",
                                "content": f"ANALYZE_PDF failed for {p}: {type(e).__name__}: {e}",
                                "response": f"ANALYZE_PDF failed for {p}: {type(e).__name__}: {e}",
                            }
                        results.append(res)

                    all_ok = all(isinstance(r, dict) and r.get("ok") for r in results)
                    content = _eli_phase11_format_multipdf_result(results, paths)
                    return {
                        "ok": all_ok,
                        "action": "ANALYZE_PDF",
                        "paths": paths,
                        "results": results,
                        "content": content,
                        "response": content,
                        "response_mode": "phase11_multipdf_aggregated_executor_result",
                    }

            return _eli_phase11_prev_execute(*call_args, **call_kwargs)

        try:
            Executor.execute = lambda self, *a, **kw: execute(*a, **kw)  # type: ignore[name-defined]
        except Exception:
            pass

        print("[EXECUTOR] Phase 11 multi-PDF executor contract installed", flush=True)

except Exception as _eli_phase11_multipdf_executor_err:
    print(f"[EXECUTOR] Phase 11 multi-PDF executor contract failed: {_eli_phase11_multipdf_executor_err}", flush=True)
'''

if "_ELI_PHASE11_MULTIPDF_EXECUTOR_INSTALLED" not in src:
    write_with_backup(executor, src.rstrip() + "\n" + executor_block + "\n")


# ---------------------------------------------------------------------
# 3. Probe
# ---------------------------------------------------------------------

probe = ROOT / "ops/probes/phase11_multipdf_route_probe.py"
probe.write_text(r'''#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PDF1="/home/jay/Desktop/Physics/Theory_MATHEMATICS/Exergetic_Coherence_Revoloution.pdf"
PDF2="/home/jay/Desktop/Physics/Theory_MATHEMATICS/FINAL.pdf"

prompt = f"read and summarise {PDF1} and {PDF2}"

from eli.execution.router_enhanced import route, route_intent

for fn in (route, route_intent):
    r = fn(prompt)
    print("=" * 100)
    print(fn.__name__, "=>", r)
    args = r.get("args", {}) if isinstance(r, dict) else {}
    print("action:", r.get("action") if isinstance(r, dict) else None)
    print("path:", args.get("path"))
    print("paths:", args.get("paths"))
    print("paths_count:", len(args.get("paths") or []))
''', encoding="utf-8")
probe.chmod(0o755)


# ---------------------------------------------------------------------
# 4. Compile + report
# ---------------------------------------------------------------------

cp = subprocess.run(
    [sys.executable, "-m", "compileall", "-q", "eli"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
)

summary = OUT / "SUMMARY.md"
summary.write_text(
    "# Phase 11 Multi-PDF Route + Executor Contract\n\n"
    "Changed files:\n"
    + ("".join(f"- {x}\n" for x in changed) if changed else "- none\n")
    + "\nCompile output:\n\n```text\n"
    + cp.stdout
    + "\n```\n",
    encoding="utf-8",
)

print(f"REPORT: {OUT}")
print(summary.read_text())

if cp.returncode != 0:
    raise SystemExit(cp.returncode)
