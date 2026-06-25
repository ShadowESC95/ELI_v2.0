"""ELI MKXI — Startup panel components.

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
            "Choose which model to load for this session. "
            "You can run automatic hardware tuning before load."
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
        form.addRow("Ollama host", self.ollama_host_input)
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        for name in list(ollama_models or []):
            self.ollama_model_combo.addItem(str(name))
        if ollama_model:
            self.ollama_model_combo.setEditText(ollama_model)
        form.addRow("Ollama model", self.ollama_model_combo)
        layout.addLayout(form)

        self.auto_tune_checkbox = QCheckBox(
            "Hardware tuning is required for GGUF and runs before load"
        )
        self.auto_tune_checkbox.setChecked(True)
        self.auto_tune_checkbox.setEnabled(False)
        layout.addWidget(self.auto_tune_checkbox)

        # Direct context-window control. Defaults to ELI's canonical default
        # (DEFAULT_N_CTX = 16384) so every model loads at 16384 unless the user
        # changes this here. 0 = auto (fall back to the fraction/VRAM sizing below).
        # Applied as ELI_FORCE_CTX, the optimizer's highest-priority ctx override.
        try:
            from eli.core.runtime_settings import DEFAULT_N_CTX as _DEFAULT_CTX
        except Exception:
            _DEFAULT_CTX = 16384
        self.ctx_window_spin = QSpinBox()
        self.ctx_window_spin.setRange(0, 262144)
        self.ctx_window_spin.setSingleStep(2048)
        self.ctx_window_spin.setValue(
            int(os.environ.get("ELI_FORCE_CTX", str(int(_DEFAULT_CTX))) or int(_DEFAULT_CTX))
        )
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
                _rec  = _hp_recommend(_hw, _rec_models)
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
    progress = pyqtSignal(int, int)        # downloaded_bytes, total_bytes
    finished_result = pyqtSignal(dict)     # download_model() result dict

    def __init__(self, entry: Dict[str, Any], parent=None):
        super().__init__(parent)
        self._entry = entry

    def run(self):
        try:
            from eli.core.model_download import download_model
            res = download_model(
                self._entry,
                progress_cb=lambda d, t: self.progress.emit(int(d), int(t)),
            )
        except Exception as exc:  # never let a worker crash take down the wizard
            res = {"ok": False, "error": f"Download crashed: {exc}"}
        self.finished_result.emit(dict(res))


# ── FirstBootWizard ────────────────────────────────────────────────────────────

class FirstBootWizard(QDialog):
    """3-step setup wizard shown on first boot when no GGUF model is found.

    Steps:
      1. Welcome — explains ELI MKXI and what is needed
      2. Model    — file browser to locate a GGUF, or switch to Ollama
      3. Hardware — confirm hardware tuning and launch
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("ELI MKXI — First Boot Setup")
        self.setMinimumWidth(640)
        self.setMinimumHeight(400)

        self._selected_path: str = ""
        self._selected_provider: str = "bundled_gguf"

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
        self._finish_btn = QPushButton("✓ Finish")
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
        title = QLabel("Welcome to ELI MKXI")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#88c0d0;")
        v.addWidget(title)
        body = QLabel(
            "ELI MKXI is a 100% local AI assistant that runs entirely on your hardware — "
            "no cloud, no subscriptions, no data leaving your machine.\n\n"
            "To get started you need:\n"
            "  • A GGUF language model file  (e.g. Qwen2.5-7B or Mistral-7B Q4)\n"
            "  • OR an Ollama server running locally\n\n"
            "This wizard will guide you through placing a model and configuring ELI "
            "for your hardware."
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

        v.addWidget(self._gguf_widget)

        # Ollama section
        self._ollama_widget = QWidget()
        ov = QVBoxLayout(self._ollama_widget)
        ov.setContentsMargins(0, 8, 0, 0)
        ov.addWidget(QLabel("Ollama host:"))
        self._wiz_ollama_host = QLineEdit("http://localhost:11434")
        ov.addWidget(self._wiz_ollama_host)
        ov.addWidget(QLabel("Model name (e.g. llama3 or mistral):"))
        self._wiz_ollama_model = QLineEdit()
        ov.addWidget(self._wiz_ollama_model)
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

    def _go_next(self):
        self._tabs.setCurrentIndex(self._tabs.currentIndex() + 1)

    def _go_back(self):
        self._tabs.setCurrentIndex(self._tabs.currentIndex() - 1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sync_wiz_provider(self):
        is_ollama = self._wiz_provider.currentData() == "ollama"
        self._gguf_widget.setVisible(not is_ollama)
        self._ollama_widget.setVisible(is_ollama)

    def _browse_gguf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select GGUF model", str(_MODELS_DIR),
            "GGUF Files (*.gguf);;All Files (*)",
        )
        if path:
            self._wiz_path.setText(path)

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

    def _on_dl_progress(self, done: int, total: int):
        mb = done / (1024 * 1024)
        if total > 0:
            self._dl_progress.setRange(0, total)
            self._dl_progress.setValue(done)
            self._dl_status.setText(f"Downloading … {mb:.0f} MB / {total/(1024*1024):.0f} MB")
        else:
            self._dl_status.setText(f"Downloading … {mb:.0f} MB")

    def _on_dl_done(self, res: Dict[str, Any]):
        self._dl_btn.setEnabled(True)
        self._dl_combo.setEnabled(True)
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
                discover_models as _hp_models,
                recommend as _hp_recommend,
                apply_recommendation as _hp_apply,
            )
            _hw   = _hp_detect()
            _mods = _hp_models()
            rec   = _hp_recommend(_hw, _mods)
            _hp_apply(rec)
            self._hw_result_label.setText(
                f"GPU: {_hw.gpu_name}  |  GPU layers: {rec.n_gpu_layers}  "
                f"|  Context: {rec.n_ctx}  |  Batch: {rec.batch_size}  "
                f"|  Free VRAM: {_hw.free_vram_mb}MB"
            )
        except Exception as exc:
            self._hw_result_label.setText(f"Detection failed: {exc}")

    # ── Public accessors ─────────────────────────────────────────────────────

    def selected_provider(self) -> str:
        return str(self._wiz_provider.currentData() or "bundled_gguf")

    def selected_model_path(self) -> str:
        return self._wiz_path.text().strip()

    def selected_ollama_host(self) -> str:
        return self._wiz_ollama_host.text().strip() or "http://localhost:11434"

    def selected_ollama_model(self) -> str:
        return self._wiz_ollama_model.text().strip()

    def accept(self):
        provider = self.selected_provider()
        if provider != "ollama" and not self.selected_model_path():
            QMessageBox.warning(self, "No model selected",
                                "Please select a .gguf model file or switch to Ollama.")
            return
        super().accept()
