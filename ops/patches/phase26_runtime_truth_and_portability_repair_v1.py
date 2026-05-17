#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import difflib
import pathlib
import py_compile
import re
import shutil
import sys

ROOT = pathlib.Path.cwd()
STAMP = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / f"ops/reports/phase26_runtime_truth_and_portability_repair_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

BACKUPS = OUT / "backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

PATCHED: list[pathlib.Path] = []
NOTES: list[str] = []


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8")


def backup(p: pathlib.Path) -> None:
    dest = BACKUPS / p.relative_to(ROOT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)


def write_with_diff(p: pathlib.Path, old: str, new: str) -> None:
    if old == new:
        NOTES.append(f"UNCHANGED {p.relative_to(ROOT)}")
        return
    backup(p)
    p.write_text(new, encoding="utf-8")
    PATCHED.append(p)

    diff = difflib.unified_diff(
        old.splitlines(True),
        new.splitlines(True),
        fromfile=f"{p.relative_to(ROOT)}.before",
        tofile=str(p.relative_to(ROOT)),
    )
    diff_path = OUT / (str(p.relative_to(ROOT)).replace("/", "__") + ".diff")
    diff_path.write_text("".join(diff), encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Missing required anchor for {label}")
    return text.replace(old, new, 1)


def sub_once(text: str, pattern: str, repl: str, label: str, flags: int = 0) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=flags)
    if n != 1:
        raise RuntimeError(f"Expected exactly one substitution for {label}; got {n}")
    return new


# ---------------------------------------------------------------------------
# 1. .env.mkxi — remove /home/jay absolute model paths
# ---------------------------------------------------------------------------
env_file = ROOT / ".env.mkxi"
if not env_file.exists():
    raise RuntimeError(".env.mkxi missing; audit previously found it.")

old = read(env_file)
new = old

portable_marker = "# === PHASE26_PORTABLE_PROJECT_ROOT_MODEL_PATHS ==="

if portable_marker not in new:
    lines = new.splitlines()
    filtered = []
    for line in lines:
        if re.match(r'^\s*export\s+(ELI_GGUF_MODEL_PATH|ELI_MODEL_PATH|ELI_MODEL|GGUF_MODEL_PATH)=', line):
            continue
        filtered.append(line)

    block = [
        portable_marker,
        '# Project-root-relative paths only. No machine-specific /home/<user> paths.',
        'export ELI_PROJECT_ROOT="${ELI_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"',
        'export ELI_GGUF_MODEL_PATH="${ELI_GGUF_MODEL_PATH:-$ELI_PROJECT_ROOT/models/mistral-small-3.1-24b-instruct-2503-q5_k_m.gguf}"',
        'export ELI_MODEL_PATH="${ELI_MODEL_PATH:-$ELI_GGUF_MODEL_PATH}"',
        'export ELI_MODEL="${ELI_MODEL:-$ELI_GGUF_MODEL_PATH}"',
        'export GGUF_MODEL_PATH="${GGUF_MODEL_PATH:-$ELI_GGUF_MODEL_PATH}"',
        "",
    ]

    insert_at = 0
    while insert_at < len(filtered) and (
        not filtered[insert_at].strip()
        or filtered[insert_at].lstrip().startswith("#")
    ):
        insert_at += 1

    filtered[insert_at:insert_at] = block
    new = "\n".join(filtered) + ("\n" if old.endswith("\n") else "")

write_with_diff(env_file, old, new)


# ---------------------------------------------------------------------------
# 2. README portability — absolute current project root -> <ELI_PROJECT_ROOT>
# ---------------------------------------------------------------------------
readme = ROOT / "requirements/README_ELI_ENVIRONMENT.md"
if readme.exists():
    old = read(readme)
    new = old.replace(str(ROOT), "<ELI_PROJECT_ROOT>")
    write_with_diff(readme, old, new)
else:
    NOTES.append("SKIP requirements/README_ELI_ENVIRONMENT.md missing")


