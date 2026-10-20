"""ELI v2.0 — Startup panel components.

Contains:
  - HardwareTuningDock  — dock widget showing hardware tuning status/log
  - StartupModelSelectionDialog — model/provider picker shown at boot
  - FirstBootWizard — 3-step wizard for zero-model first-boot state
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.gui.panels._qt import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QLabel, QLineEdit, QTimer,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QTabWidget, QThread, QVBoxLayout, QHBoxLayout, QWidget, Qt,
    now_hms, pyqtSignal,
)

from eli.utils.log import get_logger
log = get_logger(__name__)

from eli.core.mem_units import file_size_gib, bytes_to_gib

try:
    from eli.core.paths import get_paths as _get_paths
    _MODELS_DIR = _get_paths().models_dir
    _PROJECT_ROOT = _get_paths().project_root
except Exception:
    _MODELS_DIR = Path("models")
    _PROJECT_ROOT = Path(".")

MODEL_PROVIDER_LABELS = {
    "bundled_gguf": "Bundled GGUF",
    "custom_gguf":  "Custom GGUF",
    "ollama":       "Ollama",
}


def _import_eli_gpu_pack():
    """Load eli_gpu_pack in AppImage/portable (hiddenimport) or dev tree."""
    import sys
    try:
        import eli_gpu_pack
        return eli_gpu_pack
    except ImportError:
        # Expected on portable/dev: module lives under packaging/pyinstaller/.
        # Do not log exc_info — startup's DEBUG handler prints it as a scary
        # traceback even though the path fallback below succeeds.
        log.debug("eli_gpu_pack not on sys.path yet; resolving via packaging tree")
    candidates = []
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass) / "packaging" / "pyinstaller")
    candidates.append(_PROJECT_ROOT / "packaging" / "pyinstaller")
    candidates.append(Path(__file__).resolve().parents[3] / "packaging" / "pyinstaller")
    for base in candidates:
        if (base / "eli_gpu_pack.py").is_file():
            sys.path.insert(0, str(base))
            import eli_gpu_pack
            return eli_gpu_pack
    raise ImportError("eli_gpu_pack not found")


def _dialog_gpus() -> List[Dict[str, Any]]:
    """The GPUs to offer in the start-up window: llama.cpp's own devices when its runtime has any
    (the exact cards and order the loader uses, on CUDA, ROCm, Vulkan, Metal or SYCL), else what
    detection found, marked as not usable until a GPU runtime is installed."""
    try:
        from eli.core import load_plan
        found = load_plan.devices()
    except Exception:
        log.debug("llama.cpp device list unavailable for the start-up window", exc_info=True)
        found = []
    if found:
        return [{"index": d.index, "name": d.description or d.name, "free_mb": d.free_mb, "total_mb": d.total_mb,
                 "integrated": d.integrated, "usable": True} for d in found]
    try:
        from eli.core.hardware_profile import detect_hardware
        return [dict(g, usable=False) for g in (detect_hardware().gpus or [])]
    except Exception:
        return []


class _PlanPreviewThread(QThread):
    """The load plan for the window's current choices, worked out off the window's thread (llama.cpp
    simulates the load: a second or two)."""
    finished_result = pyqtSignal(int, str)

    def __init__(self, generation: int, model_path: str, overrides: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._generation = generation
        self._model_path = model_path
        self._overrides = dict(overrides)

    def run(self):
        try:
            from eli.cognition.gguf_inference import load_request
            from eli.core import load_plan
            plan = load_plan.plan(load_request(self._model_path, **self._overrides))
            text = plan.describe() + "".join(f"\n{note}" for note in plan.notes)
        except Exception as exc:
            log.debug("load plan preview failed", exc_info=True)
            text = f"No plan could be made: {exc}"
        self.finished_result.emit(self._generation, text)


class _GpuPackInstallThread(QThread):
    finished_result = pyqtSignal(int, str)
    progress_text = pyqtSignal(str)

    def __init__(self, argv: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self._argv = list(argv or [])

    def run(self):
        try:
            gp = _import_eli_gpu_pack()
            rc = int(gp.install(self._argv, lambda text, _pct: self.progress_text.emit(text)) or 0)
            msg = ""
            if rc == 0:
                dest = gp._eli_root() / "runtime" / "gpu"
                if not gp.activate_gpu_pack_runtime(dest, verify=True):
                    # Pack is on disk and verified by install — activation can
                    # need a process restart (AppImage already bound CPU llama).
                    # Do NOT surface a stale last_failure() like "no Vulkan wheel".
                    msg = (
                        "GPU pack installed. Restart ELI once so this process "
                        "can load the Vulkan/CUDA runtime (offload was not "
                        "active in this session yet)."
                    )
                    # Soft success — files are good; user must relaunch.
                    rc = 0
                else:
                    msg = "GPU pack installed."
            else:
                msg = gp.last_failure() or "GPU pack install failed."
            self.finished_result.emit(rc, str(msg or ""))
        except Exception as exc:
            self.finished_result.emit(1, str(exc))


def _pack_off_label(default: str) -> str:
    """What to call an inactive GPU backend: installed-but-switched-off is not "not installed"."""
    try:
        gp = _import_eli_gpu_pack()
        if gp.pack_switched_off_by_cpu_choice():
            return "installed, switched off by a CPU-only choice"
        old = gp.outdated_pack()
        if old:
            return f"pack {old} is from an earlier ELI, update it under GPU pack"
    except Exception:
        log.debug("gpu pack state lookup failed", exc_info=True)
    return default


def _pack_is_active() -> bool:
    """--force (re-download) only for an explicit Reinstall of a pack that's working.
    Otherwise the installer's own check skips a verified pack and reinstalls only a
    broken one; the buttons used to force a 1.2 GB download every time."""
    try:
        from eli.core.hardware_profile import _llama_gpu_offload_available
        gp = _import_eli_gpu_pack()
        return bool(gp.gpu_pack_looks_installed(gp._eli_root() / "runtime" / "gpu")
                    and _llama_gpu_offload_available())
    except Exception:
        return False


def _gpu_pack_state() -> Dict[str, Any]:
    """What the GPU pack controls show, for the startup window and the first-run wizard alike.
    The cheap gpu_pack_looks_installed() check comes first: the live probe takes up to 180 s."""
    from eli.core.hardware_profile import detect_hardware, _llama_gpu_offload_available
    gp = _import_eli_gpu_pack()
    backend = gp.pack_backend_for(detect_hardware())
    dest = gp._eli_root() / "runtime" / "gpu"
    old = gp.outdated_pack(dest)
    if (gp.gpu_pack_looks_installed(dest) or gp.gpu_pack_operational(dest)) and _llama_gpu_offload_available():
        text, verb = f"Active ({gp._pack_backend(dest) or 'GPU'}) — layer offload available.", "Reinstall"
    elif gp.pack_switched_off_by_cpu_choice():
        text, verb = ("Installed, but switched off by an earlier \"Use CPU only\" choice. "
                      "Click Enable (no download), then restart ELI."), "Enable"
    elif old:
        text, verb = (f"Installed for an earlier ELI (llama.cpp {old}); this version runs "
                      f"{gp.bundled_runtime_version()}. Click Update to download the matching pack."), "Update"
    elif (dest / "llama_cpp").is_dir():
        text, verb = ("Installed but CPU-only here — reinstall with the backend for this GPU "
                      "(CUDA for NVIDIA, Vulkan for every other GPU)."), "Install"
    else:
        text, verb = "Not installed — optional; CPU inference works without it.", "Install"
    return {"text": text, "verb": verb, "cuda": backend == "cuda", "vulkan": backend != "cuda"}


def _show_gpu_pack_state(owner, status, vulkan_btn, cuda_btn, thread_attr: str) -> None:
    try:
        state = _gpu_pack_state()
        status.setText(state["text"])
        vulkan_btn.setText(f"{state['verb']} Vulkan GPU pack")
        cuda_btn.setText(f"{state['verb']} CUDA GPU pack")
        vulkan_btn.setVisible(state["vulkan"])
        cuda_btn.setVisible(state["cuda"])
        thread = getattr(owner, thread_attr, None)
        busy = thread is not None and thread.isRunning()
        vulkan_btn.setEnabled(not busy)
        cuda_btn.setEnabled(not busy)
    except Exception as exc:
        status.setText(f"GPU pack status unknown ({exc})")


def _install_gpu_pack(owner, *, vulkan: bool, status, buttons, thread_attr: str, refresh, on_done) -> None:
    thread = getattr(owner, thread_attr, None)
    if thread is not None and thread.isRunning():
        return
    if _enable_switched_off_pack(owner):
        refresh()
        return
    _active = _pack_is_active()
    argv: List[str] = ["--force"] if _active else []
    if vulkan:
        argv.append("--vulkan")
    label = "Vulkan" if vulkan else "CUDA"
    if QMessageBox.question(
        owner,
        f"{'Reinstall' if _active else 'Install'} {label} GPU pack",
        _install_question(label, reinstall=_active),
    ) != QMessageBox.StandardButton.Yes:
        return
    status.setText(f"Installing {label} GPU pack…")
    for btn in buttons:
        btn.setEnabled(False)
    thread = _GpuPackInstallThread(argv, parent=owner)
    thread.progress_text.connect(status.setText)
    thread.finished_result.connect(on_done)
    setattr(owner, thread_attr, thread)
    thread.start()


def _install_question(label: str, *, reinstall: bool) -> str:
    """What the confirm dialog says. For a pack that already works, that it works, and why the
    GPU may still look unused: live, a working pack was downloaded again while another program
    held most of the card."""
    if not reinstall:
        return (f"Download and install the {label} GPU acceleration pack now?\n\n"
                "It is downloaded again only when an ELI update moves to a newer llama.cpp. "
                "ELI stays on CPU if verification fails.")
    text = (f"The {label} GPU pack is installed and was verified on this machine. Reinstalling "
            "downloads it again and does not change how much of the GPU ELI can use.")
    try:
        from eli.core.hardware_profile import (describe_vram_holders, get_live_gpu_telemetry,
                                               vram_holders)
        g = get_live_gpu_telemetry()
        held = describe_vram_holders(vram_holders(), total_mb=g.get("total_mb"))
        if g.get("free_mb") is not None and g.get("total_mb"):
            text += (f"\n\nRight now {int(g['free_mb'])} MB of this card's {int(g['total_mb'])} MB "
                     "is free" + (f"; other programs hold: {held}." if held else "."))
    except Exception:
        log.debug("VRAM reading for the reinstall question failed", exc_info=True)
    return text + "\n\nReinstall anyway?"


def _enable_switched_off_pack(parent) -> bool:
    """A verified pack kept off only by an earlier "Use CPU only" choice is switched
    back on, not downloaded again. The Install buttons used to pass --force here and
    re-fetch ~1.2 GB every time (three times in one day, live). True when handled."""
    try:
        gp = _import_eli_gpu_pack()
        if not gp.pack_switched_off_by_cpu_choice() or not gp.enable_installed_pack():
            return False
    except Exception:
        log.debug("gpu pack enable check failed", exc_info=True)
        return False
    QMessageBox.information(
        parent, "GPU pack switched back on",
        "The GPU pack is already installed and verified. An earlier \"Use CPU only\" "
        "choice was keeping it off, so nothing needs downloading.\n\n"
        "It's switched back on. Restart ELI once to load it.")
    return True


def _query_ollama_tags(host: str, timeout: int = 5):
    """Query an Ollama server's /api/tags. Returns (sorted_names_or_None,
    error_or_None); never raises. Loopback is allowed even with NetGuard on
    (see netguard._is_local_host), so localhost:11434 is reachable offline."""
    import json
    import urllib.request
    # Normalise through the client so a scheme-less "localhost:11434" typed here
    # behaves exactly as it does everywhere else, and try the same IPv4 fallback.
    try:
        from eli.integrations.ollama.client import candidate_hosts
        bases = candidate_hosts(host)   # listing never starts Ollama; using an Ollama model does
    except Exception:
        bases = [(host or "http://127.0.0.1:11434").strip().rstrip("/")]
    last = None
    for base in bases:
        try:
            with urllib.request.urlopen(base + "/api/tags", timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            names = sorted(
                m["name"] for m in data.get("models", [])
                if isinstance(m, dict) and m.get("name")
            )
            return names, None
        except Exception as exc:
            last = exc
    return None, last


def _ollama_unreachable_message(host: str, err) -> str:
    """Accurate, OS-specific 'Ollama unreachable' guidance.

    Loopback is always permitted by NetGuard, and a host the owner configured is
    registered as a deliberate local service, so the Net toggle is never the
    answer here — saying otherwise just sent people down the wrong path. What
    actually helps is per-OS instructions for starting Ollama, and (for a remote
    box) the two things that really do block it: the server binding only to
    localhost, and the firewall.
    """
    try:
        from eli.integrations.ollama.client import install_hint, normalise_host
        shown, hint = normalise_host(host), install_hint()
    except Exception:
        shown, hint = (host or "http://127.0.0.1:11434"), "Install Ollama from https://ollama.com"
    h = shown.lower()
    is_loopback = any(x in h for x in ("localhost", "127.", "::1", "0.0.0.0"))
    if is_loopback:
        return (
            f"Could not reach Ollama at {shown}.\n\n"
            "ELI tried to start a local Ollama server automatically but it didn't come "
            f"up — it may not be installed, or it failed to start.\n\n{hint}\n\n"
            "This is a local address, so ELI's offline-by-default guard is not the "
            f"problem — the Net toggle can stay OFF.\n\n{err}"
        )
    return (
        f"Could not reach Ollama at {shown}.\n\n"
        "ELI allows this host (a machine you configured counts as a local service, "
        "like a LAN broker), so check the server instead:\n"
        "  1. Ollama must listen beyond localhost — start it with "
        "OLLAMA_HOST=0.0.0.0:11434 on that machine.\n"
        "  2. Its firewall must allow port 11434.\n"
        f"  3. Confirm the address and port are right.\n\n{err}"
    )


# ── HardwareTuningDock ────────────────────────────────────────────────────────

# Markers for the hardware/load story ELI already writes to the terminal. The
# Hardware Tuning dock showed only the TUNER's own lines, so the panel reported a
# recommendation computed before the model loaded while the load ladder went on to
# select something else — a user comparing the tab against the terminal saw two
# different sets of numbers for the same launch.
#
# These are the prefixes the tuner and the loader already emit. Routing them into
# the dock means the tab shows the same calculation the terminal does, as it
# happens, before and during the load — no second source of truth, and no figure
# computed twice.
HARDWARE_LOG_MARKERS = (
    "[STARTUP_DIALOG][HW_OPT]",
    "[GUI][LOAD]",
    "[LOAD_PLAN]",
    "[HW_AUTHORITY]",
)


class HardwareTuningLogRelay(logging.Handler):
    """Forward ELI's hardware/load log records into the Hardware Tuning dock.

    A handler rather than call sites: the loader, the fit, the probe and the
    optimizer all already log these lines, and duplicating each call would mean
    the tab and the terminal could drift apart. This subscribes to what is
    already written.

    Emits through the dock's signal so the append happens on the GUI thread —
    these records originate on worker threads.
    """

    def __init__(self, dock: "HardwareTuningDock"):
        super().__init__(level=logging.DEBUG)
        self._dock = dock

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            return
        if not any(marker in msg for marker in HARDWARE_LOG_MARKERS):
            return
        dock = self._dock
        if dock is None:
            return
        try:
            dock.log_line.emit(msg)
        except RuntimeError:
            # Dock destroyed (window closed) — detach so we stop trying.
            self._dock = None
            try:
                logging.getLogger().removeHandler(self)
            except Exception:
                logging.getLogger(__name__).debug(
                    "suppressed exception", exc_info=True)
        except Exception:
            # Handler.emit must never raise — a broken dock (or a missing
            # module logger in a unit harness) must not kill the logger.
            logging.getLogger(__name__).debug(
                "suppressed exception", exc_info=True)


class HardwareTuningDock(QDockWidget):
    # The hardware/load story is written by code running on worker threads (the
    # tuner, the load ladder, the subprocess probe). A QPlainTextEdit may only be
    # touched on the GUI thread, so lines arrive as a signal and are appended in
    # the slot. Writing the widget directly from the loader is the Qt bug this
    # avoids.
    log_line = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Hardware Tuning", parent)
        self.log_line.connect(self.append_log)
        self.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea
            | Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.BottomDockWidgetArea
        )
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.status_label = QLabel("Idle")
        self.status_label.setStyleSheet("font-weight:700;color:#88c0d0;")
        layout.addWidget(self.status_label)

        self.summary_label = QLabel("No tuning run yet.")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color:#c8d0e0;")
        layout.addWidget(self.summary_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setPlaceholderText("Hardware tuning logs appear here.")
        layout.addWidget(self.log_view, stretch=1)

        self.setWidget(root)

    def set_status(self, text: str):
        self.status_label.setText(str(text or ""))

    def set_summary(self, text: str):
        self.summary_label.setText(str(text or ""))

    def append_log(self, text: str):
        ts = now_hms()
        self.log_view.appendPlainText(f"[{ts}] {text}")


# ── StartupModelSelectionDialog ───────────────────────────────────────────────

class StartupModelSelectionDialog(QDialog):
    def __init__(
        self,
        *,
        parent=None,
        models: Optional[List[Dict[str, Any]]] = None,
        current_provider: str = "bundled_gguf",
        current_model_path: str = "",
        ollama_host: str = "http://localhost:11434",
        ollama_model: str = "",
        ollama_models: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Startup Model Selection")
        self.setMinimumWidth(760)
        self._models = list(models or [])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        intro = QLabel(
            "Choose which model to load for this session.\n\n"
            "• Bundled / Custom GGUF — runs locally via llama.cpp (fully offline once loaded)\n"
            "• Ollama — uses a model already served by your local Ollama instance "
            "(http://localhost:11434; loopback is allowed even with NetGuard on)\n\n"
            "Hardware tuning applies to GGUF only. Ollama manages its own VRAM."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#c8d0e0;")
        layout.addWidget(intro)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        self.provider_combo = QComboBox()
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS["bundled_gguf"], "bundled_gguf")
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS["custom_gguf"],  "custom_gguf")
        self.provider_combo.addItem(MODEL_PROVIDER_LABELS["ollama"],       "ollama")
        form.addRow("Provider", self.provider_combo)

        self.gguf_combo = QComboBox()
        self.gguf_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for m in self._models:
            self.gguf_combo.addItem(self._model_label(m), str(m.get("path") or ""))
            if m.get("not_chat") or m.get("draft_only"):
                # a draft head (Kimi-K3-DSpark), a vision projector (mmproj) or an embedding model:
                # listed so the folder reads as it is, and not pickable as the model to talk to
                _item = self.gguf_combo.model().item(self.gguf_combo.count() - 1)
                if _item is not None:
                    _item.setEnabled(False)
                    _item.setToolTip(f"Not a chat model: {m.get('not_chat') or 'a draft model'}. "
                                     "It cannot answer on its own.")
        form.addRow("GGUF models", self.gguf_combo)

        self.model_path_input = QLineEdit(current_model_path or "")
        form.addRow("Custom path", self.model_path_input)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_gguf_file)
        form.addRow("", browse_btn)
        self.model_path_input.editingFinished.connect(
            lambda: self._select_model_path(self.model_path_input.text())
            if self.selected_provider() != "ollama" and self.model_path_input.text().strip() else None)

        self.ollama_host_input = QLineEdit(ollama_host or "http://localhost:11434")
        self.ollama_host_input.setToolTip(
            "Local by default. Point ELI at another machine if you like — type it any way "
            "(localhost:11434, 127.0.0.1, 192.168.1.20); ELI fills in the scheme and port. "
            "Works on Windows, macOS and Linux, with the Net toggle off.")
        form.addRow("Ollama host", self.ollama_host_input)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        for name in list(ollama_models or []):
            self.ollama_model_combo.addItem(str(name))
        if ollama_model:
            self.ollama_model_combo.setEditText(ollama_model)
        form.addRow("Ollama model", self.ollama_model_combo)
        refresh_ollama_btn = QPushButton("Refresh Ollama models")
        refresh_ollama_btn.clicked.connect(self._refresh_ollama_models)
        form.addRow("", refresh_ollama_btn)

        # Voice engine — chosen HERE, before hardware tuning / GPU allocation, so a
        # heavy neural voice's VRAM is a deliberate up-front choice on a capable box,
        # while a low-VRAM machine keeps fast Piper and all its VRAM for the model.
        self.tts_engine_combo = QComboBox()
        self.tts_engine_combo.addItem("Piper — fast, low VRAM (recommended)", "piper")
        self.tts_engine_combo.addItem("Natural neural (XTTS-v2) — human-like, uses GPU/VRAM", "natural")
        self.tts_engine_combo.setToolTip(
            "Piper is fast and light and runs anywhere. The natural neural voice (XTTS-v2) "
            "sounds human — expressive, punctuation-aware — but needs the voice extra "
            "(downloads ~1.8GB on first use) and more VRAM/compute. Pick it on a capable "
            "machine; ELI falls back to Piper automatically if it can't load.")
        try:
            from eli.core.runtime_settings import load_settings as _ls
            _cur_engine = str((_ls() or {}).get("tts_engine", "piper")).lower()
            _ei = self.tts_engine_combo.findData(_cur_engine)
            if _ei >= 0:
                self.tts_engine_combo.setCurrentIndex(_ei)
        except Exception:
            log.debug("[STARTUP] tts_engine preselect failed", exc_info=True)
        form.addRow("Voice engine", self.tts_engine_combo)
        layout.addLayout(form)

        self.auto_tune_checkbox = QCheckBox(
            "Hardware tuning is required for GGUF and runs before load"
        )
        self.auto_tune_checkbox.setChecked(True)
        self.auto_tune_checkbox.setEnabled(False)
        layout.addWidget(self.auto_tune_checkbox)

        # Direct context-window control. Pre-fills with YOUR last chosen ctx so the
        # dialog reflects what you actually picked — never a hardcoded number. Source
        # order (first available wins): ELI_FORCE_CTX env (set in-session) → saved
        # settings n_ctx (your last choice, persisted, for this model) → 0 = auto
        # (fraction/VRAM sizing). Applied as ELI_FORCE_CTX, the optimizer's
        # highest-priority override.
        # A saved context belongs to the MODEL it was chosen for. Carrying it to a
        # different model is wrong in both directions: a 12,192 picked for an 8B
        # with a 32k training length was still showing after switching to a
        # 30B whose trained context is 1,048,576 — the operator's "setting" was a
        # number computed for a model they were no longer running. Nothing here
        # invents a value: when the model has changed, it falls back to 0, which
        # this box already documents as "auto" and which the optimizer resolves
        # as fraction x THAT model's trained length, fitted to real VRAM.
        _saved_ctx, _saved_for = 0, ""
        try:
            from eli.core.runtime_settings import load_settings as _rs_load
            _s = _rs_load() or {}
            _saved_ctx = int(_s.get("n_ctx", 0) or 0)
            # ONLY the explicit association counts. settings["model_path"] is
            # rewritten whenever a model loads, while n_ctx is not — so comparing
            # against it would always look like a match and the stale context
            # would survive exactly the switch this is meant to catch.
            _saved_for = str(_s.get("n_ctx_model") or "")
        except Exception:
            _saved_ctx, _saved_for = 0, ""

        _selected_model = str(current_model_path or "")
        _same_model = bool(_saved_for) and bool(_selected_model) and (
            Path(_saved_for).name == Path(_selected_model).name
        )

        _env_ctx = (os.environ.get("ELI_FORCE_CTX") or "").strip()
        if _env_ctx.isdigit() and int(_env_ctx) > 0:
            _initial_ctx = int(_env_ctx)            # explicit in-session override
        elif _saved_ctx > 0 and _same_model:
            _initial_ctx = _saved_ctx               # your last choice, for THIS model
        else:
            # Auto. Deliberately not a constant: 16384 was as arbitrary for a 1M
            # model as for a 4k one, and "auto" already derives per model.
            _initial_ctx = 0
        self.ctx_window_spin = QSpinBox()
        # no ceiling of ELI's own: the planner holds the window to what the model was trained on and
        # what the machine has room for (eli/core/load_plan.py); a QSpinBox counts in int32
        self.ctx_window_spin.setRange(0, 2_147_483_647)
        self.ctx_window_spin.setSingleStep(2048)
        self.ctx_window_spin.setValue(_initial_ctx)
        form.addRow("Context window (tokens, 0=auto)", self.ctx_window_spin)

        self.ctx_fraction_spin = QDoubleSpinBox()
        self.ctx_fraction_spin.setRange(0.10, 0.95)
        self.ctx_fraction_spin.setSingleStep(0.05)
        self.ctx_fraction_spin.setDecimals(2)
        # Default MUST match the optimizer + gguf loader default (0.9). A lower GUI
        # default (was 0.65) silently capped launch ctx to 0.65×train even when VRAM
        # had room, and diverged from the headless path that assumes 0.9 — so the ctx a
        # model loaded with depended on whether this dialog had ever been opened. One
        # source of truth: VRAM stays the real limiter; this is just the train-ctx cap.
        self.ctx_fraction_spin.setValue(float(os.environ.get("ELI_CTX_FRACTION", "0.9")))
        form.addRow("Context target fraction", self.ctx_fraction_spin)

        self.target_batch_spin = QSpinBox()
        self.target_batch_spin.setRange(1, 2_147_483_647)     # llama.cpp holds it to the context
        self.target_batch_spin.setSingleStep(16)
        # Default from the hardware, not a constant. 256 was the same number on
        # every machine and for every model; hardware_profile.recommend() already
        # derives a batch from the detected GPU/VRAM (128 on the card this was
        # diagnosed on). An explicit ELI_TARGET_BATCH still wins.
        _env_batch = (os.environ.get("ELI_TARGET_BATCH") or "").strip()
        if _env_batch.isdigit() and int(_env_batch) > 0:
            _initial_batch = int(_env_batch)
        else:
            try:
                from eli.core.hardware_profile import detect_hardware as _dh, recommend as _rec
                _initial_batch = int(getattr(_rec(_dh()), "batch_size", 0) or 0)
            except Exception:
                _initial_batch = 0
            if _initial_batch <= 0:
                # No hardware read — leave the box at its own minimum rather than
                # asserting a number for a machine we could not inspect.
                _initial_batch = self.target_batch_spin.minimum()
        self.target_batch_spin.setValue(_initial_batch)
        form.addRow("Target batch", self.target_batch_spin)

        self.compute_mode_combo = QComboBox()
        self._populate_compute_mode_combo()
        self.compute_mode_combo.setToolTip(
            "Auto uses GPU when a backend is installed. GPU tries layer offload "
            "(install the GPU pack on AppImage/portable if needed). CPU keeps all "
            "inference on the processor — recommended on integrated-GPU laptops until "
            "the Vulkan pack is installed."
        )
        form.addRow("Compute mode", self.compute_mode_combo)

        self.moe_offload_combo = QComboBox()
        self.moe_offload_combo.addItem("Auto — only when a mixture-of-experts model does not fit the GPU", "auto")
        self.moe_offload_combo.addItem("On — experts in RAM, all layers on the GPU", "on")
        self.moe_offload_combo.addItem("Off — split by layers", "off")
        self.moe_offload_combo.setToolTip(
            "Mixture-of-experts models only. Keeps the expert weights in system memory and the rest on the GPU, "
            "which is usually much faster on a small card. Needs RAM for the experts."
        )
        try:
            from eli.core.runtime_settings import load_settings as _ls_moe
            _moe_saved = str((_ls_moe() or {}).get("moe_expert_offload") or "auto").lower()
            _moe_i = self.moe_offload_combo.findData(_moe_saved)
            if _moe_i >= 0:
                self.moe_offload_combo.setCurrentIndex(_moe_i)
        except Exception:
            log.debug("moe_expert_offload preselect failed", exc_info=True)
        form.addRow("Expert offload (MoE)", self.moe_offload_combo)

        from eli.core.hardware_profile import (
            RAM_BUDGET_PERCENT_DEFAULT,
            RAM_BUDGET_PERCENT_MAX,
            RAM_BUDGET_PERCENT_MIN,
        )
        self.ram_budget_spin = QSpinBox()
        self.ram_budget_spin.setRange(RAM_BUDGET_PERCENT_MIN, RAM_BUDGET_PERCENT_MAX)
        self.ram_budget_spin.setSingleStep(5)
        self.ram_budget_spin.setSuffix(" %")
        _initial_ram_pct = RAM_BUDGET_PERCENT_DEFAULT
        try:
            from eli.core.runtime_settings import load_settings as _ls_ram
            _initial_ram_pct = int((_ls_ram() or {}).get(
                "ram_budget_percent", RAM_BUDGET_PERCENT_DEFAULT))
        except Exception:
            log.debug("ram_budget_percent preselect failed", exc_info=True)
        _env_ram = (os.environ.get("ELI_RAM_BUDGET_PERCENT") or "").strip()
        if _env_ram.isdigit():
            _initial_ram_pct = int(_env_ram)
        self.ram_budget_spin.setValue(
            max(RAM_BUDGET_PERCENT_MIN,
                min(RAM_BUDGET_PERCENT_MAX, int(_initial_ram_pct))))
        self.ram_budget_spin.setToolTip(
            "How much of your free system RAM ELI may use for model weights and "
            "KV cache when sizing context, batch, and layers. Lower this on "
            "8 GB laptops if the OS feels tight; raise it (up to 75%) when you "
            "want a larger context on CPU or shared-memory GPUs."
        )
        form.addRow("RAM for model (max 75%)", self.ram_budget_spin)

        from eli.core.hardware_profile import fit_priority as _default_fit_priority
        self.fit_priority_combo = QComboBox()
        self.fit_priority_combo.addItem(
            "Balanced — preserve context, trade GPU speed", "balanced")
        self.fit_priority_combo.addItem(
            "Max GPU — fill VRAM with layers first", "max_gpu")
        self.fit_priority_combo.addItem(
            "Max context — use RAM spill for larger windows", "max_ctx")
        _initial_fit = _default_fit_priority()
        try:
            from eli.core.runtime_settings import load_settings as _ls_fit
            _initial_fit = str((_ls_fit() or {}).get("fit_priority") or _initial_fit)
        except Exception:
            log.debug("fit_priority preselect failed", exc_info=True)
        _env_fit = (os.environ.get("ELI_FIT_PRIORITY") or "").strip().lower()
        if _env_fit:
            _initial_fit = _env_fit
        _fit_idx = self.fit_priority_combo.findData(_initial_fit.replace("-", "_"))
        if _fit_idx < 0:
            _fit_idx = self.fit_priority_combo.findData("balanced")
        if _fit_idx >= 0:
            self.fit_priority_combo.setCurrentIndex(_fit_idx)
        self.fit_priority_combo.setToolTip(
            "How ELI trades VRAM vs system RAM on discrete GPUs. Balanced keeps "
            "your context and sheds GPU layers first. Max GPU shrinks context "
            "before dropping layers. Max context spills weights to RAM for the "
            "largest window your RAM slider allows."
        )
        form.addRow("Hardware fit profile", self.fit_priority_combo)

        # Which GPUs, and how the model is split across them. Empty "gpu_devices" means every card;
        # "tensor_split" set means the operator's shares, empty means the planner's own split by
        # each card's free memory.
        try:
            from eli.core.runtime_settings import load_settings as _ls_gpu
            _gpu_saved = _ls_gpu() or {}
        except Exception:
            _gpu_saved = {}
        _chosen_gpus = {int(x) for x in str(_gpu_saved.get("gpu_devices") or "").split(",") if x.strip().isdigit()}
        _saved_split = [x for x in str(_gpu_saved.get("tensor_split") or "").split(",") if x.strip()]
        self._gpus = _dialog_gpus()
        self._gpu_rows: List[tuple] = []
        self.gpu_split_combo = QComboBox()
        self.gpu_split_combo.addItem("Automatic — measured, by each card's free memory", "auto")
        self.gpu_split_combo.addItem("Manual — the shares set below", "manual")
        if self._gpus:
            _grid_host = QWidget()
            _grid = QGridLayout(_grid_host)
            _grid.setContentsMargins(0, 0, 0, 0)
            for _row, _g in enumerate(self._gpus):
                _cb = QCheckBox(f"GPU {_g['index']}: {_g['name']} — {float(_g.get('free_mb') or 0) / 1024:.1f} of "
                                f"{float(_g.get('total_mb') or 0) / 1024:.1f} GB free"
                                + ("" if _g.get("usable") else " (needs a GPU pack)"))
                _cb.setChecked(not _chosen_gpus or int(_g["index"]) in _chosen_gpus)
                _cb.setEnabled(bool(_g.get("usable")))
                _share = QSpinBox()
                _share.setRange(1, 100)
                _share.setSuffix(" %")
                _share.setToolTip("This card's share of the model's layers (llama.cpp's tensor split). Its "
                                  "memory use also depends on which layers hold the most cache: in some "
                                  "models the first layers do. The load plan shows what each card will hold.")
                try:
                    _share.setValue(int(round(float(_saved_split[_row]) * 100))
                                    if len(_saved_split) == len(self._gpus) else int(round(100 / len(self._gpus))))
                except (ValueError, IndexError):
                    _share.setValue(int(round(100 / len(self._gpus))))
                _grid.addWidget(_cb, _row, 0)
                _grid.addWidget(_share, _row, 1)
                self._gpu_rows.append((int(_g["index"]), _cb, _share))
                _cb.toggled.connect(lambda _on: self._schedule_plan_preview())
                _share.valueChanged.connect(lambda _v: self._schedule_plan_preview())
            _grid_host.setToolTip("Untick a card to keep the model off it; one card ticked is single-GPU mode.")
            form.addRow("GPUs", _grid_host)
            if len(_saved_split) == len(self._gpus) and len(self._gpus) > 1:
                self.gpu_split_combo.setCurrentIndex(1)
            if len(self._gpus) > 1:
                form.addRow("Split across GPUs", self.gpu_split_combo)
            self.gpu_split_combo.currentIndexChanged.connect(lambda _i: self._sync_gpu_split_controls())
        self.plan_preview_label = QLabel("")
        self.plan_preview_label.setWordWrap(True)
        self.plan_preview_label.setStyleSheet("color:#9aa5b5;font-size:11px;")
        form.addRow("Load plan", self.plan_preview_label)
        self._plan_generation = 0
        self._plan_threads: List[QThread] = []
        self._plan_timer = QTimer(self)
        self._plan_timer.setSingleShot(True)
        self._plan_timer.timeout.connect(self._start_plan_preview)
        self._sync_gpu_split_controls()

        self.gpu_pack_status_label = QLabel("")
        self.gpu_pack_status_label.setWordWrap(True)
        self.gpu_pack_status_label.setStyleSheet("color:#9aa5b5;font-size:11px;")
        form.addRow("GPU pack", self.gpu_pack_status_label)
        _gpu_btn_row = QHBoxLayout()
        self.gpu_pack_vulkan_btn = QPushButton("Install Vulkan GPU pack")
        self.gpu_pack_vulkan_btn.clicked.connect(
            lambda: self._start_gpu_pack_install(vulkan=True))
        self.gpu_pack_cuda_btn = QPushButton("Install CUDA GPU pack")
        self.gpu_pack_cuda_btn.clicked.connect(
            lambda: self._start_gpu_pack_install(vulkan=False))
        _gpu_btn_row.addWidget(self.gpu_pack_vulkan_btn)
        _gpu_btn_row.addWidget(self.gpu_pack_cuda_btn)
        _gpu_btn_host = QWidget()
        _gpu_btn_host.setLayout(_gpu_btn_row)
        form.addRow("", _gpu_btn_host)

        self.hw_summary_label = QLabel("")
        self.hw_summary_label.setWordWrap(True)
        self.hw_summary_label.setStyleSheet("color:#9aa5b5;font-size:11px;")
        form.addRow("This machine", self.hw_summary_label)
        self.ram_budget_spin.valueChanged.connect(self._on_ram_budget_changed)
        self.fit_priority_combo.currentIndexChanged.connect(self._on_fit_profile_changed)
        self.ctx_window_spin.valueChanged.connect(lambda _v: self._refresh_hw_summary())
        self.target_batch_spin.valueChanged.connect(lambda _v: self._refresh_hw_summary())
        self.model_path_input.textChanged.connect(lambda _t: self._refresh_hw_summary())
        self.gguf_combo.currentIndexChanged.connect(lambda _i: self._refresh_hw_summary())
        self.compute_mode_combo.currentIndexChanged.connect(lambda _i: self._schedule_plan_preview())
        self._refresh_hw_summary()
        self._refresh_gpu_pack_controls()

        self.vram_reserve_spin = QSpinBox()
        # 0 = measured: what llama.cpp takes on each card after a load is measured on this machine and
        # left free from then on (eli/core/load_plan.py, headroom). A figure here is used as given.
        self.vram_reserve_spin.setRange(0, int(max([float(g.get("total_mb") or 0) for g in self._gpus], default=0))
                                        or 2_147_483_647)
        self.vram_reserve_spin.setSingleStep(max(1, int(self.vram_reserve_spin.maximum() // 64)))
        _reserve_env = (os.environ.get("ELI_VRAM_RESERVE_MB") or "").strip()
        self.vram_reserve_spin.setValue(int(_reserve_env) if _reserve_env.isdigit() else 0)
        self.vram_reserve_spin.setSpecialValueText("measured")
        self.vram_reserve_spin.setToolTip(
            "GPU memory to keep free beyond what the model takes. \"measured\": ELI measures what llama.cpp "
            "uses on each card after loading and keeps exactly that free; before the first measurement it "
            "keeps llama.cpp's own working-buffer figure free.")
        form.addRow("GPU memory kept free (MB)", self.vram_reserve_spin)

        self.model_train_ctx_spin = QSpinBox()
        self.model_train_ctx_spin.setRange(0, 2_147_483_647)
        self.model_train_ctx_spin.setSingleStep(2048)
        self.model_train_ctx_spin.setValue(int(os.environ.get("ELI_MODEL_TRAIN_CTX", "0")))
        form.addRow("Model train ctx (0=auto)", self.model_train_ctx_spin)

        self.load_now_checkbox = QCheckBox("Load selected model now")
        self.load_now_checkbox.setChecked(True)
        layout.addWidget(self.load_now_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )

        def _apply_env():
            # Direct context window wins (0 = auto → let fraction/VRAM size it).
            _ctx_window = int(self.ctx_window_spin.value())
            if _ctx_window > 0:
                os.environ["ELI_FORCE_CTX"] = str(_ctx_window)
            else:
                os.environ.pop("ELI_FORCE_CTX", None)
            # Record WHICH model this context was chosen for, so the next launch
            # can tell a deliberate setting from a leftover. Without it there is
            # no way to distinguish "the operator wants 12192 for this model"
            # from "12192 is what the last, different model happened to use".
            try:
                from eli.core.runtime_settings import update_settings as _rs_update
                _chosen_for = (self.model_path_input.text().strip()
                               or str(current_model_path or ""))
                if _ctx_window > 0 and _chosen_for:
                    _rs_update(n_ctx_model=str(Path(_chosen_for).name))
                elif _ctx_window <= 0:
                    _rs_update(n_ctx_model="")     # back to auto — no association
            except Exception:
                # Observable, not swallowed: if this never lands the context
                # silently stops being remembered per model and the staleness
                # this fixes comes straight back, with nothing to show why.
                log.debug("could not record the context/model association", exc_info=True)
            # Commit whatever is still being TYPED before reading it. A Qt spin
            # box holds the editor's text until it is interpreted, so a value
            # typed and then followed straight by a click on Start can be read
            # back as the previous one — the operator sets 256 and the settings
            # file records 128. interpretText() is the documented remedy and is
            # a no-op when nothing is pending, so it costs nothing to always do.
            for _spin in (self.ctx_fraction_spin, self.target_batch_spin,
                          self.ram_budget_spin, self.vram_reserve_spin,
                          self.model_train_ctx_spin):
                try:
                    _spin.interpretText()
                except Exception:
                    log.debug("spin box interpretText failed", exc_info=True)
            _ram_pct = int(self.ram_budget_spin.value())
            os.environ["ELI_RAM_BUDGET_PERCENT"] = str(_ram_pct)
            _fit_mode = str(self.fit_priority_combo.currentData() or "balanced")
            os.environ["ELI_FIT_PRIORITY"] = _fit_mode
            try:
                from eli.core.runtime_settings import update_settings as _rs_ram
                _rs_ram(ram_budget_percent=_ram_pct, fit_priority=_fit_mode)
            except Exception:
                log.debug("ram_budget_percent persist failed", exc_info=True)
            _gpu_choice = self._gpu_choice()
            for _env, _val in (("ELI_GPU_DEVICES", _gpu_choice["gpu_devices"]),
                               ("ELI_GGUF_TENSOR_SPLIT", _gpu_choice["tensor_split"])):
                if _val:
                    os.environ[_env] = _val
                else:
                    os.environ.pop(_env, None)
            try:
                from eli.core.runtime_settings import update_settings as _rs_gpu
                _rs_gpu(gpu_devices=_gpu_choice["gpu_devices"], tensor_split=_gpu_choice["tensor_split"])
            except Exception:
                log.debug("GPU choice persist failed", exc_info=True)
            os.environ["ELI_CTX_FRACTION"] = str(float(self.ctx_fraction_spin.value()))
            os.environ["ELI_TARGET_BATCH"]  = str(int(self.target_batch_spin.value()))
            if int(self.vram_reserve_spin.value()) > 0:
                os.environ["ELI_VRAM_RESERVE_MB"] = str(int(self.vram_reserve_spin.value()))
            else:
                os.environ.pop("ELI_VRAM_RESERVE_MB", None)        # measured
            _cmode = str(self.compute_mode_combo.currentData() or "auto")
            try:
                from eli.core.runtime_settings import update_settings as _rs_cm
                _cm_updates: Dict[str, Any] = {"compute_mode": _cmode}
                if _cmode == "cpu":
                    os.environ["ELI_FORCE_GPU_LAYERS"] = "0"
                    _cm_updates["n_gpu_layers"] = 0
                else:
                    os.environ.pop("ELI_FORCE_GPU_LAYERS", None)
                _rs_cm(**_cm_updates)
            except Exception:
                log.debug("compute_mode persist failed", exc_info=True)
            _moe_mode = str(self.moe_offload_combo.currentData() or "auto")
            os.environ["ELI_MOE_EXPERT_OFFLOAD"] = _moe_mode
            try:
                from eli.core.runtime_settings import update_settings as _rs_moe
                _rs_moe(moe_expert_offload=_moe_mode)
            except Exception:
                log.debug("moe_expert_offload persist failed", exc_info=True)
            if int(self.model_train_ctx_spin.value()) > 0:
                os.environ["ELI_MODEL_TRAIN_CTX"] = str(int(self.model_train_ctx_spin.value()))
            else:
                os.environ.pop("ELI_MODEL_TRAIN_CTX", None)

        _old_accept = super().accept

        def _accept_wrapper():
            _apply_env()
            # Preload faster-whisper FIRST (warmed up on a GPU) so the memory it holds is taken before
            # the language model is planned against what each card has free; otherwise the plan
            # filled the card and Whisper ran out of memory on the first utterance.
            try:
                from eli.perception.local_whisper_stt import preload_model as _eli_preload_whisper
                if _eli_preload_whisper():
                    log.debug(
                        "[STARTUP_DIALOG][AUDIO_PRELOAD] whisper claimed VRAM "
                        "before GGUF autotune",
                    )
            except Exception as _wp_err:
                log.debug(f"[STARTUP_DIALOG][AUDIO_PRELOAD] skipped: {_wp_err}")
            try:
                selected_path = self.model_path_input.text().strip()
                if selected_path:
                    os.environ["ELI_MODEL_PATH"] = selected_path
                # Whisper is loaded first, so the load plan measures what each card has free after it
                # and sizes the batch from that (eli/core/load_plan.py). A fixed batch of 128 used to be
                # forced whenever Whisper ran on the GPU, whatever the card.
                from eli.core.hardware_profile import (
                    detect_hardware as _hp_detect,
                    discover_models as _hp_models,
                    recommend as _hp_recommend,
                    apply_recommendation as _hp_apply,
                    _is_embedder_path as _hp_is_embedder,
                )
                _hw   = _hp_detect(force=True)
                _mods = _hp_models()
                # Compute hw-profile specifically for the model the user chose,
                # not for the largest model that partially fits on GPU. Without
                # this, a 24B model on disk gets chosen (12 layers, batch=192)
                # and those params are applied to the 7B the user actually loads.
                _sel = (self.model_path_input.text().strip()
                        or str(self.gguf_combo.currentData() or "").strip())
                _rec_models = _mods
                if _sel:
                    try:
                        _sp = Path(_sel).expanduser().resolve()
                        if (_sp.exists() and _sp.suffix.lower() == ".gguf"
                                and not _hp_is_embedder(_sp)):
                            _sz = _sp.stat().st_size
                            _rec_models = [{
                                "name": _sp.name,
                                "path": str(_sp),
                                "size_bytes": _sz,
                                "size_gb": bytes_to_gib(_sz),
                            }]
                    except Exception:
                        log.debug("suppressed exception", exc_info=True)
                # Honour the user's "Direct context window" choice (ELI_FORCE_CTX,
                # just set by _apply_env) so the regenerated profile reflects what
                # they asked for — not the auto target.
                _forced_ctx = (os.environ.get("ELI_FORCE_CTX") or "").strip()
                _pin_ctx = int(_forced_ctx) if _forced_ctx.isdigit() and int(_forced_ctx) > 0 else None
                _rec  = _hp_recommend(_hw, _rec_models, user_ctx=_pin_ctx)
                _hp_apply(_rec)
                log.debug(
                    "[STARTUP_DIALOG][HW_OPT] regenerated profile "
                    f"ctx={_rec.n_ctx} gpu_layers={_rec.n_gpu_layers} "
                    f"batch={_rec.batch_size} gpu={_hw.gpu_name} "
                    f"free_vram={_hw.free_vram_mb}MB"
                )
            except Exception as _err:
                log.debug(f"[STARTUP_DIALOG][HW_OPT] regeneration failed: {_err}")
            _old_accept()

        self.accept = _accept_wrapper
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.provider_combo.currentIndexChanged.connect(self._sync_provider_controls)
        self.gguf_combo.currentIndexChanged.connect(self._sync_model_path_from_combo)

        provider_idx = self.provider_combo.findData(current_provider)
        if provider_idx >= 0:
            self.provider_combo.setCurrentIndex(provider_idx)
        self._select_model_path(current_model_path)
        self._sync_provider_controls()

    def _fetch_ollama_names(self, timeout: int = 5):
        host = self.ollama_host_input.text().strip() or "http://localhost:11434"
        return _query_ollama_tags(host, timeout)

    def _populate_ollama_combo(self, names):
        current = self.ollama_model_combo.currentText().strip()
        self.ollama_model_combo.clear()
        for name in names:
            self.ollama_model_combo.addItem(name)
        if current:
            idx = self.ollama_model_combo.findText(current)
            if idx >= 0:
                self.ollama_model_combo.setCurrentIndex(idx)
            else:
                self.ollama_model_combo.setEditText(current)

    def _auto_load_ollama_models(self):
        """Populate the Ollama model list automatically when the user picks the
        Ollama provider — the models must appear WITHOUT hunting for a Refresh
        button (the reported "can't select my Ollama models" gap). Quiet on
        failure (short timeout, no modal); the explicit Refresh button gives the
        full 'Ollama unreachable' diagnostic when the user asks for it."""
        if self.ollama_model_combo.count() > 0:
            return
        names, err = self._fetch_ollama_names(timeout=2)
        if names:
            self._populate_ollama_combo(names)

    def _refresh_ollama_models(self):
        host = self.ollama_host_input.text().strip() or "http://localhost:11434"
        names, err = self._fetch_ollama_names(timeout=5)
        if err is not None:
            QMessageBox.warning(self, "Ollama unreachable",
                                _ollama_unreachable_message(host, err))
            return
        if not names:
            QMessageBox.information(
                self, "No Ollama models",
                f"Ollama is running at {host} but no models are installed yet.\n"
                "Pull one first, e.g.  ollama pull llama3",
            )
            return
        self._populate_ollama_combo(names)

    def _browse_gguf_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select GGUF Model",
            str(_MODELS_DIR),
            "GGUF Files (*.gguf);;All Files (*)",
        )
        if file_path:
            idx = self.provider_combo.findData("custom_gguf")
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)
            self._select_model_path(file_path)    # the list shows what will load, not the last pick

    def _populate_compute_mode_combo(self) -> None:
        self.compute_mode_combo.clear()
        self.compute_mode_combo.addItem("Auto — GPU when available, else CPU", "auto")
        self.compute_mode_combo.addItem("GPU acceleration (CUDA / Vulkan pack)", "gpu")
        self.compute_mode_combo.addItem("CPU only — no GPU layers", "cpu")
        _saved = "auto"
        try:
            from eli.core.runtime_settings import load_settings as _ls_cm
            _saved = str((_ls_cm() or {}).get("compute_mode") or "auto").lower()
        except Exception:
            pass
        _idx = self.compute_mode_combo.findData(_saved if _saved in ("auto", "gpu", "cpu") else "auto")
        if _idx >= 0:
            self.compute_mode_combo.setCurrentIndex(_idx)
        try:
            from eli.core.gpu_pack_runtime import try_activate_gpu_pack
            try_activate_gpu_pack(verify=True)
            from eli.core.hardware_profile import detect_hardware, _llama_gpu_offload_available
            _hw = detect_hardware()
            if _hw.has_gpu and not _llama_gpu_offload_available() and _saved in ("auto", "gpu"):
                _cpu_idx = self.compute_mode_combo.findData("cpu")
                if _cpu_idx >= 0:
                    self.compute_mode_combo.setCurrentIndex(_cpu_idx)
        except Exception:
            log.debug("compute_mode default probe failed", exc_info=True)

    def _on_ram_budget_changed(self, _value: int) -> None:
        os.environ["ELI_RAM_BUDGET_PERCENT"] = str(int(self.ram_budget_spin.value()))
        self._refresh_hw_summary()

    def _on_fit_profile_changed(self, _index: int) -> None:
        _mode = str(self.fit_priority_combo.currentData() or "balanced")
        os.environ["ELI_FIT_PRIORITY"] = _mode
        self._refresh_hw_summary()

    def _refresh_hw_summary(self) -> None:
        try:
            from eli.core.hardware_profile import (
                cpu_ram_budget_mb,
                detect_hardware,
                _llama_gpu_offload_available,
                integrated_gpu_label,
            )
            _hw = detect_hardware(force=True)
            _backend = _llama_gpu_offload_available()
            _ram_pct = int(self.ram_budget_spin.value())
            os.environ["ELI_RAM_BUDGET_PERCENT"] = str(_ram_pct)
            _fit_mode = str(self.fit_priority_combo.currentData() or "balanced")
            os.environ["ELI_FIT_PRIORITY"] = _fit_mode
            _ram_budget = cpu_ram_budget_mb(
                _hw.available_ram_gb, fraction=_ram_pct / 100.0)
            # How the chosen model will load is the load plan below (the loader's own planner);
            # this line is the machine.
            self._schedule_plan_preview()
            if not _hw.has_gpu:
                txt = (
                    f"CPU: {_hw.cpu_threads} threads  |  "
                    f"RAM: {_hw.ram_gb:.1f} GB ({_hw.available_ram_gb:.1f} GB free)  |  "
                    f"model budget ~{_ram_budget} MB"
                )
            elif _hw.gpu_integrated:
                _kind = integrated_gpu_label(_hw.gpu_name, _hw.gpu_vendor)
                txt = (
                    f"{_kind}  |  RAM: {_hw.ram_gb:.1f} GB  |  "
                    f"shared budget ~{_hw.free_vram_mb} MB  |  "
                    f"model RAM cap ~{_ram_budget} MB  |  "
                    f"GPU backend: {'active' if _backend else _pack_off_label('not installed (CPU until GPU pack)')}"
                )
            else:
                txt = (
                    f"{_hw.gpu_name}  |  "
                    f"VRAM {_hw.free_vram_mb}/{_hw.total_vram_mb} MB  |  "
                    f"RAM spill budget ~{_ram_budget} MB ({_ram_pct}%)  |  "
                    f"GPU backend: {'active' if _backend else _pack_off_label('not installed')}"
                )
                try:
                    from eli.core.hardware_profile import describe_vram_holders, vram_holders
                    _held = describe_vram_holders(vram_holders(), total_mb=_hw.total_vram_mb)
                    if _held:
                        txt += f"\nVRAM in use by other programs: {_held}"
                except Exception:
                    log.debug("VRAM holders unavailable for the summary", exc_info=True)
            self.hw_summary_label.setText(txt)
        except Exception as exc:
            self.hw_summary_label.setText(f"Hardware probe pending ({exc})")

    def _gpu_choice(self) -> Dict[str, Any]:
        """The window's GPU choices as the loader reads them: gpu_devices ("" = every card),
        tensor_split ("" = the planner's own split), cpu_only when no card is ticked."""
        rows = getattr(self, "_gpu_rows", []) or []
        usable = [r for r in rows if r[1].isEnabled()]
        ticked = [r for r in usable if r[1].isChecked()]
        devices = "" if len(ticked) == len(usable) else ",".join(str(i) for i, _cb, _sp in ticked)
        split = ""
        if (len(ticked) > 1 and getattr(self, "gpu_split_combo", None) is not None
                and self.gpu_split_combo.currentData() == "manual"):
            total = float(sum(sp.value() for _i, cb, sp in usable if cb.isChecked())) or 1.0
            split = ",".join(f"{(sp.value() / total) if cb.isChecked() else 0.0:.3f}" for _i, cb, sp in usable)
        return {"gpu_devices": devices, "tensor_split": split, "cpu_only": bool(usable) and not ticked}

    def _sync_gpu_split_controls(self) -> None:
        manual = getattr(self, "gpu_split_combo", None) is not None and self.gpu_split_combo.currentData() == "manual"
        for _i, cb, share in getattr(self, "_gpu_rows", []) or []:
            share.setEnabled(manual and cb.isEnabled())
            share.setVisible(len(self._gpu_rows) > 1)
        self._schedule_plan_preview()

    def _schedule_plan_preview(self) -> None:
        """Plan again shortly after the choices stop changing."""
        timer = getattr(self, "_plan_timer", None)
        if timer is not None:
            timer.start(600)

    def _start_plan_preview(self) -> None:
        model_path = self.model_path_input.text().strip()
        if not model_path or not Path(model_path).is_file():
            self.plan_preview_label.setText("Choose a model to see how it will load.")
            return
        choice = self._gpu_choice()
        overrides: Dict[str, Any] = {
            "n_ctx": int(self.ctx_window_spin.value()),
            "n_batch": int(self.target_batch_spin.value()),
            "fit_priority": str(self.fit_priority_combo.currentData() or "balanced"),
            "gpu_devices": choice["gpu_devices"], "tensor_split": choice["tensor_split"],
            "cpu_only": choice["cpu_only"] or str(self.compute_mode_combo.currentData() or "auto") == "cpu",
        }
        self._plan_generation += 1
        self.plan_preview_label.setText("Working out how the model will load…")
        worker = _PlanPreviewThread(self._plan_generation, model_path, overrides, self)
        worker.finished_result.connect(self._on_plan_preview)
        worker.finished.connect(lambda: self._plan_threads.remove(worker) if worker in self._plan_threads else None)
        self._plan_threads.append(worker)
        worker.start()

    def _on_plan_preview(self, generation: int, text: str) -> None:
        if generation == self._plan_generation:     # a newer choice has a newer plan coming
            self.plan_preview_label.setText(text)

    def _refresh_gpu_pack_controls(self) -> None:
        _show_gpu_pack_state(self, self.gpu_pack_status_label, self.gpu_pack_vulkan_btn,
                             self.gpu_pack_cuda_btn, "_gpu_pack_thread")

    def _start_gpu_pack_install(self, *, vulkan: bool) -> None:
        _install_gpu_pack(self, vulkan=vulkan, status=self.gpu_pack_status_label,
                          buttons=(self.gpu_pack_vulkan_btn, self.gpu_pack_cuda_btn),
                          thread_attr="_gpu_pack_thread", refresh=self._refresh_gpu_pack_controls,
                          on_done=self._on_gpu_pack_install_done)

    def _on_gpu_pack_install_done(self, rc: int, message: str) -> None:
        if rc == 0:
            soft = "restart" in str(message or "").lower()
            self.gpu_pack_status_label.setText(
                message if soft else
                "GPU pack active — Vulkan/CUDA offload enabled for this session."
            )
            if soft:
                QMessageBox.information(
                    self, "GPU pack installed",
                    f"{message}\n\nELI will use CPU until you relaunch.",
                )
            else:
                try:
                    from eli.core.runtime_settings import update_settings as _rs_gp
                    _rs_gp(compute_mode="gpu")
                    _gpu_idx = self.compute_mode_combo.findData("gpu")
                    if _gpu_idx >= 0:
                        self.compute_mode_combo.setCurrentIndex(_gpu_idx)
                except Exception:
                    log.debug("compute_mode gpu persist failed", exc_info=True)
            self._refresh_hw_summary()
        else:
            self.gpu_pack_status_label.setText(f"GPU pack install failed: {message}")
            QMessageBox.warning(
                self, "GPU pack install failed",
                f"{message}\n\nELI will continue on CPU.",
            )
        self._refresh_gpu_pack_controls()
        self._refresh_hw_summary()

    def selected_compute_mode(self) -> str:
        return str(self.compute_mode_combo.currentData() or "auto")

    def _sync_provider_controls(self):
        provider = self.selected_provider()
        is_ollama = provider == "ollama"
        if is_ollama:
            # Ollama chosen here: start its local server (off the GUI thread) so its models can be listed
            try:
                from eli.gui.widgets.ollama_model_selector import _start_ollama_for_choice
                _start_ollama_for_choice()
            except Exception:
                log.debug("[OLLAMA] start for the user's choice failed", exc_info=True)
        self.gguf_combo.setEnabled(not is_ollama)
        self.model_path_input.setEnabled(provider == "custom_gguf")
        self.ollama_host_input.setEnabled(is_ollama)
        self.ollama_model_combo.setEnabled(is_ollama)
        self.auto_tune_checkbox.setChecked(not is_ollama)
        self.auto_tune_checkbox.setEnabled(False)
        # Selecting the Ollama provider must surface the installed models straight
        # away — don't make the user find the Refresh button (the reported gap).
        if is_ollama:
            self._auto_load_ollama_models()

    @staticmethod
    def _model_label(m: Dict[str, Any]) -> str:
        """'[source] name (x.xx GiB)'. `size_gb` here is already binary GiB — every
        discovery path (discover_gguf_models, hardware_profile.discover_models, the
        custom-path branches in this file) computes it via mem_units now. Do not run
        it through model_download._as_gib(), which expects a decimal-GB *catalog*
        estimate and would double-convert an already-binary figure."""
        return f"[{m.get('source', '?')}] {m.get('name', 'model')} ({float(m.get('size_gb', 0.0) or 0.0):.2f} GiB)"

    def showEvent(self, event):
        super().showEvent(event)
        # Whatever filled the path box (saved settings, the tuner, a previous session), the dropdown must
        # name the same model. Settings loading can run after the first selection and leave it on item 0.
        if not getattr(self, "_aligned_once", False):
            self._aligned_once = True
            try:
                path = self.model_path_input.text().strip()
                if path and self.selected_provider() != "ollama" and Path(path).is_file():
                    self._select_model_path(path)
            except Exception:
                pass

    def _sync_model_path_from_combo(self):
        if self.selected_provider() == "ollama":
            return
        path = str(self.gguf_combo.currentData() or "").strip()
        if path:
            self.model_path_input.setText(path)

    def _select_model_path(self, path: str):
        target = str(path or "").strip()
        if not target:
            _model = self.gguf_combo.model()
            _first = next((i for i in range(self.gguf_combo.count())
                           if getattr(_model.item(i), "isEnabled", lambda: True)()), None)
            if _first is not None:
                self.gguf_combo.setCurrentIndex(_first)
                self._sync_model_path_from_combo()
            return
        idx = self.gguf_combo.findData(target)
        if idx < 0:
            try:
                target_r = str(Path(target).expanduser().resolve())
            except Exception:
                target_r = target
            for i in range(self.gguf_combo.count()):
                try:
                    if str(Path(str(self.gguf_combo.itemData(i) or "")).expanduser().resolve()) == target_r:
                        idx = i
                        break
                except Exception:
                    continue
        if idx < 0 and target:
            # A saved path outside the scanned folders: list it, so the dropdown never shows
            # a model other than the one that will load. Gating this on Path(target).is_file()
            # used to mean a transient stat() miss (observed at early AppImage startup, before
            # the mount/environment fully settles) silently skipped adding the entry — the
            # combo then kept whatever the scan's first match was, while model_path_input
            # below still got set correctly, so the WRONG model name showed in the dropdown
            # even though the RIGHT model actually loaded. Try to size it; a path that
            # genuinely doesn't exist just fails to load later with its own clear error,
            # which is no worse than today — a dropdown that lies about what loads is worse.
            try:
                _size_gb = file_size_gib(target)
            except Exception:
                _size_gb = 0.0
            self.gguf_combo.addItem(self._model_label(
                {"source": "custom", "name": Path(target).name, "size_gb": _size_gb}), target)
            idx = self.gguf_combo.count() - 1
        if idx >= 0:
            self.gguf_combo.setCurrentIndex(idx)
        self.model_path_input.setText(target)

    def selected_provider(self) -> str:
        return str(self.provider_combo.currentData() or "bundled_gguf")

    def selected_model_path(self) -> str:
        if self.selected_provider() == "bundled_gguf":
            return str(self.gguf_combo.currentData() or "").strip()
        return self.model_path_input.text().strip()

    def selected_ollama_host(self) -> str:
        return self.ollama_host_input.text().strip() or "http://localhost:11434"

    def selected_ollama_model(self) -> str:
        return self.ollama_model_combo.currentText().strip()

    def selected_tts_engine(self) -> str:
        """'piper' or 'natural' — the voice engine chosen before model load."""
        try:
            return str(self.tts_engine_combo.currentData() or "piper")
        except Exception:
            return "piper"

    def selected_tts_voice(self) -> str:
        """The voice id implied by the engine choice: a natural neural voice, or ''
        (empty = leave the Piper voice as-is)."""
        return "natural:sophia" if self.selected_tts_engine() == "natural" else ""

    def should_auto_tune(self) -> bool:
        return self.selected_provider() != "ollama"

    def should_load_now(self) -> bool:
        return bool(self.load_now_checkbox.isChecked())

    def accept(self):
        if self.selected_provider() == "ollama":
            if not self.selected_ollama_model():
                QMessageBox.warning(self, "Missing Ollama model",
                                    "Choose an Ollama model before continuing.")
                return
        else:
            if not self.selected_model_path():
                QMessageBox.warning(self, "Missing model path",
                                    "Choose a GGUF model before continuing.")
                return
        super().accept()


# ── Model download worker ──────────────────────────────────────────────────────

class _ModelDownloadThread(QThread):
    """Runs a curated GGUF download off the UI thread. Routed through netguard
    (offline-by-default preserved; the download opens a scoped allow window)."""
    progress = pyqtSignal(int, int)        # percent_milli (0-1000), done_mib
    finished_result = pyqtSignal(dict)     # download_model() result dict

    def __init__(self, entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._entry = entry

    def run(self):
        try:
            from eli.core.model_download import download_model
            def _emit_progress(done: int, total: int) -> None:
                # Qt int signals are 32-bit — raw byte counts overflow on multi-GB models.
                pct = int(min(1000, round(1000 * done / total))) if total > 0 else 0
                done_mib = min(int(done // (1024 * 1024)), 2_000_000)
                self.progress.emit(pct, done_mib)

            res = download_model(
                self._entry,
                progress_cb=_emit_progress,
            )
        except Exception as exc:  # never let a worker crash take down the wizard
            res = {"ok": False, "error": f"Download crashed: {exc}"}
        self.finished_result.emit(dict(res))


class _SupportAssetsThread(QThread):
    """Fetch required embedder + voice weights (idempotent) off the UI thread."""
    finished_result = pyqtSignal(dict)

    def __init__(self, parent=None, *, force_network: bool = False):
        super().__init__(parent)
        self._force_network = bool(force_network)

    def run(self):
        out: Dict[str, Any] = {"embedder": {}, "voice": {}}
        # First-boot support assets are required for memory + voice. Offline-by-default
        # still applies to ambient traffic; this path opens a scoped allow_network
        # window (same contract as model_download / the Fetch button).
        try:
            from contextlib import ExitStack
            from eli.core.netguard import allow_network
            with ExitStack() as stack:
                stack.enter_context(allow_network("firstboot-support-assets"))
                from eli.core.model_download import download_aux
                aux = download_aux(required_only=True)
                out["embedder"] = aux[0] if aux else {"ok": False, "error": "no embedder entry"}
                from eli.runtime.voice_assets import ensure_voice_assets
                out["voice"] = ensure_voice_assets()
        except Exception as exc:
            if not out.get("embedder"):
                out["embedder"] = {"ok": False, "error": str(exc)}
            if not out.get("voice"):
                out["voice"] = {"piper": {"ok": False, "error": str(exc)}, "whisper": {"ok": False}}
        self.finished_result.emit(out)


# ── FirstBootWizard ────────────────────────────────────────────────────────────

_WIZARD_QSS = """
QDialog { background: #16181d; }
QWidget { color: #cdd6e4; font-size: 13px; }
QLineEdit, QComboBox {
    background: #21242b; color: #e5e9f0;
    border: 1px solid #333844; border-radius: 8px;
    padding: 7px 11px; min-height: 20px; selection-background-color: #5e81ac;
}
QLineEdit:focus, QComboBox:focus { border: 1px solid #5e81ac; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #21242b; color: #e5e9f0; border: 1px solid #333844;
    selection-background-color: #5e81ac; outline: none;
}
QPushButton {
    background: #262a32; color: #e5e9f0; border: 1px solid #363b47;
    border-radius: 8px; padding: 8px 18px; font-weight: 600;
}
QPushButton:hover   { background: #2f343d; border-color: #454b59; }
QPushButton:pressed { background: #21242b; }
QPushButton:disabled{ color: #5b6270; background: #1c1f25; border-color: #262a32; }
QPushButton#wizPrimary          { background: #5e81ac; color: #eceff4; border: none; }
QPushButton#wizPrimary:hover    { background: #6a8fbd; }
QPushButton#wizPrimary:pressed  { background: #52739b; }
QPushButton#wizPrimary:disabled { background: #2b323d; color: #6b7280; }
QProgressBar {
    background: #21242b; border: 1px solid #333844; border-radius: 7px;
    height: 12px; text-align: center; color: #cdd6e4; font-size: 11px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #5e81ac, stop:1 #81a1c1);
    border-radius: 6px;
}
QTabWidget::pane { border: 1px solid #262a32; border-radius: 12px; background: #191c22; top: -1px; }
QTabBar::tab { background: transparent; color: #7b8394; padding: 9px 20px;
    margin-right: 4px; border: none; font-weight: 600; }
QTabBar::tab:selected { color: #eceff4; border-bottom: 2px solid #5e81ac; }
QTabBar::tab:hover:!selected { color: #aab3c5; }
QCheckBox { color: #cdd6e4; spacing: 8px; }
"""


class FirstBootWizard(QDialog):
    """3-step setup wizard shown on first boot when no GGUF model is found.

    Steps:
      1. Welcome — explains ELI v2.0 and what is needed
      2. Model    — file browser to locate a GGUF, or switch to Ollama
      3. Hardware — confirm hardware tuning and launch
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Welcome to ELI — Setup")
        self.setMinimumWidth(660)
        self.setMinimumHeight(440)
        self.setStyleSheet(_WIZARD_QSS)
        try:
            from eli.gui.branding import load_app_icon
            _icon = load_app_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:
            log.debug("suppressed exception", exc_info=True)

        self._selected_path: str = ""
        self._selected_provider: str = "bundled_gguf"
        self._hw_auto_ran: bool = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(12)

        self._tabs = QTabWidget()
        self._tabs.setTabPosition(QTabWidget.TabPosition.North)
        root_layout.addWidget(self._tabs, stretch=1)

        self._build_welcome_tab()
        self._build_model_tab()
        self._build_hardware_tab()

        btn_row = QHBoxLayout()
        self._back_btn  = QPushButton("← Back")
        self._next_btn  = QPushButton("Next →")
        self._next_btn.setObjectName("wizPrimary")
        self._finish_btn = QPushButton("✓ Finish")
        self._finish_btn.setObjectName("wizPrimary")
        self._finish_btn.setVisible(False)
        btn_row.addWidget(self._back_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._next_btn)
        btn_row.addWidget(self._finish_btn)
        root_layout.addLayout(btn_row)

        self._back_btn.clicked.connect(self._go_back)
        self._next_btn.clicked.connect(self._go_next)
        self._finish_btn.clicked.connect(self.accept)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._on_tab_changed(0)

    # ── Tab builders ──────────────────────────────────────────────────────────

    def _build_welcome_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)
        try:
            from eli.gui.branding import resolve_app_icon_path
            from eli.gui.panels._qt import QPixmap
            _ip = resolve_app_icon_path()
            if _ip is not None:
                _logo = QLabel()
                _pix = QPixmap(str(_ip)).scaled(
                    96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                _logo.setPixmap(_pix)
                _logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                v.addWidget(_logo)
        except Exception:
            log.debug("suppressed exception", exc_info=True)
        title = QLabel("Welcome to ELI v2.0")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#88c0d0;")
        v.addWidget(title)
        body = QLabel(
            "ELI runs entirely on your own machine — no cloud, no accounts.\n\n"
            "A fresh install builds the full database architecture (blank slate — every "
            "table exists, no personal memories yet).\n\n"
            "Next we'll set up three local assets:\n"
            "   •  Chat model — the brain. Pick a GGUF file, download one, or use Ollama "
            "on step 2. Ollama works on Windows, macOS and Linux, local or on your LAN.\n"
            "   •  Embedder — nomic ~80 MiB (memory / RAG; automatic).\n"
            "   •  Voice — Piper speech out + Whisper listening (automatic). More voices, "
            "accents and generic voice styles (calm, robotic, synthetic…) are downloadable later "
            "in Settings \u25b8 Runtime \u25b8 \"VOICE / TTS\".\n\n"
            "Pick a chat model, confirm hardware, and you're in."
        )
        body.setWordWrap(True)
        body.setStyleSheet("color:#c8d0e0;line-height:1.5;")
        v.addWidget(body)

        hf_link = QLabel(
            'Download free GGUF models from '
            '<a href="https://huggingface.co/models?library=gguf&sort=downloads" '
            'style="color:#81a1c1;">HuggingFace (search "gguf")</a>'
        )
        hf_link.setOpenExternalLinks(True)
        v.addWidget(hf_link)
        v.addStretch()
        self._tabs.addTab(w, "1 — Welcome")

    def _build_model_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)

        title = QLabel("Find or select a model")
        title.setStyleSheet("font-size:15px;font-weight:bold;color:#88c0d0;")
        v.addWidget(title)

        # Provider choice
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Provider:"))
        self._wiz_provider = QComboBox()
        self._wiz_provider.addItem("Bundled GGUF", "bundled_gguf")
        self._wiz_provider.addItem("Custom GGUF (.gguf file)", "custom_gguf")
        self._wiz_provider.addItem("Ollama (local server)", "ollama")
        prow.addWidget(self._wiz_provider)
        prow.addStretch()
        v.addLayout(prow)

        # GGUF path browser
        self._gguf_widget = QWidget()
        gv = QVBoxLayout(self._gguf_widget)
        gv.setContentsMargins(0, 8, 0, 0)
        path_row = QHBoxLayout()
        self._wiz_path = QLineEdit()
        self._wiz_path.setPlaceholderText("Path to your .gguf file …")
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_gguf)
        path_row.addWidget(self._wiz_path, stretch=1)
        path_row.addWidget(browse_btn)
        gv.addLayout(path_row)
        hint = QLabel(
            f"Or place a .gguf file in:  {_MODELS_DIR}  and restart."
        )
        hint.setStyleSheet("color:#81a1c1;font-size:11px;")
        gv.addWidget(hint)

        # ── Download a model (curated, offline-by-default respected) ──────────
        dl_title = QLabel("— or — download one now:")
        dl_title.setStyleSheet("color:#88c0d0;font-weight:bold;margin-top:8px;")
        gv.addWidget(dl_title)

        dl_row = QHBoxLayout()
        self._dl_combo = QComboBox()
        self._dl_catalog: List[Dict[str, Any]] = []
        try:
            from eli.core.model_download import list_catalog
            self._dl_catalog = list_catalog()
        except Exception as _cat_err:
            log.debug(f"[wizard] model catalog unavailable: {_cat_err}")
        try:
            from eli.core.model_download import _fmt_size_gib as _fmt_gib
        except Exception:
            _fmt_gib = lambda gb: f"~{float(gb or 0)*1e9/(1024**3):.1f} GiB"
        for _e in self._dl_catalog:
            _label = f"{_e.get('name','?')}  · {_fmt_gib(_e.get('size_gb'))} · VRAM {_e.get('vram_gb',0)}GB+"
            if _e.get("default"):
                _label += "  (recommended)"
            self._dl_combo.addItem(_label, _e.get("key"))
        # Preselect the recommended default
        for _i, _e in enumerate(self._dl_catalog):
            if _e.get("default"):
                self._dl_combo.setCurrentIndex(_i)
                break
        self._dl_btn = QPushButton("Download")
        self._dl_btn.setObjectName("wizPrimary")
        self._dl_btn.clicked.connect(self._start_download)
        dl_row.addWidget(self._dl_combo, stretch=1)
        dl_row.addWidget(self._dl_btn)
        gv.addLayout(dl_row)

        self._dl_progress = QProgressBar()
        self._dl_progress.setVisible(False)
        gv.addWidget(self._dl_progress)
        self._dl_status = QLabel("")
        self._dl_status.setWordWrap(True)
        self._dl_status.setStyleSheet("color:#a3be8c;font-size:11px;")
        gv.addWidget(self._dl_status)
        if not self._dl_catalog:
            self._dl_combo.setEnabled(False)
            self._dl_btn.setEnabled(False)
            self._dl_status.setText("Download catalog unavailable — browse to a .gguf instead.")
        self._dl_thread: Optional[_ModelDownloadThread] = None

        sup_title = QLabel("Required support assets (auto):")
        sup_title.setStyleSheet("color:#88c0d0;font-weight:bold;margin-top:10px;")
        gv.addWidget(sup_title)
        self._embedder_status = QLabel("")
        self._embedder_status.setWordWrap(True)
        self._embedder_status.setStyleSheet("color:#a3be8c;font-size:11px;")
        gv.addWidget(self._embedder_status)
        self._voice_status = QLabel("")
        self._voice_status.setWordWrap(True)
        self._voice_status.setStyleSheet("color:#a3be8c;font-size:11px;")
        gv.addWidget(self._voice_status)
        fetch_sup = QPushButton("Fetch embedder + voice now")
        fetch_sup.clicked.connect(lambda: self._start_support_assets(force_network=True))
        gv.addWidget(fetch_sup)
        self._support_thread: Optional[_SupportAssetsThread] = None
        self._refresh_support_status()
        self._start_support_assets(force_network=False)

        v.addWidget(self._gguf_widget)

        # Ollama section
        self._ollama_widget = QWidget()
        ov = QVBoxLayout(self._ollama_widget)
        ov.setContentsMargins(0, 8, 0, 0)
        ov.addWidget(QLabel("Ollama host (local by default; a LAN IP or host:port also works):"))
        self._wiz_ollama_host = QLineEdit("http://localhost:11434")
        self._wiz_ollama_host.setToolTip(
            "Works on Windows, macOS and Linux. Leave the default for a normal local Ollama, "
            "or point ELI at another machine — type it any way (localhost:11434, 127.0.0.1, "
            "192.168.1.20); ELI fills in the scheme and port. A host you set here is treated "
            "as a local service, so it works with the Net toggle off.")
        ov.addWidget(self._wiz_ollama_host)
        ov.addWidget(QLabel("Model (pick one you already have, or type a name):"))
        # Editable combo so installed models are SELECTABLE (was a blank text box
        # with no list — the reported "can't select my Ollama models" gap). Still
        # accepts a typed name for models not yet pulled.
        self._wiz_ollama_model = QComboBox()
        self._wiz_ollama_model.setEditable(True)
        ov.addWidget(self._wiz_ollama_model)
        _wiz_refresh = QPushButton("Refresh Ollama models")
        _wiz_refresh.clicked.connect(self._wiz_refresh_ollama_models)
        ov.addWidget(_wiz_refresh)
        v.addWidget(self._ollama_widget)
        self._ollama_widget.setVisible(False)

        # Voice engine — same choice as the model picker, offered here for a brand-new
        # user, before the model loads. Piper (fast) vs the human-like neural voice.
        v.addWidget(QLabel("Voice engine:"))
        self._wiz_tts_engine = QComboBox()
        self._wiz_tts_engine.addItem("Piper — fast, works on any machine (recommended)", "piper")
        self._wiz_tts_engine.addItem("Natural neural (XTTS-v2) — human-like, needs GPU/VRAM", "natural")
        self._wiz_tts_engine.setToolTip(
            "Piper is fast and light. The natural neural voice sounds human — expressive and "
            "punctuation-aware — but downloads ~1.8GB on first use and needs more VRAM. ELI "
            "falls back to Piper automatically if the neural voice can't load.")
        v.addWidget(self._wiz_tts_engine)

        self._wiz_provider.currentIndexChanged.connect(self._sync_wiz_provider)
        v.addStretch()
        self._tabs.addTab(w, "2 — Model")

    def _build_hardware_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(14, 14, 14, 14)

        title = QLabel("Hardware configuration")
        title.setStyleSheet("font-size:15px;font-weight:bold;color:#88c0d0;")
        v.addWidget(title)

        note = QLabel(
            "ELI will now run automatic hardware detection to calculate the best "
            "context size, GPU layer count, and batch size for your machine.\n\n"
            "This takes about 2 seconds.  You can always re-tune later from "
            "Settings → Hardware."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#c8d0e0;")
        v.addWidget(note)

        self._hw_result_label = QLabel("")
        self._hw_result_label.setWordWrap(True)
        self._hw_result_label.setStyleSheet("color:#a3be8c;font-size:12px;")
        v.addWidget(self._hw_result_label)

        self._wiz_gpu_status = QLabel("")
        self._wiz_gpu_status.setWordWrap(True)
        self._wiz_gpu_status.setStyleSheet("color:#9aa5b5;font-size:11px;")
        v.addWidget(self._wiz_gpu_status)
        _wiz_gpu_row = QHBoxLayout()
        self._wiz_gpu_vulkan_btn = QPushButton("Install Vulkan GPU pack")
        self._wiz_gpu_vulkan_btn.clicked.connect(
            lambda: self._wiz_start_gpu_pack_install(vulkan=True))
        self._wiz_gpu_cuda_btn = QPushButton("Install CUDA GPU pack")
        self._wiz_gpu_cuda_btn.clicked.connect(
            lambda: self._wiz_start_gpu_pack_install(vulkan=False))
        _wiz_gpu_row.addWidget(self._wiz_gpu_vulkan_btn)
        _wiz_gpu_row.addWidget(self._wiz_gpu_cuda_btn)
        v.addLayout(_wiz_gpu_row)

        tune_btn = QPushButton("Run hardware detection now")
        tune_btn.clicked.connect(self._run_hw_detection)
        v.addWidget(tune_btn)
        v.addStretch()
        self._tabs.addTab(w, "3 — Hardware")

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_tab_changed(self, idx: int):
        last = self._tabs.count() - 1
        self._back_btn.setEnabled(idx > 0)
        self._next_btn.setVisible(idx < last)
        self._finish_btn.setVisible(idx == last)
        # Step 3 promises automatic detection — run it on first entry, not on click.
        if idx == 2 and not self._hw_auto_ran:
            self._hw_auto_ran = True
            self._run_hw_detection()
            self._wiz_refresh_gpu_pack_controls()

    def _models_for_hw_recommend(self) -> List[Dict[str, Any]]:
        """Prefer the wizard's selected/downloaded model over largest-on-disk."""
        try:
            from eli.core.hardware_profile import discover_models, _is_embedder_path
        except Exception:
            return []
        sel = self._wiz_path.text().strip() or self._selected_path
        if sel:
            try:
                sp = Path(sel).expanduser().resolve()
                if (sp.exists() and sp.suffix.lower() == ".gguf"
                        and not _is_embedder_path(sp)):
                    sz = sp.stat().st_size
                    return [{
                        "name": sp.name,
                        "path": str(sp),
                        "size_bytes": sz,
                        "size_gb": bytes_to_gib(sz),
                    }]
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        return discover_models()

    def _go_next(self):
        self._tabs.setCurrentIndex(self._tabs.currentIndex() + 1)

    def _go_back(self):
        self._tabs.setCurrentIndex(self._tabs.currentIndex() - 1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sync_wiz_provider(self):
        is_ollama = self._wiz_provider.currentData() == "ollama"
        self._gguf_widget.setVisible(not is_ollama)
        self._ollama_widget.setVisible(is_ollama)
        # Auto-surface installed models the moment Ollama is chosen (quiet).
        if is_ollama and self._wiz_ollama_model.count() == 0:
            names, _err = _query_ollama_tags(self._wiz_ollama_host.text().strip(), timeout=2)
            if names:
                self._wiz_populate_ollama(names)

    def _wiz_populate_ollama(self, names):
        current = self._wiz_ollama_model.currentText().strip()
        self._wiz_ollama_model.clear()
        for name in names:
            self._wiz_ollama_model.addItem(name)
        if current:
            self._wiz_ollama_model.setEditText(current)

    def _wiz_refresh_ollama_models(self):
        host = self._wiz_ollama_host.text().strip() or "http://localhost:11434"
        names, err = _query_ollama_tags(host, timeout=5)
        if err is not None:
            QMessageBox.warning(self, "Ollama unreachable",
                                _ollama_unreachable_message(host, err))
            return
        if not names:
            QMessageBox.information(
                self, "No Ollama models",
                f"Ollama is running at {host} but no models are installed yet.\n"
                "Pull one first, e.g.  ollama pull llama3",
            )
            return
        self._wiz_populate_ollama(names)

    def _browse_gguf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select GGUF model", str(_MODELS_DIR),
            "GGUF Files (*.gguf);;All Files (*)",
        )
        if path:
            self._wiz_path.setText(path)

    def _refresh_support_status(self):
        try:
            from eli.core.model_download import aux_status
            from eli.perception import tts_router
            emb = aux_status("embedder")
            if emb.get("ok"):
                sz = emb.get("size_mib")
                self._embedder_status.setText(
                    f"✓ Embedder ready — {emb.get('path','')}"
                    + (f" ({sz} MiB)" if sz else ""))
            else:
                self._embedder_status.setText(
                    f"○ Embedder missing — will download to models/embeddings/ "
                    f"({emb.get('size_gib_estimate','~80 MiB')})")
            voices = tts_router.list_voices()
            if voices:
                self._voice_status.setText(
                    f"✓ Voice ready — default {tts_router.get_active_voice()} "
                    f"({len(voices)} voice(s) found)")
            else:
                self._voice_status.setText(
                    "○ Voice missing — will fetch en_US-amy-medium (Piper) + whisper STT")
        except Exception as exc:
            self._embedder_status.setText(f"○ Embedder status unknown ({exc})")
            self._voice_status.setText("○ Voice status unknown")

    def _start_support_assets(self, *, force_network: bool = False):
        if getattr(self, "_support_thread", None) is not None and self._support_thread.isRunning():
            return
        self._embedder_status.setText("Fetching embedder (nomic) …")
        self._voice_status.setText("Fetching voice models …")
        self._support_thread = _SupportAssetsThread(parent=self, force_network=force_network)
        self._support_thread.finished_result.connect(self._on_support_done)
        self._support_thread.start()

    def _on_support_done(self, res: Dict[str, Any]):
        emb = res.get("embedder") or {}
        if emb.get("ok"):
            sz = emb.get("size_gib_actual") or emb.get("size_mib")
            extra = f" ({sz} GiB)" if isinstance(sz, float) and sz < 2 else (
                f" ({sz} MiB)" if emb.get("size_mib") else "")
            self._embedder_status.setText(
                f"✓ Embedder {'present' if emb.get('already_present') else 'downloaded'}: "
                f"{emb.get('path','')}{extra}")
        else:
            self._embedder_status.setText(
                f"✗ Embedder: {emb.get('error','failed')} — retry or run: "
                "python -m eli.core.model_download --aux")
        voice = res.get("voice") or {}
        piper = voice.get("piper") or {}
        whisper = voice.get("whisper") or {}
        if piper.get("ok") and whisper.get("ok"):
            self._voice_status.setText(
                f"✓ Voice ready — Piper {piper.get('voice','en_US-amy-medium')} + whisper STT")
        else:
            parts = []
            if not piper.get("ok"):
                parts.append(f"Piper: {piper.get('error','missing')}")
            if not whisper.get("ok"):
                parts.append(f"whisper: {whisper.get('error','missing')}")
            self._voice_status.setText("✗ Voice: " + "; ".join(parts))

    # ── Download ──────────────────────────────────────────────────────────────

    def _start_download(self):
        if getattr(self, "_dl_thread", None) is not None and self._dl_thread.isRunning():
            return
        key = self._dl_combo.currentData()
        entry = next((e for e in self._dl_catalog if e.get("key") == key), None)
        if not entry:
            QMessageBox.warning(self, "No model selected", "Pick a model to download first.")
            return
        try:
            from eli.core.model_download import _fmt_size_gib as _fmt_gib
        except Exception:
            _fmt_gib = lambda gb: f"~{float(gb or 0)*1e9/(1024**3):.1f} GiB"
        if QMessageBox.question(
            self, "Download model",
            f"Download {entry.get('name')} ({_fmt_gib(entry.get('size_gb'))}) into\n{_MODELS_DIR}?\n\n"
            "This is a one-time, deliberate network download. ELI stays offline "
            "by default afterwards.",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._dl_btn.setEnabled(False)
        self._dl_combo.setEnabled(False)
        self._dl_progress.setVisible(True)
        self._dl_progress.setRange(0, 0)  # indeterminate until first progress
        self._dl_status.setText(f"Downloading {entry.get('name')} …")
        self._dl_thread = _ModelDownloadThread(entry, parent=self)
        self._dl_thread.progress.connect(self._on_dl_progress)
        self._dl_thread.finished_result.connect(self._on_dl_done)
        self._dl_thread.start()

    def _on_dl_progress(self, pct_milli: int, done_mib: int):
        gib_done = done_mib / 1024.0
        if pct_milli > 0:
            self._dl_progress.setRange(0, 1000)
            self._dl_progress.setValue(min(pct_milli, 1000))
            if pct_milli >= 1000:
                self._dl_status.setText(
                    f"Downloaded {gib_done:.2f} GiB — verifying & saving, do NOT close…")
            else:
                est_total_gib = gib_done * 1000.0 / max(pct_milli, 1)
                self._dl_status.setText(
                    f"Downloading … {gib_done:.2f} / ~{est_total_gib:.2f} GiB")
        else:
            self._dl_status.setText(f"Downloading … {gib_done:.2f} GiB")

    def _on_dl_done(self, res: Dict[str, Any]):
        self._dl_btn.setEnabled(True)
        self._dl_combo.setEnabled(True)
        # Trust but verify: never show "Downloaded" unless the finalised file
        # is actually on disk (field report: 100% shown, models dir empty).
        if res.get("ok") and res.get("path") and not Path(str(res.get("path"))).is_file():
            res = {"ok": False,
                   "error": f"Finalised file missing on disk: {res.get('path')} — "
                            "check free space/antivirus, then Download again (resumes)."}
        if res.get("ok"):
            path = res.get("path", "")
            self._wiz_path.setText(path)
            self._selected_path = path
            self._dl_progress.setRange(0, 1)
            self._dl_progress.setValue(1)
            verb = "Already present" if res.get("already_present") else "Downloaded"
            # Show the REAL on-disk size, not the catalog's static estimate, and
            # flag when they diverge (stale catalog / repointed URL = the "wrong
            # size displayed" symptom).
            _act = res.get("size_gib_actual")
            _sz = f" ({_act:.2f} GiB)" if isinstance(_act, (int, float)) and _act else ""
            _warn = ""
            if res.get("size_mismatch") and _act:
                try:
                    from eli.core.model_download import _as_gib as _ag
                    _est = f"~{_ag(res.get('size_gb_estimate')):.1f}"
                except Exception:
                    _est = f"~{res.get('size_gb_estimate')}"
                _warn = (f"  ⚠ actual {_act:.2f} GiB vs {_est} GiB listed")
            self._dl_status.setText(f"✓ {verb}: {path}{_sz}{_warn}")
            self._start_support_assets()
            try:
                from eli.core.hardware_profile import detect_hardware, layers_for_model, recommend
                _hw = detect_hardware()
                if _hw.has_gpu and path:
                    _sz_gb = file_size_gib(path)
                    _probe = [{"name": Path(path).name, "path": path,
                               "size_bytes": Path(path).stat().st_size, "size_gb": _sz_gb}]
                    _layers = int(recommend(_hw, _probe).n_gpu_layers)
                    _total = layers_for_model(path, _sz_gb)
                    if 0 <= _layers < _total:
                        self._dl_status.setText(self._dl_status.text() + (
                            "\n⚠ None of its layers fit the GPU's free memory, so it runs on the processor."
                            if _layers == 0 else
                            f"\n⚠ {_layers} of its {_total} layers fit the GPU's free memory; "
                            "the rest run on the processor."))
                        self._dl_status.setStyleSheet("color:#ebcb8b;font-size:11px;")
            except Exception:
                log.debug("suppressed exception", exc_info=True)
        else:
            self._dl_progress.setVisible(False)
            err = res.get("error", "unknown error")
            self._dl_status.setText(f"✗ {err}")
            QMessageBox.warning(self, "Download failed",
                                f"{err}\n\nYou can retry, or browse to a .gguf you already have.")

    def _wiz_refresh_gpu_pack_controls(self) -> None:
        _show_gpu_pack_state(self, self._wiz_gpu_status, self._wiz_gpu_vulkan_btn,
                             self._wiz_gpu_cuda_btn, "_wiz_gpu_thread")

    def _wiz_start_gpu_pack_install(self, *, vulkan: bool) -> None:
        _install_gpu_pack(self, vulkan=vulkan, status=self._wiz_gpu_status,
                          buttons=(self._wiz_gpu_vulkan_btn, self._wiz_gpu_cuda_btn),
                          thread_attr="_wiz_gpu_thread", refresh=self._wiz_refresh_gpu_pack_controls,
                          on_done=self._wiz_on_gpu_pack_done)

    def _wiz_on_gpu_pack_done(self, rc: int, message: str) -> None:
        if rc == 0:
            self._wiz_gpu_status.setText("GPU pack installed — run hardware detection again.")
            self._run_hw_detection()
        else:
            self._wiz_gpu_status.setText(f"GPU pack install failed: {message}")
        self._wiz_refresh_gpu_pack_controls()
        self._wiz_gpu_vulkan_btn.setEnabled(True)
        self._wiz_gpu_cuda_btn.setEnabled(True)

    def _run_hw_detection(self):
        try:
            from eli.core.hardware_profile import (
                detect_hardware as _hp_detect,
                recommend as _hp_recommend,
                apply_recommendation as _hp_apply,
            )
            _hw = _hp_detect()
            _mods = self._models_for_hw_recommend()
            if not _mods:
                self._hw_result_label.setText(
                    f"GPU: {_hw.gpu_name}  |  Free VRAM: {_hw.free_vram_mb}MB\n"
                    "⚠ No chat model yet — pick or download one on step 2, then return here."
                )
                self._hw_result_label.setStyleSheet("color:#ebcb8b;font-size:12px;")
                return
            from eli.core.hardware_profile import (
                effective_use_gpu_layers as _use_gpu,
                format_gpu_layers_status as _fmt_layers,
                layers_for_model,
            )
            _rec = _hp_recommend(_hw, _mods)
            _hp_apply(_rec)
            _style = "color:#a3be8c;font-size:12px;"
            _extra = ""
            _layer_disp = _fmt_layers(
                int(_rec.n_gpu_layers or 0),
                gpu_integrated=bool(getattr(_hw, "gpu_integrated", False)),
                gpu_name=str(getattr(_hw, "gpu_name", "") or ""),
                gpu_vendor=str(getattr(_hw, "gpu_vendor", "") or ""),
            )
            _cpu_path = not _use_gpu(_hw)
            if _cpu_path:
                _style = "color:#ebcb8b;font-size:12px;"
                if getattr(_hw, "gpu_integrated", False):
                    from eli.core.hardware_profile import integrated_gpu_label as _igpu_lbl
                    _kind = _igpu_lbl(_hw.gpu_name, getattr(_hw, "gpu_vendor", ""))
                    _extra = (
                        f"\n⚠ {_kind} — sizing from system RAM (CPU inference). "
                        "Install the GPU pack for optional Vulkan offload."
                    )
                else:
                    _extra = "\n⚠ CPU/RAM sizing — no active GPU backend."
            elif _hw.has_gpu and _rec.n_gpu_layers == 0:
                _style = "color:#ebcb8b;font-size:12px;"
                _extra = (
                    "\n⚠ None of this model's layers fit the GPU's free memory, so it runs on the "
                    "processor. A smaller file (a lower quantisation or fewer parameters) would fit."
                )
            elif _hw.has_gpu and 0 < _rec.n_gpu_layers < layers_for_model(_rec.model_path):
                _extra = (
                    "\n⚠ Only part of this model fits the GPU; the rest runs on the processor. "
                    "A smaller file would reply faster."
                )
            self._hw_result_label.setStyleSheet(_style)
            _ram_line = (
                f"RAM: {_hw.ram_gb:.1f}GB ({_hw.available_ram_gb:.1f}GB free)  |  "
                if _cpu_path else
                f"Free VRAM: {_hw.free_vram_mb}MB  |  "
            )
            self._hw_result_label.setText(
                f"GPU: {_hw.gpu_name}  |  GPU layers: {_layer_disp}  "
                f"|  Context: {_rec.n_ctx}  |  Batch: {_rec.batch_size}  "
                f"|  {_ram_line}{_extra}"
            )
        except Exception as exc:
            self._hw_result_label.setStyleSheet("color:#bf616a;font-size:12px;")
            self._hw_result_label.setText(f"Detection failed: {exc}")

    # ── Public accessors ─────────────────────────────────────────────────────

    def selected_provider(self) -> str:
        return str(self._wiz_provider.currentData() or "bundled_gguf")

    def selected_model_path(self) -> str:
        return self._wiz_path.text().strip()

    def selected_ollama_host(self) -> str:
        return self._wiz_ollama_host.text().strip() or "http://localhost:11434"

    def selected_ollama_model(self) -> str:
        return self._wiz_ollama_model.currentText().strip()

    def selected_tts_engine(self) -> str:
        try:
            return str(self._wiz_tts_engine.currentData() or "piper")
        except Exception:
            return "piper"

    def selected_tts_voice(self) -> str:
        return "natural:sophia" if self.selected_tts_engine() == "natural" else ""

    def accept(self):
        provider = self.selected_provider()
        if provider != "ollama" and not self.selected_model_path():
            QMessageBox.warning(self, "No model selected",
                                "Please select a .gguf model file or switch to Ollama.")
            return
        self._run_hw_detection()
        super().accept()
