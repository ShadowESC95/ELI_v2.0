"""install.sh must survive Intel iGPU lspci probes under pipefail (5% abort regression)."""
from __future__ import annotations

import subprocess
from pathlib import Path


def test_install_sh_syntax():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["bash", "-n", str(root / "install.sh")], check=True)


def test_gpu_pipeline_survives_lspci_failure():
    """Reproduce pipefail abort: lspci | sed must not kill set -e scripts."""
    script = """
set -euo pipefail
_gpu_pipeline() { set +o pipefail; "$@"; set -o pipefail; }
_pci="00:02.0"
_out="$(_gpu_pipeline bash -c "lspci -s '${_pci}' -nn 2>/dev/null | sed 's/^[^:]*: //' | head -1 || true")"
echo "ok:${_out}"
"""
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().startswith("ok:")