# ---------------------------------------------------------------------------
# 3. gguf_inference.py — runtime truth metadata
# ---------------------------------------------------------------------------
gguf = ROOT / "eli/cognition/gguf_inference.py"
old = read(gguf)
new = old

helper_marker = "# === PHASE26_GPU_BACKEND_TRUTH_HELPERS ==="
helper_anchor = "        def _eli_eff_effective(llm=None, existing=None, adaptive=None):\n"

helper_block = '''        # === PHASE26_GPU_BACKEND_TRUTH_HELPERS ===
        def _eli_eff_gpu_backend_supported():
            """
            Return whether the loaded llama-cpp-python binding advertises GPU
            offload support. This is backend capability truth, not proof that a
            specific model call actively offloaded the requested layer count.
            """
            try:
                import llama_cpp as _eli_eff_lc
                probe = getattr(_eli_eff_lc, "llama_supports_gpu_offload", None)
                if callable(probe):
                    return bool(probe())
            except Exception:
                return None
            return None

        def _eli_eff_gpu_execution_claim(backend_supported, gpu_layer_parameter: int) -> str:
            if backend_supported is False:
                return "backend_cpu_only_no_gpu_offload"
            if backend_supported is True and int(gpu_layer_parameter or 0) > 0:
                return "gpu_backend_available_positive_layer_parameter"
            if backend_supported is True:
                return "gpu_backend_available_zero_layer_parameter"
            return "gpu_backend_support_unknown"

'''

if helper_marker not in new:
    new = replace_once(new, helper_anchor, helper_block + helper_anchor, "gguf truth helper insert")

state_marker = "gpu_execution_claim = _eli_eff_gpu_execution_claim("
state_anchor = (
    "            requested = _eli_eff_requested(existing, adaptive)\n"
    "            effective = _eli_eff_effective(llm, existing, adaptive)\n"
)

state_insert = state_anchor + '''            gpu_backend_offload_supported = _eli_eff_gpu_backend_supported()
            gpu_layer_parameter = int(
                effective.get("n_gpu_layers")
                or requested.get("n_gpu_layers")
                or 0
            )
            gpu_execution_claim = _eli_eff_gpu_execution_claim(
                gpu_backend_offload_supported,
                gpu_layer_parameter,
            )
'''

if state_marker not in new:
    new = replace_once(new, state_anchor, state_insert, "gguf runtime truth state insert")

payload_marker = '"gpu_backend_offload_supported": gpu_backend_offload_supported,'
payload_anchor = '                "runtime_contract": "requested_effective_split",\n'
payload_insert = payload_anchor + '''                "gpu_backend_offload_supported": gpu_backend_offload_supported,
                "gpu_layer_parameter": gpu_layer_parameter,
                "gpu_execution_claim": gpu_execution_claim,
                "runtime_truth_note": (
                    "n_gpu_layers is the selected llama.cpp load parameter. "
                    "It is not standalone proof of active CUDA execution."
                ),
'''

if payload_marker not in new:
    new = replace_once(new, payload_anchor, payload_insert, "gguf payload truth metadata insert")

old_comment = (
    "                # Legacy compatibility: top-level runtime values now mean effective.\n"
)
new_comment = (
    "                # Legacy compatibility: top-level runtime values remain selected loader\n"
    "                # parameters. They are not standalone proof of active CUDA execution;\n"
    "                # inspect gpu_backend_offload_supported + gpu_execution_claim.\n"
)
if old_comment in new:
    new = new.replace(old_comment, new_comment, 1)

# Rename the log family so it no longer sounds like hardware-verified truth.
new = new.replace("[GGUF][EFFECTIVE]", "[GGUF][LOAD-PARAMS]")
new = new.replace('f"effective ctx=', 'f"selected ctx=')

write_with_diff(gguf, old, new)


# ---------------------------------------------------------------------------
# 4. context_synthesiser.py — stop inferring GPU merely from gpu_layers > 0
# ---------------------------------------------------------------------------
ctx = ROOT / "eli/cognition/context_synthesiser.py"
old = read(ctx)
new = old

