"""ELI v2.0 — Startup panel components.

Contains:
  - HardwareTuningDock  — dock widget showing hardware tuning status/log
  - StartupModelSelectionDialog — model/provider picker shown at boot
  - FirstBootWizard — 3-step wizard for zero-model first-boot state
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from eli.gui.panels._qt import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
    QDoubleSpinBox, QFileDialog, QFormLayout, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
    QTabWidget, QThread, QVBoxLayout, QHBoxLayout, QWidget, Qt,
    now_hms, pyqtSignal,
)

from eli.utils.log import get_logger
log = get_logger(__name__)

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
        bases = candidate_hosts(host)
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
            f"{hint}\n\n"
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

class HardwareTuningDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Hardware Tuning", parent)
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
        try:
            from eli.core.model_download import _as_gib
        except Exception:
            _as_gib = lambda gb: float(gb or 0) * 1_000_000_000 / (1024 ** 3)
        for m in self._models:
            # GiB (binary) so the figure matches what the OS file managers show.
            label = (
                f"[{m.get('source', '?')}] {m.get('name', 'model')} "
                f"({_as_gib(m.get('size_gb', 0.0)):.2f} GiB)"
            )
            self.gguf_combo.addItem(label, str(m.get("path") or ""))
        form.addRow("GGUF models", self.gguf_combo)

        self.model_path_input = QLineEdit(current_model_path or "")
        form.addRow("Custom path", self.model_path_input)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_gguf_file)
        form.addRow("", browse_btn)

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
        # settings n_ctx (your last choice, persisted) → DEFAULT_N_CTX (true first-run
        # fallback only, when no choice has ever been made). 0 = auto (fraction/VRAM
        # sizing). Applied as ELI_FORCE_CTX, the optimizer's highest-priority override.
        try:
            from eli.core.runtime_settings import DEFAULT_N_CTX as _DEFAULT_CTX
        except Exception:
            _DEFAULT_CTX = 16384
        _saved_ctx = 0
        try:
            from eli.core.runtime_settings import load_settings as _rs_load
            _saved_ctx = int((_rs_load() or {}).get("n_ctx", 0) or 0)
        except Exception:
            _saved_ctx = 0
        _env_ctx = (os.environ.get("ELI_FORCE_CTX") or "").strip()
        if _env_ctx.isdigit() and int(_env_ctx) >= 2048:
            _initial_ctx = int(_env_ctx)            # explicit in-session override
        elif _saved_ctx >= 2048:
            _initial_ctx = _saved_ctx               # your last chosen value
        else:
            _initial_ctx = int(_DEFAULT_CTX)        # first-run fallback only
        self.ctx_window_spin = QSpinBox()
        self.ctx_window_spin.setRange(0, 262144)
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
        self.target_batch_spin.setRange(16, 4096)
        self.target_batch_spin.setSingleStep(16)
        self.target_batch_spin.setValue(int(os.environ.get("ELI_TARGET_BATCH", "256")))
        form.addRow("Target batch", self.target_batch_spin)

        self.vram_reserve_spin = QSpinBox()
        self.vram_reserve_spin.setRange(0, 16384)
        self.vram_reserve_spin.setSingleStep(128)
        self.vram_reserve_spin.setValue(int(os.environ.get("ELI_VRAM_RESERVE_MB", "250")))
        form.addRow("VRAM reserve MB", self.vram_reserve_spin)

        self.model_train_ctx_spin = QSpinBox()
        self.model_train_ctx_spin.setRange(0, 262144)
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
            os.environ["ELI_CTX_FRACTION"] = str(float(self.ctx_fraction_spin.value()))
            os.environ["ELI_TARGET_BATCH"]  = str(int(self.target_batch_spin.value()))
            os.environ["ELI_VRAM_RESERVE_MB"] = str(int(self.vram_reserve_spin.value()))
            if int(self.model_train_ctx_spin.value()) > 0:
                os.environ["ELI_MODEL_TRAIN_CTX"] = str(int(self.model_train_ctx_spin.value()))
            else:
                os.environ.pop("ELI_MODEL_TRAIN_CTX", None)

        _old_accept = super().accept

        def _accept_wrapper():
            _apply_env()
            # Preload faster-whisper FIRST so its VRAM allocation is visible to
            # the GGUF hardware autotune below. Without this, the autotune sees
            # full free VRAM, assigns all layers to GGUF, and whisper hits CUDA
            # OOM on first utterance. With this, autotune sees the reduced free
            # VRAM and correctly down-sizes gpu_layers for the LLM.
            _whisper_on_cuda = False
            try:
                from eli.perception.local_whisper_stt import preload_model as _eli_preload_whisper
                if _eli_preload_whisper():
                    _whisper_on_cuda = True
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
                # When Whisper is resident on GPU, batch=256 consistently OOMs on
                # the first llama_context load attempt. Always cap to 128 when
                # Whisper is on CUDA — even if ELI_TARGET_BATCH is already set
                # (prior sessions may have left "256" in the env).
                if _whisper_on_cuda:
                    _existing_batch = int(os.environ.get("ELI_TARGET_BATCH", "256") or "256")
                    if _existing_batch > 128:
                        os.environ["ELI_TARGET_BATCH"] = "128"
                        log.debug("[STARTUP_DIALOG][AUDIO_PRELOAD] Whisper on CUDA → capping batch to 128")
                from eli.core.hardware_profile import (
                    detect_hardware as _hp_detect,
                    discover_models as _hp_models,
                    recommend as _hp_recommend,
                    apply_recommendation as _hp_apply,
                    _is_embedder_path as _hp_is_embedder,
                )
                _hw   = _hp_detect()
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
                                "size_gb": _sz / 1e9,
                            }]
                    except Exception:
                        pass
                # Honour the user's "Direct context window" choice (ELI_FORCE_CTX,
                # just set by _apply_env) so the regenerated profile reflects what
                # they asked for — not the DEFAULT_N_CTX target.
                _forced_ctx = (os.environ.get("ELI_FORCE_CTX") or "").strip()
                _pin_ctx = int(_forced_ctx) if _forced_ctx.isdigit() and int(_forced_ctx) >= 2048 else None
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
            self.model_path_input.setText(file_path)
            idx = self.provider_combo.findData("custom_gguf")
            if idx >= 0:
                self.provider_combo.setCurrentIndex(idx)

    def _sync_provider_controls(self):
        provider = self.selected_provider()
        is_ollama = provider == "ollama"
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

    def _sync_model_path_from_combo(self):
        if self.selected_provider() == "ollama":
            return
        path = str(self.gguf_combo.currentData() or "").strip()
        if path:
            self.model_path_input.setText(path)

    def _select_model_path(self, path: str):
        target = str(path or "").strip()
        if not target:
            if self.gguf_combo.count():
                self.gguf_combo.setCurrentIndex(0)
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

    def run(self):
        out: Dict[str, Any] = {"embedder": {}, "voice": {}}
        try:
            from eli.core.model_download import download_aux
            aux = download_aux(required_only=True)
            out["embedder"] = aux[0] if aux else {"ok": False, "error": "no embedder entry"}
        except Exception as exc:
            out["embedder"] = {"ok": False, "error": str(exc)}
        try:
            from eli.runtime.voice_assets import ensure_voice_assets
            out["voice"] = ensure_voice_assets()
        except Exception as exc:
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
            pass

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
            pass
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
            "accents and character voices (HAL, JARVIS, GLaDOS…) are downloadable later "
            "in Settings > Voice.\n\n"
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
        fetch_sup.clicked.connect(self._start_support_assets)
        gv.addWidget(fetch_sup)
        self._support_thread: Optional[_SupportAssetsThread] = None
        self._refresh_support_status()
        self._start_support_assets()

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
                        "size_gb": sz / 1e9,
                    }]
            except Exception:
                pass
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

    def _start_support_assets(self):
        if getattr(self, "_support_thread", None) is not None and self._support_thread.isRunning():
            return
        self._embedder_status.setText("Fetching embedder (nomic) …")
        self._voice_status.setText("Fetching voice models …")
        self._support_thread = _SupportAssetsThread(parent=self)
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
                from eli.core.hardware_profile import detect_hardware, recommend
                _hw = detect_hardware()
                _sz_gb = float(res.get("size_gib_actual") or 0)
                if not _sz_gb and path:
                    _sz_gb = Path(path).stat().st_size / 1e9
                if _hw.has_gpu and _hw.total_vram_mb > 0 and _sz_gb > 0:
                    _vram_gb = _hw.total_vram_mb / 1024.0
                    if _sz_gb * 1.1 > _vram_gb:
                        self._dl_status.setText(
                            self._dl_status.text()
                            + f"\n⚠ {_sz_gb:.1f} GB model on {_vram_gb:.0f} GB GPU — "
                            "expect partial offload; Qwen2.5-7B is better for 8 GB cards."
                        )
                if _hw.has_gpu and path:
                    _probe = [{
                        "name": Path(path).name,
                        "path": path,
                        "size_bytes": Path(path).stat().st_size,
                        "size_gb": Path(path).stat().st_size / 1e9,
                    }]
                    _layers = recommend(_hw, _probe).n_gpu_layers
                    if _layers == 0:
                        self._dl_status.setStyleSheet("color:#ebcb8b;font-size:11px;")
            except Exception:
                pass
        else:
            self._dl_progress.setVisible(False)
            err = res.get("error", "unknown error")
            self._dl_status.setText(f"✗ {err}")
            QMessageBox.warning(self, "Download failed",
                                f"{err}\n\nYou can retry, or browse to a .gguf you already have.")

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
            _rec = _hp_recommend(_hw, _mods)
            _hp_apply(_rec)
            _style = "color:#a3be8c;font-size:12px;"
            _extra = ""
            if _hw.has_gpu and _rec.n_gpu_layers == 0:
                _style = "color:#ebcb8b;font-size:12px;"
                _extra = (
                    "\n⚠ This model is too large for comfortable GPU offload on your card. "
                    "Try Qwen2.5-7B (recommended for 8 GB GPUs)."
                )
            elif _hw.has_gpu and 0 < _rec.n_gpu_layers < 10:
                _extra = (
                    "\n⚠ Partial GPU offload — consider a smaller model for faster replies."
                )
            self._hw_result_label.setStyleSheet(_style)
            self._hw_result_label.setText(
                f"GPU: {_hw.gpu_name}  |  GPU layers: {_rec.n_gpu_layers}  "
                f"|  Context: {_rec.n_ctx}  |  Batch: {_rec.batch_size}  "
                f"|  Free VRAM: {_hw.free_vram_mb}MB{_extra}"
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

    def accept(self):
        provider = self.selected_provider()
        if provider != "ollama" and not self.selected_model_path():
            QMessageBox.warning(self, "No model selected",
                                "Please select a .gguf model file or switch to Ollama.")
            return
        self._run_hw_detection()
        super().accept()
