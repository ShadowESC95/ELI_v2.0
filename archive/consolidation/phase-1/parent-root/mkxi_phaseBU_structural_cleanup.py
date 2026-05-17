#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import py_compile
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

ROOT = Path.cwd().resolve()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
REPORT_DIR = ROOT / "ops" / "reports" / f"{STAMP}.phaseBU_structural_cleanup"
BACKUP_DIR = ROOT / "ops" / "backups" / f"{STAMP}.phaseBU_structural_cleanup"
ARCHIVE_DIR = ROOT / "ops" / "archives" / f"{STAMP}.retired_surface_shims"

TARGET_FILES = [
    "eli/kernel/engine.py",
    "eli/execution/router_enhanced.py",
    "eli/execution/executor_enhanced.py",
    "eli/runtime/global_persona_authority.py",
    "eli/runtime/persona_final_authority.py",
    "eli/runtime/memory_intercepts.py",
    "config/settings.json",
]

SHIM_FILES = [
    "eli/runtime/global_persona_authority.py",
    "eli/runtime/persona_final_authority.py",
    "eli/runtime/memory_intercepts.py",
]

ACTIVE_SCAN_PATTERNS = [
    "global_persona_authority",
    "persona_final_authority",
    "memory_intercepts",
    "phaseBL",
    "phaseBM",
    "phaseBO",
    "phaseBG",
    "metadata_fixed_by",
    "/home/user/models",
    "/home/Jason",
    "/home/jason",
    "my_model.gguf",
    "/data/user/eli",
    "eli.sqlite3",
    "/etc/gguf-runtime",
    "libgguf",
    "local GGUF-powered assistant depends",
    "I have updated my file paths",
    "I've updated the file paths",
]

def log(lines: List[str], msg: str) -> None:
    print(msg)
    lines.append(msg)

def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)

def backup_file(path: Path, report: List[str]) -> None:
    if not path.exists():
        log(report, f"SKIP_BACKUP missing {rel(path)}")
        return
    dest = BACKUP_DIR / rel(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    log(report, f"BACKUP {rel(path)} -> {dest}")

def restore_backups(report: List[str]) -> None:
    for b in sorted(BACKUP_DIR.rglob("*")):
        if not b.is_file():
            continue
        dest = ROOT / b.relative_to(BACKUP_DIR)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b, dest)
        log(report, f"RESTORED {rel(dest)}")

