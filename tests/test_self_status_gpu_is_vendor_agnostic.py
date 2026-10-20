"""render_self_status_block() degrades each missing GPU field (temperature, use, used memory)
on its own instead of assuming every number is present: AMD, Intel, Apple and Qualcomm GPUs
report fewer of them than NVIDIA does. Where the figures come from is covered by
tests/test_get_live_gpu_telemetry.py.
"""


def test_render_degrades_missing_fields_instead_of_crashing():
    """Old code did g['temp_c'] unconditionally -- a name-only/VRAM-only dict
    (AMD, or any identity-fallback vendor) would have raised KeyError."""
    st = {
        "uptime": "1h", "gpu": {
            "name": "Intel Iris Xe Graphics (estimated)",
            "temp_c": None, "util_pct": None, "vram_used_mb": None, "vram_total_mb": 4096,
        },
    }
    import eli.runtime.self_status as _ss
    original = _ss.get_self_status
    _ss.get_self_status = lambda: st
    try:
        out = _ss.render_self_status_block()
    finally:
        _ss.get_self_status = original
    assert "Intel Iris Xe Graphics" in out
    assert "4096 MB VRAM total" in out
    assert "None" not in out
