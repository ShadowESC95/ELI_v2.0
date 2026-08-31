"""Tests for llama-cpp CPU compatibility probing."""
from __future__ import annotations

from eli.core import llama_cpu_compat as lcc


def test_i7_8700_does_not_trust_prebuilt_wheel(monkeypatch):
    flags = (
        "flags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov "
        "pat pse36 clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe syscall nx pdpe1gb "
        "rdtscp lm constant_tsc art arch_perfmon pebs bts rep_good nopl xtopology "
        "nonstop_tsc cpuid aperfmperf pni pclmulqdq dtes64 monitor ds_cpl vmx smx est "
        "tm2 ssse3 sdbg fma cx16 xtpr pdcm pcid sse4_1 sse4_2 x2apic movbe popcnt "
        "tsc_deadline_timer aes xsave avx f16c rdrand lahf_lm abm 3dnowprefetch "
        "cpuid_fault epb pti ssbd ibrs ibpb stibp tpr_shadow flexpriority ept vpid "
        "ept_ad fsgsbase tsc_adjust bmi1 avx2 smep bmi2 erms invpcid mpx rdseed adx "
        "smap clflushopt intel_pt xsaveopt xsavec xgetbv1 xsaves dtherm ida arat pln "
        "pts hwp hwp_notify hwp_act_window hwp_epp vnmi md_clear flush_l1d arch_capabilities"
    )

    class _FakePath:
        def read_text(self, **_kw):
            return f"model name\t: Intel(R) Core(TM) i7-8700\n{flags}\n"

    monkeypatch.setattr(lcc, "Path", lambda *_a, **_k: _FakePath())
    assert lcc.cpu_supports_prebuilt_llama_wheel() is False


def test_alder_lake_trusts_prebuilt_wheel(monkeypatch):
    flags = "flags\t\t: fpu avx avx2 avx_vnni sse4_2"

    class _FakePath:
        def read_text(self, **_kw):
            return flags

    monkeypatch.setattr(lcc, "Path", lambda *_a, **_k: _FakePath())
    assert lcc.cpu_supports_prebuilt_llama_wheel() is True


def test_safe_cmake_flags_use_avx2_baseline(monkeypatch):
    flags = "flags\t\t: fpu avx avx2 sse4_2"

    class _FakePath:
        def read_text(self, **_kw):
            return flags

    monkeypatch.setattr(lcc, "Path", lambda *_a, **_k: _FakePath())
    out = lcc.safe_source_cmake_flags()
    assert "x86-64-v3" in out
    assert "GGML_NATIVE=OFF" in out


def test_linux_installer_probes_cpu_before_cuda_wheel():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "install.sh").read_text(encoding="utf-8")
    assert "_cpu_trusts_prebuilt_llama_wheel" in text
    nvidia = text[text.index("# NVIDIA."):]
    assert "skipping prebuilt CUDA llama-cpp wheel" in nvidia
    assert "CPU-safe source build" in nvidia or "CPU-safe flags" in nvidia


def test_startup_probes_llama_before_launch():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "scripts" / "eli_startup.sh").read_text(
        encoding="utf-8"
    )
    assert "llama_backend_init" in text
    assert "repairing CPU backend" in text