def compile_active_python(report: List[str]) -> List[Tuple[str, str]]:
    failures: List[Tuple[str, str]] = []
    for p in sorted((ROOT / "eli").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except Exception as exc:
            failures.append((rel(p), repr(exc)))
    log(report, f"COMPILE_FAILURES={len(failures)}")
    for path, err in failures[:80]:
        log(report, f"- {path}: {err}")
    return failures

def scan_active(report: List[str], patterns: List[str] = ACTIVE_SCAN_PATTERNS) -> List[Tuple[str, str, int]]:
    hits: List[Tuple[str, str, int]] = []
    search_roots = [ROOT / "eli", ROOT / "config", ROOT / "bin"]
    for base in search_roots:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*")) if base.is_dir() else [base]:
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                for pat in patterns:
                    if pat in line:
                        hits.append((rel(p), pat, lineno))
                        break
    log(report, f"ACTIVE_CONTAMINATION_HITS={len(hits)}")
    for path, pat, line in hits[:120]:
        log(report, f"- {path}:{line}: {pat}")
    return hits

def truncate_engine_bottom_patch_stack(engine_path: Path, report: List[str]) -> None:
    text = engine_path.read_text(encoding="utf-8", errors="replace")
    module = ast.parse(text)
    end_line = None
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == "get_engine":
            end_line = node.end_lineno
    if not end_line:
        raise RuntimeError("Could not locate get_engine() in engine.py")
    lines = text.splitlines()
    removed = max(0, len(lines) - end_line)
    text = "\n".join(lines[:end_line]) + "\n"
    log(report, f"TRUNCATED engine.py bottom monkey-patch stack removed_lines={removed}")

    m = re.search(
        r'\n        _legacy_internal_meta_prefix = .*?\n        reasoning_mode = kwargs\.get\("reasoning_mode", reasoning_mode\)',
        text,
        flags=re.S,
    )
    if m:
        text = text[:m.start()] + '\n        reasoning_mode = kwargs.get("reasoning_mode", reasoning_mode)' + text[m.end():]
        log(report, "REMOVED engine.py legacy internal meta-prompt direct response")

    m = re.search(
        r'''        _trace_low = str\(user_input or ""\)\.strip\(\)\.lower\(\)
        _trace_terms = \(
.*?        if str\(action\)\.upper\(\) == "CHAT" and _matched_by == "runtime\.status\.grounded_chat":''',
        text,
        flags=re.S,
    )
    if m:
        replacement = '''        _trace_low = str(user_input or "").strip().lower()
        _trace_terms = (
            "confidence in your last response",
            "confidence in my last response",
            "which agents contributed",
            "what agents contributed",
            "which agents were used",
            "what agents were used",
            "last response",
            "previous response",
            "last turn trace",
        )
        if any(term in _trace_low for term in _trace_terms):
            intent = dict(intent or {})
            intent["action"] = "EXPLAIN_LAST_RESPONSE"
            intent["args"] = {}
            _meta = dict(intent.get("meta") or {})
            _meta["upgraded_from_chat"] = True
            _meta["upgraded_reason"] = "last_response_trace"
            intent["meta"] = _meta
            action = "EXPLAIN_LAST_RESPONSE"
            args = {}

        if str(action).upper() == "CHAT" and _matched_by == "runtime.status.grounded_chat":'''
        text = text[:m.start()] + replacement + text[m.end():]
        log(report, "REPLACED engine.py direct last-trace template with action promotion")

    m = re.search(
        r'''        _trace_query_terms = \(
.*?        # --- Stage 2: Persona Lock Verify \(authority gate\) ---''',
        text,
        flags=re.S,
    )
    if m:
        text = text[:m.start()] + '        # --- Stage 2: Persona Lock Verify (authority gate) ---' + text[m.end():]
        log(report, "REMOVED engine.py duplicate last-trace promotion block")

    start = text.find('            # --- MKXI_PHASEAV_ROUTE_GROUNDED_BRANCH_THROUGH_PHASEAU ---')
    end_marker = '            # --- end MKXI_PHASEAV_ROUTE_GROUNDED_BRANCH_THROUGH_PHASEAU ---'
    if start != -1:
        end = text.find(end_marker, start)
        if end == -1:
            raise RuntimeError("Could not locate PhaseAV end marker")
        end += len(end_marker)
        replacement = '''            _grounded_control_actions = {
                "SELF_REPORT",
                "RUNTIME_STATUS",
                "USER_IDENTITY_SUMMARY",
                "EXPLAIN_MEMORY_RUNTIME",
                "EXPLAIN_COGNITION_RUNTIME",
                "LAST_TRACE_REPORT",
                "PERSONA_AUTO_REPORT",
                "RUNTIME_AUDIT",
                "IMPORT_AUDIT",
                "GUI_RUNTIME_AUDIT",
                "RESOLVE_RUNTIME_PATHS",
                "MEMORY_STATUS",
                "COGNITION_STATUS",
                "EXPLAIN_LAST_RESPONSE",
            }

            if evidence and str(action).upper() in _grounded_control_actions:
                try:
                    print("[COGNITIVE] Routing grounded control evidence through normal synthesis")
                    grounded_result = self._run_chat_reasoning_loop(
                        user_input,
                        evidence,
                        intent,
                        reasoning_mode,
                        trace=trace,
                        gen_overrides={"max_tokens": 768, "temperature": 0.30},
                        situation_brief=evidence[:6000],
                    )
                    if isinstance(grounded_result, dict):
                        text = str(
                            grounded_result.get("response")
                            or grounded_result.get("content")
                            or ""
                        ).strip()
                        if text:
                            final_result = dict(grounded_result)
                            final_result["ok"] = final_result.get("ok", True)
                            final_result["action"] = action
                            final_result["response"] = text
                            final_result["content"] = text
                            final_result["confidence"] = max(
                                float(final_result.get("confidence") or 0.0),
                                float(getattr(bus_result, "aggregated_confidence", 0.0) or 0.0),
                                0.92,
                            )
                            final_result["confidence_score"] = final_result["confidence"]
                            final_result["evidence_used"] = True
                            final_result["grounded"] = True
                            final_result["meta"] = {
                                "reasoning": {
                                    "confidence": final_result["confidence"],
                                    "grounded": True,
                                    "evidence_used": True,
                                },
                                "trace": trace,
                            }
                            try:
                                self._learn_from_result(intent, bus_result.action_result or {})
                            except Exception as learn_err:
                                print(f"[COGNITIVE] Grounded learn hook failed: {learn_err}")
                            try:
                                self._execute_post_actions(trace, bus_result.action_result or {})
                            except Exception as post_err:
                                print(f"[COGNITIVE] Grounded post-actions failed: {post_err}")
                            return final_result
                except Exception as grounded_err:
                    print(f"[COGNITIVE] Grounded control synthesis failed: {grounded_err}")'''
        text = text[:start] + replacement + text[end:]
        log(report, "REPLACED engine.py PhaseAV branch with neutral grounded-control synthesis")

    text = text.replace("[COGNITIVE][PHASE]", "[COGNITIVE][FINAL]")
    text = text.replace("PHASE", "INTERNAL_STAGE")
    engine_path.write_text(text, encoding="utf-8")
    log(report, "PATCHED eli/kernel/engine.py")

def patch_router(router_path: Path, report: List[str]) -> None:
    text = router_path.read_text(encoding="utf-8", errors="replace")
    marker = '__all__ = ["route", "route_intent"]'
    idx = text.find(marker)
    if idx != -1:
        end = text.find("\n", idx)
        removed = len(text[end + 1:].splitlines())
        text = text[:end + 1]
        log(report, f"TRUNCATED router_enhanced.py appended route monkey-patch removed_lines={removed}")

    replacements = {
        "phaseAR2.correction_chat": "router.correction_chat",
        "phaseAR2.runtime_status": "router.runtime_status",
        "phaseAR2.memory_runtime": "router.memory_runtime",
        "phaseAR2.cognition_runtime": "router.cognition_runtime",
        "phaseAR2.user_identity_summary": "router.user_identity_summary",
        "phaseAR2.self_report": "router.self_report",
        "phaseAB.runtime_status_to_chat": "router.runtime_status_to_chat",
        "phaseAB.memory_status_to_chat": "router.memory_status_to_chat",
        "phaseAB.memory_runtime_to_chat": "router.memory_runtime_to_chat",
        "phaseAB.cognition_runtime_to_chat": "router.cognition_runtime_to_chat",
        "phaseAB.runtime_audit_to_chat": "router.runtime_audit_to_chat",
        "phaseAB.import_audit_to_chat": "router.import_audit_to_chat",
        "phaseAB.gui_runtime_audit_to_chat": "router.gui_runtime_audit_to_chat",
        "phaseAB.runtime_paths_to_chat": "router.runtime_paths_to_chat",
        "phaseAB.runtime_status_grounded_to_chat": "router.runtime_status_grounded_to_chat",
        "phaseAB.cognition_status_to_chat": "router.cognition_status_to_chat",
        "phaseZ2.small_talk_to_chat": "router.small_talk_to_chat",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(
        r"# --- ELI MKXI PhaseAR2 explicit speech-act route authority ---",
        "# --- explicit grounded speech-act route authority ---",
        text,
    )
    text = text.replace(
        "# --- end ELI MKXI PhaseAR2 explicit speech-act route authority ---",
        "# --- end explicit grounded speech-act route authority ---",
    )
    text = text.replace("# --- MKXI dynamic evidence preempts ---", "# --- dynamic evidence preempts ---")
    text = text.replace("MKXI_PHASEJ3_IDENTITY_PRECEDENCE", "identity precedence")
    router_path.write_text(text, encoding="utf-8")
    log(report, "PATCHED eli/execution/router_enhanced.py")

def patch_executor(executor_path: Path, report: List[str]) -> None:
    text = executor_path.read_text(encoding="utf-8", errors="replace")
    marker = "# === MKXI_PHASEAE_LIVE_INTROSPECTION_EXECUTOR ==="
    idx = text.find(marker)
    if idx != -1:
        removed = len(text[idx:].splitlines())
        text = text[:idx].rstrip() + "\n"
        log(report, f"TRUNCATED executor_enhanced.py bottom live-introspection/surface wrappers removed_lines={removed}")
    text = text.replace('f"Unknown action: {action}"', 'f"Unsupported executor action: {action}"')
    text = text.replace('f"Unknown action: {a}"', 'f"Unsupported executor action: {a}"')
    text = text.replace('f"Unknown action: {_action}"', 'f"Unsupported executor action: {_action}"')
    text = text.replace('"response_mode": "phaseBG.rich_personal_memory_surface",', "")
    executor_path.write_text(text, encoding="utf-8")
    log(report, "PATCHED eli/execution/executor_enhanced.py")

def patch_settings(settings_path: Path, report: List[str]) -> None:
    if not settings_path.exists():
        log(report, "SKIP settings.json missing")
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log(report, f"SKIP settings.json invalid JSON: {exc}")
        return
    candidates = [
        ROOT / "models" / "gguf" / "base" / "mistral-7b-instruct-v0.2.Q3_K_M.gguf",
        ROOT / "models" / "mistral-7b-instruct-v0.2.Q3_K_M.gguf",
    ]
    if (ROOT / "models").exists():
        candidates.extend(sorted((ROOT / "models").rglob("*.gguf")))
    chosen = next((p.resolve() for p in candidates if p.exists()), None)
    if chosen:
        for key in ("model_path", "bundled_model_path", "custom_model_path"):
            data[key] = str(chosen)
        settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        log(report, f"PATCHED config/settings.json canonical_model_path={chosen}")
    else:
        log(report, "SKIP settings.json model canonicalisation: no .gguf found under models/")

def scan_for_remaining_shim_references(report: List[str]) -> List[Tuple[str, str, int]]:
    refs = []
    needles = ["global_persona_authority", "persona_final_authority", "memory_intercepts"]
    for p in sorted((ROOT / "eli").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        if rel(p) in SHIM_FILES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for n in needles:
                if n in line:
                    refs.append((rel(p), n, lineno))
    log(report, f"REMAINING_SHIM_REFERENCES={len(refs)}")
    for path, needle, lineno in refs[:80]:
        log(report, f"- {path}:{lineno}: {needle}")
    return refs

def retire_surface_shims(report: List[str]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for item in SHIM_FILES:
        p = ROOT / item
        if p.exists():
            dest = ARCHIVE_DIR / item
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
            log(report, f"RETIRED {item} -> {dest}")
        else:
            log(report, f"RETIRED_SKIP missing {item}")

def write_report(report: List[str]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "phaseBU_report.txt"
    path.write_text("\n".join(report) + "\n", encoding="utf-8")
    print(f"\nREPORT={path}")

def main() -> int:
    report: List[str] = []
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    log(report, "=== ELI MKXI PhaseBU structural cleanup ===")
    log(report, f"ROOT={ROOT}")
    log(report, f"BACKUP_DIR={BACKUP_DIR}")
    log(report, f"ARCHIVE_DIR={ARCHIVE_DIR}")

    if not (ROOT / "eli").is_dir() or not (ROOT / "eli/kernel/engine.py").exists():
        log(report, "ERROR: run this from the ELI_MKXI project root.")
        write_report(report)
        return 2

    for item in TARGET_FILES:
        backup_file(ROOT / item, report)

    try:
        truncate_engine_bottom_patch_stack(ROOT / "eli/kernel/engine.py", report)
        patch_router(ROOT / "eli/execution/router_enhanced.py", report)
        patch_executor(ROOT / "eli/execution/executor_enhanced.py", report)
        patch_settings(ROOT / "config/settings.json", report)

        refs = scan_for_remaining_shim_references(report)
        if refs:
            log(report, "ERROR: active files still reference retired shim modules; refusing to move them.")
            restore_backups(report)
            write_report(report)
            return 3

        failures = compile_active_python(report)
        if failures:
            log(report, "ERROR: compile failed before retirement; restoring backups.")
            restore_backups(report)
            write_report(report)
            return 4

        retire_surface_shims(report)

        failures = compile_active_python(report)
        if failures:
            log(report, "ERROR: compile failed after retirement; restoring backups.")
            restore_backups(report)
            write_report(report)
            return 5

        hits = scan_active(report)
        if hits:
            log(report, "WARNING: active contamination scan still has hits. Inspect report before checkpointing.")
        else:
            log(report, "ACTIVE_CONTAMINATION_SCAN=PASS")

        log(report, "DONE: structural cleanup completed.")
        write_report(report)
        return 0

    except Exception as exc:
        log(report, f"ERROR: {type(exc).__name__}: {exc}")
        restore_backups(report)
        write_report(report)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
