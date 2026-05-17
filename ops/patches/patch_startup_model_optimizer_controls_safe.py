from __future__ import annotations

from pathlib import Path
from datetime import datetime
import re

p = Path("eli/gui/eli_pro_audio_gui_MKI.py")
s = p.read_text(encoding="utf-8")

backup = p.with_suffix(f".py.bak_startup_controls_safe_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
backup.write_text(s, encoding="utf-8")

# Ensure imports.
if "QDoubleSpinBox" not in s:
    s = s.replace("QCheckBox,", "QCheckBox, QDoubleSpinBox, QSpinBox,", 1)

# Only operate inside startup dialog region.
start = s.find('self.setWindowTitle("Startup Model Selection")')
if start == -1:
    raise SystemExit("Could not find Startup Model Selection dialog.")

end_candidates = [
    s.find("\nclass ", start + 1),
    s.find("\ndef ", start + 1),
]
end_candidates = [x for x in end_candidates if x != -1]
end = min(end_candidates) if end_candidates else len(s)

region = s[start:end]

needle = '        self.auto_tune_checkbox = QCheckBox("Hardware tuning is required for GGUF and runs before load")'
if needle not in region:
    raise SystemExit("Could not find auto_tune_checkbox inside Startup Model Selection region.")

if "self.ctx_fraction_spin" not in region:
    controls = '''        self.auto_tune_checkbox = QCheckBox("Hardware tuning is required for GGUF and runs before load")

        self.ctx_fraction_spin = QDoubleSpinBox()
        self.ctx_fraction_spin.setRange(0.10, 0.95)
        self.ctx_fraction_spin.setSingleStep(0.05)
        self.ctx_fraction_spin.setDecimals(2)
        self.ctx_fraction_spin.setValue(float(os.environ.get("ELI_CTX_FRACTION", "0.65")))
        form.addRow("Context target fraction", self.ctx_fraction_spin)

        self.target_batch_spin = QSpinBox()
        self.target_batch_spin.setRange(16, 4096)
        self.target_batch_spin.setSingleStep(16)
        self.target_batch_spin.setValue(int(os.environ.get("ELI_TARGET_BATCH", "256")))
        form.addRow("Target batch", self.target_batch_spin)

        self.vram_reserve_spin = QSpinBox()
        self.vram_reserve_spin.setRange(0, 16384)
        self.vram_reserve_spin.setSingleStep(128)
        self.vram_reserve_spin.setValue(int(os.environ.get("ELI_VRAM_RESERVE_MB", "900")))
        form.addRow("VRAM reserve MB", self.vram_reserve_spin)

        self.runtime_reserve_spin = QSpinBox()
        self.runtime_reserve_spin.setRange(0, 16384)
        self.runtime_reserve_spin.setSingleStep(128)
        self.runtime_reserve_spin.setValue(int(os.environ.get("ELI_RUNTIME_VRAM_RESERVE_MB", "900")))
        form.addRow("Runtime reserve MB", self.runtime_reserve_spin)

        self.model_train_ctx_spin = QSpinBox()
        self.model_train_ctx_spin.setRange(0, 262144)
        self.model_train_ctx_spin.setSingleStep(2048)
        self.model_train_ctx_spin.setValue(int(os.environ.get("ELI_MODEL_TRAIN_CTX", "0")))
        form.addRow("Model train ctx override (0=auto)", self.model_train_ctx_spin)'''
    region = region.replace(needle, controls, 1)

# Find selected()/return dict method inside region, not global file.
return_idx = region.find("        return {")
if return_idx == -1:
    raise SystemExit("Could not find return dict inside Startup Model Selection region.")

export = '''        os.environ["ELI_CTX_FRACTION"] = str(float(self.ctx_fraction_spin.value()))
        os.environ["ELI_TARGET_BATCH"] = str(int(self.target_batch_spin.value()))
        os.environ["ELI_VRAM_RESERVE_MB"] = str(int(self.vram_reserve_spin.value()))
        os.environ["ELI_RUNTIME_VRAM_RESERVE_MB"] = str(int(self.runtime_reserve_spin.value()))

        if int(self.model_train_ctx_spin.value()) > 0:
            os.environ["ELI_MODEL_TRAIN_CTX"] = str(int(self.model_train_ctx_spin.value()))
        else:
            os.environ.pop("ELI_MODEL_TRAIN_CTX", None)

'''

pre_return_window = region[max(0, return_idx - 1000):return_idx]
if 'os.environ["ELI_CTX_FRACTION"]' not in pre_return_window:
    region = region[:return_idx] + export + region[return_idx:]

s = s[:start] + region + s[end:]
p.write_text(s, encoding="utf-8")

print(f"[OK] patched {p}")
print(f"[OK] backup {backup}")