old_line = '    on_gpu = bool(snap.get("on_gpu", gpu_layers > 0))\n'
new_line = (
    '    backend_gpu_offload_supported = snap.get("gpu_backend_offload_supported")\n'
    '    on_gpu = bool(\n'
    '        snap.get(\n'
    '            "on_gpu",\n'
    '            backend_gpu_offload_supported is True and gpu_layers > 0,\n'
    '        )\n'
    '    )\n'
)

new = replace_once(new, old_line, new_line, "context synthesiser GPU truth fallback")
write_with_diff(ctx, old, new)


# ---------------------------------------------------------------------------
# 5. Remove invented GPU-layer defaults in engine / deterministic gate
# ---------------------------------------------------------------------------
engine = ROOT / "eli/kernel/engine.py"
old = read(engine)
new = old

new = new.replace("        self._gpu_layers = 14\n", "        self._gpu_layers = 0\n")
new = new.replace('settings.get("n_gpu_layers", 14)', 'settings.get("n_gpu_layers", 0)')
new = new.replace("                    self._gpu_layers = 14\n", "                    self._gpu_layers = 0\n")

write_with_diff(engine, old, new)

gate = ROOT / "eli/runtime/deterministic_grounding_gate.py"
old = read(gate)
new = old

pattern = (
    r'("n_gpu_layers":\s*settings\.get\("n_gpu_layers"\)\s*'
    r'or\s*settings\.get\("gpu_layers"\)\s*or\s*)21(,)'
)
new, n = re.subn(pattern, r'\1"unknown"\2', new, count=1)
if n != 1:
    raise RuntimeError("Could not replace deterministic grounding gate fallback 21 GPU layers.")

write_with_diff(gate, old, new)


# ---------------------------------------------------------------------------
# 6. GUI/startup wording — parameter, not proof
# ---------------------------------------------------------------------------
gui = ROOT / "eli/gui/eli_pro_audio_gui_MKI.py"
old = read(gui)
new = old

new = new.replace(
    'print(f"   GPU layers: {n_gpu_layers}")',
    'print(f"   GPU-layer load parameter: {n_gpu_layers}")',
)

new = new.replace(
    'self.n_gpu_layers_input.setToolTip("Layers offloaded to GPU (0 = CPU only, 99 = all layers)")',
    'self.n_gpu_layers_input.setToolTip("Loader parameter requested for GPU offload. Backend support is reported separately. (0 = CPU request, 99 = all-layer request)")',
)

new = new.replace(
    'form.addRow(self._field_label("GPU layers"), self.n_gpu_layers_input)',
    'form.addRow(self._field_label("GPU-layer parameter"), self.n_gpu_layers_input)',
)

write_with_diff(gui, old, new)

app = ROOT / "eli/gui/app.py"
old = read(app)
new = old.replace(
    '("n_gpu_layers", "GPU layers offloaded (99=all)"),',
    '("n_gpu_layers", "GPU-layer load parameter (99=all-layer request)"),',
)
write_with_diff(app, old, new)

intro = ROOT / "eli/cognition/introspection_agent.py"
old = read(intro)
new = old.replace(
    'f"GPU layers: {gpu}",',
    'f"GPU-layer parameter: {gpu}",',
)
write_with_diff(intro, old, new)

exec_file = ROOT / "eli/execution/executor_enhanced.py"
old = read(exec_file)
new = old.replace(
    '"ELI effective llama.cpp runtime:",',
    '"ELI selected llama.cpp load parameters:",',
)
new = new.replace(
    'f"- GPU layers: {runtime_snapshot.get(\'n_gpu_layers\', \'unknown\')}",',
    'f"- GPU-layer parameter: {runtime_snapshot.get(\'n_gpu_layers\', \'unknown\')}",',
)
new = new.replace(
    "- If ELI booted with lower effective ctx/GPU layers than requested, the fallback is expected behavior, not a settings lie.",
    "- If ELI booted with lower selected ctx/GPU-layer parameters than requested, the fallback is expected behavior, not a settings lie.",
)
write_with_diff(exec_file, old, new)

