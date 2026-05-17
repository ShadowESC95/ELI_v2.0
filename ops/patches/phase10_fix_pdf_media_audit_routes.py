#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
STAMP = subprocess.check_output(["date", "+%Y%m%d_%H%M%S"], text=True).strip()
OUT = ROOT / f"ops/reports/phase10_fix_pdf_media_audit_routes_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

changed = []
notes = []


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write(path: Path, text: str) -> None:
    backup = OUT / (str(path).replace("/", "__") + ".bak")
    backup.write_text(read(path), encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    changed.append(str(path))


def line_range_for_func(src: str, func_name: str) -> tuple[int, int] | None:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            if getattr(node, "end_lineno", None):
                return node.lineno, node.end_lineno
    return None


def replace_func(src: str, func_name: str, new_func: str) -> str:
    rng = line_range_for_func(src, func_name)
    if not rng:
        raise RuntimeError(f"Could not find function {func_name}")
    start, end = rng
    lines = src.splitlines()
    return "\n".join(lines[: start - 1] + [new_func.rstrip()] + lines[end:]) + "\n"


# ---------------------------------------------------------------------
# 1. router_enhanced.py: robust PDF path extraction + audit guard
# ---------------------------------------------------------------------

router = ROOT / "eli/execution/router_enhanced.py"
src = read(router)

new_pdf_funcs = r'''
def _extract_pdf_paths(raw: str) -> list[str]:
    """
    Robust PDF path extractor.

    Fixes the old bug where:
        /home/jay/path/File.pdf
    became:
        /File.pdf

    Supports:
    - absolute paths
    - ~/ paths
    - ./ and ../ paths
    - multiple PDFs in one prompt
    - basename fallback search for bracketed PDF-content prompts
    """
    import os
    import re
    from pathlib import Path

    text = str(raw or "")
    found: list[str] = []

    full_path_re = re.compile(
        r'(?P<path>(?:~|/|\.{1,2}/)[^\n\r\t"\'<>]*?\.pdf)\b',
        re.IGNORECASE,
    )

    for m in full_path_re.finditer(text):
        p = m.group("path").strip()
        p = p.strip(" ,.;:)]}>")
        p = os.path.abspath(os.path.expanduser(p))
        found.append(p)

    # Basename fallback for prompts like:
    #   [PDF content — Exergetic_Coherence_Revoloution.pdf]
    # Only used to help route; executor still verifies existence.
    name_re = re.compile(r'(?P<name>[A-Za-z0-9_. -]+\.pdf)\b', re.IGNORECASE)
    roots = [
        Path.cwd(),
        Path.home(),
        Path.home() / "Desktop",
        Path.home() / "Desktop/Physics",
        Path.home() / "Desktop/Physics/Theory_MATHEMATICS",
    ]

    for m in name_re.finditer(text):
        name = m.group("name").strip().strip(" ,.;:)]}>")
        if any(Path(x).name == name for x in found):
            continue

        # If user supplied only a basename, try known local roots.
        for root in roots:
            if not root.exists():
                continue
            try:
                direct = root / name
                if direct.exists():
                    found.append(str(direct.resolve()))
                    break

                # Keep this bounded to likely user document locations.
                matches = list(root.rglob(name))
                if matches:
                    found.append(str(matches[0].resolve()))
                    break
            except Exception:
                continue

    deduped: list[str] = []
    seen: set[str] = set()
    for p in found:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    return deduped


def _extract_pdf_path(raw: str) -> Optional[str]:
    """
    Backward-compatible single-PDF wrapper.
    Prefer _extract_pdf_paths() for new routing.
    """
    paths = _extract_pdf_paths(raw)
    return paths[0] if paths else None
'''

src = replace_func(src, "_extract_pdf_path", new_pdf_funcs)

# Add codebase-audit helper near top if missing.
if "_eli_phase10_is_codebase_audit_request" not in src:
    insert_after = src.find("\n\n")
    helper = r'''

def _eli_phase10_is_codebase_audit_request(text: str) -> bool:
    """
    Prevent broad memory-runtime regexes from hijacking codebase audits.
    """
    s = str(text or "").lower()

    audit_words = (
        "audit", "inspect", "scan", "check", "verify", "examine",
        "what is wrong", "what's wrong", "broken", "missing",
    )
    code_words = (
        "router", "executor", "engine", "agent_bus", "world_model",
        "gguf_inference", "orchestrator", "output_governor",
        "output_governer", "response_governance", "response_governence",
        "hyde", "vector_store", "working_memory", "introspection_agent",
        "reranker", "llm_intent", "hardware_profile", "runtime_settings",
        "pipeline", "self_upgrade", "habits_memory_db", "knowledge_graph",
        "memory_adapter", "memory_truth", "memory_service", "sqlite_memory",
        "os_controller", "screen_locator", "log_rotation", "/runtime",
        "python files", ".py", "eli_pro_audio_gui", "router_enhanced",
        "executor_enhanced",
    )

    return any(a in s for a in audit_words) and any(c in s for c in code_words)
'''
    src = src[:insert_after] + helper + src[insert_after:]

# Insert guard before the known broad memory-runtime hijack block.
needle = 'r"\\b(cognition pipeline|input to output|every step|memory system|db tables|functions|files|runtime audit|diagnostic|diagnostics|full audit)\\b"'
if needle in src and "phase10.codebase_audit_guard" not in src:
    idx = src.find(needle)
    line_start = src.rfind("\n", 0, idx)
    block_start = src.rfind("\n    if ", 0, idx)
    if block_start == -1:
        block_start = line_start

    guard = '''
    if _eli_phase10_is_codebase_audit_request(raw):
        return _mk(
            "RUNTIME_AUDIT",
            {"query": raw, "audit_depth": "codebase"},
            0.99,
            matched_by="phase10.codebase_audit_guard",
            allow_chat_without_evidence=False,
            need_grounding=True,
            task_family="grounded_audit",
        )

'''
    src = src[: block_start + 1] + guard + src[block_start + 1:]
else:
    notes.append("router memory hijack needle not found or guard already installed")

write(router, src)


# ---------------------------------------------------------------------
# 2. portable_intent_contract.py and media_intents.py:
#    block long/PDF/analysis prompts from implied media routes.
# ---------------------------------------------------------------------

MEDIA_GUARD_HELPER = r'''
def _eli_phase10_blocks_media_intent(text: str) -> bool:
    """
    Hard block document/code/analysis prompts from PLAY_MEDIA.
    This prevents long academic PDF prompts being interpreted as songs.
    """
    s = str(text or "").lower().strip()

    if len(s) > 260:
        return True

    blockers = (
        ".pdf", "[pdf content", "pdf content", "analyse", "analyze",
        "summarise", "summarize", "read and summarise", "read and summarize",
        "abstract", "lagrangian", "field equation", "equation of motion",
        "stress-energy", "tensor", "cosmology", "framework", "theory",
        "audit", "router", "executor", "gguf_inference", "orchestrator",
        "python files", "codebase",
    )
    return any(b in s for b in blockers)
'''


def patch_media_file(path: Path) -> None:
    src = read(path)

    if "_eli_phase10_blocks_media_intent" not in src:
        first_gap = src.find("\n\n")
        src = src[:first_gap] + MEDIA_GUARD_HELPER + src[first_gap:]

    tree = ast.parse(src)
    target_funcs = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            seg = ast.get_source_segment(src, node) or ""
            if "implied_song_by_artist" in seg and node.args.args:
                target_funcs.append(node)

    if not target_funcs:
        notes.append(f"No implied_song_by_artist function found in {path}")
        write(path, src)
        return

    lines = src.splitlines()

    # Patch from bottom upward so line numbers remain valid.
    for node in sorted(target_funcs, key=lambda n: n.lineno, reverse=True):
        arg_name = node.args.args[0].arg

        # Find insertion point after docstring if present.
        insert_line = node.lineno
        body0 = node.body[0] if node.body else None
        if (
            body0
            and isinstance(body0, ast.Expr)
            and isinstance(getattr(body0, "value", None), ast.Constant)
            and isinstance(body0.value.value, str)
            and getattr(body0, "end_lineno", None)
        ):
            insert_line = body0.end_lineno

        guard_line = f"    if _eli_phase10_blocks_media_intent({arg_name}):\n        return None"

        func_text = "\n".join(lines[node.lineno - 1 : node.end_lineno])
        if "_eli_phase10_blocks_media_intent" in func_text:
            continue

        lines[insert_line:insert_line] = guard_line.splitlines()

    src = "\n".join(lines) + "\n"
    write(path, src)


patch_media_file(ROOT / "eli/execution/portable_intent_contract.py")
patch_media_file(ROOT / "eli/execution/media_intents.py")


# ---------------------------------------------------------------------
# 3. Lightweight verification probe
# ---------------------------------------------------------------------

probe = ROOT / "ops/probes/phase10_route_contract_probe.py"
probe.write_text(r'''
#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

PDF1 = "/home/jay/Desktop/Physics/Theory_MATHEMATICS/Exergetic_Coherence_Revoloution.pdf"
PDF2 = "/home/jay/Desktop/Physics/Theory_MATHEMATICS/FINAL.pdf"

samples = [
    f"read and summarise {PDF1} and {PDF2}",
    "analyse and talk to me about [PDF content — Exergetic_Coherence_Revoloution.pdf]: Exergetic Cosmology and Vacuum Hydrodynamics",
    "play guilty conscience by eminem on spotify",
    "audit your world_model, agent_bus, gguf_inference, orchestrator, output_governer, hyde, vector_store, runtime_settings and every file in the /runtime folder",
]

print("=== Import router ===")
import eli.execution.router_enhanced as r

if hasattr(r, "_extract_pdf_paths"):
    for s in samples[:2]:
        print("INPUT:", s[:160])
        print("PDF_PATHS:", r._extract_pdf_paths(s))
        print("PDF_PATH:", r._extract_pdf_path(s))
        print()

print("=== Media guard imports ===")
import eli.execution.portable_intent_contract as pic
import eli.execution.media_intents as mi

for mod in (pic, mi):
    guard = getattr(mod, "_eli_phase10_blocks_media_intent", None)
    print(mod.__name__, "guard_exists=", bool(guard))
    if guard:
        print("pdf blocked:", guard(samples[1]))
        print("song blocked:", guard(samples[2]))
''', encoding="utf-8")
probe.chmod(0o755)


# ---------------------------------------------------------------------
# 4. Compile and report
# ---------------------------------------------------------------------

compile_cmd = [sys.executable, "-m", "compileall", "-q", "eli"]
cp = subprocess.run(compile_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

report = OUT / "SUMMARY.md"
report.write_text(
    "# Phase 10 PDF / Media / Audit Route Patch\n\n"
    f"Changed files:\n" +
    "".join(f"- {x}\n" for x in changed) +
    "\nNotes:\n" +
    ("".join(f"- {x}\n" for x in notes) if notes else "- none\n") +
    "\nCompile output:\n\n```text\n" +
    cp.stdout +
    "\n```\n",
    encoding="utf-8",
)

print(f"REPORT: {OUT}")
print(report.read_text())

if cp.returncode != 0:
    raise SystemExit(cp.returncode)
