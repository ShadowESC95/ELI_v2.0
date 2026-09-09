"""Curated installer copy — ELI voice: direct, dry, nerdy, occasionally a pisstaker."""
from __future__ import annotations

import random
from typing import Dict, List

# phase → rotating messages shown while backend work runs
INSTALL_MESSAGES: Dict[str, List[str]] = {
    "welcome": [
        "Local-first AI. No cloud account. No subscription ransom note.",
        "Everything stays on your machine — the way software used to work before SaaS got ideas.",
        "ELI runs offline by default. Your data does not leave unless you explicitly ask it to.",
        "First-time setup takes a few minutes. After that, double-click and go.",
    ],
    "system": [
        "Scanning your hardware so we do not pretend you have a GPU when you do not.",
        "Reading CPU, RAM, and disk — sizing the install to what is actually in the box.",
        "Detecting NVIDIA, AMD, Intel, Apple — one honest report, not three conflicting ones.",
        "If this step finds integrated graphics, we budget shared memory instead of faking VRAM.",
    ],
    "venv": [
        "Creating a private Python environment — ELI's house, not your system Python's.",
        "Virtual environments exist so pip does not redecorate your entire OS.",
        "Building .venv — isolated, reproducible, and safe to delete if something goes sideways.",
    ],
    "torch": [
        "Installing PyTorch — the tensor engine behind half the modern ML stack.",
        "PyTorch download can be chunky. This is normal. Coffee optional, patience mandatory.",
        "Matching PyTorch to your GPU vendor — CUDA, ROCm, Metal, or honest CPU-only.",
    ],
    "llama": [
        "Building llama.cpp — this is the inference engine that actually runs your models.",
        "Compiling GPU offload support. On some machines this is the long bit. Worth it.",
        "llama-cpp-python: where 'it loaded' and 'it runs at usable speed' diverge or align.",
        "If this step source-builds, your CPU flags are being checked so we do not SIGILL you.",
    ],
    "eli": [
        "Installing ELI and its dependency tree — PySide6, memory, cognition, the lot.",
        "Resolving requirements. Yes, there are many. No, we are not hiding them from you.",
        "This step pulls the full stack. It is deliberately verbose in the log, not silent.",
    ],
    "database": [
        "Seeding local databases — blank slate, no imported personal data.",
        "SQLite architecture: memory, habits, runtime state. All local, all yours.",
        "Initializing data directories under artifacts/ — portable and gitignored by design.",
    ],
    "model": [
        "Downloading a starter chat model sized to your hardware budget.",
        "Models are large. Progress and ETA are shown because 'trust me bro' is not UX.",
        "Picking a sensible default model — you can swap it in the wizard after this.",
        "Fetching weights from HugHub — the one deliberate online step unless you are offline.",
    ],
    "assets": [
        "Memory embedder + voice models — ELI remembers and speaks without phoning home.",
        "Piper + Whisper assets: local TTS/STT. Optional neural backends stay optional.",
        "Support assets are idempotent — re-running setup skips what is already present.",
    ],
    "desktop": [
        "Installing app menu shortcuts — ELI, ELI Server, ELI Setup.",
        "Desktop integration so you do not have to hunt for a shell script like it is 1998.",
    ],
    "finish": [
        "Setup complete. ELI is configured to be lethal, not merely installed.",
        "All first-run stages checked. Launch when ready — the wizard will confirm.",
        "If something failed, the log below says what — no silent exceptions, no mystery.",
    ],
    "witty": [
        "Still here? Good. Abandoned installers are how projects die.",
        "ELI does not confabulate your shower habits. That was a bug, not a feature.",
        "We read the logs. We fix the logs. We do not 'works on my machine' and leave.",
        "Research-grade local AI: slower than a datacenter, faster than sending your life to a cloud.",
        "Your GPU layer count will reflect reality this time. Zero when zero. Fit when it fits.",
        "If install feels slow, blame physics — not a missing progress bar.",
        "No quick hacks. No swallowed tracebacks. Professional software, even when witty.",
    ],
}

_PHASE_ORDER = (
    "welcome", "system", "venv", "torch", "llama", "eli",
    "database", "model", "assets", "desktop", "finish",
)


def messages_for_phase(phase: str) -> List[str]:
    pool = list(INSTALL_MESSAGES.get(phase, []))
    pool.extend(INSTALL_MESSAGES.get("witty", []))
    if not pool:
        pool = ["Working…"]
    random.shuffle(pool)
    return pool


def phase_label(phase: str) -> str:
    labels = {
        "welcome": "Welcome",
        "system": "System check",
        "venv": "Python environment",
        "torch": "PyTorch",
        "llama": "Inference engine",
        "eli": "ELI core",
        "database": "Local database",
        "model": "Chat model",
        "assets": "Memory & voice",
        "desktop": "Shortcuts",
        "finish": "Complete",
        "core_install": "Core installation",
        "assets_setup": "Assets & models",
    }
    return labels.get(phase, phase.replace("_", " ").title())