live = ROOT / "eli/runtime/live_introspection.py"
old = read(live)
new = old.replace(
    "gpu_layers={rt['n_gpu_layers']}.",
    "gpu_layer_param={rt['n_gpu_layers']}.",
)
write_with_diff(live, old, new)


# ---------------------------------------------------------------------------
# 7. Compile validation
# ---------------------------------------------------------------------------
compile_targets = [
    ROOT / "eli/cognition/gguf_inference.py",
    ROOT / "eli/cognition/context_synthesiser.py",
    ROOT / "eli/kernel/engine.py",
    ROOT / "eli/runtime/deterministic_grounding_gate.py",
    ROOT / "eli/gui/eli_pro_audio_gui_MKI.py",
    ROOT / "eli/gui/app.py",
    ROOT / "eli/cognition/introspection_agent.py",
    ROOT / "eli/execution/executor_enhanced.py",
    ROOT / "eli/runtime/live_introspection.py",
]

compile_log = []
for p in compile_targets:
    try:
        py_compile.compile(str(p), doraise=True)
        compile_log.append(f"PY_COMPILE_OK {p.relative_to(ROOT)}")
    except Exception as e:
        compile_log.append(f"PY_COMPILE_FAIL {p.relative_to(ROOT)} :: {e}")
        raise

(OUT / "PY_COMPILE.txt").write_text("\n".join(compile_log) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 8. Post-patch audit snapshots
# ---------------------------------------------------------------------------
def rg_like(root: pathlib.Path, pattern: str, paths: list[str]) -> str:
    import subprocess
    cmd = ["rg", "-n", "--hidden", pattern, *paths]
    proc = subprocess.run(cmd, cwd=root, text=True, capture_output=True)
    return (proc.stdout or "") + (proc.stderr or "")

(OUT / "01_postpatch_jay_path_hits.txt").write_text(
    rg_like(
        ROOT,
        r"(/home/jay|/home/Jay|/Users/jay|/Users/Jay)",
        ["eli", "config", "scripts", "requirements", "docs", "packaging", "bin", ".env.mkxi"],
    ),
    encoding="utf-8",
)

(OUT / "02_postpatch_gpu_truth_markers.txt").write_text(
    rg_like(
        ROOT,
        r"gpu_backend_offload_supported|gpu_execution_claim|GPU-layer load parameter|GPU-layer parameter|LOAD-PARAMS|or \"unknown\"",
        ["eli", ".env.mkxi"],
    ),
    encoding="utf-8",
)

summary = [
    "# Phase 26 — Runtime Truth + Portability Repair",
    "",
    f"Root: `{ROOT}`",
    f"Output: `{OUT}`",
    "",
    "## Patched files",
]
summary.extend(f"- `{p.relative_to(ROOT)}`" for p in PATCHED)
summary += [
    "",
    "## Repair scope",
    "- Rebased `.env.mkxi` model paths away from `/home/jay/...`.",
    "- Rebased environment README absolute paths to `<ELI_PROJECT_ROOT>`.",
    "- Added backend GPU-offload truth fields to GGUF runtime snapshot payloads.",
    "- Relabeled startup/UI GPU layer wording as a loader parameter rather than verified execution.",
    "- Removed invented fallback GPU-layer constants `14` and `21` from runtime truth paths.",
    "- Prevented context synthesis from assuming GPU use solely because `n_gpu_layers > 0`.",
    "",
    "## Validation",
    "- Python compile pass written to `PY_COMPILE.txt`.",
    "- Post-patch hard-coded `/home/jay` scan written to `01_postpatch_jay_path_hits.txt`.",
    "- Runtime-truth marker scan written to `02_postpatch_gpu_truth_markers.txt`.",
]
if NOTES:
    summary += ["", "## Notes"]
    summary.extend(f"- {n}" for n in NOTES)

(OUT / "SUMMARY.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

print(f"PHASE26_PATCH_OK")
print(f"OUT={OUT}")
print(f"SUMMARY={OUT / 'SUMMARY.md'}")
