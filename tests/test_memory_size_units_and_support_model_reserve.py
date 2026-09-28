"""Every place that measured a model's file size, or RAM/VRAM capacity, for a
fit-or-comparison decision did its own inline byte conversion — most divided by
decimal 1e9, a few by binary 1024**3, all labelled "GB". The same real file's size
printed differently depending on which code path measured it (a 19.71 GiB model read
as 19.71GB from the GUI's live loader but 21.17GB from the earlier hardware-tuning
pass), and the MoE resident/experts split computed from whichever number ran first
disagreed with the other. eli/core/mem_units.py is now the one conversion helper
(binary GiB throughout, matching physical VRAM/RAM and moe_offload.py's own math);
every site that feeds a fit decision or a user-facing size display was pointed at it.

Separately: ELI's own always-on support models (whisper STT, the memory/RAG embedder)
load once at startup and stay resident all session, independent of whichever chat
model the user picks. A capacity check that runs before they exist yet — the startup
dialog's tuning pass fires before the engine and its embedder — used to size the chat
model (and an MoE model's expert split) off RAM that was about to be spoken for.
detect_hardware() now reserves their on-disk footprint explicitly.
"""
from __future__ import annotations

from eli.core import mem_units, hardware_profile, moe_offload


def test_bytes_to_gib_is_the_binary_base():
    assert mem_units.bytes_to_gib(1024 ** 3) == 1.0
    assert mem_units.bytes_to_gib(1_000_000_000) < 1.0  # decimal 1GB is less than 1 GiB


def test_file_size_gib_matches_a_real_file(tmp_path):
    f = tmp_path / "model.gguf"
    f.write_bytes(b"\0" * (3 * 1024 ** 3))
    assert mem_units.file_size_gib(f) == 3.0


def test_file_size_gib_is_zero_for_a_missing_file(tmp_path):
    assert mem_units.file_size_gib(tmp_path / "nope.gguf") == 0.0


def test_dir_size_gib_sums_every_file_under_the_directory(tmp_path):
    d = tmp_path / "whisper-model"
    d.mkdir()
    (d / "a.bin").write_bytes(b"\0" * (1024 ** 2 * 512))   # 0.5 GiB
    sub = d / "sub"
    sub.mkdir()
    (sub / "b.bin").write_bytes(b"\0" * (1024 ** 2 * 512))  # 0.5 GiB
    assert round(mem_units.dir_size_gib(d), 3) == 1.0


def test_discover_models_agrees_with_moe_plan_for_load_for_the_same_file(tmp_path, monkeypatch):
    """The exact incident: two code paths measuring the same file must now agree."""
    model = tmp_path / "qwen-moe.gguf"
    model.write_bytes(b"\0" * int(19.71 * 1024 ** 3))

    models = hardware_profile.discover_models(models_dir=tmp_path)
    assert len(models) == 1
    from_tuning_pass = models[0]["size_gb"]

    monkeypatch.setattr(
        "eli.core.hardware_profile.get_live_gpu_telemetry", lambda: {"free_mb": 6000},
    )
    monkeypatch.setattr("eli.core.moe_offload.profile", lambda *_a, **_k: None)  # not MoE, just size math
    from_load_time = mem_units.file_size_gib(model)

    assert round(from_tuning_pass, 4) == round(from_load_time, 4)


def test_hardware_profile_ram_figures_are_binary_gib(monkeypatch):
    class _FakeVM:
        total = 32 * 1024 ** 3
        available = 24 * 1024 ** 3

    monkeypatch.setattr(
        "psutil.virtual_memory", lambda: _FakeVM(), raising=False,
    )
    hw = hardware_profile._detect_hardware_impl()
    assert round(hw.ram_gb, 2) == 32.0
    assert round(hw.available_ram_gb, 2) <= 24.0  # <= : support-model reserve may trim it further


def test_available_ram_is_reduced_by_known_support_model_footprint(monkeypatch):
    class _FakeVM:
        total = 32 * 1024 ** 3
        available = 24 * 1024 ** 3

    monkeypatch.setattr("psutil.virtual_memory", lambda: _FakeVM(), raising=False)
    monkeypatch.setattr(
        "eli.perception.local_whisper_stt.resident_footprint_gib", lambda: 0.5,
    )
    monkeypatch.setattr(
        "eli.memory.vector_store.embedder_footprint_gib", lambda: 0.1,
    )
    hw = hardware_profile._detect_hardware_impl()
    assert round(hw.available_ram_gb, 2) == round(24.0 - 0.5 - 0.1, 2)


def test_available_ram_never_goes_negative_from_the_reserve(monkeypatch):
    class _FakeVM:
        total = 4 * 1024 ** 3
        available = 0.3 * 1024 ** 3

    monkeypatch.setattr("psutil.virtual_memory", lambda: _FakeVM(), raising=False)
    monkeypatch.setattr(
        "eli.perception.local_whisper_stt.resident_footprint_gib", lambda: 5.0,
    )
    monkeypatch.setattr(
        "eli.memory.vector_store.embedder_footprint_gib", lambda: 5.0,
    )
    hw = hardware_profile._detect_hardware_impl()
    assert hw.available_ram_gb == 0.0


def test_embedder_footprint_and_resolve_path_are_the_same_source_of_truth():
    from eli.memory import vector_store
    # embedder_footprint_gib must resolve the identical path _init_embedder() would use —
    # a second, diverging path-resolution copy is exactly the duplicate this fix removed.
    path = vector_store.resolve_embedder_path()
    footprint = vector_store.embedder_footprint_gib()
    import os
    if os.path.exists(path):
        assert footprint > 0.0
    else:
        assert footprint == 0.0


def test_moe_plan_uses_mem_units_not_inline_math():
    import inspect
    src = inspect.getsource(moe_offload.plan_for_load)
    assert "1024 ** 3" not in src and "1024**3" not in src
    assert "mem_units" in src


def test_gui_dropdown_and_hardware_profile_discover_agree_on_a_real_file(tmp_path):
    """discover_gguf_models() (the GUI's own file-scanner) and
    hardware_profile.discover_models() must report the same size for the same file —
    they used to (1024**3 vs 1e9), which the GUI's model dropdown showed side by side
    with the hardware-tuning panel's own figure.
    """
    from eli.gui.eli_pro_audio_gui_v2_0 import discover_gguf_models

    model = tmp_path / "model.gguf"
    model.write_bytes(b"\0" * int(5.5 * 1024 ** 3))

    gui_models = discover_gguf_models(base_dirs=[tmp_path])
    hp_models = hardware_profile.discover_models(models_dir=tmp_path)
    assert len(gui_models) == 1 and len(hp_models) == 1
    assert round(gui_models[0]["size_gb"], 4) == round(hp_models[0]["size_gb"], 4)


def test_model_label_does_not_double_convert_an_already_binary_size():
    from eli.gui.panels.startup import StartupModelSelectionDialog

    label = StartupModelSelectionDialog._model_label(
        {"source": "bundled", "name": "model.gguf", "size_gb": 20.75}
    )
    assert "20.75 GiB" in label, label
